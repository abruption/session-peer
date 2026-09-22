"""Core session-peer contract tests; standard-library only and offline."""

import argparse
import base64
import contextlib
import io
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import session_peer


class ClientUpdateNotice(unittest.TestCase):
    NOTICE = {
        "schemaVersion": 1,
        "status": "available",
        "current": "0.7.0",
        "latest": "0.7.1",
        "checkedAt": "2026-09-16T10:00:00Z",
        "source": "github_release_cache",
        "command": "session-peer update",
    }

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name) / "cache/session-peer/update.json"
        self.addCleanup(setattr, session_peer, "_CLIENT_UPDATE_NOTICE", None)

    @staticmethod
    def args(**overrides):
        values = {
            "command": "list", "host": [], "no_update_notice": False,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_stable_versions_are_strict(self):
        self.assertEqual(session_peer.stable_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(session_peer.stable_version("0.7.0"), (0, 7, 0))
        for value in ("1.2", "1.2.3.4", "1.2.3-rc1", "01.2.3", "latest", None):
            with self.subTest(value=value):
                self.assertIsNone(session_peer.stable_version(value))

    def test_latest_release_rejects_malformed_and_prerelease_responses(self):
        for response in (b"[]", b'{"tag_name":"v0.8.0-rc1"}'):
            with self.subTest(response=response), \
                 mock.patch.object(session_peer.urllib.request, "urlopen", return_value=io.BytesIO(response)), \
                 self.assertRaises(session_peer.CcPeerError):
                session_peer.latest_release()

    @mock.patch.object(session_peer, "__version__", "0.7.0")
    def test_fresh_newer_cache_produces_structured_notice(self):
        session_peer.write_update_cache("v0.7.1", self.cache, checked_at=1_000)
        with mock.patch.object(session_peer, "update_cache_path", return_value=self.cache), \
             mock.patch.object(session_peer, "installed_as_distribution", return_value=False):
            notice = session_peer.prepare_client_update(self.args(), now=1_001)
        self.assertEqual(notice, {
            **self.NOTICE, "checkedAt": "1970-01-01T00:16:40Z",
        })

    @mock.patch.object(session_peer, "__version__", "1.0.0a1")
    def test_alpha_notices_the_final_release_but_not_an_older_stable(self):
        session_peer.write_update_cache("1.0.0", self.cache, checked_at=1_000)
        with mock.patch.object(session_peer, "update_cache_path", return_value=self.cache), \
             mock.patch.object(session_peer, "installed_as_distribution", return_value=False):
            notice = session_peer.prepare_client_update(self.args(), now=1_001)
        self.assertEqual(notice["current"], "1.0.0a1")
        self.assertEqual(notice["latest"], "1.0.0")

        session_peer.write_update_cache("0.9.0", self.cache, checked_at=1_000)
        with mock.patch.object(session_peer, "update_cache_path", return_value=self.cache):
            self.assertIsNone(session_peer.prepare_client_update(self.args(), now=1_001))

    def test_current_expired_missing_and_malformed_states_are_explicit(self):
        session_peer.write_update_cache("0.7.0", self.cache, checked_at=1_000)
        self.assertEqual(session_peer.read_update_cache(self.cache, now=1_001)["status"], "fresh")
        self.assertEqual(
            session_peer.read_update_cache(
                self.cache, now=1_000 + session_peer.UPDATE_CACHE_TTL_SECONDS
            )["status"],
            "expired",
        )
        self.cache.unlink()
        self.assertEqual(session_peer.read_update_cache(self.cache, now=1_001), {"status": "missing"})
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_text("not json", encoding="utf-8")
        self.assertEqual(session_peer.read_update_cache(self.cache, now=1_001)["status"], "invalid")

    def test_stale_or_bad_cache_schedules_once_and_never_breaks_command(self):
        calls = []
        with mock.patch.object(session_peer, "update_cache_path", return_value=self.cache):
            self.assertIsNone(session_peer.prepare_client_update(
                self.args(), now=1_000, launcher=lambda: calls.append("refresh")
            ))
            self.assertIsNone(session_peer.prepare_client_update(
                self.args(), now=1_000, launcher=lambda: (_ for _ in ()).throw(OSError("no cache"))
            ))
        self.assertEqual(calls, ["refresh"])

    def test_opt_out_and_local_update_do_not_schedule_automatic_refresh(self):
        launch = mock.Mock()
        with mock.patch.object(session_peer, "update_cache_path", return_value=self.cache), \
             mock.patch.dict(os.environ, {session_peer.UPDATE_NOTICE_ENV: "1"}):
            self.assertIsNone(session_peer.prepare_client_update(self.args(), launcher=launch))
        self.assertIsNone(session_peer.prepare_client_update(
            self.args(no_update_notice=True), launcher=launch
        ))
        self.assertIsNone(session_peer.prepare_client_update(
            self.args(command="update"), launcher=launch
        ))
        launch.assert_not_called()

    def test_atomic_cache_is_private_and_background_lock_is_single_flight(self):
        session_peer.write_update_cache("0.6.3", self.cache, checked_at=1_000)
        if not session_peer.IS_WINDOWS:
            self.assertEqual(self.cache.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.cache.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.cache.parent.glob("*.tmp")), [])

        launches = []
        fake_popen = lambda *args, **kwargs: launches.append((args, kwargs))
        self.assertTrue(session_peer.schedule_update_refresh(
            self.cache, now=1_001, popen=fake_popen
        ))
        self.assertFalse(session_peer.schedule_update_refresh(
            self.cache, now=1_001, popen=fake_popen
        ))
        self.assertEqual(len(launches), 1)
        command = launches[0][0][0]
        self.assertEqual(command[-1], session_peer.UPDATE_REFRESH_ARG)

    def test_refresh_launcher_failure_releases_lock_for_a_later_attempt(self):
        def fail(*args, **kwargs):
            raise OSError("cannot launch")

        self.assertFalse(session_peer.schedule_update_refresh(
            self.cache, now=1_001, popen=fail
        ))
        self.assertFalse(session_peer.update_refresh_lock_path(self.cache).exists())
        self.assertTrue(session_peer.schedule_update_refresh(
            self.cache, now=1_002, popen=lambda *args, **kwargs: None
        ))

    def test_stale_lock_replacement_race_does_not_remove_the_winners_lock(self):
        lock = session_peer.update_refresh_lock_path(self.cache)
        lock.parent.mkdir(parents=True)
        lock.touch()
        os.utime(lock, (0, 0))
        original_open = os.open
        calls = 0

        def racing_open(path, flags, mode=0o777):
            nonlocal calls
            calls += 1
            if calls == 2:
                winner = original_open(path, flags, mode)
                os.close(winner)
                raise FileExistsError(path)
            return original_open(path, flags, mode)

        with mock.patch.object(session_peer.os, "open", side_effect=racing_open):
            self.assertFalse(session_peer.schedule_update_refresh(
                self.cache, now=session_peer.UPDATE_REFRESH_LOCK_SECONDS + 1,
                popen=lambda *args, **kwargs: None,
            ))
        self.assertTrue(lock.exists())

    def test_background_network_failure_is_silent_and_releases_lock(self):
        lock = session_peer.update_refresh_lock_path(self.cache)
        lock.parent.mkdir(parents=True)
        lock.touch()
        with mock.patch.object(session_peer, "update_cache_path", return_value=self.cache), \
             mock.patch.object(
                 session_peer, "latest_release", side_effect=session_peer.CcPeerError("timeout")
             ):
            self.assertEqual(session_peer.refresh_update_cache_background(), 0)
        self.assertFalse(lock.exists())
        self.assertFalse(self.cache.exists())

    def test_client_notice_preserves_dict_and_list_response_shapes(self):
        with mock.patch.object(session_peer, "_CLIENT_UPDATE_NOTICE", self.NOTICE):
            one = session_peer.with_client_update({"ok": True, "remoteVersion": "0.6.1"})
            many = session_peer.with_client_update([
                {"host": "a", "remoteVersion": "0.6.1"}, {"host": "b"},
            ])
        self.assertIsInstance(one, dict)
        self.assertEqual(one["remoteVersion"], "0.6.1")
        self.assertEqual(one["clientUpdate"], self.NOTICE)
        self.assertIsInstance(many, list)
        self.assertTrue(all(item["clientUpdate"] == self.NOTICE for item in many))

    def test_cli_json_and_human_notice_remain_separately_parseable(self):
        with mock.patch.object(session_peer, "prepare_client_update", return_value=self.NOTICE), \
             mock.patch.object(session_peer, "discover", return_value=[]), \
             mock.patch.object(session_peer.sys, "argv", ["session-peer", "list", "--agent", "claude", "--json"]), \
             contextlib.redirect_stdout(io.StringIO()) as stdout, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(session_peer.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())["clientUpdate"], self.NOTICE)
        self.assertEqual(stderr.getvalue(), "")

        with mock.patch.object(session_peer, "prepare_client_update", return_value=self.NOTICE), \
             mock.patch.object(session_peer, "discover", return_value=[]), \
             mock.patch.object(session_peer.sys, "argv", ["session-peer", "list", "--agent", "claude"]), \
             contextlib.redirect_stdout(io.StringIO()) as stdout, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(session_peer.main(), 0)
        self.assertIn("No reachable", stdout.getvalue())
        self.assertIn("Update available: 0.7.0", stderr.getvalue())

    def test_prepare_failure_never_changes_primary_cli_result(self):
        with mock.patch.object(
                 session_peer, "prepare_client_update", side_effect=OSError("cache unavailable")
             ), \
             mock.patch.object(session_peer, "discover", return_value=[]), \
             mock.patch.object(session_peer.sys, "argv", ["session-peer", "list", "--agent", "claude", "--json"]), \
             contextlib.redirect_stdout(io.StringIO()) as stdout, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(session_peer.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())["sessions"], [])
        self.assertEqual(stderr.getvalue(), "")

    def test_multi_host_cli_prepares_once_and_remote_calls_opt_out(self):
        prepare = mock.Mock(return_value=self.NOTICE)
        remote = mock.Mock(return_value={"sessions": []})
        with mock.patch.object(session_peer, "prepare_client_update", prepare), \
             mock.patch.object(session_peer, "tailscale_status", return_value={}), \
             mock.patch.object(session_peer, "run_remote", remote), \
             mock.patch.object(session_peer, "remote_installed_version", return_value="0.7.0"), \
             mock.patch.object(session_peer, "latest_release") as latest, \
             mock.patch.object(
                 session_peer.sys, "argv",
                 ["session-peer", "list", "--host", "one", "--host", "two", "--json"],
             ), \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(session_peer.main(), 0)
        prepare.assert_called_once()
        latest.assert_not_called()
        self.assertEqual(remote.call_count, 2)
        self.assertTrue(all(
            call.args[1] == ["list", "--no-update-notice"]
            for call in remote.call_args_list
        ))
        result = json.loads(stdout.getvalue())
        self.assertEqual([item["host"] for item in result], ["one", "two"])
        self.assertTrue(all(item["clientUpdate"] == self.NOTICE for item in result))

    def test_package_manager_specific_update_commands(self):
        with mock.patch.object(session_peer, "installed_as_distribution", return_value=False):
            self.assertEqual(session_peer.update_command(), "session-peer update")
        cases = {
            "/home/me/.local/pipx/venvs/session-peer": "pipx upgrade session-peer",
            "/home/me/.local/share/uv/tools/session-peer": "uv tool upgrade session-peer",
            "/opt/session-peer-venv": "python -m pip install --upgrade session-peer",
        }
        for prefix, expected in cases.items():
            with self.subTest(prefix=prefix), \
                 mock.patch.object(session_peer, "installed_as_distribution", return_value=True), \
                 mock.patch.object(session_peer.sys, "prefix", prefix):
                self.assertEqual(session_peer.update_command(), expected)

    def test_help_exposes_notice_opt_out(self):
        for command in ("list", "send", "update"):
            self.assertIn(
                "--no-update-notice",
                session_peer.build_parser()._subparsers._group_actions[0]
                .choices[command].format_help(),
            )


