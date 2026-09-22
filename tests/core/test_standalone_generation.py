"""Contracts for the canonical core and generated standalone artifact."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "tools" / "generate_session_peer.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("session_peer_generator", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load standalone generator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StandaloneGenerationTest(unittest.TestCase):
    def test_checked_in_artifact_matches_canonical_segments(self):
        generator = load_generator()
        rendered = generator.render()
        generator.validate(rendered)
        self.assertEqual((ROOT / "session_peer.py").read_bytes(), rendered)
        self.assertEqual(rendered, generator.render())

    def test_check_rejects_a_stale_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "session_peer.py"
            output.write_text("stale\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(GENERATOR), "--check", "--output", str(output)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(1, result.returncode)
        self.assertIn("is stale", result.stderr)

    def test_generated_file_runs_without_the_source_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            standalone = Path(directory) / "session_peer.py"
            standalone.write_bytes((ROOT / "session_peer.py").read_bytes())
            result = subprocess.run(
                [sys.executable, str(standalone), "--version"],
                cwd=directory,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("session-peer", result.stdout)


if __name__ == "__main__":
    unittest.main()
