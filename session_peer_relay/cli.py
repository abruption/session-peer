"""Explicit opt-in device/relay commands; no background service installation."""
import argparse
import asyncio
import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import signal
import sys

import session_peer as core
from .app import Receiver, pair, exchange
from .identity import private_read, private_write, private_path
from .native import Policy
from .relay import Relay, RelayLimits
from .store import Store, Rejected
from .wire import validate_relay_url, direct_address
from .transport_errors import NoAuthenticatedRoute, TransportFailure


def connection_diagnostics(exc):
    if isinstance(exc, NoAuthenticatedRoute):
        return {'routeFailures': exc.route_failures}
    if isinstance(exc, TransportFailure):
        return {'connectionFailure': exc.diagnostic()}
    return {}


def state_path(value):
    return Path(value or '~/.local/share/session-peer/device').expanduser().resolve()


def metrics_port(value):
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('invalid metrics port') from exc
    if port != 0 and not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError('invalid metrics port')
    return port


def credential(path):
    if not path:
        return None
    token = private_read(Path(path).expanduser(), 4096).strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        raise Rejected('invalid_admission_file')
    return token


def device_credential(args, store, receiver, role='client'):
    use_login = getattr(args, 'login', False) or getattr(args, 'relay_login', False)
    path = getattr(args, 'admission_file', None) or getattr(args, 'relay_admission_file', None)
    if use_login:
        if path:
            raise Rejected('login_and_static_admission_conflict')
        from .control import DeviceCredential
        return DeviceCredential(store, receiver, role)
    return credential(path)


async def lifetime(seconds):
    event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        loop.add_signal_handler(sig, event.set)
    try:
        if seconds:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(event.wait(), seconds)
        else:
            await event.wait()
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            loop.remove_signal_handler(sig)


def emit(value):
    print(json.dumps({'schemaVersion': 1, **value}, ensure_ascii=False), flush=True)


