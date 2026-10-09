"""Isolated storage guards, not evidence of native delivery or consumption."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

import session_peer as peer
from tests.codex.support import THREAD


class CodexStorage(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.config = self.root / "config.toml"
        self.args = argparse.Namespace(codex_home=str(self.root), codex_bin="fixture",
            to="codex:" + THREAD, dry_run=False, all=False,
            allow_inactive_codex_home=True, wake=False)
        # No inherited user configuration or environments are inspected.
        patcher = mock.patch.dict(os.environ, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def refuses(self, reason=None):
        with self.assertRaises(peer.CcPeerError) as caught:
            peer.check_codex_storage(self.root)
        details = caught.exception.details
        self.assertEqual(details["status"], "refused")
        self.assertIs(details["submitted"], False)
        self.assertIs(details["retryAllowed"], False)
        self.assertNotIn(str(self.root), str(caught.exception))
        if reason:
            self.assertEqual(details["reason"], reason)

    def database(self):
        with contextlib.closing(sqlite3.connect(self.root / "state_5.sqlite")) as conn:
            conn.execute("CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)")
            conn.execute("INSERT INTO threads VALUES (?,?,?,?,?,?)", (THREAD, "fixture", str(self.root), 1, 0, "unused"))
            conn.commit()

    def test_root_quoted_escaped_dotted_and_table_storage_are_refused(self):
        for key in ("sqlite_home", "'sqlite_home'", '"sqlite_home"',
                    '"\\u0073qlite_home"', '"\\U00000073qlite_home"',
                    "sqlite_home.extra", '"sqlite_home" . extra'):
            with self.subTest(key=key):
                self.config.write_text(key + ' = "private-value"\n', encoding="utf-8")
                self.refuses("sqlite_home_configuration")
        for header in ("[sqlite_home]", '[["sqlite_home"]]'):
            self.config.write_text(header + '\nvalue="private"\n', encoding="utf-8")
            self.refuses("sqlite_home_configuration")

    def test_nested_case_distinct_comments_and_string_bodies_are_not_root_settings(self):
        cases = (
            '# sqlite_home="elsewhere"\nmodel="fixture"\n',
            'instructions="sqlite_home=elsewhere"\n',
            'instructions="""\nsqlite_home="elsewhere"\n"""\n',
            "instructions='''\n[sqlite_home]\n'''\n",
            'SQLITE_HOME="ignored-by-native-schema"\n',
            '[unselected]\nsqlite_home="elsewhere"\n',
            '[profiles.unselected]\nsqlite_home="elsewhere"\n',
            'unselected.sqlite_home="elsewhere"\n',
            'model_providers.fixture={name="sqlite_home", env_key="FIXTURE"}\n',
            'values=[\n"a", # sqlite_home\n"b",\n]\n',
        )
        for text in cases:
            with self.subTest(text=text):
                self.config.write_text(text, encoding="utf-8")
                peer.check_codex_storage(self.root)

    def test_unclassifiable_config_fails_without_reflecting_contents(self):
        for text in ('model="unterminated', '"unterminated = "private"',
                     '[broken\n', 'model=[1,2\n', 'model=}\n',
                     'model\n', 'model=\n', 'bad key="private"\n',
                     '"\\uD800"="private"\n'):
            with self.subTest(text=text):
                self.config.write_text(text, encoding="utf-8")
                self.refuses("storage_config_unverifiable")
        self.config.write_bytes(b'model="\xff"')
        self.refuses("storage_config_unverifiable")

    def test_bounded_regular_file_and_permission_checks(self):
        self.config.mkdir()
        self.refuses("storage_config_unverifiable")
        self.config.rmdir()
        self.config.write_bytes(b"x" * (peer.MAX_CODEX_CONFIG_BYTES + 1))
        self.refuses("storage_config_unverifiable")
        self.config.write_text('model="fixture"\n', encoding="utf-8")
        with mock.patch.object(peer.os, "open", side_effect=PermissionError("private")):
            self.refuses("storage_config_unverifiable")

    @unittest.skipIf(os.name == "nt", "POSIX FIFO/symlink guard")
    def test_nonregular_config_does_not_block_or_follow_links(self):
        os.mkfifo(self.config)
        self.refuses("storage_config_unverifiable")
        self.config.unlink()
        target = self.root / "target"
        target.write_text('model="fixture"\n', encoding="utf-8")
        self.config.symlink_to(target)
        self.refuses("storage_config_unverifiable")

    def test_environment_precedence_refuses_nonempty_even_same_home(self):
        for value in ("/private-relocation", "relative", str(self.root), " /private-relocation "):
            with self.subTest(value=value), mock.patch.dict(os.environ, {"CODEX_SQLITE_HOME": value}):
                self.refuses("sqlite_environment_override")
        for value in ("", " \t "):
            with mock.patch.dict(os.environ, {"CODEX_SQLITE_HOME": value}):
                env = peer.codex_process_environment(self.root)
                self.assertNotIn("CODEX_SQLITE_HOME", env)

    def test_environment_case_is_platform_specific(self):
        with mock.patch.dict(os.environ, {"codex_sqlite_home": "/private"}):
            with mock.patch.object(peer, "IS_WINDOWS", False):
                peer.check_codex_storage(self.root)
            with mock.patch.object(peer, "IS_WINDOWS", True):
                self.refuses("sqlite_environment_override")
        with mock.patch.dict(os.environ, {"codex_home": "unselected", "codex_sqlite_home": ""}), \
             mock.patch.object(peer, "IS_WINDOWS", True):
            self.assertEqual(peer.codex_process_environment(self.root)["CODEX_HOME"], str(self.root))
            self.assertNotIn("codex_home", peer.codex_process_environment(self.root))
            self.assertNotIn("codex_sqlite_home", peer.codex_process_environment(self.root))

    def test_native_home_translation_does_not_read_native_spelling(self):
        env = peer.codex_process_environment(self.root, r"C:\fixture\home")
        self.assertEqual(env["CODEX_HOME"], r"C:\fixture\home")

    def test_discovery_dry_run_real_queue_and_wake_refuse_before_process(self):
        self.database()
        self.config.write_text('sqlite_home="elsewhere"\n', encoding="utf-8")
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.root]), \
             mock.patch.object(peer, "codex_executable", return_value="fixture"), \
             mock.patch.object(peer.subprocess, "run") as run, \
             mock.patch.object(peer.subprocess, "Popen") as popen:
            for dry_run in (False, True):
                self.args.dry_run = dry_run
                for wake in (False, True):
                    self.args.wake = wake
                    with self.assertRaises(peer.CcPeerError):
                        peer.queue_codex(self.args, "fixture")
                with self.assertRaises(peer.CcPeerError):
                    peer.discover_codex(self.args)
            with self.assertRaises(peer.CcPeerError):
                peer.codex_wake_preflight(self.root, THREAD, "fixture")
            run.assert_not_called()
            popen.assert_not_called()

    def test_default_environment_and_explicit_home_selection_keep_guard(self):
        self.config.write_text('sqlite_home="elsewhere"\n', encoding="utf-8")
        for explicit in (None, str(self.root)):
            self.args.codex_home = explicit
            with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root)}):
                with self.assertRaises(peer.CcPeerError):
                    peer.discover_codex(self.args)
        self.args.codex_home = None
        with mock.patch.object(peer.Path, "home", return_value=self.root):
            default = self.root / ".codex"
            default.mkdir(exist_ok=True)
            (default / "config.toml").write_text('sqlite_home="elsewhere"\n', encoding="utf-8")
            with self.assertRaises(peer.CcPeerError):
                peer.discover_codex(self.args)

    def test_inventory_never_ignores_relocated_competing_home(self):
        self.database()
        other = self.root / "other"
        other.mkdir()
        (other / "config.toml").write_text('sqlite_home="elsewhere"\n', encoding="utf-8")
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.root, other]):
            with self.assertRaises(peer.CcPeerError):
                peer.resolve_codex_home(self.args, self.root, THREAD)

    def test_changed_config_at_effect_boundary_refuses_before_queue(self):
        self.database()
        def revalidate(*unused):
            self.config.write_text('sqlite_home="elsewhere"\n', encoding="utf-8")
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.root]), \
             mock.patch.object(peer, "codex_executable", return_value="fixture"), \
             mock.patch.object(peer, "revalidate_codex_home", side_effect=revalidate), \
             mock.patch.object(peer.subprocess, "run") as run:
            with self.assertRaises(peer.CcPeerError):
                peer.queue_codex(self.args, "fixture")
            run.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX fake executable (Windows covered with process-boundary mocks)")
    def test_isolated_fake_child_observes_selected_home_and_no_override(self):
        self.database()
        fixture = Path(__file__).parents[1] / "fixtures/codex_storage_cli.py"
        executable = self.root / "fake-codex"
        shutil.copyfile(fixture, executable)
        executable.chmod(0o700)
        self.args.codex_bin = str(executable)
        # env-based fixture shebang needs only the known local Python PATH.
        with mock.patch.dict(os.environ, {"PATH": os.defpath, "CODEX_SQLITE_HOME": "  "}), \
             mock.patch.object(peer, "known_codex_homes", return_value=[self.root]):
            result = peer.queue_codex(self.args, "fixture")
        self.assertEqual(result["queueId"], "fixture-storage")
        self.assertIs(result["consumptionConfirmed"], False)
        recorded = json.loads((self.root / "fixture-environment.json").read_text(encoding="utf-8"))
        self.assertEqual(recorded, {"home": str(self.root), "sqliteOverridePresent": False})


if __name__ == "__main__":
    unittest.main()
