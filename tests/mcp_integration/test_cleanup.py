import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import session_peer_mcp as mcp


@unittest.skipUnless(sys.platform in ('darwin', 'linux'), 'POSIX process groups')
class Cleanup(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_and_cancellation_kill_term_resistant_descendants(self):
        for mode in ('timeout', 'cancel'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'child'
                script = '''import os,signal,sys,time
if os.fork() == 0:
 signal.signal(signal.SIGTERM, signal.SIG_IGN)
 with open(os.devnull, 'r+b', buffering=0) as stream:
  for fd in (0,1,2): os.dup2(stream.fileno(), fd)
 with open(sys.argv[1] + '.tmp', 'w') as stream:
  stream.write(str(os.getpid()))
 os.replace(sys.argv[1] + '.tmp', sys.argv[1])
 time.sleep(30)
else:
 time.sleep(30)
'''
                with patch.object(mcp, 'CLI_TIMEOUT', .5):
                    task = asyncio.create_task(mcp.invoke_posix([sys.executable, '-c', script, str(path)], None))
                    for _ in range(100):
                        if path.exists(): break
                        await asyncio.sleep(.005)
                    self.assertTrue(path.exists())
                    if mode == 'cancel':
                        task.cancel()
                        asyncio.get_running_loop().call_later(.02, task.cancel)
                    with self.assertRaises(asyncio.CancelledError if mode == 'cancel' else asyncio.TimeoutError):
                        await asyncio.wait_for(task, 5)
                child = int(path.read_text())
                for _ in range(100):
                    status = subprocess.run(['ps', '-o', 'stat=', '-p', str(child)], capture_output=True, text=True).stdout.strip()
                    if not status or status.startswith('Z'): break
                    await asyncio.sleep(.01)
                self.assertTrue(not status or status.startswith('Z'), status)

    async def test_normal_completion_preserves_output_and_exit_code(self):
        output, code = await mcp.invoke_posix([sys.executable, '-c', 'print("fixture")'], None)
        self.assertEqual((output.strip(), code), (b'fixture', 0))

    async def test_pipe_feeding_and_cleanup_do_not_depend_on_default_executor_capacity(self):
        # A shared single-worker pool would deadlock stdout.read before feed.
        with ThreadPoolExecutor(max_workers=1) as executor:
            asyncio.get_running_loop().set_default_executor(executor)
            output, code = await asyncio.wait_for(mcp.invoke_posix(
                [sys.executable, '-c', 'import sys; print(sys.stdin.read())'], 'fixture'), 5)
            self.assertEqual((output.strip(), code), (b'fixture', 0))
