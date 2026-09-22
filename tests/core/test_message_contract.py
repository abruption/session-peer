"""Core session-peer contract tests; standard-library only and offline."""

import argparse
import base64
import contextlib
import io
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import session_peer


class MessageChecks(unittest.TestCase):
    def test_rejects_empty_and_whitespace(self):
        for text in ("", "   ", "\n\n", "\t "):
            with self.assertRaises(session_peer.CcPeerError, msg=repr(text)):
                session_peer.check_message(text, remote=False)

    def test_local_cap(self):
        session_peer.check_message("x" * session_peer.MAX_MESSAGE_CHARS, remote=False)
        with self.assertRaises(session_peer.CcPeerError):
            session_peer.check_message("x" * (session_peer.MAX_MESSAGE_CHARS + 1), remote=False)

    def test_remote_cap_is_lower_and_enforced(self):
        # Over SSH the body travels as an argv entry and meets MAX_ARG_STRLEN
        # long before the local cap.
        self.assertLess(session_peer.MAX_REMOTE_MESSAGE_CHARS, session_peer.MAX_MESSAGE_CHARS)
        oversized = "x" * (session_peer.MAX_REMOTE_MESSAGE_CHARS + 1)
        session_peer.check_message(oversized, remote=False)          # fine locally
        with self.assertRaises(session_peer.CcPeerError) as caught:
            session_peer.check_message(oversized, remote=True)
        self.assertIn(str(session_peer.MAX_REMOTE_MESSAGE_CHARS), str(caught.exception))

    def test_remote_cap_leaves_room_for_base64(self):
        # base64 costs 4/3; the encoded form still has to fit in one argument.
        encoded = base64.b64encode(b"x" * session_peer.MAX_REMOTE_MESSAGE_CHARS)
        self.assertLess(len(encoded), 128 * 1024)


class TargetResolution(unittest.TestCase):
    @staticmethod
    def session(pid, name, reachable=True):
        return {"pid": pid, "name": name, "reachable": reachable,
                "socket": f"/tmp/{pid}.sock", "alive": True}

    def test_resolves_by_name_and_pid(self):
        rows = [self.session(1, "alpha"), self.session(2, "beta")]
        self.assertEqual(session_peer.resolve_target(rows, "beta")["pid"], 2)
        self.assertEqual(session_peer.resolve_target(rows, "2")["name"], "beta")

    def test_name_match_ignores_case(self):
        rows = [self.session(1, "API-Worker")]
        self.assertEqual(session_peer.resolve_target(rows, "api-worker")["pid"], 1)

    def test_names_with_spaces_survive(self):
        # These used to resolve as their first word, because the name reached
        # the remote shell unquoted.
        rows = [self.session(1, "my session")]
        self.assertEqual(session_peer.resolve_target(rows, "my session")["pid"], 1)

    def test_unreachable_sessions_are_not_targets(self):
        rows = [self.session(1, "ghost", reachable=False)]
        with self.assertRaises(session_peer.CcPeerError):
            session_peer.resolve_target(rows, "ghost")

    def test_ambiguous_name_asks_for_a_pid(self):
        rows = [self.session(1, "twin"), self.session(2, "twin")]
        with self.assertRaises(session_peer.CcPeerError) as caught:
            session_peer.resolve_target(rows, "twin")
        self.assertIn("pid", str(caught.exception))

    def test_missing_name_lists_what_is_reachable(self):
        rows = [self.session(1, "alpha")]
        with self.assertRaises(session_peer.CcPeerError) as caught:
            session_peer.resolve_target(rows, "nosuch")
        self.assertIn("alpha", str(caught.exception))


class ReplyLine(unittest.TestCase):
    SESSION = {"pid": 42, "name": "documents-ed", "reachable": True}

    def line(self, host="100.64.0.1", session=SESSION, user="alice"):
        with mock.patch.object(session_peer, "own_session", return_value=session), \
             mock.patch.object(session_peer, "detect_reply_host", return_value=host), \
             mock.patch.object(session_peer.getpass, "getuser", return_value=user), \
             mock.patch.dict(os.environ, {}, clear=True):
            return session_peer.reply_line(None)

    def test_carries_user_absolute_path_and_no_reply_to(self):
        line = self.line()
        self.assertIn("alice@100.64.0.1", line)   # receiver connects as us, not itself
        self.assertIn("session_peer.py", line)         # bare `session-peer` isn't on a non-login PATH
        self.assertIn("--no-reply-to", line)      # an answer shouldn't invite an answer
        self.assertNotIn("~/.local/bin", line)

    def test_keeps_an_explicit_user(self):
        self.assertIn("bob@10.0.0.9", self.line(host="bob@10.0.0.9"))

    def test_quotes_a_name_with_spaces(self):
        line = self.line(session={"pid": 7, "name": "my session", "reachable": True})
        self.assertIn("'my session'", line)

    def test_falls_back_to_pid_when_unnamed(self):
        self.assertIn("--to 42", self.line(session={"pid": 42, "name": None,
                                                    "reachable": True}))

    def test_none_outside_a_session(self):
        with mock.patch.object(session_peer, "own_session", return_value=None), \
             mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(session_peer.reply_line("100.64.0.1"))

    def test_none_when_no_address_can_be_found(self):
        with mock.patch.object(session_peer, "own_session", return_value=self.SESSION), \
             mock.patch.object(session_peer, "detect_reply_host", return_value=None), \
             mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(session_peer.reply_line(None))

    def test_uses_actual_file_path(self):
        fake_path = "/opt/custom tools/session_peer.py"
        resolved = Path(fake_path)
        with mock.patch.object(session_peer, "__file__", fake_path), \
             mock.patch("pathlib.Path.is_file", return_value=True), \
             mock.patch("pathlib.Path.resolve", return_value=resolved):
            line = self.line()
        self.assertIn(shlex.quote(str(resolved)), line)
        self.assertNotIn("~/.claude/skills", line)

    def test_falls_back_for_stdin(self):
        with mock.patch.object(session_peer, "__file__", "<stdin>"):
            line = self.line()
        self.assertIn("~/.local/share/session-peer/session_peer.py", line)


