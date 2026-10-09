"""Owned POSIX IPC, disk fencing and receipt tests; no native agent sessions.

The inbox below is a test-process Unix socket. It exercises actual credential
and birth checks, not Claude consumption, a model's reply, or Codex observation.
"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import session_peer as peer


@unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "private POSIX collector only")
class HandoffRuntime(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="codex-ho-", dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.ledger = peer.HandoffLedger(self.root / "ledger")
        self.epoch = self.ledger.initialize()
        self.generation = "tg1:" + "a" * 64
        self.binding = {"agent": "claude", "destination": ["local"], "target": str(os.getpid()), "home": None, "payloadDigest": "a" * 64}
        self.epoch, self.record = self.ledger.prepare(self.binding, self.generation)
        self.correlation = self.record["id"]
        self.clock = "collector-epoch"

    def mint(self):
        minted = peer.handoff_collect(self.ledger, self.clock, {"op": "mint", "ledgerEpoch": self.epoch,
                         "correlationId": self.correlation, "targetGeneration": self.generation})
        self.frame = {"schemaVersion": 1, "kind": "receipt", "ledgerEpoch": self.epoch,
                      "correlationId": self.correlation, "targetGeneration": self.generation,
                      "receiptId": str(peer.uuid.uuid4()), "capability": minted["capability"]}
        return minted

    def submitted(self):
        with self.ledger.transaction() as state:
            record = state["records"][self.correlation]
            record.update(phase="terminal", submission="submitted", ackRequested=True,
                          native={"ok": True, "target": {"pid": os.getpid(), "name": "fixture"}, "chars": 4, "dryRun": False})

    def record_now(self):
        return self.ledger.record(self.correlation)[1]

    def test_private_atomic_storage_and_hash_only_capability(self):
        self.mint()
        raw = (self.ledger.root / "ledger.json").read_bytes()
        self.assertNotIn(self.frame["capability"].encode(), raw)
        self.assertNotIn("capability", peer.handoff_public(self.epoch, self.record))
        for path in (self.ledger.root / "ledger.json", self.ledger.root / "ledger.lock"):
            self.assertEqual(path.stat().st_mode & 0o077, 0)
        with self.assertRaises(peer.CcPeerError):
            self.ledger.initialize()

    def test_receipt_requires_positive_submission_and_exact_authority(self):
        self.mint()
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_collect(self.ledger, self.clock, self.frame)
        self.submitted()
        for changes in ({"targetGeneration": "successor"}, {"correlationId": str(peer.uuid.uuid4())},
                        {"ledgerEpoch": str(peer.uuid.uuid4())}, {"capability": "A" * 43}):
            with self.subTest(changes=changes), self.assertRaises(peer.CcPeerError):
                peer.handoff_collect(self.ledger, self.clock, {**self.frame, **changes})
        self.assertIsNone(self.record_now()["ack"])
        result = peer.handoff_collect(self.ledger, self.clock, self.frame)
        self.assertFalse(result["duplicate"])
        public = peer.handoff_public(self.epoch, self.record_now())
        self.assertEqual(public["state"], "acknowledged")
        self.assertEqual(public["ack"]["assurance"], "token_possession")
        self.assertFalse(public["observation"]["injectionObserved"])

    def test_duplicate_after_expiry_still_requires_original_token(self):
        self.mint()
        self.submitted()
        peer.handoff_collect(self.ledger, self.clock, self.frame)
        prior = self.record_now()["ack"]
        with self.ledger.transaction() as state:
            state["records"][self.correlation]["capability"]["expiresNs"] = 0
        self.assertTrue(peer.handoff_collect(self.ledger, "new-clock", self.frame)["duplicate"])
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_collect(self.ledger, self.clock, {**self.frame, "capability": "A" * 43})
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_collect(self.ledger, self.clock, {**self.frame, "receiptId": str(peer.uuid.uuid4())})
        self.assertEqual(prior, self.record_now()["ack"])

    def test_expiry_and_uncommitted_restart_do_not_ack(self):
        self.mint()
        self.submitted()
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_collect(self.ledger, "new-collector", self.frame)
        with self.ledger.transaction() as state:
            state["records"][self.correlation]["capability"]["expiresNs"] = 0
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_collect(self.ledger, self.clock, self.frame)
        self.assertIsNone(self.record_now()["ack"])

    def test_committed_receipt_survives_new_collector_clock(self):
        self.mint()
        self.submitted()
        peer.handoff_collect(self.ledger, self.clock, self.frame)
        state = peer.handoff_public(self.epoch, self.record_now())
        self.assertTrue(peer.handoff_collect(self.ledger, "restarted-clock", self.frame)["duplicate"])
        self.assertEqual(state, peer.handoff_public(self.epoch, self.record_now()))

    def test_late_receipt_never_rewrites_terminal_wait(self):
        self.mint()
        self.submitted()
        deadline = time.monotonic() - 1
        with self.ledger.transaction() as state:
            record = state["records"][self.correlation]
            peer.handoff_start_wait(record, "acknowledged", deadline, self.clock, initial_status="timed_out_unknown")
        original = self.record_now()["waits"][0].copy()
        peer.handoff_collect(self.ledger, self.clock, self.frame)
        record = self.record_now()
        self.assertEqual(record["waits"][0], original)
        self.assertTrue(record["ack"]["late"])
        self.assertEqual(peer.handoff_wait(self.ledger, self.correlation, "acknowledged", 6), 0)
        self.assertEqual(len(self.record_now()["waits"]), 2)
        self.assertEqual(self.record_now()["waits"][0], original)
        self.assertTrue(self.record_now()["ack"]["late"])

    def test_unknown_ordering_refuses_receipt_and_manual_confirmation(self):
        self.mint()
        self.submitted()
        with self.ledger.transaction() as state:
            peer.handoff_start_wait(state["records"][self.correlation], "acknowledged", time.monotonic() + 10, "other-clock")
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_collect(self.ledger, self.clock, self.frame)
        confirm = {key: self.frame[key] for key in ("schemaVersion", "ledgerEpoch", "correlationId", "targetGeneration")}
        confirm["confirmed"] = True
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_confirm(self.ledger, confirm)
        self.assertIsNone(self.record_now()["ack"])
        self.assertEqual(self.record_now()["waits"][0]["status"], "pending")

    def test_manual_confirmation_is_new_attestation_after_timeout(self):
        self.submitted()
        with self.ledger.transaction() as state:
            peer.handoff_start_wait(state["records"][self.correlation], "acknowledged", time.monotonic() - 1, None,
                                   initial_status="timed_out_unknown")
        confirm = {"schemaVersion": 1, "ledgerEpoch": self.epoch, "correlationId": self.correlation,
                   "targetGeneration": self.generation, "confirmed": True}
        original = self.record_now()["waits"][0].copy()
        peer.handoff_confirm(self.ledger, confirm)
        self.assertEqual(self.record_now()["ack"]["assurance"], "operator_confirmed")
        self.assertTrue(self.record_now()["ack"]["late"])
        self.assertEqual(original, self.record_now()["waits"][0])

    def test_fresh_unknown_and_attempted_ids_never_prepare_again(self):
        with self.assertRaises(peer.CcPeerError):
            self.ledger.prepare(self.binding, self.generation, str(peer.uuid.uuid4()))
        with self.assertRaises(peer.CcPeerError):
            self.ledger.prepare({**self.binding, "payloadDigest": "other"}, self.generation, self.correlation)
        with self.ledger.transaction() as state:
            state["records"][self.correlation].update(phase="attempted", submission="unknown")
        reloaded = peer.HandoffLedger(self.ledger.root)
        self.assertEqual(reloaded.record(self.correlation)[1]["submission"], "unknown")
        with self.assertRaises(peer.CcPeerError):
            reloaded.prepare(self.binding, self.generation, self.correlation)

    def test_quota_reservation_and_wait_limit_do_not_evict(self):
        with mock.patch.object(peer, "HANDOFF_LEDGER_BYTES", 1024 + peer.HANDOFF_RECORD_BYTES):
            with self.assertRaises(peer.CcPeerError):
                self.ledger.prepare(self.binding, self.generation)
        self.assertEqual(len(json.loads((self.ledger.root / "ledger.json").read_text())["records"]), 1)
        with self.ledger.transaction() as state:
            record = state["records"][self.correlation]
            for _ in range(64):
                peer.handoff_start_wait(record, "delivered", time.monotonic(), None)
            with self.assertRaises(peer.CcPeerError):
                peer.handoff_start_wait(record, "delivered", time.monotonic(), None)
        self.assertEqual(len(self.record_now()["waits"]), 64)

    def test_strict_receipt_lexical_and_size_boundaries(self):
        self.mint()
        raw = peer.HandoffLedger.encode(self.frame)
        for invalid in (raw + b"{}", b"\xef\xbb\xbf" + raw, raw.replace(b'"schemaVersion":1', b'"schemaVersion":1.0'),
                        raw.replace(b'"schemaVersion":1', b'"schemaVersion":true'), raw[:-1] + b',"kind":"receipt"}',
                        raw[:-1] + b',"body":"forbidden"}', b'\xff', raw + b' ' * 4096):
            with self.subTest(raw=invalid[:20]), self.assertRaises(peer.CcPeerError):
                peer.handoff_private_wire(invalid)
        peer.handoff_private_wire(raw + b' ' * (4096 - len(raw) - 1) + b'\n')
        for token in ("01", "1.0", "1e0", "+1", " 1", "１", "0", "61"):
            with self.assertRaises(argparse.ArgumentTypeError):
                peer.handoff_timeout(token)
        self.assertEqual(peer.handoff_timeout("60"), 60)

    def test_missing_corrupt_and_unknown_status_envelopes_have_no_fabricated_epoch(self):
        for context in ("ledger_missing", "ledger_corrupt", "id_unknown"):
            result = peer.handoff_query_error(self.correlation, context)
            self.assertNotIn("handoff", result)
            self.assertNotIn("ledgerEpoch", result)
            self.assertEqual(result["handoffQuery"]["context"], context)
        (self.ledger.root / "ledger.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(peer.CcPeerError) as error:
            self.ledger.record(self.correlation)
        self.assertEqual(error.exception.details["reason"], "handoff_ledger_corrupt")

    def start_collector(self):
        process = subprocess.Popen([sys.executable, peer.__file__, peer.HANDOFF_COLLECTOR_ARG, str(self.ledger.root)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        until = time.monotonic() + 3
        while time.monotonic() < until:
            if (self.ledger.root / "receipt.sock").exists():
                return process
            if process.poll() is not None:
                self.fail("collector exited before binding")
            time.sleep(0.01)
        self.fail("collector did not bind")

    def test_real_collector_and_installed_private_stdin_producer(self):
        self.start_collector()
        minted = peer.handoff_ipc(self.ledger.root, {"op": "mint", "ledgerEpoch": self.epoch,
                 "correlationId": self.correlation, "targetGeneration": self.generation})
        self.submitted()
        frame = {"schemaVersion": 1, "kind": "receipt", "ledgerEpoch": self.epoch,
                 "correlationId": self.correlation, "targetGeneration": self.generation,
                 "receiptId": str(peer.uuid.uuid4()), "capability": minted["capability"]}
        code = "import sys,pathlib; import session_peer as p; p.handoff_root=lambda:pathlib.Path(sys.argv[1]); sys.exit(p.main(['ack','--receipt','-','--json']))"
        result = subprocess.run([sys.executable, "-c", code, str(self.ledger.root)], input=peer.HandoffLedger.encode(frame),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        self.assertNotIn(frame["capability"].encode(), result.stdout + result.stderr)
        self.assertEqual(self.record_now()["ack"]["assurance"], "token_possession")

    def test_concurrent_collectors_do_not_revoke_active_capability(self):
        first = self.start_collector()
        minted = peer.handoff_ipc(self.ledger.root, {"op": "mint", "ledgerEpoch": self.epoch,
                 "correlationId": self.correlation, "targetGeneration": self.generation})
        losing = subprocess.run([sys.executable, peer.__file__, peer.HANDOFF_COLLECTOR_ARG, str(self.ledger.root)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertEqual(losing.returncode, 1)
        self.assertIsNone(first.poll())
        self.assertFalse(self.record_now()["capability"]["revoked"])
        self.assertNotIn(minted["capability"].encode(), losing.stdout + losing.stderr)

    def test_real_disk_fence_survives_process_exit_before_effect(self):
        code = "import sys,pathlib,os; import session_peer as p; l=p.HandoffLedger(pathlib.Path(sys.argv[1]));\nwith l.transaction() as s: s['records'][sys.argv[2]].update(phase='attempted',submission='unknown')\nos._exit(17)"
        child = subprocess.run([sys.executable, "-c", code, str(self.ledger.root), self.correlation], capture_output=True, timeout=5)
        self.assertEqual(child.returncode, 17)
        self.assertEqual(self.record_now()["submission"], "unknown")
        with self.assertRaises(peer.CcPeerError):
            self.ledger.prepare(self.binding, self.generation, self.correlation)

    def test_real_pending_wait_sigint_returns_130_with_known_facts(self):
        self.start_collector()
        peer.handoff_ipc(self.ledger.root, {"op": "mint", "ledgerEpoch": self.epoch,
                 "correlationId": self.correlation, "targetGeneration": self.generation})
        self.submitted()
        code = "import sys,pathlib; import session_peer as p; p.handoff_root=lambda:pathlib.Path(sys.argv[1]); sys.exit(p.main(['handoff','wait','--correlation-id',sys.argv[2],'--wait-for','acknowledged','--wait-timeout','6','--json']))"
        process = subprocess.Popen([sys.executable, "-c", code, str(self.ledger.root), self.correlation], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            until = time.monotonic() + 3
            while not self.record_now()["waits"] and time.monotonic() < until:
                time.sleep(0.01)
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        self.assertEqual(process.returncode, 130, stderr)
        result = json.loads(stdout)
        self.assertFalse(result["ok"])
        self.assertEqual(result["target"]["pid"], os.getpid())
        self.assertNotIn("submitted", result)
        self.assertEqual(result["handoff"]["submission"]["status"], "submitted")
        self.assertEqual(result["handoff"]["wait"]["status"], "stopped")
        self.assertEqual(peer.handoff_public(self.epoch, self.record_now())["wait"]["reason"], "stopped_by_operator")

    def test_unsupported_delivery_and_short_budget_never_run_native(self):
        with mock.patch.object(peer, "handoff_root", return_value=self.ledger.root), \
                mock.patch.object(peer, "discover", return_value=[]), mock.patch.object(peer, "post_to_socket") as post:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                status = peer.main(["send", "--to", "codex:11111111-1111-1111-1111-111111111111", "--message=x",
                                    "--wait-for", "delivered", "--wait-timeout", "5", "--json", "--no-update-notice"])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(out.getvalue())["handoff"]["submission"]["status"], "refused")
        post.assert_not_called()

    def test_private_file_rejects_symlink_non_utf8_and_public_permissions(self):
        path = self.root / "message"
        path.write_bytes(b"hello")
        path.chmod(0o600)
        args = argparse.Namespace(message=None, message_option=None, b64=None, message_file=str(path))
        self.assertEqual(peer.read_message(args), "hello")
        path.chmod(0o644)
        with self.assertRaises(peer.CcPeerError):
            peer.read_message(args)
        path.chmod(0o600)
        path.write_bytes(b"\xff")
        with self.assertRaises(peer.CcPeerError):
            peer.read_message(args)
        link = self.root / "link"
        link.symlink_to(path)
        args.message_file = str(link)
        with self.assertRaises(peer.CcPeerError):
            peer.read_message(args)

    def owned_roundtrip(self, early=False):
        self.start_collector()
        sessions = self.root / "sessions"
        sessions.mkdir()
        inbox = self.root / "inbox.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(inbox))
        listener.listen(1)
        listener.settimeout(3)
        self.addCleanup(listener.close)
        pid = os.getpid()
        record_path = sessions / (str(pid) + ".json")
        record_path.write_text(json.dumps({"pid": pid, "name": "owned-fixture", "messagingSocketPath": str(inbox), "startedAt": 1000}))
        row = {"pid": pid, "name": "owned-fixture", "socket": str(inbox), "reachable": True, "alive": True, "agent": "claude"}
        failures = []
        receipt_cap = []
        def recipient():
            try:
                with listener.accept()[0] as connection:
                    raw = bytearray()
                    while True:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        raw.extend(chunk)
                    content = json.loads(raw)["message"]["content"]
                    frame = json.loads(content.rsplit("\n", 1)[1])
                    receipt_cap.append(frame["capability"])
                    if early:
                        pending = peer.handoff_ipc(self.ledger.root, frame)
                        if pending.get("pending") is not True or self.ledger.record(frame["correlationId"])[1]["ack"] is not None:
                            raise AssertionError("early receipt was not retained unclassified")
                    connection.sendall(b"1")
                until = time.monotonic() + 3
                while self.ledger.record(frame["correlationId"])[1]["submission"] != "submitted" and time.monotonic() < until:
                    time.sleep(0.01)
                if not early:
                    peer.handoff_ipc(self.ledger.root, frame)
            except Exception as error:
                failures.append(type(error).__name__)
        thread = threading.Thread(target=recipient)
        thread.start()
        out = io.StringIO()
        with mock.patch.object(peer, "handoff_root", return_value=self.ledger.root), \
                mock.patch.object(peer, "sessions_dir", return_value=sessions), \
                mock.patch.object(peer, "discover", return_value=[row]), \
                mock.patch.object(peer, "handoff_ensure_collector"), contextlib.redirect_stdout(out):
            status = peer.main(["send", "--to", "owned-fixture", "--message=hello", "--request-ack", "--wait-for", "acknowledged",
                                "--wait-timeout", "6", "--json", "--no-from", "--no-reply-to", "--no-update-notice"])
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [], out.getvalue())
        self.assertEqual(status, 0, out.getvalue())
        result = json.loads(out.getvalue())
        self.assertEqual(result["target"]["pid"], pid)
        for absent in ("status", "submitted", "consumptionConfirmed"):
            self.assertNotIn(absent, result)
        self.assertEqual(result["handoff"]["state"], "acknowledged")
        self.assertEqual(result["handoff"]["wait"]["status"], "satisfied")
        self.assertFalse(result["handoff"]["ack"]["late"])
        self.assertFalse(result["handoff"]["observation"]["injectionObserved"])
        self.assertNotIn(receipt_cap[0], out.getvalue())
        self.assertNotIn(receipt_cap[0], (self.ledger.root / "ledger.json").read_text())

    def test_actual_owned_inbox_and_receipt_roundtrip_preserves_claude_absence(self):
        self.owned_roundtrip()

    def test_receipt_during_native_drain_is_retained_not_lost_or_promoted_early(self):
        self.owned_roundtrip(early=True)

    def test_sender_classification_cannot_invent_a_receipt(self):
        self.mint()
        self.submitted()
        frame = {key: self.frame[key] for key in ("schemaVersion", "ledgerEpoch", "correlationId", "targetGeneration", "capability")}
        result = peer.handoff_collect(self.ledger, self.clock, {**frame, "op": "classify"})
        self.assertFalse(result["pending"])
        self.assertIsNone(self.record_now()["ack"])

    def test_pending_receipt_restart_and_failed_native_do_not_promote(self):
        self.mint()
        with self.ledger.transaction() as state:
            state["records"][self.correlation].update(phase="attempted", submission="unknown")
        result = peer.handoff_collect(self.ledger, self.clock, self.frame)
        self.assertTrue(result["pending"])
        self.assertIsNone(self.record_now()["ack"])
        frame = {key: self.frame[key] for key in ("schemaVersion", "ledgerEpoch", "correlationId", "targetGeneration", "capability")}
        self.submitted()
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_collect(self.ledger, "restart-clock", {**frame, "op": "classify"})
        self.assertIsNone(self.record_now()["ack"])
        self.assertIsNotNone(self.record_now()["pendingReceipt"])

    def test_old_ledger_clock_does_not_support_wait_or_next_action(self):
        self.mint()
        self.submitted()
        public = peer.handoff_public(self.epoch, self.record_now())
        self.assertNotIn("keep_waiting", public["nextActions"])
        self.assertEqual(peer.handoff_wait(self.ledger, self.correlation, "acknowledged", 6), 1)
        self.assertEqual(self.record_now()["waits"][0]["reason"], "history_unavailable")

    def test_detail_expiry_keeps_target_fence_and_rejects_receipt(self):
        self.mint()
        self.submitted()
        peer.handoff_collect(self.ledger, self.clock, self.frame)
        with self.ledger.transaction() as state:
            record = state["records"][self.correlation]
            record["createdNs"] = 1
            record["historyBoot"] = "b" * 64
        with mock.patch.object(peer, "handoff_boot_clock", return_value="b" * 64), \
                mock.patch.object(peer.time, "monotonic_ns", return_value=31 * 86400 * 1000000000):
            expired = self.record_now()
        self.assertEqual(expired["phase"], "tombstone")
        self.assertEqual(expired["binding"], self.binding)
        self.assertIsNone(expired["ack"])
        public = peer.handoff_public(self.epoch, expired)
        self.assertEqual(public["state"], "unknown")
        self.assertEqual(public["ledgerEpoch"], self.epoch)
        self.assertNotIn("keep_waiting", public["nextActions"])
        with self.assertRaises(peer.CcPeerError):
            self.ledger.prepare(self.binding, self.generation, self.correlation)
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_collect(self.ledger, self.clock, self.frame)

    def test_known_restore_quarantines_receipt_and_effect_authority(self):
        self.mint()
        self.submitted()
        peer.handoff_collect(self.ledger, self.clock, self.frame)
        self.ledger.quarantine_restored()
        self.assertEqual(self.record_now()["phase"], "quarantined")
        self.assertIsNone(self.record_now()["ack"])
        self.assertEqual(self.record_now()["submission"], "unknown")
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_collect(self.ledger, self.clock, self.frame)
        with self.assertRaises(peer.CcPeerError):
            self.ledger.prepare(self.binding, self.generation, self.correlation)

    def test_closed_validator_accepts_frozen_examples_and_rejects_native_overwrite(self):
        fixture = json.loads((Path(peer.__file__).parent / "tests/fixtures/handoff-v1.json").read_text())
        for case in fixture["accepted"]:
            with self.subTest(case=case["name"]):
                peer.handoff_validate_public(case["result"]["handoff"])
        self.submitted()
        native = self.record_now()["native"]
        for mutation in ({"status": "posted"}, {"submitted": True}, {"consumptionConfirmed": True},
                         {"target": {"pid": os.getpid() + 1, "name": "fixture"}}):
            with self.subTest(mutation=mutation), self.assertRaises(peer.CcPeerError):
                peer.handoff_validate_native({**native, **mutation}, self.record_now())

    def test_expired_ipc_budget_never_connects_or_sends(self):
        with mock.patch.object(peer.socket, "socket") as connection, self.assertRaises(peer.CcPeerError):
            peer.handoff_ipc(self.ledger.root, {"op": "clock"}, time.monotonic() - 1)
        connection.assert_not_called()

    def test_slow_partial_frame_has_total_not_per_chunk_deadline(self):
        self.start_collector()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(str(self.ledger.root / "receipt.sock"))
            connection.sendall(b'{')
            time.sleep(0.4)
            connection.sendall(b'"')
            time.sleep(0.4)
            connection.sendall(b'x')
            time.sleep(0.4)
            response = connection.recv(4096)
        self.assertFalse(json.loads(response)["ok"])
        start = time.monotonic()
        self.assertIsNotNone(peer.handoff_channel_epoch(self.ledger))
        self.assertLess(time.monotonic() - start, 0.5)

    def test_sigint_during_effect_preserves_unknown_and_stops_explicit_wait(self):
        self.start_collector()
        session = {"pid": os.getpid(), "name": "fixture", "socket": "owned-test-endpoint"}
        args = peer.build_parser().parse_args(["send", "--to", "fixture", "--message=x", "--wait-for", "acknowledged",
                                              "--wait-timeout", "6", "--no-from", "--no-reply-to", "--json"])
        output = io.StringIO()
        binding = {**self.binding, "payloadDigest": "b" * 64}
        with mock.patch.object(peer, "handoff_root", return_value=self.ledger.root), \
                mock.patch.object(peer, "handoff_binding", return_value=(binding, self.generation, session)), \
                mock.patch.object(peer, "handoff_ensure_collector"), mock.patch.object(peer, "require_claude_generation"), \
                mock.patch.object(peer, "post_to_socket", side_effect=KeyboardInterrupt) as post, contextlib.redirect_stdout(output):
            code = peer.cmd_handoff_send(args)
        self.assertEqual(code, 130)
        self.assertEqual(post.call_count, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["handoff"]["state"], "unknown")
        self.assertEqual(result["handoff"]["wait"]["status"], "stopped")
        self.assertEqual(result["handoff"]["wait"]["reason"], "stopped_by_operator")
        self.assertFalse(result["retryAllowed"])
        self.assertNotIn("submitted", result)
