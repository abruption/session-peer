"""Offline generation pinning: owned endpoints, synthetic reuse and fake SSH."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest import mock

import session_peer as peer


class TargetGeneration(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="codex-generation-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.sessions = self.root / "sessions"
        self.sessions.mkdir()
        self.pid = os.getpid()
        self.sock = str(self.root / "inbox.sock")
        self.record = {"pid": self.pid, "name": "worker", "messagingSocketPath": self.sock,
                       "startedAt": 1000}
        self.path = self.sessions / f"{self.pid}.json"
        self.write_record()
        self.row = {"pid": self.pid, "name": "worker", "socket": self.sock,
                    "reachable": True, "alive": True, "status": "idle", "cwd": "/fixture", "agent": "claude"}
        patcher = mock.patch.object(peer, "sessions_dir", return_value=self.sessions)
        patcher.start()
        self.addCleanup(patcher.stop)
        if not peer.IS_WINDOWS:
            self.listener = socket.socket(socket.AF_UNIX)
            self.listener.bind(self.sock)
            self.listener.listen(1)
            self.addCleanup(self.listener.close)
        else:
            self.sock = self.record["messagingSocketPath"] = r"\\.\pipe\generation-test"
            self.row["socket"] = self.sock
            self.write_record()

    def write_record(self):
        self.path.write_text(json.dumps(self.record), encoding="utf-8")

    def token(self):
        with mock.patch.object(peer, "process_generation", return_value="precise-birth-1"):
            return peer.claude_generation(self.row)

    def invoke(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = peer.main([*argv, "--json", "--no-update-notice"])
        return code, json.loads(out.getvalue())

    def test_legacy_output_unchanged_without_opt_in(self):
        args = argparse.Namespace(to="worker", dry_run=True)
        with mock.patch.object(peer, "discover", return_value=[self.row]):
            result = peer.ClaudeAdapter().submit(peer.ExecutionContext("local", args), "hello")
        self.assertNotIn("targetGeneration", result)
        self.assertNotIn("submitted", result)

    def test_same_generation_and_changed_birth(self):
        token = self.token()
        self.assertRegex(token, r"^tg1:[0-9a-f]{64}$")
        with mock.patch.object(peer, "process_generation", return_value="precise-birth-1"):
            peer.require_claude_generation(self.row, token)
        with mock.patch.object(peer, "process_generation", return_value="precise-birth-2"):
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.require_claude_generation(self.row, token)
        self.assertEqual(caught.exception.details["reason"], "stale_target")
        self.assertFalse(caught.exception.details["submitted"])

    def test_status_and_name_change_do_not_change_incarnation(self):
        token = self.token()
        self.record.update(status="busy", name="renamed")
        self.write_record()
        self.assertEqual(token, self.token())

    def test_same_pid_other_home_or_socket_changes_token(self):
        token = self.token()
        other = self.root / "other"
        other.mkdir()
        (other / self.path.name).write_text(json.dumps(self.record))
        with mock.patch.object(peer, "sessions_dir", return_value=other):
            self.assertNotEqual(token, self.token())
        self.record["messagingSocketPath"] += "-successor"
        self.write_record()
        self.assertIsNone(self.token())

    def test_unavailable_creation_evidence_is_not_a_token(self):
        with mock.patch.object(peer, "process_generation", return_value=None):
            self.assertIsNone(peer.claude_generation(self.row))
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.require_claude_generation(self.row, self.token() or "tg1:" + "a" * 64)
        self.assertEqual(caught.exception.details["reason"], "target_generation_unavailable")

    def test_stale_name_or_pid_refuses_before_post(self):
        token = self.token()
        for rows in ([], [{**self.row, "pid": self.pid + 1}], [self.row, self.row]):
            with mock.patch.object(peer, "discover", return_value=rows), \
                    mock.patch.object(peer, "post_to_socket") as post, \
                    mock.patch.object(peer, "process_generation", return_value="precise-birth-1"):
                code, result = self.invoke("send", "--to", "worker", "--message=x",
                                           "--no-from", "--no-reply-to", "--target-generation", token)
            self.assertEqual(code, 1)
            self.assertIn(result["reason"], ("stale_target", "target_generation_unavailable"))
            post.assert_not_called()

    def test_native_profiles_without_atomic_generation_are_refused(self):
        with mock.patch.object(peer, "subprocess") as native:
            code, result = self.invoke("send", "--to", "codex:11111111-1111-1111-1111-111111111111",
                                       "--target-generation", "tg1:" + "a" * 64,
                                       "--no-from", "--no-reply-to", "--message=x")
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "unsupported_target_generation")
        native.run.assert_not_called()

    def test_malformed_and_paired_generation_rejected_before_effect(self):
        for token in ("bad", "tg1:" + "a" * 63, "tg1:" + "A" * 64):
            with mock.patch.object(peer, "post_to_socket") as post:
                code, result = self.invoke("send", "--to", "worker", "--message=x",
                                           "--target-generation", token)
            self.assertEqual(code, 1)
            self.assertEqual(result["reason"], "invalid_target_generation")
            post.assert_not_called()
        with mock.patch.object(peer, "optional_relay") as relay:
            code, result = self.invoke("send", "--to", "worker", "--device", "device",
                                       "--target-generation", "tg1:" + "a" * 64, "--message=x")
        self.assertEqual(code, 1)
        relay.assert_not_called()

    def test_opt_in_discovery_and_remote_arg_forwarding(self):
        with mock.patch.object(peer, "discover", return_value=[self.row]), \
                mock.patch.object(peer, "process_generation", return_value="precise-birth-1"):
            code, result = self.invoke("list", "--agent", "claude", "--with-target-generation")
        self.assertEqual(code, 0)
        self.assertEqual(result["sessions"][0]["targetGeneration"], self.token())
        with mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "resolve_ssh_destination", return_value="test-host"), \
                mock.patch.object(peer, "tailscale_ssh_options", return_value=[]), \
                mock.patch.object(peer.SshTransport, "execute", return_value={"ok": True, "target": {"pid": self.pid},
                                                                           "targetGeneration": self.token()}) as remote:
            code, result = self.invoke("send", "--host", "test-host", "--to", "worker",
                                       "--target-generation", self.token(), "--message=x",
                                       "--no-from", "--no-reply-to")
        self.assertEqual(code, 0)
        self.assertIn("--target-generation", remote.call_args[0][0])
        self.assertEqual(result["targetGeneration"], self.token())

    @unittest.skipUnless(peer.sys.platform in ("darwin", "linux"), "owned Unix inbox")
    def test_owned_socket_peer_identity_and_zero_write_on_wrong_peer(self):
        token = peer.claude_generation(self.row)
        self.assertIsNotNone(token)
        received = []
        def receive():
            self.listener.settimeout(5)
            conn, _ = self.listener.accept()
            with conn:
                conn.settimeout(5)
                received.append(conn.recv(65536))
        thread = threading.Thread(target=receive)
        thread.start()
        peer.post_to_socket(self.sock, "owned fixture", self.pid,
                            generation_session=self.row, expected_generation=token)
        thread.join(6)
        self.assertFalse(thread.is_alive())
        self.assertIn(b"owned fixture", received[0])
        thread = threading.Thread(target=receive)
        thread.start()
        with mock.patch.object(peer, "connected_inbox_pid", return_value=self.pid + 1):
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.post_to_socket(self.sock, "must not arrive", self.pid,
                                    generation_session=self.row, expected_generation=token)
        thread.join(6)
        self.assertEqual(caught.exception.details["reason"], "stale_target")
        self.assertEqual(received[1], b"")

    def test_final_birth_change_and_missing_peer_refuse(self):
        token = self.token()
        for pid, birth, reason in ((None, "precise-birth-1", "target_generation_unavailable"),
                                   (self.pid, "precise-birth-2", "stale_target")):
            with mock.patch.object(peer, "process_generation", return_value=birth):
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.verify_connected_generation(self.row, token, pid)
            self.assertEqual(caught.exception.details["reason"], reason)

    def test_private_deadline_refuses_before_effect_and_bounds_write_drain(self):
        conn = mock.Mock()
        with mock.patch.object(peer, "IS_WINDOWS", False), \
                mock.patch.object(peer.socket, "AF_UNIX", 1, create=True), \
                mock.patch.object(peer.socket, "socket", return_value=conn), \
                mock.patch.object(peer.time, "monotonic", side_effect=[0, 0, 10]):
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.post_to_socket("fixture", "hello", effect_deadline=10, total_deadline=15)
        self.assertEqual(caught.exception.details["reason"], "effect_deadline_exhausted")
        conn.sendall.assert_not_called()
        conn.close.assert_called_once()
        conn = mock.Mock()
        with mock.patch.object(peer, "IS_WINDOWS", False), \
                mock.patch.object(peer.socket, "AF_UNIX", 1, create=True), \
                mock.patch.object(peer.socket, "socket", return_value=conn), \
                mock.patch.object(peer.time, "monotonic", side_effect=[0, 1, 2, 9]):
            peer.post_to_socket("fixture", "hello", effect_deadline=10, total_deadline=15)
        self.assertEqual([call.args[0] for call in conn.settimeout.call_args_list], [9, 8, 1])
        conn.sendall.assert_called_once()

    def test_private_deadline_post_write_error_unknown_and_windows_unsupported(self):
        conn = mock.Mock()
        conn.sendall.side_effect = OSError("synthetic partial write")
        with mock.patch.object(peer, "IS_WINDOWS", False), \
                mock.patch.object(peer.socket, "AF_UNIX", 1, create=True), \
                mock.patch.object(peer.socket, "socket", return_value=conn), \
                mock.patch.object(peer.time, "monotonic", return_value=0):
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.post_to_socket("fixture", "hello", effect_deadline=10, total_deadline=15)
        self.assertEqual(caught.exception.details["status"], "unknown")
        self.assertNotIn("submitted", caught.exception.details)
        self.assertFalse(caught.exception.details["retryAllowed"])
        with mock.patch.object(peer, "IS_WINDOWS", True), \
                mock.patch.object(peer, "_post_to_pipe") as pipe:
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.post_to_socket(r"\\.\pipe\fixture", "hello", effect_deadline=10, total_deadline=15)
        self.assertEqual(caught.exception.details["reason"], "unsupported_bounded_inbox")
        pipe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
