"""Unit tests for session-peer. Standard library only, no network, no SSH.

Run with:  python3 -m unittest tests.test_session_peer -v

Every case here corresponds to something that was once wrong and shipped —
the injection paths, the caps that weren't enforced, the reply line that
couldn't be run. The point is that the next release breaks loudly.
"""

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


class TailnetAddress(unittest.TestCase):
    def test_accepts_cgnat_range(self):
        for addr in ("100.64.0.1", "100.122.73.69", "100.127.255.255"):
            self.assertTrue(session_peer.is_tailnet_address(addr), addr)

    def test_rejects_public_addresses_that_merely_start_with_100(self):
        # 100.200.x.x is ordinary public space; matching on "100." alone took it.
        for addr in ("100.200.1.1", "100.63.0.1", "100.128.0.1"):
            self.assertFalse(session_peer.is_tailnet_address(addr), addr)

    def test_rejects_out_of_range_octets(self):
        for addr in ("100.64.999.999", "100.64.0.256", "100.64.0"):
            self.assertFalse(session_peer.is_tailnet_address(addr), addr)

    def test_rejects_non_addresses(self):
        for addr in ("", "not-an-ip", "100.64.0.1.5", "100.64.0.x"):
            self.assertFalse(session_peer.is_tailnet_address(addr), addr)


class SshArgumentChecks(unittest.TestCase):
    """--host and --ssh-opt reach ssh directly, so they are a trust boundary."""

    def test_host_may_not_start_with_a_dash(self):
        # ssh has no `--`, so a leading dash makes the host an option.
        with self.assertRaises(session_peer.CcPeerError):
            session_peer.check_ssh_argument("-oProxyCommand=touch /tmp/x", "--host")

    def test_rejects_options_that_run_a_local_command(self):
        for value in (
            "-oProxyCommand=whoami",
            "-o ProxyCommand=whoami",
            "-oPROXYCOMMAND=whoami",
            "-oLocalCommand=whoami",
            "-oPermitLocalCommand=yes",
        ):
            with self.assertRaises(session_peer.CcPeerError, msg=value):
                session_peer.check_ssh_argument(value, "--ssh-opt")

    def test_allows_ordinary_options(self):
        # ProxyJump takes a host, not a command — it is how you cross a bastion.
        for value in ("-p", "2222", "-oConnectTimeout=8", "-oProxyJump=bastion"):
            session_peer.check_ssh_argument(value, "--ssh-opt")

    def test_allows_ordinary_hosts(self):
        for value in ("web-01", "ubuntu@10.0.0.4", "100.64.0.1"):
            session_peer.check_ssh_argument(value, "--host")


class SshUserResolution(unittest.TestCase):
    @staticmethod
    def completed(stdout="", stderr="", returncode=0):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def test_explicit_user_takes_precedence_without_config_probe(self):
        with mock.patch.object(session_peer.subprocess, "run") as run:
            result = session_peer.ssh_user_metadata("release-user@build-alias", [])
        self.assertEqual(result, {
            "sshUser": "release-user", "sshUserSource": "explicit",
        })
        run.assert_not_called()

    def test_ssh_config_or_local_default_uses_original_alias_and_options(self):
        completed = self.completed("host build-alias\nuser deploy\nhostname verified.example.ts.net\n")
        with mock.patch.object(session_peer.subprocess, "run", return_value=completed) as run:
            result = session_peer.ssh_user_metadata(
                "build-alias", ["-o", "HostName=verified.example.ts.net", "-p", "2222"]
            )
        self.assertEqual(result, {
            "sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
        })
        self.assertEqual(run.call_args.args[0], [
            "ssh", "-G", "-o", "HostName=verified.example.ts.net",
            "-p", "2222", "build-alias",
        ])

    def test_missing_or_malformed_ssh_config_probe_is_unknown(self):
        cases = (
            OSError("ssh missing"),
            self.completed("host build-alias\nhostname build-alias\n"),
            self.completed("", "bad option", 255),
        )
        for outcome in cases:
            with self.subTest(outcome=outcome), \
                 mock.patch.object(session_peer.subprocess, "run", side_effect=[outcome]):
                self.assertEqual(session_peer.ssh_user_metadata("build-alias", []), {
                    "sshUser": None, "sshUserSource": "unknown",
                })

    def test_success_reports_the_effective_user(self):
        config = self.completed("user deploy\nhostname build-alias\n")
        remote = self.completed('{"ok": true, "sessions": []}\n')
        with mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
             mock.patch.object(session_peer.subprocess, "run",
                               side_effect=[config, remote]) as run:
            result = session_peer.run_remote("build-alias", ["list"], [])
        self.assertEqual(result["sshUser"], "deploy")
        self.assertEqual(result["sshUserSource"], "ssh_config_or_local_default")
        self.assertEqual(run.call_count, 2)

    def test_connection_failures_are_classified_without_retrying(self):
        cases = (
            (self.completed("", "Permission denied (publickey).", 255),
             "authentication_failed"),
            (self.completed("", "Host key verification failed.", 255),
             "host_key_failed"),
            (subprocess.TimeoutExpired(["ssh"], 120), "timeout"),
            (self.completed("", "connect to host failed: Connection refused", 255),
             "transport_failed"),
        )
        for outcome, expected in cases:
            config = self.completed("user deploy\nhostname build-alias\n")
            with self.subTest(expected=expected), \
                 mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
                 mock.patch.object(session_peer.subprocess, "run",
                                   side_effect=[config, outcome]) as run, \
                 self.assertRaises(session_peer.CcPeerError) as caught:
                session_peer.run_remote("build-alias", ["list"], [])
            self.assertEqual(caught.exception.details["sshFailure"], expected)
            self.assertEqual(caught.exception.details["sshUser"], "deploy")
            self.assertEqual(run.call_count, 2)
            if expected == "authentication_failed":
                self.assertIn("--host USER@HOST", str(caught.exception))

    def test_help_explains_user_precedence(self):
        help_text = session_peer.build_parser()._subparsers._group_actions[0].choices[
            "send"
        ].format_help()
        self.assertIn("[USER@]HOST", help_text)
        self.assertIn("SSH config/default", help_text)


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