class Envelope(unittest.TestCase):
    """From: exists because Claude Code records socket-posted messages with
    origin.from = "unknown" — the receiver otherwise cannot tell who asked."""

    SESSION = {"pid": 42, "name": "documents-ed", "reachable": True}

    def wrap(self, body="hello", with_from=True, with_reply=True, host="100.64.0.1",
             local_reply=False):
        with mock.patch.object(session_peer, "own_session", return_value=self.SESSION), \
             mock.patch.object(session_peer, "detect_reply_host", return_value=host), \
             mock.patch.object(session_peer.getpass, "getuser", return_value="alice"), \
             mock.patch.dict(os.environ, {}, clear=True):
            return session_peer.wrap_message(
                body, None, with_from, with_reply, local_reply=local_reply
            )

    def test_default_carries_sender_and_reply(self):
        out = self.wrap()
        self.assertTrue(out.startswith("From: claude:documents-ed @ alice@100.64.0.1"))
        self.assertIn("hello", out)
        self.assertIn("Reply:", out)

    def test_local_reply_keeps_identity_but_omits_ssh_route(self):
        out = self.wrap(local_reply=True)
        self.assertTrue(out.startswith("From: claude:documents-ed @ alice@100.64.0.1"))
        reply = out.split("Reply: ", 1)[1]
        self.assertIn("--to documents-ed", reply)
        self.assertIn("--no-reply-to", reply)
        self.assertNotIn("--host", reply)

    def test_local_reply_works_without_a_tailnet_address(self):
        out = self.wrap(host=None, local_reply=True)
        self.assertIn("From: claude:documents-ed @ alice@", out)
        self.assertIn("Reply:", out)
        self.assertNotIn("--host", out.split("Reply: ", 1)[1])

    def test_from_survives_no_reply_to(self):
        # Knowing who sent something stays useful when you can't answer it.
        out = self.wrap(with_reply=False)
        self.assertIn("From: claude:documents-ed @ alice@100.64.0.1", out)
        self.assertNotIn("Reply:", out)

    def test_no_from_leaves_the_body_alone(self):
        self.assertEqual(self.wrap(with_from=False, with_reply=False), "hello")

    def test_does_not_repeat_what_claude_code_already_adds(self):
        # Claude Code prefaces peer messages and appends its own guidance;
        # duplicating either would compound with every hop.
        out = self.wrap()
        self.assertNotIn("Another Claude session", out)
        self.assertNotIn("permission laundering", out)

    def test_from_falls_back_to_hostname_without_a_tailnet_address(self):
        out = self.wrap(host=None)
        self.assertIn("From: claude:documents-ed @ alice@", out)
        self.assertNotIn("Reply:", out)   # nothing runnable to offer

    def test_no_envelope_outside_a_session(self):
        with mock.patch.object(session_peer, "own_session", return_value=None), \
             mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(session_peer.wrap_message("hello", None, True, True), "hello")

    def test_body_is_not_duplicated_or_reordered(self):
        out = self.wrap(body="line one\nline two")
        self.assertEqual(out.count("line one"), 1)
        self.assertLess(out.index("From:"), out.index("line one"))
        self.assertLess(out.index("line two"), out.index("Reply:"))

    def test_local_send_normalizes_only_an_automatic_reply_route(self):
        session = {"pid": 42, "name": "worker", "reachable": True,
                   "socket": "/tmp/worker.sock"}
        for extra, expected_local in (([], True),
                                      (["--reply-to", "alice@other"], False)):
            with self.subTest(extra=extra), \
                 mock.patch.object(session_peer, "wrap_message", return_value="wrapped") as wrap, \
                 mock.patch.object(session_peer, "discover", return_value=[session]), \
                 mock.patch.dict(os.environ, {}, clear=True), \
                 contextlib.redirect_stdout(io.StringIO()):
                code = session_peer.main([
                    "send", "--to", "worker", "--dry-run", "--json", *extra, "hello",
                ])
            self.assertEqual(code, 0)
            self.assertIs(wrap.call_args.kwargs["local_reply"], expected_local)

    def test_local_send_normalizes_an_explicit_self_reply_route(self):
        session = {"pid": 42, "name": "worker", "reachable": True,
                   "socket": "/tmp/worker.sock"}
        identity = {
            "agent": "claude", "id": "sender", "target": "sender",
            "host": "alice@mac-mini.tailnet.ts.net",
        }
        with mock.patch.object(session_peer, "wrap_message", return_value="wrapped") as wrap, \
             mock.patch.object(session_peer, "sender_identity", return_value=identity), \
             mock.patch.object(session_peer, "is_self_ssh_destination", return_value=True) as is_self, \
             mock.patch.object(session_peer, "discover", return_value=[session]), \
             mock.patch.dict(os.environ, {}, clear=True), \
             contextlib.redirect_stdout(io.StringIO()):
            code = session_peer.main([
                "send", "--to", "worker", "--dry-run", "--json",
                "--reply-to", "mac-mini.tailnet.ts.net", "hello",
            ])
        self.assertEqual(code, 0)
        is_self.assert_called_once_with("alice@mac-mini.tailnet.ts.net")
        self.assertIs(wrap.call_args.kwargs["local_reply"], True)


