"""Isolated standalone installation and coexistence checks; no real HOME writes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipIf(os.name == "nt", "POSIX installer; Windows uses pip")
class Install(unittest.TestCase):
    def test_install_reinstall_and_remove_preserve_legacy(self):
        with tempfile.TemporaryDirectory(prefix="session-peer-test-") as directory:
            root = Path(directory)
            legacy = root / ".claude/skills/cc-peer/cc_peer.py"
            legacy.parent.mkdir(parents=True)
            legacy.write_text("legacy", encoding="utf-8")
            env = dict(os.environ, HOME=str(root), CLAUDE_CONFIG_DIR=str(root / "custom claude"))
            script = str(Path(__file__).parents[2] / "install.sh")
            for _ in range(2):
                result = subprocess.run(["sh", script], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue((root / ".local/bin/session-peer").is_symlink())
                self.assertTrue((root / ".local/share/session-peer/session_peer.py").is_file())
                self.assertTrue((root / "custom claude/skills/session-peer/SKILL.md").is_file())
                self.assertTrue((root / ".agents/skills/session-peer/SKILL.md").is_file())
            result = subprocess.run(["sh", script, "--uninstall"], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / ".local/bin/session-peer").exists())
            self.assertFalse((root / ".local/share/session-peer").exists())
            self.assertFalse((root / "custom claude/skills/session-peer").exists())
            self.assertFalse((root / ".agents/skills/session-peer").exists())
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy")

    def test_separately_managed_skills_and_claude_symlink_survive(self):
        with tempfile.TemporaryDirectory(prefix="session-peer-test-") as directory:
            root = Path(directory)
            codex_skill = root / ".agents/skills/session-peer"
            codex_skill.mkdir(parents=True)
            (codex_skill / "SKILL.md").write_text("independent skill", encoding="utf-8")
            claude_skills = root / ".claude/skills"
            claude_skills.mkdir(parents=True)
            (claude_skills / "session-peer").symlink_to(codex_skill, target_is_directory=True)
            env = dict(os.environ, HOME=str(root))
            env.pop("CLAUDE_CONFIG_DIR", None)
            env.pop("ANTHROPIC_CONFIG_DIR", None)
            script = str(Path(__file__).parents[2] / "install.sh")

            for args in ([], ["--uninstall"]):
                result = subprocess.run(["sh", script, *args], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((codex_skill / "SKILL.md").read_text(encoding="utf-8"), "independent skill")
                self.assertTrue((claude_skills / "session-peer").is_symlink())
                self.assertFalse((codex_skill / ".session-peer-installer").exists())

    def test_remote_install_and_remove_preserve_separate_skill(self):
        with tempfile.TemporaryDirectory(prefix="session-peer-test-") as directory:
            root = Path(directory)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            fake_ssh = fake_bin / "ssh"
            fake_ssh.write_text(
                "#!/bin/sh\nshift\nif [ $# -eq 1 ]; then exec sh -c \"$1\"; fi\nexec \"$@\"\n",
                encoding="utf-8",
            )
            fake_ssh.chmod(0o755)
            codex_skill = root / ".agents/skills/session-peer"
            codex_skill.mkdir(parents=True)
            (codex_skill / "SKILL.md").write_text("independent skill", encoding="utf-8")
            env = dict(os.environ, HOME=str(root), PATH=str(fake_bin) + os.pathsep + os.environ["PATH"])
            env.pop("CLAUDE_CONFIG_DIR", None)
            env.pop("ANTHROPIC_CONFIG_DIR", None)
            script = str(Path(__file__).parents[2] / "install.sh")

            for args in (["--host", "fixture"], ["--uninstall", "--host", "fixture"]):
                result = subprocess.run(["sh", script, *args], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((codex_skill / "SKILL.md").read_text(encoding="utf-8"), "independent skill")
            self.assertFalse((root / ".claude/skills/session-peer").exists())
            self.assertFalse((root / ".local/share/session-peer").exists())
