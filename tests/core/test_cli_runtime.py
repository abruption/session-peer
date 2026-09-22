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


class VersionParsing(unittest.TestCase):
    def test_orders_releases(self):
        self.assertLess(session_peer.parse_version("0.2.0"), session_peer.parse_version("0.3.0"))
        self.assertLess(session_peer.parse_version("v0.9.0"), session_peer.parse_version("v0.10.0"))
        self.assertEqual(session_peer.parse_version("v1.2.3"), session_peer.parse_version("1.2.3"))

    def test_survives_junk_without_raising(self):
        # A malformed tag must not crash an update check; sorting lowest means
        # "don't offer this as newer".
        for text in ("", "not-a-version", "v..", "1.x.3"):
            self.assertIsInstance(session_peer.parse_version(text), tuple)
        self.assertLess(session_peer.parse_version("junk"), session_peer.parse_version("0.0.1"))

    def test_ignores_anything_past_patch(self):
        self.assertEqual(session_peer.parse_version("1.2.3.4"), (1, 2, 3))

    def test_orders_pep440_and_human_prerelease_spellings(self):
        ordered = [
            "1.0.0a1", "v1.0.0-alpha.2", "1.0.0b1",
            "v1.0.0-beta.2", "1.0.0rc1", "v1.0.0-rc.2", "1.0.0",
        ]
        parsed = [session_peer.release_version(value) for value in ordered]
        self.assertTrue(all(value is not None for value in parsed))
        self.assertEqual(parsed, sorted(parsed))

    def test_rejects_ambiguous_release_versions(self):
        for text in ("1.0", "1.0.0-alpha", "1.0.0-dev1", "01.0.0", "latest"):
            with self.subTest(text=text):
                self.assertIsNone(session_peer.release_version(text))


class RemoteInstalledVersion(unittest.TestCase):
    """Why this exists at all: run_remote() ships and runs *our* source, so
    asking the remote command to report itself would only echo our version.
    The installed copy is the one that can fall behind."""

    def run_with(self, stdout):
        completed = mock.Mock(stdout=stdout, returncode=0)
        with mock.patch.object(session_peer.subprocess, "run", return_value=completed):
            return session_peer.remote_installed_version("web-01", [])

    def test_reads_the_reported_version(self):
        self.assertEqual(self.run_with("session-peer 0.2.0\n"), "0.2.0")

    def test_none_when_not_installed(self):
        self.assertIsNone(self.run_with(""))
        self.assertIsNone(self.run_with("python3: can't open file\n"))

    def test_ssh_failure_is_not_reported_as_not_installed(self):
        with mock.patch.object(session_peer.subprocess, "run", side_effect=OSError("boom")):
            with self.assertRaises(session_peer.CcPeerError) as caught:
                session_peer.remote_installed_version("web-01", [])
        self.assertEqual(caught.exception.details["sshFailure"], "transport_failed")

    def test_still_validates_ssh_arguments(self):
        # This path builds its own ssh command, so it needs the same guard.
        with self.assertRaises(session_peer.CcPeerError):
            session_peer.remote_installed_version("-oProxyCommand=whoami", [])


class ErrorHandling(unittest.TestCase):
    """Unhandled exceptions must not break the --json contract."""

    def test_main_catches_unexpected_exception_json(self):
        import io
        buf = io.StringIO()
        with mock.patch.object(session_peer, "build_parser") as bp:
            ns = argparse.Namespace(
                func=mock.Mock(side_effect=RuntimeError("boom")),
                json=True,
                command="list",
                host=[],
            )
            bp.return_value.parse_args.return_value = ns
            with mock.patch("builtins.print", side_effect=lambda *a, **kw: buf.write(a[0])):
                code = session_peer.main(["list", "--agent", "claude", "--json"])
        result = json.loads(buf.getvalue())
        self.assertFalse(result["ok"])
        self.assertEqual(result["command"], "list")
        self.assertEqual(result["host"], session_peer.local_host())
        self.assertEqual(result["schemaVersion"], 1)
        self.assertIn("boom", result["error"])
        self.assertEqual(code, session_peer.EXIT_ERROR)

    def test_main_catches_unexpected_exception_human(self):
        import io
        buf = io.StringIO()
        with mock.patch.object(session_peer, "build_parser") as bp:
            ns = argparse.Namespace(
                func=mock.Mock(side_effect=RuntimeError("boom")),
                json=False,
                command="list",
                host=[],
            )
            bp.return_value.parse_args.return_value = ns
            with mock.patch("builtins.print", side_effect=lambda *a, **kw: buf.write(a[0])):
                code = session_peer.main(["list"])
        self.assertIn("boom", buf.getvalue())
        self.assertEqual(code, session_peer.EXIT_ERROR)

    def test_discover_reports_permission_error(self):
        with mock.patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(session_peer.CcPeerError, "Cannot read Claude sessions"):
                session_peer.discover()

    def test_remote_error_keeps_structured_codex_home_resolution(self):
        resolution = {"schemaVersion": 1, "status": "unknown", "selected": None,
                      "reason": "active_writer_unverified", "candidates": []}
        completed = subprocess.CompletedProcess(
            [], 1,
            stdout=json.dumps({"ok": False, "error": "ambiguous",
                               "codexHomeResolution": resolution}),
            stderr="",
        )
        with mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
             mock.patch.object(session_peer.subprocess, "run", return_value=completed), \
             self.assertRaises(session_peer.CcPeerError) as caught:
            session_peer.run_remote("worker", ["send"], [])
        self.assertEqual(caught.exception.details["codexHomeResolution"], resolution)