async def manage(kind, args):
    if kind == 'relay':
        if args.action == 'init-replay':
            from .auth import initialize_replay
            return initialize_replay(args.out)
        if args.action == 'provision':
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', args.room):
                raise Rejected('invalid_room')
            root = Path(args.out).expanduser()
            root.mkdir(mode=0o700, parents=True, exist_ok=False)
            accounts = []
            for role in ('receiver', 'client'):
                token = secrets.token_urlsafe(32)
                private_write(root/(role+'.token'), token+'\n')
                accounts.append({'role': role, 'room': args.room, 'hash': hashlib.sha256(token.encode()).hexdigest()})
            private_write(root/'accounts.json', json.dumps(accounts))
            return {'ok': True, 'provisioned': True, 'directory': str(root)}
        control = None
        if args.auth_state:
            from .auth import ControlAdmission
            if not args.auth_issuer:
                raise Rejected('auth_issuer_required')
            if not args.auth_replay_state:
                raise Rejected('auth_replay_state_required')
            control = ControlAdmission(args.auth_state, args.auth_issuer, args.auth_replay_state)
            control.state()
        accounts = json.loads(private_read(args.accounts, systemd_credentials=True)) if args.accounts else []
        if not control and (not isinstance(accounts, list) or not 1 <= len(accounts) <= 128
                or any(not isinstance(a, dict) or set(a) != {'role', 'room', 'hash'}
                       or a['role'] not in ('receiver', 'client')
                       or not isinstance(a['room'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', a['room'])
                       or not isinstance(a['hash'], str) or not re.fullmatch(r'[a-f0-9]{64}', a['hash']) for a in accounts)):
            raise Rejected('invalid_admission_accounts')
        try:
            limits = RelayLimits(
                handshake_rate=args.handshake_rate,
                pending_sessions=args.pending_sessions,
                global_connections=args.global_connections,
                user_connections=args.user_connections,
                device_connections=args.device_connections,
                connection_byte_budget=args.connection_byte_budget,
            ).validate()
        except ValueError as exc:
            if control:
                control.close()
            raise Rejected(str(exc)) from None
        if args.metrics_port and args.metrics_port == args.port:
            if control:
                control.close()
            raise Rejected('invalid_relay_metrics_port')
        relay = Relay(accounts, control=control, limits=limits,
                      diagnostic_events=getattr(args, 'diagnostic_events', False))
        try:
            server = await relay.start(args.bind, args.port)
        except BaseException:
            if control:
                control.close()
            raise
        metrics_server = None
        try:
            metrics_server = await relay.start_metrics(args.metrics_port) if args.metrics_port else None
            emit({'ok': True, 'ready': True, 'port': server.sockets[0].getsockname()[1]})
            await lifetime(args.seconds)
        finally:
            server.close(); await server.wait_closed()
            if metrics_server:
                metrics_server.close(); await metrics_server.wait_closed()
            if control:
                control.close()
        return {'ok': True, 'stopped': True, 'frames': relay.forwarded_frames, 'rejected': relay.rejected}
    if args.action == 'restore':
        from .lifecycle import restore
        return restore(args.backup, args.state)
    if args.action.startswith('recovery-'):
        from . import recovery
        if args.action in ('recovery-begin', 'recovery-activate'):
            old_path, new_path = state_path(args.state), state_path(args.new_state)
            if old_path == new_path or old_path in new_path.parents or new_path in old_path.parents:
                raise Rejected('recovery_states_must_be_separate')
            old = Store(old_path, exclusive=True)
            try:
                fresh = Store(new_path, exclusive=True)
                try:
                    if args.action == 'recovery-begin':
                        return recovery.begin(old, fresh, args.operation_id)
                    return recovery.activate(old, fresh)
                finally:
                    fresh.close()
            finally:
                old.close()
        store = Store(state_path(args.state), exclusive=True)
        try:
            if args.action == 'recovery-status':
                return recovery.status(store)
            if args.action == 'recovery-reconcile':
                return recovery.reconcile(store, args.operation_id, args.direction,
                                          args.peer, args.request_id, args.classification)
            if args.action == 'recovery-request':
                routes = {}
                if args.direct:
                    direct_address(args.direct); routes['direct'] = args.direct
                if args.relay:
                    validate_relay_url(args.relay); routes['relay'] = args.relay
                if not routes:
                    raise Rejected('route_required')
                private_write(args.out, json.dumps(recovery.peer_request(store, args.peer, routes)))
                return {'ok': True, 'recoveryRequestSaved': True, 'peer': args.peer}
            if args.action == 'recovery-approve':
                request = json.loads(private_read(args.request))
                response = recovery.peer_approve(store, request)
                private_write(args.out, json.dumps(response))
                return {'ok': True, 'recoveryApprovalSaved': True,
                        'newPrincipal': response['newPrincipal']}
            if args.action == 'recovery-commit':
                return recovery.peer_commit(store, json.loads(private_read(args.approval)))
            if args.action == 'recovery-fence':
                from .control import recover
                plan = recovery._load(store)
                if not plan['control']['required']:
                    raise Rejected('control_fence_not_required')
                receipt = recover(store, plan['oldPrincipal'], args.name,
                                  plan['control']['operationId'])
                return recovery.record_control(store, receipt)
            raise Rejected('invalid_command')
        finally:
            store.close()
    store = Store(state_path(args.state), exclusive=args.action in ('rotate', 'backup'))
    try:
        if args.action == 'init':
            return {'ok': True, 'device': store.device}
        if args.action == 'login':
            from .control import login
            return await login(store, args.server, args.no_browser)
        if args.action == 'enroll':
            from .control import enroll
            return enroll(store, args.name, args.operation_id)
        if args.action == 'diagnostics':
            from .lifecycle import diagnostics
            return diagnostics(store)
        if args.action == 'backup':
            from .lifecycle import backup
            return backup(store, args.out, args.policy)
        if args.action == 'rotate':
            from .rotation import rotate
            if args.login and args.admission_file:
                raise Rejected('login_and_static_admission_conflict')
            return await rotate(store, args.operation_id, args.route, credential(args.admission_file), use_login=args.login)
        if args.action == 'rotation-status':
            row = store.db.execute('SELECT value FROM metadata WHERE key="local_rotation"').fetchone()
            saved = json.loads(row[0]) if row else None
            return {'ok': True, 'device': store.device, 'generation': store.generation,
                    'keyFingerprint': store.key_id, 'rotation': saved['status'] if saved else 'none',
                    'operationId': saved['proposal']['id'] if saved else None}
        if args.action == 'peers':
            return {'ok': True, 'device': store.device, 'peers': [
                {'device': row[0], 'status': row[1]} for row in store.db.execute('SELECT id,status FROM peers ORDER BY id')]}
        if args.action == 'revoke':
            store.revoke(args.peer)
            return {'ok': True, 'revoked': args.peer}
        if args.action in ('invite', 'routes'):
            routes = {}
            if args.direct:
                direct_address(args.direct)
                routes['direct'] = args.direct
            if args.relay:
                validate_relay_url(args.relay); routes['relay'] = args.relay
            if not routes:
                raise Rejected('route_required')
            if args.action == 'routes':
                peer = store.peer(args.peer)
                if not peer or peer['status'] != 'paired':
                    raise Rejected('unpaired_device')
                store.db.execute('UPDATE peers SET routes=? WHERE id=?', (json.dumps(routes), args.peer))
                return {'ok': True, 'device': args.peer, 'routes': routes, 'identityChanged': False}
            private_write(args.out, json.dumps(store.invite(routes)))
            return {'ok': True, 'invitationSaved': True, 'device': store.device, 'expiresInSeconds': 600}
        if args.action == 'pair':
            invitation = json.loads(private_read(args.invite))
            return await pair(store, invitation, args.route, device_credential(args, store, invitation['device']))
        if args.action == 'status':
            return await exchange(store, args.peer, 'status', args.request_id, route=args.route,
                                  credential=device_credential(args, store, args.peer))
        if args.action == 'serve':
            import fcntl
            lock_fd = os.open(store.root/'receiver.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(lock_fd, 'w') as receiver_lock:
                private_path(store.root/'receiver.lock')
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    receiver_lock.close()
                    raise Rejected('receiver_already_running') from None
                policy = json.loads(private_read(args.policy))
                receiver = Receiver(store, policy,
                                    diagnostic_events=getattr(args, 'diagnostic_events', False))
                # Never create a public listener merely because a relay is configured.
                server = await receiver.listen(args.bind, args.port)
                task = None
                try:
                    if args.relay:
                        validate_relay_url(args.relay)
                        token = device_credential(args, store, store.device, 'receiver')
                        if not token:
                            raise Rejected('admission_file_required')
                        task = asyncio.create_task(receiver.relay_listener(args.relay, token))
                    emit({'ok': True, 'ready': True, 'device': store.device,
                          'directPort': server.sockets[0].getsockname()[1],
                          'relayConfigured': bool(task), 'relayReadyConfirmed': False})
                    await lifetime(args.seconds)
                finally:
                    if task:
                        task.cancel(); await asyncio.gather(task, return_exceptions=True)
                    server.close(); await server.wait_closed(); await receiver.close()
                    receiver_lock.close()
                return {'ok': True, 'stopped': True}
        raise Rejected('invalid_command')
    finally:
        store.close()


def parser(kind):
    p = argparse.ArgumentParser(prog='session-peer '+kind)
    sub = p.add_subparsers(dest='action', required=True)
    def command(name, state=True):
        item = sub.add_parser(name)
        if state:
            item.add_argument('--state')
        return item
    def server_options(item):
        item.add_argument('--bind', default='127.0.0.1')
        item.add_argument('--port', type=int, default=0)
        item.add_argument('--seconds', type=int, choices=range(0, 86401), default=3600, metavar='SECONDS')
    if kind == 'relay':
        item = command('init-replay', False); item.add_argument('--out', required=True)
        item = command('provision', False)
        item.add_argument('--out', required=True); item.add_argument('--room', default='private')
        item = command('serve', False)
        source = item.add_mutually_exclusive_group(required=True)
        source.add_argument('--accounts'); source.add_argument('--auth-state')
        item.add_argument('--auth-issuer'); item.add_argument('--auth-replay-state'); server_options(item)
        item.add_argument('--handshake-rate', type=int, default=20)
        item.add_argument('--pending-sessions', type=int, default=100)
        item.add_argument('--global-connections', type=int, default=10)
        item.add_argument('--user-connections', type=int, default=8)
        item.add_argument('--device-connections', type=int, default=4)
        item.add_argument('--connection-byte-budget', type=int, default=32*1024*1024)
        item.add_argument('--metrics-port', type=metrics_port, default=0, metavar='PORT')
        item.add_argument('--diagnostic-events', action='store_true')
        return p
    command('init'); command('peers')
    item = command('login'); item.add_argument('--server', required=True); item.add_argument('--no-browser', action='store_true')
    item = command('enroll'); item.add_argument('--name', required=True); item.add_argument('--operation-id', required=True)
    command('diagnostics')
    item = command('backup'); item.add_argument('--out', required=True); item.add_argument('--policy', required=True)
    item = command('restore', False); item.add_argument('--state', required=True); item.add_argument('--backup', required=True)
    item = command('recovery-begin'); item.add_argument('--new-state', required=True)
    item.add_argument('--operation-id', required=True)
    command('recovery-status')
    item = command('recovery-reconcile'); item.add_argument('--operation-id', required=True)
    item.add_argument('--direction', choices=('native', 'outgoing'), required=True)
    item.add_argument('--peer', required=True); item.add_argument('--request-id', required=True)
    item.add_argument('--classification', choices=('already_processed', 'not_processed', 'unknown'), required=True)
    item = command('recovery-request'); item.add_argument('--peer', required=True)
    item.add_argument('--out', required=True); item.add_argument('--direct'); item.add_argument('--relay')
    item = command('recovery-approve'); item.add_argument('--request', required=True); item.add_argument('--out', required=True)
    item = command('recovery-commit'); item.add_argument('--approval', required=True)
    item = command('recovery-fence'); item.add_argument('--name', required=True)
    item = command('recovery-activate'); item.add_argument('--new-state', required=True)
    command('rotation-status')
    item = command('rotate'); item.add_argument('--operation-id', required=True)
    item.add_argument('--login', action='store_true')
    item.add_argument('--route', choices=('auto', 'direct', 'relay'), default='auto')
    item.add_argument('--admission-file')
    item = command('invite'); item.add_argument('--out', required=True)
    item.add_argument('--direct'); item.add_argument('--relay')
    item = command('routes'); item.add_argument('--peer', required=True)
    item.add_argument('--direct'); item.add_argument('--relay')
    item = command('serve'); item.add_argument('--policy', required=True)
    item.add_argument('--login', action='store_true')
    item.add_argument('--diagnostic-events', action='store_true')
    item.add_argument('--relay'); item.add_argument('--admission-file'); server_options(item)
    item = command('revoke'); item.add_argument('--peer', required=True)
    for name in ('pair', 'status'):
        item = command(name)
        if name == 'pair':
            item.add_argument('--invite', required=True)
        else:
            item.add_argument('--peer', required=True); item.add_argument('--request-id', required=True)
        item.add_argument('--route', choices=('direct', 'relay') if name == 'pair' else ('auto', 'direct', 'relay'), default='direct' if name == 'pair' else 'auto')
        item.add_argument('--admission-file')
        item.add_argument('--login', action='store_true')
    return p


def main(kind, argv):
    args = parser(kind).parse_args(argv)
    logging.getLogger('websockets').setLevel(logging.CRITICAL+1)
    os.umask(0o077)
    try:
        result = asyncio.run(manage(kind, args))
    except Exception as exc:
        result = {'ok': False, 'reason': str(exc) if isinstance(exc, Rejected) else type(exc).__name__,
                  'retryAllowed': False, **connection_diagnostics(exc)}
    emit(result)
    return 0 if result.get('ok') else 1


async def core_exchange(args):
    if any(getattr(args, key, None) for key in ('codex_home', 'codex_bin', 'antigravity_home', 'antigravity_generation', 'ssh_opt')):
        raise Rejected('device_native_options_are_receiver_policy_only')
    if args.host:
        raise Rejected('device_and_ssh_are_mutually_exclusive')
    if not re.fullmatch(r'[a-f0-9]{64}', args.device):
        raise Rejected('invalid_device')
    if args.command == 'send' and (args.wake or args.reply_to or args.b64):
        raise Rejected('device_send_option_unsupported')
    store = Store(state_path(args.device_state))
    try:
        body = None
        if args.command == 'send':
            text = core.read_message(args)
            core.check_message(text, remote=False)
            if not args.no_from:
                text = core.wrap_message(text, with_from=True, with_reply=False, explicit_host=None)
            body = {'target': args.to, 'message': text}
        operation = 'resolve' if args.command == 'send' and args.dry_run else args.command
        result = await exchange(store, args.device, operation, body,
                                getattr(args, 'request_id', None), args.device_route,
                                device_credential(args, store, args.device))
        if args.command == 'list' and args.agent:
            result['sessions'] = [row for row in result.get('sessions', []) if row.get('agent') == args.agent]
        return result
    finally:
        store.close()


def invoke_core(args):
    os.umask(0o077)
    try:
        result = asyncio.run(core_exchange(args))
    except Exception as exc:
        result = {'ok': False, 'reason': str(exc) if isinstance(exc, Rejected) else type(exc).__name__,
                  'retryAllowed': False, 'consumptionConfirmed': False, **connection_diagnostics(exc)}
    result.update(device=args.device, host='device:'+args.device, transport='paired_device')
    human = 'Device result: '+str(result.get('status', 'ok' if result.get('ok') else result.get('reason')))
    if args.command == 'list':
        human += '\nTARGET  AGENT  ID  STATUS\n' + '\n'.join(
            str(row.get('target', ''))+'  '+str(row.get('agent', ''))+'  '+str(row.get('id', row.get('pid', '')))+'  '+str(row.get('status', 'unknown'))
            for row in result.get('sessions', []))
    core.emit(args.json, result, human, command=args.command)
    return 0 if result.get('ok') else 1
