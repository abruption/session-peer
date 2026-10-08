"""Core session-peer contract tests; standard-library only and offline."""

import argparse
import base64
import contextlib
import io
import json
import os
import shlex
import subprocess
import sys
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
        session_peer.check_ssh_options(["-p", "2222", "-oConnectTimeout=8", "-oProxyJump=bastion"])

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
    UNKNOWN = {"status": "unknown", "reason": "outcome_unknown", "retryAllowed": False}

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
            for returncode in (0, 1, 137, 255):
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
                   "error": "fixture refusal", "submitted": False,
                   "status": "refused", "reason": "fixture_refusal", "retryAllowed": False}
        with self.assertRaisesRegex(session_peer.CcPeerError, "fixture refusal") as caught:
            self.remote("send", json.dumps(payload), "Permission denied")
        self.assertNotIn("sshFailure", caught.exception.details)
        for key in ("submitted", "status", "reason", "retryAllowed"):
            self.assertEqual(caught.exception.details[key], payload[key])

    def test_transport_or_empty_output_keeps_every_classifier_and_message(self):
        for marker, expected, message in self.MARKERS:
            for stdout, returncode in (("", 1), ("", 255), ("not JSON", 255)):
                with self.subTest(marker=marker, stdout=stdout, returncode=returncode), \
                     self.assertRaises(session_peer.CcPeerError) as caught:
                    self.remote("send", stdout, marker, returncode)
                self.assertEqual(caught.exception.details,
                                 {**self.SSH_INFO, **self.UNKNOWN, "sshFailure": expected})
                self.assertIn(message, str(caught.exception))

    def test_exit_255_without_marker_remains_a_transport_failure(self):
        with self.assertRaisesRegex(session_peer.CcPeerError, "SSH transport failed") as caught:
            self.remote("send", "not JSON", "Connection refused", 255)
        self.assertEqual(caught.exception.details["sshFailure"], "transport_failed")

    def test_nonempty_malformed_output_is_not_classified_from_stderr(self):
        with self.assertRaisesRegex(session_peer.CcPeerError, "unexpected output") as caught:
            self.remote("send", "not JSON", "Permission denied")
        self.assertEqual(caught.exception.details, {**self.SSH_INFO, **self.UNKNOWN})

    def test_abnormal_or_incomplete_sends_are_unknown_without_submission_claims(self):
        valid = '{"schemaVersion":1,"command":"send","ok":true,"submitted":true}'
        incomplete = ("", valid[:-1], valid + " trailing", valid + "\n{}",
                      b'\xff' + valid.encode(), "[]", "null", "true",
                      valid.replace('"ok":true', '"ok":false,"ok":true'),
                      valid.replace('"submitted":true', '"submitted":NaN'),
                      "\v" + valid + "\v")
        for code in (0, 1, 137, 255, -9):
            for stdout in incomplete:
                with self.subTest(code=code, stdout=stdout), \
                     self.assertRaises(session_peer.CcPeerError) as caught:
                    self.remote("send", stdout, b'\xff Permission denied fixture', code)
                details = caught.exception.details
                self.assertEqual({key: details[key] for key in self.UNKNOWN}, self.UNKNOWN)
                self.assertNotIn("submitted", details)
                self.assertNotIn("consumptionConfirmed", details)
                self.assertIn("Do not automatically retry", str(caught.exception))

    def test_pre_spawn_failures_do_not_claim_unknown_submission(self):
        for error in (FileNotFoundError("fixture ssh missing"), PermissionError("fixture denied")):
            with self.subTest(error=type(error).__name__), \
                 mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
                 mock.patch.object(session_peer.subprocess, "run", side_effect=error) as run, \
                 self.assertRaises(session_peer.CcPeerError) as caught:
                session_peer.run_remote("user@fixture", ["send"], [])
            self.assertNotIn("status", caught.exception.details)
            self.assertNotIn("retryAllowed", caught.exception.details)
            run.assert_called_once()

    def test_complete_refusal_survives_shutdown_timeout_and_invalid_diagnostics(self):
        payload = {"schemaVersion": 1, "command": "send", "ok": False,
                   "host": "local", "error": "fixture refusal", "status": "refused",
                   "reason": "preflight_refused", "submitted": False,
                   "wake": {"status": "refused", "reason": "writer_unknown"}}
        with mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
             mock.patch.object(session_peer.subprocess, "run", side_effect=
                 subprocess.TimeoutExpired(["ssh"], 120, output=json.dumps(payload).encode(),
                                           stderr=b'\xffPermission denied')) as run:
            result = session_peer.run_remote("user@fixture", ["send"], [])
        self.assertEqual(result, {**payload, **self.SSH_INFO})
        run.assert_called_once()

    def test_complete_codex_timeout_error_keeps_remote_unknown_fields(self):
        payload = {"schemaVersion": 1, "command": "send", "ok": False,
                   "error": "Codex queue timed out", **self.UNKNOWN}
        with self.assertRaises(session_peer.CcPeerError) as caught:
            self.remote("send", json.dumps(payload), b'\xffPermission denied', 255)
        self.assertEqual(caught.exception.details, {**self.SSH_INFO, **self.UNKNOWN})
        self.assertNotIn("submitted", caught.exception.details)

    def test_complete_refusal_facts_match_every_exit_and_timeout(self):
        payload = {"schemaVersion": 1, "command": "send", "ok": False,
                   "host": "local", "error": "fixture refusal", "status": "refused",
                   "reason": "preflight_refused", "submitted": False, "retryAllowed": False}
        frame = json.dumps(payload).encode()
        outcomes = [subprocess.CompletedProcess([], code, frame, b'\xffPermission denied')
                    for code in (0, 1, 137, 255)]
        outcomes.append(subprocess.TimeoutExpired(["ssh"], 120, output=frame,
                                                stderr=b'\xffPermission denied'))
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__, code=getattr(outcome, "returncode", None)), \
                 mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
                 mock.patch.object(session_peer.subprocess, "run", side_effect=[outcome]) as run, \
                 self.assertRaisesRegex(session_peer.CcPeerError, "fixture refusal") as caught:
                session_peer.run_remote("user@fixture", ["send"], [])
            expected = {key: value for key, value in payload.items()
                        if key not in ("schemaVersion", "command", "ok", "host", "error")}
            self.assertEqual(caught.exception.details, {**expected, **self.SSH_INFO})
            run.assert_called_once()

    def test_multi_host_cli_retains_independent_success_refusal_and_unknown(self):
        success = {"schemaVersion": 1, "command": "send", "ok": True,
                   "target": {"name": "worker"}, "chars": 5, "dryRun": False}
        refusal = {"schemaVersion": 1, "command": "send", "ok": False,
                   "host": "local", "error": "fixture refusal", "status": "refused",
                   "reason": "fixture_refusal", "submitted": False}
        outcomes = [subprocess.CompletedProcess([], 255, b"", b"Permission denied"),
                    subprocess.CompletedProcess([], 255, json.dumps(success).encode(), b'\xff'),
                    subprocess.CompletedProcess([], 137, json.dumps(refusal).encode(), b'\xff')]
        output = io.StringIO()
        with mock.patch.object(session_peer, "tailscale_status", return_value=None), \
             mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
             mock.patch.object(session_peer.subprocess, "run", side_effect=outcomes) as run, \
             contextlib.redirect_stdout(output):
            code = session_peer.main(["send", "--host", "user@unknown", "--host", "user@success",
                                      "--host", "user@refusal", "--to", "worker", "hello",
                                      "--no-from", "--no-reply-to", "--no-update-notice", "--json"])
        results = json.loads(output.getvalue())
        self.assertEqual(code, session_peer.EXIT_ERROR)
        self.assertEqual(run.call_count, 3)
        self.assertEqual([result["host"] for result in results],
                         ["user@unknown", "user@success", "user@refusal"])
        self.assertEqual({key: results[0][key] for key in self.UNKNOWN}, self.UNKNOWN)
        self.assertTrue(results[1]["ok"])
        for key in ("status", "submitted", "consumptionConfirmed", "retryAllowed"):
            self.assertNotIn(key, results[1])
        self.assertFalse(results[2]["ok"])
        self.assertEqual(results[2]["status"], "refused")
        self.assertIs(results[2]["submitted"], False)
        self.assertNotIn("sshFailure", results[2])

    def test_single_host_unknown_send_keeps_json_and_error_exit_contract(self):
        for code, frame in ((255, b""), (137, b""), (0, b'{"schemaVersion":1')):
            completed = subprocess.CompletedProcess([], code, frame, b'\xff diagnostic')
            output = io.StringIO()
            with self.subTest(code=code), \
                 mock.patch.object(session_peer, "tailscale_status", return_value=None), \
                 mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
                 mock.patch.object(session_peer.subprocess, "run", return_value=completed) as run, \
                 contextlib.redirect_stdout(output):
                exit_code = session_peer.main(["send", "--host", "user@fixture", "--to", "worker",
                                               "hello", "--no-from", "--no-reply-to",
                                               "--no-update-notice", "--json"])
            result = json.loads(output.getvalue())
            self.assertEqual(exit_code, session_peer.EXIT_ERROR)
            self.assertEqual({key: result[key] for key in self.UNKNOWN}, self.UNKNOWN)
            self.assertEqual(result["schemaVersion"], 1)
            self.assertEqual(result["command"], "send")
            self.assertFalse(result["ok"])
            self.assertNotIn("submitted", result)
            run.assert_called_once()

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

    def legacy_send_cli(self, outcome):
        output = io.StringIO()
        with mock.patch.object(session_peer, "tailscale_status", return_value={}), \
             mock.patch.object(session_peer.Path, "read_text", return_value="fixture source"), \
             mock.patch.object(session_peer.subprocess, "run", side_effect=[outcome]) as run, \
             contextlib.redirect_stdout(output):
            code = session_peer.main(["send", "--host", "user@fixture", "--to", "worker", "hello",
                                      "--no-from", "--no-reply-to", "--no-update-notice", "--json"])
        run.assert_called_once()
        return code, json.loads(output.getvalue())

    def test_malformed_legacy_send_objects_are_unknown_through_public_cli(self):
        payloads = ({}, {"submitted": True}, {"ok": "false"}, {"command": "send"},
                    {"ok": True, "command": "list"}, {"ok": False, "command": None},
                    {"ok": 1}, {"ok": 0})
        for payload in payloads:
            for returncode in (0, 1, 2):
                with self.subTest(payload=payload, returncode=returncode):
                    code, result = self.legacy_send_cli(subprocess.CompletedProcess(
                        [], returncode, json.dumps(payload).encode(), b'\xff diagnostic'))
                    self.assertEqual(code, session_peer.EXIT_ERROR)
                    self.assertFalse(result["ok"])
                    self.assertEqual({key: result[key] for key in self.UNKNOWN}, self.UNKNOWN)
                    self.assertNotIn("submitted", result)
                    self.assertNotIn("consumptionConfirmed", result)

    def test_legacy_boolean_send_outcomes_preserve_ordinary_exit_compatibility(self):
        for ok in (True, False):
            for has_command in (True, False):
                payload = {"ok": ok, "target": {"pid": 7, "name": "worker"}}
                if has_command:
                    payload["command"] = "send"
                if not ok:
                    payload["error"] = "fixture legacy refusal"
                for returncode in (0, 1, 2):
                    with self.subTest(ok=ok, command=has_command, returncode=returncode):
                        code, result = self.legacy_send_cli(subprocess.CompletedProcess(
                            [], returncode, json.dumps(payload).encode(),
                            b'\xffpython3: command not found; Permission denied'))
                        self.assertEqual(code, 0 if ok else session_peer.EXIT_ERROR)
                        self.assertEqual(result["ok"], ok)
                        self.assertEqual(result["host"], "user@fixture")
                        self.assertEqual(result["command"], "send")
                        if ok:
                            self.assertEqual(result["target"], payload["target"])
                        else:
                            self.assertIn(payload["error"], result["error"])
                        for field in ("status", "reason", "retryAllowed", "submitted", "consumptionConfirmed"):
                            self.assertNotIn(field, result)

    def test_legacy_send_response_on_abnormal_exit_remains_unknown(self):
        for ok in (True, False):
            payload = {"ok": ok, "command": "send", "target": {"pid": 7},
                       "error": "fixture legacy refusal"}
            for returncode in (137, 255, -9):
                with self.subTest(ok=ok, returncode=returncode):
                    code, result = self.legacy_send_cli(subprocess.CompletedProcess(
                        [], returncode, json.dumps(payload).encode(), b'\xff diagnostic'))
                    self.assertEqual(code, session_peer.EXIT_ERROR)
                    self.assertFalse(result["ok"])
                    self.assertEqual({key: result[key] for key in self.UNKNOWN}, self.UNKNOWN)
                    self.assertNotIn("submitted", result)

    def test_legacy_send_response_on_shutdown_timeout_remains_unknown(self):
        for ok in (True, False):
            with self.subTest(ok=ok):
                code, result = self.legacy_send_cli(subprocess.TimeoutExpired(
                    ["ssh"], 120, output=json.dumps({"ok": ok}).encode(), stderr=b'\xff diagnostic'))
                self.assertEqual(code, session_peer.EXIT_ERROR)
                self.assertEqual({key: result[key] for key in self.UNKNOWN}, self.UNKNOWN)
                self.assertNotIn("submitted", result)

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

    def test_complete_timeout_outcomes_match_normal_exit_for_text_and_utf8_bytes(self):
        for payload in (
            {"schemaVersion": 1, "command": "send", "ok": True, "submitted": True,
             "agent": "codex", "queueId": "fixture-한국어"},
            {"schemaVersion": 1, "command": "send", "ok": False, "submitted": True,
             "wake": {"status": "unknown"}},
            {"schemaVersion": 1, "command": "list", "ok": True, "sessions": []},
            {"schemaVersion": 1, "command": "doctor", "ok": True, "status": "ok"},
        ):
            text = json.dumps(payload, ensure_ascii=False) + "\n"
            for captured in (text, text.encode("utf-8")):
                with self.subTest(payload=payload, bytes=isinstance(captured, bytes)), \
                     mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
                     mock.patch.object(session_peer.subprocess, "run", side_effect=
                         subprocess.TimeoutExpired(["ssh"], 120, output=captured,
                                                   stderr=b"\xffPermission denied")) as run:
                    result = session_peer.run_remote("user@fixture", [payload["command"]], [])
                    self.assertEqual(result, {**payload, **self.SSH_INFO})
                    run.assert_called_once()

    def test_complete_timeout_response_preserved_through_send_cli(self):
        thread = "01900000-0000-7000-8000-000000000001"
        payload = {"schemaVersion": 1, "command": "send", "ok": True,
                   "agent": "codex", "target": {"id": thread},
                   "queueId": "fixture-queue", "submitted": True}
        output = io.StringIO()
        with mock.patch.object(session_peer, "tailscale_status", return_value=None), \
             mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
             mock.patch.object(session_peer.subprocess, "run", side_effect=
                 subprocess.TimeoutExpired(["ssh"], 120, output=json.dumps(payload).encode())) as run, \
             contextlib.redirect_stdout(output):
            code = session_peer.main(["send", "--host", "user@fixture", "--to", "codex:" + thread,
                                      "--no-from", "--no-reply-to", "--no-update-notice",
                                      "--json", "hello"])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["submitted"])
        self.assertEqual(result["queueId"], "fixture-queue")
        self.assertNotIn("sshFailure", result)
        run.assert_called_once()

    def test_invalid_timeout_responses_remain_unknown_without_retry(self):
        valid = '{"schemaVersion":1,"command":"send","ok":true,"submitted":true}'
        for captured in (
            None, "", valid[:-1], valid + " trailing", (valid + "\n{}").encode(),
            b'\xff' + valid.encode(), valid.replace('"ok":true', '"ok":"true"'),
            valid.replace('"schemaVersion":1', '"schemaVersion":true'),
            valid.replace('"command":"send"', '"command":"list"'),
            valid.replace('"ok":true', '"ok":false,"ok":true'),
            valid.replace('"submitted":true', '"submitted":NaN'),
            '{"ok":true,"submitted":true}',
            b'\x1c' + valid.encode() + b'\x1c', '\v' + valid + '\v',
            '\u0085' + valid + '\u0085', '\u2003' + valid + '\u2003',
        ):
            with self.subTest(captured=captured), \
                 mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
                 mock.patch.object(session_peer.subprocess, "run", side_effect=
                     subprocess.TimeoutExpired(["ssh"], 120, output=captured)) as run, \
                 self.assertRaises(session_peer.CcPeerError) as caught:
                session_peer.run_remote("user@fixture", ["send"], [])
            self.assertEqual(caught.exception.details["status"], "unknown")
            self.assertFalse(caught.exception.details["retryAllowed"])
            self.assertNotIn("submitted", caught.exception.details)
            run.assert_called_once()

    def test_timeout_decoder_failure_preserves_unknown_without_retry(self):
        # JSON's C decoder depth limit varies by interpreter; inject its failure
        # rather than assuming Python's recursionlimit defines that boundary.
        with mock.patch.object(session_peer.Path, "read_text", return_value="fixture source"), \
             mock.patch.object(session_peer.subprocess, "run", side_effect=
                 subprocess.TimeoutExpired(["ssh"], 120, output=b'{"unused":[]}')) as run, \
             mock.patch.object(session_peer.json, "loads", side_effect=RecursionError), \
             self.assertRaises(session_peer.CcPeerError) as caught:
            session_peer.run_remote("user@fixture", ["send"], [])
        self.assertEqual(caught.exception.details["status"], "unknown")
        self.assertFalse(caught.exception.details["retryAllowed"])
        self.assertNotIn("submitted", caught.exception.details)
        run.assert_called_once()

    def test_duplicate_keys_and_non_json_constants_rejected_in_normal_path(self):
        for body in (
            '{"schemaVersion":1,"command":"send","ok":false,"ok":true}',
            '{"schemaVersion":1,"command":"send","ok":true,"value":NaN}',
        ):
            with self.subTest(body=body), self.assertRaisesRegex(session_peer.CcPeerError, "unexpected output"):
                self.remote("send", body, "", 0)

    def test_real_process_non_utf8_stderr_cannot_destroy_complete_stdout(self):
        payload = {"schemaVersion": 1, "command": "send", "ok": True,
                   "agent": "codex", "queueId": "fixture-한국어", "submitted": True}
        frame = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        real_run = subprocess.run
        script = (
            "import os, sys\n"
            "sys.stdin.buffer.read()\n"
            "sys.stdout.buffer.write(bytes.fromhex(os.environ['FIXTURE_STDOUT_HEX']))\n"
            "sys.stdout.buffer.flush()\n"
            "sys.stderr.buffer.write(b'\\xff\\xfePermission denied fixture\\n')\n"
            "sys.stderr.buffer.flush()\n"
            "raise SystemExit(int(os.environ['FIXTURE_EXIT']))\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            for code in (0, 255):
                env = {"HOME": temporary, "PATH": os.defpath,
                       "FIXTURE_STDOUT_HEX": frame.hex(), "FIXTURE_EXIT": str(code)}
                if "SYSTEMROOT" in os.environ:
                    env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
                # Reproduce the exact pre-parser failure of the former text
                # capture independently, without ever contacting an SSH host.
                # Windows communicates through reader threads: decode failure
                # is sent to excepthook and leaves stderr unavailable, rather
                # than propagating through run(). Capture and assert the exact
                # failure instead of assuming POSIX exception delivery.
                reader_errors = []
                with self.subTest(code=code), \
                     mock.patch("threading.excepthook",
                                side_effect=lambda failure: reader_errors.append(failure.exc_type)):
                    try:
                        old = real_run([sys.executable, "-c", script], input="fixture",
                                       encoding="utf-8", capture_output=True, timeout=5, env=env)
                    except UnicodeDecodeError:
                        self.assertEqual(reader_errors, [])
                    else:
                        self.assertEqual(reader_errors, [UnicodeDecodeError])
                        self.assertIsNone(old.stderr)

                def fake_ssh(command, **options):
                    self.assertEqual(command[0], "ssh")
                    self.assertIsInstance(options["input"], bytes)
                    self.assertNotIn("encoding", options)
                    self.assertNotIn("text", options)
                    return real_run([sys.executable, "-c", script], env=env,
                                    **{**options, "timeout": 5})

                with self.subTest(code=code), \
                     mock.patch.object(session_peer.Path, "read_text", return_value="fixture source"), \
                     mock.patch.object(session_peer.subprocess, "run", side_effect=fake_ssh) as run:
                    result = session_peer.run_remote("user@fixture", ["send"], [])
                self.assertEqual(result, {**payload, **self.SSH_INFO})
                run.assert_called_once()

    def test_real_process_invalid_stdout_is_not_repaired_for_protocol_acceptance(self):
        real_run = subprocess.run
        script = (
            "import sys\n"
            "sys.stdin.buffer.read()\n"
            "sys.stdout.buffer.write(b'\\xff{\\\"schemaVersion\\\":1,\\\"command\\\":\\\"send\\\",\\\"ok\\\":true}')\n"
            "sys.stderr.buffer.write(b'\\xfe diagnostic')\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            env = {"HOME": temporary, "PATH": os.defpath}
            if "SYSTEMROOT" in os.environ:
                env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]

            def fake_ssh(command, **options):
                return real_run([sys.executable, "-c", script], env=env,
                                **{**options, "timeout": 5})

            with mock.patch.object(session_peer.Path, "read_text", return_value="fixture source"), \
                 mock.patch.object(session_peer.subprocess, "run", side_effect=fake_ssh) as run, \
                 self.assertRaises(session_peer.CcPeerError) as caught:
                session_peer.run_remote("user@fixture", ["send"], [])
            self.assertNotIn("submitted", caught.exception.details)
            self.assertIn("\ufffd diagnostic", str(caught.exception))
            run.assert_called_once()

    def test_real_fake_ssh_process_empty_and_truncated_outcomes_are_unknown(self):
        real_run = subprocess.run
        script = (
            "import sys\n"
            "sys.stdin.buffer.read()\n"
            "sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))\n"
            "sys.stderr.buffer.write(b'\\xffpython3: command not found; Permission denied')\n"
            "raise SystemExit(int(sys.argv[2]))\n"
        )
        for frame in (b"", b'{"schemaVersion":1,"command":"send","ok":true'):
            for code in (0, 137, 255):
                def fake_ssh(command, **options):
                    self.assertEqual(command[0], "ssh")
                    return real_run([sys.executable, "-c", script, frame.hex(), str(code)],
                                    **{**options, "timeout": 5})

                with self.subTest(frame=frame, code=code), \
                     mock.patch.object(session_peer.Path, "read_text", return_value="fixture source"), \
                     mock.patch.object(session_peer.subprocess, "run", side_effect=fake_ssh) as run, \
                     self.assertRaises(session_peer.CcPeerError) as caught:
                    session_peer.run_remote("user@fixture", ["send"], [])
                details = caught.exception.details
                self.assertEqual({key: details[key] for key in self.UNKNOWN}, self.UNKNOWN)
                self.assertNotIn("submitted", details)
                run.assert_called_once()

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