class VersionParsing(unittest.TestCase):
    def test_orders_releases(self):
        self.assertLess(session_peer.parse_version("0.2.0"), session_peer.parse_version("0.3.0"))
        self.assertLess(session_peer.parse_version("v0.9.0"), session_peer.parse_version("v0.10.0"))
        self.assertEqual(session_peer.parse_version("v1.2.3"), session_peer.parse_version("1.2.3"))

    def test_survives_junk_without_raising(self):
        # A malformed tag must not crash an update check; sorting lowest means
        # "don't offer this as newer".
        for text in ("", "not-a-version", "v..", "1.x.3"):
            self.assertIsInstance(session_peer.parse_version(text), tuple)
        self.assertLess(session_peer.parse_version("junk"), session_peer.parse_version("0.0.1"))

    def test_ignores_anything_past_patch(self):
        self.assertEqual(session_peer.parse_version("1.2.3.4"), (1, 2, 3))


class RemoteInstalledVersion(unittest.TestCase):
    """Why this exists at all: run_remote() ships and runs *our* source, so
    asking the remote command to report itself would only echo our version.
    The installed copy is the one that can fall behind."""

    def run_with(self, stdout):
        completed = mock.Mock(stdout=stdout, returncode=0)
        with mock.patch.object(session_peer.subprocess, "run", return_value=completed):
            return session_peer.remote_installed_version("web-01", [])

    def test_reads_the_reported_version(self):
        self.assertEqual(self.run_with("session-peer 0.2.0\n"), "0.2.0")

    def test_none_when_not_installed(self):
        self.assertIsNone(self.run_with(""))
        self.assertIsNone(self.run_with("python3: can't open file\n"))

    def test_ssh_failure_is_not_reported_as_not_installed(self):
        with mock.patch.object(session_peer.subprocess, "run", side_effect=OSError("boom")):
            with self.assertRaises(session_peer.CcPeerError) as caught:
                session_peer.remote_installed_version("web-01", [])
        self.assertEqual(caught.exception.details["sshFailure"], "transport_failed")

    def test_still_validates_ssh_arguments(self):
        # This path builds its own ssh command, so it needs the same guard.
        with self.assertRaises(session_peer.CcPeerError):
            session_peer.remote_installed_version("-oProxyCommand=whoami", [])


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


