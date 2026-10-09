"""Run SSH identity examples against a shell function, never a real client."""
import os
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name == "posix", "POSIX documented shell examples")
class SshIdentityCommands(unittest.TestCase):
    def test_all_locales_preserve_send_argument_boundaries(self):
        expected = ["send", "--host", "workstation", "--to", "reviewer",
                    "--message=Review this change", "--require-ssh-host-key",
                    "SHA256:<previously-verified-fingerprint>", "--json"]
        for locale in ("", "ko/", "ja/", "zh-CN/"):
            with self.subTest(locale=locale or "en"):
                source = (ROOT / "docs" / locale / "cli-reference.md").read_text(encoding="utf-8")
                example = re.search(r"^session-peer send --host workstation.*?\n```", source,
                                    re.MULTILINE | re.DOTALL)
                self.assertIsNotNone(example)
                # POSIX function identifiers cannot contain a hyphen. Replace
                # only the command word; shell argument/continuation syntax is
                # still executed exactly as documented, with no client access.
                block = example.group(0).removesuffix("```").replace("session-peer ", "capture ", 1)
                harness = 'capture() { printf "%s\\n" "$@"; }\n'
                result = subprocess.run(["/bin/sh", "-c", harness + block],
                                        capture_output=True, text=True,
                                        env={"PATH": os.defpath})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected)


if __name__ == "__main__":
    unittest.main()
