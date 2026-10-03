"""Scheduled audits report findings without gating unrelated pull requests."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/dependency-audit.yml"


def named_step(text, name):
    match = re.search(
        r"^      - name: " + re.escape(name) + r"\n(.*?)(?=^      - |^  [a-z]|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError("Missing workflow step: " + name)
    return match.group(1)


def run_script(text, name):
    return textwrap.dedent(named_step(text, name).split("        run: |\n", 1)[1])


AUDIT_STUBS = r'''
python() {
  test "$1" = -m && test "$2" = pip_audit || return 99
  while test "$#" -gt 0; do
    if test "$1" = --output; then
      shift
      printf '%s\n' "$AUDIT_FIXTURE" > "$1"
      break
    fi
    shift
  done
  printf '%s\n' "$AUDIT_DIAGNOSTIC" >&2
  return "$AUDIT_STATUS"
}
npm() {
  test "$1" = audit || return 99
  printf '%s\n' "$AUDIT_FIXTURE"
  printf '%s\n' "$AUDIT_DIAGNOSTIC" >&2
  return "$AUDIT_STATUS"
}
'''


class DependencyAuditWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_weekly_manual_read_only_workflow_is_separate_from_release_gate(self):
        trigger = self.text.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
        self.assertIn("  schedule:\n    - cron: '23 6 * * 1'\n", trigger)
        self.assertIn("  workflow_dispatch:\n", trigger)
        self.assertNotRegex(trigger, r"(?:push|pull_request|workflow_call|workflow_run):")
        self.assertEqual(["contents: read"], re.findall(r"^  ([a-z-]+: (?:read|write))$", self.text, re.MULTILINE))
        self.assertNotIn("secrets.", self.text)
        self.assertNotIn("continue-on-error", self.text)
        self.assertNotIn("needs:", self.text)
        self.assertNotIn("release-gate", self.text)
        self.assertFalse((ROOT / ".github/dependabot.yml").exists())
        self.assertEqual(2, self.text.count("persist-credentials: false"))

    def test_audits_use_only_runtime_dependencies_and_always_retain_reports(self):
        install = run_script(self.text, "Install only runtime dependencies in an isolated environment")
        self.assertIn('python -m venv "$RUNNER_TEMP/session-peer-runtime-audit"', install)
        self.assertIn("install '.[relay,mcp]'", install)
        self.assertNotIn("requirements/audit.txt", install)
        self.assertIn("--path", run_script(self.text, "Audit Python runtime dependencies"))
        self.assertIn("npm audit --omit=dev --json", run_script(self.text, "Audit Node runtime dependencies"))
        for ecosystem in ("Python", "Node"):
            with self.subTest(ecosystem=ecosystem):
                summary = named_step(self.text, "Summarize " + ecosystem + " audit")
                upload = named_step(self.text, "Upload " + ecosystem + " audit reports")
                self.assertIn("if: ${{ always() }}", summary)
                self.assertIn("if: ${{ always() }}", upload)
                self.assertIn("path: audit-reports/", upload)
                self.assertIn("retention-days: 30", upload)
                self.assertIn('"$GITHUB_STEP_SUMMARY"', summary)

    def test_findings_and_service_errors_preserve_failure_and_reports(self):
        fixtures = {
            "Python": {"dependencies": [{"name": "fixture-package", "version": "1.0", "vulns": [{"id": "TEST-PYTHON-ADVISORY", "fix_versions": ["1.1"]}]}]},
            "Node": {"auditReportVersion": 2, "vulnerabilities": {"fixture-package": {"severity": "high", "via": [{"source": 1, "name": "fixture-package", "title": "TEST-NODE-ADVISORY"}]}}, "metadata": {"vulnerabilities": {"high": 1, "total": 1}}},
        }
        for ecosystem, fixture in fixtures.items():
            for status in (0, 1, 2):
                with self.subTest(ecosystem=ecosystem, status=status):
                    self.exercise_audit(ecosystem, fixture if status == 1 else {}, status)

    def exercise_audit(self, ecosystem, fixture, status):
        # These fixtures execute the workflow's actual shell, without fetching
        # dependencies or contacting an advisory service.
        with tempfile.TemporaryDirectory(prefix="codex-dependency-audit-") as directory:
            root = Path(directory)
            control = root / "control"
            control.mkdir()
            runtime_bin = root / "session-peer-runtime-audit/bin"
            runtime_bin.mkdir(parents=True)
            (runtime_bin / "python").symlink_to(sys.executable)
            summary = root / "github-summary.md"
            diagnostic = "advisory service unavailable" if status == 2 else "audit fixture diagnostic"
            env = dict(os.environ, RUNNER_TEMP=str(root), GITHUB_STEP_SUMMARY=str(summary),
                       AUDIT_FIXTURE=json.dumps(fixture), AUDIT_STATUS=str(status),
                       AUDIT_DIAGNOSTIC=diagnostic,
                       AUDIT_OUTCOME="success" if status == 0 else "failure")
            audit = subprocess.run(
                ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c",
                 AUDIT_STUBS + run_script(self.text, "Audit " + ecosystem + " runtime dependencies")],
                cwd=control if ecosystem == "Node" else root, env=env, capture_output=True, text=True,
            )
            self.assertEqual(status, audit.returncode, audit.stderr)
            reports = root / "audit-reports"
            self.assertEqual(str(status), (reports / "exit-status.txt").read_text().strip())
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c",
                 run_script(self.text, "Summarize " + ecosystem + " audit")],
                cwd=root, env=env, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            report = reports / ("python.json" if ecosystem == "Python" else "node.json")
            self.assertEqual(fixture, json.loads(report.read_text()))
            output = summary.read_text()
            self.assertIn("Audit step: " + env["AUDIT_OUTCOME"], output)
            self.assertIn("Exit status: " + str(status), output)
            self.assertIn(diagnostic, output)
            if status == 1:
                self.assertIn("TEST-" + ecosystem.upper() + "-ADVISORY", output)
            self.assertEqual(output, (reports / "summary.md").read_text())

    def test_setup_failure_still_produces_an_explicit_summary_artifact(self):
        for ecosystem in ("Python", "Node"):
            with self.subTest(ecosystem=ecosystem), tempfile.TemporaryDirectory(prefix="codex-dependency-audit-") as directory:
                root = Path(directory)
                summary = root / "github-summary.md"
                result = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c",
                     run_script(self.text, "Summarize " + ecosystem + " audit")],
                    cwd=root, env=dict(os.environ, GITHUB_STEP_SUMMARY=str(summary), AUDIT_OUTCOME="skipped"),
                    capture_output=True, text=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("Audit did not complete", summary.read_text())
                self.assertTrue((root / "audit-reports/summary.md").is_file())


if __name__ == "__main__":
    unittest.main()