class TailscaleDestination(unittest.TestCase):
    ONLINE = {
        "ID": "peer-online",
        "HostName": "macbook-pro-m4-pro",
        "DNSName": "macbook-pro-m4-pro.tailnet.ts.net.",
        "TailscaleIPs": ["100.122.73.69", "fd7a:115c:a1e0::1"],
        "Online": True,
    }
    OFFLINE = {
        "ID": "peer-offline",
        "HostName": "old-macbook",
        "DNSName": "old-macbook.tailnet.ts.net.",
        "TailscaleIPs": ["100.96.246.30"],
        "Online": False,
    }

    def status(self, *peers):
        return {
            "BackendState": "Running",
            "CurrentTailnet": {"MagicDNSEnabled": True},
            "Self": {
                "ID": "self", "HostName": "mac-mini-m4",
                "DNSName": "mac-mini-m4.tailnet.ts.net.",
                "TailscaleIPs": ["100.93.90.11"], "Online": True,
            },
            "Peer": {peer["ID"]: peer for peer in peers},
        }

    def test_status_reads_running_json_despite_cli_warning(self):
        expected = self.status(self.ONLINE)
        completed = subprocess.CompletedProcess(
            [], 0, json.dumps(expected), "client/server version mismatch"
        )
        with mock.patch.object(session_peer.subprocess, "run", return_value=completed) as run:
            self.assertEqual(session_peer.tailscale_status(), expected)
        self.assertEqual(run.call_args.args[0], ["tailscale", "status", "--json"])

    def test_reply_host_prefers_self_magicdns(self):
        with mock.patch.object(session_peer, "tailscale_status", return_value=self.status(self.ONLINE)):
            self.assertEqual(session_peer.detect_reply_host(), "mac-mini-m4.tailnet.ts.net")

    def test_hostname_short_name_ip_and_username_resolve_to_magicdns(self):
        status = self.status(self.ONLINE)
        expected = "macbook-pro-m4-pro.tailnet.ts.net"
        for destination in (
            "macbook-pro-m4-pro", expected, expected + ".", "100.122.73.69"
        ):
            with self.subTest(destination=destination):
                self.assertEqual(session_peer.resolve_ssh_destination(destination, status), expected)
        self.assertEqual(
            session_peer.resolve_ssh_destination("alice@100.122.73.69", status),
            "alice@" + expected,
        )

    def test_known_offline_peer_fails_before_ssh(self):
        status = self.status(self.OFFLINE)
        with self.assertRaisesRegex(session_peer.CcPeerError, "offline"):
            session_peer.resolve_ssh_destination("old-macbook", status)

        output = io.StringIO()
        with mock.patch.object(session_peer, "tailscale_status", return_value=status), \
             mock.patch.object(session_peer, "run_remote") as remote, \
             contextlib.redirect_stdout(output):
            code = session_peer.main([
                "send", "--host", "old-macbook", "--to", "worker",
                "--no-from", "--no-reply-to", "--json", "hello",
            ])
        self.assertEqual(code, session_peer.EXIT_ERROR)
        self.assertIn("offline", json.loads(output.getvalue())["error"])
        remote.assert_not_called()

    def test_unknown_and_magicdns_disabled_destinations_remain_generic_ssh(self):
        status = self.status(self.ONLINE)
        self.assertEqual(session_peer.resolve_ssh_destination("build-alias", status), "build-alias")
        status["CurrentTailnet"]["MagicDNSEnabled"] = False
        self.assertEqual(
            session_peer.resolve_ssh_destination("100.122.73.69", status),
            "100.122.73.69",
        )

    def test_ambiguous_short_name_requires_full_magicdns(self):
        duplicate = {
            **self.ONLINE,
            "ID": "peer-duplicate",
            "DNSName": "macbook-pro-m4-pro.other.ts.net.",
            "TailscaleIPs": ["100.100.100.100"],
        }
        with self.assertRaisesRegex(session_peer.CcPeerError, "ambiguous"):
            session_peer.resolve_ssh_destination(
                "macbook-pro-m4-pro", self.status(self.ONLINE, duplicate)
            )

    def test_remote_send_uses_and_reports_canonical_destination(self):
        response = {"ok": True, "target": {"pid": 1, "name": "worker"}}
        output = io.StringIO()
        with mock.patch.object(session_peer, "tailscale_status", return_value=self.status(self.ONLINE)), \
             mock.patch.object(session_peer, "run_remote", return_value=response) as remote, \
             contextlib.redirect_stdout(output):
            code = session_peer.main([
                "send", "--host", "alice@100.122.73.69", "--to", "worker",
                "--no-from", "--no-reply-to", "--json", "hello",
            ])
        self.assertEqual(code, 0)
        expected = "alice@macbook-pro-m4-pro.tailnet.ts.net"
        self.assertEqual(remote.call_args.args[0], "alice@100.122.73.69")
        self.assertEqual(remote.call_args.args[1][:4], [
            "send", "--no-update-notice", "--to", "worker",
        ])
        self.assertEqual(remote.call_args.args[2], [
            "-o", "HostName=macbook-pro-m4-pro.tailnet.ts.net",
            "-o", "HostKeyAlias=100.122.73.69",
        ])
        result = json.loads(output.getvalue())
        self.assertEqual(result["host"], expected)
        self.assertEqual(result["sshHost"], "alice@100.122.73.69")

    def test_remote_list_and_update_check_use_the_same_verified_identity(self):
        expected = "macbook-pro-m4-pro.tailnet.ts.net"
        with mock.patch.object(session_peer, "tailscale_status", return_value=self.status(self.ONLINE)), \
             mock.patch.object(session_peer, "run_remote", return_value={"sessions": []}) as remote, \
             mock.patch.object(session_peer, "remote_installed_version", return_value="0.6.0") as version:
            for command in (["list"], ["update", "--check"]):
                with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()) as output:
                    code = session_peer.main([*command, "--host", "100.122.73.69", "--json"])
                self.assertEqual(code, 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result["host"], expected)
                self.assertEqual(result["sshHost"], "100.122.73.69")
                self.assertTrue(result["ok"])
                self.assertEqual(result["command"], command[0])
                self.assertEqual(result["schemaVersion"], 1)
        route = [
            "-o", "HostName=macbook-pro-m4-pro.tailnet.ts.net",
            "-o", "HostKeyAlias=100.122.73.69",
        ]
        remote.assert_called_once_with(
            "100.122.73.69", ["list", "--no-update-notice"], route
        )
        self.assertEqual([call.args[0] for call in version.call_args_list],
                         ["100.122.73.69", "100.122.73.69"])
        self.assertEqual([call.args[1] for call in version.call_args_list], [route, route])

    def test_magicdns_route_keeps_user_options_after_verified_overrides(self):
        self.assertEqual(
            session_peer.tailscale_ssh_options(
                "alice@100.122.73.69", "alice@macbook-pro-m4-pro.tailnet.ts.net"
            ) + ["-p", "2222"],
            [
                "-o", "HostName=macbook-pro-m4-pro.tailnet.ts.net",
                "-o", "HostKeyAlias=100.122.73.69", "-p", "2222",
            ],
        )
        self.assertEqual(session_peer.tailscale_ssh_options("build-alias", "build-alias"), [])


