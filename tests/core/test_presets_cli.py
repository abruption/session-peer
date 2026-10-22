"""Route presets are sender-only snapshots, never receiver bindings."""
import contextlib
import io
import json
import unittest
from unittest import mock

import session_peer as peer


class PresetCliTests(unittest.TestCase):
    route = {"transport": "local", "agent": "claude"}
    ssh_route = {"transport": "ssh", "agent": "codex", "host": "user@fixture", "codexHome": "/fixture/home"}
    revision = "dp1:" + "a" * 64

    def run_cli(self, argv, **kwargs):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            try:
                code = peer.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), error.getvalue()

    def test_opt_out_does_not_read_presets(self):
        with mock.patch.object(peer, "preset_lookup", side_effect=AssertionError("store")), \
                mock.patch.object(peer, "preset_read", side_effect=AssertionError("store")), \
                mock.patch.object(peer, "cmd_list", return_value=0) as listing:
            self.assertEqual(self.run_cli(["list"])[0], 0)
        listing.assert_called_once()

    def test_management_has_no_notice_refresh_or_transport_even_as_real_invocation(self):
        for action in (["list"], ["show", "work"]):
            with self.subTest(action=action), \
                    mock.patch.object(peer.sys, "argv", ["session-peer", "preset", *action, "--json"]), \
                    mock.patch.object(peer, "IS_WINDOWS", False), \
                    mock.patch.object(peer, "preset_read", return_value={"work": self.route}), \
                    mock.patch.object(peer, "preset_lookup", return_value=(self.route, self.revision)), \
                    mock.patch.object(peer, "preset_revision", return_value=self.revision), \
                    mock.patch.object(peer, "prepare_client_update", side_effect=AssertionError("notice")), \
                    mock.patch.object(peer, "prepare_skill_updates", side_effect=AssertionError("notice")), \
                    mock.patch.object(peer, "validate_ssh_identity_options", side_effect=AssertionError("transport")):
                code, output, _ = self.run_cli(None)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["command"], "preset")

    def test_management_add_replace_remove_shapes(self):
        cases = [
            (["add", "work", "--agent", "claude"], "add", self.route, None),
            (["replace", "work", "--agent", "codex", "--host", "user@fixture", "--codex-home", "/fixture/home", "--expect-revision", self.revision], "replace", self.ssh_route, self.revision),
            (["remove", "work", "--expect-revision", self.revision], "remove", None, self.revision),
        ]
        for argv, action, route, expected in cases:
            with self.subTest(action=action), mock.patch.object(peer, "IS_WINDOWS", False), \
                    mock.patch.object(peer, "preset_mutate", return_value={"name": "work", "revision": self.revision, "route": self.route}) as mutation:
                code, output, _ = self.run_cli(["preset", *argv, "--json"])
            self.assertEqual(code, 0)
            mutation.assert_called_once_with(action, "work", route, expected)
            self.assertNotIn("clientUpdate", json.loads(output))

    def test_conflicts_are_usage_errors_before_store_input_or_notices(self):
        flags = [["--host", "fixture"], ["--host=fixture"], ["--ho=fixture"],
                 ["--codex-home", "/fixture"], ["--ssh-opt=-4"], ["--codex-bin", "codex"],
                 ["--device", "device"], ["--device-route", "auto"], ["--request-ack"],
                 ["--wait-timeout", "30"], ["--wake"], ["--wake-timeout", "30"],
                 ["--allow-inactive-codex-home"], ["--b64", "eA=="],
                 ["--_handoff-native-total-ms", "1000"], ["--_wake-depth", "0"]]
        for extra in flags:
            with self.subTest(extra=extra), \
                    mock.patch.object(peer, "preset_lookup", side_effect=AssertionError("store")), \
                    mock.patch.object(peer, "read_message", side_effect=AssertionError("stdin")), \
                    mock.patch.object(peer, "prepare_client_update", side_effect=AssertionError("notice")):
                code, _, error = self.run_cli(["send", "--preset", "work", "--to", "test", "--dry-run", *extra])
            self.assertEqual(code, 2)
            self.assertIn("--preset conflicts with", error)

    def test_uri_and_agent_conflict_and_missing_revision(self):
        for target in ("session-peer://v1/reply?token=do-not-echo", "SESSION-PEER://v1/reply"):
            with mock.patch.object(peer, "preset_lookup", side_effect=AssertionError("store")):
                code, _, error = self.run_cli(["send", "--preset", "work", "--dry-run", "--to", target])
            self.assertEqual(code, 2)
            self.assertIn("Reply-To URI", error)
            self.assertNotIn("token=do-not-echo", error)
        with mock.patch.object(peer, "IS_WINDOWS", False), mock.patch.object(peer, "preset_lookup", return_value=(self.route, self.revision)):
            code, _, error = self.run_cli(["send", "--preset", "work", "--dry-run", "--to", "codex:fixture"])
        self.assertEqual(code, 2)
        self.assertIn("--to agent conflicts", error)
        with mock.patch.object(peer, "preset_lookup", side_effect=AssertionError("store")):
            code, _, error = self.run_cli(["send", "--preset", "work", "--to", "test"])
        self.assertEqual(code, 2)
        self.assertIn("require --preset-revision", error)

    def test_revision_without_preset_and_list_agent_override(self):
        for argv in (["send", "--to", "test", "--preset-revision", self.revision],
                     ["list", "--preset", "work", "--agent", "claude"]):
            with mock.patch.object(peer, "preset_lookup", side_effect=AssertionError("store")):
                self.assertEqual(self.run_cli(argv)[0], 2)

    def test_message_option_values_and_post_separator_values_are_not_flags(self):
        for body in (["--message=--host"], ["--message=--"], ["--", "--wake"]):
            with self.subTest(body=body), mock.patch.object(peer, "IS_WINDOWS", False), \
                    mock.patch.object(peer, "preset_lookup", return_value=(self.route, self.revision)), \
                    mock.patch.object(peer, "cmd_send", return_value=0) as send:
                code, _, _ = self.run_cli(["send", "--preset", "work", "--to", "test", "--dry-run", *body])
            self.assertEqual(code, 0)
            send.assert_called_once()

    def test_real_invocation_store_error_starts_no_advisory_work(self):
        with mock.patch.object(peer.sys, "argv", ["session-peer", "list", "--preset", "work", "--json"]), \
                mock.patch.object(peer, "IS_WINDOWS", False), \
                mock.patch.object(peer, "preset_lookup", side_effect=peer.CcPeerError("Preset not found")), \
                mock.patch.object(peer, "prepare_client_update") as client, \
                mock.patch.object(peer, "prepare_skill_updates") as skills, \
                mock.patch.object(peer, "cmd_list") as listing:
            code, _, _ = self.run_cli(None)
        self.assertEqual(code, 1)
        client.assert_not_called()
        skills.assert_not_called()
        listing.assert_not_called()

    def test_early_lookup_and_management_interrupt_or_unexpected_error_are_bounded(self):
        for management in (False, True):
            for failure in (KeyboardInterrupt(), RuntimeError("PRIVATE_PATH_AND_BODY")):
                with self.subTest(management=management, failure=type(failure).__name__), \
                        mock.patch.object(peer, "IS_WINDOWS", False), \
                        mock.patch.object(peer.sys, "argv", ["session-peer", *(["preset", "list", "--json"] if management else ["list", "--preset", "work", "--json"])]), \
                        mock.patch.object(peer, "preset_read", side_effect=failure), \
                        mock.patch.object(peer, "preset_lookup", side_effect=failure), \
                        mock.patch.object(peer, "prepare_client_update") as client, \
                        mock.patch.object(peer, "prepare_skill_updates") as skills, \
                        mock.patch.object(peer, "cmd_list") as listing:
                    code, output, error = self.run_cli(None)
                client.assert_not_called()
                skills.assert_not_called()
                listing.assert_not_called()
                self.assertNotIn("PRIVATE_PATH_AND_BODY", output + error)
                self.assertNotIn("Traceback", output + error)
                if isinstance(failure, KeyboardInterrupt):
                    self.assertEqual(code, 130)
                    self.assertEqual(output + error, "")
                else:
                    self.assertEqual(code, 1)
                    result = json.loads(output)
                    self.assertEqual(result["reason"], "preset_operation_failed")
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["command"], "preset" if management else "list")

    def test_lookup_failure_and_changed_revision_use_error_envelope_before_effect(self):
        for result in (peer.CcPeerError("Preset not found", {"reason": "preset_not_found"}), (self.route, "dp1:" + "b" * 64)):
            patch = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
            with self.subTest(result=type(result).__name__), mock.patch.object(peer, "IS_WINDOWS", False), \
                    mock.patch.object(peer, "preset_lookup", **patch), \
                    mock.patch.object(peer, "read_message", side_effect=AssertionError("input")), \
                    mock.patch.object(peer, "cmd_send", side_effect=AssertionError("effect")), \
                    mock.patch.object(peer, "prepare_client_update", side_effect=AssertionError("notice")):
                code, output, _ = self.run_cli(["send", "--preset", "work", "--preset-revision", self.revision, "--to", "test", "--json"])
            self.assertEqual(code, 1)
            payload = json.loads(output)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["command"], "send")
            self.assertNotIn("submitted", payload)

    def test_local_send_keeps_json_and_text_revision_on_stderr(self):
        native = {"ok": True, "target": {"pid": 42, "name": "test"}, "chars": 1, "dryRun": True}
        for output_flags in (["--json"], []):
            with self.subTest(output_flags=output_flags), mock.patch.object(peer, "IS_WINDOWS", False), \
                    mock.patch.object(peer, "preset_lookup", return_value=(self.route, self.revision)) as lookup, \
                    mock.patch.object(peer.LocalTransport, "execute", return_value=dict(native)) as execute:
                code, output, error = self.run_cli(["send", "--preset", "work", "--to", "test", "--message", "x", "--dry-run", "--no-from", "--no-reply-to", *output_flags])
            self.assertEqual(code, 0)
            lookup.assert_called_once_with("work")
            self.assertEqual(execute.call_args.args[2].host, [])
            if output_flags:
                payload = json.loads(output)
                self.assertNotIn("preset", payload)
                self.assertNotIn("submitted", payload)
                self.assertEqual(error, "")
            else:
                self.assertIn(self.revision, error)
                self.assertNotIn(self.revision, output)

    def test_ssh_list_expands_single_route_without_forwarding_preset(self):
        transport = mock.Mock(host="fixture", ssh_opts=[], identity_requested=False)
        transport.execute.return_value = {"ok": True, "sessions": []}
        with mock.patch.object(peer, "IS_WINDOWS", False), \
                mock.patch.object(peer, "preset_lookup", return_value=(self.ssh_route, self.revision)), \
                mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "SshTransport", return_value=transport) as factory, \
                mock.patch.object(peer, "remote_installed_version", return_value=peer.__version__):
            code, output, _ = self.run_cli(["list", "--preset", "work", "--json", "--ssh-identity"])
        self.assertEqual(code, 0)
        self.assertEqual(factory.call_args.args[0], "user@fixture")
        args = factory.call_args.args[1]
        self.assertEqual(args.agent, "codex")
        self.assertEqual(args.codex_home, "/fixture/home")
        argv = transport.execute.call_args.args[0]
        self.assertEqual(argv, ["list", "--no-update-notice", "--agent", "codex", "--codex-home", "/fixture/home"])
        self.assertNotIn("preset", json.loads(output))

    def test_actual_ssh_send_requires_snapshot_and_does_not_forward_it(self):
        transport = mock.Mock(host="fixture", ssh_opts=[])
        transport.execute.return_value = {"ok": True, "target": {"agent": "codex", "id": "00000000-0000-4000-8000-000000000001"}, "status": "queued", "submitted": True, "consumptionConfirmed": False, "chars": 1, "dryRun": False}
        with mock.patch.object(peer, "IS_WINDOWS", False), \
                mock.patch.object(peer, "preset_lookup", return_value=(self.ssh_route, self.revision)), \
                mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "SshTransport", return_value=transport):
            code, output, _ = self.run_cli(["send", "--preset", "work", "--preset-revision", self.revision, "--to", "codex:00000000-0000-4000-8000-000000000001", "--message", "x", "--no-from", "--no-reply-to", "--json"])
        self.assertEqual(code, 0)
        argv = transport.execute.call_args.args[0]
        self.assertNotIn("--preset", argv)
        self.assertNotIn(self.revision, argv)
        self.assertNotIn("--preset-revision", argv)
        self.assertNotIn("preset", json.loads(output))

    def test_windows_refuses_before_store_and_management_is_sanitized(self):
        for argv in (["preset", "list", "--json"], ["list", "--preset", "work", "--json"]):
            with mock.patch.object(peer, "IS_WINDOWS", True), \
                    mock.patch.object(peer, "preset_lookup", side_effect=AssertionError("store")), \
                    mock.patch.object(peer, "preset_read", side_effect=AssertionError("store")):
                code, output, _ = self.run_cli(argv)
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output)["reason"], "preset_platform_unsupported")
        shown = peer.render_preset_route("bad\x1bname", {"transport": "ssh", "host": "a\nhost", "agent": "codex", "codexHome": "/a\x07"}, self.revision)
        self.assertNotIn("\x1b", shown)
        self.assertNotIn("\x07", shown)
        self.assertIn("a\\x0ahost", shown)


if __name__ == "__main__":
    unittest.main()
