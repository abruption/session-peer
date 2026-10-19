"""Offline known-profile inventory; no native inbox connections or credentials."""
import argparse
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

import session_peer as peer


class ClaudeProfiles(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="sp317-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.default = self.root / ".claude/sessions"
        self.default.mkdir(parents=True)
        self.base = self.root / "Library/Application Support/orca/claude-profiles"
        self.base.mkdir(parents=True)
        self.counter = 0
        for patcher in (
            mock.patch.object(Path, "home", return_value=self.root),
            mock.patch.object(peer.sys, "platform", "darwin"),
            mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "", "ANTHROPIC_CONFIG_DIR": ""}),
            mock.patch.object(peer, "pid_alive", return_value=True),
            mock.patch.object(peer, "windows_process_start_ms", return_value=1000),
            mock.patch.object(peer, "process_generation", return_value="fixture-birth"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def profile(self, name):
        directory = self.base / name / "home/sessions"
        directory.mkdir(parents=True)
        return directory

    def record(self, directory, pid, name="worker", inbox=None):
        if inbox is None:
            self.counter += 1
            if peer.IS_WINDOWS:
                inbox = r"\\.\pipe\fixture-" + str(self.counter)
            else:
                inbox = str(self.root / (str(self.counter) + ".sock"))
                listener = socket.socket(socket.AF_UNIX)
                listener.bind(inbox)
                self.addCleanup(listener.close)
        record = {"pid": pid, "name": name, "startedAt": 1000,
                  "cwd": "/fixture", "status": "idle", "messagingSocketPath": inbox}
        (directory / (str(pid) + ".json")).write_text(json.dumps(record), encoding="utf-8")
        return record

    def test_default_and_multiple_orca_profiles_without_private_json_fields(self):
        self.record(self.default, 100, "default")
        self.record(self.profile("one"), 101, "one")
        self.record(self.profile("two"), 102, "two")
        with mock.patch.object(peer, "_read_win_auth") as auth:
            rows = peer.discover()
            diagnostic = peer.diagnose_claude()
        self.assertEqual({row["pid"] for row in rows}, {100, 101, 102})
        self.assertEqual(rows.errors, [])
        self.assertEqual(diagnostic["availableInboxes"], 3)
        self.assertEqual(diagnostic["status"], "available")
        self.assertNotIn("registry", json.dumps(rows))
        self.assertNotIn("claude-profiles", json.dumps(rows))
        auth.assert_not_called()

    def test_explicit_environment_scope_and_precedence(self):
        first, second = self.profile("first"), self.profile("second")
        self.record(self.default, 100)
        self.record(first, 101)
        self.record(second, 102)
        for primary in (True, False):
            with self.subTest(primary=primary), mock.patch.dict(os.environ, {
                "CLAUDE_CONFIG_DIR": str(first.parent) if primary else "",
                "ANTHROPIC_CONFIG_DIR": str(second.parent),
            }), mock.patch.object(peer.os, "scandir", wraps=os.scandir) as scan:
                rows = peer.discover()
                self.assertEqual([row["pid"] for row in rows], [101 if primary else 102])
                self.assertNotIn(mock.call(self.base), scan.call_args_list)

    def test_non_macos_does_not_guess_orca_locations(self):
        self.record(self.profile("one"), 101)
        with mock.patch.object(peer.sys, "platform", "linux"):
            self.assertEqual(peer.discover(), [])

    def test_missing_default_and_unstarted_profiles_are_not_errors(self):
        self.default.rmdir()
        (self.base / "unstarted").mkdir()
        self.record(self.profile("ready"), 101)
        rows = peer.discover()
        self.assertEqual([row["pid"] for row in rows], [101])
        self.assertEqual(rows.errors, [])

    def test_profile_metadata_files_are_not_opened_or_treated_as_homes(self):
        self.record(self.profile("ready"), 101)
        for name in (".DS_Store", "metadata.txt", "account.key"):
            (self.base / name).write_text("not a profile", encoding="utf-8")
        original = os.open
        def read(path, *args, **kwargs):
            self.assertEqual(Path(path).suffix, ".json", "Only registry JSON may be opened")
            return original(path, *args, **kwargs)
        with mock.patch.object(peer.os, "open", side_effect=read), \
                mock.patch.object(peer, "_read_win_auth") as auth:
            rows = peer.discover()
            self.assertEqual(peer.diagnose_claude()["status"], "available")
        self.assertEqual([row["pid"] for row in rows], [101])
        self.assertEqual(rows.errors, [])
        auth.assert_not_called()

    def test_malformed_oversized_and_unreadable_records_keep_healthy_rows(self):
        good, bad = self.profile("good"), self.profile("bad")
        self.record(good, 101)
        (bad / "102.json").write_text("{", encoding="utf-8")
        (bad / "103.json").write_bytes(b"x" * (peer.MAX_CLAUDE_RECORD_BYTES + 1))
        self.record(bad, 104)
        original = peer.read_claude_record
        def read(path):
            if path.name == "104.json":
                raise PermissionError("fixture")
            return original(path)
        with mock.patch.object(peer, "read_claude_record", side_effect=read):
            result = peer.ClaudeAdapter().list(peer.ExecutionContext("local", argparse.Namespace(all=False)))
            diagnostic = peer.diagnose_claude()
        self.assertEqual([row["pid"] for row in result["sessions"]], [101])
        self.assertEqual(result["discovery"]["status"], "error")
        self.assertEqual(diagnostic["status"], "permission_denied")
        self.assertEqual(diagnostic["availableInboxes"], 1)
        self.assertNotIn(str(bad), json.dumps(result["discovery"]))

    def test_incomplete_inventory_refuses_dry_run_send_and_handoff(self):
        self.record(self.profile("good"), 101)
        (self.profile("bad") / "102.json").write_text("{", encoding="utf-8")
        with mock.patch.object(peer, "post_to_socket") as post:
            for dry in (False, True):
                args = argparse.Namespace(to="101", dry_run=dry)
                with self.subTest(dry=dry), self.assertRaises(peer.CcPeerError):
                    peer.ClaudeAdapter().submit(peer.ExecutionContext("local", args), "fixture")
            with self.assertRaises(peer.CcPeerError):
                peer.handoff_binding(argparse.Namespace(to="101"), "fixture")
        post.assert_not_called()

    def test_doctor_uses_same_bound_and_conflict_rules(self):
        self.record(self.default, 100)
        with mock.patch.object(peer, "MAX_CLAUDE_RECORDS", 0):
            self.assertEqual(peer.diagnose_claude()["status"], "unknown")
        one, two = self.profile("one"), self.profile("two")
        record = self.record(one, 101)
        (two / "101.json").write_text(json.dumps(record), encoding="utf-8")
        diagnostic = peer.diagnose_claude()
        self.assertEqual(diagnostic["status"], "unknown")
        self.assertEqual(diagnostic["availableInboxes"], 1)

    def test_unreadable_profile_preserves_other_profile(self):
        good, bad = self.profile("good"), self.profile("bad")
        self.record(good, 101)
        original = os.scandir
        def scan(path):
            if Path(path) == bad:
                raise PermissionError("fixture")
            return original(path)
        with mock.patch.object(peer.os, "scandir", side_effect=scan):
            rows = peer.discover()
        self.assertEqual([row["pid"] for row in rows], [101])
        self.assertIn("sessions_directory_unavailable", rows.errors)

    def test_inventory_limits_are_reported(self):
        self.record(self.profile("one"), 101)
        self.record(self.profile("two"), 102)
        with mock.patch.object(peer, "MAX_CLAUDE_PROFILES", 1):
            self.assertIn("profile_inventory_limit", peer.discover().errors)
        with mock.patch.object(peer, "MAX_CLAUDE_RECORDS", 1):
            rows = peer.discover()
            self.assertLessEqual(len(rows), 1)
            self.assertIn("session_inventory_limit", rows.errors)

    @unittest.skipIf(os.name == "nt", "symlink privilege is not assumed")
    def test_profile_symlink_and_home_symlink_are_not_followed(self):
        target = self.root / "outside/sessions"
        target.mkdir(parents=True)
        self.record(target, 101)
        (self.base / "alias").symlink_to(target.parent, target_is_directory=True)
        profile = self.base / "home-alias"
        profile.mkdir()
        (profile / "home").symlink_to(target.parent, target_is_directory=True)
        rows = peer.discover()
        self.assertEqual(rows, [])
        self.assertIn("profile_directory_unavailable", rows.errors)

    def test_reparse_and_foreign_uid_directories_are_rejected(self):
        node = self.base.stat()
        fields = dict(st_mode=node.st_mode, st_uid=getattr(node, "st_uid", 0),
                      st_dev=node.st_dev, st_ino=node.st_ino, st_file_attributes=0x400)
        with mock.patch.object(Path, "lstat", return_value=argparse.Namespace(**fields)):
            with self.assertRaises(ValueError):
                peer._claude_safe_directory(self.base)
        if hasattr(os, "getuid"):
            fields.update(st_file_attributes=0, st_uid=os.getuid() + 1)
            with mock.patch.object(Path, "lstat", return_value=argparse.Namespace(**fields)):
                with self.assertRaises(ValueError):
                    peer._claude_safe_directory(self.base)

    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX directory ownership")
    def test_explicit_directory_preserves_existing_readable_owner_scope(self):
        self.record(self.default, 100)
        actual_uid = os.getuid()
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.default.parent)}), \
                mock.patch.object(peer.os, "getuid", return_value=actual_uid + 1):
            selected = peer.discover()[0]
            peer.revalidate_claude_selection(selected)
        self.assertEqual(selected["pid"], 100)

    @unittest.skipIf(os.name == "nt", "symlink privilege is not assumed")
    def test_default_symlink_loop_preserves_healthy_profile_as_partial(self):
        self.default.rmdir()
        self.default.symlink_to(self.default, target_is_directory=True)
        self.record(self.profile("one"), 101)
        rows = peer.discover()
        self.assertEqual([row["pid"] for row in rows], [101])
        self.assertIn("sessions_directory_unavailable", rows.errors)

    def test_profile_disappearance_after_inventory_is_incomplete(self):
        directory = self.profile("one")
        self.record(directory, 101)
        inventory = peer.claude_registry_directories()
        directory.rename(directory.parent / "old-sessions")
        with mock.patch.object(peer, "claude_registry_directories", return_value=inventory):
            rows = peer.discover()
        self.assertIn("sessions_directory_unavailable", rows.errors)

    def test_stale_pid_or_inbox_is_not_a_reachable_profile(self):
        directory = self.profile("one")
        self.record(directory, 101)
        with mock.patch.object(peer, "claude_process_state", return_value=(False, "process_not_live")):
            self.assertEqual(peer.discover(), [])
            self.assertFalse(peer.discover(True)[0]["reachable"])
        value = self.record(directory, 102)
        value["messagingSocketPath"] = ""
        (directory / "102.json").write_text(json.dumps(value), encoding="utf-8")
        self.assertEqual([row["pid"] for row in peer.discover()], [101])

    @unittest.skipIf(os.name == "nt", "symlink privilege is not assumed")
    def test_canonical_alias_dedup_and_name_ambiguity(self):
        one, two = self.profile("one"), self.profile("two")
        self.record(one, 101)
        self.default.rmdir()
        self.default.symlink_to(one, target_is_directory=True)
        self.assertEqual(len(peer.discover()), 1)
        self.record(two, 102)
        rows = peer.discover()
        with self.assertRaises(peer.CcPeerError):
            peer.resolve_target(rows, "worker")
        self.assertEqual(peer.resolve_target(rows, "102")["pid"], 102)

    def test_identical_records_in_distinct_profile_roots_are_conflicting(self):
        one, two = self.profile("one"), self.profile("two")
        record = self.record(one, 101)
        (two / "101.json").write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(peer.discover(), [])
        self.assertEqual(len(peer.discover(True)), 2)

    @unittest.skipIf(os.name == "nt", "symlink privilege is not assumed")
    def test_explicit_default_alias_cannot_retarget_after_selection(self):
        one, two = self.profile("one"), self.profile("two")
        record = self.record(one, 101)
        (two / "101.json").write_text(json.dumps(record), encoding="utf-8")
        self.default.rmdir()
        self.default.symlink_to(one, target_is_directory=True)
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.default.parent)}):
            selected = peer.discover()[0]
            peer.revalidate_claude_selection(selected)
            self.default.unlink()
            self.default.symlink_to(two, target_is_directory=True)
            with self.assertRaises(peer.CcPeerError):
                peer.revalidate_claude_selection(selected)

    def test_conflicting_pid_or_inbox_never_selects_by_inventory_order(self):
        one, two = self.profile("one"), self.profile("two")
        original = self.record(one, 101)
        for pid, inbox in ((101, None), (102, original["messagingSocketPath"])):
            with self.subTest(pid=pid):
                for path in two.glob("*.json"):
                    path.unlink()
                self.record(two, pid, "conflict", inbox)
                self.assertEqual(peer.discover(), [])
                rows = peer.discover(True)
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(not row["reachable"] for row in rows))
                with self.assertRaises(peer.CcPeerError):
                    peer.resolve_target(rows, "101")

    def test_proven_dead_record_does_not_claim_successors_reused_socket(self):
        one, two = self.profile("one"), self.profile("two")
        record = self.record(one, 101)
        self.record(two, 102, inbox=record["messagingSocketPath"])
        with mock.patch.object(peer, "claude_process_state", side_effect=lambda row, pid:
                               (pid == 102, None if pid == 102 else "process_not_live")):
            rows = peer.discover()
        self.assertEqual([row["pid"] for row in rows], [102])
        self.assertEqual(rows.errors, [])

    def test_generation_uses_selected_profile_and_survives_adapter_listing(self):
        directory = self.profile("one")
        self.record(directory, 101)
        result = peer.ClaudeAdapter().list(peer.ExecutionContext("local", argparse.Namespace(all=False)))
        selected = result["sessions"][0]
        generation = peer.claude_generation(selected)
        self.assertRegex(generation, r"^tg1:[0-9a-f]{64}$")
        self.assertEqual(selected.registry_directory, directory)
        self.assertFalse((self.default / "101.json").exists())
        with mock.patch.object(peer, "discover", return_value=[selected]):
            binding, pinned, handoff_session = peer.handoff_binding(
                argparse.Namespace(to="101", target_generation=generation), "fixture")
        self.assertIs(handoff_session, selected)
        self.assertEqual(pinned, generation)
        self.assertEqual(binding["target"], "101")
        args = argparse.Namespace(all=False, with_target_generation=True)
        listing = peer.LocalTransport().execute("list", peer.ClaudeAdapter(), args)
        self.assertIsInstance(listing["sessions"][0], peer.ClaudeSession)
        self.assertEqual(listing["sessions"][0]["targetGeneration"], generation)
        self.assertNotIn("registry", json.dumps(listing))

    def test_replaced_profile_or_record_refuses_before_dry_run_or_send(self):
        directory = self.profile("one")
        self.record(directory, 101)
        selected = peer.discover()[0]
        replacement = directory.parent / "replaced"
        directory.rename(replacement)
        directory.mkdir()
        self.record(directory, 101)
        with mock.patch.object(peer, "discover", return_value=[selected]), \
                mock.patch.object(peer, "post_to_socket") as post:
            for dry in (True, False):
                with self.subTest(dry=dry), self.assertRaises(peer.CcPeerError):
                    peer.ClaudeAdapter().submit(peer.ExecutionContext("local",
                        argparse.Namespace(to="101", dry_run=dry)), "fixture")
        post.assert_not_called()
        self.assertIsNone(peer.claude_generation(selected))

    def test_endpoint_replacement_and_symlink_retarget_are_refused(self):
        directory = self.profile("one")
        record = self.record(directory, 101)
        selected = peer.discover()[0]
        record["messagingSocketPath"] = "replaced"
        (directory / "101.json").write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(peer.CcPeerError):
            peer.revalidate_claude_selection(selected)

    @unittest.skipIf(os.name == "nt", "POSIX socket boundary")
    def test_profile_replacement_during_connect_prevents_any_write(self):
        directory = self.profile("one")
        self.record(directory, 101)
        selected = peer.discover()[0]
        def replace(_):
            directory.rename(directory.parent / "old-sessions")
            directory.mkdir()
        connection = mock.Mock()
        connection.connect.side_effect = replace
        with mock.patch.object(peer.socket, "socket", return_value=connection):
            with self.assertRaises(peer.CcPeerError):
                peer.post_to_socket(selected["socket"], "fixture", pid=101,
                                    generation_session=selected)
        connection.sendall.assert_not_called()
        connection.close.assert_called_once()

    def test_windows_auth_reader_uses_selected_root_only_when_sending(self):
        directory = self.profile("one")
        self.record(directory, 101)
        selected = peer.discover()[0]
        with mock.patch.object(peer, "IS_WINDOWS", True), \
                mock.patch.object(peer, "_read_win_auth", return_value=None) as auth:
            with self.assertRaises(peer.CcPeerError):
                peer._post_to_pipe(r"\\.\pipe\fixture", 101, "fixture", generation_session=selected)
        auth.assert_called_once_with(101, directory)

    def test_selected_decimal_filename_aliases_preserve_ordinary_dry_run(self):
        for stem in ("00101", "١٠١"):
            with self.subTest(stem=stem):
                for old_record in self.default.glob("*.json"):
                    old_record.unlink()
                self.record(self.default, 101)
                canonical_generation = peer.claude_generation(peer.discover()[0])
                (self.default / "101.json").rename(self.default / (stem + ".json"))
                with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.default.parent)}):
                    selected = peer.discover()[0]
                    peer.revalidate_claude_selection(selected)
                    result = peer.ClaudeAdapter().submit(peer.ExecutionContext("local",
                        argparse.Namespace(to="101", dry_run=True)), "fixture")
                self.assertTrue(result["dryRun"])
                self.assertEqual(peer.claude_generation(selected), canonical_generation)
                self.assertNotIn("registry", json.dumps(selected))
                value = json.loads((self.default / (stem + ".json")).read_text(encoding="utf-8"))
                value["startedAt"] += 1
                (self.default / (stem + ".json")).write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(peer.CcPeerError):
                    peer.revalidate_claude_selection(selected)
                (self.default / (stem + ".json")).unlink()

    @unittest.skipIf(os.name == "nt", "POSIX socket aliases")
    def test_ordinary_socket_alias_remains_usable_and_retarget_is_refused(self):
        record = self.record(self.default, 101)
        alias = self.root / "alias.sock"
        alias.symlink_to(record["messagingSocketPath"])
        record["messagingSocketPath"] = str(alias)
        (self.default / "101.json").write_text(json.dumps(record), encoding="utf-8")
        selected = peer.discover()[0]
        peer.revalidate_claude_selection(selected)
        self.assertIsNone(peer.claude_generation(selected), "Existing alias-generation limit remains")
        connection = mock.Mock()
        with mock.patch.object(peer.socket, "socket", return_value=connection):
            peer.post_to_socket(selected["socket"], "fixture", pid=101, generation_session=selected)
        connection.connect.assert_called_once_with(str(alias))
        connection.sendall.assert_called_once()
        alias.unlink()
        other = self.record(self.default, 102)
        alias.symlink_to(other["messagingSocketPath"])
        with self.assertRaises(peer.CcPeerError) as caught:
            peer.revalidate_claude_selection(selected)
        self.assertEqual(caught.exception.details.get("status"), "refused")

    def test_doctor_directory_and_record_permission_classifications_are_preserved(self):
        self.record(self.default, 101)
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.default.parent)}), \
                mock.patch.object(peer.os, "scandir", side_effect=PermissionError("fixture")):
            result = peer.diagnose_claude()
        self.assertEqual(result["status"], "permission_denied")
        self.assertEqual(result["checks"][0]["code"], "sessions_dir_permission_denied")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.default.parent)}), \
                mock.patch.object(peer, "read_claude_record", side_effect=PermissionError("fixture")):
            result = peer.diagnose_claude()
        self.assertEqual(result["status"], "permission_denied")
        self.assertEqual(result["invalidRecords"], 0)
        self.assertEqual(result["checks"][0]["count"], 1)

    @unittest.skipIf(os.name == "nt", "symlink privilege is not assumed")
    def test_canonical_registry_is_read_once_despite_status_changes(self):
        directory = self.profile("one")
        self.record(directory, 101)
        self.default.rmdir()
        self.default.symlink_to(directory, target_is_directory=True)
        original = peer.read_claude_record
        reads = []
        def read(path):
            record = original(path)
            reads.append(path)
            record["status"] = "idle" if len(reads) == 1 else "busy"
            return record
        with mock.patch.object(peer, "read_claude_record", side_effect=read):
            rows = peer.discover()
        self.assertEqual(len(reads), 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.errors, [])

    @unittest.skipIf(os.name == "nt", "POSIX socket boundary")
    def test_after_connect_selection_refusal_is_typed_no_effect(self):
        directory = self.profile("one")
        self.record(directory, 101)
        selected = peer.discover()[0]
        connection = mock.Mock()
        def replace(_):
            directory.rename(directory.parent / "old-sessions")
            directory.mkdir()
        connection.connect.side_effect = replace
        with mock.patch.object(peer.socket, "socket", return_value=connection):
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.post_to_socket(selected["socket"], "fixture", pid=101, generation_session=selected)
        self.assertEqual(caught.exception.details.get("status"), "refused")
        self.assertFalse(caught.exception.details.get("submitted", True))
        self.assertFalse(caught.exception.details.get("retryAllowed", True))
        self.assertNotIn("lastSeenTarget", caught.exception.details)
        connection.sendall.assert_not_called()

    @unittest.skipIf(os.name == "nt", "POSIX handoff boundary")
    def test_local_handoff_records_before_and_after_connect_changes_as_refused(self):
        for boundary in ("before", "after"):
            with self.subTest(boundary=boundary):
                directory = self.profile(boundary)
                self.record(directory, 101)
                ledger_root = self.root / ("ledger-" + boundary)
                peer.HandoffLedger(ledger_root).initialize()
                output = io.StringIO()
                connection = mock.Mock()
                def replace():
                    directory.rename(directory.parent / "old-sessions")
                    directory.mkdir()
                real_post = peer.post_to_socket
                def post(*args, **kwargs):
                    if boundary == "before":
                        replace()
                    return real_post(*args, **kwargs)
                if boundary == "after":
                    connection.connect.side_effect = lambda _: replace()
                with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(directory.parent)}), \
                        mock.patch.object(peer, "handoff_root", return_value=ledger_root), \
                        mock.patch.object(peer, "handoff_now_ns", side_effect=peer.time.monotonic_ns), \
                        mock.patch.object(peer, "handoff_boot_clock", return_value="a" * 64), \
                        mock.patch.object(peer, "post_to_socket", side_effect=post), \
                        mock.patch.object(peer.socket, "socket", return_value=connection), \
                        contextlib.redirect_stdout(output):
                    code = peer.main(["send", "--to=101", "--message=fixture", "--observe-delivery",
                                      "--no-from", "--no-reply-to", "--no-update-notice", "--json"])
                result = json.loads(output.getvalue())
                self.assertEqual(code, 1)
                self.assertEqual(result["handoff"]["submission"]["status"], "refused")
                self.assertEqual(result["reason"], "native_submission_refused")
                self.assertFalse(result["retryAllowed"])
                connection.sendall.assert_not_called()
                self.assertEqual(connection.connect.call_count, int(boundary == "after"))

    @unittest.skipIf(os.name == "nt", "POSIX private source streaming")
    def test_remote_handoff_after_connect_change_is_refused_without_writes(self):
        directory = self.profile("remote")
        self.record(directory, 101)
        context = {"schemaVersion": 1, "phase": "probe", "requestId": str(peer.uuid.uuid4()),
                   "agent": "claude", "target": "101", "home": None, "nativeContext": None,
                   "generation": None, "anchor": None, "remainingCutoffMs": None, "remainingTotalMs": None}
        def invoke(request):
            argv = ["send", "--_handoff-native-context=" + base64.b64encode(peer.HandoffLedger.encode(request)).decode(),
                    "--to=101", "--b64=" + base64.b64encode(b"fixture").decode(),
                    "--no-from", "--no-reply-to", "--no-update-notice", "--json"]
            if request["phase"] == "probe":
                argv += ["--_handoff-native-cutoff-ms=2000", "--_handoff-native-total-ms=7000"]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = peer.main(argv)
            return code, json.loads(output.getvalue())
        connection = mock.Mock()
        def replace(_):
            directory.rename(directory.parent / "old-sessions")
            directory.mkdir()
        connection.connect.side_effect = replace
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(directory.parent)}), \
                mock.patch.object(peer, "handoff_now_ns", side_effect=peer.time.monotonic_ns), \
                mock.patch.object(peer, "handoff_boot_clock", return_value="a" * 64):
            code, response = invoke(context)
            self.assertEqual(code, 0)
            peer.handoff_validate_remote_response(response, context)
            proof = response["handoffNative"]
            context.update(phase="effect", generation=proof["generation"], nativeContext=proof["nativeContext"],
                           anchor=proof["anchor"], remainingCutoffMs=2000, remainingTotalMs=7000)
            with mock.patch.object(peer.socket, "socket", return_value=connection):
                code, response = invoke(context)
            native = peer.handoff_validate_remote_response(response, context)
        self.assertEqual(code, 1)
        self.assertEqual(native["reason"], "native_submission_refused")
        self.assertFalse(native["retryAllowed"])
        connection.connect.assert_called_once()
        connection.sendall.assert_not_called()

    def test_selected_refusal_is_a_valid_pinned_ssh_response(self):
        refusal = peer.generation_refused("target_generation_unavailable", "fixture")
        response = {"schemaVersion": 1, "command": "send", "ok": False, "error": str(refusal), **refusal.details}
        token = "tg1:" + "a" * 64
        result = peer.parse_ssh_response(json.dumps(response),
            ["send", "--to=101", "--target-generation=" + token])
        self.assertTrue(result[3])
        self.assertNotIn("lastSeenTarget", response)

    @unittest.skipIf(os.name == "nt", "POSIX socket snapshot")
    def test_endpoint_disappearance_does_not_invalidate_other_inventory_rows(self):
        value = self.record(self.default, 101)
        original = Path.is_socket
        def disappear(path):
            if str(path) == value["messagingSocketPath"]:
                path.unlink()
                return True  # It existed at the preceding presence checkpoint.
            return original(path)
        with mock.patch.object(Path, "is_socket", disappear):
            rows = peer.discover(True)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["reachable"])
        self.assertEqual(rows.errors, [])

    def test_distinct_same_registry_records_are_conflicting_even_if_identical(self):
        value = self.record(self.default, 101)
        (self.default / "00101.json").write_text(json.dumps(value), encoding="utf-8")
        rows = peer.discover(True)
        self.assertEqual(len(rows), 2)
        self.assertIn("conflicting_session_records", rows.errors)
        self.assertTrue(all(not row["reachable"] for row in rows))

    def test_unrelated_healthy_target_is_not_selected_amid_live_conflicts(self):
        self.record(self.default, 100, "healthy")
        value = self.record(self.profile("one"), 101)
        two = self.profile("two")
        (two / "101.json").write_text(json.dumps(value), encoding="utf-8")
        rows = peer.discover(True)
        self.assertTrue(next(row for row in rows if row["pid"] == 100)["reachable"])
        with self.assertRaises(peer.CcPeerError):
            peer.resolve_target(rows, "100")
        with mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.default.parent)}):
            self.assertEqual(peer.resolve_target(peer.discover(), "100")["pid"], 100)

    @unittest.skipIf(os.name == "nt", "POSIX endpoint inode identity")
    def test_live_socket_alias_claims_conflict_in_both_inventory_orders(self):
        one, two = self.profile("one"), self.profile("two")
        original = self.record(one, 101, "physical")
        alias = self.root / "same-inbox-alias.sock"
        alias.symlink_to(original["messagingSocketPath"])
        self.record(two, 102, "alias", str(alias))
        for directories in ([one, two], [two, one]):
            with self.subTest(reversed=directories[0] == two), \
                    mock.patch.object(peer, "claude_registry_directories", return_value=(directories, [])):
                rows = peer.discover(True)
                self.assertEqual(len(rows), 2)
                self.assertIn("conflicting_session_records", rows.errors)
                self.assertTrue(all(not row["reachable"] for row in rows))
                for target in ("101", "102", "physical", "alias"):
                    with self.assertRaises(peer.CcPeerError):
                        peer.resolve_target(rows, target)
