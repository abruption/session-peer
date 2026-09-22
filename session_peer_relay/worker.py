"""Internal bounded native worker. No network-provided executable or arguments."""
import json
import sys

import session_peer as core
from .native import Policy, options, invoke_windows_codex


def main():
    attempted = False
    try:
        value = json.loads(sys.stdin.buffer.read(65537))
        binding, op, text = value['binding'], value['operation'], value.get('text')
        Policy({'targets': {'endpoint': binding}, 'peers': {}})
        if op not in ('list', 'send', 'resolve'):
            raise ValueError('invalid_operation')
        adapter = core.AGENTS.get(binding['agent'])
        args = options(binding)
        if binding.get('codexBin') is not None:
            result = invoke_windows_codex(binding, op, text)
        elif op in ('send', 'resolve'):
            args.dry_run = op == 'resolve'
            if not isinstance(text, str) or not text.strip() or len(text.encode()) > 32768 or '\0' in text:
                raise ValueError('invalid_message')
            adapter.validate_send(args, text)
            attempted = True
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
        result = {'ok': False, 'reason': 'native_outcome_unknown' if attempted else exc.details.get('reason', 'native_refused'),
                  'status': 'unknown' if attempted else 'refused', 'consumptionConfirmed': False, 'retryAllowed': False}
    except Exception:
        result = {'ok': False, 'reason': 'native_outcome_unknown', 'status': 'unknown',
                  'consumptionConfirmed': False, 'retryAllowed': False}
    encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded.encode()) > 60*1024:
        encoded = json.dumps({'ok': False, 'reason': 'native_result_too_large',
                              'status': 'unknown', 'retryAllowed': False, 'consumptionConfirmed': False})
    print(encoded)


if __name__ == '__main__':
    main()
