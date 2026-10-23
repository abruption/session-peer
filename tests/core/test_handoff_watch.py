"""Bounded, read-only sampled history; no model or native session is used."""
import argparse
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import signal
import select
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

import session_peer as peer


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds


@unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "POSIX ledger and pipes")
class HandoffWatch(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codex-watch-", dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(temporary.cleanup)
        self.ledger = peer.HandoffLedger(Path(temporary.name) / "ledger")
        self.epoch = self.ledger.initialize()
        binding = {"agent": "claude", "destination": ["local"], "target": str(os.getpid()),
                   "home": None, "payloadDigest": "a" * 64}
        self.epoch, self.record = self.ledger.prepare(binding, "tg1:" + "a" * 64)
        self.args = argparse.Namespace(correlation_id=self.record["id"], watch_timeout=3,
                                       interval_ms=1000, json=True, no_update_notice=True)
        self.clock = Clock()

    def invoke(self, lookup=None, stream=None, *, real_clock=False):
        output = stream if stream is not None else io.StringIO()
        popen = peer.subprocess.Popen
        self.output_processes = []
        def output_helper(command, **kwargs):
            self.assertIsNotNone(stream, "unexpected process during captured watch")
            self.assertEqual(command[:5], [peer.sys.executable, "-I", "-S", "-c", peer.HANDOFF_WATCH_WRITER_SCRIPT])
            self.assertEqual(command[5], str(os.getpid()))
            self.assertEqual(len(command), 7)
            self.assertGreater(float(command[6]), peer.handoff_now())
            self.assertEqual(kwargs["stdout"], stream.fileno())
            self.assertEqual(kwargs["env"], {})
            self.assertTrue(kwargs["close_fds"])
            self.assertTrue(kwargs["start_new_session"])
            process = popen(command, **kwargs)
            self.output_processes.append(process)
            return process
        with contextlib.ExitStack() as stack:
            if not real_clock:
                stack.enter_context(mock.patch.object(peer, "handoff_now", side_effect=lambda: self.clock.now))
                stack.enter_context(mock.patch.object(peer.time, "sleep", side_effect=self.clock.sleep))
            stack.enter_context(mock.patch.object(peer, "handoff_root", return_value=self.ledger.root))
            if lookup is not None:
                stack.enter_context(mock.patch.object(peer.HandoffLedger, "record", side_effect=lookup))
            for owner, name in ((peer.HandoffLedger, "_save"), (peer, "handoff_wait"),
                                (peer, "post_to_socket"), (peer, "handoff_codex_submit")):
                stack.enter_context(mock.patch.object(owner, name, side_effect=AssertionError("watch performed an effect")))
            stack.enter_context(mock.patch.object(peer.subprocess, "Popen", side_effect=output_helper))
            stack.enter_context(contextlib.redirect_stdout(output))
            code = peer.cmd_handoff_watch(self.args)
        if stream is not None:
            self.assertEqual(len(self.output_processes), 1, "expected only the owned output helper")
        return code, [json.loads(line) for line in output.getvalue().splitlines()] if stream is None else None

    def snapshot(self):
        return {path.name: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
                for path in self.ledger.root.iterdir() if path.is_file()}

    def test_ascii_parsers(self):
        for value in ("1", "30", "60"):
            self.assertEqual(peer.handoff_watch_timeout(value), int(value))
        for value in ("1000", "3000", "5000"):
            self.assertEqual(peer.handoff_watch_interval(value), int(value))
        for parser, values in ((peer.handoff_watch_timeout, ("0", "61", "01", "１", "1.0")),
                               (peer.handoff_watch_interval, ("999", "5001", "01000", "１０００", "+1000"))):
            for value in values:
                with self.assertRaises(argparse.ArgumentTypeError):
                    parser(value)

    def test_real_ledger_is_unchanged_and_unchanged_samples_are_suppressed(self):
        before = self.snapshot()
        code, frames = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual([row["event"] for row in frames], ["snapshot", "end"])
        self.assertEqual(frames[-1]["samples"], 3)
        self.assertEqual(frames[-1]["snapshotsEmitted"], 1)
        self.assertTrue(before == self.snapshot(), "watch mutated ledger bytes or metadata")
        self.assertEqual(set(frames[0]) - {"observedAtUtcMs"},
                         {"schemaVersion", "ok", "host", "command", "operation", "event", "sequence", "historyPhase", "handoff"})

    def test_phase_changes_emit_and_epoch_change_stops_before_new_facts(self):
        changed = copy.deepcopy(self.record)
        changed.update(phase="attempted", submission="unknown")
        rows = iter([(self.epoch, self.record), (self.epoch, changed),
                     (str(peer.uuid.uuid4()), self.record)])
        code, frames = self.invoke(lambda *a, **kw: next(rows))
        self.assertEqual(code, 1)
        self.assertEqual([row.get("sequence") for row in frames[:-1]], [1, 2])
        self.assertEqual(frames[-1]["reason"], "history_changed")
        self.assertEqual(frames[-1]["samples"], 3)

    def test_missing_history_is_closed_error_without_fabricated_handoff(self):
        code, frames = self.invoke(lambda *a, **kw: (_ for _ in ()).throw(peer.handoff_error("handoff_id_unknown")))
        self.assertEqual(code, 1)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["queryContext"], "id_unknown")
        self.assertNotIn("handoff", frames[0])
        self.assertNotIn("ledgerEpoch", frames[0])

    def test_busy_and_unsafe_history_do_not_claim_it_is_missing(self):
        for reason in ("handoff_storage_busy", "unsafe_handoff_storage", "handoff_history_unavailable"):
            self.clock.now = 0
            def lookup(*args, **kwargs):
                raise peer.handoff_error(reason)
            code, frames = self.invoke(lookup)
            self.assertEqual(code, 1)
            self.assertEqual(frames[0]["reason"], "history_unavailable")
            self.assertNotIn("queryContext", frames[0])

    def test_missing_files_have_positive_missing_context(self):
        with mock.patch.object(peer, "handoff_private_stat", side_effect=FileNotFoundError()):
            code, frames = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(frames[0]["queryContext"], "ledger_missing")

    def test_lock_sleep_exhaustion_prevents_second_attempt_or_snapshot_read(self):
        attempts = []
        def lock(*args):
            attempts.append(1)
            self.clock.now = self.args.watch_timeout - peer.HANDOFF_WATCH_FINISH_SECONDS - 0.005
            raise BlockingIOError()
        with mock.patch.object(peer.fcntl, "flock", side_effect=lock), \
                mock.patch.object(peer.os, "fdopen", side_effect=AssertionError("read after deadline")), \
                mock.patch.object(peer.HandoffLedger, "_validate_record", side_effect=AssertionError("validation after deadline")):
            code, frames = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(frames[0]["reason"], "duration_elapsed")
        self.assertNotIn("queryContext", frames[0])

    def test_lock_acquisition_at_deadline_does_not_start_snapshot_read(self):
        def lock(*args):
            self.clock.now = self.args.watch_timeout - peer.HANDOFF_WATCH_FINISH_SECONDS
        with mock.patch.object(peer.fcntl, "flock", side_effect=lock), \
                mock.patch.object(peer.os, "fdopen", side_effect=AssertionError("read after deadline")), \
                mock.patch.object(peer.HandoffLedger, "_validate_record", side_effect=AssertionError("validation after deadline")):
            code, frames = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(frames[0]["reason"], "duration_elapsed")
        self.assertNotIn("queryContext", frames[0])

    def test_parse_consuming_budget_does_not_begin_record_validation(self):
        original = peer.handoff_json
        def parse(*args, **kwargs):
            result = original(*args, **kwargs)
            self.clock.now = self.args.watch_timeout - peer.HANDOFF_WATCH_FINISH_SECONDS
            return result
        with mock.patch.object(peer, "handoff_json", side_effect=parse), \
                mock.patch.object(peer.HandoffLedger, "_validate_record", side_effect=AssertionError("validation after deadline")):
            code, frames = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(frames[0]["reason"], "duration_elapsed")
        self.assertNotIn("queryContext", frames[0])

    def test_initial_lookup_and_clock_share_original_deadline(self):
        record = copy.deepcopy(self.record)
        record["capability"] = {"revoked": False}
        calls = []
        def lookup(*args, **kwargs):
            calls.append((args, kwargs))
            self.clock.now += 0.25
            return self.epoch, record
        def clock(*args, **kwargs):
            self.assertEqual(args[1], 2.9)
            self.assertEqual(kwargs, {"read_only": True})
            self.clock.now = 2.9
        with mock.patch.object(peer, "handoff_channel_epoch", side_effect=clock):
            code, frames = self.invoke(lookup)
        self.assertEqual(code, 0)
        self.assertEqual(calls[0][0][1], 2.9)
        self.assertEqual(calls[0][1], {"read_only": True})
        self.assertEqual(frames[-1]["snapshotsEmitted"], 0)

    def test_ack_does_not_end_watch_and_revoked_capability_never_queries_clock(self):
        record = copy.deepcopy(self.record)
        record.update(phase="terminal", submission="submitted", ackRequested=True,
                      ack={"status": "acknowledged", "assurance": "operator_confirmed", "receivedAtUtcMs": 2, "late": False})
        for ack in (record["ack"], None):
            self.clock.now = 0
            record["ack"] = ack
            record["capability"] = {"revoked": True}
            with mock.patch.object(peer, "handoff_channel_epoch", side_effect=AssertionError("unexpected clock query")):
                code, frames = self.invoke(lambda *a, **kw: (self.epoch, record))
            self.assertEqual(code, 0)
            self.assertEqual(frames[-1]["samples"], 3)

    def test_output_caps_reserve_end_and_fail_without_private_error(self):
        with mock.patch.object(peer, "HANDOFF_WATCH_OUTPUT_BYTES", 2100):
            code, frames = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["reason"], "output_limit")

    def test_sixty_seconds_never_exceeds_sixty_one_samples(self):
        self.args.watch_timeout = 60
        code, frames = self.invoke()
        self.assertEqual(code, 0)
        self.assertLessEqual(frames[-1]["samples"], 61)
        self.assertEqual(self.clock.now, 59.9)

    def test_retention_is_only_a_memory_projection(self):
        boot = "b" * 64
        with self.ledger.transaction() as state:
            state["records"][self.record["id"]].update(historyBoot=boot, createdNs=1)
        before = self.snapshot()
        with mock.patch.object(peer, "handoff_boot_clock", return_value=boot), \
                mock.patch.object(peer, "handoff_now_ns", return_value=1 + 30 * 86400 * 1000000000):
            code, frames = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(frames[0]["historyPhase"], "tombstone")
        self.assertTrue(before == self.snapshot(), "watch persisted retention")

    def test_quarantined_satisfied_wait_stays_failure_without_repair(self):
        with self.ledger.transaction() as state:
            record = state["records"][self.record["id"]]
            record.update(phase="terminal", submission="submitted", ackRequested=True,
                          native={"ok": True, "target": {"pid": os.getpid(), "name": "fixture"}, "chars": 4, "dryRun": False},
                          ack={"status": "acknowledged", "assurance": "operator_confirmed", "receivedAtUtcMs": 2,
                               "late": False, "receiptId": None, "classifiedClockEpoch": None})
            record["waits"] = [{"for": "acknowledged", "status": "satisfied", "operationId": str(peer.uuid.uuid4()),
                                "deadlineAtUtcMs": 1, "deadlineNs": 1000000, "clockEpoch": None}]
        self.ledger.quarantine_restored()
        before = self.snapshot()
        code, frames = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["reason"], "history_unavailable")
        self.assertNotIn("queryContext", frames[0])
        self.assertTrue(before == self.snapshot(), "watch repaired quarantined history")

    def test_real_pipe_never_changes_flags_and_reaps_on_interrupt_or_broken_pipe(self):
        for interrupt in (False, True):
            read_fd, write_fd = os.pipe()
            stream = os.fdopen(write_fd, "w")
            # Darwin may expose an internal "has been written" bit after the
            # first write. Establish it before comparing restorable flags.
            os.write(write_fd, b"x")
            os.read(read_fd, 1)
            original = peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL)
            try:
                if not interrupt:
                    os.close(read_fd)
                    read_fd = None
                    code, _ = self.invoke(stream=stream, real_clock=True)
                    self.assertEqual(code, 1)
                else:
                    def lookup(*args, **kwargs):
                        raise KeyboardInterrupt
                    code, _ = self.invoke(lookup, stream, real_clock=True)
                    self.assertEqual(code, 130)
                    data = os.read(read_fd, 4096)
                    self.assertEqual(json.loads(data)["reason"], "interrupted")
                self.assertEqual(peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL), original)
                self.assertTrue(all(process.poll() is not None for process in self.output_processes))
            finally:
                stream.close()
                if read_fd is not None:
                    os.close(read_fd)

    def test_full_real_pipe_is_bounded_without_inherited_flag_mutation(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(write_fd, "w")
        os.write(write_fd, b"x")
        os.read(read_fd, 1)
        original = peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL)
        try:
            peer.fcntl.fcntl(write_fd, peer.fcntl.F_SETFL, original | os.O_NONBLOCK)
            try:
                while True:
                    os.write(write_fd, b"x" * 4096)
            except BlockingIOError:
                pass
            peer.fcntl.fcntl(write_fd, peer.fcntl.F_SETFL, original)
            self.args.watch_timeout = 1
            started = time.monotonic()
            with mock.patch.object(peer.fcntl, "fcntl", side_effect=AssertionError("inherited flag mutation")):
                code, _ = self.invoke(stream=stream, real_clock=True)
            self.assertEqual(code, 1)
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertEqual(peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL), original)
            self.assertTrue(all(process.poll() is not None for process in self.output_processes))
        finally:
            stream.close()
            os.close(read_fd)

    def test_unknown_frame_completion_suppresses_later_frames_and_reaps(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(write_fd, "w")
        writer = None
        try:
            flags = peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL)
            peer.fcntl.fcntl(write_fd, peer.fcntl.F_SETFL, flags | os.O_NONBLOCK)
            try:
                while True:
                    os.write(write_fd, b"x" * 4096)
            except BlockingIOError:
                pass
            peer.fcntl.fcntl(write_fd, peer.fcntl.F_SETFL, flags)
            os.read(read_fd, 4096)
            writer = peer.HandoffWatchOutput(stream, peer.handoff_now() + 0.4)
            self.assertEqual(writer.write("s" * 15000), "output_unavailable")
            self.assertTrue(writer.damaged)
            self.assertEqual(writer.write("end", end=True), "output_unavailable")
            self.assertTrue(writer.close())
            self.assertIsNotNone(writer.process.poll())
        finally:
            if writer is not None:
                writer.close()
            stream.close()
            os.close(read_fd)

    def test_sigint_during_blocked_output_kills_and_reaps_owned_helper(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(write_fd, "w")
        timer = None
        try:
            flags = peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL)
            peer.fcntl.fcntl(write_fd, peer.fcntl.F_SETFL, flags | os.O_NONBLOCK)
            try:
                while True:
                    os.write(write_fd, b"x" * 4096)
            except BlockingIOError:
                pass
            peer.fcntl.fcntl(write_fd, peer.fcntl.F_SETFL, flags)
            before = peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL)
            timer = threading.Timer(0.1, lambda: os.kill(os.getpid(), signal.SIGINT))
            timer.start()
            with mock.patch.object(peer.fcntl, "fcntl", side_effect=AssertionError("inherited flag mutation")):
                code, _ = self.invoke(stream=stream, real_clock=True)
            self.assertEqual(code, 130)
            self.assertTrue(all(process.poll() is not None for process in self.output_processes))
            self.assertEqual(peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL), before)
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
            stream.close()
            os.close(read_fd)

    def test_tty_output_completes_without_changing_inherited_flags(self):
        master, slave = os.openpty()
        stream = os.fdopen(slave, "w")
        try:
            os.write(slave, b"x")
            os.read(master, 1)
            before = peer.fcntl.fcntl(slave, peer.fcntl.F_GETFL)
            self.args.watch_timeout = 1
            with mock.patch.object(peer.fcntl, "fcntl", side_effect=AssertionError("inherited flag mutation")):
                code, _ = self.invoke(stream=stream, real_clock=True)
            self.assertEqual(code, 0)
            rows = [json.loads(line) for line in os.read(master, 8192).decode().splitlines()]
            self.assertEqual([row["event"] for row in rows], ["snapshot", "end"])
            self.assertEqual(peer.fcntl.fcntl(slave, peer.fcntl.F_GETFL), before)
            self.assertTrue(all(process.poll() is not None for process in self.output_processes))
        finally:
            stream.close()
            os.close(master)

    def test_control_socket_close_error_does_not_skip_helper_reaping(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(write_fd, "w")
        writer = None
        try:
            writer = peer.HandoffWatchOutput(stream, peer.handoff_now() + 1)
            channel = writer.channel
            def close_and_fail():
                channel.close()
                raise OSError()
            writer.channel = mock.Mock(wraps=channel)
            writer.channel.close.side_effect = close_and_fail
            self.assertTrue(writer.close())
            self.assertIsNotNone(writer.process.poll())
        finally:
            if writer is not None:
                writer.close()
            stream.close()
            os.close(read_fd)

    def test_helper_exits_if_expected_parent_already_died_before_start(self):
        process = subprocess.Popen(
            [peer.sys.executable, "-I", "-S", "-c", peer.HANDOFF_WATCH_WRITER_SCRIPT,
             str(os.getpid() + 1000000), repr(peer.handoff_now() + 1)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={}, close_fds=True, start_new_session=True)
        try:
            self.assertEqual(process.wait(timeout=2), 1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1)
            process.stdin.close()
            process.stdout.close()

    def test_blocked_helper_exits_after_parent_death_or_stop(self):
        # The harness loads the source module so this also tests an in-memory
        # generated build without overwriting the checked-in standalone file.
        script = '''
import sys
from pathlib import Path
import session_peer as peer
exec(Path("session_peer_core/handoff_watch.py").read_text(), peer.__dict__)
writer = peer.HandoffWatchOutput(sys.stdout, peer.handoff_now() + 0.8)
print(writer.process.pid, file=sys.stderr, flush=True)
writer.write("blocked output")
writer.close()
'''
        for stop in (False, True):
            read_fd, write_fd = os.pipe()
            parent = None
            try:
                flags = peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL)
                peer.fcntl.fcntl(write_fd, peer.fcntl.F_SETFL, flags | os.O_NONBLOCK)
                try:
                    while True:
                        os.write(write_fd, b"x" * 4096)
                except BlockingIOError:
                    pass
                peer.fcntl.fcntl(write_fd, peer.fcntl.F_SETFL, flags)
                parent = subprocess.Popen([peer.sys.executable, "-c", script],
                                          stdout=write_fd, stderr=subprocess.PIPE,
                                          close_fds=True, start_new_session=True)
                self.assertTrue(select.select([parent.stderr], [], [], 2)[0])
                worker_pid = int(parent.stderr.readline())
                time.sleep(0.05)
                os.kill(parent.pid, signal.SIGSTOP if stop else signal.SIGKILL)
                if not stop:
                    parent.wait(timeout=1)
                limit = time.monotonic() + 2
                while True:
                    result = subprocess.run(["ps", "-o", "stat=", "-p", str(worker_pid)],
                                            capture_output=True, text=True, timeout=1)
                    state = result.stdout.strip()
                    if not state or state.startswith("Z"):
                        break
                    if time.monotonic() >= limit:
                        self.fail("output helper survived its owner and original budget")
                    time.sleep(0.02)
            finally:
                if parent is not None:
                    if parent.poll() is None:
                        parent.kill()
                    parent.wait(timeout=1)
                    parent.stderr.close()
                os.close(read_fd)
                os.close(write_fd)

    def test_unexpected_exceptions_never_emit_success_or_private_diagnostics(self):
        for kind in (RuntimeError, MemoryError):
            self.clock.now = 0
            def lookup(*args, **kwargs):
                raise kind("private diagnostic")
            code, frames = self.invoke(lookup)
            self.assertEqual(code, 1)
            self.assertFalse(frames[-1]["ok"])
            self.assertEqual(frames[-1]["reason"], "history_unavailable")
            self.assertNotIn("queryContext", frames[-1])
            self.assertNotIn("private diagnostic", json.dumps(frames))

    def signal_from_unmasked_thread(self):
        def interrupt():
            signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})
            for unused in range(3):
                time.sleep(0.005)
                os.kill(os.getpid(), signal.SIGINT)
        sender = threading.Thread(target=interrupt)
        sender.start()
        time.sleep(0.04)
        sender.join()

    def test_sigint_between_spawn_and_handle_registration_is_deferred_and_reaped(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(write_fd, "w")
        processes = []
        popen = peer.subprocess.Popen
        previous_handler = signal.getsignal(signal.SIGINT)
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        def spawn(*args, **kwargs):
            process = popen(*args, **kwargs)
            processes.append(process)
            self.signal_from_unmasked_thread()
            return process
        try:
            with mock.patch.object(peer.subprocess, "Popen", side_effect=spawn):
                code, unused = self.invoke(stream=stream, real_clock=True)
            self.assertEqual(code, 130)
            self.assertEqual(len(processes), 1)
            self.assertIsNotNone(processes[0].poll())
            self.assertEqual(signal.getsignal(signal.SIGINT), previous_handler)
            self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, set()), previous_mask)
        finally:
            stream.close()
            os.close(read_fd)

    def test_scoped_interrupt_deferral_preserves_custom_and_ignored_handlers(self):
        previous = signal.getsignal(signal.SIGINT)
        calls = []
        def custom(signum, frame):
            calls.append(signum)
        try:
            signal.signal(signal.SIGINT, custom)
            with peer.handoff_watch_defer_interrupt():
                self.signal_from_unmasked_thread()
                self.assertEqual(calls, [])
            self.assertEqual(calls, [signal.SIGINT])
            self.assertIs(signal.getsignal(signal.SIGINT), custom)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            with peer.handoff_watch_defer_interrupt():
                self.signal_from_unmasked_thread()
            self.assertEqual(signal.getsignal(signal.SIGINT), signal.SIG_IGN)
        finally:
            signal.signal(signal.SIGINT, previous)

    def test_repeated_sigint_during_final_wait_is_deferred_until_reaping(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(write_fd, "w")
        popen = peer.subprocess.Popen
        def spawn(*args, **kwargs):
            process = popen(*args, **kwargs)
            wait = process.wait
            def interrupted_wait(*values, **options):
                self.signal_from_unmasked_thread()
                return wait(*values, **options)
            process.wait = interrupted_wait
            return process
        try:
            def unavailable(*args, **kwargs):
                raise peer.handoff_error("handoff_id_unknown")
            with mock.patch.object(peer.subprocess, "Popen", side_effect=spawn):
                code, unused = self.invoke(unavailable, stream, real_clock=True)
            self.assertEqual(code, 130)
            self.assertTrue(all(process.poll() is not None for process in self.output_processes))
        finally:
            stream.close()
            os.close(read_fd)

    def test_snapshot_stat_exhaustion_does_not_open_snapshot(self):
        private_stat = peer.handoff_private_stat
        opened = []
        original_open = peer.os.open
        def stat_then_expire(path, *args):
            result = private_stat(path, *args)
            if path.name == "ledger.json":
                self.clock.now = self.args.watch_timeout - peer.HANDOFF_WATCH_FINISH_SECONDS
            return result
        def record_open(path, *args, **kwargs):
            opened.append(Path(path).name)
            return original_open(path, *args, **kwargs)
        with mock.patch.object(peer, "handoff_private_stat", side_effect=stat_then_expire), \
                mock.patch.object(peer.os, "open", side_effect=record_open):
            code, frames = self.invoke()
        self.assertEqual(code, 0)
        self.assertNotIn("ledger.json", opened)
        self.assertEqual(frames[-1]["reason"], "duration_elapsed")

    def test_readonly_validation_runs_after_snapshot_lock_is_released(self):
        validate = peer.HandoffLedger._validate_record
        checked = []
        def unlocked_validation(record):
            fd = os.open(str(self.ledger.root / "ledger.lock"), os.O_RDWR)
            try:
                peer.fcntl.flock(fd, peer.fcntl.LOCK_EX | peer.fcntl.LOCK_NB)
                checked.append(True)
            finally:
                os.close(fd)
            return validate(record)
        with mock.patch.object(peer.HandoffLedger, "_validate_record", side_effect=unlocked_validation):
            code, frames = self.invoke()
        self.assertEqual(code, 0)
        self.assertEqual(len(checked), 3)

    def test_inherited_nonblocking_stdout_waits_for_drain_and_succeeds(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(write_fd, "w")
        drainer = None
        try:
            flags = peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL)
            peer.fcntl.fcntl(write_fd, peer.fcntl.F_SETFL, flags | os.O_NONBLOCK)
            try:
                while True:
                    os.write(write_fd, b"x" * 4096)
            except BlockingIOError:
                pass
            before = peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL)
            drainer = threading.Timer(0.1, lambda: os.read(read_fd, 1024 * 1024))
            drainer.start()
            self.args.watch_timeout = 1
            with mock.patch.object(peer.fcntl, "fcntl", side_effect=AssertionError("inherited flag mutation")):
                code, unused = self.invoke(stream=stream, real_clock=True)
            drainer.join()
            self.assertEqual(code, 0)
            rows = [json.loads(line) for line in os.read(read_fd, 8192).decode().splitlines()]
            self.assertEqual([row["event"] for row in rows], ["snapshot", "end"])
            self.assertEqual(peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL), before)
        finally:
            if drainer is not None:
                drainer.cancel()
                drainer.join()
            stream.close()
            os.close(read_fd)

    def test_sigint_after_snapshot_with_now_full_pipe_has_immediate_finish_budget(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(write_fd, "w")
        self.args.watch_timeout = 60
        def block_and_interrupt(seconds):
            flags = peer.fcntl.fcntl(write_fd, peer.fcntl.F_GETFL)
            peer.fcntl.fcntl(write_fd, peer.fcntl.F_SETFL, flags | os.O_NONBLOCK)
            try:
                while True:
                    os.write(write_fd, b"x" * 4096)
            except BlockingIOError:
                pass
            finally:
                peer.fcntl.fcntl(write_fd, peer.fcntl.F_SETFL, flags)
            os.kill(os.getpid(), signal.SIGINT)
        try:
            started = time.monotonic()
            with mock.patch.object(peer.time, "sleep", side_effect=block_and_interrupt):
                code, unused = self.invoke(stream=stream, real_clock=True)
            self.assertEqual(code, 130)
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(all(process.poll() is not None for process in self.output_processes))
        finally:
            stream.close()
            os.close(read_fd)

    def test_cleanup_failure_requires_nonzero_exit_even_after_end_frame(self):
        with mock.patch.object(peer.HandoffWatchOutput, "close", return_value=False):
            code, frames = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(frames[-1]["reason"], "duration_elapsed")


if __name__ == "__main__":
    unittest.main()
