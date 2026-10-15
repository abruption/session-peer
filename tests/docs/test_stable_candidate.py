"""Stable version and publication boundary agree across package and docs."""

from pathlib import Path
import unittest

import session_peer


ROOT = Path(__file__).resolve().parents[2]


class StableCandidate(unittest.TestCase):
    def test_v120_candidate_keeps_proposed_scope_and_open_gates(self):
        profiles = (
            ("", "The 26 regression tests include unsupported API cases",
             "Merge the release-preparation PR last", "not publishable release assets"),
            ("ko/", "회귀 테스트 26개에는 미지원 API 사례",
             "릴리스 준비 PR은 범위 내 PR 6개를 모두 병합한 뒤 마지막으로 병합",
             "게시할 릴리스 자산이 아닙니다"),
            ("ja/", "26件の回帰テストには未対応API例",
             "リリース準備PRは対象6件のPRをすべてマージした後、最後にマージ",
             "公開用リリース資産ではありません"),
            ("zh-CN/", "26项回归测试包括不支持API的情况",
             "发布准备PR必须在范围内全部6项PR合并后最后合并",
             "不是可发布的版本资产"),
        )
        for locale, regression_scope, merge_order, artifact_boundary in profiles:
            text = (ROOT / ("docs/" + locale + "releases/v1.2.0.md")).read_text(encoding="utf-8")
            for marker in ("1.1.2", "1.2.0", "2026-10-15", "2026-10-18",
                           "#305", "#308", "#310", "#311", "#313", "#314",
                           "#180", "#181", "#268", "#304", "#306", "#307",
                           regression_scope, merge_order, artifact_boundary,
                           "20/21", "#161", "pypi", "Control/Relay"):
                self.assertIn(marker, text)
            suffix = "." + locale.rstrip("/") if locale else ""
            runbook = (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8")
            self.assertIn(merge_order, runbook)
            self.assertIn(artifact_boundary, runbook)
        english = (ROOT / "docs/releases/v1.2.0.md").read_text(encoding="utf-8")
        for marker in ("candidate is unpublished", "not effective-storage attestation",
                       "unmaterialized empty TUIs may be refused", "remain open",
                       "not proof of general first-input support",
                       "required human pypi environment approval",
                       "review its final head", "historical approvals do not authorize v1.2.0",
                       "final protected-main CI", "rebuild and verify release assets",
                       "At publication time", "actual publication evidence"):
            self.assertIn(marker, english)

    def test_historical_pid_patch_preparation_remains_narrow(self):
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            note = (ROOT / ("docs/" + locale + "releases/v1.1.2.md")).read_text(encoding="utf-8")
            for marker in ("#298", "1.1.1", "1.1.2", "2026-10-13", "²",
                           "Control/Relay", "20/21", "#161", "handoff-runtime.md"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, note)
        english = (ROOT / "docs/releases/v1.1.2.md").read_text(encoding="utf-8")
        self.assertIn("candidate is unpublished", english)
        self.assertIn("preparation does not authorize merge", english)
        self.assertIn("Package publication does not include operational deployment", english)

    def test_maintenance_notes_do_not_claim_runtime_remediation(self):
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            note = (ROOT / ("docs/" + locale + "releases/v1.1.1.md")).read_text(encoding="utf-8")
            for marker in ("#297", "#281", "#299", "#298", "Paramiko 5.0.0",
                           "OpenSSH", "2026-10-12", "1.1.0", "20/21", "#161",
                           "handoff-runtime.md", "Control/Relay",
                           "https://github.com/abruption/session-peer/releases/tag/v1.1.1",
                           "https://pypi.org/pypi/session-peer/1.1.1/json"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, note)
        english = (ROOT / "docs/releases/v1.1.1.md").read_text(encoding="utf-8")
        self.assertIn("runtime behavior is unchanged", english)
        self.assertIn("This patch does not fix that runtime defect", english)
        self.assertIn("Paramiko is not a shipped runtime dependency", english)
        self.assertIn("Package publication does not include operational deployment", english)

    def test_documentation_maps_keep_published_and_historical_status_distinct(self):
        profiles = (
            ("", "Experimental handoff runtime", "remaining acceptance gates",
             "published 1.1.0 evidence", "prior maintenance release"),
            ("ko/", "실험적 Handoff 런타임", "남은 수락 조건",
             "공개된 1.1.0 증거", "이전 유지보수 릴리스"),
            ("ja/", "実験的なHandoffランタイム", "残る受け入れ条件",
             "公開済み1.1.0の証拠", "以前のメンテナンス版"),
            ("zh-CN/", "实验性Handoff运行时", "剩余验收条件",
             "已发布1.1.0的证据", "先前维护版本"),
        )
        for locale, handoff_label, gates, stable, historical in profiles:
            text = (ROOT / ("docs/" + locale + "README.md")).read_text(encoding="utf-8")
            with self.subTest(locale=locale or "en"):
                handoff = next(line for line in text.splitlines() if "(handoff-runtime.md)" in line)
                current = next(line for line in text.splitlines() if "(releases/v1.1.0.md)" in line)
                previous = next(line for line in text.splitlines() if "(releases/v1.0.4.md)" in line)
                self.assertIn(handoff_label, handoff)
                self.assertIn("1.1.0", handoff)
                self.assertIn(gates, handoff)
                self.assertIn(stable, current)
                maintenance = next(line for line in text.splitlines()
                                   if "(releases/v1.1.1.md)" in line)
                self.assertIn("2026-10-12", maintenance)
                self.assertIn("1.1.0", maintenance)
                self.assertIn(historical, previous)
                self.assertIn("2026-10-07", previous)
                self.assertIn("releases/v1.0.3.md", previous)
                self.assertIn("validation/69-rc.md", previous)

    def test_published_guides_share_exact_source_and_publication_evidence(self):
        source = "8ca77cf31254c8287a2593fe484bb30a7dba2727"
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            note = (ROOT / ("docs/" + locale + "releases/v1.1.0.md")).read_text(encoding="utf-8")
            for marker in (source, "06:46:41 UTC", "08:04:35", "08:04:37 UTC",
                           "https://github.com/abruption/session-peer/releases/tag/v1.1.0",
                           "https://pypi.org/pypi/session-peer/1.1.0/json"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, note)
            guide = (ROOT / ("docs/" + locale + "handoff-runtime.md")).read_text(encoding="utf-8")
            self.assertIn("Python v1.1.0", guide)
            self.assertIn("#181", guide)
            self.assertIn("2026-10-09", guide)
            self.assertNotIn("Python v1.0.4", guide)

    def test_completed_release_examples_are_explicitly_historical(self):
        warning = "# Historical v1.1.0 example: do not rerun or reuse this version."
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            text = (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8")
            with self.subTest(locale=suffix or "en"):
                self.assertIn("8ca77cf31254c8287a2593fe484bb30a7dba2727", text)
                self.assertEqual(2, text.count(warning))
                self.assertIn(warning + "\ngit fetch origin main --tags", text)
                self.assertIn(warning + "\ngh release edit v1.1.0", text)
                self.assertIn("state_db_missing", text)
                self.assertIn("POSIX", text)

    def test_published_release_keeps_experimental_acceptance_gates(self):
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            text = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            self.assertIn("**1.1.2**", text)
            self.assertIn("releases/v1.1.2.md", text)
            self.assertIn("handoff-runtime.md", text)
            self.assertIn("POSIX", text)
            self.assertNotIn("**1.0.4**", text)
            self.assertIn('<div align="center">', text)
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            text = (ROOT / ("docs/" + locale + "releases/v1.1.0.md")).read_text(encoding="utf-8")
            for marker in ("#261", "#283–#290", "#242", "#268", "#232", "#180", "#183",
                           "#238", "#211", "#181", "#30", "1.0.4", "1.1.0", "0.154.0",
                           "0.3.2", "0.9.1", "1.0.1", "32 KiB", "64 KiB", "256 KiB",
                           "1 MiB", "131,071", "90,000", "20/21", "#161"):
                with self.subTest(locale=locale, marker=marker):
                    self.assertIn(marker, text)
        english = (ROOT / "docs/releases/v1.1.0.md").read_text(encoding="utf-8")
        for marker in ("Published on 2026-10-09", "correlation-only", "unsupported", "receipt",
                       "Package publication does not include operational deployment"):
            self.assertIn(marker, english)

    def test_package_and_generated_core_version_agree(self):
        self.assertEqual(session_peer.__version__, "1.2.0")
        self.assertIn('__version__ = "1.2.0"',
                      (ROOT / "session_peer_core/common.py").read_text(encoding="utf-8"))

    def test_all_current_readmes_and_runbooks_use_stable_version(self):
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            for stem in ("README", "RELEASING"):
                with self.subTest(stem=stem, suffix=suffix):
                    text = (ROOT / (stem + suffix + ".md")).read_text(encoding="utf-8")
                    self.assertIn("1.1.2", text)
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
        self.assertIn("Version covered by this README: **1.1.2**.",
                      (ROOT / "README.md").read_text(encoding="utf-8"))
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            text = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            self.assertIn("**1.1.2**", text)
            self.assertNotIn("**1.0.3**", text)
            self.assertIn("1.2.0", text)
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
