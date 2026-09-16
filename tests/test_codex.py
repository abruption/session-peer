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

THREAD = "01900000-0000-7000-8000-000000000001"
OTHER = "01900000-0000-7000-8000-000000000002"


class Codex(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = self.root / "state_5.sqlite"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE threads (id TEXT, name TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)")
        conn.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?,?)", [
            (THREAD, None, "title", "/project", 10, 0, "/missing-rollout"),
            (OTHER, "named", "fallback", "/other", 20, 1, "/missing-rollout")])
        conn.commit()
        conn.close()
        self.args = argparse.Namespace(codex_home=str(self.root), codex_bin=None, all=False,
                                       to="codex:" + THREAD, dry_run=False)

    def invoke(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = peer.main(list(argv))
        return code, json.loads(output.getvalue())

    def test_readonly_discovery_filters_and_sorts_saved_sessions(self):
        before = self.db.read_bytes()
        rows = peer.discover_codex(self.args)
        self.assertEqual([r["id"] for r in rows], [THREAD])
        self.assertEqual(rows[0]["name"], "title")
        self.assertNotIn("alive", rows[0])
        self.assertNotIn("reachable", rows[0])
        self.args.all = True
        self.assertEqual([r["id"] for r in peer.discover_codex(self.args)], [OTHER, THREAD])
        self.assertEqual(before, self.db.read_bytes())

    def test_missing_db_does_not_create_it(self):
        self.args.codex_home = str(self.root / "missing")
        with self.assertRaisesRegex(peer.CcPeerError, "not found"):
            peer.discover_codex(self.args)
        self.assertFalse((self.root / "missing").exists())

    def test_title_preview_does_not_dump_transcripts(self):
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            conn.execute("UPDATE threads SET title=? WHERE id=?", ("x" * 200 + "\nprivate transcript", THREAD))
            conn.commit()
        self.assertEqual(peer.discover_codex(self.args)[0]["name"], "x" * 120)

    def test_changed_schema_is_actionable(self):
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            conn.execute("DROP TABLE threads")
            conn.commit()
        with self.assertRaisesRegex(peer.CcPeerError, "Unsupported Codex"):
            peer.discover_codex(self.args)

    def test_home_precedence(self):
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root / "env")}):
            self.assertEqual(peer.codex_home(self.args), self.root.resolve())
            self.args.codex_home = None
            self.assertEqual(peer.codex_home(self.args), (self.root / "env").resolve())

    def test_invalid_ids_fail_before_dispatch(self):
        for target in ("codex:", "codex:short", "codex:../data", "codex:" + THREAD + ";echo x"):
            with mock.patch.object(peer, "run_remote") as run:
                code, result = self.invoke("send", "--host", "worker", "--to", target, "--json", "test")
            self.assertEqual(code, 1)
            self.assertFalse(result["ok"])
            run.assert_not_called()

    def test_cli_missing(self):
        with mock.patch.object(peer.shutil, "which", return_value=None):
            with self.assertRaisesRegex(peer.CcPeerError, "--codex-bin"):
                peer.queue_codex(self.args, "test")

    def test_queue_argv_home_and_payload(self):
        message = "한글 🧪\n'quotes' \"double\" $HOME `literal` $(literal);|&"
        done = subprocess.CompletedProcess([], 0, "Queued message test-id for thread " + THREAD + ".\n", "")
        with mock.patch.object(peer, "codex_executable", return_value="/path with space/codex"), \
             mock.patch.object(peer.subprocess, "run", return_value=done) as run:
            result = peer.queue_codex(self.args, message)
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["queueId"], "test-id")
        self.assertEqual(result["codexHome"], str(self.root.resolve()))
        self.assertTrue(result["submitted"])
        self.assertIs(result["consumptionConfirmed"], False)
        self.assertEqual(run.call_args.args[0], ["/path with space/codex", "queue", "--thread", THREAD, "--message", message])
        self.assertEqual(run.call_args.kwargs["env"]["CODEX_HOME"], str(self.root.resolve()))
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(run.call_count, 1)

    def test_different_success_output_remains_success(self):
        with mock.patch.object(peer, "codex_executable", return_value="codex"), \
             mock.patch.object(peer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "accepted", "")):
            result = peer.queue_codex(self.args, "test")
        self.assertEqual(result["status"], "queued")
        self.assertNotIn("queueId", result)

    def test_dry_run_checks_saved_id_without_running(self):
        self.args.dry_run = True
        with mock.patch.object(peer, "codex_executable", return_value="codex"), \
             mock.patch.object(peer.subprocess, "run") as run:
            result = peer.queue_codex(self.args, "test")
        self.assertEqual(result["status"], "validated")
        self.assertEqual(result["codexHome"], str(self.root.resolve()))
        self.assertIs(result["submitted"], False)
        self.assertIs(result["consumptionConfirmed"], False)
        run.assert_not_called()

    def test_unknown_dry_run_target_exit_code(self):
        with mock.patch.object(peer, "codex_executable", return_value="codex"):
            code, result = self.invoke("send", "--to", "codex:" + "00000000-0000-0000-0000-000000000000",
                                       "--codex-home", str(self.root), "--dry-run", "--no-from", "--no-reply-to", "--json", "test")
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])

    def test_timeout_is_unknown_and_never_retried(self):
        with mock.patch.object(peer, "codex_executable", return_value="codex"), \
             mock.patch.object(peer.subprocess, "run", side_effect=subprocess.TimeoutExpired("codex", 30)) as run:
            with self.assertRaisesRegex(peer.CcPeerError, "outcome unknown"):
                peer.queue_codex(self.args, "test")
        self.assertEqual(run.call_count, 1)

    def test_failure_is_not_success(self):
        for error in ("no rollout found", "attempt to write a readonly database"):
            with mock.patch.object(peer, "codex_executable", return_value="codex"), \
                 mock.patch.object(peer.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", error)):
                with self.assertRaisesRegex(peer.CcPeerError, error):
                    peer.queue_codex(self.args, "test")

    def test_byte_limit_after_wrapping(self):
        peer.check_codex_message("한" * 10922 + "ab")
        with self.assertRaisesRegex(peer.CcPeerError, "UTF-8 bytes"):
            peer.check_codex_message("한" * 10923)
        with self.assertRaisesRegex(peer.CcPeerError, "NUL"):
            peer.check_codex_message("a\x00b")
        with mock.patch.object(peer, "wrap_message", return_value="x" * 32769), \
             mock.patch.object(peer, "queue_codex") as queue:
            code, _ = self.invoke("send", "--to", "codex:" + THREAD, "--json", "short")
        self.assertEqual(code, 1)
        queue.assert_not_called()

    def test_remote_send_preserves_status_and_destination_options(self):
        resolution = {"schemaVersion": 1, "status": "explicit",
                      "selected": "/resolved remote home",
                      "reason": "explicit_codex_home", "candidates": []}
        response = {"ok": True, "target": {"agent": "codex", "id": THREAD}, "status": "queued",
                    "queueId": "queue-id", "dryRun": False, "chars": 4,
                    "codexHome": "/resolved remote home", "submitted": True,
                    "consumptionConfirmed": False, "codexHomeResolution": resolution}
        with mock.patch.object(peer, "run_remote", return_value=response) as remote:
            code, result = self.invoke("send", "--host", "worker", "--to", "codex:" + THREAD,
                "--codex-home", "/remote home", "--codex-bin", "/remote bin/codex", "--json", "--no-from", "--no-reply-to", "test")
        self.assertEqual(code, 0)
        self.assertEqual(result["host"], "worker")
        self.assertEqual(result["queueId"], "queue-id")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["codexHome"], "/resolved remote home")
        self.assertEqual(result["codexHomeResolution"], resolution)
        self.assertTrue(result["submitted"])
        self.assertIs(result["consumptionConfirmed"], False)
        argv = remote.call_args.args[1]
        self.assertEqual(argv[argv.index("--codex-home") + 1], "/remote home")
        self.assertEqual(argv[argv.index("--codex-bin") + 1], "/remote bin/codex")

    def test_remote_send_preserves_structured_home_failure(self):
        resolution = {"schemaVersion": 1, "status": "ambiguous", "selected": None,
                      "reason": "multiple_live_writers", "candidates": []}
        error = peer.CcPeerError(
            "worker: ambiguous Codex home",
            {"codexHomeResolution": resolution},
        )
        with mock.patch.object(peer, "run_remote", side_effect=error), \
             mock.patch.object(peer, "tailscale_status", return_value=None):
            code, result = self.invoke(
                "send", "--host", "worker", "--to", "codex:" + THREAD,
                "--json", "--no-from", "--no-reply-to", "test",
            )
        self.assertEqual(code, 1)
        self.assertEqual(result["codexHomeResolution"], resolution)

    def test_remote_list_forwards_agent_and_home(self):
        with mock.patch.object(peer, "run_remote", return_value={"sessions": [], "codexHome": "/resolved remote home"}) as remote, \
             mock.patch.object(peer, "remote_installed_version", return_value=None):
            code, result = self.invoke("list", "--agent", "codex", "--host", "worker", "--all", "--codex-home", "/remote", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(result["host"], "worker")
        self.assertEqual(result["codexHome"], "/resolved remote home")
        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "list")
        self.assertEqual(result["schemaVersion"], 1)
        self.assertEqual(remote.call_args.args[1], [
            "list", "--no-update-notice", "--all", "--agent", "codex",
            "--codex-home", "/remote",
        ])

    def test_multihost_results_keep_destination_specific_home(self):
        def remote(host, argv, ssh_opts):
            if argv[0] == "list":
                return {"sessions": [], "codexHome": "/" + host + "/codex"}
            return {"ok": True, "target": {"agent": "codex", "id": THREAD},
                    "codexHome": "/" + host + "/codex", "status": "queued",
                    "submitted": True, "consumptionConfirmed": False, "dryRun": False, "chars": 4}

        with mock.patch.object(peer, "run_remote", side_effect=remote), \
             mock.patch.object(peer, "remote_installed_version", return_value=None):
            for command in (["list", "--agent", "codex"],
                            ["send", "--to", "codex:" + THREAD, "--no-from", "--no-reply-to", "test"]):
                code, result = self.invoke(*command, "--host", "first", "--host", "second", "--json")
                self.assertEqual(code, 0)
                self.assertEqual([(r["host"], r["codexHome"]) for r in result],
                                 [("first", "/first/codex"), ("second", "/second/codex")])

    def test_claude_listing_uses_common_json_envelope(self):
        with mock.patch.object(peer, "discover", return_value=[]):
            code, result = self.invoke("list", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(result, {
            "schemaVersion": 1,
            "ok": True,
            "host": peer.local_host(),
            "command": "list",
            "sessions": [],
            "version": peer.__version__,
        })

    def test_help_documents_explicit_home_and_bounded_guard(self):
        for command in ("list", "send"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as context:
                peer.main([command, "--help"])
            self.assertEqual(context.exception.code, 0)
            help_text = " ".join(output.getvalue().split())
            self.assertIn("Orca/multiple homes", help_text)
            if command == "send":
                self.assertIn("SESSION_PEER_CODEX_HOMES", help_text)
                self.assertIn("stable live writer", help_text)


class CodexWriterEvidence(unittest.TestCase):
    def test_parses_nul_delimited_lsof_processes(self):
        self.assertEqual(peer.parse_lsof_processes("p42\0ccodex\0u501\0\np7\0cnode\0u502\0"), [
            {"pid": 7, "command": "node", "uid": 502},
            {"pid": 42, "command": "codex", "uid": 501},
        ])

    @unittest.skipIf(peer.fcntl is None, "POSIX flock is unavailable")
    def test_probes_a_real_advisory_lock_without_changing_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "thread.lock"
            lock.write_text("unchanged", encoding="utf-8")
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
            self.assertEqual(peer.probe_codex_writer_lock(lock),
                             ("held", "kernel_lock_held"))
            self.assertEqual(lock.read_text(encoding="utf-8"), "unchanged")
            child.terminate()
            child.wait(timeout=5)
            self.assertEqual(peer.probe_codex_writer_lock(lock),
                             ("free", "kernel_lock_free"))

    @unittest.skipIf(peer.fcntl is None, "POSIX flock is unavailable")
    @unittest.skipIf(peer._lsof_executable() is None, "lsof is unavailable")
    def test_correlates_a_real_lock_opener_without_reading_process_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "thread.lock"
            lock.write_text("unchanged", encoding="utf-8")
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
            openers, error = peer._codex_lock_openers(lock)
            self.assertIsNone(error)
            self.assertEqual([process["pid"] for process in openers], [child.pid])
            self.assertNotIn("args", openers[0])

    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX UID is unavailable")
    def test_stable_same_user_codex_owner_is_live(self):
        sample = {
            "snapshot": (1, 2, 0, 3), "writerLock": "held",
            "probeReason": "kernel_lock_held", "openerError": None,
            "openers": [{"pid": 42, "uid": os.getuid(), "command": "codex",
                         "startTime": "stable"}],
        }
        with mock.patch.object(peer, "_codex_lock_sample", side_effect=[sample, sample]), \
             mock.patch.object(peer.time, "sleep"):
            result = peer.inspect_codex_writer(Path("/home"), THREAD)
        self.assertEqual(result["activity"], "live_writer")
        self.assertEqual(result["ownerPid"], 42)
        self.assertNotIn("command", result)
        self.assertNotIn("startTime", result)

    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX UID is unavailable")
    def test_pid_change_is_unknown(self):
        def sample(pid):
            return {
                "snapshot": (1, 2, 0, 3), "writerLock": "held",
                "probeReason": "kernel_lock_held", "openerError": None,
                "openers": [{"pid": pid, "uid": os.getuid(), "command": "codex",
                             "startTime": "stable"}],
            }
        with mock.patch.object(peer, "_codex_lock_sample",
                               side_effect=[sample(42), sample(43)]), \
             mock.patch.object(peer.time, "sleep"):
            result = peer.inspect_codex_writer(Path("/home"), THREAD)
        self.assertEqual(result["activity"], "unknown")
        self.assertEqual(result["reason"], "lock_owner_changed")


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
            self.assertIn("ambiguous", result["error"].lower())
            for expected in (str(self.default), str(self.account), "--codex-home"):
                self.assertIn(expected, result["error"])
        self.queue.assert_not_called()
        for path, original in before.items():
            self.assertEqual((path / "state_5.sqlite").read_bytes(), original)

    def test_one_stable_live_writer_selects_its_home_and_revalidates(self):
        inactive = {"activity": "inactive", "writerLock": "free",
                    "reason": "kernel_lock_free"}
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "reason": "stable_live_writer"}
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
                  "ownerStable": True, "reason": "stable_live_writer"}
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
                  "ownerStable": True, "reason": "stable_live_writer"}
        with mock.patch.object(peer, "inspect_codex_writer", side_effect=[active, active]):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.account))
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "single_stable_live_writer")

    def test_multiple_live_writers_are_structured_ambiguity(self):
        active_a = {"activity": "live_writer", "writerLock": "held", "ownerPid": 41,
                    "ownerStable": True, "reason": "stable_live_writer"}
        active_b = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                    "ownerStable": True, "reason": "stable_live_writer"}
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
                  "ownerStable": True, "reason": "stable_live_writer"}
        unknown = {"activity": "unknown", "writerLock": "held",
                   "reason": "lsof_unavailable"}
        with mock.patch.object(peer, "inspect_codex_writer", side_effect=[active, unknown]):
            code, result = self.send()
        self.assertEqual(code, 1)
        self.assertEqual(result["codexHomeResolution"]["status"], "unknown")
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "active_writer_unverified")
        self.queue.assert_not_called()

    def test_writer_pid_change_before_queue_fails_closed(self):
        inactive = {"activity": "inactive", "writerLock": "free",
                    "reason": "kernel_lock_free"}
        active = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                  "ownerStable": True, "reason": "stable_live_writer"}
        changed = {**active, "ownerPid": 43}
        with mock.patch.object(peer, "inspect_codex_writer",
                               side_effect=[inactive, active, inactive, changed]):
            code, result = self.send()
        self.assertEqual(code, 1)
        self.assertEqual(result["codexHomeResolution"]["status"], "unknown")
        self.assertEqual(result["codexHomeResolution"]["reason"],
                         "writer_evidence_changed_before_queue")
        self.queue.assert_not_called()

    def test_competing_writer_appearing_before_queue_fails_closed(self):
        inactive = {"activity": "inactive", "writerLock": "free",
                    "reason": "kernel_lock_free"}
        selected = {"activity": "live_writer", "writerLock": "held", "ownerPid": 42,
                    "ownerStable": True, "reason": "stable_live_writer"}
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

    def test_explicit_home_queues_only_selected_copy_and_exposes_semantics(self):
        for home in (self.account, self.default):
            with self.subTest(home=home):
                code, result = self.send("--codex-home", str(home))
                self.assertEqual(code, 0)
                self.assertEqual(result["codexHome"], str(home))
                self.assertEqual(result["status"], "queued")
                self.assertTrue(result["submitted"])
                self.assertIs(result["consumptionConfirmed"], False)
                self.assertEqual(result["codexHomeResolution"]["status"], "explicit")
                self.assertEqual(result["codexHomeResolution"]["reason"],
                                 "explicit_codex_home")
                self.assertEqual(self.queue.call_args.kwargs["env"]["CODEX_HOME"], str(home))

    def test_explicit_dry_run_selects_one_copy_without_submission(self):
        code, result = self.send("--codex-home", str(self.account), "--dry-run")
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

    def test_archived_duplicate_is_not_assumed_inactive_or_safe(self):
        with contextlib.closing(sqlite3.connect(self.account / "state_5.sqlite")) as conn:
            conn.execute("UPDATE threads SET archived=1")
            conn.commit()
        code, result = self.send()
        self.assertEqual(code, 1)
        self.assertIn("Ambiguous", result["error"])
        self.queue.assert_not_called()

    def test_unrelated_known_home_keeps_selected_destination(self):
        with contextlib.closing(sqlite3.connect(self.account / "state_5.sqlite")) as conn:
            conn.execute("UPDATE threads SET id=?", (OTHER,))
            conn.commit()
        code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.default))
        self.assertEqual(self.queue.call_args.kwargs["env"]["CODEX_HOME"], str(self.default))
        self.queue.assert_called_once()

    def test_single_default_home_preserves_native_queue_behavior(self):
        with mock.patch.object(peer.sys, "platform", "linux"):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.default))
        self.assertEqual(result["status"], "queued")
        self.queue.assert_called_once()

    def test_single_default_without_discovery_db_still_delegates_to_native_queue(self):
        empty_user = self.user / "empty-user"
        with mock.patch.object(peer.Path, "home", return_value=empty_user):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(empty_user / ".codex"))
        self.assertFalse(empty_user.exists())
        self.queue.assert_called_once()

    def test_macos_default_without_orca_installation_remains_compatible(self):
        user = self.user / "single-home-user"
        self.make_home(user / ".codex")
        with mock.patch.object(peer.Path, "home", return_value=user):
            code, result = self.send()
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(user / ".codex"))
        self.queue.assert_called_once()

    def test_orca_account_without_db_is_not_a_competing_saved_copy(self):
        user = self.user / "empty-orca-user"
        self.make_home(user / ".codex")
        empty = user / "Library/Application Support/orca/codex-accounts/empty/home"
        empty.mkdir(parents=True)
        with mock.patch.object(peer.Path, "home", return_value=user):
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
        self.assertEqual(code, 2)
        self.assertIn(str(self.account), result["error"])
        self.assertIn("--codex-home", result["error"])
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
        self.assertIn("--codex-home", result["error"])
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

    def test_explicit_selection_bypasses_unrelated_broken_inventory(self):
        os.environ["SESSION_PEER_CODEX_HOMES"] = 'invalid'
        with mock.patch.object(peer.Path, "iterdir", side_effect=PermissionError("denied")):
            code, result = self.send("--codex-home", str(self.account))
        self.assertEqual(code, 0)
        self.assertEqual(result["codexHome"], str(self.account))
        self.queue.assert_called_once()

    @unittest.skipIf(os.name == "nt", "creating symlinks may require Windows privileges")
    def test_symlink_and_repeated_paths_are_one_home(self):
        alias = self.user / "codex-alias"
        alias.symlink_to(self.default, target_is_directory=True)
        os.environ["SESSION_PEER_CODEX_HOMES"] = json.dumps([str(alias), str(self.default), str(alias)])
        with mock.patch.object(peer.sys, "platform", "linux"):
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

    def test_listing_identifies_selected_home_without_merging_or_claiming_activity(self):
        for selected in (None, self.account):
            output = io.StringIO()
            flags = ["--codex-home", str(selected)] if selected else []
            with contextlib.redirect_stdout(output):
                code = peer.main(["list", "--agent", "codex", "--json", *flags])
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["codexHome"], str(selected or self.default))
            self.assertEqual(len(result["sessions"]), 1)
            self.assertNotIn("alive", result["sessions"][0])
            self.assertNotIn("submitted", result)
        self.queue.assert_not_called()

    def test_human_results_identify_home_and_unconfirmed_consumption(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = peer.main(["send", "--to", "codex:" + THREAD, "--codex-home", str(self.account),
                              "--no-from", "--no-reply-to", "test"])
        self.assertEqual(code, 0)
        self.assertIn(str(self.account), output.getvalue())
        self.assertIn("consumption not confirmed", output.getvalue())

    def test_timeout_does_not_return_false_submission_or_consumption_confirmation(self):
        self.queue.side_effect = subprocess.TimeoutExpired("codex", 30)
        code, result = self.send("--codex-home", str(self.account))
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
            self.assertIn("Ambiguous", result["error"])
            self.queue.assert_not_called()
            code, result = self.send("--host", "worker", "--codex-home", str(self.account))
            self.assertEqual(code, 0)
            self.assertEqual(result["host"], "worker")
            self.assertEqual(result["codexHome"], str(self.account))
            self.assertTrue(result["submitted"])
            self.assertIs(result["consumptionConfirmed"], False)
            self.assertEqual(self.queue.call_args.kwargs["env"]["CODEX_HOME"], str(self.account))
            self.queue.reset_mock()
            code, result = self.send("--host", "worker", "--codex-home", str(self.account), "--dry-run")
            self.assertEqual(code, 0)
            self.assertIs(result["submitted"], False)
            self.assertEqual(result["codexHome"], str(self.account))
            self.queue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
