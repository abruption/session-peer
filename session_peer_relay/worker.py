"""Internal bounded native worker. No network-provided executable or arguments."""
import argparse
import json
import sys

import session_peer as core
from .native import Policy, options, invoke_windows_codex
from .framing import MAX_WORKER_BYTES, valid_text, valid_delivery_context


def delivery_context(binding, adapter, result):
    """Use the executing registry and actual native resolution, never guessed homes."""
    agent = binding['agent']
    target = None
    native_target = result.get('target')
    if result.get('ok') is True:
        if isinstance(native_target, dict):
            identifier = native_target.get('pid' if agent == 'claude' else 'id')
            if (agent == 'claude' and type(identifier) is int and identifier > 0
                    or agent != 'claude' and isinstance(identifier, str) and identifier):
                # Claude's public CLI adapter uses an unprefixed PID, whereas
                # this private cross-agent context always carries an agent tag.
                target = agent + ':' + str(identifier).lower()
    home = result.get('codexHome' if agent == 'codex' else 'antigravityHome') if agent != 'claude' else None
    value = {'schemaVersion': 1, 'agent': agent, 'target': target, 'home': home,
             'capabilities': {key: getattr(adapter.capabilities, key)
                              for key in ('send', 'wake', 'wait', 'ack')}}
    return value if valid_delivery_context(value) else None


def main():
    attempted = False
    explain = False
    binding = adapter = None
    try:
        raw = sys.stdin.buffer.read(MAX_WORKER_BYTES + 1)
        if len(raw) > MAX_WORKER_BYTES:
            raise ValueError('native_worker_frame_too_large')
        value = json.loads(raw.decode('utf-8'))
        binding, op, text = value['binding'], value['operation'], value.get('text')
        peer_fingerprint = value.get('peerFingerprint')
        Policy({'targets': {'endpoint': binding}, 'peers': {}})
        if op not in ('list', 'send', 'resolve'):
            raise ValueError('invalid_operation')
        if 'explain' in value and (op != 'resolve' or value['explain'] is not True):
            raise ValueError('invalid_explain')
        explain = value.get('explain') is True
        adapter = core.AGENTS.get(binding['agent'])
        args = options(binding)
        args._peer_fingerprint = peer_fingerprint
        if op in ('send', 'resolve'):
            if not valid_text(text) or not valid_text(
                    core.peer_delivery_message(text, binding['agent'], peer_fingerprint)):
                raise ValueError('invalid_framed_message')
        if binding.get('codexPython') is not None:
            result = invoke_windows_codex(binding, op, text, peer_fingerprint)
        elif op in ('send', 'resolve'):
            args.dry_run = op == 'resolve'
            if not valid_text(text):
                raise ValueError('invalid_message')
            adapter.validate_send(args, text)
            if binding['agent'] == 'codex':
                try:
                    core.codex_executable(args)
                except core.CcPeerError as exc:
                    raise core.CcPeerError('Codex executable unavailable',
                                           {'reason': 'codex_executable_not_found'}) from exc
            if op == 'send':
                preview = argparse.Namespace(**vars(args))
                preview.dry_run = True
                preview_result = core.LocalTransport().execute('send', adapter, preview, text)
                if preview_result.get('ok') is not True:
                    raise core.CcPeerError('Native preflight refused', {'reason': 'native_refused'})
            # Everything above is read-only. After this point, a delivery may
            # have started; any ambiguous outcome must remain unknown.
            attempted = op == 'send'
            result = core.LocalTransport().execute('send', adapter, args, text)
            result['consumptionConfirmed'] = False
            result.setdefault('submitted', result.get('ok') is True and not args.dry_run)
            result.setdefault('status', 'dry_run' if args.dry_run else ('submitted' if result.get('ok') else 'unknown'))
        else:
            found = core.LocalTransport().execute('list', adapter, args)
            ident = adapter.identity(binding['target'], core.ExecutionContext('local', args)).identifier
            rows = [row for row in found['sessions'] if (
                str(row.get('id')) == ident if binding['agent'] != 'claude'
                else str(row.get('pid')) == ident or row.get('name') == ident)]
            result = {'ok': found['discovery']['status'] != 'error', 'sessions': rows,
                      'discovery': {binding['agent']: found['discovery']}}
    except core.CcPeerError as exc:
        # Native error text can contain local paths or user content. Codes only.
        allowed = {'codex_executable_not_found', 'native_refused'}
        preflight_reason = exc.details.get('reason', 'native_refused')
        result = {'ok': False, 'reason': 'native_outcome_unknown' if attempted else (
                      preflight_reason if preflight_reason in allowed else 'native_refused'),
                  'status': 'unknown' if attempted else 'refused', 'consumptionConfirmed': False, 'retryAllowed': False}
    except Exception:
        result = {'ok': False, 'reason': 'native_outcome_unknown' if attempted else 'native_refused',
                  'status': 'unknown' if attempted else 'refused',
                  'consumptionConfirmed': False, 'retryAllowed': False}
    if explain and adapter is not None:
        context = delivery_context(binding, adapter, result)
        if context is not None:
            result['deliveryContext'] = context
    encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded.encode()) > 60*1024 and 'deliveryContext' in result:
        # Optional explanation metadata cannot erase independently usable
        # native facts merely by taking the result over the legacy byte cap.
        result.pop('deliveryContext', None)
        encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded.encode()) > 60*1024:
        encoded = json.dumps({'ok': False, 'reason': 'native_result_too_large',
                              'status': 'unknown', 'retryAllowed': False, 'consumptionConfirmed': False})
    print(encoded)


if __name__ == '__main__':
    main()
