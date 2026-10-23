"""Address-specific effect guards reuse native ownership, never manufacture epochs."""
import contextlib
import copy
import io
import json
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import session_peer as peer
from tests.codex import test_dispatch as fixture
from tests.codex.support import THREAD


class AddressSendGuards(unittest.TestCase):
    def setUp(self):
        fixture.Codex.setUp(self)
        self.args.allow_inactive_codex_home = False
        self.owner = {"activity": "live_writer", "writerLock": "held", "ownerStable": True,
                      "ownerPid": 42, "ownerStartTime": 123456}
        self.resolution = {"schemaVersion": 1, "status": "selected", "selected": str(self.root),
            "reason": "explicit_live_writer", "candidates": [
                {"codexHome": str(self.root), "savedThread": True, **self.owner}]}
        self.args._address_expected_writer = peer.address_codex_writer_revision(self.root, THREAD, self.resolution)

    @contextlib.contextmanager
    def native(self, environment=None):
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(peer, "codex_executable", return_value="codex-fixture"))
            stack.enter_context(mock.patch.object(peer, "resolve_codex_home", return_value=(self.root, self.resolution)))
            stack.enter_context(mock.patch.object(peer, "codex_queue_storage_preflight", return_value=self.root))
            stack.enter_context(mock.patch.object(peer, "codex_queue_preference_policy", return_value=False))
            stack.enter_context(mock.patch.object(peer, "check_codex_consumer_storage"))
            stack.enter_context(mock.patch.object(peer, "codex_process_environment", side_effect=environment,
                                                  return_value={}))
            inspection = stack.enter_context(mock.patch.object(peer, "inspect_codex_writer", side_effect=lambda *a: dict(self.owner)))
            child = stack.enter_context(mock.patch.object(peer.subprocess, "run", return_value=
                subprocess.CompletedProcess([], 0, stdout="", stderr="")))
            yield inspection, child

    def test_changed_saved_writer_refuses_preview_and_effect(self):
        for preview in (False, True):
            self.args.dry_run = preview
            self.args._address_expected_writer = "aw1:" + "0" * 64
            with self.native() as (_, child), self.assertRaises(peer.CcPeerError) as error:
                peer._queue_codex(self.args, "fixture")
            self.assertEqual(error.exception.details["reason"], "address_writer_changed")
            self.assertFalse(error.exception.details["submitted"])
            self.assertFalse(error.exception.details["retryAllowed"])
            child.assert_not_called()

    def test_writer_change_during_storage_checks_refuses_before_native_child(self):
        def environment(*args, **kwargs):
            self.owner["ownerPid"] = 43
            return {}
        with self.native(environment) as (inspection, child), self.assertRaises(peer.CcPeerError) as error:
            peer._queue_codex(self.args, "fixture")
        self.assertEqual(error.exception.details["reason"], "address_writer_changed")
        self.assertFalse(error.exception.details["submitted"])
        self.assertFalse(error.exception.details["retryAllowed"])
        self.assertEqual(inspection.call_count, 2)
        child.assert_not_called()

    def test_matching_writer_submits_once_without_generation_claim(self):
        with self.native() as (inspection, child):
            result = peer._queue_codex(self.args, "fixture")
        self.assertTrue(result["ok"])
        self.assertTrue(result["submitted"])
        self.assertFalse(result["consumptionConfirmed"])
        self.assertNotIn("targetGeneration", result)
        self.assertEqual(inspection.call_count, 2)
        child.assert_called_once()

    def test_remote_effect_carries_the_exact_writer_observation_guard(self):
        result = {"ok": True, "target": {"agent": "codex", "id": THREAD}, "dryRun": True,
                  "submitted": False, "consumptionConfirmed": False, "status": "validated", "chars": 7}
        out = io.StringIO()
        with mock.patch.object(peer, "tailscale_status", return_value={}), \
                mock.patch.object(peer, "SshTransport") as transport, contextlib.redirect_stdout(out):
            transport.return_value.host = "fixture"
            transport.return_value.ssh_opts = []
            transport.return_value.execute.return_value = result
            code = peer.main(["send", "--host", "fixture", "--to", "codex:" + THREAD,
                "--_address-writer-revision", self.args._address_expected_writer,
                "--message", "fixture", "--dry-run", "--json", "--no-from", "--no-reply-to"])
        self.assertEqual(code, 0)
        argv = transport.return_value.execute.call_args.args[0]
        index = argv.index("--_address-writer-revision")
        self.assertEqual(argv[index + 1], self.args._address_expected_writer)
        transport.return_value.execute.assert_called_once()


class AddressInspectionWire(unittest.TestCase):
    def test_real_home_alias_resolves_and_inventory_deduplicates(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("SESSION_PEER_TEST_TMP")) as directory:
            base = Path(directory).resolve()
            actual = base / "actual"
            actual.mkdir()
            (actual / "state_5.sqlite").touch()
            alias = base / "alias"
            try:
                alias.symlink_to(actual, target_is_directory=True)
            except OSError:
                self.skipTest("symlink creation unavailable")
            args = argparse.Namespace(codex_home=str(alias))
            self.assertEqual(peer.codex_home(args), actual)
            with mock.patch.object(peer.Path, "home", return_value=base / "empty-user"), \
                    mock.patch.object(peer, "configured_codex_home_paths", return_value=[alias, actual]):
                self.assertEqual(peer.known_codex_homes(peer.codex_home(args)), [actual])

    def test_public_inspection_keeps_partial_failure_in_json_and_exit(self):
        payload = {"selectionSchemaVersion": 1, "homeSelector": None, "ok": False,
                   "selections": [{"requestedTarget": "missing", "ok": False,
                                   "reason": "address_selection_unavailable"}]}
        output = io.StringIO()
        with mock.patch.object(peer, "address_inspect_selection", return_value=payload), \
                contextlib.redirect_stdout(output):
            code = peer.main(["address", "_inspect", "--agent", "claude", "--to=missing", "--json"])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["selections"], payload["selections"])

    def test_partial_private_metadata_survives_transport_for_exact_consumer_validation(self):
        payload = {"schemaVersion": 1, "ok": False, "command": "address", "host": "fixture",
                   "selectionSchemaVersion": 1, "selections": [{"ok": False}]}
        done = subprocess.CompletedProcess([], 1, stdout=json.dumps(payload), stderr="")
        with mock.patch.object(peer, "ssh_user_metadata", return_value={}), \
                mock.patch.object(peer.subprocess, "run", return_value=done):
            result = peer.run_remote("fixture", ["address", "_inspect", "--agent", "claude", "--to", "worker"], [])
            self.assertEqual(result["selections"], payload["selections"])
            with self.assertRaises(peer.CcPeerError):
                peer.run_remote("fixture", ["address", "show", "worker"], [])