class JsonResponseContract(unittest.TestCase):
    def assert_envelope(self, result, command, ok=True, host="local-node"):
        self.assertEqual(result["schemaVersion"], 1)
        self.assertIs(result["ok"], ok)
        self.assertEqual(result["host"], host)
        self.assertEqual(result["command"], command)

    def test_local_list_send_and_update_share_the_envelope(self):
        with mock.patch.object(session_peer.socket, "gethostname", return_value="local-node"):
            output = io.StringIO()
            with mock.patch.object(session_peer, "discover", return_value=[]), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(session_peer.main(["list", "--agent", "claude", "--json"]), 0)
            listing = json.loads(output.getvalue())
            self.assert_envelope(listing, "list")
            self.assertEqual(listing["sessions"], [])

            output = io.StringIO()
            session = {"pid": 7, "name": "worker", "reachable": True,
                       "socket": "/tmp/7.sock", "alive": True}
            with mock.patch.object(session_peer, "discover", return_value=[session]), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(session_peer.main([
                    "send", "--to", "worker", "--dry-run", "--no-from",
                    "--no-reply-to", "--json", "hello",
                ]), 0)
            sending = json.loads(output.getvalue())
            self.assert_envelope(sending, "send")
            self.assertTrue(sending["dryRun"])

            output = io.StringIO()
            with mock.patch.object(session_peer, "installed_as_distribution", return_value=True), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(session_peer.main(["update", "--json"]), 0)
            updating = json.loads(output.getvalue())
            self.assert_envelope(updating, "update")
            self.assertEqual(updating["managedBy"], "package-manager")

    def test_command_wide_remote_failure_is_attributed_to_each_destination(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = session_peer.main([
                "send", "--host", "first", "--host", "second", "--to", "worker",
                "--no-from", "--no-reply-to", "--json", " ",
            ])
        results = json.loads(output.getvalue())
        self.assertEqual(code, session_peer.EXIT_ERROR)
        self.assertEqual([item["host"] for item in results], ["first", "second"])
        for item in results:
            self.assert_envelope(item, "send", ok=False, host=item["host"])
            self.assertIn("empty", item["error"])


class MultiHost(unittest.TestCase):
    """--host is repeatable: every host is visited, one failure does not stop the rest."""

    def test_list_iterates_over_hosts(self):
        calls = []
        def fake_remote(host, argv, opts):
            calls.append(host)
            return {"sessions": []}
        with mock.patch.object(session_peer, "run_remote", side_effect=fake_remote), \
             mock.patch.object(session_peer, "remote_installed_version", return_value=None):
            session_peer.cmd_list(argparse.Namespace(
                host=["hostA", "hostB"], ssh_opt=[], json=False, all=False))
        self.assertEqual(calls, ["hostA", "hostB"])

    def test_send_delivers_to_both_hosts(self):
        calls = []
        def fake_remote(host, argv, opts):
            calls.append(host)
            return {"ok": True, "target": {"pid": 1, "name": "w"}}
        with mock.patch.object(session_peer, "run_remote", side_effect=fake_remote):
            session_peer.cmd_send(argparse.Namespace(
                host=["hostA", "hostB"], ssh_opt=[], json=False,
                b64=None, message="hi", to="w", reply_to=None,
                no_reply_to=True, no_from=True, dry_run=False))
        self.assertEqual(calls, ["hostA", "hostB"])

    def test_one_failure_continues(self):
        def fail_then_ok(host, argv, opts):
            if host == "bad":
                raise session_peer.CcPeerError("unreachable")
            return {"sessions": []}
        with mock.patch.object(session_peer, "run_remote", side_effect=fail_then_ok), \
             mock.patch.object(session_peer, "remote_installed_version", return_value=None):
            code = session_peer.cmd_list(argparse.Namespace(
                host=["bad", "good"], ssh_opt=[], json=False, all=False))
        self.assertEqual(code, session_peer.EXIT_ERROR)

    def test_ssh_failure_details_survive_multi_host_results(self):
        failure = session_peer.CcPeerError(
            "SSH authentication failed for deploy@bad",
            {"sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
             "sshFailure": "authentication_failed"},
        )
        success = {
            "ok": True, "target": {"pid": 1, "name": "w"},
            "sshUser": "release", "sshUserSource": "explicit",
        }
        output = io.StringIO()
        with mock.patch.object(session_peer, "run_remote",
                               side_effect=[failure, success]), \
             mock.patch.object(session_peer, "tailscale_status", return_value=None), \
             contextlib.redirect_stdout(output):
            code = session_peer.main([
                "send", "--host", "bad", "--host", "release@good",
                "--to", "w", "--no-from", "--no-reply-to", "--json", "hi",
            ])
        results = json.loads(output.getvalue())
        self.assertEqual(code, session_peer.EXIT_ERROR)
        self.assertEqual(results[0]["sshFailure"], "authentication_failed")
        self.assertEqual(results[0]["sshUser"], "deploy")
        self.assertEqual(results[1]["sshUser"], "release")
        for result in results:
            self.assertEqual(result["schemaVersion"], 1)
            self.assertEqual(result["command"], "send")

    def test_single_host_send_json_is_flat(self):
        import io
        buf = io.StringIO()
        with mock.patch.object(session_peer, "run_remote",
                               return_value={"ok": True, "target": {"pid": 1, "name": "w"}}), \
             mock.patch("builtins.print", side_effect=lambda *a, **kw: buf.write(a[0])):
            session_peer.cmd_send(argparse.Namespace(
                host=["hostA"], ssh_opt=[], json=True,
                b64=None, message="hi", to="w", reply_to=None,
                no_reply_to=True, no_from=True, dry_run=False))
        result = json.loads(buf.getvalue())
        self.assertIsInstance(result, dict)
        self.assertNotIsInstance(result, list)
        self.assertTrue(result["ok"])
        self.assertEqual(result["host"], "hostA")
        self.assertEqual(result["command"], "send")
        self.assertEqual(result["schemaVersion"], 1)


class PushToRemote(unittest.TestCase):
    def test_builds_correct_ssh_command(self):
        fake_result = subprocess.CompletedProcess([], 0, stdout="session-peer 0.4.0\n", stderr="")
        with mock.patch("subprocess.run", return_value=fake_result) as run, \
             mock.patch("pathlib.Path.read_bytes", return_value=b"source"):
            version = session_peer.push_to_remote("web-01", ["-p", "2222"])
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "ssh")
        self.assertIn("-p", cmd)
        self.assertIn("web-01", cmd)
        self.assertIn("base64 -d", cmd[-1])
        self.assertEqual(version, "0.4.0")

    def test_validates_host(self):
        with self.assertRaises(session_peer.CcPeerError):
            session_peer.push_to_remote("-oProxyCommand=whoami", [])

    def test_update_host_pushes_when_outdated(self):
        with mock.patch.object(session_peer, "remote_installed_version", return_value="0.3.0"), \
             mock.patch.object(session_peer, "push_to_remote", return_value="0.4.0") as push, \
             mock.patch.object(session_peer, "ssh_user_metadata", return_value={
                 "sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
             }):
            session_peer.cmd_update(argparse.Namespace(
                host=["web-01"], ssh_opt=[], json=False, check=False))
        push.assert_called_once_with("web-01", [], {
            "sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
        })

    def test_update_host_skips_when_current(self):
        with mock.patch.object(session_peer, "remote_installed_version",
                               return_value=session_peer.__version__), \
             mock.patch.object(session_peer, "push_to_remote") as push, \
             mock.patch.object(session_peer, "ssh_user_metadata", return_value={
                 "sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
             }):
            session_peer.cmd_update(argparse.Namespace(
                host=["web-01"], ssh_opt=[], json=False, check=False))
        push.assert_not_called()

    def test_update_host_check_reports_only(self):
        with mock.patch.object(session_peer, "remote_installed_version", return_value="0.3.0"), \
             mock.patch.object(session_peer, "push_to_remote") as push, \
             mock.patch.object(session_peer, "ssh_user_metadata", return_value={
                 "sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
             }):
            session_peer.cmd_update(argparse.Namespace(
                host=["web-01"], ssh_opt=[], json=False, check=True))
        push.assert_not_called()