class ErrorHandling(unittest.TestCase):
    """Unhandled exceptions must not break the --json contract."""

    def test_main_catches_unexpected_exception_json(self):
        import io
        buf = io.StringIO()
        with mock.patch.object(session_peer, "build_parser") as bp:
            ns = argparse.Namespace(
                func=mock.Mock(side_effect=RuntimeError("boom")),
                json=True,
                command="list",
                host=[],
            )
            bp.return_value.parse_args.return_value = ns
            with mock.patch("builtins.print", side_effect=lambda *a, **kw: buf.write(a[0])):
                code = session_peer.main(["list", "--json"])
        result = json.loads(buf.getvalue())
        self.assertFalse(result["ok"])
        self.assertEqual(result["command"], "list")
        self.assertEqual(result["host"], session_peer.local_host())
        self.assertEqual(result["schemaVersion"], 1)
        self.assertIn("boom", result["error"])
        self.assertEqual(code, session_peer.EXIT_ERROR)

    def test_main_catches_unexpected_exception_human(self):
        import io
        buf = io.StringIO()
        with mock.patch.object(session_peer, "build_parser") as bp:
            ns = argparse.Namespace(
                func=mock.Mock(side_effect=RuntimeError("boom")),
                json=False,
                command="list",
                host=[],
            )
            bp.return_value.parse_args.return_value = ns
            with mock.patch("builtins.print", side_effect=lambda *a, **kw: buf.write(a[0])):
                code = session_peer.main(["list"])
        self.assertIn("boom", buf.getvalue())
        self.assertEqual(code, session_peer.EXIT_ERROR)

    def test_discover_survives_permission_error(self):
        with mock.patch("pathlib.Path.is_dir", return_value=True), \
             mock.patch("pathlib.Path.glob", side_effect=PermissionError):
            result = session_peer.discover()
        self.assertEqual(result, [])

    def test_remote_error_keeps_structured_codex_home_resolution(self):
        resolution = {"schemaVersion": 1, "status": "unknown", "selected": None,
                      "reason": "active_writer_unverified", "candidates": []}
        completed = subprocess.CompletedProcess(
            [], 1,
            stdout=json.dumps({"ok": False, "error": "ambiguous",
                               "codexHomeResolution": resolution}),
            stderr="",
        )
        with mock.patch.object(session_peer.Path, "read_text", return_value="source"), \
             mock.patch.object(session_peer.subprocess, "run", return_value=completed), \
             self.assertRaises(session_peer.CcPeerError) as caught:
            session_peer.run_remote("worker", ["send"], [])
        self.assertEqual(caught.exception.details["codexHomeResolution"], resolution)


