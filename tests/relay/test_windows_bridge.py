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

    def test_dash_bodies_reach_core_argparse_for_resolve_and_send(self):
        for text in ('-x', '--help', '- item', '--', '- first\n-- second\n한국어'):
            for operation in ('resolve', 'send'):
                def parse_native(argv, **kwargs):
                    self.assertEqual(argv[:3], [self.binding['codexPython'], '-', 'send'])
                    self.assertIn('--message=' + text, argv)
                    args = native.core.build_parser().parse_args(argv[2:])
                    self.assertEqual(native.core.read_message(args), text)
                    self.assertTrue(args.no_from)
                    self.assertTrue(args.no_reply_to)
                    self.assertEqual(args.dry_run, operation == 'resolve')
                    return subprocess.CompletedProcess(argv, 0, json.dumps({'ok': True}).encode(), b'')
                with self.subTest(text=text, operation=operation), \
                     mock.patch.object(native.subprocess, 'run', side_effect=parse_native) as run:
                    value = native.invoke_windows_codex(self.binding, operation, text)
                self.assertTrue(value['ok'])
                run.assert_called_once()

    def test_utf8_size_boundary_accepts_for_resolve_and_send(self):
        text = '한' * 10922 + 'ab'
        self.assertEqual(len(text.encode()), 32768)
        for operation in ('resolve', 'send'):
            with self.subTest(operation=operation), \
                 mock.patch.object(native.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'{"ok":true}', b'')) as run:
                self.assertTrue(native.invoke_windows_codex(self.binding, operation, text)['ok'])
            self.assertIn('--message=' + text, run.call_args.args[0])

    def test_ascii_byte_limit_refuses_before_native_launch(self):
        for operation in ('resolve', 'send'):
            with self.subTest(operation=operation), mock.patch.object(native.subprocess, 'run') as run:
                result = native.invoke_windows_codex(self.binding, operation, 'x' * 32768)
            self.assertEqual(result, {'ok': False, 'status': 'refused', 'submitted': False,
                                     'reason': 'native_windows_command_too_long', 'retryAllowed': False,
                                     'consumptionConfirmed': False})
            run.assert_not_called()

    def test_full_command_boundary_counts_windows_quoting_and_unicode_paths(self):
        self.binding['codexPython'] = '/mnt/c/工具 🧪/python.exe'
        native.validate_wsl_codex.return_value = 'C:\\工具 🧪\\home'
        native.windows_codex_home.return_value = 'C:\\工具 🧪\\codex.exe'
        for operation in ('resolve', 'send'):
            for sample in ('x', ' "', ' \\'):
                with self.subTest(operation=operation, sample=sample):
                    _, run = self.run_result({'ok': True}, operation)
                    baseline = run.call_args.args[0]
                    self.assertIn('C:\\工具 🧪\\home', baseline)
                    self.assertIn('C:\\工具 🧪\\codex.exe', baseline)
                    index = next(i for i, arg in enumerate(baseline) if arg.startswith('--message='))
                    def units(text):
                        args = baseline[:]
                        args[index] = '--message=' + text
                        return len(subprocess.list2cmdline(args).encode('utf-16-le')) // 2 + 1
                    # Find the largest repeated body that fits without exceeding
                    # the independent 32 KiB UTF-8 message policy.
                    low, high = 1, 32768 // len(sample.encode())
                    while low < high:
                        middle = (low + high + 1) // 2
                        if units(sample * middle) <= 32767:
                            low = middle
                        else:
                            high = middle - 1
                    fits, oversized = sample * low, sample * (low + 1)
                    self.assertLessEqual(units(fits), 32767)
                    self.assertGreater(units(oversized), 32767)
                    self.assertLessEqual(len(oversized.encode()), 32768)
                    with mock.patch.object(native.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'{"ok":true}', b'')) as run:
                        self.assertTrue(native.invoke_windows_codex(self.binding, operation, fits)['ok'])
                    run.assert_called_once()
                    with mock.patch.object(native.subprocess, 'run') as run:
                        result = native.invoke_windows_codex(self.binding, operation, oversized)
                    self.assertEqual(result['status'], 'refused')
                    self.assertEqual(result['reason'], 'native_windows_command_too_long')
                    run.assert_not_called()

    def test_emoji_utf8_boundary_fits_without_changing_message_policy(self):
        text = '🧪' * 8192
        self.assertEqual(len(text.encode()), 32768)
        for operation in ('resolve', 'send'):
            with self.subTest(operation=operation), \
                 mock.patch.object(native.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'{"ok":true}', b'')) as run:
                self.assertTrue(native.invoke_windows_codex(self.binding, operation, text)['ok'])
            run.assert_called_once()

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
            invalid = (None, '', ' \n', 'x\0y', 'x' * 32769, '한' * 10923)
            for operation, text in [('shell', 'hello')] + [(op, text) for op in ('resolve', 'send') for text in invalid]:
                with self.assertRaises(native.Rejected):
                    native.invoke_windows_codex(self.binding, operation, text)
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
