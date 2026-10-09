"""Owned Python process/pipe fixtures, not SSH, agents or delivery tests."""

import json
import os
from pathlib import Path
import signal
import selectors
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import session_peer as peer
from session_peer import handoff_stream_child


@unittest.skipUnless(os.name == "posix", "owned POSIX child/group fixtures")
class HandoffProcess(unittest.TestCase):
    def test_empty_or_failed_group_probe_is_not_zombies_only_proof(self):
        original = subprocess.Popen
        for stdout, stderr, exit_code, expected in (("", "", 1, False),
                ("", "", 0, False), ("Z\n", "error", 1, False), ("S\n", "", 0, False), ("Z\nZ+\n", "", 0, True)):
            with self.subTest(stdout=stdout, stderr=stderr, exit_code=exit_code):
                def owned_probe(*args, **kwargs):
                    script = "import sys;sys.stdout.write(" + repr(stdout) + ");sys.stderr.write(" + repr(stderr) + ");sys.exit(" + str(exit_code) + ")"
                    return original([sys.executable, "-c", script], **kwargs)
                with patch("session_peer.subprocess.Popen", new=owned_probe), patch("session_peer.sys.platform", "darwin"):
                    result = peer.handoff_group_zombies_only(os.getpid(), time.monotonic() + 1)
                self.assertEqual(result, expected)

    def run_child(self, code, source=b"", seconds=1, cleanup=.5, clock=time.monotonic):
        now = clock()
        return handoff_stream_child([sys.executable, "-c", code], source,
                                    now + seconds, now + seconds + cleanup, clock)

    def assert_not_executing(self, pid):
        # Read-only process state: a killed descendant may remain a zombie
        # until its reparented system owner reaps it. Do not signal it again.
        done = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1)
        self.assertTrue(done.returncode == 1 or not done.stdout.strip()
                        or all(line.strip().startswith(b"Z") for line in done.stdout.splitlines()))

    def test_source_streamed_in_chunks_with_both_output_pipes_drained(self):
        source = ("源🙂\n" * 20_000).encode()
        code = '''import os
os.write(2, b"d" * 65536)
while True:
    raw = os.read(0, 4096)
    if not raw: break
    view = memoryview(raw)
    while view:
        view = view[os.write(1, view):]
'''
        result = self.run_child(code, source, seconds=2)
        self.assertTrue(result.spawned)
        self.assertEqual(result.stdout, source)
        self.assertEqual(result.stderr, b"d" * 65536)
        self.assertFalse(result.stdout_overflow)
        self.assertFalse(result.stderr_overflow)
        self.assertFalse(result.cleanup_failed)
        self.assertIsNone(result.reason)
        self.assertIn(result.returncode, (0, -signal.SIGKILL))

    def test_complete_stdout_and_invalid_utf8_stderr_are_returned_raw(self):
        result = self.run_child('import os; os.write(1, b\'{"ok":true}\\n\'); os.write(2, b"\\xff\\xfe")')
        self.assertEqual(result.stdout, b'{"ok":true}\n')
        self.assertEqual(result.stderr, b"\xff\xfe")
        self.assertIsNone(result.reason)

    def test_complete_stdout_survives_diagnostic_overflow(self):
        result = self.run_child('import os; os.write(1, b\'{"ok":true}\\n\'); os.write(2, b"x"*100000); import time; time.sleep(10)')
        self.assertEqual(result.stdout, b'{"ok":true}\n')
        self.assertEqual(result.stderr, b"x" * 65536)
        self.assertTrue(result.stderr_overflow)
        self.assertFalse(result.stdout_overflow)
        self.assertEqual(result.reason, "stderr_capacity")
        self.assertFalse(result.cleanup_failed)

    def test_stdout_overflow_never_turns_valid_prefix_into_success(self):
        result = self.run_child('import os; os.write(1, b\'{"ok":true}\\n\'); os.write(1, b"x"*1100000)')
        self.assertEqual(len(result.stdout), 1048576)
        self.assertTrue(result.stdout.startswith(b'{"ok":true}\n'))
        self.assertTrue(result.stdout_overflow)
        self.assertEqual(result.reason, "stdout_capacity")
        self.assertFalse(result.cleanup_failed)

    def test_blocked_source_feeder_and_live_child_timeout_are_bounded(self):
        started = time.monotonic()
        result = self.run_child('import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(10)',
                                b"x" * 4194304, seconds=.08)
        self.assertTrue(result.spawned)
        self.assertEqual(result.reason, "process_deadline")
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertFalse(result.cleanup_failed)
        self.assertLess(time.monotonic() - started, 1)

    def test_slow_source_read_does_not_renew_cutoff(self):
        result = self.run_child('import os,time;\nwhile os.read(0,1): time.sleep(.02)', b"x" * 65536, seconds=.08)
        self.assertEqual(result.reason, "process_deadline")
        self.assertFalse(result.cleanup_failed)

    def test_early_stdin_close_preserves_complete_raw_response(self):
        result = self.run_child('import os; os.close(0); os.write(1, b\'{"ok":false}\\n\')', b"x" * 4194304)
        self.assertEqual(result.stdout, b'{"ok":false}\n')
        self.assertEqual(result.reason, "source_stream_failed")
        self.assertFalse(result.cleanup_failed)

    def test_own_term_resistant_forked_descendant_is_not_left_executing(self):
        code = '''import os, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = os.fork()
if child == 0:
    while True: time.sleep(10)
print(child, flush=True)
while True: time.sleep(10)
'''
        result = self.run_child(code, seconds=.2)
        self.assertEqual(result.reason, "process_deadline")
        self.assertFalse(result.cleanup_failed)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assert_not_executing(int(result.stdout))

    def test_descendant_holding_pipes_after_leader_exit_is_bounded(self):
        code = '''import os, time
child = os.fork()
if child == 0:
    time.sleep(10)
    os._exit(0)
print(child, flush=True)
os._exit(0)
'''
        result = self.run_child(code, seconds=.2)
        self.assertEqual(result.reason, "process_deadline")
        self.assertFalse(result.cleanup_failed)
        self.assertEqual(result.returncode, 0)
        self.assert_not_executing(int(result.stdout))

    def test_closed_output_pipes_do_not_allow_unbounded_wait(self):
        result = self.run_child('import os,time; os.close(1); os.close(2); time.sleep(10)')
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertFalse(result.cleanup_failed)

    def test_missing_executable_is_definitely_not_spawned(self):
        now = time.monotonic()
        result = handoff_stream_child([str(Path(__file__).with_name("missing-owned-executable"))],
                                      b"", now + 1, now + 2, time.monotonic)
        self.assertFalse(result.spawned)
        self.assertEqual(result.reason, "process_not_started")
        self.assertIsNone(result.returncode)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")

    def test_preexpired_and_source_overflow_never_spawn(self):
        now = time.monotonic()
        for source, cutoff, reason in ((b"", now, "deadline_before_spawn"),
                                        (b"x" * 4194305, now + 1, "source_capacity")):
            with patch("session_peer.subprocess.Popen", side_effect=AssertionError("no spawn")):
                result = handoff_stream_child([sys.executable], source, cutoff, now + 2, time.monotonic)
            self.assertFalse(result.spawned)
            self.assertEqual(result.reason, reason)

    def test_clock_unavailable_before_spawn_is_definite(self):
        def failed():
            raise RuntimeError("private-body-do-not-reflect")
        with patch("session_peer.subprocess.Popen", side_effect=AssertionError("no spawn")):
            result = handoff_stream_child([sys.executable], b"", 10, 15, failed)
        self.assertFalse(result.spawned)
        self.assertEqual(result.reason, "process_clock_unavailable")
        self.assertEqual(result.stderr, b"")
        self.assertNotIn("private-body", repr(result))

    def test_clock_failure_after_spawn_uses_native_duration_cleanup(self):
        started = time.monotonic()
        calls = 0
        def shared():
            nonlocal calls
            calls += 1
            if calls <= 2:
                return 9_000_000_000
            raise RuntimeError("private-diagnostic")
        result = handoff_stream_child([sys.executable, "-c", "import time; time.sleep(10)"],
                                      b"", 9_000_000_001, 9_000_000_001.5, shared)
        self.assertTrue(result.spawned)
        self.assertEqual(result.reason, "process_clock_unavailable")
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertFalse(result.cleanup_failed)
        self.assertLess(time.monotonic() - started, 1)

    def test_backward_shared_clock_cannot_extend_native_budget(self):
        calls = 0
        started = time.monotonic()
        def shared():
            nonlocal calls
            calls += 1
            return 100 if calls <= 2 else 0
        result = handoff_stream_child([sys.executable, "-c", "import time; time.sleep(10)"],
                                      b"", 100.08, 100.58, shared)
        self.assertEqual(result.reason, "process_deadline")
        self.assertFalse(result.cleanup_failed)
        self.assertLess(time.monotonic() - started, 1)

    def test_readiness_cannot_authorize_source_write_after_cutoff(self):
        calls = 0
        writes = []
        actual_write = os.write
        def clock():
            nonlocal calls
            calls += 1
            return 0 if calls <= 3 else 1
        def write(fd, data):
            writes.append(len(data))
            return actual_write(fd, data)
        with patch("session_peer.os.write", new=write):
            result = handoff_stream_child([sys.executable, "-c", "import time;time.sleep(10)"],
                                          b"source-not-authorized-after-cutoff", 1, 2, clock)
        self.assertTrue(result.spawned)
        self.assertEqual(result.reason, "process_deadline")
        self.assertEqual(writes, [])
        self.assertFalse(result.cleanup_failed)

    def test_group_signal_is_before_wait_never_after_reap(self):
        events = []
        actual = subprocess.Popen
        actual_kill = os.killpg
        class Tracked(actual):
            def poll(self):
                raise AssertionError("must not reap by poll before group cleanup")
            def wait(self, *args, **kwargs):
                if self.args[0] != "/bin/ps":
                    events.append("wait")
                    self.assert_signal_order()
                return super().wait(*args, **kwargs)
            def assert_signal_order(self):
                if not events or events[0] != "signal":
                    raise AssertionError("group signal must precede wait")
        def kill(pid, number):
            events.append("signal")
            return actual_kill(pid, number)
        with patch("session_peer.subprocess.Popen", new=Tracked), patch("session_peer.os.killpg", new=kill):
            result = self.run_child("pass")
        self.assertFalse(result.cleanup_failed)
        self.assertEqual(events, ["signal", "wait"])

    def test_platform_and_invalid_requests_refuse_before_spawn(self):
        with patch("session_peer.os.name", "nt"):
            result = handoff_stream_child([sys.executable], b"", 10, 15, lambda: 0)
        self.assertFalse(result.spawned)
        self.assertEqual(result.reason, "process_platform_unsupported")
        for argv, source, cutoff, total in (([], b"", 1, 2), (["bad\0arg"], b"", 1, 2),
                                            (["x"], "not-bytes", 1, 2), (["x"], b"", float("nan"), 2)):
            result = handoff_stream_child(argv, source, cutoff, total, lambda: 0)
            self.assertFalse(result.spawned)
            self.assertIn(result.reason, ("invalid_process_request", "invalid_process_deadline"))

    def test_interrupt_during_group_cleanup_still_signals_before_wait(self):
        calls = 0
        actual = os.killpg
        def interrupted_kill(pid, number):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise KeyboardInterrupt()
            return actual(pid, number)
        with patch("session_peer.os.killpg", new=interrupted_kill):
            result = self.run_child("import os,time; os.close(1); os.close(2); time.sleep(10)")
        self.assertEqual(calls, 2)
        self.assertTrue(result.interrupted)
        self.assertEqual(result.reason, "process_interrupted")
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertFalse(result.cleanup_failed)

    def test_unregister_interrupt_during_finally_cannot_skip_reap(self):
        actual_selector = selectors.DefaultSelector
        actual_kill = os.killpg
        killed = interrupted = False
        class InterruptSelector:
            def __init__(self):
                self.inner = actual_selector()
            def register(self, *args, **kwargs):
                return self.inner.register(*args, **kwargs)
            def get_map(self):
                return self.inner.get_map()
            def select(self, *args):
                return self.inner.select(*args)
            def unregister(self, stream):
                nonlocal interrupted
                key = self.inner.get_key(stream)
                if killed and key.data == "stdin" and not interrupted:
                    interrupted = True
                    raise KeyboardInterrupt()
                return self.inner.unregister(stream)
            def close(self):
                return self.inner.close()
        def kill(pid, number):
            nonlocal killed
            killed = True
            return actual_kill(pid, number)
        with patch("session_peer.selectors.DefaultSelector", new=InterruptSelector), patch("session_peer.os.killpg", new=kill):
            result = self.run_child("import time; time.sleep(10)", b"x" * 4194304, seconds=.04)
        self.assertTrue(interrupted)
        self.assertTrue(result.interrupted)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertFalse(result.cleanup_failed)

    def test_persistent_clock_keyboard_interrupt_uses_cleanup_backup(self):
        calls = 0
        started = time.monotonic()
        def clock():
            nonlocal calls
            calls += 1
            if calls <= 2:
                return 1_000_000_000
            raise KeyboardInterrupt()
        result = handoff_stream_child([sys.executable, "-c", "import time;time.sleep(10)"],
                                      b"", 1_000_000_000.2, 1_000_000_000.7, clock)
        self.assertTrue(result.interrupted)
        self.assertEqual(result.reason, "process_interrupted")
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertFalse(result.cleanup_failed)
        self.assertLess(time.monotonic() - started, 1)

    def test_enormous_integer_deadline_is_fixed_pre_spawn_failure(self):
        with patch("session_peer.subprocess.Popen", side_effect=AssertionError("no spawn")):
            result = handoff_stream_child([sys.executable], b"", 10 ** 10000, 10 ** 10000, lambda: 0)
        self.assertFalse(result.spawned)
        self.assertEqual(result.reason, "invalid_process_deadline")

    def test_constructor_interrupt_never_claims_definite_no_spawn(self):
        with patch("session_peer.subprocess.Popen", side_effect=KeyboardInterrupt()), patch("session_peer.os.killpg", side_effect=AssertionError("no guessed signal")):
            result = self.run_child("pass")
        self.assertIsNone(result.spawned)
        self.assertTrue(result.interrupted)
        self.assertTrue(result.cleanup_failed)
        self.assertIsNone(result.returncode)
        self.assertEqual(result.reason, "process_spawn_interrupted")

    def test_constructor_interrupt_after_actual_spawn_is_unknown(self):
        original = subprocess.Popen
        owned = []
        def interrupted_constructor(*args, **kwargs):
            child = original(*args, **kwargs)
            owned.append(child)
            raise KeyboardInterrupt()
        try:
            with patch("session_peer.subprocess.Popen", new=interrupted_constructor):
                result = self.run_child("import time;time.sleep(10)")
            self.assertEqual(len(owned), 1)
            self.assertIsNone(result.spawned)
            self.assertTrue(result.cleanup_failed)
            self.assertEqual(result.reason, "process_spawn_interrupted")
        finally:
            # The harness owns this otherwise unreturned object and cleans it
            # independently; production cannot infer this unavailable handle.
            for child in owned:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=1)
                for stream in (child.stdin, child.stdout, child.stderr):
                    stream.close()

    def test_sigint_returns_metadata_and_reaps_owned_child(self):
        with tempfile.TemporaryDirectory(prefix="codex-child-signal-", dir=os.environ.get("SESSION_PEER_TEST_TMP")) as directory:
            pid_path = Path(directory) / "pid"
            inner = "import os,time,pathlib; pathlib.Path(" + repr(str(pid_path)) + ").write_text(str(os.getpid())); time.sleep(10)"
            runner = '''import json,sys,time
from session_peer import handoff_stream_child
now=time.monotonic()
result=handoff_stream_child([sys.executable,"-c",sys.argv[1]],b"x"*4194304,now+2,now+3,time.monotonic)
print(json.dumps({"reason":result.reason,"spawned":result.spawned,"interrupted":result.interrupted,"code":result.returncode,"cleanup":result.cleanup_failed}),flush=True)
raise SystemExit(130 if result.interrupted else 1)
'''
            with subprocess.Popen([sys.executable, "-c", runner, inner], cwd=Path(peer.__file__).parent,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as child:
                deadline = time.monotonic() + 1
                while not pid_path.exists() and time.monotonic() < deadline:
                    time.sleep(.005)
                self.assertTrue(pid_path.exists())
                pid = int(pid_path.read_text())
                child.send_signal(signal.SIGINT)
                stdout, stderr = child.communicate(timeout=2)
            self.assertEqual(child.returncode, 130)
            self.assertEqual(stderr, "")
            self.assertEqual(json.loads(stdout), {"reason":"process_interrupted", "spawned":True,
                               "interrupted":True, "code":-signal.SIGKILL, "cleanup":False})
            self.assert_not_executing(pid)


if __name__ == "__main__":
    unittest.main()
