"""Structural contracts for release-critical GitHub Actions workflows."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
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


if __name__ == "__main__":
    unittest.main()