class OwnSession(unittest.TestCase):
    def test_reads_pid_from_the_exported_socket_path(self):
        rows = [{"pid": 4011, "name": "worker", "reachable": True}]
        with mock.patch.dict(os.environ,
                             {"CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/cc-socks/4011.sock"}), \
             mock.patch.object(session_peer, "discover", return_value=rows):
            self.assertEqual(session_peer.own_session()["name"], "worker")

    def test_none_when_the_variable_is_absent(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(session_peer.own_session())

    def test_none_when_the_path_has_no_pid(self):
        with mock.patch.dict(os.environ,
                             {"CLAUDE_CODE_MESSAGING_SOCKET": "/tmp/cc-socks/odd.sock"}):
            self.assertIsNone(session_peer.own_session())


class SenderAgent(unittest.TestCase):
    THREAD = "01900000-0000-7000-8000-000000000001"

    def test_codex_thread_is_explicit_in_header_and_reply_target(self):
        with mock.patch.object(session_peer, "own_session", return_value=None), \
             mock.patch.object(session_peer, "tailscale_status", return_value=None), \
             mock.patch.dict(os.environ, {"CODEX_THREAD_ID": self.THREAD}, clear=True), \
             mock.patch.object(session_peer.getpass, "getuser", return_value="alice"):
            wrapped = session_peer.wrap_message("hello", "100.64.0.1", True, True)
        self.assertIn(f"From: codex:{self.THREAD} @ alice@100.64.0.1", wrapped)
        self.assertIn(f"--to codex:{self.THREAD}", wrapped)

    def test_codex_session_id_is_the_compatibility_fallback(self):
        with mock.patch.object(session_peer, "own_session", return_value=None), \
             mock.patch.dict(os.environ, {"CODEX_SESSION_ID": self.THREAD}, clear=True):
            self.assertEqual(session_peer.sender_agent(), {
                "agent": "codex", "id": self.THREAD,
                "target": f"codex:{self.THREAD}",
            })

    def test_claude_socket_takes_precedence_over_nested_codex_variables(self):
        session = {"pid": 42, "name": "reviewer", "reachable": True}
        with mock.patch.object(session_peer, "own_session", return_value=session), \
             mock.patch.dict(os.environ, {"CODEX_THREAD_ID": self.THREAD}, clear=True):
            self.assertEqual(session_peer.sender_agent(), {
                "agent": "claude", "id": "reviewer", "target": "reviewer",
            })

    def test_plain_shell_and_invalid_codex_id_do_not_invent_an_agent(self):
        for environment in ({}, {"CODEX_THREAD_ID": "not-a-thread"}):
            with self.subTest(environment=environment), \
                 mock.patch.object(session_peer, "own_session", return_value=None), \
                 mock.patch.dict(os.environ, environment, clear=True):
                self.assertIsNone(session_peer.sender_agent())


class ReadMessage(unittest.TestCase):
    def test_rejects_tty_stdin(self):
        args = argparse.Namespace(b64=None, message=None)
        with mock.patch("sys.stdin") as stdin:
            stdin.isatty.return_value = True
            with self.assertRaises(session_peer.CcPeerError) as caught:
                session_peer.read_message(args)
        self.assertIn("terminal", str(caught.exception))

    def test_catches_binary_stdin(self):
        args = argparse.Namespace(b64=None, message=None)
        with mock.patch("sys.stdin") as stdin:
            stdin.isatty.return_value = False
            stdin.read.side_effect = UnicodeDecodeError("utf-8", b"", 0, 1, "invalid")
            with self.assertRaises(session_peer.CcPeerError) as caught:
                session_peer.read_message(args)
        self.assertIn("UTF-8", str(caught.exception))
