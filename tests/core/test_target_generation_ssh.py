"""Actual streamed Python source against an owned restarted protocol inbox."""
import contextlib
import io
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import session_peer as peer


@unittest.skipUnless(sys.platform in ("darwin", "linux"), "owned Unix peer PID")
class SourceStreamedGeneration(unittest.TestCase):
    def test_restart_between_source_streamed_list_and_send_never_retargets(self):
        with tempfile.TemporaryDirectory(prefix="codex-generation-wire-") as directory:
            root = Path(directory)
            root.chmod(0o700)
            sessions = root / "sessions"
            sessions.mkdir(mode=0o700)
            endpoint, counter = root / "owned.sock", root / "writes.txt"
            attempts = root / "attempts.txt"
            attempts.write_text("0", encoding="ascii")
            name = "owned-streamed-inbox"
            fixtures = Path(__file__).parents[1] / "fixtures"
            processes = []

            def stop(process):
                if process.poll() is None:
                    process.terminate()
                try:
                    process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)

            def spawn():
                process = subprocess.Popen([sys.executable, str(fixtures / "claude_generation_inbox.py"),
                    str(sessions), str(endpoint), str(counter), name],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                processes.append(process)
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(5))
                    ready = os.read(process.stdout.fileno(), 512)
                self.assertEqual(json.loads(ready)["pid"], process.pid)
                return process

            env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "LANG": "C.UTF-8",
                   "CLAUDE_CONFIG_DIR": str(root), "SESSION_PEER_TEST_SSH_COUNTER": str(attempts)}
            native_run = subprocess.run
            def fake_ssh(command, *args, **kwargs):
                if command[0] == "ssh":
                    return native_run([sys.executable, str(fixtures / "source_streamed_fake_ssh.py"),
                        *command[1:]], *args, **{**kwargs, "env": env, "cwd": root})
                return native_run(command, *args, **kwargs)

            def invoke(*arguments):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = peer.main([*arguments, "--host", "owned-fixture", "--json", "--no-update-notice"])
                return code, json.loads(output.getvalue())

            try:
                with mock.patch.object(peer.subprocess, "run", side_effect=fake_ssh), \
                        mock.patch.object(peer, "tailscale_status", return_value={}), \
                        mock.patch.object(peer, "resolve_ssh_destination", return_value="owned-fixture"), \
                        mock.patch.object(peer, "tailscale_ssh_options", return_value=[]):
                    first = spawn()
                    code, listing = invoke("list", "--agent", "claude", "--with-target-generation")
                    self.assertEqual(code, 0, listing)
                    original = listing["sessions"][0]["targetGeneration"]
                    self.assertEqual(counter.read_text(encoding="ascii"), "0")
                    stop(first)
                    endpoint.unlink()
                    successor = spawn()
                    for mode in ([], ["--dry-run"]):
                        before = int(attempts.read_text(encoding="ascii"))
                        code, result = invoke("send", "--to", name, "--message=must not arrive",
                            "--no-from", "--no-reply-to", "--target-generation", original, *mode)
                        self.assertEqual(code, 1, result)
                        self.assertEqual(result["reason"], "stale_target")
                        self.assertIs(result["submitted"], False)
                        self.assertFalse(result["retryAllowed"])
                        self.assertEqual(result["lastSeenTarget"], {"agent": "claude", "targetGeneration": original})
                        self.assertEqual(counter.read_text(encoding="ascii"), "0")
                        self.assertEqual(int(attempts.read_text(encoding="ascii")), before + 1)
                    _, listing = invoke("list", "--agent", "claude", "--with-target-generation")
                    observed = listing["sessions"][0]["targetGeneration"]
                    self.assertNotEqual(original, observed)
                    before = int(attempts.read_text(encoding="ascii"))
                    code, result = invoke("send", "--to", name, "--message=owned positive control",
                        "--no-from", "--no-reply-to", "--target-generation", observed)
                    self.assertEqual(code, 0, result)
                    self.assertEqual(result["target"]["pid"], successor.pid)
                    self.assertEqual(result["targetGeneration"], observed)
                    self.assertNotIn("lastSeenTarget", result)
                    self.assertNotIn("submitted", result)
                    self.assertEqual(counter.read_text(encoding="ascii"), "1")
                    self.assertEqual(int(attempts.read_text(encoding="ascii")), before + 1)
            finally:
                for process in processes:
                    stop(process)


