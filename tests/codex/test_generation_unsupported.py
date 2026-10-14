"""Negative fixtures: weak Codex evidence is never promoted to a generation.

The reviewed queued-input paths in native Codex 0.162.1 (rust-v0.162.1,
092d3acd6bec) did not establish a supported atomic original-incarnation
precondition. This is not a proof about every native API or future version.
These offline tests prove that
session-peer keeps Codex generation `unsupported` whatever weak evidence is
present. They are not evidence of native delivery or consumption.
"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import session_peer as peer
from tests.codex.support import THREAD

CLAUDE_SHAPED = "tg1:" + "a" * 64


class CodexGenerationUnsupported(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        environment = mock.patch.dict(os.environ, {
            "HOME": str(self.root), "USERPROFILE": str(self.root),
            "CODEX_HOME": str(self.root)}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        for name in ("codex_system_config_paths", "codex_managed_preference_paths"):
            if hasattr(peer, name):
                layer = mock.patch.object(peer, name, return_value=[])
                layer.start()
                self.addCleanup(layer.stop)

    def invoke(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = peer.main([*argv, "--json", "--no-update-notice"])
        return code, json.loads(out.getvalue())

    def strongest_weak_row(self, **extra):
        # Every field a caller might mistake for an incarnation guarantee.
        return {"agent": "codex", "id": THREAD, "name": "worker", "status": "active",
                "archived": False, "cwd": "/fixture", "codexHome": str(self.root),
                "activity": "live_writer", "writerLock": "held", "ownerPid": 4242,
                "ownerStable": True, "ownerStartTime": 1700000000.25,
                "queueId": "01900000-0000-7000-8000-0000000000aa",
                "clientUserMessageId": "01900000-0000-7000-8000-0000000000bb",
                "canAcceptDirectInput": True, "sessionId": THREAD,
                "queueRevision": 7, "expectedTurnId": "01900000-0000-7000-8000-0000000000cc",
                **extra}

    def test_listing_never_mints_codex_generation_from_writer_queue_or_session_evidence(self):
        row = self.strongest_weak_row()
        with mock.patch.object(peer.CodexAdapter, "list", return_value={
                "sessions": [row], "discovery": {"status": "ok"}}), \
                mock.patch.object(peer, "claude_generation") as minted:
            code, result = self.invoke("list", "--agent", "codex", "--with-target-generation")
        self.assertEqual(code, 0)
        listed = result["sessions"][0]
        self.assertIsNone(listed["targetGeneration"])
        self.assertEqual(listed["generationStatus"], "unsupported")
        minted.assert_not_called()

    def test_saved_discovery_with_arbitrary_lock_content_stays_unsupported(self):
        with contextlib.closing(sqlite3.connect(self.root / "state_5.sqlite")) as conn:
            conn.execute("CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)")
            conn.execute("INSERT INTO threads VALUES (?,?,?,?,?,?)",
                         (THREAD, "fixture", str(self.root), 1, 0, "unused"))
            conn.commit()
        locks = self.root / "thread-writer-locks"
        locks.mkdir()
        # Native writers leave the lock empty; any content is not a token either.
        for content in (b"", b"pid=4242 generation=" + b"f" * 64, CLAUDE_SHAPED.encode()):
            with self.subTest(content=content[:16]):
                (locks / f"{THREAD}.lock").write_bytes(content)
                # Saved-row listing does not call inspect_codex_writer. This
                # case tests lock content only; stable writer fields are covered
                # by the explicit adapter-row fixture above.
                with mock.patch.object(peer, "claude_generation") as minted, \
                        mock.patch.object(peer, "inspect_codex_writer", wraps=peer.inspect_codex_writer) as inspected:
                    code, result = self.invoke("list", "--agent", "codex", "--codex-home",
                                               str(self.root), "--with-target-generation")
                self.assertEqual(code, 0)
                rows = [row for row in result["sessions"] if row.get("id") == THREAD]
                self.assertEqual(len(rows), 1)
                self.assertIsNone(rows[0]["targetGeneration"])
                self.assertEqual(rows[0]["generationStatus"], "unsupported")
                minted.assert_not_called()
                inspected.assert_not_called()

    def test_changed_writer_rows_stay_unsupported_and_arbitrary_pins_are_refused(self):
        # Two synthetic listings and a separate pin refusal, not a live race.
        for owner in (4242, 4243):
            with mock.patch.object(peer.CodexAdapter, "list", return_value={
                    "sessions": [self.strongest_weak_row(ownerPid=owner)],
                    "discovery": {"status": "ok"}}):
                code, result = self.invoke("list", "--agent", "codex", "--with-target-generation")
            self.assertEqual(code, 0)
            self.assertIsNone(result["sessions"][0]["targetGeneration"])
        for token in (CLAUDE_SHAPED, "tg1:" + "0" * 64):
            for options in ([], ["--dry-run"], ["--wake"], ["--host", "test-host"]):
                with self.subTest(token=token[:8], options=options), \
                        mock.patch.object(peer, "queue_codex") as queue, \
                        mock.patch.object(peer, "run_codex_wake") as wake, \
                        mock.patch.object(peer.SshTransport, "execute") as remote, \
                        mock.patch.object(peer, "tailscale_status") as network_discovery, \
                        mock.patch.object(peer.subprocess, "run") as child:
                    code, result = self.invoke("send", "--to", "codex:" + THREAD,
                                               "--target-generation", token, "--message=x",
                                               "--no-from", "--no-reply-to", *options)
                self.assertEqual(code, 1)
                self.assertEqual(result["reason"], "unsupported_target_generation")
                self.assertIs(result["submitted"], False)
                self.assertIs(result["retryAllowed"], False)
                self.assertNotIn("lastSeenTarget", result)
                for effect in (queue, wake, remote, child, network_discovery):
                    effect.assert_not_called()

    def test_successful_queue_result_never_carries_a_generation(self):
        queued = {"ok": True, "target": {"agent": "codex", "id": THREAD}, "chars": 1,
                  "dryRun": False, "codexHome": str(self.root), "submitted": True,
                  "consumptionConfirmed": False, "status": "queued",
                  "queueId": "01900000-0000-7000-8000-0000000000aa"}
        with mock.patch.object(peer, "queue_codex", return_value=queued) as queue:
            code, result = self.invoke("send", "--to", "codex:" + THREAD, "--message=x",
                                       "--no-from", "--no-reply-to")
        self.assertEqual(code, 0)
        queue.assert_called_once()
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["queueId"], queued["queueId"])
        self.assertNotIn("targetGeneration", result)
        self.assertIs(result["consumptionConfirmed"], False)

    def test_codex_adapter_contract_has_no_generation_capability(self):
        adapter = peer.AGENTS.for_target("codex:" + THREAD)
        args = argparse.Namespace(to="codex:" + THREAD, target_generation=CLAUDE_SHAPED,
                                  wake=False, host=[])
        with self.assertRaises(peer.CcPeerError) as caught:
            adapter.validate_send(args, "x")
        self.assertEqual(caught.exception.details["reason"], "unsupported_target_generation")
        args.target_generation = None
        adapter.validate_send(args, "x")


if __name__ == "__main__":
    unittest.main()
