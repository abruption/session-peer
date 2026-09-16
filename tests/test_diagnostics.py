"""Reply-address and doctor contracts. All fixtures are local and read-only."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock

import session_peer as peer


THREAD = "01900000-0000-7000-8000-000000000045"


class ReplyAddresses(unittest.TestCase):
    def test_local_claude_round_trip(self):
        identity = {"agent": "claude", "id": "my session", "target": "my session", "host": None}
        uri = peer.reply_address(identity, local=True)
        self.assertEqual(peer.parse_reply_address(uri), {
            "agent": "claude", "session": "my session", "transport": "local",
            "target": "my session", "uri": uri,
        })

    def test_ssh_codex_round_trip_preserves_home_as_data(self):
        identity = {
            "agent": "codex", "id": THREAD, "target": "codex:" + THREAD,
            "host": "alice@worker.example.ts.net", "codexHome": "/path with space/home",
        }
        uri = peer.reply_address(identity)
        parsed = peer.parse_reply_address(uri)
        self.assertEqual(parsed["target"], "codex:" + THREAD)
        self.assertEqual(parsed["transport"], "ssh")
        self.assertEqual(parsed["host"], "alice@worker.example.ts.net")
        self.assertEqual(parsed["codexHome"], "/path with space/home")

    def test_codex_home_accepts_both_platforms_as_remote_data(self):
        for home in ("/Users/alice/.codex", r"C:\Users\alice\.codex"):
            with self.subTest(home=home):
                uri = peer.reply_address({
                    "agent": "codex", "id": THREAD, "target": "codex:" + THREAD,
                    "host": "alice@worker", "codexHome": home,
                })
                self.assertEqual(peer.parse_reply_address(uri)["codexHome"], home)

    def test_envelope_carries_structured_and_legacy_reply_forms(self):
        identity = {
            "agent": "claude", "id": "worker", "target": "worker",
            "host": "alice@host.example.ts.net",
        }
        with mock.patch.object(peer, "sender_identity", return_value=identity):
            message = peer.wrap_message("hello", None, True, True)
        self.assertIn("Reply-To: session-peer://v1/reply?", message)
        self.assertIn("Reply: python3 ", message)
        route = peer.reply_route(identity, local=False)
        self.assertEqual(route["status"], "unverified")
        self.assertEqual(route["reason"], "reverse_ssh_not_checked")

    def test_rejects_malformed_or_unsafe_addresses(self):
        invalid = [
            "session-peer://v2/reply?agent=claude&session=x&transport=local",
            "session-peer://v1/reply?agent=claude&session=x&session=y&transport=local",
            "session-peer://v1/reply?agent=claude&session=x&transport=local&extra=y",
            "session-peer://v1/reply?agent=claude&session=x&transport=ssh",
            "session-peer://v1/reply?agent=claude&session=x&transport=local&host=worker",
            "session-peer://v1/reply?agent=claude&session=x%0Ay&transport=local",
            "session-peer://v1/reply?agent=claude&session=x%ZZ&transport=local",
            "session-peer://v1/reply?agent=claude&session=x&transport=ssh&host=-oProxyCommand%3Did",
            "session-peer://v1/reply?agent=codex&session=not-a-uuid&transport=local",
            ("session-peer://v1/reply?agent=codex&session=" + THREAD
             + "&transport=local&codexHome=relative"),
        ]
        for uri in invalid:
            with self.subTest(uri=uri), self.assertRaises(peer.CcPeerError):
                peer.parse_reply_address(uri)

    def test_structured_address_conflicts_fail_before_dispatch(self):
        uri = "session-peer://v1/reply?agent=claude&session=worker&transport=local"
        args = argparse.Namespace(to=uri, host=["elsewhere"], codex_home=None)
        with self.assertRaisesRegex(peer.CcPeerError, "combine"):
            peer.apply_reply_target(args)

    def test_same_machine_ssh_address_normalizes_to_local(self):
        uri = (
            "session-peer://v1/reply?agent=claude&session=worker&transport=ssh"
            "&host=alice%40this-machine"
        )
        args = argparse.Namespace(to=uri, host=[], codex_home=None)
        with mock.patch.object(peer, "is_self_ssh_destination", return_value=True):
            resolution = peer.apply_reply_target(args)
        self.assertEqual(args.to, "worker")
        self.assertEqual(args.host, [])
        self.assertEqual(resolution["transport"], "local")
        self.assertEqual(resolution["normalizedFrom"], "ssh_self")

    def test_ssh_address_routes_via_remote_dispatch_without_execution(self):
        hostile_name = "worker; touch /tmp/not-executed"
        uri = peer.reply_address({
            "agent": "claude", "id": hostile_name, "target": hostile_name,
            "host": "alice@remote",
        })
        output = io.StringIO()
        response = {"ok": True, "target": {"pid": 1, "name": hostile_name}}
        with mock.patch.object(peer, "is_self_ssh_destination", return_value=False), \
             mock.patch.object(peer, "tailscale_status", return_value={}), \
             mock.patch.object(peer, "run_remote", return_value=response) as remote, \
             contextlib.redirect_stdout(output):
            code = peer.main([
                "send", "--to", uri, "--no-from", "--no-reply-to", "--dry-run",
                "--json", "hello",
            ])
        self.assertEqual(code, 0)
        argv = remote.call_args.args[1]
        self.assertEqual(argv[3], hostile_name)
        self.assertEqual(json.loads(output.getvalue())["addressResolution"]["transport"], "ssh")

    def test_codex_address_forwards_home_to_the_destination(self):
        uri = peer.reply_address({
            "agent": "codex", "id": THREAD, "target": "codex:" + THREAD,
            "host": "alice@remote", "codexHome": "/opt/orca account/home",
        })
        response = {
            "ok": True, "target": {"agent": "codex", "id": THREAD},
            "status": "validated", "dryRun": True, "chars": 5,
            "codexHome": "/opt/orca account/home", "submitted": False,
            "consumptionConfirmed": False,
        }
        with mock.patch.object(peer, "is_self_ssh_destination", return_value=False), \
             mock.patch.object(peer, "tailscale_status", return_value={}), \
             mock.patch.object(peer, "run_remote", return_value=response) as remote, \
             contextlib.redirect_stdout(io.StringIO()):
            code = peer.main([
                "send", "--to", uri, "--no-from", "--no-reply-to", "--dry-run",
                "--json", "hello",
            ])
        self.assertEqual(code, 0)
        argv = remote.call_args.args[1]
        self.assertEqual(argv[argv.index("--codex-home") + 1], "/opt/orca account/home")


class ClaudeDoctor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_missing_home_is_distinct(self):
        with mock.patch.object(peer, "sessions_dir", return_value=self.root / "missing"):
            result = peer.diagnose_claude()
        self.assertEqual(result["status"], "missing_home")
        self.assertEqual(result["checks"][0]["code"], "sessions_dir_missing")

    def test_live_session_without_socket_is_unavailable(self):
        (self.root / "12.json").write_text(json.dumps({
            "pid": 12, "name": "worker", "messagingSocketPath": str(self.root / "missing.sock"),
        }))
        with mock.patch.object(peer, "sessions_dir", return_value=self.root), \
             mock.patch.object(peer, "pid_alive", return_value=True):
            result = peer.diagnose_claude()
        self.assertEqual(result["status"], "inbox_unavailable")
        self.assertEqual(result["checks"][0]["code"], "inbox_unavailable")

    @unittest.skipIf(peer.IS_WINDOWS, "Unix socket fixture")
    def test_live_unix_socket_is_available_but_only_filesystem_verified(self):
        path = self.root / "inbox.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(str(path))
        (self.root / "12.json").write_text(json.dumps({
            "pid": 12, "name": "worker", "messagingSocketPath": str(path),
        }))
        with mock.patch.object(peer, "sessions_dir", return_value=self.root), \
             mock.patch.object(peer, "pid_alive", return_value=True):
            result = peer.diagnose_claude()
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["checks"][0]["verification"], "filesystem_only")

    def test_permission_failure_is_distinct(self):
        path = mock.Mock()
        path.stat.side_effect = PermissionError("denied")
        path.__str__ = mock.Mock(return_value="/private/claude/sessions")
        with mock.patch.object(peer, "sessions_dir", return_value=path):
            result = peer.diagnose_claude()
        self.assertEqual(result["status"], "permission_denied")


class CodexDoctor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = argparse.Namespace(codex_home=str(self.root), codex_bin=None)

    def create_db(self, supported=True):
        conn = sqlite3.connect(self.root / "state_5.sqlite")
        if supported:
            conn.execute(
                "CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, "
                "archived INTEGER, rollout_path TEXT)"
            )
        else:
            conn.execute("CREATE TABLE threads (id TEXT)")
        conn.commit()
        conn.close()

    def test_missing_tool_and_home_are_separate_checks(self):
        with mock.patch.object(peer.shutil, "which", return_value=None):
            result = peer.diagnose_codex(self.args)
        self.assertEqual(result["status"], "missing_home")
        self.assertEqual(result["homes"][0]["code"], "state_db_missing")
        self.assertEqual(result["checks"][0]["code"], "codex_executable_missing")

    def test_unsupported_schema_is_explicit(self):
        self.create_db(supported=False)
        with mock.patch.object(peer.shutil, "which", return_value="/opt/codex"):
            result = peer.diagnose_codex(self.args)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["homes"][0]["code"], "unsupported_threads_schema")

    def test_readable_home_reports_count_and_source(self):
        self.create_db()
        with mock.patch.object(peer.shutil, "which", return_value="/opt/codex"):
            result = peer.diagnose_codex(self.args)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["homeSource"], "explicit")
        self.assertEqual(result["homes"][0]["sessionCount"], 0)

    def test_state_db_permission_failure_is_explicit(self):
        with mock.patch.object(Path, "stat", side_effect=PermissionError("denied")):
            result = peer.diagnose_codex_home(self.root)
        self.assertEqual(result["status"], "permission_denied")
        self.assertEqual(result["code"], "state_db_permission_denied")


class ReturnRouteDoctor(unittest.TestCase):
    def test_self_route_is_local_and_never_spawns_ssh(self):
        with mock.patch.object(peer, "is_self_ssh_destination", return_value=True), \
             mock.patch.object(peer.subprocess, "run") as run:
            result = peer.probe_return_route("alice@self")
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["transport"], "local")
        run.assert_not_called()

    def test_reverse_ssh_probe_is_noninteractive_and_strict(self):
        config = subprocess.CompletedProcess([], 0, "user alice\n", "")
        success = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(peer, "is_self_ssh_destination", return_value=False), \
             mock.patch.object(peer.shutil, "which", return_value="/usr/bin/ssh"), \
             mock.patch.object(peer.subprocess, "run", side_effect=[config, success]) as run:
            result = peer.probe_return_route("origin")
        self.assertEqual(result["status"], "verified")
        command = run.call_args_list[1].args[0]
        self.assertIn("BatchMode=yes", command)
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("PasswordAuthentication=no", command)
        self.assertEqual(command[-2:], ["origin", "true"])

    def test_authentication_failure_is_structured(self):
        config = subprocess.CompletedProcess([], 0, "user alice\n", "")
        failed = subprocess.CompletedProcess([], 255, "", "Permission denied (publickey).")
        with mock.patch.object(peer, "is_self_ssh_destination", return_value=False), \
             mock.patch.object(peer.shutil, "which", return_value="/usr/bin/ssh"), \
             mock.patch.object(peer.subprocess, "run", side_effect=[config, failed]):
            result = peer.probe_return_route("origin")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "authentication_failed")

    def test_remote_doctor_checks_return_route_only_when_requested(self):
        response = {
            "schemaVersion": 1, "ok": True, "host": "remote", "command": "doctor",
            "status": "partial", "claude": {"status": "available"},
            "codex": {"status": "missing_tool", "selectedHome": "/home/x/.codex"},
            "capabilities": {"replyObservation": {"status": "unsupported"}},
        }
        with mock.patch.object(peer, "tailscale_status", return_value={}), \
             mock.patch.object(peer, "run_remote", return_value=response) as remote, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(peer.main(["doctor", "--host", "worker", "--json"]), 0)
        self.assertNotIn("--_return-host", remote.call_args.args[1])

        with mock.patch.object(peer, "tailscale_status", return_value={}), \
             mock.patch.object(peer, "run_remote", return_value=response) as remote, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(peer.main([
                "doctor", "--host", "worker", "--check-return-route",
                "--reply-to", "alice@origin", "--json",
            ]), 0)
        argv = remote.call_args.args[1]
        self.assertEqual(argv[argv.index("--_return-host") + 1], "alice@origin")

    def test_doctor_json_uses_common_envelope_and_reports_wait_unsupported(self):
        args = argparse.Namespace(
            codex_home=None, codex_bin=None, _return_host=None,
        )
        payload = {
            "status": "partial", "claude": {"status": "available"},
            "codex": {"status": "missing_tool", "selectedHome": "/x"},
            "capabilities": {"replyObservation": {
                "status": "unsupported", "reason": "no_cross_agent_acknowledgement_api",
            }},
        }
        output = io.StringIO()
        with mock.patch.object(peer, "doctor_payload", return_value=payload), \
             contextlib.redirect_stdout(output):
            code = peer.main(["doctor", "--json"])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["command"], "doctor")
        self.assertEqual(result["schemaVersion"], 1)
        self.assertEqual(result["capabilities"]["replyObservation"]["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