class LastSeenWire(unittest.TestCase):
    def test_only_valid_original_stale_generation_adds_metadata(self):
        token = "tg1:" + "a" * 64
        expected = {"agent": "claude", "targetGeneration": token}
        self.assertEqual(peer.generation_refused("stale_target", "fixture",
            expected_generation=token).details["lastSeenTarget"], expected)
        for reason, original in (("target_generation_unavailable", token),
                                 ("unsupported_target_generation", token),
                                 ("invalid_target_generation", token),
                                 ("stale_target", None), ("stale_target", "not a token")):
            with self.subTest(reason=reason, original=original):
                self.assertNotIn("lastSeenTarget", peer.generation_refused(reason, "fixture",
                    expected_generation=original).details)

    def test_closed_original_metadata_only_proves_requested_stale_refusal(self):
        token = "tg1:" + "a" * 64
        argv = ["send", "--to", "owned", "--target-generation", token]
        response = {"schemaVersion": 1, "command": "send", "ok": False,
            "status": "refused", "reason": "stale_target", "submitted": False, "retryAllowed": False,
            "lastSeenTarget": {"agent": "claude", "targetGeneration": token}}
        self.assertTrue(peer.parse_ssh_response(json.dumps(response), argv)[3])
        self.assertTrue(peer.parse_ssh_response(json.dumps(response),
            ["send", "--to=owned", "--target-generation=" + token])[3])
        for mismatched in (["list", "--to", "owned", "--target-generation", token],
                           ["send", "--to", "codex:00000000-0000-4000-8000-000000000000", "--target-generation", token],
                           ["send", "--to", "antigravity:owned", "--target-generation", token],
                           ["send", "--target-generation", token],
                           ["send", "--to", "owned", "--to", "other", "--target-generation", token]):
            with self.subTest(argv=mismatched):
                candidate = {**response, "command": mismatched[0]}
                self.assertFalse(peer.parse_ssh_response(json.dumps(candidate), mismatched)[3])
        for metadata in ({"agent": "codex", "targetGeneration": token},
                         {"agent": "claude", "targetGeneration": "tg1:" + "b" * 64},
                         {"agent": "claude", "targetGeneration": token, "path": "CORRUPTION_SENTINEL"},
                         {"agent": "claude", "targetGeneration": True}):
            with self.subTest(metadata=metadata):
                altered = {**response, "lastSeenTarget": metadata}
                self.assertFalse(peer.parse_ssh_response(json.dumps(altered), argv)[3])
                self.assertFalse(peer.parse_ssh_response(json.dumps(altered), ["send"])[3])
        for edits in ({"reason": "unsupported_target_generation"}, {"retryAllowed": True}, {"submitted": None}):
            self.assertFalse(peer.parse_ssh_response(json.dumps({**response, **edits}), argv)[3])

    def test_invalid_optional_metadata_preserves_existing_positive_parser_semantics(self):
        native = {"schemaVersion": 1, "command": "send", "ok": True,
            "target": {"pid": 4242, "name": "owned"}, "chars": 1, "dryRun": False,
            "lastSeenTarget": {"secret": "CORRUPTION_SENTINEL"}}
        _, result, _, valid = peer.parse_ssh_response(json.dumps(native), ["send"])
        self.assertTrue(valid)
        self.assertEqual(result["target"], native["target"])
        self.assertNotIn("lastSeenTarget", result)
        self.assertNotIn("submitted", result)
