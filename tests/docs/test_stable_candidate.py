"""Stable version and publication boundary agree across package and docs."""

from pathlib import Path
import re
import unittest

import session_peer


ROOT = Path(__file__).resolve().parents[2]


class StableCandidate(unittest.TestCase):
    def test_v121_preparation_records_patch_sources_and_publication_gates(self):
        notes = [(ROOT / ("docs/" + locale + "releases/v1.2.1.md")).read_text(encoding="utf-8")
                 for locale in ("", "ko/", "ja/", "zh-CN/")]
        source_base = "32e76d2c85d945d66466f630d9729ec0be5288d8"
        expected_pairs = ((319, 317, "ba00540e24e4e378c002c11e7cbeb23b85003b9f"),
                          (320, 318, "c5625a1667de50b2684067febed1772ed693eca7"),
                          (303, 302, source_base))
        locale_boundaries = {
            "": ("unknown never permits automatic resend",
                 "does not authorize its own merge, tag/draft creation, workflow dispatch, publication or deployment"),
            "ko/": ("unknown은 자동 재전송을 허용하지 않습니다",
                    "준비 PR 자체의 병합, 태그·초안 생성, 워크플로 실행 요청, 공개·배포를 승인하지 않습니다"),
            "ja/": ("unknownは自動再送を許可しません",
                    "この準備自身のマージ、タグ・ドラフト作成、ワークフロー実行、公開・配備も承認しません"),
            "zh-CN/": ("unknown不允许自动重发",
                       "也不授权准备自身合并、创建标签/草稿、派发工作流、发布或部署"),
        }
        for locale, text in zip(("", "ko/", "ja/", "zh-CN/"), notes):
            with self.subTest(locale=locale):
                self.assertNotIn("PENDING", text)
                positions = []
                for pr, issue, expected_sha in expected_pairs:
                    row = re.search(r"\| #%d \| #%d \| `([0-9a-f]{40})` \|" % (pr, issue), text)
                    self.assertIsNotNone(row)
                    positions.append(row.start())
                    self.assertEqual(expected_sha, row.group(1))
                self.assertEqual(positions, sorted(positions))
                self.assertIn(source_base, text)
                suffix = "." + locale.rstrip("/") if locale else ""
                self.assertIn(source_base, (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8"))
                for marker in ("1.2.1", "1.2.0", "2026-10-19", "macOS", "Windows/Linux",
                               "CLAUDE_CONFIG_DIR", "ANTHROPIC_CONFIG_DIR", "16 KiB", "UTF-8",
                               "0.3.3", "0.9.1", "1.0.1", "#316", "#161", "20/21",
                               "#321", "#322", "HUP/INT/TERM", "SIGKILL",
                               "#180", "#181", "#268", "#304", "#306", "#307", "Control/Relay",
                               "pypi", "attach-draft", "SHA256SUMS", "release-provenance.json",
                               "ad4aa0e464fb142424f6fb6a30303bb88e47163e",
                               "4cd202af4b6a2f0b5e7daa1e7f9d960eb7a67217", "generationStatus=available",
                               "eb239fb358336d85b49bab2c80e4ea39037d1374",
                               "15378c6d503a69d1d738ac4739182e23257aa6f2f7fd31ef3fd2fa60e692867f"):
                    self.assertIn(marker, text)
                for marker in locale_boundaries[locale]:
                    self.assertIn(marker, text)
                self.assertNotIn("```", text)
        for marker in ("not a publication announcement", "No YAML or skill instructions are executed",
                       "refuses all target selection", "ordinary socket aliases remain supported",
                       "not publishable release assets", "required human pypi environment approval",
                       "not a reservation", "no executable release commands",
                       "does not authorize its own merge", "never rebuild or replace immutable assets",
                       "not the proven cause of the original CI failure", "only the allocation child",
                       "no-automatic-retry contract are unchanged", "not a universal cancellation deadline"):
            self.assertIn(marker, notes[0])

    def test_v120_publication_addendum_does_not_erase_candidate_history(self):
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            text = (ROOT / ("docs/" + locale + "releases/v1.2.0.md")).read_text(encoding="utf-8")
            for marker in ("2026-10-19", "2026-10-16", "12:39:13 UTC", "12:41:38.903354 UTC",
                           "12:41:40.537212 UTC", "4fc526f36afc65bb6ec460439eb0986c09ecc8ee",
                           "https://github.com/abruption/session-peer/releases/tag/v1.2.0",
                           "https://pypi.org/pypi/session-peer/1.2.0/json", "#315", "2026-10-15"):
                self.assertIn(marker, text)
        english = (ROOT / "docs/releases/v1.2.0.md").read_text(encoding="utf-8")
        self.assertIn("historical preparation snapshot", english)
        self.assertIn("not current status", english)
        self.assertIn("candidate is unpublished", english)

    def test_v120_candidate_records_merged_scope_and_open_gates(self):
        source_base = "21a0be0c0c5bcb8bca214d90a873b7479d7ba97a"
        merged_prs = (
            (305, "3392c561e8b8b3221c8c5fcad6077cad8f7becd8"),
            (311, "57c42d4a97b351de41a6180b7a05a0ec018d0c4c"),
            (310, "10a6da72b8b94f08b6b3b2ff70f581aadf548279"),
            (308, "b04e46c4e641fd0defab72b96c26d0612d0d6a5e"),
            (313, "9c625bebb21dec2519214889fc60cc3f362142c1"),
            (314, source_base),
        )
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
            for marker in ("1.1.2", "1.2.0", "2026-10-15", "2026-10-16", "2026-10-18",
                           "#305", "#308", "#310", "#311", "#313", "#314", "#315", source_base,
                           "#180", "#181", "#268", "#304", "#306", "#307",
                           regression_scope, merge_order, artifact_boundary,
                           "20/21", "#161", "#316", "pypi", "Control/Relay"):
                self.assertIn(marker, text)
            merge_rows = ["| #%d | `%s` |" % pair for pair in merged_prs]
            positions = [text.index(row) for row in merge_rows]
            self.assertEqual(positions, sorted(positions))
            suffix = "." + locale.rstrip("/") if locale else ""
            runbook = (ROOT / ("RELEASING" + suffix + ".md")).read_text(encoding="utf-8")
            self.assertIn(merge_order, runbook)
            self.assertIn(artifact_boundary, runbook)
            self.assertIn(source_base, runbook)
            self.assertIn("#315", runbook)
            neutral_freeze, immutable_metadata, diagnostic = {
                "": ("publication-neutral wording", "never rebuild or replace immutable assets",
                     "transport-creation and shutdown diagnostics"),
                "ko/": ("공개 여부와 무관하게 정확한 문구", "불변 자산을 다시 빌드하거나 교체하지",
                        "transport 생성·종료 진단"),
                "ja/": ("公開の前後によらず正確な表現", "不変資産を再ビルド・置換せず",
                        "transport生成・終了診断"),
                "zh-CN/": ("发布前后均准确的表述", "重新构建或替换不可变资产",
                           "transport创建及关闭诊断"),
            }[locale]
            for marker in (neutral_freeze, immutable_metadata, diagnostic,
                           "SHA256SUMS", "release-provenance.json"):
                self.assertIn(marker, text)
                self.assertIn(marker, runbook)
        english = (ROOT / "docs/releases/v1.2.0.md").read_text(encoding="utf-8")
        for marker in ("candidate is unpublished", "The six scoped PRs are merged",
                       "PR #315 remains open", "not the final release-preparation or publication commit",
                       "3-second timeout", "up to 2 seconds", "not effective-storage attestation",
                       "unmaterialized empty TUIs may be refused", "remain open",
                       "not proof of general first-input support",
                       "required human pypi environment approval",
                       "review its final head", "historical approvals do not authorize v1.2.0",
                       "final protected-main CI", "rebuild and verify release assets",
                       "At publication time", "actual publication evidence"):
            self.assertIn(marker, english)
        self.assertNotIn("## Proposed changes", english)
        runbook = (ROOT / "RELEASING.md").read_text(encoding="utf-8")
        self.assertIn("not recorded as verified", runbook)
        self.assertNotIn("six unmerged feature branches", runbook)

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
            self.assertIn("**1.2.0**", text)
            self.assertIn("releases/v1.2.0.md", text)
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
        self.assertEqual(session_peer.__version__, "1.2.1")
        self.assertIn('__version__ = "1.2.1"',
                      (ROOT / "session_peer_core/common.py").read_text(encoding="utf-8"))

    def test_all_current_readmes_and_runbooks_use_stable_version(self):
        for suffix in ("", ".ko", ".ja", ".zh-CN"):
            for stem in ("README", "RELEASING"):
                with self.subTest(stem=stem, suffix=suffix):
                    text = (ROOT / (stem + suffix + ".md")).read_text(encoding="utf-8")
                    self.assertIn("1.2.0", text)
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
        profiles = (
            ("", "Source version: **1.2.1**.",
             "At the 2026-10-19 publication checkpoint, the last verified published stable release was **1.2.0**.",
             "Development candidate 1.2.1 is unpublished"),
            (".ko", "소스 버전: **1.2.1**.",
             "2026-10-19 공개 상태 확인 시점의 마지막 확인 공개 안정판은 **1.2.0**이었습니다.",
             "개발 후보 1.2.1은 미공개입니다"),
            (".ja", "ソースバージョン：**1.2.1**。",
             "2026-10-19の公開状況の確認時点で、最後に確認した公開済み安定版は**1.2.0**でした。",
             "開発候補1.2.1は未公開です"),
            (".zh-CN", "源码版本：**1.2.1**。",
             "在2026-10-19的发布状态检查时，最后确认的已发布稳定版本为**1.2.0**。",
             "开发候选版本1.2.1尚未发布"),
        )
        for suffix, source_version, dated_checkpoint, stale_unpublished in profiles:
            text = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            self.assertIn(source_version, text)
            self.assertIn(dated_checkpoint, text)
            for stale_version in ("1.2.0", "1.2.1"):
                self.assertNotIn(stale_unpublished.replace("1.2.1", stale_version), text)
            self.assertIn("https://github.com/abruption/session-peer/releases", text)
            self.assertIn("https://pypi.org/project/session-peer/", text)
            self.assertNotIn("**1.0.3**", text)
        for locale, merged_scope, stale_scope in (
                ("", "the merged six-PR scope", "the proposed six-PR scope"),
                ("ko/", "병합된 PR 6개 범위", "제안한 PR 6개 범위"),
                ("ja/", "マージ済み6件のPRの範囲", "提案する6件のPRの範囲"),
                ("zh-CN/", "已合并的6项PR范围", "拟议的6项PR范围")):
            text = (ROOT / ("docs/" + locale + "README.md")).read_text(encoding="utf-8")
            self.assertIn("releases/v1.0.3.md", text)
            self.assertIn("releases/v1.0.4.md", text)
            self.assertIn(merged_scope, text)
            self.assertNotIn(stale_scope, text)
            self.assertIn("2026-10-16", text)
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
