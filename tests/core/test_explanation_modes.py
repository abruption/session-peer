"""New modes reuse existing facts; no extra probes or native submission."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import session_peer as peer


class ExplanationModes(unittest.TestCase):
    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = peer.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_doctor_reuses_exactly_one_existing_payload_and_keeps_default_json(self):
        payload = {"status": "partial", "claude": {"status": "available"},
                   "capabilities": {"agents": {"claude": {"send": True, "wake": False, "wait": False, "ack": False}}}}
        with mock.patch.object(peer, "doctor_payload", return_value=payload) as doctor, \
                mock.patch.object(peer, "render_doctor", return_value="Existing diagnostics"), \
                mock.patch.object(peer.subprocess, "Popen", side_effect=AssertionError("extra process")):
            code, plain, _ = self.invoke(["doctor", "--no-update-notice"])
            self.assertEqual(code, 0)
            self.assertNotIn("Delivery capabilities", plain)
            code, explained, _ = self.invoke(["doctor", "--explain", "--no-update-notice"])
            self.assertEqual(code, 0)
            self.assertIn("Delivery capabilities", explained)
            self.assertIn("not per-target readiness", explained)
            self.assertIn("not a delivery observation", explained)
            self.assertEqual(doctor.call_count, 2)
            code, encoded, _ = self.invoke(["doctor", "--json", "--no-update-notice"])
            self.assertEqual(code, 0)
            self.assertNotIn("deliveryExplanation", json.loads(encoded))
            self.assertNotIn("Delivery capabilities", encoded)

    def test_remote_doctor_explains_each_existing_response_without_extra_ssh(self):
        payload = {"status": "partial", "capabilities": {"agents": {}}, "host": "remote"}
        with mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "SshTransport") as transport, \
                mock.patch.object(peer, "render_doctor", return_value="Existing remote diagnostics"):
            transport.return_value.host = "resolved"
            transport.return_value.ssh_opts = []
            transport.return_value.execute.return_value = payload
            code, output, _ = self.invoke(["doctor", "--host", "one", "--host", "two", "--explain", "--no-update-notice"])
        self.assertEqual(code, 0)
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(transport.return_value.execute.call_count, 2)
        self.assertTrue(all("--explain" not in c.args[0] for c in transport.return_value.execute.call_args_list))
        self.assertEqual(output.count("Delivery capabilities"), 2)

    def test_new_json_combinations_fail_before_advisory_or_destination_work(self):
        for argv in (["doctor", "--explain", "--json"],
                     ["handoff", "status", "--correlation-id", "00000000-0000-4000-8000-000000000001", "--explain", "--json"]):
            with mock.patch.object(peer, "prepare_client_update") as updates, \
                    mock.patch.object(peer, "prepare_skill_updates") as skills, \
                    mock.patch.object(peer, "HandoffLedger") as ledger, \
                    mock.patch.object(peer, "doctor_payload") as doctor, \
                    mock.patch.object(peer.sys, "argv", ["session-peer", *argv]), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                peer.main()
            self.assertEqual(error.exception.code, 2)
            for operation in (updates, skills, ledger, doctor):
                operation.assert_not_called()

    def test_remote_doctor_partial_failure_still_explains_each_host(self):
        payload = {"status": "partial", "capabilities": {"agents": {}}}
        with mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "SshTransport") as transport, \
                mock.patch.object(peer, "render_doctor", return_value="Existing diagnostics"):
            transport.return_value.host = "resolved"
            transport.return_value.ssh_opts = []
            transport.return_value.execute.side_effect = [payload, peer.CcPeerError("fixture transport failed")]
            code, output, err = self.invoke(["doctor", "--host", "one", "--host", "two", "--explain", "--no-update-notice"])
        self.assertEqual(code, 1)
        self.assertEqual(transport.return_value.execute.call_count, 2)
        self.assertEqual(output.count("Delivery capabilities"), 1)
        self.assertEqual(err.count("Delivery capabilities"), 1)
        self.assertIn("unknown (not reported", err)

    @unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "local POSIX ledger")
    def test_status_explain_clock_is_readonly_and_legacy_failure_never_retries(self):
        epoch = "00000000-0000-4000-8000-000000000001"
        correlation = "00000000-0000-4000-8000-000000000002"
        public = {"submission": {"status": "submitted"}, "observation": {"status": "unsupported"},
                  "ack": {"status": "pending"}, "wait": {"status": "not_requested"}}
        record = {"capability": {"revoked": False}, "ack": None}
        for response in ({"ok": True, "clockEpoch": epoch}, peer.handoff_error("receipt_operation_refused")):
            with mock.patch.object(peer.HandoffLedger, "record", return_value=(epoch, record)) as read, \
                    mock.patch.object(peer.HandoffLedger, "_save", side_effect=AssertionError("history write")), \
                    mock.patch.object(peer, "handoff_public", return_value=public) as projection, \
                    mock.patch.object(peer, "handoff_ipc", side_effect=response if isinstance(response, Exception) else None,
                                      return_value=response) as ipc, \
                    mock.patch.object(peer, "handoff_collector", side_effect=AssertionError("collector start")):
                code, _, _ = self.invoke(["handoff", "status", "--correlation-id", correlation, "--explain"])
            self.assertEqual(code, 0)
            read.assert_called_once_with(correlation, read_only=True)
            self.assertEqual(ipc.call_count, 1)
            self.assertEqual(ipc.call_args.args[1], {"op": "clock", "readOnly": True})
            self.assertEqual(projection.call_args.args[2], None if isinstance(response, Exception) else epoch)

    @unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "local POSIX ledger")
    def test_handoff_explanation_never_persists_retention_or_creates_authority(self):
        with tempfile.TemporaryDirectory(prefix="codex-explain-", dir=os.environ.get("SESSION_PEER_TEST_TMP")) as directory:
            root = Path(directory).resolve() / "ledger"
            ledger = peer.HandoffLedger(root)
            ledger.initialize()
            _, record = ledger.prepare({"agent": "claude", "destination": ["local"],
                "target": str(os.getpid()), "home": None, "payloadDigest": "a" * 64}, "tg1:" + "b" * 64)
            before = {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in root.iterdir()}
            with mock.patch.object(peer, "handoff_root", return_value=root), \
                    mock.patch.object(peer.HandoffLedger, "_save", side_effect=AssertionError("history write")), \
                    mock.patch.object(peer, "handoff_collector", side_effect=AssertionError("collector launch")), \
                    mock.patch.object(peer, "handoff_ipc", side_effect=AssertionError("unneeded IPC")), \
                    mock.patch.object(peer, "post_to_socket", side_effect=AssertionError("native post")), \
                    mock.patch.object(peer.subprocess, "Popen", side_effect=AssertionError("child process")):
                code, output, _ = self.invoke(["handoff", "status", "--correlation-id", record["id"], "--explain"])
            self.assertEqual(code, 0)
            self.assertIn("existing intent snapshot", output)
            self.assertIn("Task completion: unknown", output)
            self.assertIn("Submission: not_attempted", output)
            after = {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in root.iterdir()}
            self.assertTrue(before == after, "explanation mutated history")

    @unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "local POSIX ledger")
    def test_missing_handoff_explanation_does_not_initialize_history(self):
        with tempfile.TemporaryDirectory(prefix="codex-explain-", dir=os.environ.get("SESSION_PEER_TEST_TMP")) as directory:
            root = Path(directory).resolve() / "missing"
            with mock.patch.object(peer, "handoff_root", return_value=root):
                code, _, err = self.invoke(["handoff", "status", "--correlation-id", "00000000-0000-4000-8000-000000000001", "--explain"])
            self.assertEqual(code, 1)
            self.assertIn("unknown", err)
            self.assertFalse(root.exists())
