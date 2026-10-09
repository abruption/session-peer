"""Owned SQLite/fake queue child tests, never a native Codex/model session."""
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import signal
import sqlite3
import subprocess
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
        code += "with open(" + repr(str(self.log)) + ", 'w') as f: json.dump({'argv':sys.argv[1:],'home':os.environ.get('CODEX_HOME'),'sqliteEnv':os.environ.get('CODEX_SQLITE_HOME')}, f)\n"
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

    def test_empty_inherited_sqlite_home_is_normalized_in_private_child(self):
        with mock.patch.dict(os.environ, {"CODEX_SQLITE_HOME": ""}):
            code, result = self.invoke(["--request-ack"])
        self.assertEqual(code, 0, result)
        self.assertIsNone(json.loads(self.log.read_text())["sqliteEnv"])

    def test_relocated_native_config_refuses_before_effect(self):
        (self.home / "config.toml").write_text('sqlite_home = "/owned/alternate"\n')
        code, result = self.invoke(["--request-ack"])
        self.assertEqual(code, 1, result)
        self.assertFalse(self.log.exists())

    def test_fenced_crash_history_never_submits_on_recovery(self):
        args = peer.build_parser().parse_args(["send", "--to", "codex:" + self.thread, "--message=x", "--codex-home", str(self.home), "--allow-inactive-codex-home", "--request-ack", "--json"])
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.home]):
            binding, generation, _ = peer.handoff_binding(args, "x")
        _, record = self.ledger.prepare(binding, generation)
        with self.ledger.transaction() as state:
            state["records"][record["id"]].update(phase="attempted", submission="unknown")
        with mock.patch.object(peer, "handoff_codex_submit") as queue:
            code, result = self.invoke(correlation=record["id"], body="x")
        self.assertEqual(code, 1, result)
        self.assertEqual(result["reason"], "handoff_already_attempted")
        queue.assert_not_called()
        retained = self.ledger.record(record["id"])[1]
        self.assertEqual(peer.handoff_public(self.ledger.record(record["id"])[0], retained)["state"], "unknown")
        self.assertIsNone(retained["capability"])

    def test_prepared_original_writer_context_is_not_rebound_on_restart(self):
        args = peer.build_parser().parse_args(["send", "--to", "codex:" + self.thread, "--message=x", "--codex-home", str(self.home), "--allow-inactive-codex-home", "--request-ack", "--json"])
        original_writer = {"activity": "live_writer", "writerLock": "held", "ownerPid": 100,
                           "ownerStable": True, "ownerStartTime": "original", "reason": "stable_live_writer"}
        with mock.patch.object(peer, "known_codex_homes", return_value=[self.home]), \
                mock.patch.object(peer, "inspect_codex_writer", return_value=original_writer):
            binding, generation, _ = peer.handoff_binding(args, "x")
        _, record = self.ledger.prepare(binding, generation, native_context=peer.handoff_native_context(args))
        with mock.patch.object(peer, "inspect_codex_writer", return_value={**original_writer, "ownerPid": 101, "ownerStartTime": "successor"}), \
                mock.patch.object(peer, "handoff_codex_submit") as queue:
            code, result = self.invoke(correlation=record["id"], body="x")
        self.assertEqual(code, 1, result)
        self.assertEqual(result["reason"], "handoff_native_context_changed")
        queue.assert_not_called()
        self.assertFalse(self.log.exists())
        self.assertIsNone(self.ledger.record(record["id"])[1]["generation"])

    def test_corrupt_or_missing_context_never_creates_submission_authority(self):
        code, first = self.invoke(["--request-ack"])
        self.assertEqual(code, 0)
        _, original = self.ledger.record(first["handoff"]["correlationId"])
        for context in (True, {"root": str(self.home), "resolution": {"schemaVersion": True}}):
            with self.subTest(context=context):
                malformed = {**original, "nativeContext": context}
                with self.assertRaises((peer.CcPeerError, ValueError)):
                    self.ledger._validate_record(malformed)
        # A forgotten ledger is not initialized by status or a resend attempt.
        output = io.StringIO()
        with mock.patch.object(peer, "handoff_root", return_value=self.root / "missing-ledger"), \
                mock.patch.object(peer, "handoff_codex_submit") as queue, contextlib.redirect_stdout(output):
            code = peer.main(["handoff", "status", "--correlation-id", first["handoff"]["correlationId"], "--json"])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["handoffQuery"]["context"], "ledger_missing")
        self.assertFalse((self.root / "missing-ledger").exists())
        queue.assert_not_called()

    def test_shared_clock_failure_after_spawn_still_reaps_owned_child(self):
        original_clock = peer.handoff_now
        original_popen = subprocess.Popen
        started = original_clock()
        calls = 0
        children = []
        def clock():
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise peer.handoff_error("handoff_clock_unavailable")
            return original_clock()
        def spawn(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            children.append(child)
            return child
        with mock.patch.object(peer, "handoff_now", side_effect=clock), mock.patch.object(peer.subprocess, "Popen", side_effect=spawn):
            result = peer.handoff_child([str(self.fake), "--version"], started + 1, started + 2)
        self.assertEqual(result["reason"], "native_clock_failed")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        self.assertLess(original_clock() - started, 1)

    def test_bounded_raw_stdin_reaches_one_fenced_queue_with_unicode_preserved(self):
        body = "전용 시험🙂\nsecond owned line\n"
        read_fd, write_fd = os.pipe()
        os.write(write_fd, body.encode("utf-8"))
        os.close(write_fd)
        args = ["send", "--to", "codex:" + self.thread, "--message=-", "--codex-home", str(self.home),
                "--codex-bin", str(self.fake), "--allow-inactive-codex-home", "--request-ack", "--no-from", "--no-reply-to", "--json"]
        output = io.StringIO()
        with os.fdopen(read_fd, "rb") as stream, mock.patch.object(peer.sys, "stdin", stream), \
                mock.patch.object(peer, "known_codex_homes", return_value=[self.home]), \
                mock.patch.object(peer, "handoff_root", return_value=self.ledger.root), contextlib.redirect_stdout(output):
            code = peer.main(args)
        self.assertEqual(code, 0, output.getvalue())
        result = json.loads(output.getvalue())
        self.assertTrue(result["submitted"])
        emitted = json.loads(self.log.read_text())["argv"][-1].removeprefix("--message=")
        self.assertIn("| 전용 시험🙂\n| second owned line\n| ", emitted)
        self.assertEqual(result["chars"], len(emitted))
