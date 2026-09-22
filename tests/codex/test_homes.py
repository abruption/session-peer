"""Codex contract tests: fixture DBs and process boundaries, no live agents."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock

import session_peer as peer

from tests.codex.support import OTHER, THREAD


class CodexHomes(unittest.TestCase):
    """An inactive saved copy must not win merely because it is in ~/.codex."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.user = Path(directory.name).resolve()
        self.default = self.user / ".codex"
        self.account = self.user / "Library/Application Support/orca/codex-accounts/account-a/home"
        self.make_home(self.default)
        self.make_home(self.account)
        self.patch(mock.patch.object(peer.Path, "home", return_value=self.user))
        self.patch(mock.patch.dict(os.environ))
        os.environ.pop("CODEX_HOME", None)
        os.environ.pop("SESSION_PEER_CODEX_HOMES", None)
        self.patch(mock.patch.object(peer.sys, "platform", "darwin"))
        self.patch(mock.patch.object(peer, "codex_executable", return_value="codex"))
        self.queue = self.patch(mock.patch.object(peer.subprocess, "run", return_value=
            subprocess.CompletedProcess([], 0, "Queued message queue-id for thread " + THREAD + ".\n", "")))

    def patch(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def make_home(self, home, thread=THREAD, archived=0):
        home.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(sqlite3.connect(home / "state_5.sqlite")) as conn:
            conn.execute("CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)")
            conn.execute("INSERT INTO threads VALUES (?, 'copy', '/project', 1, ?, '/missing-rollout')", (thread, archived))
            conn.commit()

    def send(self, *options):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = peer.main(["send", "--to", "codex:" + THREAD, "--no-from", "--no-reply-to",
                              "--json", *options, "test"])
        return code, json.loads(output.getvalue())

    def test_orca_duplicate_rejects_implicit_send_and_dry_run(self):
        before = {p: (p / "state_5.sqlite").read_bytes() for p in (self.default, self.account)}
        for flags in ((), ("--dry-run",)):
            code, result = self.send(*flags)
            self.assertEqual(code, 1)
            self.assertFalse(result["ok"])
            self.assertEqual(result["codexHomeResolution"]["reason"],
                             "inactive_queue_requires_opt_in")
            for expected in (str(self.default), str(self.account),
                             "--allow-inactive-codex-home"):
                self.assertIn(expected, result["error"])
        self.queue.assert_not_called()
        for path, original in before.items():
            self.assertEqual((path / "state_5.sqlite").read_bytes(), original)

    def test_one_stable_live_writer_selects_its_home_and_revalidates(self):
        inactive = {"activity": "inactive", "writerLock": "free",
                    "reason": "kernel_lock_free"}
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable", "reason": "stable_live_writer"}
        with mock.patch.object(peer, "inspect_codex_writer",
                               side_effect=[inactive, active, inactive, active]) as inspect:
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.account))
        self.assertEqual(result["codexHomeResolution"]["status"], "selected")
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "single_stable_live_writer")
        self.assertEqual(self.queue.call_args.kwargs["env"]["CODEX_HOME"], str(self.account))
        self.assertEqual(inspect.call_count, 4)

    def test_dry_run_selects_live_writer_without_queue_or_revalidation(self):
        inactive = {"activity": "inactive", "writerLock": "absent",
                    "reason": "lock_absent"}
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable", "reason": "stable_live_writer"}
        with mock.patch.object(peer, "inspect_codex_writer",
                               side_effect=[inactive, active]) as inspect:
            code, result = self.send("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.account))
        self.assertFalse(result["submitted"])
        self.assertEqual(inspect.call_count, 2)
        self.queue.assert_not_called()

    def test_live_writer_can_select_the_only_saved_copy_outside_default(self):
        with contextlib.closing(sqlite3.connect(self.default / "state_5.sqlite")) as conn:
            conn.execute("DELETE FROM threads")
            conn.commit()
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable", "reason": "stable_live_writer"}
        with mock.patch.object(peer, "inspect_codex_writer", side_effect=[active, active]):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.account))
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "single_stable_live_writer")

    def test_multiple_live_writers_are_structured_ambiguity(self):
        active_a = {"activity": "live_writer", "writerLock": "held", "ownerPid": 41,
                    "ownerStable": True, "ownerStartTime": "stable", "reason": "stable_live_writer"}
        active_b = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                    "ownerStable": True, "ownerStartTime": "stable", "reason": "stable_live_writer"}
        with mock.patch.object(peer, "inspect_codex_writer", side_effect=[active_a, active_b]):
            code, result = self.send()
        self.assertEqual(code, 1)
        resolution = result["codexHomeResolution"]
        self.assertEqual(resolution["status"], "ambiguous")
        self.assertEqual(resolution["reason"], "multiple_live_writers")
        self.assertIsNone(resolution["selected"])
        self.queue.assert_not_called()

    def test_unknown_competing_writer_prevents_selection(self):
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 41,
                  "ownerStable": True, "ownerStartTime": "stable", "reason": "stable_live_writer"}
        unknown = {"activity": "unknown", "writerLock": "held",
                   "reason": "lsof_unavailable"}
        with mock.patch.object(peer, "inspect_codex_writer", side_effect=[active, unknown]):
            code, result = self.send()
        self.assertEqual(code, 1)
        self.assertEqual(result["codexHomeResolution"]["status"], "unknown")
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "active_writer_unverified")
        self.queue.assert_not_called()

    def test_unknown_probe_prevents_explicit_selection(self):
        unknown = {"activity": "unknown", "writerLock": "held",
                   "reason": "lsof_unavailable"}
        inactive = {"activity": "inactive", "writerLock": "free",
                    "reason": "kernel_lock_free"}
        with mock.patch.object(peer, "inspect_codex_writer",
                               side_effect=[unknown, inactive]):
            code, result = self.send("--codex-home", str(self.account),
                                     "--allow-inactive-codex-home")
        self.assertEqual(code, 1)
        self.assertEqual(result["codexHomeResolution"]["status"], "unknown")
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "active_writer_unverified")
        self.queue.assert_not_called()

    def test_writer_pid_change_before_queue_fails_closed(self):
        inactive = {"activity": "inactive", "writerLock": "free",
                    "reason": "kernel_lock_free"}
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable", "reason": "stable_live_writer"}
        changed = {**active, "ownerPid": 43}
        with mock.patch.object(peer, "inspect_codex_writer",
                               side_effect=[inactive, active, inactive, changed]):
            code, result = self.send()
        self.assertEqual(code, 1)
        self.assertEqual(result["codexHomeResolution"]["status"], "unknown")
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "writer_evidence_changed_before_queue")
        self.queue.assert_not_called()

    def test_writer_start_time_change_before_queue_fails_closed(self):
        inactive = {"activity": "inactive", "writerLock": "free",
                    "reason": "kernel_lock_free"}
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "first",
                  "reason": "stable_live_writer"}
        changed = {**active, "ownerStartTime": "reused-pid"}
        with mock.patch.object(peer, "inspect_codex_writer",
                               side_effect=[inactive, active, inactive, changed]):
            code, result = self.send()
        self.assertEqual(code, 1)
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "writer_evidence_changed_before_queue")
        self.queue.assert_not_called()

    def test_competing_writer_appearing_before_queue_fails_closed(self):
        inactive = {"activity": "inactive", "writerLock": "free",
                    "reason": "kernel_lock_free"}
        selected = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                    "ownerStable": True, "ownerStartTime": "stable", "reason": "stable_live_writer"}
        competitor = {**selected, "ownerPid": 41}
        with mock.patch.object(peer, "inspect_codex_writer",
                               side_effect=[inactive, selected, competitor, selected]):
            code, result = self.send()
        self.assertEqual(code, 1)
        self.assertEqual(result["codexHomeResolution"]["status"], "unknown")
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "writer_evidence_changed_before_queue")
        self.queue.assert_not_called()

    def test_configured_duplicate_rejected_without_macos_discovery(self):
        with mock.patch.object(peer.sys, "platform", "linux"):
            os.environ["SESSION_PEER_CODEX_HOMES"] = json.dumps([str(self.account)])
            code, result = self.send()
        self.assertEqual(code, 1)
        self.assertIn("--codex-home", result["error"])
        self.queue.assert_not_called()

    def test_explicit_live_writer_is_validated_and_revalidated(self):
        inactive = {"activity": "inactive", "writerLock": "free",
                    "reason": "kernel_lock_free"}
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable",
                  "reason": "stable_live_writer"}
        with mock.patch.object(peer, "inspect_codex_writer",
                               side_effect=[active, inactive, active, inactive]) as inspect:
            code, result = self.send("--codex-home", str(self.account))
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.account))
        self.assertEqual(result["codexHomeResolution"]["status"], "explicit")
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "explicit_live_writer")
        self.assertEqual(inspect.call_count, 4)
        self.assertEqual(self.queue.call_args.kwargs["env"]["CODEX_HOME"], str(self.account))

    def test_explicit_inactive_home_conflicting_with_live_writer_is_rejected(self):
        inactive = {"activity": "inactive", "writerLock": "free",
                    "reason": "kernel_lock_free"}
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable",
                  "reason": "stable_live_writer"}
        with mock.patch.object(peer, "inspect_codex_writer",
                               side_effect=[inactive, active]):
            code, result = self.send("--codex-home", str(self.default))
        self.assertEqual(code, 1)
        resolution = result["codexHomeResolution"]
        self.assertEqual(resolution["reason"],
                         "explicit_home_conflicts_with_live_writer")
        self.assertIsNone(resolution["selected"])
        self.assertIn(str(self.account), result["error"])
        self.queue.assert_not_called()

    def test_explicit_inactive_home_requires_opt_in(self):
        code, result = self.send("--codex-home", str(self.account))
        self.assertEqual(code, 1)
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "inactive_queue_requires_opt_in")
        self.assertIn("--allow-inactive-codex-home", result["error"])
        self.queue.assert_not_called()

    def test_inactive_opt_in_requires_explicit_home(self):
        code, result = self.send("--allow-inactive-codex-home")
        self.assertEqual(code, 1)
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "inactive_opt_in_requires_explicit_home")
        self.queue.assert_not_called()

    def test_explicit_inactive_opt_in_queues_selected_copy_and_revalidates(self):
        with mock.patch.object(peer, "inspect_codex_writer", wraps=peer.inspect_codex_writer) as inspect:
            code, result = self.send(
                "--codex-home", str(self.account), "--allow-inactive-codex-home"
            )
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.account))
        self.assertEqual(result["codexHomeResolution"]["status"], "explicit")
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "explicit_inactive_opt_in")
        self.assertEqual(inspect.call_count, 4)
        self.assertEqual(self.queue.call_args.kwargs["env"]["CODEX_HOME"], str(self.account))

    def test_explicit_inactive_dry_run_requires_and_accepts_opt_in(self):
        code, result = self.send(
            "--codex-home", str(self.account), "--allow-inactive-codex-home", "--dry-run"
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.account))
        self.assertEqual(result["status"], "validated")
        self.assertIs(result["submitted"], False)
        self.assertIs(result["consumptionConfirmed"], False)
        self.queue.assert_not_called()

    def test_environment_selection_still_checks_default_copy(self):
        os.environ["CODEX_HOME"] = str(self.account)
        with mock.patch.object(peer.sys, "platform", "linux"):
            code, result = self.send()
        self.assertEqual(code, 1)
        self.assertIn(str(self.default), result["error"])
        self.assertIn(str(self.account), result["error"])
        self.queue.assert_not_called()

    @unittest.skipIf(os.name == "nt", "hard links require platform-specific privileges")
    def test_hard_linked_rollouts_still_use_unique_live_writer(self):
        rollouts = self.user / "rollouts"
        rollouts.mkdir()
        default_rollout = rollouts / "default.jsonl"
        account_rollout = rollouts / "account.jsonl"
        default_rollout.write_text("fixture", encoding="utf-8")
        os.link(default_rollout, account_rollout)
        self.assertEqual(default_rollout.stat().st_ino, account_rollout.stat().st_ino)
        for home, rollout in ((self.default, default_rollout),
                              (self.account, account_rollout)):
            with contextlib.closing(sqlite3.connect(home / "state_5.sqlite")) as conn:
                conn.execute("UPDATE threads SET rollout_path=? WHERE id=?",
                             (str(rollout), THREAD))
                conn.commit()
        inactive = {"activity": "inactive", "writerLock": "free",
                    "reason": "kernel_lock_free"}
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable",
                  "reason": "stable_live_writer"}
        with mock.patch.object(peer, "inspect_codex_writer",
                               side_effect=[inactive, active, inactive, active]):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.account))
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "single_stable_live_writer")

    @unittest.skipIf(peer.fcntl is None, "POSIX flock is unavailable")
    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX UID is unavailable")
    def test_resolver_uses_real_advisory_lock_and_revalidates_it(self):
        with contextlib.closing(sqlite3.connect(self.account / "state_5.sqlite")) as conn:
            conn.execute("UPDATE threads SET id=?", (OTHER,))
            conn.commit()
        directory = self.default / "thread-writer-locks"
        directory.mkdir()
        lock = directory / f"{THREAD}.lock"
        lock.write_text("fixture", encoding="utf-8")
        child = subprocess.Popen([
            peer.sys.executable, "-c",
            "import fcntl,sys,time; f=open(sys.argv[1],'r+'); "
            "fcntl.flock(f,fcntl.LOCK_EX); print('ready',flush=True); time.sleep(60)",
            str(lock),
        ], stdout=subprocess.PIPE, text=True)

        def cleanup():
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            if child.stdout and not child.stdout.closed:
                child.stdout.close()

        self.addCleanup(cleanup)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        opener = [{"pid": child.pid, "uid": os.getuid(), "command": "codex",
                   "startTime": "stable"}]
        with mock.patch.object(peer, "_codex_lock_openers",
                               return_value=(opener, None)), \
             mock.patch.object(peer.time, "sleep"):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.default))
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "single_stable_live_writer")
        self.assertEqual(peer.probe_codex_writer_lock(lock),
                         ("held", "kernel_lock_held"))

    def test_archived_duplicate_is_not_assumed_inactive_or_safe(self):
        with contextlib.closing(sqlite3.connect(self.account / "state_5.sqlite")) as conn:
            conn.execute("UPDATE threads SET archived=1")
            conn.commit()
        code, result = self.send()
        self.assertEqual(code, 1)
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "inactive_queue_requires_opt_in")
        self.queue.assert_not_called()

    def test_unrelated_known_home_keeps_selected_destination(self):
        with contextlib.closing(sqlite3.connect(self.account / "state_5.sqlite")) as conn:
            conn.execute("UPDATE threads SET id=?", (OTHER,))
            conn.commit()
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable",
                  "reason": "stable_live_writer"}
        with mock.patch.object(peer, "inspect_codex_writer", side_effect=[active, active]):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.default))
        self.assertEqual(self.queue.call_args.kwargs["env"]["CODEX_HOME"], str(self.default))
        self.queue.assert_called_once()

    def test_single_default_live_writer_is_validated(self):
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable",
                  "reason": "stable_live_writer"}
        with mock.patch.object(peer.sys, "platform", "linux"), \
             mock.patch.object(peer, "inspect_codex_writer", side_effect=[active, active]):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.default))
        self.assertEqual(result["status"], "queued")
        self.queue.assert_called_once()

    def test_single_default_without_discovery_db_fails_without_queue(self):
        empty_user = self.user / "empty-user"
        with mock.patch.object(peer.Path, "home", return_value=empty_user):
            code, result = self.send()
        self.assertEqual(code, 2)
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "thread_not_saved_in_known_homes")
        self.assertFalse(empty_user.exists())
        self.queue.assert_not_called()

    def test_macos_default_without_orca_installation_remains_compatible(self):
        user = self.user / "single-home-user"
        self.make_home(user / ".codex")
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable",
                  "reason": "stable_live_writer"}
        with mock.patch.object(peer.Path, "home", return_value=user), \
             mock.patch.object(peer, "inspect_codex_writer", side_effect=[active, active]):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(user / ".codex"))
        self.queue.assert_called_once()

    def test_orca_account_without_db_is_not_a_competing_saved_copy(self):
        user = self.user / "empty-orca-user"
        self.make_home(user / ".codex")
        empty = user / "Library/Application Support/orca/codex-accounts/empty/home"
        empty.mkdir(parents=True)
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable",
                  "reason": "stable_live_writer"}
        with mock.patch.object(peer.Path, "home", return_value=user), \
             mock.patch.object(peer, "inspect_codex_writer", side_effect=[active, active]):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(user / ".codex"))
        self.assertFalse((empty / "state_5.sqlite").exists())
        self.queue.assert_called_once()

    def test_never_automatically_switches_to_another_home(self):
        with contextlib.closing(sqlite3.connect(self.default / "state_5.sqlite")) as conn:
            conn.execute("DELETE FROM threads")
            conn.commit()
        code, result = self.send()
        self.assertEqual(code, 1)
        self.assertIn(str(self.account), result["error"])
        self.assertIn("--allow-inactive-codex-home", result["error"])
        self.queue.assert_not_called()

    def test_invalid_config_fails_closed_without_echoing_raw_value(self):
        for value in ('secret-not-json', '{}', '[1]', '[null]', '[""]', '["relative/path"]'):
            with self.subTest(value=value):
                os.environ["SESSION_PEER_CODEX_HOMES"] = value
                code, result = self.send()
                self.assertEqual(code, 1)
                self.assertIn("SESSION_PEER_CODEX_HOMES", result["error"])
                self.assertNotIn("secret-not-json", result["error"])
        self.queue.assert_not_called()

    def test_missing_configured_home_is_not_created_or_silently_skipped(self):
        missing = self.user / "missing home"
        os.environ["SESSION_PEER_CODEX_HOMES"] = json.dumps([str(missing)])
        code, result = self.send()
        self.assertEqual(code, 1)
        self.assertIn(str(missing), result["error"])
        self.assertIn("nothing queued", result["error"])
        self.assertFalse(missing.exists())
        self.queue.assert_not_called()

    def test_unreadable_known_db_prevents_implicit_submission(self):
        original = peer.sqlite3.connect

        def connect(database, **kwargs):
            if self.account.as_uri() in database:
                raise sqlite3.OperationalError("unable to open database file")
            return original(database, **kwargs)

        with mock.patch.object(peer.sqlite3, "connect", side_effect=connect):
            code, result = self.send()
        self.assertEqual(code, 1)
        self.assertIn(str(self.account), result["error"])
        self.queue.assert_not_called()

    def test_unsupported_known_db_schema_prevents_implicit_submission(self):
        with contextlib.closing(sqlite3.connect(self.account / "state_5.sqlite")) as conn:
            conn.execute("DROP TABLE threads")
            conn.commit()
        code, result = self.send()
        self.assertEqual(code, 1)
        self.assertIn("Cannot check Codex home", result["error"])
        self.queue.assert_not_called()

    def test_orca_scan_permission_error_is_not_silently_skipped(self):
        with mock.patch.object(peer.Path, "iterdir", side_effect=PermissionError("denied")):
            code, result = self.send()
        self.assertEqual(code, 1)
        self.assertIn("Cannot inspect Codex homes", result["error"])
        self.queue.assert_not_called()

    def test_explicit_selection_does_not_bypass_broken_inventory(self):
        os.environ["SESSION_PEER_CODEX_HOMES"] = 'invalid'
        with mock.patch.object(peer.Path, "iterdir", side_effect=PermissionError("denied")):
            code, result = self.send("--codex-home", str(self.account))
        self.assertEqual(code, 1)
        self.assertIn("Cannot inspect Codex homes", result["error"])
        self.queue.assert_not_called()

    @unittest.skipIf(os.name == "nt", "creating symlinks may require Windows privileges")
    def test_symlink_and_repeated_paths_are_one_home(self):
        alias = self.user / "codex-alias"
        alias.symlink_to(self.default, target_is_directory=True)
        os.environ["SESSION_PEER_CODEX_HOMES"] = json.dumps([str(alias), str(self.default), str(alias)])
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "ownerStartTime": "stable",
                  "reason": "stable_live_writer"}
        with mock.patch.object(peer.sys, "platform", "linux"), \
             mock.patch.object(peer, "inspect_codex_writer", side_effect=[active, active]):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.default))
        self.queue.assert_called_once()

    def test_configured_paths_with_spaces_and_unicode_are_not_shell_parsed(self):
        unusual = self.user / "한글 'literal' $var ; home"
        self.make_home(unusual)
        os.environ["SESSION_PEER_CODEX_HOMES"] = json.dumps([str(unusual)])
        with mock.patch.object(peer.sys, "platform", "linux"):
            code, result = self.send()
        self.assertEqual(code, 1)
        self.assertIn(str(unusual), result["error"])
        self.queue.assert_not_called()

    def test_listing_merges_known_homes_unless_explicit_without_claiming_activity(self):
        for selected in (None, self.account):
            output = io.StringIO()
            flags = ["--codex-home", str(selected)] if selected else []
            with contextlib.redirect_stdout(output):
                code = peer.main(["list", "--agent", "codex", "--json", *flags])
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            if selected:
                self.assertEqual(result["codexHome"], str(selected))
                self.assertEqual(len(result["sessions"]), 1)
            else:
                self.assertNotIn("codexHome", result)
                self.assertEqual({r["codexHome"] for r in result["sessions"]},
                                 {str(self.default), str(self.account)})
                self.assertEqual(len(result["sessions"]), 2)
            self.assertNotIn("alive", result["sessions"][0])
            self.assertNotIn("submitted", result)
        self.queue.assert_not_called()

    def test_human_results_identify_home_and_unconfirmed_consumption(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = peer.main(["send", "--to", "codex:" + THREAD, "--codex-home", str(self.account),
                              "--allow-inactive-codex-home", "--no-from", "--no-reply-to", "test"])
        self.assertEqual(code, 0)
        self.assertIn(str(self.account), output.getvalue())
        self.assertIn("consumption not confirmed", output.getvalue())

    def test_timeout_does_not_return_false_submission_or_consumption_confirmation(self):
        self.queue.side_effect = subprocess.TimeoutExpired("codex", 30)
        code, result = self.send("--codex-home", str(self.account),
                                 "--allow-inactive-codex-home")
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertIn("outcome unknown", result["error"])
        self.assertNotIn("submitted", result)
        self.assertNotIn("consumptionConfirmed", result)
        self.queue.assert_called_once()

    def test_remote_dispatch_applies_destination_guard_and_explicit_override(self):
        # Exercise the remote argv and JSON boundary with the destination's
        # inventory. Do not infer the destination home from the local output.
        def destination(host, argv, ssh_opts):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                peer.main([*argv, "--json"])
            result = json.loads(output.getvalue())
            if result.get("ok") is False:
                raise peer.CcPeerError(host + ": " + result["error"])
            return result

        with mock.patch.object(peer, "run_remote", side_effect=destination), \
             mock.patch.object(peer, "tailscale_status", return_value=None):
            code, result = self.send("--host", "worker")
            self.assertEqual(code, 1)
            self.assertEqual(result["host"], "worker")
            self.assertIn("inactive", result["error"])
            self.queue.assert_not_called()
            code, result = self.send("--host", "worker", "--codex-home", str(self.account),
                                     "--allow-inactive-codex-home")
            self.assertEqual(code, 0)
            self.assertEqual(result["host"], "worker")
            self.assertEqual(result["codexHome"], str(self.account))
            self.assertTrue(result["submitted"])
            self.assertIs(result["consumptionConfirmed"], False)
            self.assertEqual(self.queue.call_args.kwargs["env"]["CODEX_HOME"], str(self.account))
            self.queue.reset_mock()
            code, result = self.send("--host", "worker", "--codex-home", str(self.account),
                                     "--allow-inactive-codex-home", "--dry-run")
            self.assertEqual(code, 0)
            self.assertIs(result["submitted"], False)
            self.assertEqual(result["codexHome"], str(self.account))
            self.queue.assert_not_called()
