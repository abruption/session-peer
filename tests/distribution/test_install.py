"""Isolated standalone installation and coexistence checks; no real HOME writes."""
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest


@unittest.skipIf(os.name == "nt", "POSIX installer; Windows uses pip")
class Install(unittest.TestCase):
    def test_failed_network_install_preserves_program_launcher_and_skills(self):
        self._check_failed_network_install(symlink_root=False)

    def test_failed_network_install_through_symlink_preserves_install(self):
        self._check_failed_network_install(symlink_root=True)

    def _check_failed_network_install(self, *, symlink_root):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if symlink_root:
                actual = root / 'actual'
                actual.mkdir()
                alias = root / 'alias'
                alias.symlink_to(actual, target_is_directory=True)
                root = alias
            home = root / 'home'
            home.mkdir()
            env = {**os.environ, 'HOME': str(home)}
            env.pop('CLAUDE_CONFIG_DIR', None)
            env.pop('ANTHROPIC_CONFIG_DIR', None)
            subprocess.run(['sh', str(repo / 'install.sh')], env=env, check=True, capture_output=True)
            program = home / '.local/share/session-peer/session_peer.py'
            launcher = home / '.local/bin/session-peer'
            skills = [home / '.claude/skills/session-peer/SKILL.md', home / '.agents/skills/session-peer/SKILL.md']
            previous = [p.read_bytes() for p in [program, *skills]]
            source = root / 'source'
            source.mkdir()
            shutil.copyfile(repo / 'install.sh', source / 'install.sh')
            fake = root / 'bin'
            fake.mkdir()
            curl = fake / 'curl'
            curl.write_text('''#!/bin/sh
case "$2" in
  */SKILL.md) cp "$FIXTURE_SKILL" "$4"; exit ;;
esac
case "$FIXTURE_MODE" in
  partial) printf 'partial' > "$4"; exit 18 ;;
  http) exit 22 ;;
  invalid) printf '<html>error</html>' > "$4" ;;
  valid) cp "$FIXTURE_PROGRAM" "$4" ;;
esac
''')
            curl.chmod(0o755)
            env.update(PATH=str(fake)+os.pathsep+os.environ['PATH'],
                       FIXTURE_PROGRAM=str(repo / 'session_peer.py'),
                       FIXTURE_SKILL=str(repo / 'skills/session-peer/SKILL.md'))
            for mode in ('partial', 'http', 'invalid', 'valid'):
                with self.subTest(mode=mode):
                    result = subprocess.run(['sh', str(source / 'install.sh')],
                        env={**env, 'FIXTURE_MODE': mode}, capture_output=True)
                    self.assertEqual(result.returncode == 0, mode == 'valid', result.stderr)
                    self.assertEqual([p.read_bytes() for p in [program, *skills]], previous)
                    self.assertTrue(launcher.is_symlink())
                    self.assertEqual(launcher.resolve(), program.resolve())
                    self.assertEqual(list(program.parent.glob('.install.*')), [])

    def test_invalid_local_and_remote_artifacts_do_not_replace_existing_install(self):
        repo = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {**os.environ, 'HOME': str(root)}
            env.pop('CLAUDE_CONFIG_DIR', None)
            env.pop('ANTHROPIC_CONFIG_DIR', None)
            subprocess.run(['sh', str(repo / 'install.sh')], env=env, check=True, capture_output=True)
            program = root / '.local/share/session-peer/session_peer.py'
            before = program.read_bytes()
            source = root / 'source'
            source.mkdir()
            shutil.copyfile(repo / 'install.sh', source / 'install.sh')
            (source / 'session_peer.py').write_text('not valid python!')
            (source / 'SKILL.md').write_text('must not replace')
            ssh = source / 'ssh'
            ssh.write_text('#!/bin/sh\nshift\nexec "$@"\n')
            ssh.chmod(0o755)
            env['PATH'] = str(source)+os.pathsep+os.environ['PATH']
            for args in ([], ['--host', 'fixture']):
                result = subprocess.run(['sh', str(source / 'install.sh'), *args], env=env, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(program.read_bytes(), before)
                self.assertEqual(list(program.parent.glob('.install.*')), [])

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
