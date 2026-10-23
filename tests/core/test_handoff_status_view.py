"""Read-only status snapshots; private fixtures, no native sessions or messages."""
import contextlib
import copy
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


@unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "private POSIX ledger only")
class HandoffStatusView(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(
            prefix="codex-status-", dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ledger = peer.HandoffLedger(self.root / "ledger")
        self.epoch = self.ledger.initialize()
        self.binding = {"agent": "claude", "destination": ["local"],
                        "target": str(os.getpid()), "home": None, "payloadDigest": "a" * 64}
        self.epoch, self.record = self.ledger.prepare(self.binding, "tg1:" + "a" * 64)
        self.correlation = self.record["id"]

    def snapshot(self, root=None):
        root = root or self.ledger.root
        if not root.exists():
            return None
        return {path.name: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
                for path in root.iterdir() if path.is_file()}

    def status(self, *, as_json=True, root=None, correlation=None):
        command = ["handoff", "status", "--correlation-id", correlation or self.correlation]
        if as_json:
            command.append("--json")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(peer, "handoff_root", return_value=root or self.ledger.root))
            # Any of these would turn inspection into an effect or durable write.
            for owner, name in ((peer.HandoffLedger, "_save"), (peer, "handoff_wait"),
                                (peer, "post_to_socket"), (peer, "handoff_codex_submit"),
                                (peer.subprocess, "Popen")):
                stack.enter_context(mock.patch.object(owner, name, side_effect=AssertionError("status performed an effect")))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            code = peer.main(command)
        return code, json.loads(out.getvalue()) if as_json and out.getvalue() else out.getvalue(), err.getvalue()

    def submitted(self, wait_status=None, acknowledged=False):
        with self.ledger.transaction() as state:
            record = state["records"][self.correlation]
            record.update(phase="terminal", submission="submitted", observe=True, ackRequested=True,
                          native={"ok": True, "target": {"pid": os.getpid(), "name": "native-private-sentinel"},
                                  "chars": 4, "dryRun": False})
            if wait_status:
                wait = {"for": "acknowledged", "status": wait_status,
                        "operationId": str(peer.uuid.uuid4()), "deadlineAtUtcMs": 1234,
                        "deadlineNs": 1234000000, "clockEpoch": None}
                if wait_status == "stopped":
                    wait["reason"] = "stopped_by_operator"
                record["waits"].append(wait)
            if acknowledged:
                record["ack"] = {"status": "acknowledged", "assurance": "operator_confirmed",
                                 "receivedAtUtcMs": 5678, "late": True,
                                 "receiptId": None, "classifiedClockEpoch": None}
        return self.ledger.record(self.correlation, read_only=True)[1]

    def test_json_preserves_existing_native_and_public_shape_without_writes(self):
        record = self.submitted("timed_out_unknown", acknowledged=True)
        before = self.snapshot()
        with mock.patch.object(peer.HandoffLedger, "record", autospec=True,
                               wraps=None, side_effect=lambda ledger, correlation, **kw:
                               (self.epoch, copy.deepcopy(record))) as lookup:
            code, result, _ = self.status()
        lookup.assert_called_once()
        self.assertTrue(lookup.call_args.kwargs.get("read_only"))
        expected = dict(record["native"])
        expected.update(schemaVersion=1, host=peer.local_host(), command="handoff", ok=True,
                        handoff=peer.handoff_public(self.epoch, record))
        self.assertEqual(code, 0)
        self.assertTrue(result == expected, "status changed the public snapshot")
        self.assertTrue(before == self.snapshot(), "status changed durable history")

    def test_json_and_text_actual_lookup_preserve_bytes_inode_and_mtime(self):
        before = self.snapshot()
        for as_json in (True, False):
            with self.subTest(as_json=as_json):
                code, result, _ = self.status(as_json=as_json)
                self.assertEqual(code, 0)
                self.assertTrue(before == self.snapshot(), "status changed durable history")
                if not as_json:
                    for label in ("State:", "Submission:", "Injection observation:", "Receipt (ACK):",
                                  "Latest wait:", "Retry:", "Next actions:"):
                        self.assertIn(label, result)

    def test_late_receipt_and_original_timeout_are_both_visible(self):
        self.submitted("timed_out_unknown", acknowledged=True)
        before = self.snapshot()
        code, output, _ = self.status(as_json=False)
        self.assertEqual(code, 0)
        for fact in ("Receipt (ACK): acknowledged", "Latest wait: timed_out_unknown; goal: acknowledged",
                     "Assurance: operator_confirmed", "Received at (UTC milliseconds): 5678", "Late receipt: yes"):
            self.assertIn(fact, output)
        self.assertNotIn("native-private-sentinel", output)
        self.assertTrue(before == self.snapshot(), "late receipt inspection changed history")

    def test_on_time_receipt_is_distinguished_from_late_receipt(self):
        self.submitted("satisfied", acknowledged=True)
        with self.ledger.transaction() as state:
            state["records"][self.correlation]["ack"]["late"] = False
        before = self.snapshot()
        code, text, _ = self.status(as_json=False)
        self.assertEqual(code, 0)
        self.assertIn("Late receipt: no", text)
        self.assertNotIn("Late receipt: yes", text)
        self.assertIn("Latest wait: satisfied; goal: acknowledged", text)
        self.assertTrue(before == self.snapshot(), "on-time receipt inspection changed history")

    def test_only_latest_wait_is_rendered_and_previous_wait_remains_unchanged(self):
        record = self.submitted("timed_out_unknown", acknowledged=True)
        previous = copy.deepcopy(record["waits"][0])
        current = {**previous, "status": "satisfied", "operationId": str(peer.uuid.uuid4()),
                   "deadlineAtUtcMs": 6789, "deadlineNs": 6789000000}
        with self.ledger.transaction() as state:
            state["records"][self.correlation]["waits"].append(current)
        before = self.snapshot()
        code, text, _ = self.status(as_json=False)
        self.assertEqual(code, 0)
        self.assertIn("Operation: " + current["operationId"], text)
        self.assertNotIn(previous["operationId"], text)
        self.assertIn("Latest wait: satisfied; goal: acknowledged", text)
        self.assertNotIn("Latest wait: timed_out_unknown", text)
        _, result, _ = self.status()
        self.assertEqual(result["handoff"]["wait"]["operationId"], current["operationId"])
        self.assertTrue(self.ledger.record(self.correlation, read_only=True)[1]["waits"][0] == previous,
                        "previous wait changed")
        self.assertTrue(before == self.snapshot(), "latest wait inspection changed history")

    def test_stopped_wait_status_query_is_success_and_keeps_submission(self):
        self.submitted("stopped")
        before = self.snapshot()
        code, result, _ = self.status()
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["handoff"]["submission"], {"status": "submitted"})
        self.assertEqual(result["handoff"]["wait"]["status"], "stopped")
        self.assertEqual(result["handoff"]["wait"]["reason"], "stopped_by_operator")
        self.assertTrue(before == self.snapshot(), "query rewrote stopped wait")

    def test_unsupported_evidence_does_not_advertise_wait_or_retry(self):
        self.submitted("unsupported")
        before = self.snapshot()
        code, result, _ = self.status()
        self.assertEqual(code, 0)
        public = result["handoff"]
        self.assertEqual(public["ack"]["status"], "unsupported")
        self.assertEqual(public["observation"], {"status": "unsupported", "injectionObserved": False})
        self.assertEqual(public["nextActions"], ["reconcile"])
        _, text, _ = self.status(as_json=False)
        self.assertIn("Receipt (ACK): unsupported", text)
        self.assertIn("Retry: not allowed", text)
        self.assertNotIn("keep_waiting", text)
        self.assertTrue(before == self.snapshot(), "unsupported status changed history")

    def test_retention_projects_tombstone_without_saving_it(self):
        boot = "b" * 64
        with self.ledger.transaction() as state:
            record = state["records"][self.correlation]
            record.update(historyBoot=boot, createdNs=1)
        before = self.snapshot()
        with mock.patch.object(peer, "handoff_boot_clock", return_value=boot), \
                mock.patch.object(peer, "handoff_now_ns", return_value=1 + 30 * 86400 * 1000000000):
            code, result, _ = self.status()
            _, text, _ = self.status(as_json=False)
        self.assertEqual(code, 0)
        self.assertEqual(result["handoff"]["state"], "unknown")
        self.assertEqual(result["handoff"]["nextActions"], ["reconcile"])
        self.assertIn("retained effect fence", text.lower())
        self.assertIn("expired detail", text.lower())
        self.assertTrue(before == self.snapshot(), "status persisted retention projection")

    def test_quarantined_history_caution_without_repair(self):
        prior = self.submitted("timed_out_unknown", acknowledged=True)
        self.ledger.quarantine_restored()
        before = self.snapshot()
        code, text, _ = self.status(as_json=False)
        self.assertEqual(code, 0)
        self.assertIn("quarantin", text.lower())
        self.assertIn("reconcile", text)
        _, result, _ = self.status()
        self.assertEqual(result["handoff"]["submission"], {"status": "unknown"})
        self.assertEqual(result["handoff"]["state"], "timed_out_unknown")
        expected_wait = {key: value for key, value in prior["waits"][-1].items()
                         if key not in ("deadlineNs", "clockEpoch")}
        self.assertTrue(result["handoff"]["wait"] == expected_wait, "quarantine status changed original wait")
        self.assertTrue(before == self.snapshot(), "status repaired quarantined history")

    def test_quarantined_satisfied_wait_preserves_existing_refusal_without_repair(self):
        # Existing #181 gate: quarantine removes ACK, but preserves terminal
        # waits; the frozen public schema cannot represent satisfied without
        # ACK. A presentation change must not fabricate ACK or rewrite waits.
        self.submitted("satisfied", acknowledged=True)
        self.ledger.quarantine_restored()
        before = self.snapshot()
        for as_json in (True, False):
            code, output, error = self.status(as_json=as_json)
            self.assertEqual(code, 1)
            if as_json:
                self.assertEqual(output["reason"], "invalid_handoff")
                self.assertNotIn("handoff", output)
            else:
                self.assertIn("Handoff operation refused", error)
            self.assertTrue(before == self.snapshot(), "query rewrote quarantined terminal wait")

    def test_missing_corrupt_and_unknown_id_keep_query_errors_and_initialize_nothing(self):
        missing = self.root / "missing"
        for context, root, correlation in (("ledger_missing", missing, self.correlation),
                                           ("id_unknown", self.ledger.root, str(peer.uuid.uuid4()))):
            with self.subTest(context=context):
                before = self.snapshot(root)
                code, result, _ = self.status(root=root, correlation=correlation)
                self.assertEqual(code, 1)
                self.assertTrue(result == peer.handoff_query_error(correlation, context), "query envelope changed")
                self.assertTrue(before == self.snapshot(root), "query initialized or changed history")
        path = self.ledger.root / "ledger.json"
        path.write_bytes(b"{invalid")
        before = self.snapshot()
        code, result, _ = self.status()
        self.assertEqual(code, 1)
        self.assertEqual(result["handoffQuery"]["context"], "ledger_corrupt")
        self.assertNotIn("handoff", result)
        self.assertNotIn("ledgerEpoch", result)
        self.assertTrue(before == self.snapshot(), "query repaired corrupt history")

    def test_read_only_transaction_discards_local_mutation_default_still_saves(self):
        before = self.snapshot()
        with self.ledger.transaction(read_only=True) as state:
            state["records"][self.correlation]["observe"] = True
        self.assertTrue(before == self.snapshot(), "read-only transaction saved")
        with self.ledger.transaction() as state:
            state["records"][self.correlation]["observe"] = True
        self.assertTrue(self.ledger.record(self.correlation, read_only=True)[1]["observe"])

    def test_keyboard_interrupt_during_read_does_not_save(self):
        before = self.snapshot()
        with mock.patch.object(peer, "handoff_boot_clock", side_effect=KeyboardInterrupt):
            code, _, _ = self.status(as_json=False)
        self.assertEqual(code, 130)
        self.assertTrue(before == self.snapshot(), "interrupted read saved history")

    def test_keyboard_interrupt_after_snapshot_does_not_save(self):
        before = self.snapshot()
        with mock.patch.object(peer, "handoff_public", side_effect=KeyboardInterrupt):
            code, _, _ = self.status(as_json=False)
        self.assertEqual(code, 130)
        self.assertTrue(before == self.snapshot(), "completed read saved before interruption")

    def test_lost_history_never_displays_no_ack_requested_as_historical_fact(self):
        self.submitted("timed_out_unknown", acknowledged=True)
        self.ledger.quarantine_restored()
        _, text, _ = self.status(as_json=False)
        self.assertIn("Receipt (ACK): unavailable (quarantined history)", text)
        self.assertIn("Injection observation: unavailable (quarantined history)", text)
        with self.ledger.transaction() as state:
            state["records"][self.correlation].update(historyBoot="b" * 64, createdNs=1)
        before = self.snapshot()
        with mock.patch.object(peer, "handoff_boot_clock", return_value="b" * 64), \
                mock.patch.object(peer, "handoff_now_ns", return_value=1 + 30 * 86400 * 1000000000):
            _, text, _ = self.status(as_json=False)
        self.assertIn("Receipt (ACK): unavailable (expired history)", text)
        self.assertNotIn("Receipt (ACK): not_requested", text)
        self.assertIn("Latest wait: unavailable (expired history)", text)
        self.assertNotIn("Latest wait: not_requested", text)
        self.assertNotIn("  Operation:", text)
        self.assertTrue(before == self.snapshot(), "history presentation persisted retention")

    def test_pending_receipt_without_collector_does_not_offer_wait_or_launch(self):
        clock = str(peer.uuid.uuid4())
        peer.handoff_collect(self.ledger, clock, {"op": "mint", "ledgerEpoch": self.epoch,
                             "correlationId": self.correlation, "targetGeneration": self.record["generation"]})
        self.submitted()
        before = self.snapshot()
        code, text, _ = self.status(as_json=False)
        self.assertEqual(code, 0)
        self.assertIn("pending; waiting availability not established", text)
        self.assertNotIn("keep_waiting", text)
        self.assertTrue(before == self.snapshot(), "missing collector changed history")
        with self.ledger.transaction() as state:
            state["records"][self.correlation]["capability"]["revoked"] = True
        with mock.patch.object(peer, "handoff_channel_epoch", side_effect=AssertionError("revoked clock probe")):
            self.assertEqual(self.status()[0], 0)

    def test_read_only_clock_frame_strictness_and_total_budget(self):
        before = self.snapshot()
        for frame in ({"op": "clock", "readOnly": 1}, {"op": "clock", "readOnly": False},
                      {"op": "clock", "readOnly": True, "extra": True}):
            with self.assertRaises(peer.CcPeerError), \
                    mock.patch.object(peer.HandoffLedger, "_save", side_effect=AssertionError("invalid clock saved")):
                peer.handoff_collect(self.ledger, str(peer.uuid.uuid4()), frame)
        self.assertTrue(before == self.snapshot(), "invalid query wrote history")
        with mock.patch.object(peer, "handoff_now", return_value=100), \
                mock.patch.object(peer, "handoff_ipc", side_effect=peer.handoff_error("receipt_channel_unavailable")) as ipc:
            self.assertIsNone(peer.handoff_channel_epoch(self.ledger, read_only=True))
        ipc.assert_called_once_with(self.ledger.root, {"op": "clock", "readOnly": True}, 102)

    def test_read_only_collector_clock_query_does_not_save(self):
        before = self.snapshot()
        clock = str(peer.uuid.uuid4())
        with mock.patch.object(peer.HandoffLedger, "_save", side_effect=AssertionError("clock query saved")):
            result = peer.handoff_collect(self.ledger, clock, {"op": "clock", "readOnly": True})
        self.assertEqual(result["clockEpoch"], clock)
        self.assertTrue(before == self.snapshot(), "clock query changed history")

    def test_read_only_clock_over_private_socket_preserves_history(self):
        clock = str(peer.uuid.uuid4())
        before = self.snapshot()
        errors, frames = [], []
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        path = self.ledger.root / "receipt.sock"
        server.bind(str(path))
        path.chmod(0o600)
        server.listen(1)
        server.settimeout(3)

        def serve_once():
            try:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(3)
                    raw = bytearray()
                    while True:
                        chunk = connection.recv(1024)
                        if not chunk:
                            break
                        raw.extend(chunk)
                    frame = peer.handoff_json(bytes(raw), 4096)
                    frames.append(frame)
                    connection.sendall(peer.HandoffLedger.encode(peer.handoff_collect(self.ledger, clock, frame)))
            except BaseException as error:
                errors.append(type(error).__name__)

        worker = threading.Thread(target=serve_once, daemon=True)
        with mock.patch.object(peer.HandoffLedger, "_save", side_effect=AssertionError("clock query saved")):
            worker.start()
            result = peer.handoff_channel_epoch(self.ledger, read_only=True)
            worker.join(4)
        self.assertFalse(worker.is_alive(), "clock fixture did not terminate")
        self.assertEqual(errors, [])
        self.assertEqual(frames, [{"op": "clock", "readOnly": True}])
        self.assertEqual(result, clock)
        self.assertTrue(before == self.snapshot(), "IPC clock query changed durable history")

    def test_status_pending_authority_requests_only_read_only_clock(self):
        clock = str(peer.uuid.uuid4())
        peer.handoff_collect(self.ledger, clock, {"op": "mint", "ledgerEpoch": self.epoch,
                             "correlationId": self.correlation, "targetGeneration": self.record["generation"]})
        self.submitted()
        before = self.snapshot()
        with mock.patch.object(peer, "handoff_ipc", return_value={"clockEpoch": clock}) as ipc:
            code, result, _ = self.status()
        self.assertEqual(code, 0)
        ipc.assert_called_once()
        self.assertEqual(ipc.call_args.args[1], {"op": "clock", "readOnly": True})
        self.assertIn("keep_waiting", result["handoff"]["nextActions"])
        self.assertTrue(before == self.snapshot(), "clock validation changed history")
        with mock.patch.object(peer, "handoff_ipc", side_effect=peer.handoff_error("invalid_receipt")) as ipc:
            code, result, _ = self.status()
        self.assertEqual(code, 0)
        self.assertEqual(ipc.call_count, 1, "legacy clock was retried")
        self.assertNotIn("keep_waiting", result["handoff"]["nextActions"])

    def test_recovered_clock_does_not_reopen_history_unavailable_wait(self):
        clock = str(peer.uuid.uuid4())
        peer.handoff_collect(self.ledger, clock, {"op": "mint", "ledgerEpoch": self.epoch,
                             "correlationId": self.correlation, "targetGeneration": self.record["generation"]})
        self.submitted("failed")
        with self.ledger.transaction() as state:
            state["records"][self.correlation]["waits"][-1]["reason"] = "history_unavailable"
        before = self.snapshot()
        with mock.patch.object(peer, "handoff_ipc", return_value={"clockEpoch": clock}):
            code, result, _ = self.status()
        self.assertEqual(code, 0)
        public = result["handoff"]
        self.assertEqual(public["submission"], {"status": "submitted"})
        self.assertEqual(public["wait"]["status"], "failed")
        self.assertEqual(public["wait"]["reason"], "history_unavailable")
        self.assertEqual(public["nextActions"], ["reconcile"])
        self.assertTrue(before == self.snapshot(), "recovered clock changed terminal wait")

    def test_legacy_clock_handler_rejects_new_frame_before_saving(self):
        def legacy_clock_or_receipt(frame):
            # Pinned 87e46e8 handoff_collect entry: a legacy exact clock frame
            # returned inside transaction; other non-mint/non-classify frames
            # went to private_wire. The new clock frame takes that rejection
            # path before the contextmanager reaches its write-through save.
            with self.ledger.transaction():
                if frame == {"op": "clock"}:
                    return {"ok": True, "clockEpoch": str(peer.uuid.uuid4())}
                return peer.handoff_private_wire(peer.HandoffLedger.encode(frame))

        before = self.snapshot()
        with mock.patch.object(peer.HandoffLedger, "_save", side_effect=AssertionError("legacy saved")), \
                self.assertRaises(peer.CcPeerError) as caught:
            legacy_clock_or_receipt({"op": "clock", "readOnly": True})
        self.assertEqual(caught.exception.details.get("reason"), "invalid_receipt")
        self.assertTrue(before == self.snapshot(), "legacy rejection saved history")

    def test_renderer_validates_snapshot_and_never_reflects_untrusted_values(self):
        public = peer.handoff_public(self.epoch, self.record)
        for mutate in (lambda value: value.update(state="\x1b[31muntrusted"),
                       lambda value: value.update(body="private-body-sentinel"),
                       lambda value: value["ack"].update(status="future_status"),
                       lambda value: value["retry"].update(allowed=True)):
            candidate = copy.deepcopy(public)
            mutate(candidate)
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.handoff_status_text(candidate, "prepared")
            self.assertNotIn("\x1b", str(caught.exception))
            self.assertNotIn("private-body-sentinel", str(caught.exception))

    def test_renderer_omits_private_native_fields_and_unsafe_phase_text(self):
        public = peer.handoff_public(self.epoch, self.record)
        with self.assertRaises(peer.CcPeerError) as caught:
            peer.handoff_status_text(public, "\x1b[31mprivate-phase")
        self.assertNotIn("\x1b", str(caught.exception))
        self.assertNotIn("private-phase", str(caught.exception))
        text = peer.handoff_status_text(public, "prepared")
        self.assertNotIn("\x1b", text)
        self.assertIn(self.correlation, text)
        for private in (self.epoch, self.record["generation"], self.binding["payloadDigest"]):
            self.assertNotIn(private, text)
