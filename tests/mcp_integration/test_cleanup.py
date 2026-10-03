import asyncio
import contextlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import session_peer_mcp as mcp
from tests.codex.support import THREAD


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


@unittest.skipUnless(sys.platform in ('darwin', 'linux'), 'POSIX detached wake cleanup')
class DetachedWakeCleanup(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='codex-mcp-wake-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        rollout = self.root / 'rollout.jsonl'
        rollout.write_text('synthetic initialized rollout\n')
        with contextlib.closing(sqlite3.connect(self.root / 'state_5.sqlite')) as conn:
            conn.execute('CREATE TABLE threads (id TEXT, cwd TEXT, archived INTEGER, rollout_path TEXT)')
            conn.execute('INSERT INTO threads VALUES (?,?,?,?)',
                         (THREAD, str(self.root), 0, str(rollout)))
            conn.commit()
        fixture = Path(__file__).parents[1] / 'fixtures' / 'codex_wake_cli.py'
        self.executable = self.root / 'codex-fixture'
        # Select the current test interpreter, including an existing venv.
        self.executable.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' +
                                   shlex.quote(str(fixture.resolve())) + ' "$@"\n')
        self.executable.chmod(0o700)
        self.argv = ['send', '--to', 'codex:' + THREAD, '--codex-home', str(self.root),
                     '--codex-bin', str(self.executable), '--wake', '--wake-timeout', '60',
                     '--no-from', '--no-reply-to']
        self.adapter = mcp.Adapter({})
        self.processes = []
        self.output = []
        real_popen = subprocess.Popen
        output = self.output

        class RecordingPipe:
            def __init__(self, stream):
                self.stream = stream

            def read(self):
                value = self.stream.read()
                output.append(value)
                return value

            def close(self):
                self.stream.close()

        def spawn(argv, **kwargs):
            is_cli = len(argv) > 1 and argv[1] == str(Path(mcp.core.__file__).resolve())
            if is_cli:
                # Native --version preflight has no home requirement. Reproduce
                # a clean CI environment even when the local launcher sets one.
                kwargs['env'] = {key: value for key, value in os.environ.items()
                                 if key != 'CODEX_HOME'}
            process = real_popen(argv, **kwargs)
            if is_cli:
                self.processes.append(process)
                process.stdout = RecordingPipe(process.stdout)
            return process

        patcher = patch.object(mcp.subprocess, 'Popen', side_effect=spawn)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def wait_ready(self, task):
        ready = self.root / 'app-server-ready'
        deadline = asyncio.get_running_loop().time() + 5
        while not ready.exists() and asyncio.get_running_loop().time() < deadline:
            if task.done():
                self.fail('wake exited before readiness: ' + repr(task.result()))
            await asyncio.sleep(.01)
        self.assertTrue(ready.exists(), 'detached fixture failed to resume')
        return int(ready.read_text())

    async def assert_native_stopped(self, pid):
        for _ in range(100):
            status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)],
                                    capture_output=True, text=True, timeout=1).stdout.strip()
            if not status or status.startswith('Z'):
                return
            await asyncio.sleep(.01)
        self.fail('owned detached app-server survived cleanup: ' + status)

    def assert_one_submission(self, wake_status, wake_reason):
        self.assertEqual((self.root / 'queue-submissions').read_text().splitlines(), ['queued'])
        self.assertEqual(len(self.processes), 1, 'ambiguous submission was retried')
        self.assertEqual(self.processes[0].returncode, 0 if wake_status == 'completed' else 1,
                         'MCP killed the CLI before it could report the wake outcome')
        result = json.loads(self.output[0])
        self.assertTrue(result['submitted'])
        self.assertEqual(result['status'], 'queued')
        self.assertEqual(result['queueId'], 'fixture-queue')
        self.assertFalse(result['consumptionConfirmed'])
        self.assertEqual((result['wake']['status'], result['wake']['reason']),
                         (wake_status, wake_reason))

    async def interrupted_wake(self, mode, timeout=False, repeated=False):
        # Keep an unrelated group alive to detect overly broad cleanup signals.
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                                     start_new_session=True)
        task = None
        try:
            with patch.dict(os.environ, {'WAKE_TEST_MODE': mode}):
                task = asyncio.create_task(self.adapter.invoke(self.argv, 'synthetic message'))
                pid = await self.wait_ready(task)
                self.assertNotEqual(os.getpgid(pid), self.processes[0].pid,
                                    'fixture must escape the MCP-owned CLI group')
                started = asyncio.get_running_loop().time()
                if timeout:
                    # Enter the real wait_for timeout path after deterministic readiness.
                    # Timeout is selected before invocation by the caller's patch below.
                    result = await task
                    self.assertEqual(result['reason'], 'outcome_unknown')
                    self.assertIn('do not automatically retry', result['error'])
                else:
                    task.cancel()
                    if repeated:
                        for delay in (.02, .1, .3):
                            asyncio.get_running_loop().call_later(delay, task.cancel)
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertLess(asyncio.get_running_loop().time() - started,
                                mcp.WAKE_CLI_CLEANUP_GRACE + mcp.core.CODEX_WAKE_CLEANUP_BUDGET + 2)
                await self.assert_native_stopped(pid)
                self.assert_one_submission('unknown', 'activation_interrupted')
                self.assertIsNone(unrelated.poll(), 'unrelated process group was signalled')
                with patch.object(mcp.core.os, 'killpg') as kill:
                    mcp.core.stop_codex_wake(self.processes[0])
                    kill.assert_not_called()
        finally:
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            # A failing regression assertion must also release the synthetic
            # app-server, without signalling a PID whose owner was reaped.
            (self.root / 'fixture-stop').touch()
            ready = self.root / 'app-server-ready'
            if ready.exists():
                await self.assert_native_stopped(int(ready.read_text()))
            # Retain each Popen leader's ownership until its cleanup is complete.
            mcp.core.stop_codex_wake(unrelated)

    async def test_cancellation_reaps_term_resistant_detached_app_server(self):
        await self.interrupted_wake('resistant')

    async def test_repeated_cancellation_still_reaps_detached_app_server(self):
        await self.interrupted_wake('resistant', repeated=True)

    async def test_cancellation_reaps_promptly_exiting_detached_app_server(self):
        await self.interrupted_wake('prompt')

    async def test_timeout_reaps_detached_app_server_without_retry(self):
        real_wait_for = asyncio.wait_for

        async def deadline_after_resume(awaitable, timeout):
            # Start the short transport deadline only once the detached native
            # fixture has resumed, so slow fixture startup cannot hide the race.
            ready = self.root / 'app-server-ready'
            deadline = asyncio.get_running_loop().time() + 5
            while not ready.exists() and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(.01)
            return await real_wait_for(awaitable, .1)

        with patch.object(mcp.asyncio, 'wait_for', side_effect=deadline_after_resume):
            await self.interrupted_wake('resistant', timeout=True)

    async def test_normal_wake_completion_preserves_queue_and_short_cleanup(self):
        with patch.dict(os.environ, {'WAKE_TEST_MODE': 'complete'}):
            started = asyncio.get_running_loop().time()
            result = await self.adapter.invoke(self.argv, 'synthetic message')
        self.assertLess(asyncio.get_running_loop().time() - started, mcp.WAKE_CLI_CLEANUP_GRACE)
        self.assertTrue(result['ok'])
        self.assert_one_submission('completed', 'native_turn_completed')
        await self.assert_native_stopped(int((self.root / 'app-server-ready').read_text()))
