"""Opt-in setup orchestrator. Plan/target inventory never constructs Store.

No package installation, background service registration, native message send,
agent approval or uncertain-message retry is part of this workflow.
"""
import argparse
import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import tempfile
import time
import uuid

import session_peer as core
from . import control
from .app import pair, exchange
from .cli import manage, parser, state_path
from .identity import private_path, private_read, private_write, fingerprint
from .native import Policy
from .store import Store, Rejected
from .wire import direct_address, validate_relay_url


def document(path):
    return json.loads(private_read(path))


def digest(path):
    return hashlib.sha256(private_read(path).encode()).hexdigest()


def inventory(root, policy=None):
    """No initialization/migration or SQLite WAL/shared-memory creation.

    immutable reads only a checkpointed diagnostic view. It is explicitly not
    authority for enrollment/pairing; approved actions recheck a live Store.
    """
    result = {'stateExists': root.exists(), 'receiverRunning': False,
              'autostartManaged': False, 'serviceDiscoveryComplete': False,
              'existingServiceFiles': [str(path) for path in (
                  Path('/etc/systemd/system/session-peer-receiver.service'),
                  Path.home()/'.config/systemd/user/session-peer-receiver.service',
                  Path.home()/'Library/LaunchAgents/dev.abruption.session-peer-receiver.plist') if path.exists()],
              'databaseView': 'checkpointed_diagnostic_only'}
    if root.exists() or root.is_symlink():
        private_path(root, True)
        result['existingFiles'] = [name for name in (
            'identity.pem', 'identity.key', 'device.sqlite', 'login.json',
            'setup.json', 'receiver.lock', 'restore-incomplete') if (root/name).exists()]
        for name in ('identity.pem', 'identity.key', 'device.sqlite', 'login.json', 'setup.json', 'receiver.lock'):
            if (root/name).exists() or (root/name).is_symlink():
                private_path(root/name)
        if (root/'login.json').exists():
            login = document(root/'login.json')
            expiry = login.get('expiresAt')
            result['login'] = 'valid_locally' if type(expiry) in (int, float) and expiry > time.time() else 'expired'
        if (root/'device.sqlite').exists():
            db = sqlite3.connect((root/'device.sqlite').as_uri()+'?mode=ro&immutable=1', uri=True)
            try:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='peers'").fetchone():
                    result['peers'] = [{'device': ident, 'status': state} for ident, state in
                                       db.execute('SELECT id,status FROM peers LIMIT 129')]
            finally:
                db.close()
        if (root/'receiver.lock').exists():
            with os.fdopen(os.open(root/'receiver.lock', os.O_RDONLY | os.O_NOFOLLOW), 'rb') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    result['receiverRunning'] = True
    if policy and (policy.exists() or policy.is_symlink()):
        result['policyExists'] = True
        result['policyDigest'] = digest(policy)
    return result


