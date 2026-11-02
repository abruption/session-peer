"""Local POSIX process fixtures; no native agents, SSH, services or model calls.

Run with TMPDIR set to the task's private codex directory on the workspace volume.
Every fixture directory is private and removed by TemporaryDirectory.
"""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import session_peer_mcp as peer


@unittest.skipUnless(os.name == 'posix', 'Requires POSIX session and nonblocking pipe ownership')
class DiagnosticPipes(unittest.IsolatedAsyncioTestCase):
    async def run_escaped_fixture(self, action, output_fd=1):
        # The test retains a control-pipe writer. The grandchild only exits when
        # this owner closes it, including on assertion failure; no saved-PID kill.
        control_read, control_write = os.pipe()
        children = []
        original = subprocess.Popen
        with tempfile.TemporaryDirectory(prefix='codex-diagnostic-pipes-',
                                         dir=os.environ.get('TMPDIR', tempfile.gettempdir())) as folder:
            marker = Path(folder) / 'escaped-ready.json'
            escaped = ('import json,os,signal; '
                       'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                       f'open({str(marker)!r},"w").write(json.dumps({{"pid":os.getpid(),"sid":os.getsid(0)}})); '
                       f'os.read({control_read},1); os._exit(0)')
            owned = ('import os,signal,subprocess,sys,time; '
                     'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                     f'subprocess.Popen([sys.executable,"-c",{escaped!r}], '
                     f'pass_fds=({control_read},),start_new_session=True); '
                     f'os.close({control_read}); '
                     f'\nwhile not os.path.exists({str(marker)!r}): time.sleep(.001)\n')
            if action == 'overflow':
                # A valid doctor-shaped JSON prefix must not be accepted when
                # any subsequent bytes exceed either pipe's separate budget.
                prefix = json.dumps({'ok': True, 'schemaVersion': 1, 'command': 'doctor'})
                owned += f'os.write(1,{prefix.encode()!r}); os.write({output_fd},b"x"*100000)\n'
            owned += 'while True: time.sleep(1)\n'

            def spawn(*args, **kwargs):
                kwargs['pass_fds'] = (control_read,)
                child = original(*args, **kwargs)
                children.append(child)
                return child

            started = time.monotonic()
            try:
                with patch.object(peer.subprocess, 'Popen', side_effect=spawn):
                    task = asyncio.create_task(peer.invoke_posix(
                        [sys.executable, '-c', owned], None,
                        timeout=.35 if action == 'timeout' else 5, output_limit=128))
                    if action == 'cancel':
                        deadline = asyncio.get_running_loop().time() + 2
                        while not marker.exists():
                            self.assertLess(asyncio.get_running_loop().time(), deadline)
                            await asyncio.sleep(.005)
                        task.cancel()
                        await asyncio.sleep(.02)
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await asyncio.wait_for(task, 2)
                    else:
                        expected = asyncio.TimeoutError if action == 'timeout' else peer.DiagnosticOutputLimit
                        with self.assertRaises(expected):
                            await asyncio.wait_for(task, 2)
                self.assertLess(time.monotonic() - started, 2)
                self.assertTrue(marker.exists(), 'Fixture must actually create the escaped pipe holder')
                escaped_identity = json.loads(marker.read_text())
                self.assertEqual(escaped_identity['pid'], escaped_identity['sid'])
                self.assertNotEqual(escaped_identity['sid'], children[0].pid)
                self.assertEqual(children[0].returncode, -signal.SIGKILL)
                self.assertEqual(children[0].wait(timeout=.1), -signal.SIGKILL)
                self.assertTrue(children[0].stdout.closed)
                self.assertTrue(children[0].stderr.closed)
                self.assertIsNone(children[0].stdin)
                # It is still alive despite helper completion; the helper has
                # authority over the original process group only.
                os.kill(escaped_identity['pid'], 0)
            finally:
                os.close(control_read)
                os.close(control_write)
                for child in children:
                    if child.returncode is None:
                        # Only our unreaped Popen leader is signalled here.
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=2)

    async def test_timeout_ignores_escaped_inherited_pipe_eof(self):
        await self.run_escaped_fixture('timeout')

    async def test_repeated_cancel_ignores_escaped_inherited_pipe_eof(self):
        await self.run_escaped_fixture('cancel')

    async def test_stdout_overflow_rejects_valid_prefix_and_escaped_pipe(self):
        await self.run_escaped_fixture('overflow', 1)

    async def test_stderr_overflow_rejects_valid_prefix_and_escaped_pipe(self):
        await self.run_escaped_fixture('overflow', 2)

    async def test_success_returns_bounded_stdout_and_reaps_leader(self):
        value, code = await peer.invoke_posix(
            [sys.executable, '-c', 'import os; os.write(1,b"{}")'], None,
            timeout=1, output_limit=128)
        self.assertEqual(value, b'{}')
        self.assertEqual(code, 0)
