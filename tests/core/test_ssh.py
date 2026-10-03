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


class TailnetAddress(unittest.TestCase):
    def test_accepts_cgnat_range(self):
        for addr in ("100.64.0.1", "100.122.73.69", "100.127.255.255"):
            self.assertTrue(session_peer.is_tailnet_address(addr), addr)

    def test_rejects_public_addresses_that_merely_start_with_100(self):
        # 100.200.x.x is ordinary public space; matching on "100." alone took it.
        for addr in ("100.200.1.1", "100.63.0.1", "100.128.0.1"):
            self.assertFalse(session_peer.is_tailnet_address(addr), addr)

    def test_rejects_out_of_range_octets(self):
        for addr in ("100.64.999.999", "100.64.0.256", "100.64.0"):
            self.assertFalse(session_peer.is_tailnet_address(addr), addr)

    def test_rejects_non_addresses(self):
        for addr in ("", "not-an-ip", "100.64.0.1.5", "100.64.0.x"):
            self.assertFalse(session_peer.is_tailnet_address(addr), addr)


class SshArgumentChecks(unittest.TestCase):
    """--host and --ssh-opt reach ssh directly, so they are a trust boundary."""

    def test_host_may_not_start_with_a_dash(self):
        # ssh has no `--`, so a leading dash makes the host an option.
        with self.assertRaises(session_peer.CcPeerError):
            session_peer.check_ssh_argument("-oProxyCommand=touch /tmp/x", "--host")

    def test_rejects_options_that_run_a_local_command(self):
        for value in (
            "-oProxyCommand=whoami",
            "-o ProxyCommand=whoami",
            "-oPROXYCOMMAND=whoami",
            "-oLocalCommand=whoami",
            "-oPermitLocalCommand=yes",
        ):
            with self.assertRaises(session_peer.CcPeerError, msg=value):
                session_peer.check_ssh_argument(value, "--ssh-opt")

    def test_allows_ordinary_options(self):
        # ProxyJump takes a host, not a command — it is how you cross a bastion.
        for value in ("-p", "2222", "-oConnectTimeout=8", "-oProxyJump=bastion"):
            session_peer.check_ssh_argument(value, "--ssh-opt")

    def test_allows_ordinary_hosts(self):
        for value in ("web-01", "ubuntu@10.0.0.4", "100.64.0.1"):
            session_peer.check_ssh_argument(value, "--host")


class SshUserResolution(unittest.TestCase):
    @staticmethod
    def completed(stdout="", stderr="", returncode=0):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def test_explicit_user_takes_precedence_without_config_probe(self):
        with mock.patch.object(session_peer.subprocess, "run") as run:
            result = session_peer.ssh_user_metadata("release-user@build-alias", [])
        self.assertEqual(result, {
            "sshUser": "release-user", "sshUserSource": "explicit",
        })
        run.assert_not_called()

    def test_ssh_config_or_local_default_uses_original_alias_and_options(self):
        completed = self.completed("host build-alias\nuser deploy\nhostname verified.example.ts.net\n")
        with mock.patch.object(session_peer.subprocess, "run", return_value=completed) as run:
            result = session_peer.ssh_user_metadata(
                "build-alias", ["-o", "HostName=verified.example.ts.net", "-p", "2222"]
            )
        self.assertEqual(result, {
            "sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
        })
        self.assertEqual(run.call_args.args[0], [
            "ssh", "-G", "-o", "HostName=verified.example.ts.net",
            "-p", "2222", "build-alias",
        ])

    def test_missing_or_malformed_ssh_config_probe_is_unknown(self):
        cases = (
            OSError("ssh missing"),
            self.completed("host build-alias\nhostname build-alias\n"),
            self.completed("", "bad option", 255),
        )
        for outcome in cases:
            with self.subTest(outcome=outcome), \
                 mock.patch.object(session_peer.subprocess, "run", side_effect=[outcome]):
                self.assertEqual(session_peer.ssh_user_metadata("build-alias", []), {
                    "sshUser": None, "sshUserSource": "unknown",
                })

    def test_success_reports_the_effective_user(self):
        config = self.completed("user deploy\nhostname build-alias\n")
        remote = self.completed('{"ok": true, "sessions": []}\n')
        with mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
             mock.patch.object(session_peer.subprocess, "run",
                               side_effect=[config, remote]) as run:
            result = session_peer.run_remote("build-alias", ["list"], [])
        self.assertEqual(result["sshUser"], "deploy")
        self.assertEqual(result["sshUserSource"], "ssh_config_or_local_default")
        self.assertEqual(run.call_count, 2)

    def test_connection_failures_are_classified_without_retrying(self):
        cases = (
            (self.completed("", "Permission denied (publickey).", 255),
             "authentication_failed"),
            (self.completed("", "Host key verification failed.", 255),
             "host_key_failed"),
            (subprocess.TimeoutExpired(["ssh"], 120), "timeout"),
            (self.completed("", "connect to host failed: Connection refused", 255),
             "transport_failed"),
        )
        for outcome, expected in cases:
            config = self.completed("user deploy\nhostname build-alias\n")
            with self.subTest(expected=expected), \
                 mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
                 mock.patch.object(session_peer.subprocess, "run",
                                   side_effect=[config, outcome]) as run, \
                 self.assertRaises(session_peer.CcPeerError) as caught:
                session_peer.run_remote("build-alias", ["list"], [])
            self.assertEqual(caught.exception.details["sshFailure"], expected)
            self.assertEqual(caught.exception.details["sshUser"], "deploy")
            self.assertEqual(run.call_count, 2)
            if expected == "authentication_failed":
                self.assertIn("--host USER@HOST", str(caught.exception))

    def test_help_explains_user_precedence(self):
        help_text = session_peer.build_parser()._subparsers._group_actions[0].choices[
            "send"
        ].format_help()
        self.assertIn("[USER@]HOST", help_text)
        self.assertIn("SSH config/default", help_text)


