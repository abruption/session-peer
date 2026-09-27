"""Actionable SSH prerequisite errors without shell guessing or retries."""
import subprocess
import unittest
from unittest import mock

import session_peer as peer


class RemotePythonPrerequisites(unittest.TestCase):
    def test_unusable_interpreters_fail_actionably_without_retry(self):
        for output, error, code in (("", "Python", 9009), ("Python", "", 0),
                                    ("", "python3: command not found", 127),
                                    ("", "'python3' is not recognized as an internal command", 1),
                                    ("", "Python was not found; run without arguments to install", 9009)):
            with self.subTest(error=error), mock.patch.object(peer.Path, "read_text", return_value="source"), \
                    mock.patch.object(peer.subprocess, "run", return_value=subprocess.CompletedProcess([], code, output, error)) as run:
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.run_remote("user@fixture", ["list"], [])
                self.assertEqual(caught.exception.details["remoteRuntimeFailure"],
                                 "python3_unavailable_or_unsupported_shell")
                self.assertIn("POSIX-compatible", str(caught.exception))
                self.assertIn("No fallback or resend", str(caught.exception))
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][-1], "python3 - list --json")

    def test_auth_failure_takes_precedence(self):
        with mock.patch.object(peer.Path, "read_text", return_value="source"), \
                mock.patch.object(peer.subprocess, "run", return_value=subprocess.CompletedProcess([], 255, "", "Permission denied")):
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.run_remote("user@fixture", ["list"], [])
        self.assertEqual(caught.exception.details["sshFailure"], "authentication_failed")

    def test_valid_json_is_unchanged(self):
        value = '{"ok": true, "command": "list", "sessions": []}'
        with mock.patch.object(peer.Path, "read_text", return_value="source"), \
                mock.patch.object(peer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, value, "")):
            self.assertTrue(peer.run_remote("user@fixture", ["list"], [])["ok"])

