"""Structural contracts for release-critical GitHub Actions workflows."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
ACTION_REF = re.compile(r"^\s*- uses: [^@\s]+@([^\s#]+)", re.MULTILINE)
FULL_SHA = re.compile(r"[0-9a-f]{40}")
JOB = re.compile(r"^  ([a-z][a-z0-9-]*):\s*$", re.MULTILINE)


class ReleaseWorkflows(unittest.TestCase):
    def test_every_third_party_action_is_commit_pinned(self):
        for relative in (".github/workflows/ci.yml", ".github/workflows/publish.yml"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            refs = ACTION_REF.findall(text)
            self.assertTrue(refs, relative)
            for ref in refs:
                self.assertIsNotNone(
                    FULL_SHA.fullmatch(ref), f"{relative}: unpinned action ref {ref}"
                )

    def test_release_gate_needs_every_other_ci_job(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        jobs = set(JOB.findall(text.split("\njobs:\n", 1)[1]))
        match = re.search(r"^  release-gate:\n(?:^    .*\n)*?^    needs: \[([^]]+)\]$", text, re.MULTILINE)
        self.assertIsNotNone(match, "release-gate must use a reviewable inline needs list")
        dependencies = {item.strip() for item in match.group(1).split(",")}
        self.assertEqual(dependencies, jobs - {"release-gate"})
        self.assertIn("    name: release gate\n", text)
        self.assertIn("    if: ${{ always() }}\n", text)

    def test_maintenance_publish_has_no_unverified_path(self):
        text = (ROOT / '.github/workflows/publish.yml').read_text(encoding='utf-8')
        self.assertIn('types: [published]', text)
        self.assertNotIn('workflow_dispatch:', text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertIn('needs: [build, test-wheel, test-sdist, dependency-audit]', text)
        self.assertEqual(text.count('verify-governance --commit'), 2)
        for guard in ('verify-source', 'verify-manifest', 'download-pypi',
                      'skip-existing: false', 'attestations: true',
                      'subject-checksums: dist/SHA256SUMS', 'environment: pypi',
                      'refs/heads/release/0.9.x:refs/remotes/origin/release/0.9.x'):
            self.assertIn(guard, text)
        self.assertNotIn('continue-on-error', text)
        ci = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
        self.assertIn('branches: [main, release/0.9.x]', ci)


if __name__ == "__main__":
    unittest.main()
