"""Keep the README a compact, multilingual entry point with safe first steps."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
LAYOUTS = {
    "": ("Demo", "Quick Start", "Install", "Update", "Docs", "License", "Support and security"),
    ".ko": ("데모", "빠른 시작", "설치", "업데이트", "문서", "라이선스", "지원 및 보안"),
    ".ja": ("デモ", "クイックスタート", "インストール", "更新", "ドキュメント", "ライセンス", "サポートとセキュリティ"),
    ".zh-CN": ("演示", "快速开始", "安装", "更新", "文档", "许可证", "支持与安全"),
}


class ReadmeLayoutTest(unittest.TestCase):
    def test_requested_section_order_in_every_locale(self):
        for suffix, titles in LAYOUTS.items():
            text = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            expected = list(zip((2, 2, 3, 3, 2, 2, 2), titles))
            headings = [(len(level), title) for level, title in re.findall(r"^(#{2,}) (.+)$", text, re.MULTILINE)]
            with self.subTest(locale=suffix or "en"):
                positions = []
                for heading in expected:
                    self.assertEqual(1, headings.count(heading), heading)
                    positions.append(headings.index(heading))
                self.assertEqual(sorted(positions), positions)
                for position in positions[2:4]:
                    parent = next(title for level, title in reversed(headings[:position]) if level == 2)
                    self.assertEqual(titles[1], parent)

    def test_entry_points_and_safety_markers_remain_visible(self):
        for suffix in LAYOUTS:
            text = (ROOT / ("README" + suffix + ".md")).read_text(encoding="utf-8")
            with self.subTest(locale=suffix or "en"):
                for marker in (
                    "docs/assets/session-peer-live-codex-claude.gif",
                    '<a id="installation-options"></a>',
                    '<a id="see-it-in-action"></a>',
                    '<a id="documentation"></a>',
                    "pipx install session-peer",
                    "pipx upgrade session-peer",
                    "session-peer list",
                    "session-peer update",
                    "3.9",
                    "3.10",
                    "3.11",
                    "SECURITY",
                    "--dry-run",
                    "--codex-home",
                    "`posted` / `queued`",
                    "ACK",
                    "session-peer[relay]",
                    "session-peer[mcp]",
                    "https://github.com/abruption/session-peer-skill",
                    "https://github.com/abruption/session-peer/security/advisories/new",
                    "mailto:support@abruption.dev",
                ):
                    self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
