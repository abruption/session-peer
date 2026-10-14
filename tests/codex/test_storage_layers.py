"""Offline fixtures for native Codex storage layers beyond the selected home.

Native evidence (codex-cli 0.162.1, rust-v0.162.1): sqlite_home precedence is
requirements > config layers > CODEX_SQLITE_HOME > CODEX_HOME. Config layers
include system files, macOS managed profiles and the project layers of the
process working directory; `codex queue` routes through a running app-server
daemon when its control socket exists. These tests prove only that
session-peer refuses before any process when it cannot vouch for storage.
They are not evidence of native delivery, consumption or misrouting.
"""
import argparse
import base64
import contextlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import socket
import sys
import sqlite3
import tempfile
import unittest
from unittest import mock

import session_peer as peer
from tests.codex.support import THREAD

SECRET = "private-relocation-value"
# Captured before each test replaces them with fixture paths.
REAL_SYSTEM_PATHS = peer.codex_system_config_paths
REAL_MANAGED_PATHS = peer.codex_managed_preference_paths
REAL_PROJECT_PATHS = peer.codex_project_config_paths


class StorageLayers(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "home"
        self.root.mkdir()
        self.system = self.base / "system"
        self.system.mkdir()
        self.managed = self.base / "managed"
        self.managed.mkdir()
        self.system_paths = [self.system / "config.toml", self.system / "managed_config.toml",
                             self.system / "requirements.toml"]
        self.managed_paths = [self.managed / "user.plist", self.managed / "device.plist"]
        patches = (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(peer, "codex_system_config_paths", return_value=self.system_paths),
            mock.patch.object(peer, "codex_managed_preference_paths", return_value=self.managed_paths),
            # Never read the developer's real ancestor directories.
            mock.patch.object(peer, "codex_project_config_paths", side_effect=lambda cwd: [
                path for path in REAL_PROJECT_PATHS(cwd)
                if os.path.abspath(path).startswith(str(self.base) + os.sep)]),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.args = argparse.Namespace(codex_home=str(self.root), codex_bin="fixture",
            to="codex:" + THREAD, dry_run=False, all=False,
            allow_inactive_codex_home=True, wake=False)

    def refuses(self, reason, **kwargs):
        with self.assertRaises(peer.CcPeerError) as caught:
            peer.check_codex_storage(self.root, **kwargs)
        details = caught.exception.details
        self.assertEqual(details["reason"], reason)
        self.assertEqual(details["status"], "refused")
        self.assertIs(details["submitted"], False)
        self.assertIs(details["retryAllowed"], False)
        # Never reflect configuration contents or any inspected path.
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertNotIn(str(self.base), str(caught.exception))
        return caught.exception

    def database(self, cwd=None):
        with contextlib.closing(sqlite3.connect(self.root / "state_5.sqlite")) as conn:
            conn.execute("CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)")
            rollout = self.root / "rollout.jsonl"
            rollout.write_text("{}\n", encoding="utf-8")
            conn.execute("INSERT INTO threads VALUES (?,?,?,?,?,?)",
                         (THREAD, "fixture", str(cwd or self.root), 1, 0, str(rollout)))
            conn.commit()

    # -- system config and requirements layers ---------------------------

    def test_each_system_layer_with_root_storage_is_refused(self):
        for path in self.system_paths:
            with self.subTest(layer=path.name):
                path.write_text('sqlite_home = "%s"\n' % SECRET, encoding="utf-8")
                self.refuses("sqlite_home_system_configuration")
                path.unlink()
        peer.check_codex_storage(self.root)

    def test_system_layers_reuse_root_only_classification(self):
        # Legacy [profiles.*] has no sqlite_home field in the native schema.
        for text in ('[profiles.work]\nsqlite_home="%s"\n' % SECRET,
                     '# sqlite_home="%s"\nmodel="fixture"\n' % SECRET):
            with self.subTest(text=text):
                self.system_paths[0].write_text(text, encoding="utf-8")
                peer.check_codex_storage(self.root)

    def test_unverifiable_system_layer_fails_closed(self):
        target = self.system_paths[2]
        target.mkdir()
        self.refuses("storage_config_unverifiable")
        target.rmdir()
        target.write_text('sqlite_home = "unterminated\n', encoding="utf-8")
        self.refuses("storage_config_unverifiable")

    def test_real_system_paths_are_platform_specific(self):
        with mock.patch.object(peer, "IS_WINDOWS", False):
            self.assertEqual(REAL_SYSTEM_PATHS(), [Path("/etc/codex/config.toml"),
                                                   Path("/etc/codex/managed_config.toml"),
                                                   Path("/etc/codex/requirements.toml")])
        with mock.patch.object(peer, "IS_WINDOWS", True), \
             mock.patch.dict(os.environ, {"ProgramData": "D:" + os.sep + "Data"}):
            base = Path("D:" + os.sep + "Data") / "OpenAI" / "Codex"
            self.assertEqual(REAL_SYSTEM_PATHS(), [base / "config.toml", base / "requirements.toml"])

    # -- macOS managed preferences --------------------------------------

    def write_plist(self, path, values):
        path.write_bytes(plistlib.dumps(values))

    def encoded(self, text):
        return base64.b64encode(text.encode("utf-8")).decode("ascii")

    def test_managed_config_and_requirements_with_storage_are_refused(self):
        for key in peer.CODEX_MANAGED_PREFERENCES_KEYS:
            for path in self.managed_paths:
                with self.subTest(key=key, path=path.name):
                    self.write_plist(path, {key: self.encoded('sqlite_home = "%s"\n' % SECRET)})
                    self.refuses("sqlite_home_managed_configuration")
                    path.unlink()

    def test_managed_preferences_without_storage_are_allowed(self):
        self.write_plist(self.managed_paths[0], {
            "config_toml_base64": self.encoded('model = "fixture"\n[profiles.x]\nsqlite_home="%s"\n' % SECRET),
            "unrelated": "value"})
        self.write_plist(self.managed_paths[1], {"unrelated": 1})
        peer.check_codex_storage(self.root)

    def test_unverifiable_managed_preferences_fail_closed(self):
        cases = (
            {"config_toml_base64": "%%% not base64"},
            {"config_toml_base64": 7},
            {"requirements_toml_base64": base64.b64encode(b"\xff\xfe").decode()},
            {"requirements_toml_base64": self.encoded('sqlite_home = "unterminated\n')},
        )
        for values in cases:
            with self.subTest(values=sorted(values)):
                self.write_plist(self.managed_paths[0], values)
                self.refuses("storage_config_unverifiable")
        self.managed_paths[0].write_bytes(b"not a plist")
        self.refuses("storage_config_unverifiable")
        self.managed_paths[0].write_bytes(plistlib.dumps(["not", "a", "dictionary"]))
        self.refuses("storage_config_unverifiable")

    def test_managed_preference_paths_are_macos_only(self):
        with mock.patch.object(peer.sys, "platform", "linux"):
            self.assertEqual(REAL_MANAGED_PATHS(), [])
        with mock.patch.object(peer.sys, "platform", "darwin"):
            paths = REAL_MANAGED_PATHS()
        self.assertEqual(paths[-1], Path("/Library/Managed Preferences/com.openai.codex.plist"))
        self.assertTrue(all(path.name == "com.openai.codex.plist" for path in paths))

    # -- project layers of the native process working directory -----------

    def test_project_layers_of_the_process_directory_are_refused(self):
        project = self.base / "repo" / "nested" / "work"
        project.mkdir(parents=True)
        candidates = (project / "config.toml",
                      project / ".codex" / "config.toml",
                      self.base / "repo" / ".codex" / "config.toml")
        for path in candidates:
            with self.subTest(layer=str(path.relative_to(self.base))):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('sqlite_home = "%s"\n' % SECRET, encoding="utf-8")
                self.refuses("sqlite_home_project_configuration", cwd=project)
                # Without a process directory, project layers are not consulted.
                peer.check_codex_storage(self.root)
                path.unlink()
        peer.check_codex_storage(self.root, cwd=project)

    def test_project_layers_refuse_regardless_of_trust_and_ignore_profile_tables(self):
        project = self.base / "untrusted"
        (project / ".codex").mkdir(parents=True)
        config = project / ".codex" / "config.toml"
        config.write_text('[profiles.x]\nsqlite_home = "%s"\n' % SECRET, encoding="utf-8")
        peer.check_codex_storage(self.root, cwd=project)
        config.write_text('"sqlite_home" = "%s"\n' % SECRET, encoding="utf-8")
        self.refuses("sqlite_home_project_configuration", cwd=project)

    def test_home_as_working_directory_keeps_the_user_layer_reason(self):
        (self.root / "config.toml").write_text('sqlite_home = "%s"\n' % SECRET, encoding="utf-8")
        self.refuses("sqlite_home_configuration", cwd=self.root)

    def test_project_paths_cover_every_ancestor(self):
        project = self.base / "a" / "b"
        paths = REAL_PROJECT_PATHS(project)
        self.assertEqual(paths[0], project / "config.toml")
        for directory in (project, project.parent, self.base, Path(self.base.anchor)):
            self.assertIn(directory / ".codex" / "config.toml", paths)

    # -- shared app-server daemon ---------------------------------------

    def daemon_socket(self):
        path = peer.codex_daemon_socket_path(self.root)
        path.parent.mkdir(parents=True)
        return path

    @unittest.skipIf(os.name == "nt" or not hasattr(socket, "AF_UNIX"), "POSIX socket fixture")
    def test_present_daemon_socket_refuses_native_submission_only(self):
        # AF_UNIX paths are short; macOS per-user temp directories are not.
        short = Path(tempfile.mkdtemp(prefix="sp", dir="/tmp" if os.path.isdir("/tmp") else None))
        self.addCleanup(shutil.rmtree, short, True)
        self.root = short.resolve()
        path = self.daemon_socket()
        if len(os.fsencode(str(path))) > 100:
            self.skipTest("temporary path too long for an AF_UNIX socket")
        with contextlib.closing(socket.socket(socket.AF_UNIX)) as server:
            server.bind(str(path))
            self.refuses("shared_server_storage_unverifiable", native_submission=True)
            # Discovery and inventory read the home's own state, not the daemon.
            peer.check_codex_storage(self.root)

    def test_stale_or_nonsocket_daemon_entry_still_refuses(self):
        # Presence is enough: the daemon's startup storage is never observable.
        path = self.daemon_socket()
        path.write_text("", encoding="utf-8")
        self.refuses("shared_server_storage_unverifiable", native_submission=True)

    def test_daemon_refusal_applies_to_dry_run_and_send_before_any_process(self):
        self.database()
        self.daemon_socket().write_text("", encoding="utf-8")
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.root]), \
             mock.patch.object(peer, "codex_executable", return_value="fixture"), \
             mock.patch.object(peer.subprocess, "run") as run, \
             mock.patch.object(peer.subprocess, "Popen") as popen:
            for dry_run in (False, True):
                self.args.dry_run = dry_run
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.queue_codex(self.args, "fixture")
                self.assertEqual(caught.exception.details["reason"],
                                 "shared_server_storage_unverifiable")
            run.assert_not_called()
            popen.assert_not_called()

    # -- effect boundaries ----------------------------------------------

    def test_queue_pins_the_process_directory_to_the_inspected_home(self):
        self.database()
        elsewhere = self.base / "caller"
        (elsewhere / ".codex").mkdir(parents=True)
        # The caller's own project layers are irrelevant once the queue is pinned.
        (elsewhere / ".codex" / "config.toml").write_text(
            'sqlite_home = "%s"\n' % SECRET, encoding="utf-8")
        completed = mock.Mock(returncode=0, stdout="Queued message q-1 for thread %s.\n" % THREAD,
                              stderr="")
        previous = os.getcwd()
        os.chdir(elsewhere)
        self.addCleanup(os.chdir, previous)
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.root]), \
             mock.patch.object(peer, "codex_executable", return_value="fixture"), \
             mock.patch.object(peer.subprocess, "run", return_value=completed) as run:
            result = peer.queue_codex(self.args, "fixture")
        self.assertEqual(result["queueId"], "q-1")
        self.assertEqual(run.call_args.kwargs["cwd"], str(self.root))
        if not peer.IS_WINDOWS:
            self.assertEqual(run.call_args.kwargs["env"]["PWD"], str(self.root))

    def test_consumer_thread_directory_layers_refuse_dry_run_and_send(self):
        # The live writer normally started in the saved thread directory; its
        # project layers can make it poll storage other than the home's queue.
        project = self.base / "thread-project"
        (project / ".codex").mkdir(parents=True)
        (project / ".codex" / "config.toml").write_text(
            'sqlite_home = "%s"\n' % SECRET, encoding="utf-8")
        self.database(cwd=project)
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.root]), \
             mock.patch.object(peer, "codex_executable", return_value="fixture"), \
             mock.patch.object(peer.subprocess, "run") as run:
            for dry_run in (True, False):
                self.args.dry_run = dry_run
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.queue_codex(self.args, "fixture")
                self.assertEqual(caught.exception.details["reason"],
                                 "sqlite_home_project_configuration")
            run.assert_not_called()

    def test_missing_thread_directory_has_no_layers_to_inspect(self):
        self.database(cwd=self.base / "deleted-project")
        self.assertIsNone(peer.codex_thread_cwd(self.root, THREAD))
        self.assertIsNone(peer.codex_thread_cwd(self.root, "00000000-0000-4000-8000-000000000000"))
        peer.check_codex_consumer_storage(self.root, THREAD)

    def test_translated_native_home_checks_the_inherited_directory(self):
        self.database()
        caller = self.base / "caller"
        (caller / ".codex").mkdir(parents=True)
        (caller / ".codex" / "config.toml").write_text(
            'sqlite_home = "%s"\n' % SECRET, encoding="utf-8")
        previous = os.getcwd()
        os.chdir(caller)
        self.addCleanup(os.chdir, previous)
        self.args.codex_native_home = r"C:\fixture\home"
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.root]), \
             mock.patch.object(peer, "codex_executable", return_value="fixture"), \
             mock.patch.object(peer.subprocess, "run") as run:
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.queue_codex(self.args, "fixture")
            run.assert_not_called()
        self.assertEqual(caught.exception.details["reason"], "sqlite_home_project_configuration")

    def test_layer_change_at_effect_boundary_refuses_before_queue(self):
        self.database()
        def revalidate(*unused):
            self.system_paths[1].write_text('sqlite_home = "%s"\n' % SECRET, encoding="utf-8")
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.root]), \
             mock.patch.object(peer, "codex_executable", return_value="fixture"), \
             mock.patch.object(peer, "revalidate_codex_home", side_effect=revalidate), \
             mock.patch.object(peer.subprocess, "run") as run:
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.queue_codex(self.args, "fixture")
            run.assert_not_called()
        self.assertEqual(caught.exception.details["reason"], "sqlite_home_system_configuration")

    @unittest.skipUnless(sys.platform in ("darwin", "linux"), "wake is macOS/Linux only")
    def test_storage_refusal_does_not_consume_a_wake_reservation(self):
        self.database()
        socket_entry = self.root / "app-server-control" / "app-server-control.sock"
        socket_entry.parent.mkdir()
        socket_entry.write_text("", encoding="utf-8")
        self.args.wake = True
        self.args.wake_timeout = 1
        self.args.allow_inactive_codex_home = False
        version = mock.Mock(stdout=sorted(peer.CODEX_WAKE_VERSIONS)[0] + "\n")
        state = self.root / "session-peer" / "wake-locks" / (THREAD + ".lock")
        for attempt in range(4):
            with self.subTest(attempt=attempt), \
                    mock.patch.object(peer, "known_codex_homes", return_value=[self.root]), \
                    mock.patch.object(peer, "codex_executable", return_value="fixture"), \
                    mock.patch.object(peer.subprocess, "run", return_value=version) as run, \
                    mock.patch.object(peer.subprocess, "Popen") as popen, \
                    mock.patch.object(peer, "wake_target_rate_reserve",
                                      wraps=peer.wake_target_rate_reserve) as reserve:
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.queue_codex(self.args, "fixture")
                self.assertEqual(caught.exception.details["reason"],
                                 "shared_server_storage_unverifiable")
                reserve.assert_not_called()
                popen.assert_not_called()
                # Only the version probe ran; no queue child was started.
                self.assertTrue(all(call.args[0][1:] == ["--version"] for call in run.call_args_list))
            # The per-target budget file holds no reservation after any attempt.
            self.assertEqual(state.read_bytes() if state.exists() else b"", b"")

    def test_unreadable_or_malformed_consumer_metadata_refuses(self):
        with contextlib.closing(sqlite3.connect(self.root / "state_5.sqlite")) as conn:
            conn.execute("CREATE TABLE threads (id TEXT)")
            conn.execute("INSERT INTO threads VALUES (?)", (THREAD,))
            conn.commit()
        with self.assertRaises(peer.CcPeerError) as caught:
            peer.codex_thread_cwd(self.root, THREAD)
        self.assertEqual(caught.exception.details["reason"], "consumer_directory_unverifiable")
        (self.root / "state_5.sqlite").unlink()
        for value in ("relative/project", 7):
            with self.subTest(value=value):
                path = self.root / "state_5.sqlite"
                if path.exists():
                    path.unlink()
                with contextlib.closing(sqlite3.connect(path)) as conn:
                    conn.execute("CREATE TABLE threads (id TEXT, cwd)")
                    conn.execute("INSERT INTO threads VALUES (?, ?)", (THREAD, value))
                    conn.commit()
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.check_codex_consumer_storage(self.root, THREAD)
                self.assertEqual(caught.exception.details["reason"],
                                 "consumer_directory_unverifiable")
        for value in (None, ""):
            with self.subTest(value=value):
                path = self.root / "state_5.sqlite"
                path.unlink()
                with contextlib.closing(sqlite3.connect(path)) as conn:
                    conn.execute("CREATE TABLE threads (id TEXT, cwd)")
                    conn.execute("INSERT INTO threads VALUES (?, ?)", (THREAD, value))
                    conn.commit()
                self.assertIsNone(peer.codex_thread_cwd(self.root, THREAD))

    @unittest.skipIf(os.name == "nt", "wake is macOS/Linux only")
    def test_wake_checks_the_thread_directory_before_starting_app_server(self):
        project = self.base / "thread-project"
        (project / ".codex").mkdir(parents=True)
        (project / ".codex" / "config.toml").write_text(
            'sqlite_home = "%s"\n' % SECRET, encoding="utf-8")
        self.database(cwd=project)
        version = mock.Mock(stdout=sorted(peer.CODEX_WAKE_VERSIONS)[0] + "\n")
        with mock.patch.object(peer.subprocess, "run", return_value=version), \
             mock.patch.object(peer.subprocess, "Popen") as popen:
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.codex_wake_preflight(self.root, THREAD, "fixture")
            popen.assert_not_called()
        self.assertEqual(caught.exception.details["reason"], "sqlite_home_project_configuration")


if __name__ == "__main__":
    unittest.main()
