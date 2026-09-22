"""Native Windows writer evidence; no inactive-home bypass or model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import session_peer as peer


class WindowsWriter(unittest.TestCase):
    def test_windows_probe_uses_native_backend_without_fcntl(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'writer.lock'
            path.write_bytes(b'unchanged')
            with mock.patch.object(peer.sys, 'platform', 'win32'), \
                    mock.patch.object(peer, 'fcntl', None), \
                    mock.patch.object(peer, '_windows_probe_lock', return_value=('held', 'kernel_lock_held')) as probe:
                self.assertEqual(peer.probe_codex_writer_lock(path), ('held', 'kernel_lock_held'))
                probe.assert_called_once()
            self.assertEqual(path.read_bytes(), b'unchanged')

    def test_native_owner_identity_and_same_user_are_required(self):
        sample = {'snapshot': (1, 2, 0, 3), 'writerLock': 'held',
                  'probeReason': 'kernel_lock_held', 'openerError': None,
                  'openers': [{'pid': 123, 'uid': 'S-1-fixture', 'command': 'codex.exe', 'startTime': '12345'}]}
        with mock.patch.object(peer.sys, 'platform', 'win32'), \
                mock.patch.object(peer, '_codex_lock_sample', return_value=sample), \
                mock.patch.object(peer.time, 'sleep'), \
                mock.patch.object(peer, '_codex_current_user', return_value='S-1-fixture') as user:
            self.assertEqual(peer.inspect_codex_writer(Path('fixture'), 'thread')['activity'], 'live_writer')
            user.return_value = 'S-1-other'
            self.assertEqual(peer.inspect_codex_writer(Path('fixture'), 'thread')['reason'], 'lock_owner_wrong_user')
            user.return_value = None
            self.assertEqual(peer.inspect_codex_writer(Path('fixture'), 'thread')['activity'], 'unknown')

    def test_inspector_is_bounded_and_fail_closed(self):
        for stdout in ('null', '{}', '[{}]', '[{"pid":1,"uid":null}]', 'not json'):
            with self.subTest(stdout=stdout), mock.patch.object(peer.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], 0, stdout, '')) as run:
                self.assertIsNone(peer._windows_process_inspect('openers', 'fixture.lock'))
                self.assertEqual(run.call_args.kwargs['timeout'], peer.DETECT_TIMEOUT)
                self.assertNotIn('shell', run.call_args.kwargs)
        with mock.patch.object(peer.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 3)):
            self.assertIsNone(peer._windows_process_inspect('openers', 'fixture.lock'))

    @unittest.skipUnless(sys.platform == 'win32', 'native Windows API required')
    def test_real_windows_lock_and_process_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'writer.lock'
            path.write_bytes(b'unchanged')
            child = subprocess.Popen([sys.executable, '-c',
                "import msvcrt,sys,time; f=open(sys.argv[1],'r+b'); "
                "msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1); print('ready',flush=True); time.sleep(60)",
                str(path)], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                self.assertEqual(peer.probe_codex_writer_lock(path), ('held', 'kernel_lock_held'))
                rows, error = peer._codex_lock_openers(path)
                self.assertIsNone(error)
                self.assertEqual([row['pid'] for row in rows], [child.pid])
                self.assertEqual(rows[0]['uid'], peer._codex_current_user())
                self.assertTrue(rows[0]['startTime'].isdigit())
                self.assertNotIn('args', rows[0])
            finally:
                child.terminate()
                child.wait(timeout=5)
                child.stdout.close()
            self.assertEqual(peer.probe_codex_writer_lock(path), ('free', 'kernel_lock_free'))
            self.assertEqual(path.read_bytes(), b'unchanged')


if __name__ == '__main__':
    unittest.main()
