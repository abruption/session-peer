"""Private budget plumbing: owned fake SSH only, no remote agent or model.

The profile callback here is a deliberate test double. It verifies dispatch
uses the owner's validator; it does not certify the future remote protocol.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import shlex
import signal
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import session_peer as peer


@unittest.skipIf(peer.IS_WINDOWS, "owned bounded POSIX SSH child")
class HandoffSshBackend(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="codex-handoff-ssh-",
            dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root.chmod(0o700)
        self.context = {"schemaVersion": 1, "phase": "effect",
            "requestId": "12345678-abcd-4abc-8abc-123456789abc", "agent": "codex",
            "target": "12345678-abcd-1234-abcd-123456789abc", "home": "/owned/home",
            "nativeContext": {"root": "/owned/home", "resolution": {}},
            "generation": None,
            "anchor": {"boot": "owned-boot", "monotonicMs": 1234},
            "remainingCutoffMs": 1000, "remainingTotalMs": 6000}
        self.native = {"ok": True, "target": {"agent": "codex", "id": self.context["target"]},
            "status": "queued", "submitted": True, "consumptionConfirmed": False,
            "queueId": "owned-queue-01", "codexHome": "/owned/home"}
        self.response = {"schemaVersion": 1, "ok": True, "command": "send", "host": "owned-remote",
            "handoffNative": {"schemaVersion": 1, "phase": "effect",
                "requestId": self.context["requestId"], "native": self.native,
                "nativeContext": self.context["nativeContext"]}}
        self.budget = (peer.handoff_now() + 3, peer.handoff_now() + 8)
        self.output = json.dumps(self.response).encode() + b"\n"

    def result(self, **changes):
        fields = dict(stdout=self.output, stderr=b"", returncode=0, reason=None,
            spawned=True, interrupted=False, stdout_overflow=False,
            stderr_overflow=False, cleanup_failed=False)
        fields.update(changes)
        return SimpleNamespace(**fields)

    def validator(self, result, context):
        self.assertEqual(context, self.context)
        if result != self.response:
            raise peer.CcPeerError("Owned callback rejected response")
        return dict(result)

    def invoke(self, outcome=None, host="operator@fixture", **options):
        with mock.patch.object(peer, "handoff_stream_child", return_value=outcome or self.result()) as child, \
                mock.patch.object(peer, "handoff_validate_remote_response", side_effect=self.validator, create=True) as validator:
            result = peer.run_remote(host, ["send", "--owned-test"], [],
                handoff_budget=self.budget, handoff_context=self.context, **options)
        return result, child, validator

    def test_complete_response_preserved_across_transport_and_diagnostic_failures(self):
        for changes in ({"returncode": 255, "stderr": b"\xff"},
                        {"returncode": -signal.SIGKILL, "reason": "process_deadline"},
                        {"reason": "stderr_capacity", "stderr_overflow": True},
                        {"reason": "process_interrupted", "interrupted": True},
                        {"cleanup_failed": True, "reason": "process_cleanup_failed"}):
            with self.subTest(changes=changes):
                result, child, validator = self.invoke(self.result(**changes))
                self.assertEqual(result["handoffNative"]["native"], self.native)
                self.assertEqual(result["sshUser"], "operator")
                self.assertEqual(child.call_count, 1)
                self.assertIsInstance(child.call_args.args[1], bytes)
                self.assertEqual(child.call_args.args[2:4], self.budget)
                validator.assert_called_once()

    def test_stdout_overflow_forbids_salvaging_valid_prefix(self):
        with mock.patch.object(peer, "handoff_stream_child", return_value=self.result(stdout_overflow=True)), \
                mock.patch.object(peer, "handoff_validate_remote_response", create=True) as validator, \
                self.assertRaises(peer.CcPeerError) as caught:
            peer.run_remote("operator@fixture", ["send"], [], handoff_budget=self.budget,
                            handoff_context=self.context)
        validator.assert_not_called()
        self.assertEqual(caught.exception.details["status"], "unknown")
        self.assertNotIn("submitted", caught.exception.details)

    def test_invalid_protocol_or_context_is_metadata_only_unknown(self):
        bad = [b"", self.output[:-2], self.output + b"extra", b"\xff" + self.output,
               self.output.replace(b'"ok": true', b'"ok": true, "ok": true', 1),
               self.output.replace(b'"queued"', b'"posted"', 1)]
        for output in bad:
            with self.subTest(output=output[:32]), \
                    mock.patch.object(peer, "handoff_stream_child", return_value=self.result(stdout=output)), \
                    mock.patch.object(peer, "handoff_validate_remote_response", side_effect=self.validator, create=True), \
                    self.assertRaises(peer.CcPeerError) as caught:
                peer.run_remote("operator@fixture", ["send"], [], handoff_budget=self.budget,
                                handoff_context=self.context)
            self.assertEqual(caught.exception.details["status"], "unknown")
            self.assertFalse(caught.exception.details["retryAllowed"])
            for absent in ("target", "submitted", "queueId", "handoffNative"):
                self.assertNotIn(absent, caught.exception.details)

    def test_spawn_tristate_never_infers_no_effect_from_constructor_uncertainty(self):
        for spawned in (False, None, True):
            with self.subTest(spawned=spawned), \
                    mock.patch.object(peer, "handoff_stream_child", return_value=self.result(stdout=b"", spawned=spawned)), \
                    self.assertRaises(peer.CcPeerError) as caught:
                peer.run_remote("operator@fixture", ["send"], [], handoff_budget=self.budget,
                                handoff_context=self.context)
            self.assertEqual(caught.exception.details["spawned"], spawned)
            self.assertEqual(caught.exception.details["status"], "refused" if spawned is False else "unknown")
            self.assertNotIn("submitted", caught.exception.details)

    def test_invalid_closed_request_rejected_before_config_or_effect(self):
        for edits in ({"capability": "sentinel"}, {"schemaVersion": True},
                      {"requestId": "not-an-id"}, {"anchor": {"boot": "x", "monotonicMs": True}},
                      {"remainingCutoffMs": 60001}, {"remainingTotalMs": 0},
                      {"generation": True}, {"generation": "x" * 129},
                      {"target": "bad\x1btarget"}):
            with self.subTest(edits=edits), mock.patch.object(peer, "handoff_stream_child") as child, \
                    self.assertRaises(peer.CcPeerError) as caught:
                peer.run_remote("fixture", ["send"], [], handoff_budget=self.budget,
                                handoff_context={**self.context, **edits})
            child.assert_not_called()
            self.assertIs(caught.exception.details["spawned"], False)
        for budget in (None, (True, 5), (float("nan"), 5), (10**1000, 10**1001), (5, 4)):
            with self.subTest(budget=str(budget)[:30]), mock.patch.object(peer, "handoff_stream_child") as child, \
                    self.assertRaises(peer.CcPeerError):
                peer.run_remote("fixture", ["send"], [], handoff_budget=budget,
                                handoff_context=self.context)
            child.assert_not_called()

    def test_config_uses_original_deadline_and_no_source_or_native_effect(self):
        config = self.result(stdout=b"user configured-user\nhostname owned\nport 22\n", returncode=0)
        with mock.patch.object(peer, "handoff_stream_child", return_value=config) as child:
            result = peer.ssh_user_metadata("fixture", [], handoff_budget=self.budget)
        self.assertEqual(result["sshUser"], "configured-user")
        self.assertEqual(child.call_args.args[:2], (["ssh", "-G", "fixture"], b""))
        self.assertLessEqual(child.call_args.args[2], self.budget[0])
        self.assertLessEqual(child.call_args.args[3], self.budget[1])
        for edits in ({"stdout_overflow": True}, {"interrupted": True}, {"stdout": b"\xff"}, {"returncode": 1}):
            with self.subTest(edits=edits), \
                    mock.patch.object(peer, "handoff_stream_child", return_value=self.result(**edits)), \
                    self.assertRaises(peer.CcPeerError) as caught:
                peer.ssh_user_metadata("fixture", [], handoff_budget=self.budget)
            self.assertIs(caught.exception.details["spawned"], False)

    def test_transport_threads_private_options_without_bypassing_identity(self):
        args = argparse.Namespace(ssh_opt=[], require_ssh_host_key="SHA256:" + "A" * 43,
                                  ssh_identity=False)
        with mock.patch.object(peer, "resolve_ssh_destination", return_value="fixture"), \
                mock.patch.object(peer, "tailscale_ssh_options", return_value=[]):
            transport = peer.SshTransport("fixture", args, {})
        with mock.patch.object(peer, "run_remote_with_identity", return_value={}) as pinned, \
                mock.patch.object(peer, "run_remote") as unpinned:
            transport.execute(["send"], handoff_budget=self.budget, handoff_context=self.context)
        unpinned.assert_not_called()
        self.assertEqual(pinned.call_args.kwargs, {"handoff_budget": self.budget, "handoff_context": self.context})

    def test_source_replaced_by_fifo_refuses_before_any_ssh_child(self):
        fifo = self.root / "source-fifo"
        os.mkfifo(fifo, 0o600)
        original_open = os.open
        source_path = str(Path(peer.__file__).resolve())
        def replaced(path, flags, *args, **kwargs):
            if str(path) == source_path:
                self.assertTrue(flags & os.O_NONBLOCK)
                return original_open(str(fifo), flags, *args, **kwargs)
            return original_open(path, flags, *args, **kwargs)
        with mock.patch.object(peer.os, "open", side_effect=replaced), \
                mock.patch.object(peer, "handoff_stream_child") as child, \
                self.assertRaises(peer.CcPeerError) as caught:
            peer.run_remote("operator@fixture", ["send"], [], handoff_budget=self.budget,
                            handoff_context=self.context)
        child.assert_not_called()
        self.assertIs(caught.exception.details["spawned"], False)
        self.assertEqual(caught.exception.details["reason"], "ssh_handoff_source_unavailable")

    def test_identity_wrapper_keeps_fixed_native_options_in_private_dispatch(self):
        configuration = {"destination": "owned", "port": 22, "keyLookupName": "owned"}
        fingerprint = "SHA256:" + "A" * 43
        receipt = {"schemaVersion": 1, "algorithm": "ssh-ed25519", "fingerprint": fingerprint,
                   "decision": "observed"}
        with mock.patch.object(peer, "ssh_identity_configuration", return_value=configuration) as config, \
                mock.patch.object(peer, "ssh_key_receipt", return_value=receipt), \
                mock.patch.object(peer, "_run_remote_dispatch", return_value=dict(self.response)) as dispatch:
            result = peer.run_remote_with_identity("fixture", ["send"], [], fingerprint,
                handoff_budget=self.budget, handoff_context=self.context)
        self.assertEqual(config.call_args.kwargs, {"handoff_budget": self.budget})
        self.assertEqual(dispatch.call_args.kwargs["handoff_budget"], self.budget)
        self.assertEqual(dispatch.call_args.kwargs["handoff_context"], self.context)
        fixed = dispatch.call_args.kwargs["identity_options"]
        for option in ("-oControlMaster=no", "-oControlPath=none", "-oStrictHostKeyChecking=yes",
                       "-oHostKeyAlias=session-peer-pinned", "-oUserKnownHostsFile=none"):
            self.assertIn(option, fixed)
        self.assertEqual(result["sshIdentity"]["status"], "verified")

    def test_probe_context_cannot_carry_effect_deadline_or_authority(self):
        probe = {**self.context, "phase": "probe", "anchor": None,
                 "remainingCutoffMs": None, "remainingTotalMs": None}
        peer.ssh_handoff_request(self.budget, probe)
        for edit in ({"anchor": self.context["anchor"]}, {"remainingTotalMs": 2000},
                     {"receipt": {}}, {"handoff": {}}):
            with self.subTest(edit=edit), self.assertRaises(peer.CcPeerError):
                peer.ssh_handoff_request(self.budget, {**probe, **edit})

    def test_complete_probe_response_interruption_cannot_enable_later_effect(self):
        context = {**self.context, "phase": "probe", "anchor": None,
                   "remainingCutoffMs": None, "remainingTotalMs": None}
        response = {**self.response, "handoffNative": {**self.response["handoffNative"], "phase": "probe"}}
        outcome = self.result(stdout=json.dumps(response).encode(), interrupted=True,
                              reason="process_interrupted")
        with mock.patch.object(peer, "handoff_stream_child", return_value=outcome) as child, \
                mock.patch.object(peer, "handoff_validate_remote_response", create=True) as validator, \
                self.assertRaises(peer.CcPeerError) as caught:
            peer.run_remote("operator@fixture", ["send"], [], handoff_budget=self.budget,
                            handoff_context=context)
        self.assertEqual(child.call_count, 1)
        validator.assert_not_called()
        self.assertEqual(caught.exception.details["reason"], "ssh_handoff_probe_interrupted")
        self.assertIs(caught.exception.details["interrupted"], True)
        self.assertNotIn("submitted", caught.exception.details)

    def test_identity_requires_context_before_configuration_child(self):
        with mock.patch.object(peer, "ssh_identity_configuration") as config, \
                mock.patch.object(peer, "handoff_stream_child") as child, \
                self.assertRaises(peer.CcPeerError) as caught:
            peer.run_remote_with_identity("fixture", ["send"], [], handoff_budget=self.budget)
        self.assertIs(caught.exception.details["spawned"], False)
        config.assert_not_called()
        child.assert_not_called()

    def test_complete_config_eof_then_owned_kill_keeps_raw_code_consistently(self):
        config = self.result(stdout=b"user operator\nhostname owned\nport 22\nhostkeyalias none\nknownhostscommand none\n",
                             returncode=-signal.SIGKILL)
        with mock.patch.object(peer, "handoff_stream_child", return_value=config):
            result = peer.ssh_identity_configuration("fixture", [], handoff_budget=self.budget)
            metadata = peer.ssh_user_metadata("fixture", [], handoff_budget=self.budget)
        self.assertEqual(result, {"destination": "owned", "port": 22, "keyLookupName": "owned"})
        self.assertEqual(metadata["sshUser"], "operator")
        self.assertEqual(config.returncode, -signal.SIGKILL)

    def test_owned_fake_ssh_streams_source_and_preserves_complete_exit255(self):
        script = self.root / "fake-ssh.py"
        script.write_text("import os,sys\nsource=sys.stdin.buffer.read()\n"
            + "assert source.startswith(b'#!/usr/bin/env python3') and len(source)<4194305\n"
            + "os.write(1," + repr(self.output) + ")\nos.write(2,b'\\xff\\xfe')\nraise SystemExit(255)\n")
        launcher = self.root / "fake-ssh"
        launcher.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(script)) + ' "$@"\n')
        launcher.chmod(0o700)
        actual = peer.handoff_stream_child
        def child(argv, source, cutoff, total, clock):
            self.assertEqual(argv[0], "ssh")
            return actual([str(launcher), *argv[1:]], source, cutoff, total, clock,
                env={"PATH": "/usr/bin:/bin", "HOME": str(self.root), "LANG": "C.UTF-8"})
        with mock.patch.object(peer, "handoff_stream_child", side_effect=child), \
                mock.patch.object(peer, "handoff_validate_remote_response", side_effect=self.validator, create=True):
            result = peer.run_remote("operator@fixture", ["send"], [], handoff_budget=self.budget,
                                     handoff_context=self.context)
        self.assertEqual(result["handoffNative"]["native"], self.native)
