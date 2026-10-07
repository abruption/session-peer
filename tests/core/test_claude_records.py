"""Offline regular-file boundaries for Claude discovery and sender metadata."""
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import session_peer as peer


class ClaudeRecords(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='codex-cr-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.directory = self.root / 'sessions'
        self.directory.mkdir()
        self.healthy = {'pid': 101, 'name': 'worker', 'status': 'idle', 'cwd': '/project',
                        'startedAt': 1000, 'messagingSocketPath': str(self.root / '101.sock')}
        if peer.IS_WINDOWS:
            self.healthy['messagingSocketPath'] = r'\\.\pipe\claude-101'
        else:
            inbox = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.addCleanup(inbox.close)
            inbox.bind(self.healthy['messagingSocketPath'])
        self.write(101, json.dumps(self.healthy).encode())
        for patcher in (
            mock.patch.object(peer, 'sessions_dir', return_value=self.directory),
            mock.patch.object(peer, 'pid_alive', return_value=True),
            mock.patch.object(peer, 'windows_process_start_ms', return_value=1000),
            mock.patch.object(peer, 'diagnose_codex', return_value={'status': 'disabled', 'checks': []}),
            mock.patch.object(peer, 'agy_registrations', return_value=[]),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, pid, content):
        path = self.directory / f'{pid}.json'
        path.write_bytes(content)
        return path

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = peer.main([*args, '--json', '--no-update-notice'])
        self.assertEqual(stderr.getvalue(), '')
        return code, json.loads(stdout.getvalue())

    def assert_descriptor_closed(self, descriptor):
        with self.assertRaises(OSError) as caught:
            os.fstat(descriptor)
        self.assertEqual(caught.exception.errno, errno.EBADF)

    def test_mixed_abnormal_entries_preserve_list_doctor_dry_run_and_sender(self):
        contents = [b'null', b'[]', b'true', b'42', b'"scalar"', b'{bad', b'\xff',
                    b'[' * 2000 + b']' * 2000,
                    b' ' * (peer.MAX_CLAUDE_RECORD_BYTES + 1)]
        contents += [json.dumps({**self.healthy, field: value}).encode() for field, value in (
            ('pid', True), ('pid', '101'), ('name', ['worker']), ('cwd', 42),
            ('status', {}), ('messagingSocketPath', [self.healthy['messagingSocketPath']]),
            ('messagingSocketPath', 'bad\0path'),
            ('name', '\ud800'), ('messagingSocketPath', '\ud800'),
        )]
        for number, content in enumerate(contents, 200):
            self.write(number, content)
        (self.directory / '300.json').mkdir()
        extra_invalid = 1
        if not peer.IS_WINDOWS:
            (self.directory / '301.json').symlink_to(self.directory / '101.json')
            os.mkfifo(self.directory / '302.json')
            extra_invalid += 2
        self.assertEqual([row['pid'] for row in peer.discover(include_unreachable=True)], [101])
        code, listing = self.invoke('list', '--agent', 'claude')
        self.assertEqual(code, 0)
        self.assertTrue(listing['ok'])
        self.assertEqual([row['pid'] for row in listing['sessions']], [101])
        code, doctor = self.invoke('doctor')
        self.assertEqual(code, 0)
        self.assertEqual(doctor['claude']['status'], 'available')
        self.assertEqual(doctor['claude']['records'], 1)
        self.assertEqual(doctor['claude']['invalidRecords'], len(contents) + extra_invalid)
        with mock.patch.object(peer, 'post_to_socket') as post:
            code, dry_run = self.invoke('send', '--to', 'worker', '--dry-run',
                                        '--no-from', '--no-reply-to', '--message', 'hello')
        self.assertEqual(code, 0)
        self.assertEqual(dry_run['target'], {'pid': 101, 'name': 'worker'})
        self.assertTrue(dry_run['dryRun'])
        post.assert_not_called()
        with mock.patch.dict(os.environ, {'CLAUDE_CODE_MESSAGING_SOCKET': str(self.root / '101.sock')}):
            self.assertEqual(peer.own_session()['pid'], 101)
            self.assertEqual(peer.sender_agent(), {'agent': 'claude', 'id': 'worker', 'target': 'worker'})

    def test_limit_is_in_bytes_and_accepts_exactly_one_mib(self):
        path = self.write(200, json.dumps({'pid': 200, 'name': '안녕'}, ensure_ascii=False).encode())
        content = path.read_bytes()
        path.write_bytes(content + b' ' * (peer.MAX_CLAUDE_RECORD_BYTES - len(content)))
        self.assertEqual(peer.read_claude_record(path), {'pid': 200, 'name': '안녕'})
        path.write_bytes(content + b' ' * (peer.MAX_CLAUDE_RECORD_BYTES + 1 - len(content)))
        with mock.patch.object(peer.os, 'open', wraps=os.open) as opened:
            with self.assertRaises(ValueError):
                peer.read_claude_record(path)
        opened.assert_not_called()

    def test_growth_after_stat_stops_after_budget_plus_one_byte_and_closes(self):
        path = self.write(200, b'{"pid": 200}')
        original_read = os.read
        total = 0
        grew = False
        def grow_and_read(descriptor, amount):
            nonlocal total, grew
            if not grew:
                with path.open('ab') as stream:
                    stream.write(b' ' * peer.MAX_CLAUDE_RECORD_BYTES)
                grew = True
            data = original_read(descriptor, amount)
            total += len(data)
            return data
        with mock.patch.object(peer.os, 'read', side_effect=grow_and_read), \
             mock.patch.object(peer.os, 'close', wraps=os.close) as closed:
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                peer.read_claude_record(path)
        self.assertEqual(total, peer.MAX_CLAUDE_RECORD_BYTES + 1)
        closed.assert_called_once()
        self.assert_descriptor_closed(closed.call_args.args[0])

    def test_opened_regular_file_replacement_is_rejected_and_closed(self):
        path = self.write(200, b'{"pid": 200}')
        replacement = self.root / 'replacement'
        replacement.write_bytes(b'{"pid": 200, "name": "replacement"}')
        original_open = os.open
        def replace_and_open(record_path, flags):
            replacement.replace(record_path)
            return original_open(record_path, flags)
        with mock.patch.object(peer.os, 'open', side_effect=replace_and_open), \
             mock.patch.object(peer.os, 'close', wraps=os.close) as closed:
            with self.assertRaisesRegex(ValueError, 'changed'):
                peer.read_claude_record(path)
        closed.assert_called_once()
        self.assert_descriptor_closed(closed.call_args.args[0])

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NONBLOCK'), 'POSIX FIFO replacement')
    def test_fifo_replacement_open_does_not_block_in_isolated_process(self):
        path = self.write(200, b'{"pid": 200}')
        script = '''
import os
from pathlib import Path
import sys
import session_peer as peer
path = Path(sys.argv[1])
original_open = os.open
def replace_and_open(record_path, flags):
    assert flags & os.O_NONBLOCK
    path.unlink()
    os.mkfifo(path)
    return original_open(record_path, flags)
peer.os.open = replace_and_open
try:
    peer.read_claude_record(path)
except ValueError:
    pass
else:
    raise AssertionError('FIFO accepted')
'''
        done = subprocess.run([sys.executable, '-c', script, str(path)],
                              capture_output=True, text=True, timeout=5)
        self.assertEqual(done.returncode, 0, done.stderr)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'POSIX no-follow open')
    def test_symlink_replacement_is_not_followed(self):
        path = self.write(200, b'{"pid": 200}')
        original_open = os.open
        def replace_and_open(record_path, flags):
            self.assertTrue(flags & os.O_NOFOLLOW)
            path.unlink()
            path.symlink_to(self.directory / '101.json')
            return original_open(record_path, flags)
        with mock.patch.object(peer.os, 'open', side_effect=replace_and_open), \
             mock.patch.object(peer.os, 'read', wraps=os.read) as read:
            with self.assertRaises(OSError):
                peer.read_claude_record(path)
        read.assert_not_called()

    def test_descriptor_closes_on_stat_read_decode_and_json_failures(self):
        for step in ('stat', 'read', 'decode', 'json', 'object'):
            with self.subTest(step=step):
                content = {'decode': b'\xff', 'json': b'{bad', 'object': b'null'}.get(step, b'{"pid": 200}')
                path = self.write(200, content)
                with contextlib.ExitStack() as stack:
                    closed = stack.enter_context(mock.patch.object(peer.os, 'close', wraps=os.close))
                    if step in ('stat', 'read'):
                        stack.enter_context(mock.patch.object(peer.os, 'fstat' if step == 'stat' else 'read',
                                                              side_effect=OSError('unreadable')))
                    with self.assertRaises((OSError, ValueError)):
                        peer.read_claude_record(path)
                closed.assert_called_once()
                self.assert_descriptor_closed(closed.call_args.args[0])

    def test_record_permission_error_keeps_healthy_rows_and_doctor_diagnostic(self):
        denied = self.write(200, b'{"pid": 200}')
        original_open = os.open
        def guarded_open(path, flags):
            if path == denied:
                raise PermissionError('denied')
            return original_open(path, flags)
        with mock.patch.object(peer.os, 'open', side_effect=guarded_open):
            self.assertEqual([row['pid'] for row in peer.discover()], [101])
            doctor = peer.diagnose_claude()
        self.assertEqual(doctor['records'], 1)
        self.assertEqual(doctor['availableInboxes'], 1)
        self.assertEqual(doctor['status'], 'permission_denied')
        self.assertEqual(doctor['checks'][0]['code'], 'session_record_permission_denied')
        self.assertEqual(doctor['checks'][0]['count'], 1)

    def test_windows_fallback_keeps_bounded_regular_file_reads(self):
        original_open = os.open
        with mock.patch.object(peer, 'IS_WINDOWS', True), \
             mock.patch.object(peer.os, 'open', wraps=original_open) as opened:
            self.assertEqual(peer.read_claude_record(self.directory / '101.json'), self.healthy)
        flags = opened.call_args.args[1]
        self.assertEqual(flags, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