class SshRemoteOutcomes(unittest.TestCase):
    MARKERS = (
        ("permission denied", "authentication_failed", "SSH authentication failed"),
        ("authentication failed", "authentication_failed", "SSH authentication failed"),
        ("no supported authentication methods available", "authentication_failed", "SSH authentication failed"),
        ("too many authentication failures", "authentication_failed", "SSH authentication failed"),
        ("host key verification failed", "host_key_failed", "SSH host-key verification failed"),
        ("remote host identification has changed", "host_key_failed", "SSH host-key verification failed"),
        ("offending key in", "host_key_failed", "SSH host-key verification failed"),
        ("known_hosts", "host_key_failed", "SSH host-key verification failed"),
        ("operation timed out", "timeout", "SSH connection to user@fixture timed out"),
        ("connection timed out", "timeout", "SSH connection to user@fixture timed out"),
        ("connect timeout", "timeout", "SSH connection to user@fixture timed out"),
        ("timed out", "timeout", "SSH connection to user@fixture timed out"),
    )
    SSH_INFO = {"sshUser": "user", "sshUserSource": "explicit"}

    def remote(self, command, stdout, stderr="", returncode=1):
        completed = subprocess.CompletedProcess([], returncode, stdout, stderr)
        with mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
             mock.patch.object(session_peer.subprocess, "run", return_value=completed) as run:
            try:
                return session_peer.run_remote("user@fixture", [command], [])
            finally:
                run.assert_called_once()

    def test_submitted_send_survives_every_stderr_classifier_marker(self):
        payload = {
            "schemaVersion": 1, "command": "send", "ok": False,
            "agent": "codex", "submitted": True, "status": "queued",
            "queueId": "fixture-queue", "wake": {"status": "refused"},
        }
        for marker, _, _ in self.MARKERS:
            for returncode in (1, 255):
                with self.subTest(marker=marker, returncode=returncode):
                    result = self.remote("send", json.dumps(payload),
                                         f"bash: startup: {marker}", returncode)
                    self.assertEqual(result, {**payload, **self.SSH_INFO})

    def test_valid_response_precedes_interpreter_stderr_heuristics(self):
        payload = {"schemaVersion": 1, "command": "send", "ok": False,
                   "submitted": True, "wake": {"status": "unknown"}}
        result = self.remote("send", json.dumps(payload), "python3: command not found")
        self.assertEqual(result, {**payload, **self.SSH_INFO})

    def test_valid_send_refusal_keeps_the_remote_error(self):
        payload = {"schemaVersion": 1, "command": "send", "ok": False,
                   "error": "fixture refusal", "submitted": False}
        with self.assertRaisesRegex(session_peer.CcPeerError, "fixture refusal") as caught:
            self.remote("send", json.dumps(payload), "Permission denied")
        self.assertNotIn("sshFailure", caught.exception.details)

    def test_transport_or_empty_output_keeps_every_classifier_and_message(self):
        for marker, expected, message in self.MARKERS:
            for stdout, returncode in (("", 1), ("", 255), ("not JSON", 255)):
                with self.subTest(marker=marker, stdout=stdout, returncode=returncode), \
                     self.assertRaises(session_peer.CcPeerError) as caught:
                    self.remote("send", stdout, marker, returncode)
                self.assertEqual(caught.exception.details,
                                 {**self.SSH_INFO, "sshFailure": expected})
                self.assertIn(message, str(caught.exception))

    def test_exit_255_without_marker_remains_a_transport_failure(self):
        with self.assertRaisesRegex(session_peer.CcPeerError, "SSH transport failed") as caught:
            self.remote("send", "not JSON", "Connection refused", 255)
        self.assertEqual(caught.exception.details["sshFailure"], "transport_failed")

    def test_nonempty_malformed_output_is_not_classified_from_stderr(self):
        with self.assertRaisesRegex(session_peer.CcPeerError, "unexpected output") as caught:
            self.remote("send", "not JSON", "Permission denied")
        self.assertEqual(caught.exception.details, self.SSH_INFO)

    def test_invalid_envelopes_do_not_establish_a_remote_outcome(self):
        valid = {"schemaVersion": 1, "command": "send", "ok": True,
                 "submitted": True}
        for invalid in ({"schemaVersion": True}, {"schemaVersion": 1.0},
                        {"schemaVersion": 2}, {"ok": "true"}, {"command": "list"},
                        {"command": None}):
            for returncode in (1, 255):
                with self.subTest(invalid=invalid, returncode=returncode), \
                     self.assertRaises(session_peer.CcPeerError) as caught:
                    self.remote("send", json.dumps({**valid, **invalid}),
                                "Permission denied", returncode)
                if returncode == 255:
                    self.assertEqual(caught.exception.details["sshFailure"],
                                     "authentication_failed")
                else:
                    self.assertIn("unexpected output", str(caught.exception))
                    self.assertNotIn("sshFailure", caught.exception.details)

    def test_legacy_json_responses_remain_supported(self):
        payload = {"ok": True, "sessions": []}
        self.assertEqual(self.remote("list", json.dumps(payload), "", 0),
                         {**payload, **self.SSH_INFO})

    def test_antigravity_unknown_result_keeps_retry_and_request_evidence(self):
        payload = {"schemaVersion": 1, "command": "send", "ok": False,
                   "agent": "antigravity", "status": "unknown", "retryAllowed": False,
                   "requestId": "fixture-request", "reason": "outcome_unknown"}
        self.assertEqual(self.remote("send", json.dumps(payload), "Permission denied"),
                         {**payload, **self.SSH_INFO})

    def test_list_partial_discovery_survives_stderr_markers(self):
        payload = {
            "schemaVersion": 1, "command": "list", "ok": False, "sessions": [],
            "discovery": {"claude": {"status": "error", "error": "fixture failure"}},
        }
        self.assertEqual(self.remote("list", json.dumps(payload), "Permission denied"),
                         {**payload, **self.SSH_INFO})

    def test_list_and_doctor_success_and_remote_errors_keep_their_behavior(self):
        for command in ("list", "doctor"):
            for ok in (True, False):
                payload = {"schemaVersion": 1, "command": command, "ok": ok,
                           "error": "fixture remote failure"}
                with self.subTest(command=command, ok=ok):
                    if ok:
                        self.assertEqual(self.remote(command, json.dumps(payload),
                                                     "Permission denied", 0),
                                         {**payload, **self.SSH_INFO})
                    else:
                        with self.assertRaisesRegex(session_peer.CcPeerError,
                                                    "fixture remote failure") as caught:
                            self.remote(command, json.dumps(payload), "Permission denied")
                        self.assertNotIn("sshFailure", caught.exception.details)

    def test_send_timeout_is_unknown_and_not_retryable(self):
        output = io.StringIO()
        with mock.patch.object(session_peer, "tailscale_status", return_value=None), \
             mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
             mock.patch.object(session_peer.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(["ssh"], 120)) as run, \
             contextlib.redirect_stdout(output):
            code = session_peer.main([
                "send", "--host", "user@fixture", "--to", "worker",
                "--no-from", "--no-reply-to", "--no-update-notice", "--json", "hello",
            ])
        self.assertEqual(code, session_peer.EXIT_ERROR)
        run.assert_called_once()
        result = json.loads(output.getvalue())
        self.assertEqual(result["command"], "send")
        self.assertEqual(result["schemaVersion"], 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "outcome_unknown")
        self.assertIs(result["retryAllowed"], False)
        self.assertNotIn("submitted", result)
        self.assertIn("submission outcome unknown", result["error"])
        self.assertIn("Do not automatically retry", result["error"])

    def test_non_send_timeouts_keep_the_transport_timeout_behavior(self):
        for operation in ("list", "doctor", "push", "version"):
            with self.subTest(operation=operation), \
                 mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
                 mock.patch.object(session_peer.Path, "read_bytes", return_value=b"source"), \
                 mock.patch.object(session_peer.subprocess, "run",
                                   side_effect=subprocess.TimeoutExpired(["ssh"], 120)) as run, \
                 self.assertRaises(session_peer.CcPeerError) as caught:
                if operation == "push":
                    session_peer.push_to_remote("user@fixture", [])
                elif operation == "version":
                    session_peer.remote_installed_version("user@fixture", [])
                else:
                    session_peer.run_remote("user@fixture", [operation], [])
            # Update-transfer outcomes (#229) may add commit metadata. Keep the
            # original transport classification and identity contract exact.
            expected = {**self.SSH_INFO, "sshFailure": "timeout"}
            self.assertEqual({key: caught.exception.details[key] for key in expected}, expected)
            self.assertEqual(str(caught.exception), "SSH connection to user@fixture timed out")
            run.assert_called_once()

    def test_update_paths_keep_authentication_failure_behavior(self):
        completed = subprocess.CompletedProcess([], 255, "", "Permission denied")
        for operation in (session_peer.push_to_remote, session_peer.remote_installed_version):
            with self.subTest(operation=operation.__name__), \
                 mock.patch.object(session_peer.Path, "read_bytes", return_value=b"source"), \
                 mock.patch.object(session_peer.subprocess, "run", return_value=completed) as run, \
                 self.assertRaises(session_peer.CcPeerError) as caught:
                operation("user@fixture", [])
            expected = {**self.SSH_INFO, "sshFailure": "authentication_failed"}
            self.assertEqual({key: caught.exception.details[key] for key in expected}, expected)
            self.assertIn("--host USER@HOST", str(caught.exception))
            run.assert_called_once()