class PackageManagement(unittest.TestCase):
    def test_package_update_does_not_download(self):
        import contextlib
        import io
        with mock.patch.object(session_peer, "installed_as_distribution", return_value=True), \
             mock.patch.object(session_peer, "latest_release") as latest, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(session_peer.main(["update", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["managedBy"], "package-manager")
        latest.assert_not_called()

    @mock.patch.object(session_peer, "__version__", "0.7.0")
    def test_package_update_check_refreshes_cache_and_reports_command(self):
        import contextlib
        import io
        args = argparse.Namespace(host=[], check=True, json=True)
        with mock.patch.object(session_peer, "installed_as_distribution", return_value=True), \
             mock.patch.object(session_peer, "update_command", return_value="pipx upgrade session-peer"), \
             mock.patch.object(session_peer, "latest_release", return_value=("v0.7.1", "url")), \
             mock.patch.object(session_peer, "write_update_cache") as write, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(session_peer.cmd_update(args), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["outdated"])
        self.assertEqual(result["updateCommand"], "pipx upgrade session-peer")
        write.assert_called_once_with("v0.7.1")

    @mock.patch.object(session_peer, "__version__", "1.0.0a1")
    def test_package_alpha_reports_the_final_as_newer(self):
        args = argparse.Namespace(host=[], check=True, json=True)
        with mock.patch.object(session_peer, "installed_as_distribution", return_value=True), \
             mock.patch.object(session_peer, "update_command", return_value="pipx upgrade session-peer"), \
             mock.patch.object(session_peer, "latest_release", return_value=("v1.0.0", "url")), \
             mock.patch.object(session_peer, "write_update_cache"), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(session_peer.cmd_update(args), 0)
        self.assertTrue(json.loads(output.getvalue())["outdated"])

    def test_new_reply_variable_precedes_legacy(self):
        with mock.patch.dict(os.environ, {"SESSION_PEER_REPLY_HOST": "alice@new", "CC_PEER_REPLY_HOST": "bob@old"}), \
             mock.patch.object(session_peer, "own_session", return_value={"name": "worker", "pid": 42}), \
             mock.patch.object(session_peer, "tailscale_status", return_value=None):
            self.assertEqual(session_peer.sender_identity(None), {
                "agent": "claude", "id": "worker", "target": "worker", "host": "alice@new"
            })
