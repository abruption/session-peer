"""WSL must use a fixed native interpreter, not cross-mount SQLite or flock."""
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

if sys.version_info < (3, 11) or os.name != 'posix':
    raise unittest.SkipTest('optional native relay requires Unix Python 3.11+')
try:
    import cryptography
    import websockets
except ImportError:
    raise unittest.SkipTest('optional relay dependencies not installed')

from session_peer_relay import native


class WindowsBridge(unittest.TestCase):
    def setUp(self):
        self.binding = {'agent': 'codex', 'target': 'codex:fixture', 'codexHome': '/mnt/c/home',
                        'codexBin': '/mnt/c/tools/codex.exe', 'codexPython': '/mnt/c/Python/python.exe'}
        self.patches = [mock.patch.object(native, 'validate_wsl_codex', return_value=r'C:\home'),
                        mock.patch.object(native, 'windows_codex_home', return_value=r'C:\tools\codex.exe'),
                        mock.patch.object(native.Path, 'read_bytes', return_value=b'core-source')]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def run_result(self, result, operation='list'):
        done = subprocess.CompletedProcess([], 0, json.dumps(result).encode(), b'')
        with mock.patch.object(native.subprocess, 'run', return_value=done) as run:
            value = native.invoke_windows_codex(self.binding, operation, 'hello')
        return value, run

    def test_native_discovery_filters_fixed_target_without_linux_sqlite(self):
        result, run = self.run_result({'ok': True, 'sessions': [
            {'agent': 'codex', 'id': 'fixture'}, {'agent': 'codex', 'id': 'other'}],
            'discovery': {'codex': {'status': 'ok'}}})
        self.assertEqual(result['sessions'], [{'agent': 'codex', 'id': 'fixture'}])
        args = run.call_args.args[0]
        self.assertEqual(args[:3], [self.binding['codexPython'], '-', 'list'])
        self.assertIn(r'C:\home', args)
        self.assertIn(r'C:\tools\codex.exe', args)
        self.assertEqual(run.call_args.kwargs['input'], b'core-source')
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_resolve_and_send_preserve_native_writer_requirement(self):
        for operation in ('resolve', 'send'):
            value, run = self.run_result({'ok': True, 'submitted': operation == 'send'}, operation)
            args = run.call_args.args[0]
            self.assertEqual('--dry-run' in args, operation == 'resolve')
            self.assertNotIn('--allow-inactive-codex-home', args)
            self.assertIn('--no-reply-to', args)
            self.assertFalse(value['consumptionConfirmed'])

    def test_timeout_is_unknown_and_never_retried(self):
        with mock.patch.object(native.subprocess, 'run', side_effect=subprocess.TimeoutExpired('native', 32)) as run:
            result = native.invoke_windows_codex(self.binding, 'send', 'hello')
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['retryAllowed'])
        self.assertEqual(run.call_count, 1)

    def test_failures_do_not_leak_native_error_text(self):
        value, _ = self.run_result({'ok': False, 'error': 'private path and message'})
        self.assertFalse(value['ok'])
        self.assertNotIn('private', json.dumps(value))

    def test_invalid_operations_and_message_fail_before_launch(self):
        with mock.patch.object(native.subprocess, 'run') as run:
            for operation, text in (('shell', 'hello'), ('send', ''), ('send', 'x\0y')):
                with self.assertRaises(native.Rejected):
                    native.invoke_windows_codex(self.binding, operation, text)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
