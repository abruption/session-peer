"""Structural contracts for release-critical GitHub Actions workflows."""

from pathlib import Path
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
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
        self.assertIn('"$GITHUB_REF" != refs/heads/main', prepare)
        self.assertIn('"$GITHUB_ACTOR" != "$GITHUB_REPOSITORY_OWNER"', prepare)
        self.assertIn("group: prepare-release-${{ inputs.tag }}", prepare)
        self.assertIn("cancel-in-progress: false", prepare)
        self.assertIn("--expected-sha", prepare)
        self.assertIn("subject-path: 'dist/*'", prepare)
        self.assertIn("release.get('isDraft') is True", prepare)
        self.assertIn("release.get('assets') == []", prepare)
        self.assertIn('gh release view "$RELEASE_TAG"', prepare)
        self.assertIn("--json isDraft,isPrerelease,tagName,targetCommitish,assets", prepare)
        self.assertNotIn('gh api "repos/$GITHUB_REPOSITORY/releases/tags/$RELEASE_TAG"', prepare)
        self.assertIn('gh release upload "$RELEASE_TAG" dist/*', prepare)
        self.assertNotIn("--draft=false", prepare)
        self.assertNotIn("    if: ${{ github.repository", publish)
        self.assertIn("Require owner publication (fail rather than silently skip)", publish)
        self.assertIn("exit 1", publish.split("  test-wheel:")[0])
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

    def test_both_prepare_and_publication_keep_dependency_audit_gates(self):
        for name, consumer in (("prepare-release.yml", "attach-draft"), ("publish.yml", "publish")):
            text = (ROOT / ".github/workflows" / name).read_text()
            self.assertIn("python -m pip_audit --path", text)
            self.assertIn("npm audit --omit=dev", text)
            block = re.split(r"\n  [a-z][a-z0-9-]*:\n", text.split("\n  " + consumer + ":", 1)[1], maxsplit=1)[0]
            self.assertIn("dependency-audit", block)

    def test_draft_guard_requires_view_metadata_empty_assets_and_exact_sha(self):
        text = (ROOT / ".github/workflows/prepare-release.yml").read_text()
        code = textwrap.dedent(text.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0])
        base = {"isDraft": True, "isPrerelease": False, "tagName": "v1.2.3",
                "targetCommitish": "a" * 40, "assets": []}
        cases = [({}, True), ({"isPrerelease": True}, True), ({"isDraft": False}, False),
                 ({"tagName": "v1.2.4"}, False), ({"targetCommitish": "main"}, False),
                 ({"targetCommitish": "b" * 40}, False), ({"assets": [{}]}, False), ({"assets": None}, False)]
        for change, success in cases:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                (Path(temporary) / "draft.json").write_text(json.dumps({**base, **change}))
                env = {**os.environ, "RELEASE_TAG": "v1.2.3", "GITHUB_SHA": "a" * 40}
                # Security validation must remain active even with assertions disabled.
                done = subprocess.run([sys.executable, "-O", "-c", code], cwd=temporary,
                                      env=env, capture_output=True, text=True)
                self.assertEqual(done.returncode == 0, success, done.stderr)

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
