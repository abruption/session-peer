"""Structural contracts for release-critical GitHub Actions workflows."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
ACTION_REF = re.compile(r"^\s*(?:-\s+)?uses: ([^\s#]+)", re.MULTILINE)
FULL_SHA = re.compile(r"[0-9a-f]{40}")
JOB = re.compile(r"^  ([a-z][a-z0-9-]*):\s*$", re.MULTILINE)


class ReleaseWorkflows(unittest.TestCase):
    def test_every_third_party_action_is_commit_pinned(self):
        for workflow in sorted((ROOT / ".github/workflows").glob("*.yml")):
            relative = workflow.relative_to(ROOT)
            text = workflow.read_text(encoding="utf-8")
            refs = ACTION_REF.findall(text)
            self.assertTrue(refs, relative)
            for action in refs:
                if action.startswith("./"):
                    continue
                ref = action.partition("@")[2]
                self.assertIsNotNone(
                    FULL_SHA.fullmatch(ref), f"{relative}: unpinned action {action}"
                )

    def test_assets_are_attested_on_main_and_attached_before_publication(self):
        prepare = (ROOT / ".github/workflows/prepare-release.yml").read_text()
        publish = (ROOT / ".github/workflows/publish.yml").read_text()
        self.assertIn("workflow_dispatch:", prepare)
        self.assertIn("github.ref == 'refs/heads/main'", prepare)
        self.assertIn("github.actor == github.repository_owner", prepare)
        self.assertIn("--expected-sha", prepare)
        self.assertIn("subject-path: 'dist/*'", prepare)
        self.assertIn("release['draft'] is True", prepare)
        self.assertIn("release['assets'] == []", prepare)
        self.assertIn('gh release upload "$RELEASE_TAG" dist/*', prepare)
        self.assertNotIn("--draft=false", prepare)
        self.assertIn("github.event.release.immutable == true", publish)
        self.assertIn("download_release.py", publish)
        self.assertNotIn("python -m build", publish)
        self.assertNotIn("gh release upload", publish)

    def test_action_ref_detection_includes_named_and_unpinned_steps(self):
        text = """      - uses: actions/checkout@main
      - name: Upload evidence
        uses: actions/upload-artifact
      - uses: ./local-action
"""
        self.assertEqual(
            ["actions/checkout@main", "actions/upload-artifact", "./local-action"],
            ACTION_REF.findall(text),
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
