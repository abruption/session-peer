"""The candidate version and opt-in upgrade boundary must agree across docs."""
from pathlib import Path
import unittest

import session_peer


ROOT = Path(__file__).resolve().parents[2]


class RC2Candidate(unittest.TestCase):
    def test_package_and_generated_core_version_agree(self):
        self.assertEqual(session_peer.__version__, "1.0.0rc2")
        self.assertIn('__version__ = "1.0.0rc2"',
                      (ROOT / "session_peer_core/common.py").read_text(encoding="utf-8"))

    def test_all_current_readmes_and_runbooks_use_rc2(self):
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            for stem in ("README", "RELEASING"):
                with self.subTest(stem=stem, suffix=suffix):
                    text = (ROOT / (stem + suffix + ".md")).read_text(encoding="utf-8")
                    self.assertIn("1.0.0rc2", text)
                    self.assertNotIn("1.0.0rc1", text)
                    if stem == "RELEASING":
                        self.assertIn("--prerelease --latest=false", text)
                        self.assertIn("v0.9.2", text)
                        self.assertIn("#158", text)

    def test_release_notes_keep_migration_and_pending_evidence_visible(self):
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            text = (ROOT / ("docs/" + locale + "releases/v1.0.0-rc.2.md")).read_text(encoding="utf-8")
            for marker in ("#150", "#151", "#153", "#156", "#157", "#158",
                           "codexPython", "consumptionConfirmed: false", "v0.9.2",
                           "T0/T2h/T4h", "1.0.0rc2", "v1.0.0-rc.2"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
