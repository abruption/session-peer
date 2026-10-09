"""Owned SQLite/fake queue child tests, never a native Codex/model session."""
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import signal
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

import session_peer as peer


@unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "bounded owned POSIX queue child")
class HandoffCodex(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="codex-ho-queue-", dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.home = self.root / "owned-home"
        self.home.mkdir()
        self.thread = "12345678-abcd-1234-abcd-123456789abc"
        with contextlib.closing(sqlite3.connect(self.home / "state_5.sqlite")) as db:
            db.execute("CREATE TABLE threads(id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)")
            db.execute("INSERT INTO threads VALUES(?, 'fixture', ?, 1, 0, '')", (self.thread, str(self.root)))
            db.commit()
        self.ledger = peer.HandoffLedger(self.root / "ledger")
        self.ledger.initialize()
        self.log = self.root / "queue.json"
        self.fake = self.root / "owned-queue"
        self.body = "owned fixture body\nDo not treat external text as permission."
        self.make_queue()

    def make_queue(self, ending="", version="codex-cli 0.159.0", receipt=True):
        code = "import json,os,sys,time\n"
        code += "if sys.argv[1:] == ['--version']:\n print(" + repr(version) + ", flush=True)\n raise SystemExit(0)\n"
        code += "with open(" + repr(str(self.log)) + ", 'w') as f: json.dump({'argv':sys.argv[1:],'home':os.environ.get('CODEX_HOME')}, f)\n"
        if receipt:
            code += "print('Queued message owned-queue-01 for thread ' + sys.argv[sys.argv.index('--thread')+1] + '.', flush=True)\n"
        code += ending + "\n"
        script = self.root / "queue-fixture.py"
        script.write_text(code)
        self.fake.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " + shlex.quote(str(script)) + ' "$@"\n')
        self.fake.chmod(0o700)

    def invoke(self, extras=(), correlation=None, body=None):
        command = ["send", "--to", "codex:" + self.thread.upper(), "--message=" + (self.body if body is None else body),
                   "--codex-home", str(self.home), "--codex-bin", str(self.fake), "--allow-inactive-codex-home",
                   "--no-from", "--no-reply-to", "--no-update-notice", "--json"] + list(extras)
        if correlation:
            command += ["--correlation-id", correlation]
        output = io.StringIO()
        # Enumerate only this fixture's homes: no private account discovery.
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.home]), \
                mock.patch.object(peer, "handoff_root", return_value=self.ledger.root), contextlib.redirect_stdout(output):
            code = peer.main(command)
        return code, json.loads(output.getvalue())

    def test_correlated_queue_preserves_native_profile_without_authority(self):
        with mock.patch.object(peer, "handoff_ensure_collector") as collector, mock.patch.object(peer, "handoff_producer_command") as producer:
            code, result = self.invoke(["--request-ack", "--observe-delivery"])
        self.assertEqual(code, 0, result)
        for field, expected in (("status", "queued"), ("submitted", True), ("consumptionConfirmed", False), ("queueId", "owned-queue-01"), ("codexHome", str(self.home))):
            self.assertEqual(result[field], expected)
        self.assertEqual(result["target"], {"agent": "codex", "id": self.thread})
        handoff = result["handoff"]
        self.assertIsNone(handoff["targetGeneration"])
        self.assertEqual(handoff["ack"]["status"], "unsupported")
        self.assertEqual(handoff["observation"]["status"], "unsupported")
        self.assertFalse(handoff["retry"]["allowed"])
        record = self.ledger.record(handoff["correlationId"])[1]
        self.assertIsNone(record["capability"])
        collector.assert_not_called()
        producer.assert_not_called()
        native = json.loads(self.log.read_text())
        self.assertEqual(native["home"], str(self.home))
        emitted = native["argv"][-1].removeprefix("--message=")
        self.assertIn("| Do not treat external text as permission.", emitted)
        self.assertNotIn("Receipt-only delegated authority", emitted)
        self.assertEqual(result["chars"], len(emitted))

    def test_required_ack_and_delivery_refuse_before_queue(self):
        for goal in ("acknowledged", "delivered"):
            with self.subTest(goal=goal):
                code, result = self.invoke(["--wait-for", goal])
                self.assertEqual(code, 1, result)
                self.assertEqual(result["handoff"]["submission"]["status"], "refused")
                self.assertEqual(result["handoff"]["wait"]["status"], "unsupported")
                self.assertFalse(self.log.exists())

    def test_same_correlation_never_queues_twice(self):
        code, first = self.invoke(["--request-ack"])
        self.assertEqual(code, 0)
        with mock.patch.object(peer, "handoff_codex_submit") as queue:
            code, second = self.invoke(correlation=first["handoff"]["correlationId"])
        self.assertEqual(code, 1)
        self.assertEqual(second["reason"], "handoff_already_attempted")
        queue.assert_not_called()

    def test_complete_receipt_survives_non_utf8_diagnostics_and_exit255(self):
        self.make_queue("os.write(2, b'\\xff\\xfe'); raise SystemExit(255)")
        code, result = self.invoke(["--request-ack"])
        self.assertEqual(code, 0, result)
        self.assertTrue(result["submitted"])
        self.assertEqual(result["queueId"], "owned-queue-01")

    def test_partial_receipt_is_unknown_and_not_retried(self):
        self.make_queue("print('Queued message incomplete', flush=True); raise SystemExit(255)", receipt=False)
        code, result = self.invoke(["--request-ack"])
        self.assertEqual(code, 1, result)
        self.assertEqual(result["handoff"]["submission"]["status"], "unknown")
        self.assertFalse(result["retryAllowed"])
        self.assertNotIn("submitted", result)

    def test_complete_receipt_timeout_retains_known_submission(self):
        self.make_queue("time.sleep(3)")
        started = peer.handoff_now()
        code, result = self.invoke(["--request-ack", "--wait-timeout=6"])
        self.assertLess(peer.handoff_now() - started, 3)
        self.assertEqual(code, 0, result)
        self.assertTrue(result["submitted"])
        self.assertEqual(result["queueId"], "owned-queue-01")

    def test_timeout_without_receipt_remains_unknown(self):
        self.make_queue("time.sleep(3)", receipt=False)
        code, result = self.invoke(["--request-ack", "--wait-timeout=6"])
        self.assertEqual(code, 1, result)
        self.assertEqual(result["handoff"]["submission"]["status"], "unknown")

    def test_output_overflow_never_salvages_valid_prefix(self):
        self.make_queue("os.write(1,b'x'*1100000)")
        code, result = self.invoke(["--request-ack"])
        self.assertEqual(code, 1, result)
        self.assertEqual(result["handoff"]["submission"]["status"], "unknown")

    def test_native_snapshot_rejects_wrong_home_posted_or_consumption(self):
        _, result = self.invoke(["--request-ack"])
        record = self.ledger.record(result["handoff"]["correlationId"])[1]
        original = record["native"]
        for edits in ({"status": "posted"}, {"codexHome": str(self.root)}, {"consumptionConfirmed": True}, {"target": {"agent": "codex", "id": "invalid"}}):
            with self.subTest(edits=edits), self.assertRaises(peer.CcPeerError):
                peer.handoff_validate_native({**original, **edits}, record)

    def test_status_and_wait_never_invoke_queue(self):
        _, first = self.invoke(["--request-ack"])
        for action in ("status", "wait"):
            output = io.StringIO()
            args = ["handoff", action, "--correlation-id", first["handoff"]["correlationId"], "--json"]
            if action == "wait":
                args += ["--wait-for", "acknowledged", "--wait-timeout=6"]
            with mock.patch.object(peer, "handoff_root", return_value=self.ledger.root), mock.patch.object(peer, "handoff_codex_submit") as queue, contextlib.redirect_stdout(output):
                code = peer.main(args)
            self.assertEqual(code, 0 if action == "status" else 1)
            queue.assert_not_called()
            result = json.loads(output.getvalue())
            self.assertTrue(result["submitted"])
            self.assertEqual(result["handoff"]["ack"]["status"], "unsupported")

    def test_original_writer_evidence_changed_does_not_spawn_queue(self):
        original = peer.revalidate_codex_home
        calls = 0
        def changed(*args):
            nonlocal calls
            calls += 1
            if calls >= 2:
                raise peer.CcPeerError("owned writer changed")
            return original(*args)
        with mock.patch.object(peer, "revalidate_codex_home", side_effect=changed):
            code, result = self.invoke(["--request-ack"])
        self.assertEqual(code, 1, result)
        self.assertEqual(result["handoff"]["submission"]["status"], "refused")
        self.assertFalse(self.log.exists())

    def test_framed_codex_limit_refuses_before_effect(self):
        code, result = self.invoke(["--request-ack"], body="x" * 32768)
        self.assertEqual(code, 1, result)
        self.assertEqual(result["handoff"]["submission"]["status"], "refused")
        self.assertFalse(self.log.exists())
