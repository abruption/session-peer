"""Offline harness checks: fake APIs and an owned Python sleeper, never Codex."""
import os
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import native_fixture as fixture


class FixtureBudget(unittest.TestCase):
    def test_failed_case_stops_batch_and_removes_its_temporary_home(self):
        with tempfile.TemporaryDirectory(prefix="codex-batch-", dir=os.environ.get("TMPDIR")) as scratch:
            argv = ['fixture', '--run-native-fixture', '--temp-root', scratch, '--repetitions', '2']
            with mock.patch.object(sys, 'argv', argv), \
                    mock.patch.object(fixture, 'native_version', return_value=('/fake/codex', 'codex-cli 0.159.2')), \
                    mock.patch.object(fixture, 'run_case', side_effect=TimeoutError('fixture_case_deadline')) as case:
                with self.assertRaises(TimeoutError):
                    fixture.main()
            case.assert_called_once()
            self.assertEqual(os.listdir(scratch), [])

    def test_version_timeout_is_bounded_and_fixed(self):
        with mock.patch.object(fixture.shutil, "which", return_value="/fake/codex"), \
                mock.patch.object(fixture.subprocess, "check_output",
                    side_effect=subprocess.TimeoutExpired("private-command", 5)) as probe:
            with self.assertRaisesRegex(RuntimeError, "^fixture_version_deadline$"):
                fixture.native_version()
        probe.assert_called_once_with(["/fake/codex", "--version"], text=True, timeout=5)

    def test_missing_executable_never_launches(self):
        with mock.patch.object(fixture.shutil, "which", return_value=None), \
                mock.patch.object(fixture.subprocess, "check_output") as probe:
            with self.assertRaisesRegex(RuntimeError, "^fixture_executable_missing$"):
                fixture.native_version()
        probe.assert_not_called()

    def test_delayed_waits_share_one_budget(self):
        clock = [10.0]
        event = mock.Mock()

        def delayed_api(timeout):
            clock[0] += timeout
            return False

        event.wait.side_effect = delayed_api
        with mock.patch.object(fixture.time, "monotonic", side_effect=lambda: clock[0]):
            self.assertFalse(fixture.wait_with_budget(event, 0.75, 11.0))
            with self.assertRaisesRegex(TimeoutError, "fixture_case_deadline"):
                fixture.wait_with_budget(event, 10, 11.0)
            with self.assertRaises(TimeoutError):
                fixture.wait_with_budget(event, 10, 11.0)
        self.assertEqual(event.wait.call_args_list, [mock.call(0.75), mock.call(0.25)])

    def test_expired_budget_cannot_pass_even_with_ready_event(self):
        event = threading.Event()
        event.set()
        with mock.patch.object(fixture.time, "monotonic", return_value=12):
            with self.assertRaises(TimeoutError):
                fixture.wait_with_budget(event, 10, 11)

    def test_stopped_watchdog_never_signals(self):
        done, hit, errors = threading.Event(), threading.Event(), []
        done.set()
        with mock.patch.object(fixture, "terminate_owned_group") as terminate:
            fixture.deadline_watchdog(object(), time.monotonic(), done, hit, errors)
        terminate.assert_not_called()
        self.assertFalse(hit.is_set())
        self.assertEqual(errors, [])

    @unittest.skipUnless(os.name == "posix", "owned POSIX process group")
    def test_deadline_kills_term_resistant_owned_process_before_reaping(self):
        # TMPDIR is selected by the invoking review/test workflow.
        with tempfile.TemporaryDirectory(prefix="codex-steer-watchdog-",
                                         dir=os.environ.get("TMPDIR")) as scratch:
            process = subprocess.Popen([sys.executable, "-I", "-c",
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(60)"], cwd=scratch,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                start_new_session=True)
            watcher = None
            done, hit, errors = threading.Event(), threading.Event(), []
            try:
                self.assertTrue(select.select([process.stdout], [], [], 3)[0], "dummy did not start")
                self.assertEqual(process.stdout.readline(), b"ready\n")
                started = time.monotonic()
                watcher = threading.Thread(target=fixture.deadline_watchdog,
                    args=(process, started + 0.1, done, hit, errors), daemon=True)
                watcher.start()
                watcher.join(timeout=8)
                self.assertFalse(watcher.is_alive(), "watchdog failed to finish")
                self.assertTrue(hit.is_set())
                self.assertEqual(errors, [])
                self.assertIsNone(process.returncode, "leader was reaped by watchdog")
                # The group has received KILL; normal cleanup owns the sole reap.
                fixture.kill_owned(process)
                self.assertEqual(process.returncode, -signal.SIGKILL)
                self.assertLess(time.monotonic() - started, 8)
            finally:
                done.set()
                if watcher is not None:
                    watcher.join()
                if process.returncode is None:
                    fixture.kill_owned(process)
                process.stdout.close()


if __name__ == "__main__":
    unittest.main()
