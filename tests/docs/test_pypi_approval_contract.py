"""Source contracts only; the next release must still prove the approval pause."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
JOB = re.compile(r"^  ([a-z][a-z0-9-]*):\s*$", re.MULTILINE)


def workflow_jobs(text):
    jobs_text = text.split("\njobs:\n", 1)[1]
    boundaries = list(JOB.finditer(jobs_text))
    return {
        match.group(1): jobs_text[
            match.end(): boundaries[index + 1].start()
            if index + 1 < len(boundaries) else len(jobs_text)
        ]
        for index, match in enumerate(boundaries)
    }


class PyPIApprovalContract(unittest.TestCase):
    def test_upload_is_in_pypi_environment_after_candidate_checks(self):
        jobs = workflow_jobs(
            (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
        )
        publishers = [
            name for name, body in jobs.items()
            if "uses: pypa/gh-action-pypi-publish@" in body
        ]
        self.assertEqual(["publish"], publishers)
        publish = jobs["publish"]
        self.assertRegex(publish, r"(?m)^    environment: pypi$")
        self.assertRegex(publish, r"(?m)^      id-token: write$")
        dependencies = re.search(r"(?m)^    needs: \[([^]]+)\]$", publish)
        self.assertIsNotNone(dependencies)
        self.assertTrue(
            {"build", "test-wheel", "test-sdist", "dependency-audit"}
            <= {name.strip() for name in dependencies.group(1).split(",")}
        )
        self.assertNotRegex(publish, r"(?m)^    if:.*(?:always\(\)|cancelled\(\))")
        self.assertRegex(publish, r"(?m)^          skip-existing: false$")

    def test_all_release_guides_preserve_review_actions_and_evidence(self):
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            with self.subTest(language=suffix or "en"):
                text = (ROOT / ("RELEASING" + suffix + ".md")).read_text(
                    encoding="utf-8"
                )
                for required in (
                    "**Review deployments**", "**Approve and deploy**", "**Reject**",
                    "`prevent_self_review: false`", "`can_admins_bypass: true`",
                    "`abruption`", "`v*`", "2026-09-29", "2026-10-03",
                    "https://github.com/abruption/session-peer/issues/235#issuecomment-5882178667",
                    "release-provenance.json", "SHA256SUMS", "#235",
                ):
                    self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
