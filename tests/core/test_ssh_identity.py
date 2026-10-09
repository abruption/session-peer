"""No real hosts: native helper subprocess + fake connection/response fixtures."""
import argparse
import base64
import hashlib
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


@unittest.skipIf(peer.IS_WINDOWS, "POSIX KnownHostsCommand only")
class SshIdentity(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="codex-ssh-identity-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.kind = "ssh-ed25519"
        # Public-key-format synthetic bytes, not a usable private credential.
        raw = len(self.kind).to_bytes(4, "big") + self.kind.encode() + b"\x00\x00\x00\x20" + b"x" * 32
        self.blob = base64.b64encode(raw).decode()
        self.fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
        self.helper = self.root / "helper.py"
        self.helper.write_text(peer.SSH_IDENTITY_HELPER, encoding="utf-8")
        self.receipt = self.root / "receipt.json"
        self.config = {"destination": "fixture.example", "port": 2222, "keyLookupName": "fixture-key"}

    def run_helper(self, expected, phase="HOSTNAME", kind=None, blob=None):
        return subprocess.run([sys.executable, "-I", str(self.helper), str(self.receipt), expected,
                               phase, self.kind if kind is None else kind, self.blob if blob is None else blob],
                              capture_output=True)

    def test_native_helper_correct_wrong_key_and_order(self):
        out = self.run_helper(self.fingerprint)
        self.assertEqual(out.returncode, 0)
        self.assertEqual(out.stdout.decode().strip(), f"session-peer-pinned {self.kind} {self.blob}")
        self.assertEqual(peer.ssh_key_receipt(self.receipt)["fingerprint"], self.fingerprint)
        self.assertEqual(self.receipt.stat().st_mode & 0o777, 0o600)
        out = self.run_helper("SHA256:" + "A" * 43)
        self.assertEqual(out.returncode, 0)
        self.assertEqual(out.stdout, b"")
        self.assertEqual(peer.ssh_key_receipt(self.receipt)["decision"], "refused")
        out = self.run_helper("-", phase="ORDER", kind="", blob="")
        self.assertEqual(out.returncode, 0)
        out = self.run_helper("-")
        self.assertEqual(out.stdout, b"")

    def test_helper_rejects_unsupported_type_and_malformed_no_reflection(self):
        for kind, blob in (("host-cert-v01@openssh.com", self.blob),
                           (self.kind, "invalid ; diagnostic"), (self.kind, "eA==")):
            out = self.run_helper(self.fingerprint, kind=kind, blob=blob)
            self.assertNotEqual(out.returncode, 0)
            self.assertEqual(out.stdout, b"")
            self.assertEqual(out.stderr, b"")

    def callback(self, result, expected=None, fail=False):
        def dispatch(host, argv, opts, *, identity_options):
            self.assertEqual(host, "fixture")
            self.assertIn("-oControlPath=none", identity_options)
            self.assertIn("-oStrictHostKeyChecking=yes", identity_options)
            line = next(v.split("=", 1)[1] for v in identity_options if v.startswith("-oKnownHostsCommand="))
            self.assertTrue(line.endswith("'%I' '%t' '%K'"))
            # These native expansions are enums and base64, not remote stderr.
            parts = shlex.split(line)
            parts[-3:] = ["HOSTNAME", self.kind, self.blob]
            run = subprocess.run(parts, capture_output=True)
            self.assertEqual(run.returncode, 0)
            if fail:
                raise peer.CcPeerError("synthetic SSH auth failure", {"sshFailure": "authentication_failed"})
            if expected:
                self.assertIn("-oUserKnownHostsFile=none", identity_options)
                self.assertIn("-oHostKeyAlias=session-peer-pinned", identity_options)
                self.assertIn(b"session-peer-pinned", run.stdout)
            return dict(result)
        return dispatch

    def test_complete_success_verifies_callback_in_same_dispatch(self):
        native = {"schemaVersion": 1, "command": "send", "ok": True,
                  "target": {"pid": 10, "name": "fixture"}, "chars": 4}
        with mock.patch.object(peer, "ssh_identity_configuration", return_value=self.config), \
                mock.patch.object(peer, "_run_remote_dispatch",
                                  side_effect=self.callback(native, self.fingerprint)) as dispatch:
            result = peer.run_remote_with_identity("fixture", ["send"], [], self.fingerprint)
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(result["sshIdentity"]["status"], "verified")
        self.assertEqual(result["sshIdentity"]["fingerprint"], self.fingerprint)
        self.assertNotIn("submitted", result)  # Do not invent absent Claude fields.

    def test_callback_without_remote_success_is_only_observed(self):
        with mock.patch.object(peer, "ssh_identity_configuration", return_value=self.config), \
                mock.patch.object(peer, "_run_remote_dispatch", side_effect=self.callback({}, fail=True)):
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.run_remote_with_identity("fixture", ["send"], [])
        self.assertEqual(caught.exception.details["sshIdentity"]["status"], "observed")
        self.assertEqual(caught.exception.details["sshFailure"], "authentication_failed")

    def test_missing_receipt_keeps_valid_submission_facts_no_retry(self):
        native = {"ok": True, "status": "queued", "submitted": True,
                  "queueId": "native-q", "target": {"agent": "codex", "session": "fixture"}}
        with mock.patch.object(peer, "ssh_identity_configuration", return_value=self.config), \
                mock.patch.object(peer, "_run_remote_dispatch", return_value=native):
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.run_remote_with_identity("fixture", ["send"], [], self.fingerprint)
        self.assertEqual(caught.exception.details["submitted"], True)
        self.assertEqual(caught.exception.details["queueId"], "native-q")
        self.assertFalse(caught.exception.details["retryAllowed"])
        self.assertEqual(caught.exception.details["reason"], "ssh_identity_evidence_unavailable")

    def test_custom_known_hosts_command_unavailable_config_bounds(self):
        for body, reason in (("hostname fixture\nport 22\nknownhostscommand unsafe command\n",
                              "unsupported_ssh_identity_config"),
                             ("hostname fixture\nport 99999\n", "ssh_identity_config_unavailable"),
                             ("hostname fixture\nport 22\n".encode() + b"\xff", "ssh_identity_config_unavailable")):
            completed = subprocess.CompletedProcess([], 0, body, b"")
            with mock.patch.object(peer.subprocess, "run", return_value=completed):
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.ssh_identity_configuration("fixture", [])
            self.assertEqual(caught.exception.details["reason"], reason)

    def test_public_cli_allowlist_remains_closed_and_invalid_modes_refuse(self):
        for option in ("-oKnownHostsCommand=anything", "-oUserKnownHostsFile=anything",
                       "-oStrictHostKeyChecking=no", "-oControlPath=anything"):
            with self.assertRaises(peer.CcPeerError):
                peer.check_ssh_options([option])
        for args, reason in ((argparse.Namespace(ssh_identity=True, host=[], command="list"),
                               "ssh_identity_requires_host"),
                              (argparse.Namespace(ssh_identity=True, host=["fixture"], command="update"),
                               "unsupported_ssh_identity_operation"),
                              (argparse.Namespace(require_ssh_host_key="bad", host=["fixture"], command="send"),
                               "invalid_ssh_host_key")):
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.validate_ssh_identity_options(args)
            self.assertEqual(caught.exception.details["reason"], reason)

    def test_legacy_dispatch_unchanged_and_native_ssh_config_accepts_fixed_options(self):
        with mock.patch.object(peer, "_run_remote_dispatch", return_value={"ok": True}) as dispatch:
            peer.run_remote("fixture", ["list"], [])
        dispatch.assert_called_once_with("fixture", ["list"], [])
        # Native -G is read-only and -F /dev/null excludes personal configuration.
        completed = subprocess.run(["ssh", "-G", "-F", os.devnull,
                                    "-oControlMaster=no", "-oControlPath=none", "-oControlPersist=no",
                                    "-oStrictHostKeyChecking=yes", "-oUserKnownHostsFile=none",
                                    "-oGlobalKnownHostsFile=none", "-oHostKeyAlias=session-peer-pinned",
                                    "-oKnownHostsCommand=" + sys.executable + " -I fixture '%I' '%t' '%K'",
                                    "fixture.invalid"], capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
        self.assertIn(b"stricthostkeychecking true", completed.stdout)


if __name__ == "__main__":
    unittest.main()

