"""PR references remain review aids and never execute contributor text."""

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/check_pr_references.py"
WORKFLOW = ROOT / ".github/workflows/pr-reference-warning.yml"
spec = importlib.util.spec_from_file_location("check_pr_references", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class PrReferences(unittest.TestCase):
    def check(self, body):
        return checker.warnings_for_body(body)

    def test_nonclosing_references_and_intentional_completion_do_not_warn(self):
        for body in ("Refs #12", "Related to #12 and #34", "Closes #12",
                     "Fixes owner/repository#34", "Resolves #12, #34", "",
                     "This does not change the protocol. Closes #12"):
            with self.subTest(body=body):
                self.assertEqual((), self.check(body))

    def test_negated_closing_phrases_warn(self):
        for body in ("Does not close #12", "This never fixes #12", "This can't close #12",
                     "Doesn't resolve owner/repository#12", "This won’t close #12",
                     "This is not intended to close #12", "Does not\nclose #12",
                     "This does NOT CLOSE: #12", "Does not resolve https://github.com/owner/repository/issues/12"):
            with self.subTest(body=body):
                self.assertEqual(("negated",), self.check(body))

    def test_partial_closing_phrases_warn_without_disallowing_references(self):
        self.assertEqual(("partial",), self.check("Partially fixes #12"))
        self.assertEqual(("partial",), self.check("Incomplete work resolves #12"))
        self.assertEqual((), self.check("Partial work. Refs #12"))

    def test_multiple_references_have_separate_preceding_context(self):
        self.assertEqual(("negated",), self.check("Does not close #12, but closes #34"))
        self.assertEqual(("negated", "partial"), self.check("Does not close #12. Partially fixes #34"))
        self.assertEqual((), self.check("Refs #12; Closes #34"))

    def test_trailing_qualification_is_a_manual_review_limit(self):
        # The bounded preceding-clause heuristic intentionally cannot certify
        # intent stated after a closing reference. Review remains necessary.
        for body in ("Closes #12, but this work is incomplete", "Fixes #12 (not yet)"):
            self.assertEqual((), self.check(body))

    def run_event(self, root, event):
        path = root / "event.json"
        path.write_text(json.dumps(event), encoding="utf-8")
        summary = root / "summary.md"
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            env=dict(os.environ, GITHUB_EVENT_PATH=str(path), GITHUB_STEP_SUMMARY=str(summary)),
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout, summary.read_text(encoding="utf-8")

    def test_actual_event_script_handles_body_edits_without_changing_event(self):
        with tempfile.TemporaryDirectory(prefix="codex-pr-reference-") as folder:
            root = Path(folder)
            for action, body, warning in (("opened", "Refs #12", False),
                                          ("edited", "Does not close #12", True),
                                          ("edited", "Closes #12", False)):
                event = {"action": action, "pull_request": {"body": body}}
                output, _ = self.run_event(root, event)
                self.assertEqual(warning, "::warning::" in output)
                self.assertEqual(event, json.loads((root / "event.json").read_text()))

    def test_body_is_data_and_never_workflow_command_or_summary_content(self):
        with tempfile.TemporaryDirectory(prefix="codex-pr-reference-") as folder:
            root = Path(folder)
            marker = root / "executed"
            body = "Does not close #12\n::error::INJECTED\n$(touch " + str(marker) + ")\n<script>INJECTED</script>"
            output, summary = self.run_event(root, {"pull_request": {"body": body}})
            self.assertIn("::warning::", output)
            self.assertNotIn("INJECTED", output + summary)
            self.assertFalse(marker.exists())

    def test_missing_invalid_and_oversize_events_only_warn(self):
        with tempfile.TemporaryDirectory(prefix="codex-pr-reference-") as folder:
            root = Path(folder)
            for event in ({}, [], {"pull_request": {"body": 123}}):
                output, _ = self.run_event(root, event)
                self.assertIn(checker.MESSAGES["unavailable"], output)
            path = root / "oversize.json"
            path.write_bytes(b" " * (checker.MAX_EVENT_BYTES + 1))
            self.assertEqual(("unavailable",), checker.event_warnings(path))
            self.assertEqual(("unavailable",), checker.event_warnings(root / "absent"))

    def test_long_whitespace_without_a_reference_is_not_a_regex_time_trap(self):
        with tempfile.TemporaryDirectory(prefix="codex-pr-reference-") as folder:
            output, _ = self.run_event(Path(folder), {
                "pull_request": {"body": "Does not close" + " " * 65536 + "not-a-reference"}})
            self.assertNotIn("::warning::", output)

    def test_workflow_uses_only_trusted_base_code_and_read_only_permissions(self):
        text = WORKFLOW.read_text()
        self.assertIn("pull_request_target:", text)
        self.assertIn("branches: [main]", text)
        self.assertIn("types: [opened, edited, reopened, synchronize]", text)
        self.assertIn("ref: ${{ github.sha }}", text)
        self.assertIn("persist-credentials: false", text)
        self.assertEqual(["contents: read"], re.findall(r"^  ([a-z-]+: (?:read|write))$", text, re.M))
        self.assertNotRegex(text, r"(?m)^\s+[a-z-]+:\s*write\b")
        self.assertNotRegex(text, r"(?m)^\s*permissions:\s*write-all\b")
        self.assertNotIn("secrets.", text)
        self.assertNotIn("pull_request.head", text)
        self.assertNotIn("pull_request.base.sha", text)
        self.assertNotIn("pull_request.body", text)
        self.assertNotIn("refs/pull", text)
        self.assertIn("run: python3 .github/scripts/check_pr_references.py", text)
        uses = re.findall(r"uses: ([^\s]+)", text)
        self.assertTrue(all(re.fullmatch(r"[\w-]+/[\w-]+@[0-9a-f]{40}", ref) for ref in uses))

    def test_template_defaults_to_nonclosing_references_and_current_checks(self):
        text = (ROOT / ".github/pull_request_template.md").read_text()
        self.assertIn("Refs #<!-- issue number", text)
        self.assertNotRegex(text, r"(?im)^\s*(?:closes|fixes|resolves)\s+#")
        self.assertNotIn("cc_peer.py", text)
        self.assertNotIn("CLAUDE.md", text)
        for item in ("python session_peer.py --version", "python tools/generate_session_peer.py --check",
                     "tests/core", "tests/adapters", "tests/codex", "tests/distribution", "tests/docs",
                     "tests/mcp_integration", "tests/relay", "npm audit --omit=dev",
                     "not run: reason", "not applicable: reason", "Node/npm", "Codex", "Antigravity"):
            self.assertIn(item, text)
        self.assertIn("Do not negate", text)
        for limitation in ("sidebar", "commit messages", "default branch"):
            self.assertIn(limitation, text)
        self.assertIn("Closes <issue-reference>", text)
        self.assertIn("not required for every PR", text)
        for link in re.findall(r"\]\(https://github.com/abruption/session-peer/blob/main/([^)]*)\)", text):
            self.assertTrue((ROOT / link).is_file(), link)

    def test_summary_failure_still_warns_without_reflecting_data(self):
        with tempfile.TemporaryDirectory(prefix="codex-pr-reference-") as folder:
            root = Path(folder)
            event = root / "event.json"
            event.write_text(json.dumps({"pull_request": {"body": "Closes #12"}}))
            result = subprocess.run(
                [sys.executable, str(SCRIPT)],
                env=dict(os.environ, GITHUB_EVENT_PATH=str(event), GITHUB_STEP_SUMMARY=str(root)),
                capture_output=True, text=True)
            self.assertEqual(0, result.returncode)
            self.assertIn(checker.MESSAGES["unavailable"], result.stdout)
            self.assertEqual("", result.stderr)


if __name__ == "__main__":
    unittest.main()
