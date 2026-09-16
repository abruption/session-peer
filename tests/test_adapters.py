"""Agent/transport contract and standalone extension regressions."""
import argparse
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import session_peer as peer
import session_peer_mcp as mcp
from tests.fixtures.agent_adapter import install


class Contracts(unittest.TestCase):
    def setUp(self):
        registry = peer.AgentRegistry()
        registry.register(peer.ClaudeAdapter())
        registry.register(peer.CodexAdapter())
        patcher = mock.patch.object(peer, "AGENTS", registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        install(peer)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.args = peer.build_parser().parse_args([
            "send", "--to", "fixture:one", "--message", "hello", "--no-from",
            "--no-reply-to", "--output-format", "json", "--codex-home", str(self.home)])
        self.claude = {"agent": "claude", "pid": 7, "name": "worker", "reachable": True,
                       "alive": True, "status": "idle", "cwd": "/fixture", "socket": "/unused"}
        self.codex = {"agent": "codex", "id": "01900000-0000-7000-8000-000000000001",
                      "archived": False, "codexHome": str(self.home), "updatedAt": 1}

    def invoke(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = peer.main(argv)
        return code, json.loads(out.getvalue())

    def test_builtin_discovery_and_submission_shared_contract(self):
        for name, row, target in (("claude", self.claude, "worker"),
                                  ("codex", self.codex, "codex:" + self.codex["id"]),
                                  ("fixture", {"agent": "fixture", "id": "one"}, "fixture:one")):
            with self.subTest(agent=name), \
                 mock.patch.object(peer, "discover", return_value=[self.claude]), \
                 mock.patch.object(peer, "collect_codex_listing", return_value={
                     "sessions": [self.codex], "discovery": {"status": "ok"}}), \
                 mock.patch.object(peer, "queue_codex", return_value={
                     "ok": True, "status": "queued", "submitted": True,
                     "consumptionConfirmed": False, "queueId": "one"}) as queue, \
                 mock.patch.object(peer, "post_to_socket") as post:
                adapter = peer.AGENTS.get(name)
                self.args.to = target
                self.args.all = False
                result = peer.LocalTransport().execute("list", adapter, self.args)
                self.assertEqual(result["sessions"][0]["agent"], name)
                identity = adapter.identity(target, peer.ExecutionContext("host", self.args))
                self.assertEqual((identity.agent, identity.host), (name, "host"))
                if name == "codex":
                    self.assertEqual(identity.codex_home, str(self.home))
                sent = peer.LocalTransport().execute("send", adapter, self.args, "hello")
                self.assertTrue(sent["ok"])
                self.assertFalse(sent.get("consumptionConfirmed", False))
                self.assertEqual(queue.call_count, int(name == "codex"))
                self.assertEqual(post.call_count, int(name == "claude"))

    def test_third_adapter_cli_and_reply_roundtrip(self):
        code, result = self.invoke(["list", "--agent", "fixture", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(result["sessions"][0]["id"], "one")
        uri = peer.reply_address({"agent": "fixture", "id": "one"}, local=True)
        self.assertEqual(peer.parse_reply_address(uri)["target"], "fixture:one")
        code, result = self.invoke(["send", "--to", uri, "-m", "hello\nworld",
                                    "--no-from", "--no-reply-to", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(result["body"], "hello\nworld")
        self.assertFalse(result["consumptionConfirmed"])
        self.assertEqual(result["addressResolution"]["transport"], "local")

    def test_capabilities_diagnostics_and_unsupported_wake(self):
        with mock.patch.object(peer, "diagnose_claude", return_value={"status": "available"}), \
             mock.patch.object(peer, "diagnose_codex", return_value={"status": "available"}):
            result = peer.doctor_payload(self.args)
        self.assertEqual(result["fixture"]["status"], "available")
        caps = result["capabilities"]["agents"]
        self.assertTrue(caps["codex"]["wake"])
        for name in peer.AGENTS.names():
            self.assertFalse(caps[name]["wait"])
            self.assertFalse(caps[name]["ack"])
        adapter = peer.AGENTS.get("fixture")
        with mock.patch.object(adapter, "submit") as submit:
            self.args.wake = True
            with self.assertRaises(peer.CcPeerError):
                peer.LocalTransport().execute("send", adapter, self.args, "hello")
            submit.assert_not_called()
        for operation in ("wait", "ack", "shell"):
            with self.subTest(operation=operation), self.assertRaises(peer.AdapterError):
                peer.LocalTransport().execute(operation, adapter, self.args)

    def test_registration_rejects_invalid_contract_without_mutation(self):
        registry = peer.AgentRegistry()
        for attr, value in (("name", "bad:name"), ("name", None), ("contract_version", 2),
                            ("contract_version", True), ("capabilities", {}), ("submit", None)):
            adapter = peer.ClaudeAdapter()
            setattr(adapter, attr, value)
            with self.subTest(attr=attr), self.assertRaises(peer.AdapterError):
                registry.register(adapter)
            self.assertEqual(registry.names(), ())
        registry.register(peer.ClaudeAdapter())
        with self.assertRaises(peer.AdapterError):
            registry.register(peer.ClaudeAdapter())
        with self.assertRaises(peer.AdapterError):
            registry.register(peer.AgentAdapter())

    def test_unknown_agents_and_legacy_colon_names(self):
        self.assertEqual(peer.AGENTS.for_target("team:worker").name, "claude")
        self.assertEqual(peer.AGENTS.for_target("claude:worker").name, "claude")
        with self.assertRaises(peer.AdapterError):
            peer.AGENTS.get("missing")
        with self.assertRaises(peer.AdapterError):
            peer.parse_reply_address("session-peer://v1/reply?agent=missing&session=a&transport=local")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            peer.build_parser().parse_args(["list", "--agent", "missing"])

    def test_adapter_failure_and_malformed_results_preserve_other_rows(self):
        for failure in (ValueError("secret-token"), None):
            with self.subTest(failure=type(failure)), \
                 mock.patch.object(peer, "discover", return_value=[self.claude]), \
                 mock.patch.object(peer, "collect_codex_listing", return_value={
                     "sessions": [], "discovery": {"status": "not_installed"}}), \
                 mock.patch.object(peer.AGENTS.get("fixture"), "list",
                                   side_effect=failure, return_value={"sessions": "bad"}):
                code, result = self.invoke(["list", "--json"])
            self.assertEqual(code, 1)
            self.assertEqual(result["sessions"][0]["agent"], "claude")
            self.assertEqual(result["discovery"]["fixture"]["status"], "error")
            self.assertNotIn("secret-token", json.dumps(result))

    def test_submission_failure_is_unknown_and_never_retried(self):
        adapter = peer.AGENTS.get("fixture")
        for failure, value in ((RuntimeError("secret"), None), (None, []), (None, {}), (None, {"ok": "yes"})):
            with mock.patch.object(adapter, "submit", side_effect=failure, return_value=value) as submit:
                with self.assertRaises(peer.AdapterError) as raised:
                    peer.LocalTransport().execute("send", adapter, self.args, "hello")
                self.assertEqual(raised.exception.details["reason"], "outcome_unknown")
                self.assertNotIn("secret", str(raised.exception))
                submit.assert_called_once()

    def test_streamed_source_supports_third_adapter_without_dispatch_changes(self):
        source = Path(peer.__file__).read_text()
        fixture = (Path(__file__).parent / "fixtures/agent_adapter.py").read_text()
        marker = 'if __name__ == "__main__":'
        source = source.replace(marker, fixture + '\ninstall(sys.modules[__name__])\n\n' + marker)
        original_run = subprocess.run
        env = dict(os.environ, HOME=str(self.home), SESSION_PEER_NO_UPDATE_NOTICE="1")
        calls = []

        def ssh(command, **kwargs):
            calls.append(command)
            remote = shlex.split(command[-1])
            self.assertEqual(remote[:2], ["python3", "-"])
            return original_run([sys.executable, "-", *remote[2:]], input=source,
                                text=True, capture_output=True, env=env, timeout=20)

        with mock.patch.object(peer, "resolve_ssh_destination", return_value="resolved"), \
             mock.patch.object(peer, "tailscale_ssh_options", return_value=[]), \
             mock.patch.object(peer, "ssh_user_metadata", return_value={}), \
             mock.patch.object(peer.subprocess, "run", side_effect=ssh):
            transport = peer.SshTransport("test-host", self.args, {})
            listed = transport.execute(["list", "--agent", "fixture", "--no-update-notice"])
            sent = transport.execute(["send", "--to", "fixture:one", "--message", "a 'quote'\n$(literal)",
                                      "--no-from", "--no-reply-to", "--no-update-notice"])
        self.assertEqual(listed["sessions"][0]["agent"], "fixture")
        self.assertEqual(sent["body"], "a 'quote'\n$(literal)")
        self.assertEqual(len(calls), 2)

    def test_remote_partial_failure_keeps_not_installed_diagnostic(self):
        payload = {"schemaVersion": 1, "command": "list", "ok": False,
                   "sessions": [], "discovery": {
                       "claude": {"status": "error", "error": "unavailable"},
                       "codex": {"status": "not_installed"}}, "error": "Discovery failed"}
        with mock.patch.object(peer, "ssh_user_metadata", return_value={}), \
             mock.patch.object(peer.subprocess, "run", return_value=subprocess.CompletedProcess(
                 [], 1, json.dumps(payload), "")):
            self.assertEqual(peer.run_remote("test-host", ["list"], []), payload)

    def test_mcp_policy_uses_registry_and_retains_capability_checks(self):
        config = self.home / "policy.json"
        config.write_text(json.dumps({"schemaVersion": 1, "destinations": {
            "fixture": {"agents": ["fixture"], "capabilities": ["list", "send"]}}}))
        adapter = mcp.Adapter(mcp.load_policy(str(config)))
        with mock.patch.object(adapter, "invoke", new_callable=mock.AsyncMock, return_value={"ok": True}) as invoke:
            asyncio.run(adapter.send_message("fixture", "fixture:one", "hello"))
            self.assertIn("fixture:one", invoke.call_args.args[0])
            with self.assertRaises(mcp.PolicyError):
                asyncio.run(adapter.send_message("fixture", "fixture:one", "hello", wake=True))
            self.assertEqual(invoke.call_count, 1)

    def test_reply_uri_cannot_switch_agent_via_target(self):
        code, result = self.invoke(["send", "--to",
            "session-peer://v1/reply?agent=claude&session=fixture%3Aone&transport=local",
            "--message", "hello", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "invalid_target")

    def test_disabled_list_and_send_do_not_invoke_adapter(self):
        adapter = peer.AGENTS.get("fixture")
        adapter.capabilities = peer.AgentCapabilities(list=False, send=False)
        with mock.patch.object(adapter, "list") as listing, mock.patch.object(adapter, "submit") as submit:
            for operation in ("list", "send"):
                with self.subTest(operation=operation), self.assertRaises(peer.AdapterError):
                    peer.LocalTransport().execute(operation, adapter, self.args, "hello")
            listing.assert_not_called()
            submit.assert_not_called()

    def test_preflight_exception_is_redacted_before_submission(self):
        adapter = peer.AGENTS.get("fixture")
        with mock.patch.object(adapter, "validate_send", side_effect=RuntimeError("secret")), \
             mock.patch.object(adapter, "submit") as submit:
            code, result = self.invoke(["send", "--to", "fixture:one", "--message", "hello", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "adapter_failed")
        self.assertNotIn("secret", json.dumps(result))
        submit.assert_not_called()

    def test_remote_submission_partial_failure_retains_native_facts(self):
        payload = {"schemaVersion": 1, "command": "send", "ok": False,
                   "submitted": True, "queueId": "fixture-one", "error": "later failure"}
        with mock.patch.object(peer, "ssh_user_metadata", return_value={}), \
             mock.patch.object(peer.subprocess, "run", return_value=subprocess.CompletedProcess(
                 [], 1, json.dumps(payload), "")) as run:
            self.assertEqual(peer.run_remote("test-host", ["send"], []), payload)
        run.assert_called_once()
