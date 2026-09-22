"""Exact wheel/sdist content contracts for release artifacts."""

import os
from pathlib import Path, PurePosixPath
import tarfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
DIST_DIR_VALUE = os.environ.get("SESSION_PEER_DIST_DIR")


@unittest.skipUnless(DIST_DIR_VALUE, "set SESSION_PEER_DIST_DIR after building artifacts")
class DistributionContents(unittest.TestCase):
    def setUp(self):
        self.dist = (ROOT / DIST_DIR_VALUE).resolve()
        wheels = sorted(self.dist.glob("*.whl"))
        sdists = sorted(self.dist.glob("*.tar.gz"))
        self.assertEqual(len(wheels), 1, "expected exactly one wheel")
        self.assertEqual(len(sdists), 1, "expected exactly one sdist")
        self.wheel = wheels[0]
        self.sdist = sdists[0]

    @staticmethod
    def source_files(path):
        return {
            item.relative_to(ROOT).as_posix()
            for item in (ROOT / path).rglob("*")
            if item.is_file() and "__pycache__" not in item.parts
        }

    def test_wheel_contains_exact_runtime_contract(self):
        expected_runtime = {
            "session_peer.py",
            "session_peer_mcp.py",
            *self.source_files("session_peer_relay"),
        }
        with zipfile.ZipFile(self.wheel) as archive:
            names = set(archive.namelist())

        dist_info = {
            name.split("/", 1)[0]
            for name in names
            if ".dist-info/" in name
        }
        self.assertEqual(len(dist_info), 1, "expected one dist-info directory")
        prefix = dist_info.pop()
        expected_metadata = {
            f"{prefix}/METADATA",
            f"{prefix}/WHEEL",
            f"{prefix}/entry_points.txt",
            f"{prefix}/licenses/LICENSE",
            f"{prefix}/RECORD",
        }
        self.assertEqual(names, expected_runtime | expected_metadata)

    def test_sdist_contains_exact_source_and_documentation_contract(self):
        expected = {
            ".agents/plugins/marketplace.json",
            ".gitignore",
            "LICENSE",
            "README.md",
            "README.ja.md",
            "README.ko.md",
            "README.zh-CN.md",
            "SECURITY.md",
            "pyproject.toml",
            "session_peer.py",
            "session_peer_mcp.py",
            *self.source_files("session_peer_relay"),
            *self.source_files("docs"),
            *self.source_files("deploy/examples"),
            *self.source_files("plugins"),
        }
        expected.add("deploy/README.md")

        with tarfile.open(self.sdist) as archive:
            files = [item.name for item in archive.getmembers() if item.isfile()]
        roots = {PurePosixPath(name).parts[0] for name in files}
        self.assertEqual(len(roots), 1, "expected one sdist root directory")
        root = roots.pop()
        actual = {
            PurePosixPath(name).relative_to(root).as_posix()
            for name in files
        }
        self.assertEqual(actual, expected | {"PKG-INFO"})

    def test_artifacts_exclude_private_state_and_development_trees(self):
        with zipfile.ZipFile(self.wheel) as archive:
            wheel_names = archive.namelist()
        with tarfile.open(self.sdist) as archive:
            sdist_names = [item.name for item in archive.getmembers() if item.isfile()]

        for name in wheel_names + sdist_names:
            path = PurePosixPath(name)
            parts = {part.lower() for part in path.parts}
            basename = path.name.lower()
            self.assertNotIn("experiments", parts, name)
            self.assertNotIn("node_modules", parts, name)
            self.assertNotIn("ops", parts if "deploy" in parts else set(), name)
            self.assertNotIn("tests", parts, name)
            self.assertFalse(basename.endswith((".db", ".sqlite", ".sqlite3")), name)
            self.assertFalse(basename.endswith((".key", ".pem")), name)
            self.assertNotIn("credential", basename, name)
            self.assertNotIn("client_secret", basename, name)
        self.assertFalse(any(PurePosixPath(name).name == "cc_peer.py" for name in wheel_names + sdist_names))


if __name__ == "__main__":
    unittest.main()
