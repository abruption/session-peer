"""Claude list completeness against injected inventories and owned POSIX records."""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

import session_peer as peer


class ClaudeReadErrors(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix='codex-394-', dir=os.environ.get('SESSION_PEER_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.sessions = self.root/'sessions'
        self.sessions.mkdir(mode=0o700)
        self.env = mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.row = {'agent': 'claude', 'pid': 77, 'name': 'owned-fixture', 'reachable': True,
                    'alive': True, 'status': 'idle', 'cwd': '/fixture', 'socket': '/fixture/inbox'}
        for method in ('post_to_socket', 'queue_codex'):
            guard = mock.patch.object(peer, method, side_effect=AssertionError('list attempted send'))
            guard.start()
            self.addCleanup(guard.stop)

    def inventory(self, rows=(), errors=(), permission_failures=0, invalid_records=0):
        result = peer.ClaudeSessions()
        result.extend(rows)
        result.errors = list(errors)
        result.permission_failures = permission_failures
        result.invalid_records = invalid_records
        return result

    def cli(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = peer.main(['list', '--agent', 'claude', '--json', '--no-update-notice'])
        return code, json.loads(output.getvalue())

    def adapter(self, rows):
        args = peer.build_parser().parse_args(['list', '--agent', 'claude'])
        with mock.patch.object(peer, 'discover', return_value=rows):
            return peer.ClaudeAdapter().list(peer.ExecutionContext('local', args))

    def healthy_record(self):
        endpoint = self.root/'inbox.sock'
        server = socket.socket(socket.AF_UNIX)
        server.bind(str(endpoint))
        self.addCleanup(server.close)
        record = self.sessions/(str(os.getpid())+'.json')
        record.write_text(json.dumps({'pid': os.getpid(), 'name': 'owned-fixture',
                                     'cwd': '/fixture', 'messagingSocketPath': str(endpoint)}))
        record.chmod(0o600)
        return record

    def test_injected_permission_failure_keeps_rows_and_makes_cli_nonzero(self):
        rows = self.inventory([self.row], permission_failures=1)
        with mock.patch.object(peer, 'discover', return_value=rows):
            code, payload = self.cli()
        self.assertEqual(code, 1)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['sessions'], [self.row])
        self.assertEqual(payload['discovery']['claude'], {
            'status': 'error',
            'error': 'Claude profile discovery incomplete: session_record_unavailable'})
        self.assertEqual(rows.errors, [])

    def test_existing_multi_profile_errors_are_preserved_deduplicated_without_mutation(self):
        errors = ['sessions_directory_unavailable', 'session_record_unavailable',
                  'session_record_unavailable']
        rows = self.inventory([self.row], errors, permission_failures=2)
        before = list(rows.errors)
        result = self.adapter(rows)
        self.assertEqual(result['sessions'], [self.row])
        self.assertEqual(result['discovery'], {'status': 'error', 'error':
            'Claude profile discovery incomplete: session_record_unavailable, sessions_directory_unavailable'})
        self.assertEqual(rows.errors, before)

    def test_empty_healthy_and_nonpermission_invalid_inventory_keep_existing_contract(self):
        for rows in (self.inventory(), self.inventory([self.row]),
                     self.inventory(invalid_records=1)):
            with self.subTest(rows=len(rows), invalid=rows.invalid_records):
                self.assertEqual(self.adapter(rows), {
                    'sessions': list(rows), 'discovery': {'status': 'ok'}})
                with mock.patch.object(peer, 'discover', return_value=rows):
                    code, payload = self.cli()
                self.assertEqual(code, 0)
                self.assertTrue(payload['ok'])
                self.assertEqual(payload['discovery']['claude'], {'status': 'ok'})
                self.assertEqual(rows.errors, [])

    @unittest.skipUnless(os.name == 'posix', 'owned POSIX mode000 fixture')
    def test_actual_mode000_selected_record_is_partial_without_private_error_path(self):
        self.healthy_record()
        blocked = self.sessions/(str(os.getpid()+100000)+'.json')
        blocked.write_text(json.dumps({'pid': os.getpid()+100000}))
        blocked.chmod(0)
        self.addCleanup(blocked.chmod, 0o600)
        # Root/DAC-bypass environments can read mode000. Probe the kernel
        # independently of the production reader, so a reader regression cannot
        # turn this test into a false skip. Injected coverage remains unconditional.
        try:
            with blocked.open('rb') as probe:
                probe.read(1)
        except PermissionError:
            pass
        else:
            self.skipTest('mode000 fixture is readable; kernel denial unavailable')
        with self.assertRaises(PermissionError):
            peer.read_claude_record(blocked)
        inventory = peer.discover()
        self.assertEqual(inventory.permission_failures, 1)
        self.assertEqual(inventory.errors, [])
        self.assertEqual([row['pid'] for row in inventory], [os.getpid()])
        code, payload = self.cli()
        self.assertEqual(code, 1)
        self.assertFalse(payload['ok'])
        self.assertEqual([row['pid'] for row in payload['sessions']], [os.getpid()])
        error = payload['discovery']['claude']['error']
        self.assertEqual(error, 'Claude profile discovery incomplete: session_record_unavailable')
        self.assertNotIn(str(self.root), error)
        self.assertNotIn(str(blocked), error)

    @unittest.skipUnless(os.name == 'posix', 'owned POSIX permission probe')
    def test_readable_mode000_probe_skips_only_actual_permission_case(self):
        case = type(self)('test_actual_mode000_selected_record_is_partial_without_private_error_path')
        result = unittest.TestResult()
        original_open = Path.open
        blocked_name = str(os.getpid()+100000)+'.json'

        def readable_probe(path, *args, **kwargs):
            mode = args[0] if args else kwargs.get('mode', 'r')
            if path.name == blocked_name and mode == 'rb':
                return io.BytesIO(b'kernel-readable fixture')
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, 'open', readable_probe), mock.patch.object(
                peer, 'read_claude_record', side_effect=AssertionError('production reader reached')):
            case.run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])
        self.assertEqual(len(result.skipped), 1)
        self.assertIn('kernel denial unavailable', result.skipped[0][1])

    @unittest.skipUnless(os.name == 'posix', 'owned POSIX record fixture')
    def test_actual_nonpermission_invalid_record_is_still_ignored(self):
        self.healthy_record()
        invalid = self.sessions/(str(os.getpid()+100000)+'.json')
        invalid.write_text('{invalid')
        invalid.chmod(0o600)
        inventory = peer.discover()
        self.assertEqual(inventory.permission_failures, 0)
        self.assertEqual(inventory.invalid_records, 1)
        self.assertEqual(inventory.errors, [])
        code, payload = self.cli()
        self.assertEqual(code, 0)
        self.assertTrue(payload['ok'])
        self.assertEqual([row['pid'] for row in payload['sessions']], [os.getpid()])


if __name__ == '__main__':
    unittest.main()
