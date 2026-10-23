"""Watch argument bounds fail before ledger or process access."""
import contextlib
import io
import unittest
from unittest import mock

import session_peer as peer


CORRELATION = "00000000-0000-4000-8000-000000000001"


class HandoffWatchCli(unittest.TestCase):
    def test_unsupported_platform_is_explicit_before_history_access(self):
        output = io.StringIO()
        with mock.patch.object(peer, 'IS_WINDOWS', True), contextlib.redirect_stdout(output), \
                mock.patch.object(peer, 'HandoffLedger', side_effect=AssertionError('history accessed')):
            code = peer.main(['handoff', 'watch', '--correlation-id', CORRELATION, '--json'])
        self.assertEqual(code, 1)
        import json
        result = json.loads(output.getvalue())
        self.assertEqual(result['reason'], 'unsupported')
        self.assertNotIn('handoff', result)
        self.assertNotIn('ledgerEpoch', result)

    def test_defaults_and_explicit_bounds(self):
        args = peer.build_parser().parse_args(['handoff', 'watch', '--correlation-id', CORRELATION])
        self.assertIs(args.func, peer.cmd_handoff_watch)
        self.assertTrue(args.no_update_notice)
        self.assertEqual((args.watch_timeout, args.interval_ms), (30, 1000))
        args = peer.build_parser().parse_args(['handoff', 'watch', '--correlation-id', CORRELATION,
                                               '--watch-timeout', '60', '--interval-ms', '5000', '--json'])
        self.assertEqual((args.watch_timeout, args.interval_ms, args.json), (60, 5000, True))

    def test_invalid_options_never_touch_history_or_start_processes(self):
        cases = [(flag, value) for flag, values in (
            ('--watch-timeout', ('0', '61', '-1', '1.0', '1e0', '+1', '１')),
            ('--interval-ms', ('999', '5001', '1e3', '1000.0', '-1000', '+1000', '１０００')),
            ('--host', ('fixture',)), ('--wait-for', ('acknowledged',)),
        ) for value in values]
        cases.append(('--correlation-id', 'invalid'))
        for flag, value in cases:
            with self.subTest(flag=flag, value=value), \
                    contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()), \
                    mock.patch.object(peer, 'HandoffLedger', side_effect=AssertionError('history accessed')), \
                    mock.patch.object(peer.subprocess, 'Popen', side_effect=AssertionError('process started')), \
                    mock.patch.object(peer.subprocess, 'run', side_effect=AssertionError('process started')):
                with self.assertRaises(SystemExit) as result:
                    peer.main(['handoff', 'watch', '--correlation-id', CORRELATION, flag, value])
                self.assertEqual(result.exception.code, 2)