class JsonResponseContract(unittest.TestCase):
    def assert_envelope(self, result, command, ok=True, host="local-node"):
        self.assertEqual(result["schemaVersion"], 1)
        self.assertIs(result["ok"], ok)
        self.assertEqual(result["host"], host)
        self.assertEqual(result["command"], command)

    def test_local_list_send_and_update_share_the_envelope(self):
        with mock.patch.object(session_peer.socket, "gethostname", return_value="local-node"):
            output = io.StringIO()
            with mock.patch.object(session_peer, "discover", return_value=[]), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(session_peer.main(["list", "--json"]), 0)
            listing = json.loads(output.getvalue())
            self.assert_envelope(listing, "list")
            self.assertEqual(listing["sessions"], [])

            output = io.StringIO()
            session = {"pid": 7, "name": "worker", "reachable": True,
                       "socket": "/tmp/7.sock", "alive": True}
            with mock.patch.object(session_peer, "discover", return_value=[session]), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(session_peer.main([
                    "send", "--to", "worker", "--dry-run", "--no-from",
                    "--no-reply-to", "--json", "hello",
                ]), 0)
            sending = json.loads(output.getvalue())
            self.assert_envelope(sending, "send")
            self.assertTrue(sending["dryRun"])

            output = io.StringIO()
            with mock.patch.object(session_peer, "installed_as_distribution", return_value=True), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(session_peer.main(["update", "--json"]), 0)
            updating = json.loads(output.getvalue())
            self.assert_envelope(updating, "update")
            self.assertEqual(updating["managedBy"], "package-manager")

    def test_command_wide_remote_failure_is_attributed_to_each_destination(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = session_peer.main([
                "send", "--host", "first", "--host", "second", "--to", "worker",
                "--no-from", "--no-reply-to", "--json", " ",
            ])
        results = json.loads(output.getvalue())
        self.assertEqual(code, session_peer.EXIT_ERROR)
        self.assertEqual([item["host"] for item in results], ["first", "second"])
        for item in results:
            self.assert_envelope(item, "send", ok=False, host=item["host"])
            self.assertIn("empty", item["error"])


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


class MultiHost(unittest.TestCase):
    """--host is repeatable: every host is visited, one failure does not stop the rest."""

    def test_list_iterates_over_hosts(self):
        calls = []
        def fake_remote(host, argv, opts):
            calls.append(host)
            return {"sessions": []}
        with mock.patch.object(session_peer, "run_remote", side_effect=fake_remote), \
             mock.patch.object(session_peer, "remote_installed_version", return_value=None):
            session_peer.cmd_list(argparse.Namespace(
                host=["hostA", "hostB"], ssh_opt=[], json=False, all=False))
        self.assertEqual(calls, ["hostA", "hostB"])

    def test_send_delivers_to_both_hosts(self):
        calls = []
        def fake_remote(host, argv, opts):
            calls.append(host)
            return {"ok": True, "target": {"pid": 1, "name": "w"}}
        with mock.patch.object(session_peer, "run_remote", side_effect=fake_remote):
            session_peer.cmd_send(argparse.Namespace(
                host=["hostA", "hostB"], ssh_opt=[], json=False,
                b64=None, message="hi", to="w", reply_to=None,
                no_reply_to=True, no_from=True, dry_run=False))
        self.assertEqual(calls, ["hostA", "hostB"])

    def test_one_failure_continues(self):
        def fail_then_ok(host, argv, opts):
            if host == "bad":
                raise session_peer.CcPeerError("unreachable")
            return {"sessions": []}
        with mock.patch.object(session_peer, "run_remote", side_effect=fail_then_ok), \
             mock.patch.object(session_peer, "remote_installed_version", return_value=None):
            code = session_peer.cmd_list(argparse.Namespace(
                host=["bad", "good"], ssh_opt=[], json=False, all=False))
        self.assertEqual(code, session_peer.EXIT_ERROR)

    def test_ssh_failure_details_survive_multi_host_results(self):
        failure = session_peer.CcPeerError(
            "SSH authentication failed for deploy@bad",
            {"sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
             "sshFailure": "authentication_failed"},
        )
        success = {
            "ok": True, "target": {"pid": 1, "name": "w"},
            "sshUser": "release", "sshUserSource": "explicit",
        }
        output = io.StringIO()
        with mock.patch.object(session_peer, "run_remote",
                               side_effect=[failure, success]), \
             mock.patch.object(session_peer, "tailscale_status", return_value=None), \
             contextlib.redirect_stdout(output):
            code = session_peer.main([
                "send", "--host", "bad", "--host", "release@good",
                "--to", "w", "--no-from", "--no-reply-to", "--json", "hi",
            ])
        results = json.loads(output.getvalue())
        self.assertEqual(code, session_peer.EXIT_ERROR)
        self.assertEqual(results[0]["sshFailure"], "authentication_failed")
        self.assertEqual(results[0]["sshUser"], "deploy")
        self.assertEqual(results[1]["sshUser"], "release")
        for result in results:
            self.assertEqual(result["schemaVersion"], 1)
            self.assertEqual(result["command"], "send")

    def test_single_host_send_json_is_flat(self):
        import io
        buf = io.StringIO()
        with mock.patch.object(session_peer, "run_remote",
                               return_value={"ok": True, "target": {"pid": 1, "name": "w"}}), \
             mock.patch("builtins.print", side_effect=lambda *a, **kw: buf.write(a[0])):
            session_peer.cmd_send(argparse.Namespace(
                host=["hostA"], ssh_opt=[], json=True,
                b64=None, message="hi", to="w", reply_to=None,
                no_reply_to=True, no_from=True, dry_run=False))
        result = json.loads(buf.getvalue())
        self.assertIsInstance(result, dict)
        self.assertNotIsInstance(result, list)
        self.assertTrue(result["ok"])
        self.assertEqual(result["host"], "hostA")
        self.assertEqual(result["command"], "send")
        self.assertEqual(result["schemaVersion"], 1)


class PushToRemote(unittest.TestCase):
    def test_builds_correct_ssh_command(self):
        fake_result = subprocess.CompletedProcess([], 0, stdout="session-peer 0.4.0\n", stderr="")
        with mock.patch("subprocess.run", return_value=fake_result) as run, \
             mock.patch("pathlib.Path.read_bytes", return_value=b"source"):
            version = session_peer.push_to_remote("web-01", ["-p", "2222"])
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "ssh")
        self.assertIn("-p", cmd)
        self.assertIn("web-01", cmd)
        self.assertIn("base64 -d", cmd[-1])
        self.assertEqual(version, "0.4.0")

    def test_validates_host(self):
        with self.assertRaises(session_peer.CcPeerError):
            session_peer.push_to_remote("-oProxyCommand=whoami", [])

    def test_update_host_pushes_when_outdated(self):
        with mock.patch.object(session_peer, "remote_installed_version", return_value="0.3.0"), \
             mock.patch.object(session_peer, "push_to_remote", return_value="0.4.0") as push, \
             mock.patch.object(session_peer, "ssh_user_metadata", return_value={
                 "sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
             }):
            session_peer.cmd_update(argparse.Namespace(
                host=["web-01"], ssh_opt=[], json=False, check=False))
        push.assert_called_once_with("web-01", [], {
            "sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
        })

    def test_update_host_skips_when_current(self):
        with mock.patch.object(session_peer, "remote_installed_version",
                               return_value=session_peer.__version__), \
             mock.patch.object(session_peer, "push_to_remote") as push, \
             mock.patch.object(session_peer, "ssh_user_metadata", return_value={
                 "sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
             }):
            session_peer.cmd_update(argparse.Namespace(
                host=["web-01"], ssh_opt=[], json=False, check=False))
        push.assert_not_called()

    def test_update_host_check_reports_only(self):
        with mock.patch.object(session_peer, "remote_installed_version", return_value="0.3.0"), \
             mock.patch.object(session_peer, "push_to_remote") as push, \
             mock.patch.object(session_peer, "ssh_user_metadata", return_value={
                 "sshUser": "deploy", "sshUserSource": "ssh_config_or_local_default",
             }):
            session_peer.cmd_update(argparse.Namespace(
                host=["web-01"], ssh_opt=[], json=False, check=True))
        push.assert_not_called()


