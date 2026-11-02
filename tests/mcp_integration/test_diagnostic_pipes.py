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
import types
import unittest
from unittest.mock import AsyncMock, patch

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

            # Delay only this helper's deadline wrapper until the actual
            # escaped pipe holder is ready. Never patch global asyncio.wait_for.
            original_helper = peer.invoke_bounded_diagnostic
            async def ready_then_wait_for(awaitable, timeout):
                try:
                    deadline = asyncio.get_running_loop().time() + 2
                    while not marker.exists():
                        self.assertLess(asyncio.get_running_loop().time(), deadline)
                        await asyncio.sleep(.005)
                except BaseException:
                    # Match wait_for's ownership of its shield future if the
                    # fixture itself fails before the real budget starts.
                    awaitable.cancel()
                    raise
                return await asyncio.wait_for(awaitable, timeout)
            proxy = types.SimpleNamespace(**{
                name: getattr(asyncio, name) for name in
                ('get_running_loop', 'create_task', 'gather', 'CancelledError', 'shield')})
            proxy.wait_for = ready_then_wait_for
            isolated_helper = types.FunctionType(original_helper.__code__,
                {**original_helper.__globals__, 'asyncio': proxy}, original_helper.__name__)
            started = time.monotonic()
            try:
                with patch.object(peer, 'invoke_bounded_diagnostic',
                                  isolated_helper if action == 'timeout' else original_helper), \
                     patch.object(peer.subprocess, 'Popen', side_effect=spawn):
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


    @unittest.skipUnless(sys.platform in ("darwin", "linux"), "Active adapter platform contract")
    async def test_cancel_wins_cleanup_errors_and_stops_next_agent(self):
        original = subprocess.Popen
        for failure in (PermissionError('fixture cleanup denied'),
                        subprocess.TimeoutExpired('fixture cleanup', .1)):
            with self.subTest(failure=type(failure).__name__):
                children = []
                spawned = asyncio.Event()
                adapter = peer.Adapter({'test': {
                    'capabilities': ['diagnostics', 'diagnostics_probe'],
                    'agents': ['claude', 'codex'], 'codexHome': '/fixture/pinned-home'}})
                adapter.invoke_diagnostic = AsyncMock(wraps=adapter.invoke_diagnostic)
                def spawn(*args, **kwargs):
                    # Route CLI launch to a local inert fixture. No CLI/native
                    # agent, network, SSH, service or model is ever started.
                    child = original([sys.executable, '-c', 'import time; time.sleep(30)'],
                                     **kwargs)
                    children.append(child)
                    spawned.set()
                    return child
                def failed_cleanup(process, grace):
                    self.assertIs(process, children[0])
                    time.sleep(.04)
                    raise failure
                try:
                    with patch.object(peer.subprocess, 'Popen', side_effect=spawn), \
                         patch.object(peer.core, 'stop_codex_wake', side_effect=failed_cleanup):
                        task = asyncio.create_task(adapter.diagnose_destination('test', active_probe=True))
                        await asyncio.wait_for(spawned.wait(), 1)
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await asyncio.wait_for(task, 1)
                    self.assertEqual(adapter.invoke_diagnostic.await_count, 1)
                    self.assertEqual(len(children), 1)
                    self.assertTrue(children[0].stdout.closed)
                    self.assertTrue(children[0].stderr.closed)
                finally:
                    for child in children:
                        if child.returncode is None:
                            # Cleanup was deliberately denied; only this test's
                            # still-unreaped Popen leader/group is ours to reap.
                            os.killpg(child.pid, signal.SIGKILL)
                            child.wait(timeout=2)
