"""Offline terminal-control fixtures; no terminal or destination is contacted."""

import contextlib
import copy
import io
import json
import subprocess
import unittest
from unittest import mock

import session_peer as peer


CONTROLS = (
    "\x1b]52;c;Zml4dHVyZQ==\x07",  # OSC clipboard
    "\x1b]8;;https://example.invalid\x1b\\link\x1b]8;;\x1b\\",  # OSC link
    "\x1b[31mred\x1b[0m",  # CSI
    "\x9b31m\x9dtitle\x9c",  # C1 CSI, OSC and ST
    "\x07", "\x7f", "\n\r\t\x00",
)
EXTERNAL = "이름 café " + "|".join(CONTROLS)


class HumanOutput(unittest.TestCase):
    def assert_terminal_safe(self, text):
        self.assertFalse(any(ord(char) < 0x20 and char != "\n"
                             or 0x7f <= ord(char) <= 0x9f for char in text), repr(text))

    def invoke(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = peer.main([*argv, "--no-update-notice"])
        return code, stdout.getvalue(), stderr.getvalue()

    def listing(self):
        return {
            "ok": False,
            "sessions": [
                {"agent": "claude", "pid": 7, "name": EXTERNAL, "cwd": EXTERNAL,
                 "status": EXTERNAL, "alive": True, "reachable": True},
                {"agent": "codex", "id": EXTERNAL, "name": EXTERNAL, "cwd": EXTERNAL,
                 "archived": False, "codexHome": EXTERNAL},
            ],
            "discovery": {"claude": {"status": "ok"},
                          "codex": {"status": "error", "error": EXTERNAL,
                                    "homes": [{"status": "error", "codexHome": EXTERNAL,
                                               "code": EXTERNAL, "error": EXTERNAL}],
                                    "errors": [{"source": EXTERNAL, "code": EXTERNAL,
                                                "error": EXTERNAL}]}},
            "codexHome": EXTERNAL,
        }

    def test_all_controls_escape_and_unicode_survives(self):
        controls = "".join(chr(code) for code in (*range(32), *range(127, 160)))
        expected = "".join(f"\\x{ord(char):02x}" for char in controls)
        self.assertEqual(peer.human_text(controls), expected)
        self.assertEqual(peer.human_text("이름 café 😀"), "이름 café 😀")
        self.assertEqual(peer.human_text(peer.human_text(EXTERNAL)), peer.human_text(EXTERNAL))

    def test_listing_fields_notes_and_renderer_newlines(self):
        payload = self.listing()
        original = copy.deepcopy(payload)
        for selected in (None, "claude", "codex"):
            rows = payload if selected is None else {
                **payload, "sessions": [row for row in payload["sessions"]
                                          if row["agent"] == selected],
            }
            with self.subTest(selected=selected):
                rendered = peer.render_listing(rows, EXTERNAL, selected)
                self.assert_terminal_safe(rendered)
                self.assertIn(peer.human_text(EXTERNAL), rendered)
                self.assertGreater(len(rendered.splitlines()), 2)
                self.assertIn("\\x0a\\x0d\\x09\\x00", rendered)
        self.assertEqual(payload, original)

    def test_mapping_keys_are_preserved_and_escaped_only_when_rendered(self):
        # Sanitizing keys inside a copied mapping would collapse these two
        # distinct records and could hide one of the discovery failures.
        discovery = {"fixture\x1b": {"status": "error", "error": EXTERNAL},
                     "fixture\\x1b": {"status": "error", "error": EXTERNAL}}
        self.assertEqual(list(peer.human_text(discovery)), list(discovery))
        adapter = mock.Mock()
        adapter.listing_notes.return_value = []
        with mock.patch.object(peer.AGENTS, "get", return_value=adapter):
            rendered = peer.render_listing({"sessions": [], "discovery": discovery}, "fixture", None)
        self.assert_terminal_safe(rendered)
        self.assertEqual(rendered.count("fixture\\x1b discovery failed:"), 2)
        self.assertEqual(len(discovery), 2)

    def test_table_padding_uses_escaped_width(self):
        sessions = [
            {"name": "a\x1b\x07", "pid": 456, "status": "idle\x9b", "cwd": "/one",
             "alive": True, "reachable": True},
            {"name": "longer", "pid": 12345, "status": "busy", "cwd": "/two",
             "alive": True, "reachable": True},
        ]
        lines = peer.render_sessions(sessions, "fixture").splitlines()[1:]
        pid_column, status_column, cwd_column = (lines[0].index(label) for label in
                                                 ("PID", "STATUS", "CWD"))
        for line, row in zip(lines[1:], sessions):
            self.assertEqual(line.index(str(row["pid"])), pid_column)
            self.assertEqual(line.index(peer.human_text(row["status"])), status_column)
            self.assertEqual(line.index(row["cwd"]), cwd_column)

    def test_doctor_sanitizes_paths_checks_and_return_status(self):
        payload = {"claude": {"status": EXTERNAL},
                   "codex": {"status": EXTERNAL, "selectedHome": EXTERNAL,
                             "checks": [{"status": "error", "code": EXTERNAL,
                                         "message": EXTERNAL}]},
                   "antigravity": {"status": EXTERNAL},
                   "skill": {"checks": [{"code": EXTERNAL, "message": EXTERNAL}]},
                   "returnRoute": {"status": EXTERNAL, "transport": EXTERNAL,
                                   "reason": EXTERNAL}}
        original = copy.deepcopy(payload)
        rendered = peer.render_doctor(payload, EXTERNAL)
        self.assert_terminal_safe(rendered)
        self.assertIn(peer.human_text(EXTERNAL), rendered)
        self.assertGreater(len(rendered.splitlines()), 3)
        self.assertEqual(payload, original)

    def test_send_renderers_sanitize_all_agents(self):
        results = {
            "claude": {"target": {"name": EXTERNAL}, "chars": 4, "dryRun": True},
            "codex": {"target": {"id": EXTERNAL}, "codexHome": EXTERNAL,
                      "dryRun": False, "queueId": EXTERNAL,
                      "wake": {"status": EXTERNAL, "reason": EXTERNAL, "error": EXTERNAL}},
            "antigravity": {"status": EXTERNAL},
        }
        original = copy.deepcopy(results)
        for agent, result in results.items():
            with self.subTest(agent=agent):
                self.assert_terminal_safe(peer.AGENTS.get(agent).submission_text(result, EXTERNAL))
        self.assertEqual(results, original)

    def test_json_list_bytes_unchanged_and_payload_not_mutated(self):
        payload = self.listing()
        original = copy.deepcopy(payload)
        expected = json.dumps(peer.json_result("list", payload), ensure_ascii=False) + "\n"
        with mock.patch.object(peer, "collect_listing", return_value=payload):
            code, stdout, stderr = self.invoke("list", "--json")
        self.assertEqual(code, peer.EXIT_ERROR)
        self.assertEqual(stdout.encode(), expected.encode())
        self.assertEqual(stderr, "")
        self.assertEqual(payload, original)

    def test_doctor_json_bytes_unchanged(self):
        payload = {"status": "partial", "codex": {"status": EXTERNAL,
                                                    "selectedHome": EXTERNAL}}
        original = copy.deepcopy(payload)
        expected = json.dumps(peer.json_result("doctor", payload), ensure_ascii=False) + "\n"
        with mock.patch.object(peer, "doctor_payload", return_value=payload):
            code, stdout, stderr = self.invoke("doctor", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(stdout.encode(), expected.encode())
        self.assertEqual(stderr, "")
        self.assertEqual(payload, original)

    def test_send_body_and_json_bytes_unchanged(self):
        body = EXTERNAL
        result = {"ok": True, "target": {"name": EXTERNAL, "pid": 7},
                  "chars": len(body), "dryRun": False}
        expected = json.dumps(peer.json_result("send", result), ensure_ascii=False) + "\n"
        for json_mode in (False, True):
            with self.subTest(json=json_mode), \
                 mock.patch.object(peer.LocalTransport, "execute", return_value=copy.deepcopy(result)) as execute:
                code, stdout, stderr = self.invoke("send", "--to", "fixture", "--message", body,
                                                   "--no-from", "--no-reply-to",
                                                   *(["--json"] if json_mode else []))
            self.assertEqual(code, 0)
            self.assertEqual(execute.call_args.args[3], body)
            self.assertEqual(stderr, "")
            if json_mode:
                self.assertEqual(stdout.encode(), expected.encode())
            else:
                self.assert_terminal_safe(stdout)

    def test_update_result_and_notices_sanitize_display_only(self):
        with mock.patch.object(peer, "installed_as_distribution", return_value=True), \
             mock.patch.object(peer, "update_command", return_value=EXTERNAL):
            code, stdout, stderr = self.invoke("update")
            expected = json.dumps(peer.json_result("update", {
                "current": peer.__version__, "updated": False, "managedBy": "package-manager",
                "updateCommand": EXTERNAL}), ensure_ascii=False) + "\n"
            _, json_stdout, json_stderr = self.invoke("update", "--json")
        self.assertEqual(code, 0)
        self.assert_terminal_safe(stdout)
        self.assertIn(peer.human_text(EXTERNAL), stdout)
        self.assertEqual(json_stdout.encode(), expected.encode())
        self.assertEqual(stderr + json_stderr, "")
        notice = {"current": EXTERNAL, "latest": EXTERNAL, "command": EXTERNAL}
        skills = [{**notice, "location": EXTERNAL}]
        with mock.patch.object(peer, "_CLIENT_UPDATE_NOTICE", notice), \
             mock.patch.object(peer, "_SKILL_UPDATE_NOTICES", skills), \
             contextlib.redirect_stderr(io.StringIO()) as output:
            peer.emit_human_update_notice()
        self.assert_terminal_safe(output.getvalue())
        self.assertEqual(notice["current"], EXTERNAL)
        self.assertEqual(skills[0]["location"], EXTERNAL)

    def test_remote_version_warning_and_update_check(self):
        with mock.patch.object(peer, "tailscale_status", return_value={}), \
             mock.patch.object(peer.SshTransport, "execute", return_value=self.listing()), \
             mock.patch.object(peer, "remote_installed_version", return_value=EXTERNAL), \
             mock.patch.object(peer, "release_version", return_value=(1, 0, 2, 3, 0)), \
             mock.patch.object(peer, "ssh_user_metadata", return_value={}):
            # This fixture checks display escaping, not version validity. The
            # ordered updater (#229) rejects malformed versions before display;
            # stub only its semantic comparison without changing that guard.
            for command in (("list", "--host", "fixture"),
                            ("update", "--check", "--host", "fixture")):
                with self.subTest(command=command):
                    _, stdout, stderr = self.invoke(*command)
                    self.assert_terminal_safe(stdout + stderr)
                    self.assertIn(peer.human_text(EXTERNAL), stdout)
                    if command[0] == "list":
                        self.assertIn("Sessions on fixture:\n", stdout)

    def test_mocked_ssh_stderr_in_each_human_error_and_json(self):
        completed = subprocess.CompletedProcess([], 255, "", EXTERNAL)
        commands = (("list",), ("doctor",),
                    ("send", "--to", "fixture", "--message", "fixture",
                     "--no-from", "--no-reply-to"), ("update", "--check"))
        with mock.patch.object(peer, "tailscale_status", return_value={}), \
             mock.patch.object(peer, "ssh_user_metadata", return_value={}), \
             mock.patch.object(peer.subprocess, "run", return_value=completed):
            for command in commands:
                with self.subTest(command=command):
                    code, stdout, stderr = self.invoke(*command, "--host", "fixture")
                    self.assertEqual(code, peer.EXIT_ERROR)
                    self.assertEqual(stdout, "")
                    self.assert_terminal_safe(stderr)
                    self.assertIn(peer.human_text(EXTERNAL), stderr)
                    _, json_stdout, json_stderr = self.invoke(*command, "--host", "fixture", "--json")
                    error = peer.ssh_failure_error("fixture", {}, "transport_failed", EXTERNAL)
                    message, details = str(error), error.details
                    if command[0] == "send":
                        message += ("; submission outcome unknown. Do not automatically retry; "
                                    "check the target before retrying.")
                        details = {**details, "status": "unknown", "reason": "outcome_unknown",
                                   "retryAllowed": False}
                    expected = json.dumps(peer.json_result(command[0], {
                        "host": "fixture", "error": message, **details}, ok=False),
                        ensure_ascii=False) + "\n"
                    self.assertEqual(json_stdout.encode(), expected.encode())
                    self.assertEqual(json_stderr, "")

    def test_main_and_argument_parser_errors_sanitize_external_newlines(self):
        for exception in (peer.CcPeerError(EXTERNAL), RuntimeError(EXTERNAL)):
            with self.subTest(exception=type(exception).__name__), \
                 mock.patch.object(peer, "collect_listing", side_effect=exception):
                code, _, stderr = self.invoke("list")
                self.assertEqual(code, peer.EXIT_ERROR)
                self.assert_terminal_safe(stderr)
                self.assertEqual(len(stderr.splitlines()), 1)
        with contextlib.redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit):
            peer.main(["list", "--unknown=" + EXTERNAL])
        self.assert_terminal_safe(stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