class ClientUpdateNotice(unittest.TestCase):
    NOTICE = {
        "schemaVersion": 1,
        "status": "available",
        "current": "0.7.0",
        "latest": "0.7.1",
        "checkedAt": "2026-09-16T10:00:00Z",
        "source": "github_release_cache",
        "command": "session-peer update",
    }

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name) / "cache/session-peer/update.json"
        self.addCleanup(setattr, session_peer, "_CLIENT_UPDATE_NOTICE", None)

    @staticmethod
    def args(**overrides):
        values = {
            "command": "list", "host": [], "no_update_notice": False,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_stable_versions_are_strict(self):
        self.assertEqual(session_peer.stable_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(session_peer.stable_version("0.7.0"), (0, 7, 0))
        for value in ("1.2", "1.2.3.4", "1.2.3-rc1", "01.2.3", "latest", None):
            with self.subTest(value=value):
                self.assertIsNone(session_peer.stable_version(value))

    def test_latest_release_rejects_malformed_and_prerelease_responses(self):
        for response in (b"[]", b'{"tag_name":"v0.8.0-rc1"}'):
            with self.subTest(response=response), \
                 mock.patch.object(session_peer.urllib.request, "urlopen", return_value=io.BytesIO(response)), \
                 self.assertRaises(session_peer.CcPeerError):
                session_peer.latest_release()

    def test_fresh_newer_cache_produces_structured_notice(self):
        session_peer.write_update_cache("v0.7.1", self.cache, checked_at=1_000)
        with mock.patch.object(session_peer, "update_cache_path", return_value=self.cache), \
             mock.patch.object(session_peer, "installed_as_distribution", return_value=False):
            notice = session_peer.prepare_client_update(self.args(), now=1_001)
        self.assertEqual(notice, {
            **self.NOTICE, "checkedAt": "1970-01-01T00:16:40Z",
        })

    def test_current_expired_missing_and_malformed_states_are_explicit(self):
        session_peer.write_update_cache("0.7.0", self.cache, checked_at=1_000)
        self.assertEqual(session_peer.read_update_cache(self.cache, now=1_001)["status"], "fresh")
        self.assertEqual(
            session_peer.read_update_cache(
                self.cache, now=1_000 + session_peer.UPDATE_CACHE_TTL_SECONDS
            )["status"],
            "expired",
        )
        self.cache.unlink()
        self.assertEqual(session_peer.read_update_cache(self.cache, now=1_001), {"status": "missing"})
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_text("not json", encoding="utf-8")
        self.assertEqual(session_peer.read_update_cache(self.cache, now=1_001)["status"], "invalid")

    def test_stale_or_bad_cache_schedules_once_and_never_breaks_command(self):
        calls = []
        with mock.patch.object(session_peer, "update_cache_path", return_value=self.cache):
            self.assertIsNone(session_peer.prepare_client_update(
                self.args(), now=1_000, launcher=lambda: calls.append("refresh")
            ))
            self.assertIsNone(session_peer.prepare_client_update(
                self.args(), now=1_000, launcher=lambda: (_ for _ in ()).throw(OSError("no cache"))
            ))
        self.assertEqual(calls, ["refresh"])

    def test_opt_out_and_local_update_do_not_schedule_automatic_refresh(self):
        launch = mock.Mock()
        with mock.patch.object(session_peer, "update_cache_path", return_value=self.cache), \
             mock.patch.dict(os.environ, {session_peer.UPDATE_NOTICE_ENV: "1"}):
            self.assertIsNone(session_peer.prepare_client_update(self.args(), launcher=launch))
        self.assertIsNone(session_peer.prepare_client_update(
            self.args(no_update_notice=True), launcher=launch
        ))
        self.assertIsNone(session_peer.prepare_client_update(
            self.args(command="update"), launcher=launch
        ))
        launch.assert_not_called()

    def test_atomic_cache_is_private_and_background_lock_is_single_flight(self):
        session_peer.write_update_cache("0.6.3", self.cache, checked_at=1_000)
        if not session_peer.IS_WINDOWS:
            self.assertEqual(self.cache.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.cache.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.cache.parent.glob("*.tmp")), [])

        launches = []
        fake_popen = lambda *args, **kwargs: launches.append((args, kwargs))
        self.assertTrue(session_peer.schedule_update_refresh(
            self.cache, now=1_001, popen=fake_popen
        ))
        self.assertFalse(session_peer.schedule_update_refresh(
            self.cache, now=1_001, popen=fake_popen
        ))
        self.assertEqual(len(launches), 1)
        command = launches[0][0][0]
        self.assertEqual(command[-1], session_peer.UPDATE_REFRESH_ARG)

    def test_refresh_launcher_failure_releases_lock_for_a_later_attempt(self):
        def fail(*args, **kwargs):
            raise OSError("cannot launch")

        self.assertFalse(session_peer.schedule_update_refresh(
            self.cache, now=1_001, popen=fail
        ))
        self.assertFalse(session_peer.update_refresh_lock_path(self.cache).exists())
        self.assertTrue(session_peer.schedule_update_refresh(
            self.cache, now=1_002, popen=lambda *args, **kwargs: None
        ))

    def test_stale_lock_replacement_race_does_not_remove_the_winners_lock(self):
        lock = session_peer.update_refresh_lock_path(self.cache)
        lock.parent.mkdir(parents=True)
        lock.touch()
        os.utime(lock, (0, 0))
        original_open = os.open
        calls = 0

        def racing_open(path, flags, mode=0o777):
            nonlocal calls
            calls += 1
            if calls == 2:
                winner = original_open(path, flags, mode)
                os.close(winner)
                raise FileExistsError(path)
            return original_open(path, flags, mode)

        with mock.patch.object(session_peer.os, "open", side_effect=racing_open):
            self.assertFalse(session_peer.schedule_update_refresh(
                self.cache, now=session_peer.UPDATE_REFRESH_LOCK_SECONDS + 1,
                popen=lambda *args, **kwargs: None,
            ))
        self.assertTrue(lock.exists())

    def test_background_network_failure_is_silent_and_releases_lock(self):
        lock = session_peer.update_refresh_lock_path(self.cache)
        lock.parent.mkdir(parents=True)
        lock.touch()
        with mock.patch.object(session_peer, "update_cache_path", return_value=self.cache), \
             mock.patch.object(
                 session_peer, "latest_release", side_effect=session_peer.CcPeerError("timeout")
             ):
            self.assertEqual(session_peer.refresh_update_cache_background(), 0)
        self.assertFalse(lock.exists())
        self.assertFalse(self.cache.exists())

    def test_client_notice_preserves_dict_and_list_response_shapes(self):
        with mock.patch.object(session_peer, "_CLIENT_UPDATE_NOTICE", self.NOTICE):
            one = session_peer.with_client_update({"ok": True, "remoteVersion": "0.6.1"})
            many = session_peer.with_client_update([
                {"host": "a", "remoteVersion": "0.6.1"}, {"host": "b"},
            ])
        self.assertIsInstance(one, dict)
        self.assertEqual(one["remoteVersion"], "0.6.1")
        self.assertEqual(one["clientUpdate"], self.NOTICE)
        self.assertIsInstance(many, list)
        self.assertTrue(all(item["clientUpdate"] == self.NOTICE for item in many))

    def test_cli_json_and_human_notice_remain_separately_parseable(self):
        with mock.patch.object(session_peer, "prepare_client_update", return_value=self.NOTICE), \
             mock.patch.object(session_peer, "discover", return_value=[]), \
             mock.patch.object(session_peer.sys, "argv", ["session-peer", "list", "--json"]), \
             contextlib.redirect_stdout(io.StringIO()) as stdout, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(session_peer.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())["clientUpdate"], self.NOTICE)
        self.assertEqual(stderr.getvalue(), "")

        with mock.patch.object(session_peer, "prepare_client_update", return_value=self.NOTICE), \
             mock.patch.object(session_peer, "discover", return_value=[]), \
             mock.patch.object(session_peer.sys, "argv", ["session-peer", "list"]), \
             contextlib.redirect_stdout(io.StringIO()) as stdout, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(session_peer.main(), 0)
        self.assertIn("No reachable", stdout.getvalue())
        self.assertIn("Update available: 0.7.0", stderr.getvalue())

    def test_prepare_failure_never_changes_primary_cli_result(self):
        with mock.patch.object(
                 session_peer, "prepare_client_update", side_effect=OSError("cache unavailable")
             ), \
             mock.patch.object(session_peer, "discover", return_value=[]), \
             mock.patch.object(session_peer.sys, "argv", ["session-peer", "list", "--json"]), \
             contextlib.redirect_stdout(io.StringIO()) as stdout, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(session_peer.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue())["sessions"], [])
        self.assertEqual(stderr.getvalue(), "")

    def test_multi_host_cli_prepares_once_and_remote_calls_opt_out(self):
        prepare = mock.Mock(return_value=self.NOTICE)
        remote = mock.Mock(return_value={"sessions": []})
        with mock.patch.object(session_peer, "prepare_client_update", prepare), \
             mock.patch.object(session_peer, "tailscale_status", return_value={}), \
             mock.patch.object(session_peer, "run_remote", remote), \
             mock.patch.object(session_peer, "remote_installed_version", return_value="0.7.0"), \
             mock.patch.object(session_peer, "latest_release") as latest, \
             mock.patch.object(
                 session_peer.sys, "argv",
                 ["session-peer", "list", "--host", "one", "--host", "two", "--json"],
             ), \
             contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(session_peer.main(), 0)
        prepare.assert_called_once()
        latest.assert_not_called()
        self.assertEqual(remote.call_count, 2)
        self.assertTrue(all(
            call.args[1] == ["list", "--no-update-notice"]
            for call in remote.call_args_list
        ))
        result = json.loads(stdout.getvalue())
        self.assertEqual([item["host"] for item in result], ["one", "two"])
        self.assertTrue(all(item["clientUpdate"] == self.NOTICE for item in result))

    def test_package_manager_specific_update_commands(self):
        with mock.patch.object(session_peer, "installed_as_distribution", return_value=False):
            self.assertEqual(session_peer.update_command(), "session-peer update")
        cases = {
            "/home/me/.local/pipx/venvs/session-peer": "pipx upgrade session-peer",
            "/home/me/.local/share/uv/tools/session-peer": "uv tool upgrade session-peer",
            "/opt/session-peer-venv": "python -m pip install --upgrade session-peer",
        }
        for prefix, expected in cases.items():
            with self.subTest(prefix=prefix), \
                 mock.patch.object(session_peer, "installed_as_distribution", return_value=True), \
                 mock.patch.object(session_peer.sys, "prefix", prefix):
                self.assertEqual(session_peer.update_command(), expected)

    def test_help_exposes_notice_opt_out(self):
        for command in ("list", "send", "update"):
            self.assertIn(
                "--no-update-notice",
                session_peer.build_parser()._subparsers._group_actions[0]
                .choices[command].format_help(),
            )


