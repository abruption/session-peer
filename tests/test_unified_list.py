"""Unified discovery and partial-result transport regression tests."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import session_peer as peer


class UnifiedList(unittest.TestCase):
    claude = {"pid": 7, "name": "worker", "cwd": "/project", "alive": True,
              "reachable": True, "status": "idle"}
    codex = {"id": "01900000-0000-7000-8000-000000000001",
             "name": "worker", "cwd": "/project", "archived": False}

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        self.home = root / ".codex"
        self.home.mkdir()
        (self.home / "state_5.sqlite").touch()
        self.codex = {**type(self).codex, "agent": "codex", "updatedAt": 1,
                      "codexHome": str(self.home), "stateDb": str(self.home / "state_5.sqlite")}
        for patcher in (mock.patch.object(Path, "home", return_value=root),
                        mock.patch.dict(os.environ)):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("CODEX_HOME", None)
        os.environ.pop("SESSION_PEER_CODEX_HOMES", None)

    def invoke(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = peer.main(["list", "--no-update-notice", *args])
        return code, out.getvalue()

    def test_combined_and_filters(self):
        for agent, expected in ((None, ["claude", "codex"]),
                                ("claude", ["claude"]), ("codex", ["codex"])):
            with self.subTest(agent=agent),                  mock.patch.object(peer, "discover", return_value=[self.claude]) as claude,                  mock.patch.object(peer, "discover_codex", return_value=[self.codex]) as codex:
                code, output = self.invoke("--json", *(["--agent", agent] if agent else []))
                result = json.loads(output)
                self.assertEqual(code, 0)
                self.assertEqual([row["agent"] for row in result["sessions"]], expected)
                self.assertEqual(list(result["discovery"]), expected + (["antigravity"] if agent is None else []))
                self.assertEqual(claude.called, "claude" in expected)
                self.assertEqual(codex.called, "codex" in expected)

    def test_failures_preserve_other_agent_even_when_empty(self):
        for failed in ("claude", "codex", "both"):
            with self.subTest(failed=failed),                  mock.patch.object(peer, "discover", side_effect=(
                     peer.CcPeerError("permission denied") if failed in ("claude", "both")
                     else None), return_value=[self.claude]),                  mock.patch.object(peer, "discover_codex", side_effect=(
                     peer.CcPeerError("unsupported schema") if failed in ("codex", "both")
                     else None), return_value=[self.codex]):
                code, output = self.invoke("--json")
                result = json.loads(output)
                self.assertEqual(code, 1)
                self.assertFalse(result["ok"])
                self.assertEqual(len(result["sessions"]), 0 if failed == "both" else 1)
                self.assertIn("error", result)
                if failed != "both":
                    self.assertNotEqual(result["sessions"][0]["agent"], failed)

    def test_missing_home_and_missing_claude_directory(self):
        with tempfile.TemporaryDirectory() as tmp,              mock.patch.object(peer, "sessions_dir", return_value=Path(tmp)/"claude"):
            code, output = self.invoke("--codex-home", tmp, "--json")
            result = json.loads(output)
            self.assertEqual(code, 1)
            self.assertEqual(result["sessions"], [])
            self.assertEqual(result["discovery"]["claude"]["status"], "ok")
            self.assertEqual(result["discovery"]["codex"]["status"], "error")

    def test_claude_directory_permission_is_not_empty_success(self):
        with mock.patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
            with self.assertRaises(peer.CcPeerError):
                peer.discover()

    def test_all_and_home_forwarded_and_human_states(self):
        with mock.patch.object(peer, "discover", return_value=[self.claude]) as claude,              mock.patch.object(peer, "discover_codex", return_value=[self.codex]) as codex:
            code, output = self.invoke("--all", "--codex-home", str(self.home))
        self.assertEqual(code, 0)
        claude.assert_called_once_with(include_unreachable=True)
        self.assertTrue(codex.call_args.args[0].all)
        self.assertEqual(codex.call_args.args[0].codex_home, str(self.home))
        self.assertIn("AGENT", output)
        self.assertIn("execution unknown", output)

    def test_remote_partial_result_survives_nonzero_exit(self):
        partial = {"schemaVersion": 1, "command": "list", "ok": False,
                   "sessions": [{**self.claude, "agent": "claude"}],
                   "discovery": {"claude": {"status": "ok"},
                                 "codex": {"status": "error", "error": "missing DB"}},
                   "error": "Discovery failed for: codex"}
        completed = subprocess.CompletedProcess([], 1, json.dumps(partial), "")
        with mock.patch.object(peer, "ssh_user_metadata", return_value={}),              mock.patch.object(peer.subprocess, "run", return_value=completed):
            self.assertEqual(peer.run_remote("host", ["list"], []), partial)
            with self.assertRaises(peer.CcPeerError):
                peer.run_remote("host", ["send"], [])
        success = {**partial, "ok": True, "discovery": {"claude": {"status": "ok"}}}
        with mock.patch.object(peer, "tailscale_status", return_value=None),              mock.patch.object(peer, "run_remote", side_effect=[partial, success]) as remote,              mock.patch.object(peer, "remote_installed_version", return_value=peer.__version__):
            code, output = self.invoke("--host", "a", "--host", "b", "--all",
                                       "--codex-home", "/custom", "--json")
        results = json.loads(output)
        self.assertEqual(code, 1)
        self.assertEqual([r["ok"] for r in results], [False, True])
        self.assertEqual(results[0]["sessions"], partial["sessions"])
        self.assertEqual([r["host"] for r in results], ["a", "b"])
        self.assertIn("--all", remote.call_args.args[1])
        self.assertIn("/custom", remote.call_args.args[1])

    def test_complete_empty_result(self):
        with mock.patch.object(peer, "discover", return_value=[]),              mock.patch.object(peer, "discover_codex", return_value=[]):
            code, output = self.invoke("--json")
        result = json.loads(output)
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["sessions"], [])
        self.assertEqual(result["discovery"]["claude"], {"status": "ok"})
        self.assertEqual(result["discovery"]["codex"]["status"], "ok")
        self.assertEqual(result["discovery"]["codex"]["homes"][0]["sessionCount"], 0)
