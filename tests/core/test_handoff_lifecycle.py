"""Handoff #181 lifecycle boundaries: stale receipt channels, retention and restore.

Offline and test-only. Every ledger, socket and collector lives in a private
temporary directory. No native Claude/Codex session is contacted; native
posting is mocked and asserted to be absent unless a case explicitly pins a
best-effort submission. Assertion messages are fixed strings so that message
bodies, capabilities and private identifiers are never echoed into test logs.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import session_peer as peer


DAY_NS = 86400 * 1000000000
RETENTION_NS = 30 * DAY_NS  # handoff.py: detail retention is 30 days from preparation
BOOT = "b" * 64


class SocketSpy(socket.socket):
    """Real socket that records client connects and any server-side bind."""
    connects = []
    binds = []

    def connect(self, address):
        type(self).connects.append(address)
        return super().connect(address)

    def bind(self, address):
        type(self).binds.append(address)
        return super().bind(address)


@unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "private POSIX collector only")
class HandoffLifecycle(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="codex-hl-", dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.root.chmod(0o700)
        self.ledger = peer.HandoffLedger(self.root / "ledger")
        self.epoch = self.ledger.initialize()
        self.generation = "tg1:" + "a" * 64
        self.binding = {"agent": "claude", "destination": ["local"], "target": str(os.getpid()), "home": None, "payloadDigest": "a" * 64}
        self.epoch, record = self.ledger.prepare(self.binding, self.generation)
        self.correlation = record["id"]
        self.clock = str(peer.uuid.uuid4())
        self.channel = self.ledger.root / "receipt.sock"
        self.session = {"pid": os.getpid(), "name": "fixture", "socket": "owned-test-endpoint"}

    # -- helpers -----------------------------------------------------------

    def record_now(self, correlation=None):
        return self.ledger.record(correlation or self.correlation)[1]

    def update(self, correlation=None, **fields):
        with self.ledger.transaction() as state:
            state["records"][correlation or self.correlation].update(fields)

    def mint(self, correlation=None, clock=None):
        correlation = correlation or self.correlation
        minted = peer.handoff_collect(self.ledger, clock or self.clock, {"op": "mint", "ledgerEpoch": self.epoch,
                                      "correlationId": correlation, "targetGeneration": self.generation})
        return {"schemaVersion": 1, "kind": "receipt", "ledgerEpoch": self.epoch,
                "correlationId": correlation, "targetGeneration": self.generation,
                "receiptId": str(peer.uuid.uuid4()), "capability": minted["capability"]}

    def submitted(self, correlation=None):
        self.update(correlation, phase="terminal", submission="submitted", ackRequested=True,
                    native={"ok": True, "target": {"pid": os.getpid(), "name": "fixture"}, "chars": 4, "dryRun": False})

    def stale_socket(self, mode=0o600):
        # A server socket that was bound and then closed: the path is left
        # behind with no listener, exactly like a crashed collector.
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.channel))
        finally:
            server.close()
        os.chmod(self.channel, mode)
        info = self.channel.lstat()
        self.assertTrue(stat.S_ISSOCK(info.st_mode))
        self.assertEqual(info.st_uid, os.getuid())
        return info

    def assert_same_entry(self, path, before):
        after = path.lstat()
        self.assertEqual((after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode)),
                         (before.st_dev, before.st_ino, stat.S_IFMT(before.st_mode)),
                         "receipt channel entry was deleted or replaced")

    def send(self, argv, *, post=None, producer=True):
        args = peer.build_parser().parse_args(["send", "--to", "fixture", "--message=fixture-body",
                                               "--no-from", "--no-reply-to", "--json"] + argv)
        output = io.StringIO()
        binding = {**self.binding, "payloadDigest": "c" * 64}
        SocketSpy.connects, SocketSpy.binds = [], []
        patches = [mock.patch.object(peer, "handoff_root", return_value=self.ledger.root),
                   mock.patch.object(peer, "handoff_binding", return_value=(binding, self.generation, self.session)),
                   mock.patch.object(peer, "require_claude_generation"),
                   mock.patch.object(peer.subprocess, "Popen", side_effect=AssertionError("collector launched")),
                   mock.patch.object(peer.socket, "socket", SocketSpy)]
        if producer:
            patches.append(mock.patch.object(peer, "handoff_producer_command", return_value=["owned-receipt-fixture"]))
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            native = stack.enter_context(mock.patch.object(peer, "post_to_socket", side_effect=post))
            stack.enter_context(contextlib.redirect_stdout(output))
            code = peer.cmd_handoff_send(args)
        return code, output.getvalue(), native

    def status(self, *extra, action="status"):
        output = io.StringIO()
        command = ["handoff", action, "--correlation-id", self.correlation, "--json"] + list(extra)
        with mock.patch.object(peer, "handoff_root", return_value=self.ledger.root), \
                mock.patch.object(peer, "post_to_socket") as inbox, \
                mock.patch.object(peer, "handoff_codex_submit") as queue, contextlib.redirect_stdout(output):
            code = peer.main(command)
        return code, json.loads(output.getvalue()), inbox, queue

    @contextlib.contextmanager
    def clocks(self, now_ns, boot=BOOT, utc=None):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(peer, "handoff_now_ns", return_value=now_ns))
            stack.enter_context(mock.patch.object(peer, "handoff_boot_clock", return_value=boot))
            if utc is not None:
                stack.enter_context(mock.patch.object(peer.time, "time", return_value=utc))
            yield

    def start_collector(self):
        process = subprocess.Popen([sys.executable, peer.__file__, peer.HANDOFF_COLLECTOR_ARG, str(self.ledger.root)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)
        self.addCleanup(cleanup)
        until = peer.handoff_now() + 3
        while peer.handoff_now() < until:
            if self.channel.exists():
                return process
            if process.poll() is not None:
                self.fail("collector exited before binding")
            time.sleep(0.01)
        self.fail("collector did not bind")

    # -- S1: stale or forged receipt channel -------------------------------

    def test_stale_receipt_socket_refuses_required_ack_before_native_post(self):
        before = self.stale_socket()
        code, out, native = self.send(["--wait-for", "acknowledged", "--wait-timeout", "10"])
        result = json.loads(out)
        self.assertEqual(code, 1)
        native.assert_not_called()
        # The sender only acted as a client of the leftover path; it never
        # rebound the server path or launched a replacement collector.
        self.assertEqual(SocketSpy.binds, [])
        self.assertEqual(SocketSpy.connects, [str(self.channel)])
        self.assert_same_entry(self.channel, before)
        self.assertEqual(self.channel.lstat().st_uid, os.getuid())
        handoff = result["handoff"]
        self.assertEqual(handoff["submission"]["status"], "refused")
        self.assertEqual(handoff["wait"]["status"], "unsupported")
        self.assertEqual(handoff["wait"]["reason"], "evidence_unsupported")
        self.assertEqual(handoff["ack"]["status"], "unsupported")
        self.assertNotIn("keep_waiting", handoff["nextActions"])
        record = self.record_now(handoff["correlationId"])
        self.assertIsNone(record["capability"])
        self.assertEqual(record["phase"], "terminal")

    def test_stale_receipt_socket_best_effort_ack_submits_without_delegated_authority(self):
        before = self.stale_socket()
        code, out, native = self.send(["--request-ack", "--wait-timeout", "10"])
        result = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(native.call_count, 1)
        self.assertEqual(SocketSpy.binds, [])
        self.assert_same_entry(self.channel, before)
        body = native.call_args.args[1]
        self.assertFalse("Receipt-only delegated authority" in body, "delegated authority text in native body")
        self.assertFalse("owned-receipt-fixture" in body, "receipt handler command in native body")
        self.assertFalse('"capability"' in body or '"kind":"receipt"' in body, "receipt frame in native body")
        handoff = result["handoff"]
        self.assertEqual(handoff["submission"]["status"], "submitted")
        self.assertEqual(handoff["ack"], {"status": "unsupported"})
        self.assertEqual(handoff["wait"], {"for": "none", "status": "not_requested"})
        self.assertNotIn("keep_waiting", handoff["nextActions"])
        record = self.record_now(handoff["correlationId"])
        self.assertIsNone(record["capability"])
        self.assertFalse("capability" in out, "capability reflected in output")
        self.assertFalse("fixture-body" in out, "message body reflected in output")

    def test_non_socket_or_permissive_receipt_channel_is_unsafe_and_untouched(self):
        target = self.root / "foreign-target"
        target.write_bytes(b"foreign")
        target.chmod(0o600)
        cases = {"regular_file": lambda: self.channel.write_bytes(b"stale"),
                 "symlink": lambda: self.channel.symlink_to(target),
                 "group_accessible_socket": lambda: self.stale_socket(0o660)}
        for name, create in cases.items():
            with self.subTest(case=name):
                create()
                if name == "regular_file":
                    self.channel.chmod(0o600)
                before = self.channel.lstat()
                with mock.patch.object(peer.socket, "socket") as client, self.assertRaises(peer.CcPeerError) as caught:
                    peer.handoff_ipc(self.ledger.root, {"op": "clock"})
                self.assertEqual(caught.exception.details["reason"], "unsafe_receipt_channel")
                client.assert_not_called()
                self.assertIsNone(peer.handoff_channel_epoch(self.ledger))
                self.assert_same_entry(self.channel, before)
                self.assertEqual(target.read_bytes(), b"foreign")
                self.assertTrue(stat.S_ISREG(target.lstat().st_mode))
                self.channel.unlink()

    def test_unsafe_receipt_channel_refuses_required_ack_through_send(self):
        self.channel.write_bytes(b"stale")
        self.channel.chmod(0o600)
        before = self.channel.lstat()
        code, out, native = self.send(["--wait-for", "acknowledged", "--wait-timeout", "10"])
        self.assertEqual(code, 1)
        native.assert_not_called()
        self.assertEqual(SocketSpy.connects, [])
        self.assertEqual(SocketSpy.binds, [])
        self.assert_same_entry(self.channel, before)
        self.assertEqual(self.channel.read_bytes(), b"stale")
        handoff = json.loads(out)["handoff"]
        self.assertEqual(handoff["wait"]["status"], "unsupported")
        self.assertEqual(handoff["wait"]["reason"], "evidence_unsupported")

    def test_collector_startup_on_existing_channel_refuses_without_revoking_authority(self):
        self.mint()
        other = self.ledger.prepare({**self.binding, "payloadDigest": "d" * 64}, self.generation)[1]["id"]
        self.mint(other)
        target = self.root / "foreign-target"
        target.write_bytes(b"foreign")
        target.chmod(0o600)
        cases = {"stale_socket": self.stale_socket,
                 "regular_file": lambda: self.channel.write_bytes(b"stale"),
                 "symlink": lambda: self.channel.symlink_to(target)}
        for name, create in cases.items():
            with self.subTest(case=name):
                create()
                before = self.channel.lstat()
                ledger_bytes = (self.ledger.root / "ledger.json").read_bytes()
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.handoff_collector(self.ledger.root)
                self.assertEqual(caught.exception.details["reason"], "receipt_channel_exists")
                self.assert_same_entry(self.channel, before)
                self.assertEqual(target.read_bytes(), b"foreign")
                self.assertEqual((self.ledger.root / "ledger.json").read_bytes(), ledger_bytes)
                for correlation in (self.correlation, other):
                    self.assertFalse(self.record_now(correlation)["capability"]["revoked"])
                self.channel.unlink()

    # -- S2: retention tombstone boundaries --------------------------------
    # Detail cleanup is the explicit 30-day retention scope only. Losing the
    # retained detail is not evidence that a receipt or ACK never happened.

    def created(self):
        self.update(historyBoot=BOOT)
        return self.record_now()["createdNs"]

    def test_retention_boundary_is_exact_under_proven_boot_continuity(self):
        created = self.created()
        with self.clocks(created + RETENTION_NS - 1):
            self.assertEqual(self.record_now()["phase"], "prepared")
        with self.clocks(created + RETENTION_NS):
            record = self.record_now()
        self.assertEqual(record["phase"], "tombstone")
        self.assertEqual(record["submission"], "unknown")
        self.assertEqual(record["binding"], self.binding)
        self.assertEqual(record["generation"], self.generation)
        for field in ("native", "ack", "capability", "pendingReceipt"):
            self.assertIsNone(record[field])
        self.assertEqual(record["waits"], [])

    def test_unproven_boot_continuity_keeps_detail_and_refuses_mint(self):
        created = self.record_now()["createdNs"]
        for name, history, boot in (("different_boot", "c" * 64, BOOT), ("record_boot_unknown", None, BOOT),
                                    ("current_boot_unknown", BOOT, None)):
            with self.subTest(case=name):
                self.update(historyBoot=history)
                with self.clocks(created + RETENTION_NS + DAY_NS, boot=boot):
                    self.assertEqual(self.record_now()["phase"], "prepared")
                    with self.assertRaises(peer.CcPeerError) as caught:
                        self.mint()
                self.assertEqual(caught.exception.details["reason"], "receipt_authority_expired")
                self.assertIsNone(self.record_now()["capability"])

    def test_utc_clock_jump_never_moves_retention_or_authority(self):
        created = self.created()
        for utc in (0.0, time.time() + 365 * 86400):
            with self.subTest(utc=utc):
                with self.clocks(created + RETENTION_NS - 1, utc=utc):
                    self.assertEqual(self.record_now()["phase"], "prepared")
        with self.clocks(created + 1, utc=time.time() + 365 * 86400):
            self.mint()
        self.assertFalse(self.record_now()["capability"]["revoked"])
        self.assertEqual(self.record_now()["capability"]["expiresNs"], created + DAY_NS)
        with self.clocks(created + RETENTION_NS, utc=0.0):
            self.assertEqual(self.record_now()["phase"], "tombstone")

    def test_never_attempted_tombstone_cannot_be_prepared_again(self):
        created = self.created()
        with self.clocks(created + RETENTION_NS):
            with self.assertRaises(peer.CcPeerError) as caught:
                self.ledger.prepare(self.binding, self.generation, self.correlation)
            # A refused transaction is not saved, so expiry is re-derived from
            # the retained createdNs/historyBoot facts on every read.
            self.assertEqual(self.record_now()["phase"], "tombstone")
            with self.assertRaises(peer.CcPeerError) as again:
                self.ledger.prepare(self.binding, self.generation, self.correlation)
        self.assertEqual(caught.exception.details["reason"], "handoff_already_attempted")
        self.assertEqual(again.exception.details["reason"], "handoff_already_attempted")

    def test_tombstone_counts_toward_ledger_quota_without_eviction(self):
        created = self.created()
        with self.clocks(created + RETENTION_NS):
            tombstone = self.record_now()
        self.assertEqual(tombstone["phase"], "tombstone")
        exact = 1024 + len(peer.HandoffLedger.encode(tombstone)) + 64 + peer.HANDOFF_RECORD_BYTES
        with mock.patch.object(peer, "HANDOFF_LEDGER_BYTES", exact - 1):
            with self.assertRaises(peer.CcPeerError) as caught:
                self.ledger.prepare({**self.binding, "payloadDigest": "e" * 64}, self.generation)
        self.assertEqual(caught.exception.details["reason"], "handoff_ledger_capacity")
        records = json.loads((self.ledger.root / "ledger.json").read_text())["records"]
        self.assertEqual(list(records), [self.correlation])
        self.assertEqual(records[self.correlation]["phase"], "tombstone")
        with mock.patch.object(peer, "HANDOFF_LEDGER_BYTES", exact):
            self.ledger.prepare({**self.binding, "payloadDigest": "e" * 64}, self.generation)
        self.assertEqual(len(json.loads((self.ledger.root / "ledger.json").read_text())["records"]), 2)

    def test_tombstone_status_matches_known_tombstone_fixture_shape(self):
        fixture = json.loads((Path(peer.__file__).parent / "tests/fixtures/handoff-v1.json").read_text())["knownTombstone"]
        created = self.created()
        with self.clocks(created + RETENTION_NS):
            self.record_now()
        code, result, inbox, queue = self.status()
        self.assertEqual(code, fixture["exit"])
        self.assertEqual(set(result), set(fixture["result"]))
        self.assertTrue(result["ok"])
        expected = {**fixture["result"]["handoff"], "correlationId": self.correlation,
                    "ledgerEpoch": self.epoch, "targetGeneration": self.generation}
        self.assertEqual(result["handoff"], expected)
        self.assertNotIn("keep_waiting", result["handoff"]["nextActions"])
        inbox.assert_not_called()
        queue.assert_not_called()

    # -- S3: explicit known-restored-history quarantine --------------------

    def receipt_capable_pending_wait(self):
        frame = self.mint()
        self.submitted()
        with self.ledger.transaction() as state:
            peer.handoff_start_wait(state["records"][self.correlation], "acknowledged", peer.handoff_now() + 600, self.clock)
        return frame

    def test_explicit_known_restore_quarantine_status_is_reconcile_only(self):
        self.receipt_capable_pending_wait()
        self.ledger.quarantine_restored()
        record = self.record_now()
        self.assertEqual(record["waits"][0]["status"], "failed")
        self.assertEqual(record["waits"][0]["reason"], "history_unavailable")
        self.assertTrue(record["capability"]["revoked"])
        code, result, inbox, queue = self.status()
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        handoff = result["handoff"]
        self.assertEqual(handoff["state"], "unknown")
        self.assertEqual(handoff["submission"], {"status": "unknown"})
        self.assertEqual(handoff["nextActions"], ["reconcile"])
        self.assertEqual(handoff["retry"], {"allowed": False, "reason": "receiver_dedup_unavailable"})
        self.assertEqual(handoff["wait"]["status"], "failed")
        self.assertEqual(handoff["wait"]["reason"], "history_unavailable")
        self.assertEqual(handoff["ledgerEpoch"], self.epoch)
        for native_field in ("target", "chars", "dryRun", "status", "submitted", "consumptionConfirmed", "queueId"):
            self.assertNotIn(native_field, result)
        inbox.assert_not_called()
        queue.assert_not_called()

    def test_explicit_known_restore_quarantine_clears_ack(self):
        # Pinned current behavior: the operator's explicit known-restored-history
        # quarantine (contract: restored history is unknown, old intents are
        # quarantined) drops the committed ACK detail together with the native
        # facts. This is not a restart/clock rule; see the positive control below.
        frame = self.mint()
        self.submitted()
        peer.handoff_collect(self.ledger, self.clock, frame)
        self.assertEqual(self.record_now()["ack"]["assurance"], "token_possession")
        self.ledger.quarantine_restored()
        record = self.record_now()
        self.assertEqual(record["phase"], "quarantined")
        self.assertIsNone(record["ack"])
        self.assertIsNone(record["native"])
        public = peer.handoff_public(self.epoch, record)
        self.assertEqual(public["state"], "unknown")
        self.assertEqual(public["ack"], {"status": "unsupported"})

    def test_explicit_known_restore_quarantine_is_idempotent(self):
        self.receipt_capable_pending_wait()
        self.ledger.quarantine_restored()
        once = (self.ledger.root / "ledger.json").read_bytes()
        self.ledger.quarantine_restored()
        self.assertEqual(json.loads((self.ledger.root / "ledger.json").read_bytes()), json.loads(once))
        self.assertEqual(self.ledger.record(self.correlation)[0], self.epoch)

    def test_quarantine_on_missing_or_damaged_ledger_initializes_nothing(self):
        missing = peer.HandoffLedger(self.root / "absent")
        with self.assertRaises(peer.CcPeerError):
            missing.quarantine_restored()
        self.assertFalse(missing.root.exists())
        path = self.ledger.root / "ledger.json"
        for name, damage, context in (("damaged", lambda: path.write_text("{}", encoding="utf-8"), "ledger_corrupt"),
                                      ("missing_snapshot", path.unlink, "ledger_missing")):
            with self.subTest(case=name):
                damage()
                before = sorted(entry.name for entry in self.ledger.root.iterdir())
                content = path.read_bytes() if path.exists() else None
                with self.assertRaises(peer.CcPeerError):
                    self.ledger.quarantine_restored()
                self.assertEqual(sorted(entry.name for entry in self.ledger.root.iterdir()), before)
                self.assertEqual(path.read_bytes() if path.exists() else None, content)
                for action, extra in (("status", ()), ("wait", ("--wait-for", "acknowledged", "--wait-timeout", "6"))):
                    code, result, inbox, queue = self.status(*extra, action=action)
                    self.assertEqual(code, 1)
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["reason"], "handoff_history_unavailable")
                    self.assertEqual(result["handoffQuery"]["context"], context)
                    self.assertEqual(result["handoffQuery"]["retry"], {"allowed": False, "reason": "history_unavailable"})
                    self.assertNotIn("handoff", result)
                    self.assertNotIn("ledgerEpoch", result)
                    inbox.assert_not_called()
                    queue.assert_not_called()
                self.assertEqual(sorted(entry.name for entry in self.ledger.root.iterdir()), before)
                self.assertEqual(path.read_bytes() if path.exists() else None, content)
        code, result, _, _ = self.status()
        self.assertEqual(result["handoffQuery"]["context"], "ledger_missing")
        self.assertFalse(path.exists())

    def test_wait_on_quarantined_record_makes_no_native_call(self):
        self.receipt_capable_pending_wait()
        self.ledger.quarantine_restored()
        code, result, inbox, queue = self.status("--wait-for", "acknowledged", "--wait-timeout", "6", action="wait")
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        handoff = result["handoff"]
        self.assertEqual(handoff["state"], "unknown")
        self.assertEqual(handoff["wait"]["status"], "failed")
        self.assertEqual(handoff["wait"]["reason"], "history_unavailable")
        self.assertNotIn("keep_waiting", handoff["nextActions"])
        inbox.assert_not_called()
        queue.assert_not_called()
        self.assertEqual(len(self.record_now()["waits"]), 2)
        self.assertFalse(self.channel.exists())

    def test_duplicate_receipt_refused_when_revoked_or_quarantined(self):
        frame = self.mint()
        self.submitted()
        peer.handoff_collect(self.ledger, self.clock, frame)
        for name in ("revoked", "quarantined"):
            with self.subTest(case=name):
                if name == "revoked":
                    with self.ledger.transaction() as state:
                        state["records"][self.correlation]["capability"]["revoked"] = True
                else:
                    self.ledger.quarantine_restored()
                before = self.record_now()
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.handoff_collect(self.ledger, self.clock, frame)
                self.assertEqual(caught.exception.details["reason"], "receipt_authority_unavailable")
                self.assertEqual(self.record_now(), before)

    # -- Positive control: intact history keeps a committed ACK ------------

    def test_committed_ack_survives_collector_restart_and_clock_change(self):
        frame = self.mint()
        self.submitted()
        unused = self.ledger.prepare({**self.binding, "payloadDigest": "f" * 64}, self.generation)[1]["id"]
        unused_frame = self.mint(unused)
        self.submitted(unused)
        with self.ledger.transaction() as state:
            # Origin wait already past its deadline: the receipt is late and
            # the wait terminates as timed_out_unknown, never satisfied.
            peer.handoff_start_wait(state["records"][self.correlation], "acknowledged", peer.handoff_now() - 1, self.clock)
        peer.handoff_collect(self.ledger, self.clock, frame)
        committed = self.record_now()
        self.assertEqual(committed["ack"]["assurance"], "token_possession")
        self.assertTrue(committed["ack"]["late"])
        self.assertEqual(committed["waits"][0]["status"], "timed_out_unknown")
        public = peer.handoff_public(self.epoch, committed)
        self.assertEqual(public["state"], "acknowledged")

        # Plain collector restart: a new clock epoch over the same intact history.
        self.start_collector()
        restarted = self.record_now()
        self.assertEqual(restarted["ack"], committed["ack"])
        self.assertEqual(restarted["waits"], committed["waits"])
        self.assertFalse(restarted["capability"]["revoked"])
        self.assertEqual(peer.handoff_public(self.epoch, restarted), public)
        duplicate = peer.handoff_ipc(self.ledger.root, frame)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(self.record_now()["ack"], committed["ack"])
        # Unused new-receipt authority is expired separately by the restart.
        self.assertTrue(self.record_now(unused)["capability"]["revoked"])
        with self.assertRaises(peer.CcPeerError):
            peer.handoff_ipc(self.ledger.root, unused_frame)
        self.assertIsNone(self.record_now(unused)["ack"])

        # A later wait is satisfied by the already committed late ACK; the
        # original timed-out wait and the late flag are not rewritten.
        self.assertEqual(peer.handoff_wait(self.ledger, self.correlation, "acknowledged", 6), 0)
        waited = self.record_now()
        self.assertEqual(waited["waits"][0], committed["waits"][0])
        self.assertEqual(waited["waits"][1]["status"], "satisfied")
        self.assertEqual(waited["ack"], committed["ack"])

        # Clock change within retention (beyond capability lifetime, UTC moved):
        # the stored classification is unchanged and a new wait still succeeds.
        jumped = committed["createdNs"] + 2 * DAY_NS
        with mock.patch.object(peer, "handoff_now_ns", return_value=jumped), \
                mock.patch.object(peer.time, "time", return_value=0.0):
            shifted = self.record_now()
            self.assertEqual(shifted["phase"], "terminal")
            self.assertEqual(shifted["ack"], committed["ack"])
            self.assertEqual(peer.handoff_public(self.epoch, shifted)["state"], "acknowledged")
            self.assertEqual(peer.handoff_wait(self.ledger, self.correlation, "acknowledged", 6), 0)
            self.assertTrue(peer.handoff_collect(self.ledger, str(peer.uuid.uuid4()), frame)["duplicate"])
        final = self.record_now()
        self.assertEqual(final["ack"], committed["ack"])
        self.assertEqual(final["waits"][0], committed["waits"][0])
        self.assertEqual([wait["status"] for wait in final["waits"][1:]], ["satisfied", "satisfied"])


if __name__ == "__main__":
    unittest.main()