def exclusive_file(path, text):
    """Publish a complete private file only if absent; never overwrite."""
    private_path(path.parent, True)
    fd, temporary = tempfile.mkstemp(prefix='.setup-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.link(temporary, path, follow_symlinks=False)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)


def binding_identity(store):
    return {'principal': store.device, 'generation': store.generation, 'keyFingerprint': store.key_id}


class Workflow:
    def __init__(self, root):
        self.root = root
        self.path = root/'setup.json'
        self.saved = document(self.path) if self.path.exists() else {'schemaVersion': 1, 'phases': {}}
        if (not isinstance(self.saved, dict) or self.saved.get('schemaVersion') != 1
                or not isinstance(self.saved.get('phases'), dict)):
            raise Rejected('invalid_setup_journal')
        self.expected = digest(self.path) if self.path.exists() else None

    def save(self):
        current = digest(self.path) if self.path.exists() else None
        if current != self.expected:
            raise Rejected('setup_journal_changed')
        text = json.dumps(self.saved, sort_keys=True)
        if current is None:
            exclusive_file(self.path, text)
        else:
            private_write(self.path, text)
        self.expected = hashlib.sha256(text.encode()).hexdigest()

    def phase(self, action, state):
        self.saved['phases'][action] = state
        self.save()

    def attach(self, store):
        identity = binding_identity(store)
        if self.saved.get('identity', identity) != identity:
            raise Rejected('setup_identity_changed')
        self.saved['identity'] = identity


@contextlib.contextmanager
def mutation(root):
    private_path(root, True)
    fd = os.open(root/'setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        private_path(root/'setup.lock')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Rejected('setup_busy') from None
        yield Workflow(root)


def targets(args):
    view = argparse.Namespace(**vars(args))
    view.all = False
    view.agent = None
    rows = core.collect_listing(view)
    return {'ok': rows.get('ok', True), 'sessions': rows['sessions'], 'discovery': rows.get('discovery', {})}


def selected_binding(args):
    if not args.target or not args.peer or not re.fullmatch(r'[a-f0-9]{64}', args.peer):
        raise Rejected('setup_target_and_peer_required')
    adapter = core.AGENTS.for_target(args.target)
    rows = targets(args)['sessions']
    identifier = args.target.removeprefix(adapter.name+':') if adapter.name != 'claude' else args.target
    matches = [row for row in rows if row['agent'] == adapter.name and
               str(row.get('pid') if adapter.name == 'claude' else row.get('id')) == identifier and
               (adapter.name != 'codex' or not args.codex_home or row.get('codexHome') == str(Path(args.codex_home).expanduser().resolve()))]
    if len(matches) != 1:
        raise Rejected('setup_target_missing_or_ambiguous')
    row = matches[0]
    binding = {'agent': adapter.name, 'target': args.target}
    if adapter.name == 'codex':
        binding['codexHome'] = str(Path(row['codexHome']).expanduser().resolve())
        check = argparse.Namespace(codex_bin=args.codex_bin)
        binding['codexBin'] = core.codex_executable(check)
    if adapter.name == 'antigravity':
        binding['antigravityHome'] = row.get('antigravityHome') or args.antigravity_home
    probe = core.build_parser().parse_args(['send', '--to', args.target, '--dry-run', '--no-from', '--no-reply-to'])
    probe.codex_home = binding.get('codexHome')
    probe.codex_bin = binding.get('codexBin')
    probe.antigravity_home = binding.get('antigravityHome')
    # Existing native dry-run is read-only, never wake or model invocation.
    result = core.LocalTransport().execute('send', adapter, probe, 'setup metadata preflight')
    if result.get('ok') is not True:
        raise Rejected('setup_target_not_ready')
    snapshot = {key: row.get(key) for key in (
        'agent', 'id', 'pid', 'startedAt', 'codexHome', 'antigravityHome', 'generation')}
    if getattr(args, '_chosen_setup_target', snapshot) != snapshot:
        raise Rejected('setup_target_changed')
    return binding, snapshot


def policy_preview(args):
    binding, snapshot = selected_binding(args)
    rights = sorted(set(args.capability or ['list']))
    value = {'targets': {args.alias: binding}, 'peers': {
        args.peer: {'capabilities': rights, 'targets': [args.alias]}}}
    Policy(value)
    return value, snapshot


def receiver_command(args, root, policy):
    argv = ['session-peer', 'device', 'serve', '--state', str(root), '--policy', str(policy),
            '--seconds', str(args.seconds)]
    if args.relay:
        validate_relay_url(args.relay)
        argv += ['--relay', args.relay, '--login']
    if args.direct:
        host, port = direct_address(args.direct)
        argv += ['--bind', host, '--port', str(port)]
    return argv


async def execute(args):
    root = Path(args.state or '~/.local/share/session-peer/device').expanduser().absolute()
    policy = Path(args.policy).expanduser().absolute() if args.policy else root/'receiver-policy.json'
    if args.host or args.ssh_opt:
        raise Rejected('relay_setup_ssh_options_conflict')
    current = inventory(root, policy)
    if args.action == 'plan':
        return {'ok': True, 'mode': 'relay', 'inventory': current,
                'installation': core.relay_install_guidance(), 'changed': False,
                'nextAction': 'Use --interactive, or select --action and approve each mutation with --apply. No dependencies or services are installed.'}
    if args.action == 'targets':
        return {**targets(args), 'metadataOnly': True}
    if args.action == 'policy':
        preview, selected = policy_preview(args)
        if not args.apply:
            return {'ok': True, 'policyPreview': preview, 'selectedTarget': selected, 'changed': False,
                    'policyPath': str(policy), 'nextAction': 'Review the exact peer, target/path and capabilities; repeat with --apply to create a new policy only.'}
    if not args.apply:
        raise Rejected('setup_explicit_apply_required')
    if args.action == 'init':
        # Existing files were checked above. Partial identity must never cause
        # silent regeneration; Store has the existing key-pair consistency gate.
        store = Store(root)
        try:
            with mutation(root) as work:
                work.attach(store)
                work.phase('init', 'complete')
                return {'ok': True, 'device': store.device, 'state': str(root), 'preservedExistingIdentity': current['stateExists']}
        finally:
            store.close()
    if not root.exists() or not (root/'identity.pem').exists() or not (root/'device.sqlite').exists():
        raise Rejected('setup_init_required')
    with mutation(root) as work:
        if args.action == 'cancel':
            work.saved['cancelled'] = True
            work.save()
            return {'ok': True, 'cancelled': True, 'operationCancelled': False,
                    'nextAction': 'No enrollment/send was rolled back. Resume the same enrollment intent explicitly; stop a foreground receiver with Ctrl-C.'}
        store = Store(root)
        try:
            work.attach(store)
            if args.action == 'login':
                if not args.server:
                    raise Rejected('setup_server_required')
                control.origin(args.server)
                work.phase('login', 'pending')
                result = await control.login(store, args.server, args.no_browser)
                work.phase('login', 'complete')
                return result
            if args.action == 'enroll':
                login = control.session(store)
                if not args.name or not 1 <= len(args.name) <= 64 or any(ord(c) < 32 for c in args.name):
                    raise Rejected('invalid_device_name')
                intent = {'server': login['server'], 'name': args.name, 'identity': binding_identity(store)}
                saved = work.saved.get('enrollment')
                if saved and saved.get('intent') != intent:
                    raise Rejected('setup_enrollment_intent_changed')
                if not saved:
                    saved = {'operationId': str(uuid.uuid4()), 'intent': intent, 'state': 'prepared'}
                    saved['payload'] = control.enrollment_payload(store, args.name, saved['operationId'])
                    work.saved['enrollment'] = saved
                    work.save()  # Durable original UUID/identity before any network mutation.
                if saved.get('payload') != control.enrollment_payload(store, args.name, saved['operationId']):
                    # DER identity alone does not fence the Control API's exact
                    # canonical payload digest. Even PEM whitespace is material.
                    raise Rejected('setup_enrollment_payload_changed')
                if saved['state'] == 'committed':
                    return {'ok': True, **saved['receipt'], 'reconciled': True}
                saved['state'] = 'unknown'
                work.save()
                result = control.enroll(store, args.name, saved['operationId'])
                saved.update(state='committed', receipt={key: result[key] for key in (
                    'operationId', 'principal', 'keyFingerprint', 'keyGeneration', 'committed')})
                work.phase('enroll', 'complete')
                return {'ok': True, **saved['receipt']}
            if args.action == 'policy':
                # Discovery/identity is checked a second time after taking the
                # setup lock. A stale/ambiguous selection cannot be applied.
                if (preview, selected) != policy_preview(args):
                    raise Rejected('setup_target_changed')
                if policy.exists() or policy.is_symlink():
                    if document(policy) != preview:
                        raise Rejected('setup_existing_policy_preserved')
                    changed = False
                else:
                    exclusive_file(policy, json.dumps(preview, indent=2))
                    changed = True
                work.phase('policy', 'complete')
                return {'ok': True, 'policyPath': str(policy), 'policyPreview': preview,
                        'changed': changed, 'receiverCommand': shlex.join(receiver_command(args, root, policy))}
            if args.action == 'invite':
                if not args.out or not args.relay and not args.direct:
                    raise Rejected('setup_invitation_path_and_route_required')
                output = Path(args.out).expanduser().absolute()
                if output.exists() or output.is_symlink() or work.saved['phases'].get('invite') == 'pending':
                    raise Rejected('setup_invitation_reconcile_required')
                routes = {}
                if args.relay:
                    validate_relay_url(args.relay); routes['relay'] = args.relay
                if args.direct:
                    direct_address(args.direct); routes['direct'] = args.direct
                private_path(output.parent, True)
                work.phase('invite', 'pending')
                invitation = store.invite(routes)
                exclusive_file(output, json.dumps(invitation))
                work.phase('invite', 'complete')
                return {'ok': True, 'invitationSaved': True, 'expiresInSeconds': 600,
                        'nextAction': 'Transfer this private file securely to the client; do not paste its secret in logs or chat.'}
            if args.action == 'pair':
                if not args.invite:
                    raise Rejected('setup_invitation_required')
                path = Path(args.invite).expanduser().absolute()
                invitation = document(path)
                saved = work.saved.get('pairing')
                intent = {'invitationDigest': digest(path), 'device': invitation['device'], 'route': args.route}
                if saved and saved != intent:
                    raise Rejected('setup_pairing_intent_changed')
                work.saved['pairing'] = intent
                work.phase('pair', 'pending')
                existing = store.peer(invitation['device'])
                if existing and existing['status'] == 'paired':
                    if fingerprint(existing['certificate']) != fingerprint(invitation['certificate']):
                        raise Rejected('setup_pairing_identity_changed')
                    result = {'ok': True, 'paired': True, 'resumed': True}
                else:
                    credential = control.DeviceCredential(store, invitation['device'], 'client') if 'relay' in invitation['routes'] else None
                    result = await pair(store, invitation, args.route, credential)
                if result.get('ok') is True:
                    work.phase('pair', 'complete')
                return result
            if args.action == 'ready':
                if not args.peer or not re.fullmatch(r'[a-f0-9]{64}', args.peer):
                    raise Rejected('setup_peer_required')
                record = store.peer(args.peer)
                if not record or record['status'] != 'paired':
                    raise Rejected('unpaired_device')
                credential = control.DeviceCredential(store, args.peer, 'client') if 'relay' in record['routes'] else None
                probe = await exchange(store, args.peer, 'probe', route=args.route, credential=credential)
                listed = await exchange(store, args.peer, 'list', route=args.route, credential=credential) if probe.get('ok') is True else None
                return {'ok': bool(probe.get('ok') is True and listed and listed.get('ok') is True),
                        'metadataOnly': True, 'messageSubmitted': False, 'probe': probe, 'listing': listed,
                        'nextAction': 'Readiness is not an ACK, agent permission or hosted availability guarantee. A real message requires separate explicit send consent.'}
            if args.action == 'receiver':
                if current['receiverRunning']:
                    raise Rejected('receiver_already_running')
                Policy(document(policy))
                # Reuse the existing foreground lifetime/lock and stop path;
                # do not register a service, edit a profile or enable autostart.
                argv = receiver_command(args, root, policy)[2:]
                store.close()
                store = None
                return await manage('device', parser('device').parse_args(argv))
            raise Rejected('invalid_setup_action')
        finally:
            if store:
                store.close()


def consent(prompt):
    return input(prompt+' [yes/no]: ').strip().lower() == 'yes'


async def interactive(args):
    def ask(label, default=''):
        answer = input(label+(' ['+default+']' if default else '')+': ').strip()
        return answer or default
    args.state = ask('Private device state directory', args.state or '~/.local/share/session-peer/device')
    args.action = 'plan'
    print(json.dumps(core.human_text(await execute(args)), ensure_ascii=False))
    for action in ('init', 'login', 'enroll'):
        if action == 'login':
            args.server = ask('Control login origin (https://...)', args.server or '')
        if action == 'enroll':
            args.name = ask('Device name', args.name or '')
        if not consent('Approve '+action+' for this state only'):
            return {'ok': False, 'cancelled': True, 'operationCancelled': False}
        args.action, args.apply = action, True
        print(json.dumps(core.human_text(await execute(args)), ensure_ascii=False))
    args.role = ask('Role receiver/client', args.role)
    if args.role == 'receiver':
        args.action, args.apply = 'targets', False
        rows = (await execute(args))['sessions']
        print(json.dumps(core.human_text(rows), ensure_ascii=False))
        index = int(ask('Select target row number (starts at 1)'))-1
        if not 0 <= index < len(rows):
            raise Rejected('setup_target_missing_or_ambiguous')
        row = rows[index]
        args._chosen_setup_target = {key: row.get(key) for key in (
            'agent', 'id', 'pid', 'startedAt', 'codexHome', 'antigravityHome', 'generation')}
        args.target = str(row['pid']) if row['agent'] == 'claude' else row['agent']+':'+row['id']
        args.codex_home = row.get('codexHome')
        args.antigravity_home = row.get('antigravityHome')
        if row['agent'] == 'codex':
            args.codex_bin = ask('Exact Codex executable path (empty uses current PATH)', args.codex_bin or '') or None
        args.peer = ask('Trusted client device principal (obtain from its init result)', args.peer or '')
        args.capability = ['list', 'send'] if consent('Also allow this peer to send to this target') else ['list']
        args.policy = ask('New policy path', args.policy or str(Path(args.state).expanduser()/'receiver-policy.json'))
        args.relay = ask('Receiver WSS /v1/connect URL (empty for direct)', args.relay or '') or None
        if not args.relay:
            args.direct = ask('Private direct address HOST:PORT', args.direct or '')
        args.action = 'policy'
        print(json.dumps(core.human_text(await execute(args)), ensure_ascii=False))
        if not consent('Apply this exact policy without overwriting an existing policy'):
            return {'ok': False, 'cancelled': True, 'operationCancelled': False}
        args.apply = True
        policy_result = await execute(args)
        print(json.dumps(core.human_text(policy_result), ensure_ascii=False))
        args.out = ask('New private invitation file', args.out or str(Path(args.state).expanduser()/'invite.json'))
        if not consent('Create the one-time invitation (securely transfer it within 10 minutes)'):
            return {'ok': False, 'cancelled': True, 'operationCancelled': False}
        args.action = 'invite'
        result = await execute(args)
        result['receiverCommand'] = policy_result['receiverCommand']
        result['nextAction'] = 'Start this foreground receiver in another terminal; Ctrl-C stops it. No service/autostart was installed. Then the client runs setup --role client --interactive.'
        return result
    if args.role != 'client':
        raise Rejected('invalid_setup_role')
    args.invite = ask('Securely received private invitation path', args.invite or '')
    if not consent('Pair with the device certificate and routes in this invitation'):
        return {'ok': False, 'cancelled': True, 'operationCancelled': False}
    args.action = 'pair'
    result = await execute(args)
    if not result.get('ok'):
        return result
    args.peer = document(Path(args.invite).expanduser())['device']
    if not consent('Perform metadata/probe-only readiness check (no message)'):
        return {'ok': True, 'paired': True, 'readinessChecked': False}
    args.action = 'ready'
    return await execute(args)


def run(args):
    os.umask(0o077)
    try:
        return asyncio.run(interactive(args) if args.interactive else execute(args))
    except (KeyboardInterrupt, EOFError):
        return {'ok': False, 'cancelled': True, 'operationCancelled': False, '_exit': 130,
                'nextAction': 'Setup stopped waiting, not rolling back committed operations. Resume enrollment with the same state/name; expired login needs explicit login again.'}
    except Exception as exc:
        # No arbitrary server/body/path/credential error reflection.
        reason = str(exc) if isinstance(exc, Rejected) and re.fullmatch(r'[a-z_]{1,80}', str(exc)) else 'setup_failed'
        return {'ok': False, 'reason': reason, 'retryAllowed': False,
                'nextAction': 'Inspect the private setup journal. Resume the original enrollment intent explicitly; never retry an uncertain native message.'}