class PackageManagement(unittest.TestCase):
    def test_package_update_does_not_download(self):
        import contextlib
        import io
        with mock.patch.object(session_peer, "installed_as_distribution", return_value=True), \
             mock.patch.object(session_peer, "latest_release") as latest, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(session_peer.main(["update", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue())["managedBy"], "package-manager")
        latest.assert_not_called()

    def test_package_update_check_refreshes_cache_and_reports_command(self):
        import contextlib
        import io
        args = argparse.Namespace(host=[], check=True, json=True)
        with mock.patch.object(session_peer, "installed_as_distribution", return_value=True), \
             mock.patch.object(session_peer, "update_command", return_value="pipx upgrade session-peer"), \
             mock.patch.object(session_peer, "latest_release", return_value=("v0.7.1", "url")), \
             mock.patch.object(session_peer, "write_update_cache") as write, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(session_peer.cmd_update(args), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result["outdated"])
        self.assertEqual(result["updateCommand"], "pipx upgrade session-peer")
        write.assert_called_once_with("v0.7.1")

    def test_new_reply_variable_precedes_legacy(self):
        with mock.patch.dict(os.environ, {"SESSION_PEER_REPLY_HOST": "alice@new", "CC_PEER_REPLY_HOST": "bob@old"}), \
             mock.patch.object(session_peer, "own_session", return_value={"name": "worker", "pid": 42}), \
             mock.patch.object(session_peer, "tailscale_status", return_value=None):
            self.assertEqual(session_peer.sender_identity(None), {
                "agent": "claude", "id": "worker", "target": "worker", "host": "alice@new"
            })


if __name__ == "__main__":
    unittest.main()
