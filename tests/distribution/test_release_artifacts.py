"""Release artifact checksum and reproducibility contracts."""

import importlib.util
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/release_artifacts.py"
SPEC = importlib.util.spec_from_file_location("release_artifacts", SCRIPT)
release_artifacts = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(release_artifacts)


class ReleaseArtifacts(unittest.TestCase):
    version = "1.2.3"

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
        return directory

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


if __name__ == "__main__":
    unittest.main()
