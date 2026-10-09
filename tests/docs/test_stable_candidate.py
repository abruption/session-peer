"""Stable version and publication boundary agree across package and docs."""

from pathlib import Path
import unittest

import session_peer


ROOT = Path(__file__).resolve().parents[2]


class StableCandidate(unittest.TestCase):
    def test_candidate_is_not_advertised_as_published_or_fully_supported(self):
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            text = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            self.assertIn("**1.0.4**", text)
            self.assertIn("**1.1.0**", text)
            self.assertIn('<div align="center">', text)
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            text = (ROOT / ("docs/" + locale + "releases/v1.1.0.md")).read_text(encoding="utf-8")
            for marker in ("#261", "#283–#289", "#290", "#242", "#268", "#232", "#180", "#183",
                           "#238", "#211", "#181", "#30", "1.0.4", "1.1.0", "0.154.0",
                           "0.3.2", "0.9.1", "1.0.1", "32 KiB", "64 KiB", "256 KiB",
                           "1 MiB", "131,071", "90,000", "20/21", "#161"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, text)
        english = (ROOT / "docs/releases/v1.1.0.md").read_text(encoding="utf-8")
        for marker in ("not published", "correlation-only", "unsupported", "receipt",
                       "Package publication does not include operational deployment"):
            self.assertIn(marker, english)

    def test_package_and_generated_core_version_agree(self):
        self.assertEqual(session_peer.__version__, "1.1.0")
        self.assertIn('__version__ = "1.1.0"',
                      (ROOT / "session_peer_core/common.py").read_text(encoding="utf-8"))

    def test_all_current_readmes_and_runbooks_use_stable_version(self):
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            for stem in ("README", "RELEASING"):
                with self.subTest(stem=stem, suffix=suffix):
                    text = (ROOT / (stem + suffix + ".md")).read_text(encoding="utf-8")
                    self.assertIn("1.0.4", text)
                    self.assertNotIn("1.0.0rc4", text)
                    if stem == "RELEASING":
                        self.assertIn("--draft=false --prerelease=false --latest", text)
                        self.assertIn("20/21", text)
                        self.assertIn("#161", text)
                        for marker in ("prepare-release.yml", "publish.yml", "SHA256SUMS",
                                       "release-provenance.json", "Review deployments",
                                       "Approve and deploy", "Reject"):
                            self.assertIn(marker, text)

    def test_release_notes_keep_scope_and_limits_visible(self):
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            text = (ROOT / ("docs/" + locale + "releases/v1.0.4.md")).read_text(encoding="utf-8")
            for marker in ("#262", "#263", "#264", "#265", "#266", "#267",
                           "1.0.4", "1.0.3", "0.3.2", "0.9.1", "1.0.1", "2026-10-07",
                           "32 KiB", "64 KiB", "256 KiB", "1 MiB",
                           "outcome_unknown", "retryAllowed: false", "20/21", "#161"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, text)

    def test_stable_release_keeps_operational_deployment_separate(self):
        self.assertIn("Current stable release: **1.0.4**.",
                      (ROOT / "README.md").read_text(encoding="utf-8"))
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            text = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            self.assertIn("**1.0.4**", text)
            self.assertNotIn("**1.0.3**", text)
            self.assertIn("2026-10-07", text)
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            text = (ROOT / ("docs/" + locale + "README.md")).read_text(encoding="utf-8")
            self.assertIn("releases/v1.0.3.md", text)
            self.assertIn("releases/v1.0.4.md", text)
        self.assertIn("Package publication and operational deployment are separate.",
                      (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("Package publication does not include operational deployment",
                      (ROOT / "docs/releases/v1.0.4.md").read_text(encoding="utf-8"))

    def test_historical_security_notes_keep_validation_and_limits_visible(self):
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            text = (ROOT / ("docs/" + locale + "releases/v1.0.3.md")).read_text(encoding="utf-8")
            for marker in ("#161", "#249", "#250", "#251", "#252", "#253", "#254",
                           "#255", "#256", "#257", "#258", "1.0.3", "ACK", "20/21",
                           "GHSA-9x52-82cv-4c22", "GHSA-4rvw-q2vm-v4x3",
                           "GHSA-6xwm-5p7g-8v8q", "GHSA-2hjv-35jg-gghm",
                           "GHSA-646x-xjw9-mf6x", "CVE", "ProxyCommand", "LocalCommand"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
