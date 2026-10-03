"""Release artifact checksum and reproducibility contracts."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/release_artifacts.py"
SPEC = importlib.util.spec_from_file_location("release_artifacts", SCRIPT)
release_artifacts = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(release_artifacts)


class ReleaseArtifacts(unittest.TestCase):
    version = "1.2.3"

    def test_same_named_branch_cannot_replace_the_trusted_tag_source(self):
        git_executable = shutil.which("git")
        self.assertIsNotNone(git_executable, "the source verification fixture requires Git")
        git_executable = str(Path(git_executable).resolve())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {"PATH": str(Path(git_executable).parent) + os.pathsep + os.defpath,
                   "HOME": temporary, "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_CONFIG_GLOBAL": os.devnull}
            # Windows requires this runtime location when launching child processes.
            if "SYSTEMROOT" in os.environ:
                env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]

            def git(*args):
                return subprocess.run([git_executable, *args], cwd=root, env=env, check=True,
                                      capture_output=True, text=True).stdout.strip()

            def verify(expected):
                with mock.patch.dict(os.environ, env, clear=True):
                    return release_artifacts.verify_source("v1.2.3", "main", expected, root)

            git("init", "--initial-branch=main")
            git("config", "user.name", "Release fixture")
            git("config", "user.email", "fixture@example.invalid")
            source = root / "session_peer.py"
            source.write_text('__version__ = "1.2.3"\n# trusted release source\n')
            git("add", "session_peer.py")
            git("commit", "-m", "trusted main release")
            trusted = git("rev-parse", "HEAD")
            git("update-ref", "refs/remotes/origin/main", trusted)
            git("tag", "v1.2.3", trusted)
            git("switch", "--create", "v1.2.3")
            source.write_text('__version__ = "1.2.3"\n# untrusted branch source\n')
            git("commit", "-am", "same-name branch changes source")
            branch = git("rev-parse", "HEAD")
            git("checkout", "main")
            # A bare checkout selects the branch when both namespaces contain the name.
            git("checkout", "v1.2.3")
            self.assertEqual(git("rev-parse", "HEAD"), branch)
            with self.assertRaisesRegex(release_artifacts.VerificationError, "event commit"):
                verify(trusted)
            # Event-SHA checkout never loads source from the colliding branch.
            git("checkout", "--detach", trusted)
            self.assertIn("trusted release source", source.read_text())
            self.assertEqual(verify(trusted), self.version)
            # Even a matching event/checkout SHA must not substitute the branch for the tag.
            git("checkout", "--detach", branch)
            with self.assertRaisesRegex(release_artifacts.VerificationError, "not checked-out"):
                verify(branch)
            git("checkout", "--detach", trusted)
            # Retain protected-main ancestry validation independently of tag matching.
            git("checkout", "--orphan", "unrelated-main")
            git("commit", "-m", "unrelated protected main")
            git("update-ref", "refs/remotes/origin/main", git("rev-parse", "HEAD"))
            git("checkout", "--detach", trusted)
            with self.assertRaisesRegex(release_artifacts.VerificationError, "not contained in origin/main"):
                verify(trusted)

    def make_dist(self, parent: Path, suffix: bytes = b"") -> Path:
        directory = parent / "dist"
        directory.mkdir()
        wheel = directory / "session_peer-1.2.3-py3-none-any.whl"
        metadata = b"Metadata-Version: 2.4\nName: session-peer\nVersion: 1.2.3\n\n"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("session_peer-1.2.3.dist-info/METADATA", metadata)
            archive.writestr("session_peer.py", b"runtime" + suffix)
        sdist = directory / "session_peer-1.2.3.tar.gz"
        payload = parent / "PKG-INFO"
        payload.write_bytes(metadata + suffix)
        with tarfile.open(sdist, "w:gz") as archive:
            archive.add(payload, arcname="session_peer-1.2.3/PKG-INFO")
        for name in ("session_peer.py", "install.sh", "SKILL.md"):
            (directory / name).write_bytes(b"fixture" + suffix)
        return directory

    def test_pypi_download_accepts_only_the_exact_files_host(self):
        name = "session_peer-1.2.3-py3-none-any.whl"
        for url in ("https://files.pythonhosted.org.example.com/x.whl",
                    "https://evilpythonhosted.org/x.whl",
                    "http://files.pythonhosted.org/x.whl"):
            payload = {"info": {"version": self.version},
                       "urls": [{"filename": name, "url": url, "digests": {"sha256": "a" * 64}}]}
            with self.subTest(url=url), tempfile.TemporaryDirectory() as temporary, \
                    mock.patch.object(release_artifacts, "read_manifest", return_value={name: "a" * 64}), \
                    mock.patch.object(release_artifacts, "_pypi_json", return_value=payload), \
                    mock.patch.object(release_artifacts, "urlopen") as urlopen:
                with self.assertRaisesRegex(release_artifacts.VerificationError, "unexpected PyPI artifact URL"):
                    release_artifacts.download_from_pypi(Path(temporary), Path(temporary) / "out",
                                                         self.version, 1, 0)
                urlopen.assert_not_called()

    def test_manifest_rejects_an_artifact_changed_after_hashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = self.make_dist(root)
            release_artifacts.write_manifest(dist, self.version)
            wheel, _ = release_artifacts.package_artifacts(dist)
            wheel.write_bytes(wheel.read_bytes() + b"altered")
            with self.assertRaisesRegex(release_artifacts.VerificationError, "checksum mismatch"):
                release_artifacts.read_manifest(dist, self.version)

    def test_compare_requires_identical_independent_builds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_root = root / "first"
            second_root = root / "second"
            first_root.mkdir()
            second_root.mkdir()
            first = self.make_dist(first_root)
            second = self.make_dist(second_root, suffix=b"changed")
            with self.assertRaisesRegex(release_artifacts.VerificationError, "not byte-for-byte"):
                release_artifacts.compare_builds(first, second, self.version)

    def test_provenance_records_commit_and_artifact_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = self.make_dist(root)
            release_artifacts.write_manifest(dist, self.version)
            path = release_artifacts.write_provenance(
                dist,
                self.version,
                "abruption/session-peer",
                "a" * 40,
                "v1.2.3",
                "123",
                "1",
                "abruption/session-peer/.github/workflows/publish.yml@refs/tags/v1.2.3",
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn('"commit": "' + "a" * 40 + '"', text)
            self.assertIn('"sha256":', text)
            for name in ("session_peer.py", "install.sh", "SKILL.md"):
                self.assertIn(name, text)

    def test_manifest_requires_standalone_support_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            dist = self.make_dist(Path(temporary))
            (dist / "session_peer.py").unlink()
            with self.assertRaisesRegex(release_artifacts.VerificationError, "support asset is missing"):
                release_artifacts.write_manifest(dist, self.version)

    def test_standalone_must_be_exact_tagged_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = self.make_dist(root)
            (root / "session_peer.py").write_bytes(b"reviewed source")
            with mock.patch.object(release_artifacts.subprocess, "run"):
                with self.assertRaisesRegex(release_artifacts.VerificationError, "differs from tagged source"):
                    release_artifacts.verify_standalone(dist, root)


if __name__ == "__main__":
    unittest.main()
