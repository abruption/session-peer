"""Offline display-only previews preserve ordinary submission contracts."""
import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import session_peer as peer


THREAD = "01900000-0000-7000-8000-000000000001"
BODY = "PRIVATE-BODY-MUST-NOT-BE-DISPLAYED"


class DeliveryExplanation(unittest.TestCase):
    def invoke(self, *flags, target="worker"):
        out, err = io.StringIO(), io.StringIO()
        argv = ["send", "--to", target, "--no-from", "--no-reply-to",
                "--message", BODY, *flags]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = peer.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_invalid_combinations_fail_before_updates_input_or_dispatch(self):
        variants = [[], ["--dry-run", "--json"],
                    ["--dry-run", "--output-format", "json"],
                    ["--dry-run", "--device", "fixture"],
                    ["--dry-run", "--correlation-id", "00000000-0000-4000-8000-000000000001"],
                    ["--dry-run", "--request-ack"],
                    ["--dry-run", "--observe-delivery"],
                    ["--dry-run", "--wait-for", "acknowledged"],
                    ["--dry-run", "--_handoff-native-context", "private"],
                    ["--dry-run", "--_handoff-native-cutoff-ms", "1"],
                    ["--dry-run", "--_handoff-native-total-ms", "1"]]
        for flags in variants:
            diagnostic = io.StringIO()
            with self.subTest(flags=flags), \
                    mock.patch.object(peer, "prepare_client_update") as updates, \
                    mock.patch.object(peer, "prepare_skill_updates") as skills, \
                    mock.patch.object(peer, "read_message") as read, \
                    mock.patch.object(peer, "cmd_send") as send, \
                    mock.patch.object(peer.subprocess, "Popen") as child, \
                    mock.patch.object(sys, "argv", ["session-peer", "send", "--to", "worker",
                                                      "--explain", *flags]), \
                    contextlib.redirect_stderr(diagnostic), self.assertRaises(SystemExit) as exc:
                peer.main()
            self.assertEqual(exc.exception.code, 2)
            expected = ("--explain requires --dry-run" if not flags else
                        "--explain requires text output" if "--json" in flags or "--output-format" in flags else
                        "--explain does not support paired-device sends" if "--device" in flags else
                        "--explain does not support experimental handoff sends")
            self.assertIn("session-peer: error: " + expected, diagnostic.getvalue())
            for action in (updates, skills, read, send, child):
                action.assert_not_called()

    def test_claude_preview_reuses_dry_run_without_native_post_or_extra_discovery(self):
        session = {"pid": 42, "name": "worker", "alive": True,
                   "reachable": True, "socket": "/fixture.sock"}
        outputs = []
        for extra in ([], ["--explain"]):
            with mock.patch.object(peer, "discover", return_value=[session]) as discover, \
                    mock.patch.object(peer, "post_to_socket") as post, \
                    mock.patch.object(peer.subprocess, "run") as run:
                code, out, err = self.invoke("--dry-run", *extra)
            self.assertEqual(code, 0)
            self.assertEqual(err, "")
            discover.assert_called_once_with(include_unreachable=True)
            post.assert_not_called()
            run.assert_not_called()
            outputs.append(out)
        self.assertTrue(outputs[1].startswith(outputs[0]))
        self.assertIn("Resolved target: Claude PID 42 (worker)", outputs[1])
        self.assertIn("Wake: not requested; eligibility not checked", outputs[1])
        self.assertNotIn(BODY, outputs[1])

    def test_existing_json_and_absent_claude_fields_are_unchanged(self):
        payload = {"ok": True, "target": {"pid": 42, "name": None},
                   "chars": 99, "dryRun": True}
        before = json.dumps(payload, sort_keys=True)
        with mock.patch.object(peer.LocalTransport, "execute", return_value=payload) as execute:
            code, out, _ = self.invoke("--dry-run", "--json")
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result, {"schemaVersion": 1, "ok": True, "host": peer.local_host(),
                                  "command": "send", "target": {"pid": 42, "name": None},
                                  "chars": 99, "dryRun": True})
        self.assertEqual(json.dumps(payload, sort_keys=True), before)
        self.assertNotIn("submitted", result)
        self.assertNotIn("status", result)
        execute.assert_called_once()

    def test_codex_reported_home_and_wake_use_only_native_result(self):
        for wake, fact, expected in (
                (False, None, "not requested; eligibility not checked"),
                (True, {"status": "validated", "cwd": "/hidden-cwd"},
                 "preflight passed for this dry run; no turn started"),
                (True, None, "requested; preflight not confirmed")):
            with self.subTest(wake=wake, fact=fact):
                payload = {"ok": True, "target": {"agent": "codex", "id": THREAD},
                           "chars": 12, "dryRun": True, "status": "validated", "submitted": False,
                           "consumptionConfirmed": False, "codexHome": "/receiver/codex"}
                if fact is not None:
                    payload["wake"] = fact
                with mock.patch.object(peer, "queue_codex", return_value=payload) as queue:
                    code, out, _ = self.invoke("--dry-run", "--explain",
                                               *(["--wake"] if wake else []), target="codex:" + THREAD)
                self.assertEqual(code, 0)
                queue.assert_called_once()
                self.assertIn("Codex home: /receiver/codex", out)
                self.assertIn("Wake: " + expected, out)
                self.assertNotIn("/hidden-cwd", out)

    def test_antigravity_dry_run_needs_no_target_or_dry_run_fields(self):
        payload = {"ok": True, "status": "dry_run", "submitted": False,
                   "consumptionConfirmed": False, "generation": "not-for-display",
                   "antigravityHome": "/receiver/agy"}
        with mock.patch.object(peer.AntigravityAdapter, "submit", return_value=payload) as submit:
            code, out, _ = self.invoke("--dry-run", "--explain", target="antigravity:" + THREAD)
        self.assertEqual(code, 0)
        submit.assert_called_once()
        self.assertIn("registered Antigravity bridge", out)
        self.assertIn("Antigravity home: /receiver/agy", out)
        self.assertNotIn("not-for-display", out)

    def test_remote_preview_is_sender_only_and_does_not_guess_remote_home(self):
        payload = {"ok": True, "target": {"agent": "codex", "id": THREAD},
                   "chars": 12, "dryRun": True, "status": "validated", "submitted": False,
                   "consumptionConfirmed": False}
        with mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "SshTransport") as transport:
            transport.return_value.host = "receiver"
            transport.return_value.ssh_opts = []
            transport.return_value.execute.return_value = payload
            code, out, _ = self.invoke("--host", "receiver", "--dry-run", "--explain",
                                      "--codex-home", "/requested/home", target="codex:" + THREAD)
        self.assertEqual(code, 0)
        transport.assert_called_once()
        transport.return_value.execute.assert_called_once()
        argv = transport.return_value.execute.call_args.args[0]
        self.assertNotIn("--explain", argv)
        self.assertIn("--dry-run", argv)
        self.assertIn("/requested/home", argv)
        self.assertIn("Codex home: unknown (not reported)", out)
        self.assertNotIn("Codex home: /requested/home", out)

    def test_multiple_hosts_keep_partial_failure_attribution_and_streams(self):
        good = mock.Mock(host="first", ssh_opts=[])
        good.execute.return_value = {"target": {"pid": 42, "name": "worker"},
                                     "chars": 12, "dryRun": True}
        bad = mock.Mock(host="second", ssh_opts=[])
        bad.execute.side_effect = peer.CcPeerError("fixture diagnostic", {
            "status": "unknown", "submitted": None, "retryAllowed": False,
            "error": BODY, "receipt": BODY})
        with mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "SshTransport", side_effect=[good, bad]):
            code, out, err = self.invoke("--host", "first", "--host", "second",
                                        "--dry-run", "--explain")
        self.assertEqual(code, peer.EXIT_ERROR)
        self.assertIn("on first", out)
        self.assertNotIn("on second", out)
        self.assertIn("on second", err)
        self.assertIn("session-peer: second: fixture diagnostic", err)
        self.assertIn("Do not automatically resend after an unknown outcome.", err)
        self.assertNotIn(BODY, out + err)
        good.execute.assert_called_once()
        bad.execute.assert_called_once()

    def test_local_failure_keeps_exit_and_sanitized_diagnostic(self):
        error = peer.NoTargetError("no reachable session: fixture\x1b[31m")
        with mock.patch.object(peer.LocalTransport, "execute", side_effect=error) as execute:
            code, out, err = self.invoke("--dry-run", "--explain")
        self.assertEqual(code, peer.EXIT_NO_TARGET)
        self.assertEqual(out, "")
        self.assertIn("Validation: not confirmed", err)
        self.assertIn("fixture\\x1b[31m", err)
        self.assertNotIn("\x1b", err)
        execute.assert_called_once()

    def test_unknown_local_and_ssh_exceptions_preserve_uncertainty(self):
        for remote in (False, True):
            with self.subTest(remote=remote), contextlib.ExitStack() as stack:
                error = peer.CcPeerError("fixture unknown outcome", {
                    "status": "unknown", "submitted": None, "retryAllowed": False})
                stack.enter_context(mock.patch.object(peer, "tailscale_status", return_value={}))
                if remote:
                    transport = stack.enter_context(mock.patch.object(peer, "SshTransport"))
                    transport.return_value.host = "receiver"
                    transport.return_value.ssh_opts = []
                    execute = transport.return_value.execute
                    execute.side_effect = error
                else:
                    execute = stack.enter_context(mock.patch.object(
                        peer.LocalTransport, "execute", side_effect=error))
                code, out, err = self.invoke("--dry-run", "--explain",
                                            *(["--host", "receiver"] if remote else []))
                self.assertEqual(code, peer.EXIT_ERROR)
                self.assertEqual(out, "")
                self.assertIn("Validation: result unknown", err)
                self.assertIn("inspect the target and existing evidence", err)
                self.assertIn("Do not automatically resend", err)
                self.assertNotIn("nothing submitted", err)
                self.assertNotIn("Destination checks: not run", err)
                execute.assert_called_once()

    def test_local_transport_invalid_result_and_adapter_exception_stay_unknown(self):
        for kwargs in ({"return_value": None}, {"side_effect": RuntimeError(BODY)}):
            with self.subTest(case=tuple(kwargs)), \
                    mock.patch.object(peer.ClaudeAdapter, "submit", **kwargs) as submit:
                code, out, err = self.invoke("--dry-run", "--explain")
            self.assertEqual(code, peer.EXIT_ERROR)
            self.assertEqual(out, "")
            self.assertIn("Validation: result unknown", err)
            self.assertIn("inspect the target and existing evidence", err)
            self.assertIn("Do not automatically resend", err)
            self.assertNotIn(BODY, err)
            self.assertNotIn("nothing submitted", err)
            submit.assert_called_once()

    def test_returned_failed_payload_keeps_old_stdout_and_explanation_on_stderr(self):
        for remote in (False, True):
            for submitted in (None, False):
                outputs = []
                for explain in (False, True):
                    with self.subTest(remote=remote, submitted=submitted, explain=explain), \
                            contextlib.ExitStack() as stack:
                        payload = {"ok": False, "target": {"agent": "codex", "id": THREAD},
                                   "dryRun": True, "chars": 12, "status": "unknown",
                                   "submitted": submitted, "consumptionConfirmed": False}
                        stack.enter_context(mock.patch.object(peer, "tailscale_status", return_value={}))
                        if remote:
                            transport = stack.enter_context(mock.patch.object(peer, "SshTransport"))
                            transport.return_value.host = "receiver"
                            transport.return_value.ssh_opts = []
                            execute = transport.return_value.execute
                            execute.return_value = payload
                        else:
                            execute = stack.enter_context(mock.patch.object(
                                peer.LocalTransport, "execute", return_value=payload))
                        code, out, err = self.invoke("--dry-run", *(["--explain"] if explain else []),
                                                    *(["--host", "receiver"] if remote else []),
                                                    target="codex:" + THREAD)
                        self.assertEqual(code, peer.EXIT_ERROR)
                        execute.assert_called_once()
                        outputs.append(out)
                        if explain:
                            self.assertIn("Delivery preview\n", err)
                            self.assertIn("Validation: result unknown", err)
                            self.assertNotIn("nothing submitted", err)
                        else:
                            self.assertEqual(err, "")
                self.assertEqual(outputs[0], outputs[1])

    def test_common_multihost_failures_do_not_claim_destination_checks(self):
        for stage in ("read_message", "validate_ssh_identity_options"):
            with self.subTest(stage=stage), \
                    mock.patch.object(peer, stage, side_effect=peer.CcPeerError("common command failure")), \
                    mock.patch.object(peer, "SshTransport") as transport, \
                    mock.patch.object(peer.LocalTransport, "execute") as local:
                code, out, err = self.invoke("--host", "first", "--host", "second",
                                            "--dry-run", "--explain")
            self.assertEqual(code, peer.EXIT_ERROR)
            self.assertEqual(out, "")
            self.assertEqual(err.count("Delivery preview\n"), 1)
            self.assertIn("Destination checks: not run", err)
            self.assertIn("Validation: not confirmed", err)
            self.assertNotIn("passed for this dry run", err)
            transport.assert_not_called()
            local.assert_not_called()

    def test_second_host_unexpected_error_names_only_current_destination(self):
        good = mock.Mock(host="first", ssh_opts=[])
        good.execute.return_value = {"target": {"pid": 42, "name": "worker"},
                                     "chars": 12, "dryRun": True}
        bad = mock.Mock(host="second", ssh_opts=[])
        bad.execute.side_effect = OSError("fixture transport error")
        with mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "SshTransport", side_effect=[good, bad]):
            code, out, err = self.invoke("--host", "first", "--host", "second",
                                        "--dry-run", "--explain")
        self.assertEqual(code, peer.EXIT_ERROR)
        self.assertIn("on first", out)
        self.assertIn("on second", err)
        self.assertNotIn("first", err)
        self.assertNotIn("Destination checks: not run", err)
        self.assertIn("Validation: result unknown", err)
        self.assertIn("inspect the target and existing evidence", err)
        good.execute.assert_called_once()
        bad.execute.assert_called_once()

    def test_remote_submission_evidence_is_not_presented_as_validated_dry_run(self):
        for agent in ("claude", "codex"):
            for evidence in ({"submitted": True}, {"dryRun": False},
                             {"status": "queued"}, {"status": "posted"}):
                with self.subTest(agent=agent, evidence=evidence):
                    payload = {"ok": True, "target": {"pid": 42, "name": "worker"}
                               if agent == "claude" else {"agent": "codex", "id": THREAD},
                               "chars": 12, "dryRun": True, **evidence}
                    with mock.patch.object(peer, "tailscale_status", return_value={}), \
                            mock.patch.object(peer, "SshTransport") as transport:
                        transport.return_value.host = "receiver"
                        transport.return_value.ssh_opts = []
                        transport.return_value.execute.return_value = payload
                        code, out, err = self.invoke("--host", "receiver", "--dry-run", "--explain",
                                                    target="worker" if agent == "claude" else "codex:" + THREAD)
                    self.assertEqual(code, 0)
                    self.assertNotIn("passed for this dry run", out + err)
                    self.assertIn("unexpected submission evidence; dry-run not confirmed", err)
                    self.assertIn("Reported ", err)
                    self.assertIn("Do not automatically resend", err)
                    self.assertNotIn("nothing submitted", out + err)
                    transport.return_value.execute.assert_called_once()

    def test_display_allowlist_does_not_mutate_or_reflect_payload_secrets(self):
        args = argparse.Namespace(to="codex:" + THREAD, host=[], wake=False,
                                  codex_home="/sender/home")
        payload = {"codexHome": "/receiver/\n\x1b", "target": {"id": THREAD + "\r"},
                   "error": BODY, "message": BODY, "receipt": BODY,
                   "handoff": {"capability": BODY}, "reason": BODY,
                   "replyRoute": {"uri": BODY}}
        original = json.dumps(payload)
        rendered = peer.render_delivery_explanation(args, payload, host="host\x00")
        self.assertNotIn(BODY, rendered)
        for char in ("\x1b", "\r", "\x00"):
            self.assertNotIn(char, rendered)
        self.assertIn("\\x0a\\x1b", rendered)
        self.assertEqual(json.dumps(payload), original)

    def test_ok_true_does_not_promote_unknown_evidence_to_validation(self):
        args = argparse.Namespace(to="codex:" + THREAD, host=[], wake=False)
        for evidence in ({"status": "unknown"}, {"submitted": None}):
            rendered = peer.render_delivery_explanation(args, {"ok": True, **evidence})
            self.assertIn("Validation: result unknown", rendered)
            self.assertNotIn("passed for this dry run", rendered)

    def test_connection_identity_failure_reason_preserves_uncertainty(self):
        args = argparse.Namespace(to="worker", host=["receiver"], wake=False)
        rendered = peer.render_delivery_explanation(args, {
            "reason": "ssh_identity_evidence_unavailable", "dryRun": True}, failed=True)
        self.assertIn("Validation: result unknown", rendered)
        self.assertIn("inspect the target and existing evidence", rendered)
        self.assertNotIn("nothing submitted", rendered)

    def test_passed_validation_requires_adapter_dry_run_evidence(self):
        args = argparse.Namespace(to="worker", host=[], wake=False)
        for result, passed in (({"ok": True}, False), ({"ok": True, "submitted": False}, False),
                               ({"ok": True, "dryRun": True}, True),
                               ({"ok": True, "status": "validated"}, True),
                               ({"ok": True, "status": "dry_run"}, True)):
            with self.subTest(result=result):
                rendered = peer.render_delivery_explanation(args, result)
                if passed:
                    self.assertIn("Validation: passed for this dry run", rendered)
                else:
                    self.assertIn("Validation: not confirmed (dry-run evidence not reported)", rendered)
                    self.assertNotIn("passed for this dry run", rendered)

    def test_ambiguous_or_submitted_response_does_not_claim_no_turn_started(self):
        args = argparse.Namespace(to="codex:" + THREAD, host=[], wake=True)
        for evidence in ({"status": "unknown"}, {"submitted": None},
                         {"submitted": True}, {"dryRun": False}, {"status": "queued"}):
            rendered = peer.render_delivery_explanation(args, {
                "ok": True, "wake": {"status": "validated"}, **evidence})
            self.assertIn("Wake: requested; preflight not confirmed", rendered)
            self.assertNotIn("no turn started", rendered)

    def test_unresolved_reply_uri_is_not_reflected(self):
        for scheme in ("session-peer", "SeSsIoN-PeEr"):
            args = argparse.Namespace(to=scheme + "://v1/reply?secret=" + BODY,
                                      host=[], wake=False)
            rendered = peer.render_delivery_explanation(args, {}, failed=True)
            self.assertNotIn(BODY, rendered)
            self.assertIn("Delivery method: unknown (not resolved)", rendered)
            self.assertNotIn("Claude Code inbox", rendered)

    def test_private_message_file_remains_an_ordinary_supported_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "private-message"
            path.write_text(BODY, encoding="utf-8")
            path.chmod(0o600)
            out = io.StringIO()
            payload = {"ok": True, "target": {"pid": 42, "name": "worker"},
                       "chars": 12, "dryRun": True}
            with mock.patch.object(peer.LocalTransport, "execute", return_value=payload) as execute, \
                    contextlib.redirect_stdout(out):
                code = peer.main(["send", "--to", "worker", "--no-from", "--no-reply-to",
                                  "--message-file", str(path), "--dry-run", "--explain"])
        self.assertEqual(code, 0)
        self.assertEqual(execute.call_args.args[-1], BODY)
        self.assertNotIn(BODY, out.getvalue())


if __name__ == "__main__":
    unittest.main()
