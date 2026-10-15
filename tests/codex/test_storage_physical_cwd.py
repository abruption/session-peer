"""Synthetic physical-cwd boundaries; no native Codex or user config is read."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import session_peer as peer
from tests.codex.support import THREAD, isolate_native_layers


class PhysicalStorageCwd(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "home"
        self.root.mkdir()
        self.repo = self.base / "physical" / "repo"
        self.cwd = self.repo / "nested"
        self.cwd.mkdir(parents=True)
        (self.repo / ".git").mkdir()
        (self.repo / ".git" / "HEAD").write_text("fixture\n", encoding="utf-8")
        self.rollout = self.root / "rollout.jsonl"
        self.rollout.write_text("{}\n", encoding="utf-8")
        isolate_native_layers(self, self.base)
        environment = mock.patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.args = argparse.Namespace(codex_home=str(self.root), codex_bin="fixture",
            to="codex:" + THREAD, dry_run=False, all=False,
            allow_inactive_codex_home=True, wake=False)

    def link(self, path, destination):
        try:
            path.symlink_to(destination, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks are unavailable")
        return path

    def database(self, cwd):
        with contextlib.closing(sqlite3.connect(self.root / "state_5.sqlite")) as conn:
            conn.execute("CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)")
            conn.execute("INSERT INTO threads VALUES (?,?,?,?,?,?)",
                         (THREAD, "fixture", str(cwd), 1, 0, str(self.rollout)))
            conn.commit()

    def relocation(self):
        directory = self.repo / ".codex"
        directory.mkdir(exist_ok=True)
        (directory / "config.toml").write_text('sqlite_home="relocated-fixture"\n', encoding="utf-8")

    def assert_storage_refused(self, action):
        with self.assertRaises(peer.CcPeerError) as caught:
            action()
        self.assertEqual(caught.exception.details["reason"], "sqlite_home_project_configuration")
        self.assertIs(caught.exception.details["submitted"], False)
        self.assertIs(caught.exception.details["retryAllowed"], False)
        self.assertNotIn(str(self.base), str(caught.exception))
        self.assertNotIn("relocated-fixture", str(caught.exception))

    def test_leaf_alias_checks_physical_project_ancestors(self):
        alias = self.link(self.base / "alias", self.cwd)
        self.relocation()
        self.assert_storage_refused(lambda: peer.check_codex_storage(self.root, cwd=alias))

    def test_ancestor_alias_checks_physical_project_ancestors(self):
        (self.cwd / "deeper").mkdir()
        ancestor = self.link(self.base / "alias-parent", self.cwd)
        alias = ancestor / "deeper"
        self.assertFalse(alias.is_symlink())
        self.relocation()
        self.assert_storage_refused(lambda: peer.check_codex_storage(self.root, cwd=alias))

    def test_consumer_cwd_is_physical_and_missing_directory_still_skips(self):
        alias = self.link(self.base / "alias", self.cwd)
        self.database(alias)
        self.assertEqual(peer.codex_thread_cwd(self.root, THREAD), self.cwd)
        self.relocation()
        self.assert_storage_refused(lambda: peer.check_codex_consumer_storage(self.root, THREAD))
        alias.unlink()
        self.assertIsNone(peer.codex_thread_cwd(self.root, THREAD))

    def test_consumer_also_refuses_a_lexical_only_project_layer(self):
        # An already-running writer may have received an explicit logical cwd.
        # Its path spelling is not evidence that it used physical cwd semantics.
        logical = self.base / "logical"
        logical.mkdir()
        (logical / ".git").mkdir()
        (logical / ".git" / "HEAD").write_text("fixture\n", encoding="utf-8")
        alias = self.link(logical / "alias", self.cwd)
        (logical / ".codex").mkdir()
        (logical / ".codex" / "config.toml").write_text(
            'sqlite_home="relocated-fixture"\n', encoding="utf-8")
        self.database(alias)
        # The physical-only project tree is clean, but is not the only possible
        # startup tree for an existing writer with a logical saved cwd.
        peer.check_codex_storage(self.root, cwd=self.cwd)
        self.assert_storage_refused(lambda: peer.check_codex_consumer_storage(self.root, THREAD))

    def test_consumer_lexical_scan_stops_at_its_nearest_git_marker(self):
        logical = self.base / "logical"
        logical.mkdir()
        ancestor = self.link(logical / "alias-parent", self.repo)
        alias = ancestor / "nested"
        (logical / ".codex").mkdir()
        (logical / ".codex" / "config.toml").write_text(
            'sqlite_home="relocated-fixture"\n', encoding="utf-8")
        self.database(alias)
        # alias-parent/.git resolves to the real repo marker; the logical
        # parent's config is outside that root and must not be over-scanned.
        peer.check_codex_consumer_storage(self.root, THREAD)

    def test_consumer_alias_refuses_dry_run_and_send_without_child(self):
        alias = self.link(self.base / "alias", self.cwd)
        self.database(alias)
        self.relocation()
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.root]), \
             mock.patch.object(peer, "codex_executable", return_value="fixture"), \
             mock.patch.object(peer.subprocess, "run") as run, \
             mock.patch.object(peer.subprocess, "Popen") as start:
            for dry_run in (True, False):
                self.args.dry_run = dry_run
                self.assert_storage_refused(lambda: peer.queue_codex(self.args, "fixture"))
            run.assert_not_called()
            start.assert_not_called()

    def test_queue_plan_and_pwd_use_the_same_physical_home(self):
        alias = self.link(self.base / "home-alias", self.root)
        self.database(self.cwd)
        planned = peer.codex_queue_cwd(alias, None)
        self.assertEqual(planned, self.root)
        env = peer.codex_process_environment(self.root, cwd=alias)
        if not peer.IS_WINDOWS:
            self.assertEqual(env["PWD"], str(self.root))
        self.assertEqual(peer.codex_queue_storage_preflight(self.args, self.root, THREAD), self.root)

    def test_resolution_errors_are_sanitized_and_do_not_start_a_child(self):
        for error in (OSError("private-path"), RuntimeError("private-loop"), ValueError("private-value")):
            with self.subTest(kind=type(error).__name__), \
                 mock.patch.object(Path, "resolve", side_effect=error), \
                 mock.patch.object(peer.subprocess, "run") as run, \
                 mock.patch.object(peer.subprocess, "Popen") as start:
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.codex_physical_cwd(self.cwd)
                self.assertEqual(caught.exception.details["reason"], "storage_config_unverifiable")
                self.assertIs(caught.exception.details["submitted"], False)
                self.assertNotIn("private-", str(caught.exception))
                run.assert_not_called()
                start.assert_not_called()

    def test_dangling_and_loop_cwds_are_refused(self):
        dangling = self.link(self.base / "dangling", self.base / "absent")
        loop = self.link(self.base / "loop", self.base / "loop")
        for path in (dangling, loop):
            with self.subTest(kind=path.name):
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.codex_physical_cwd(path)
                self.assertEqual(caught.exception.details["reason"], "storage_config_unverifiable")
                self.assertIs(caught.exception.details["submitted"], False)
                self.assertNotIn(str(self.base), str(caught.exception))

    def test_cwd_must_be_a_directory(self):
        with self.assertRaises(peer.CcPeerError) as caught:
            peer.codex_physical_cwd(self.rollout)
        self.assertEqual(caught.exception.details["reason"], "storage_config_unverifiable")

    def test_consumer_alias_retarget_at_effect_boundary_refuses_queue(self):
        safe = self.base / "safe"
        safe.mkdir()
        alias = self.link(self.base / "alias", safe)
        self.database(alias)
        self.relocation()

        def revalidate(*args, **kwargs):
            alias.unlink()
            alias.symlink_to(self.cwd, target_is_directory=True)

        with mock.patch.object(peer, "resolve_codex_home", return_value=(self.root, {})), \
             mock.patch.object(peer, "codex_executable", return_value="fixture"), \
             mock.patch.object(peer, "revalidate_codex_home", side_effect=revalidate), \
             mock.patch.object(peer.subprocess, "run") as run:
            self.assert_storage_refused(lambda: peer._queue_codex(self.args, "fixture"))
        run.assert_not_called()

    def test_translated_consumer_keeps_the_explicit_unverified_contract(self):
        self.database(self.base / "missing-consumer")
        with mock.patch.object(peer, "IS_WINDOWS", False), \
             mock.patch.object(peer, "codex_thread_cwd") as inspect:
            peer.check_codex_consumer_storage(self.root, THREAD, native_home=r"C:\fixture\home")
        inspect.assert_not_called()

    @unittest.skipUnless(sys.platform in ("darwin", "linux"), "wake supports macOS/Linux only")
    def test_wake_preflight_returns_physical_cwd_and_refuses_its_layers(self):
        alias = self.link(self.base / "alias", self.cwd)
        self.database(alias)
        with mock.patch.object(peer.subprocess, "run", return_value=subprocess.CompletedProcess(
                [], 0, "codex-cli 0.154.0\n", "")), \
             mock.patch.object(peer, "inspect_codex_writer", return_value={"activity": "inactive"}):
            self.assertEqual(peer.codex_wake_preflight(self.root, THREAD, "fixture")["cwd"], str(self.cwd))
            self.relocation()
            self.assert_storage_refused(lambda: peer.codex_wake_preflight(self.root, THREAD, "fixture"))

    @unittest.skipUnless(sys.platform in ("darwin", "linux"), "wake supports macOS/Linux only")
    def test_wake_child_and_resume_share_physical_cwd(self):
        alias = self.link(self.base / "alias", self.cwd)

        class Input(io.BytesIO):
            def close(self):
                pass

        incoming = Input()
        process = mock.Mock()
        process.stdin = incoming
        process.stdout.fileno.return_value = 47
        replies = b"\n".join(json.dumps(value).encode() for value in (
            {"id": 1, "result": {}},
            {"id": 2, "result": {"thread": {"id": THREAD}}},
            {"method": "turn/completed", "params": {"threadId": THREAD, "turn": {"status": "completed"}}},
        )) + b"\n"
        selector = mock.Mock()
        selector.select.return_value = [(None, None)]
        with mock.patch.object(peer.subprocess, "Popen", return_value=process) as start, \
             mock.patch.object(peer.selectors, "DefaultSelector", return_value=selector), \
             mock.patch.object(peer.os, "read", return_value=replies), \
             mock.patch.object(peer, "stop_codex_wake"):
            result = peer.run_codex_wake("fixture", self.root, THREAD, str(alias), 1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(start.call_args.kwargs["cwd"], str(self.cwd))
        self.assertEqual(start.call_args.kwargs["env"]["PWD"], str(self.cwd))
        frames = [json.loads(line) for line in incoming.getvalue().splitlines()]
        resume = next(frame for frame in frames if frame.get("method") == "thread/resume")
        self.assertEqual(resume["params"]["cwd"], str(self.cwd))