class TailscaleDestination(unittest.TestCase):
    ONLINE = {
        "ID": "peer-online",
        "HostName": "macbook-pro-m4-pro",
        "DNSName": "macbook-pro-m4-pro.tailnet.ts.net.",
        "TailscaleIPs": ["100.122.73.69", "fd7a:115c:a1e0::1"],
        "Online": True,
    }
    OFFLINE = {
        "ID": "peer-offline",
        "HostName": "old-macbook",
        "DNSName": "old-macbook.tailnet.ts.net.",
        "TailscaleIPs": ["100.96.246.30"],
        "Online": False,
    }

    def status(self, *peers):
        return {
            "BackendState": "Running",
            "CurrentTailnet": {"MagicDNSEnabled": True},
            "Self": {
                "ID": "self", "HostName": "mac-mini-m4",
                "DNSName": "mac-mini-m4.tailnet.ts.net.",
                "TailscaleIPs": ["100.93.90.11"], "Online": True,
            },
            "Peer": {peer["ID"]: peer for peer in peers},
        }

    def test_status_reads_running_json_despite_cli_warning(self):
        expected = self.status(self.ONLINE)
        completed = subprocess.CompletedProcess(
            [], 0, json.dumps(expected), "client/server version mismatch"
        )
        with mock.patch.object(session_peer.subprocess, "run", return_value=completed) as run:
            self.assertEqual(session_peer.tailscale_status(), expected)
        self.assertEqual(run.call_args.args[0], ["tailscale", "status", "--json"])

    def test_reply_host_prefers_self_magicdns(self):
        with mock.patch.object(session_peer, "tailscale_status", return_value=self.status(self.ONLINE)):
            self.assertEqual(session_peer.detect_reply_host(), "mac-mini-m4.tailnet.ts.net")

    def test_hostname_short_name_ip_and_username_resolve_to_magicdns(self):
        status = self.status(self.ONLINE)
        expected = "macbook-pro-m4-pro.tailnet.ts.net"
        for destination in (
            "macbook-pro-m4-pro", expected, expected + ".", "100.122.73.69"
        ):
            with self.subTest(destination=destination):
                self.assertEqual(session_peer.resolve_ssh_destination(destination, status), expected)
        self.assertEqual(
            session_peer.resolve_ssh_destination("alice@100.122.73.69", status),
            "alice@" + expected,
        )

    def test_known_offline_peer_fails_before_ssh(self):
        status = self.status(self.OFFLINE)
        with self.assertRaisesRegex(session_peer.CcPeerError, "offline"):
            session_peer.resolve_ssh_destination("old-macbook", status)

        output = io.StringIO()
        with mock.patch.object(session_peer, "tailscale_status", return_value=status), \
             mock.patch.object(session_peer, "run_remote") as remote, \
             contextlib.redirect_stdout(output):
            code = session_peer.main([
                "send", "--host", "old-macbook", "--to", "worker",
                "--no-from", "--no-reply-to", "--json", "hello",
            ])
        self.assertEqual(code, session_peer.EXIT_ERROR)
        self.assertIn("offline", json.loads(output.getvalue())["error"])
        remote.assert_not_called()

    def test_unknown_and_magicdns_disabled_destinations_remain_generic_ssh(self):
        status = self.status(self.ONLINE)
        self.assertEqual(session_peer.resolve_ssh_destination("build-alias", status), "build-alias")
        status["CurrentTailnet"]["MagicDNSEnabled"] = False
        self.assertEqual(
            session_peer.resolve_ssh_destination("100.122.73.69", status),
            "100.122.73.69",
        )

    def test_ambiguous_short_name_requires_full_magicdns(self):
        duplicate = {
            **self.ONLINE,
            "ID": "peer-duplicate",
            "DNSName": "macbook-pro-m4-pro.other.ts.net.",
            "TailscaleIPs": ["100.100.100.100"],
        }
        with self.assertRaisesRegex(session_peer.CcPeerError, "ambiguous"):
            session_peer.resolve_ssh_destination(
                "macbook-pro-m4-pro", self.status(self.ONLINE, duplicate)
            )

    def test_remote_send_uses_and_reports_canonical_destination(self):
        response = {"ok": True, "target": {"pid": 1, "name": "worker"}}
        output = io.StringIO()
        with mock.patch.object(session_peer, "tailscale_status", return_value=self.status(self.ONLINE)), \
             mock.patch.object(session_peer, "run_remote", return_value=response) as remote, \
             contextlib.redirect_stdout(output):
            code = session_peer.main([
                "send", "--host", "alice@100.122.73.69", "--to", "worker",
                "--no-from", "--no-reply-to", "--json", "hello",
            ])
        self.assertEqual(code, 0)
        expected = "alice@macbook-pro-m4-pro.tailnet.ts.net"
        self.assertEqual(remote.call_args.args[0], "alice@100.122.73.69")
        self.assertEqual(remote.call_args.args[1][:4], [
            "send", "--no-update-notice", "--to", "worker",
        ])
        self.assertEqual(remote.call_args.args[2], [
            "-o", "HostName=macbook-pro-m4-pro.tailnet.ts.net",
            "-o", "HostKeyAlias=100.122.73.69",
        ])
        result = json.loads(output.getvalue())
        self.assertEqual(result["host"], expected)
        self.assertEqual(result["sshHost"], "alice@100.122.73.69")

    def test_remote_list_and_update_check_use_the_same_verified_identity(self):
        expected = "macbook-pro-m4-pro.tailnet.ts.net"
        with mock.patch.object(session_peer, "tailscale_status", return_value=self.status(self.ONLINE)), \
             mock.patch.object(session_peer, "run_remote", return_value={"sessions": []}) as remote, \
             mock.patch.object(session_peer, "remote_installed_version", return_value="0.6.0") as version:
            for command in (["list"], ["update", "--check"]):
                with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()) as output:
                    code = session_peer.main([*command, "--host", "100.122.73.69", "--json"])
                self.assertEqual(code, 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result["host"], expected)
                self.assertEqual(result["sshHost"], "100.122.73.69")
                self.assertTrue(result["ok"])
                self.assertEqual(result["command"], command[0])
                self.assertEqual(result["schemaVersion"], 1)
        route = [
            "-o", "HostName=macbook-pro-m4-pro.tailnet.ts.net",
            "-o", "HostKeyAlias=100.122.73.69",
        ]
        remote.assert_called_once_with(
            "100.122.73.69", ["list", "--no-update-notice"], route
        )
        self.assertEqual([call.args[0] for call in version.call_args_list],
                         ["100.122.73.69", "100.122.73.69"])
        self.assertEqual([call.args[1] for call in version.call_args_list], [route, route])

    def test_magicdns_route_keeps_user_options_after_verified_overrides(self):
        self.assertEqual(
            session_peer.tailscale_ssh_options(
                "alice@100.122.73.69", "alice@macbook-pro-m4-pro.tailnet.ts.net"
            ) + ["-p", "2222"],
            [
                "-o", "HostName=macbook-pro-m4-pro.tailnet.ts.net",
                "-o", "HostKeyAlias=100.122.73.69", "-p", "2222",
            ],
        )
        self.assertEqual(session_peer.tailscale_ssh_options("build-alias", "build-alias"), [])
