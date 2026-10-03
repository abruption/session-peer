"""Offline management argv fixtures; no state or transport is accessed."""
import argparse
import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

if sys.version_info < (3, 11) or os.name != 'posix':
    raise unittest.SkipTest('optional relay management requires Unix Python 3.11+')
try:
    import cryptography
    import websockets
except ImportError:
    raise unittest.SkipTest('optional relay dependencies not installed')

import session_peer as core
from session_peer_relay import cli


EXTERNAL = '이름 café ' + ''.join(chr(code) for code in (*range(32), *range(127, 160))) + (
    '\x1b]52;c;Zml4dHVyZQ==\x07\x1b]8;;https://example.invalid\x1b\\link\x1b]8;;\x1b\\'
)


class ManagementParser(unittest.TestCase):
    def capture_exit(self, invoke, status):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
             self.assertRaises(SystemExit) as raised:
            invoke()
        self.assertEqual(raised.exception.code, status)
        return stdout.getvalue(), stderr.getvalue()

    def test_core_management_errors_escape_all_controls_before_side_effects(self):
        commands = (
            ('device', 'init', '--unexpected=' + EXTERNAL),
            ('relay', 'provision', '--out', 'fixture', '--unexpected=' + EXTERNAL),
            ('device', EXTERNAL),
            ('relay', EXTERNAL),
            ('device', 'status', '--peer', 'fixture', '--request-id', 'fixture', '--route', EXTERNAL),
            ('relay', 'serve', '--accounts', 'fixture', '--port', EXTERNAL),
            ('relay', 'serve', '--accounts', 'fixture', '--metrics-port', EXTERNAL),
        )
        for argv in commands:
            with self.subTest(argv=argv[:2]), \
                 mock.patch.object(cli, 'manage', new_callable=mock.AsyncMock) as manage, \
                 mock.patch.object(cli, 'Store') as store, \
                 mock.patch.object(cli, 'private_read') as private_read, \
                 mock.patch.object(cli, 'private_write') as private_write, \
                 mock.patch.object(cli, 'Receiver') as receiver, \
                 mock.patch.object(cli, 'Relay') as relay, \
                 mock.patch.object(cli.os, 'umask') as umask:
                stdout, stderr = self.capture_exit(lambda: core.main(list(argv)), 2)
            self.assertEqual(stdout, '')
            self.assertTrue(stderr.startswith('usage: session-peer ' + argv[0]))
            self.assertTrue(any(line.startswith('session-peer ' + argv[0]) and ': error:' in line
                                for line in stderr.splitlines()))
            self.assertFalse(any(ord(char) < 0x20 and char != '\n'
                                 or 0x7f <= ord(char) <= 0x9f for char in stderr), repr(stderr))
            if '--unexpected=' in argv[-1]:
                self.assertIn(core.human_text(EXTERNAL), stderr)
            for effect in (manage, store, private_read, private_write, receiver, relay, umask):
                effect.assert_not_called()

    def test_usage_help_and_trusted_errors_match_argparse(self):
        for kind, argv in (('device', []), ('relay', ['serve']),
                           ('device', ['--help']), ('relay', ['--help']),
                           ('device', ['status', '--help']), ('relay', ['serve', '--help'])):
            with self.subTest(kind=kind, argv=argv):
                safe = cli.parser(kind)
                with mock.patch.object(core, 'HumanArgumentParser', argparse.ArgumentParser):
                    baseline = cli.parser(kind)
                self.assertEqual(safe.format_usage(), baseline.format_usage())
                self.assertEqual(safe.format_help(), baseline.format_help())
                status = 0 if '--help' in argv else 2
                self.assertEqual(self.capture_exit(lambda: safe.parse_args(argv), status),
                                 self.capture_exit(lambda: baseline.parse_args(argv), status))

    def test_valid_values_defaults_and_management_json_remain_raw(self):
        commands = (
            ('device', ['init', '--state', EXTERNAL]),
            ('device', ['status', '--peer', EXTERNAL, '--request-id', EXTERNAL]),
            ('relay', ['provision', '--out', EXTERNAL, '--room', EXTERNAL]),
            ('relay', ['serve', '--accounts', EXTERNAL]),
        )
        for kind, argv in commands:
            with self.subTest(kind=kind, argv=argv[:1]):
                parsed = cli.parser(kind).parse_args(argv)
                with mock.patch.object(core, 'HumanArgumentParser', argparse.ArgumentParser):
                    baseline = cli.parser(kind).parse_args(argv)
                self.assertEqual(vars(parsed), vars(baseline))
        result = {'ok': True, 'directory': EXTERNAL}
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, 'manage', new_callable=mock.AsyncMock, return_value=result) as manage, \
             mock.patch.object(cli.os, 'umask'), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = core.main(['relay', 'provision', '--out', EXTERNAL])
        self.assertEqual(code, 0)
        self.assertEqual(manage.call_args.args[1].out, EXTERNAL)
        self.assertEqual(stdout.getvalue().encode(),
                         (json.dumps({'schemaVersion': 1, **result}, ensure_ascii=False) + '\n').encode())
        self.assertEqual(stderr.getvalue(), '')
        self.assertEqual(result['directory'], EXTERNAL)
