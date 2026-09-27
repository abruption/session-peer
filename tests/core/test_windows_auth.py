"""Windows auth-envelope regression tests; never contact a real inbox."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import session_peer as peer


class WindowsAuth(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.patch = mock.patch.object(peer, "sessions_dir", return_value=self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def write_key(self, value):
        (self.root / "123.fixture.key").write_text(json.dumps(value), encoding="utf-8")

    def test_registry_token_is_translated_not_forwarded(self):
        self.write_key({"peerToken": "fixture-only-token", "pidDomain": "win32:fixture",
                        "procStartFt": "123456", "type": "untrusted-extra"})
        self.assertEqual(json.loads(peer._read_win_auth(123)),
                         {"type": "auth", "token": "fixture-only-token"})

    def test_rejects_invalid_key_shapes_and_tokens(self):
        for value in (None, [], "text", 42, {}, {"token": "wrong-schema"},
                      {"peerToken": None}, {"peerToken": 123},
                      {"peerToken": True}, {"peerToken": []},
                      {"peerToken": ""}, {"peerToken": "   "}):
            with self.subTest(value=value):
                self.write_key(value)
                self.assertIsNone(peer._read_win_auth(123))

    def test_missing_or_wrong_pid_key_is_not_used(self):
        self.write_key({"peerToken": "fixture-only-token"})
        self.assertIsNone(peer._read_win_auth(456))

    def test_malformed_json_is_not_used(self):
        (self.root / "123.fixture.key").write_text("{", encoding="utf-8")
        self.assertIsNone(peer._read_win_auth(123))

    def test_unreadable_key_is_not_used(self):
        self.write_key({"peerToken": "fixture-only-token"})
        with mock.patch.object(Path, "read_text", side_effect=PermissionError):
            self.assertIsNone(peer._read_win_auth(123))

    def test_pipe_writes_auth_before_user_message(self):
        self.write_key({"peerToken": "fixture-only-token"})
        pipe = mock.mock_open()
        with mock.patch("builtins.open", pipe), mock.patch("time.sleep"):
            peer._post_to_pipe(r"\\\\.\\pipe\\fixture", 123, "fixture message")
        writes = [call.args[0] for call in pipe().write.call_args_list]
        self.assertEqual(len(writes), 2)
        self.assertEqual(json.loads(writes[0]),
                         {"type": "auth", "token": "fixture-only-token"})
        self.assertEqual(json.loads(writes[1]),
                         {"type": "user", "message": {"role": "user", "content": "fixture message"}})
        self.assertTrue(all(line.endswith(b"\n") for line in writes))
        pipe().flush.assert_called_once_with()

    def test_invalid_key_never_opens_pipe(self):
        self.write_key({"peerToken": ""})
        with mock.patch("builtins.open") as opened:
            with self.assertRaises(peer.CcPeerError):
                peer._post_to_pipe(r"\\\\.\\pipe\\fixture", 123, "fixture message")
        opened.assert_not_called()

    def test_pipe_write_failure_is_not_success(self):
        self.write_key({"peerToken": "fixture-only-token"})
        pipe = mock.mock_open()
        pipe().write.side_effect = BrokenPipeError("fixture pipe closed")
        with mock.patch("builtins.open", pipe):
            with self.assertRaisesRegex(peer.CcPeerError, "cannot reach inbox"):
                peer._post_to_pipe(r"\\\\.\\pipe\\fixture", 123, "fixture message")


if __name__ == "__main__":
    unittest.main()

