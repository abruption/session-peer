"""Offline private address storage; selected evidence is supplied by fixtures."""
import concurrent.futures
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

import session_peer as peer


def selected(label="Worker", agent="claude", transport="local"):
    route = {"transport": transport, "agent": agent}
    if transport == "ssh":
        route["host"] = "fixture-host"
    if agent == "codex":
        route["codexHome"] = "/fixture/home"
    recipient = {"agent": agent, "target": "claude:42" if agent == "claude" else
                 "codex:00000000-0000-4000-8000-000000000001",
                 "home": None if agent == "claude" else "/fixture/home"}
    selection = {"generationStatus": "available" if agent == "claude" else "unsupported",
                 "targetGeneration": "tg1:" + "a" * 64 if agent == "claude" else None,
                 "writerRevision": "aw1:" + "b" * 64 if agent == "codex" else None,
                 "observationRevision": None}
    key = "SHA256:" + "A" * 43 if transport == "ssh" else None
    revision = peer.preset_revision("fixture", route)
    selection["observationRevision"] = peer.address_selection_revision(
        "fixture", revision, route, recipient, selection, key)
    return {"label": label, "preset": "fixture", "presetRevision": revision,
            "route": route, "recipient": recipient, "selection": selection, "sshHostKey": key}


class AddressValidationTests(unittest.TestCase):
    def entry(self, **kwargs):
        return {"bindingId": str(uuid.uuid4()), **selected(**kwargs)}

    def refuse(self, function, *args, **kwargs):
        with self.assertRaises(peer.CcPeerError) as caught:
            function(*args, **kwargs)
        self.assertTrue(caught.exception.details["reason"].startswith("address_"))

    def test_all_local_ssh_claude_codex_combinations(self):
        for agent in ("claude", "codex"):
            for transport in ("local", "ssh"):
                entry = self.entry(agent=agent, transport=transport)
                self.assertEqual(peer.address_validate_entry(entry), entry)

    def test_closed_entry_and_binding_uuid4_contract(self):
        entry = self.entry()
        for change in ({"secret": "forbidden"}, {"bindingId": None}, {"bindingId": str(uuid.uuid1())},
                       {"bindingId": entry["bindingId"].upper()}, {"bindingId": []}, {"presetRevision": "dp1:" + "f" * 64}):
            self.refuse(peer.address_validate_entry, {**entry, **change})
        self.refuse(peer.address_validate_entry, {k: v for k, v in entry.items() if k != "label"})

    def test_labels_nfc_unicode_control_bidi_and_zero_width(self):
        entry = self.entry(label="한글 日本語 Café")
        self.assertEqual(peer.address_validate_entry(entry), entry)
        for label in ("", "   ", "x" * 129, "Cafe\u0301", "a\n", "a\x85", "a\u202e", "a\u200b", "a\u2066", "a\ud800",
                      "a\u034f", "a\u2028", "a\ufe0f", "a\u3164"):
            self.refuse(peer.address_validate_entry, {**entry, "label": label})

    def test_recipient_selection_and_route_cannot_be_mixed_or_injected(self):
        for agent in ("claude", "codex"):
            entry = self.entry(agent=agent)
            for field, updates in (("recipient", {"target": "codex:ALIAS"}),
                                   ("recipient", {"agent": "antigravity"}),
                                   ("recipient", {"home": "/x/../home"}),
                                   ("recipient", {"command": "injected"}),
                                   ("selection", {"targetGeneration": "tg1:bad"}),
                                   ("selection", {"writerRevision": "aw1:bad"}),
                                   ("selection", {"observationRevision": "as1:" + "0" * 64}),
                                   ("selection", {"timestamp": 1})):
                modified = copy.deepcopy(entry)
                modified[field].update(updates)
                self.refuse(peer.address_validate_entry, modified)
            for key in ("SHA256:" + "A" * 43, [], "private_key"):
                self.refuse(peer.address_validate_entry, {**entry, "sshHostKey": key})
        ssh = self.entry(transport="ssh")
        for key in (None, "SHA256:" + "A" * 42, "SHA256:" + "A" * 42 + "B", "SHA256:" + "A" * 43 + "=", "MD5:forbidden"):
            self.refuse(peer.address_validate_entry, {**ssh, "sshHostKey": key})

    def test_selection_revision_excludes_only_itself(self):
        entry = self.entry(transport="ssh")
        def revision(value):
            return peer.address_selection_revision(value["preset"], value["presetRevision"], value["route"],
                                                   value["recipient"], value["selection"], value["sshHostKey"])
        expected = revision(entry)
        self.assertRegex(expected, r"^as1:[0-9a-f]{64}$")
        other = copy.deepcopy(entry)
        other["selection"]["observationRevision"] = "arbitrary-self-field"
        other["label"] = "Changed"
        other["bindingId"] = str(uuid.uuid4())
        self.assertEqual(revision(other), expected)
        other["recipient"]["target"] = "claude:43"
        self.assertNotEqual(revision(other), expected)
        other = copy.deepcopy(entry)
        other["selection"]["targetGeneration"] = "tg1:" + "c" * 64
        self.assertNotEqual(revision(other), expected)
        other = copy.deepcopy(entry)
        other["sshHostKey"] = "SHA256:" + "B" * 42 + "A"
        self.assertNotEqual(revision(other), expected)

    def test_binding_revision_covers_name_label_and_fresh_binding(self):
        entry = self.entry()
        token = peer.address_revision("worker", entry)
        self.assertRegex(token, r"^ab1:[0-9a-f]{64}$")
        self.assertEqual(token, peer.address_revision("worker", dict(reversed(list(entry.items())))))
        self.assertNotEqual(token, peer.address_revision("other", entry))
        self.assertNotEqual(token, peer.address_revision("worker", {**entry, "label": "Other"}))
        self.assertNotEqual(token, peer.address_revision("worker", {**entry, "bindingId": str(uuid.uuid4())}))


@unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "POSIX private storage")
class AddressStorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codex-addresses-", dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)}).start()
        self.app = self.root / "session-peer"
        self.file = self.app / "addresses.json"
        # These are explicit unit metadata fixtures, not a production exception
        # for owner-ignored volumes. The refusal path is tested separately.
        mock.patch.object(peer, "_preset_check_ownership").start()
        real_fstat = os.fstat
        # The task's required external-volume root is group writable. Model
        # only those pre-existing ancestors as private metadata for unit I/O.
        modeled = {(p.stat().st_dev, p.stat().st_ino) for p in self.root.parents
                   if p.stat().st_uid == os.geteuid() and p.stat().st_mode & 0o022}
        def metadata(fd):
            info = real_fstat(fd)
            if (info.st_dev, info.st_ino) in modeled:
                fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
                fields["st_mode"] &= ~0o022
                return SimpleNamespace(**fields)
            return info
        mock.patch.object(peer.os, "fstat", side_effect=metadata).start()
        self.entry = selected()

    def refuse(self, reason, function, *args, **kwargs):
        with self.assertRaises(peer.CcPeerError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.details["reason"], reason)
        self.assertNotIn(str(self.root), str(caught.exception))

    def write_raw(self, raw):
        self.app.mkdir(mode=0o700, exist_ok=True)
        self.file.write_bytes(raw)
        self.file.chmod(0o600)

    def test_absent_is_empty_without_creating_directory_or_lock(self):
        self.assertEqual(peer.address_read(), {})
        self.refuse("address_not_found", peer.address_lookup, "worker")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_add_lookup_and_fresh_reselect_prevent_aba(self):
        original = copy.deepcopy(self.entry)
        first = peer.address_mutate("add", "worker", self.entry)
        self.assertEqual(self.entry, original)
        self.assertEqual(peer.address_lookup("worker"), (first["entry"], first["revision"]))
        lock = self.app / "addresses.lock"
        inode = lock.stat().st_ino
        for path, mode in ((self.app, 0o700), (self.file, 0o600), (lock, 0o600)):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
        second = peer.address_mutate("reselect", "worker", self.entry, first["revision"])
        self.assertNotEqual(first["entry"]["bindingId"], second["entry"]["bindingId"])
        self.assertNotEqual(first["revision"], second["revision"])
        self.assertEqual(lock.stat().st_ino, inode)
        self.refuse("address_revision_mismatch", peer.address_mutate, "remove", "worker", None, first["revision"])
        removed = peer.address_mutate("remove", "worker", expected_revision=second["revision"])
        self.assertTrue(removed["removed"])
        self.assertEqual(peer.address_read(), {})
        self.assertFalse((self.app / "destinations.json").exists())
        self.assertFalse((self.app / "destinations.lock").exists())

    def test_no_overwrite_cas_and_binding_id_injection(self):
        first = peer.address_mutate("add", "worker", self.entry)
        before = self.file.read_bytes()
        self.refuse("address_already_exists", peer.address_mutate, "add", "worker", self.entry)
        for action in ("reselect", "remove"):
            entry = self.entry if action == "reselect" else None
            self.refuse("address_revision_required", peer.address_mutate, action, "worker", entry)
        self.refuse("address_invalid_entry", peer.address_mutate, "add", "other", first["entry"])
        self.assertEqual(self.file.read_bytes(), before)

    def test_duplicate_labels_and_bad_names_refused(self):
        peer.address_mutate("add", "worker", self.entry)
        self.refuse("address_duplicate_label", peer.address_mutate, "add", "other", self.entry)
        for name in ("UPPER", "a/b", "日本語", "a" * 65):
            self.refuse("address_invalid_name", peer.address_mutate, "add", name, selected("Different"))
        self.assertEqual(set(peer.address_read()), {"worker"})

    def test_corrupt_future_duplicate_keys_and_version_types_never_repaired(self):
        bad = [b"", b"\xff", b"{} trailing", b'{"schemaVersion":1,"schemaVersion":1,"addresses":{}}',
               b'{"schemaVersion":1,"addresses":{"x":{},"\\u0078":{}}}',
               b'{"schemaVersion":NaN,"addresses":{}}']
        for version in (True, 1.0, 2, None):
            bad.append(json.dumps({"schemaVersion": version, "addresses": {}}).encode())
        for raw in bad:
            self.write_raw(raw)
            self.refuse("address_corrupt", peer.address_read)
            self.refuse("address_corrupt", peer.address_mutate, "add", "worker", self.entry)
            self.assertEqual(self.file.read_bytes(), raw)

    def test_preset_bytes_and_dp1_unchanged_by_address_mutation(self):
        preset = peer.preset_mutate("add", "fixture", self.entry["route"])
        file = self.app / "destinations.json"
        before = (file.read_bytes(), file.stat().st_ino, file.stat().st_mtime_ns)
        peer.address_mutate("add", "worker", self.entry)
        self.assertEqual(peer.preset_lookup("fixture"), (self.entry["route"], preset["revision"]))
        self.assertEqual((file.read_bytes(), file.stat().st_ino, file.stat().st_mtime_ns), before)

    def test_symlink_hardlink_and_unsafe_modes_preserved(self):
        peer.address_mutate("add", "worker", self.entry)
        original = self.file.read_bytes()
        outside = self.root / "preserved"
        self.file.rename(outside)
        self.file.symlink_to(outside)
        self.refuse("address_unsafe_storage", peer.address_read)
        self.refuse("address_unsafe_storage", peer.address_mutate, "add", "other", selected("Other"))
        self.assertEqual(outside.read_bytes(), original)
        self.file.unlink()
        os.link(outside, self.file)
        self.refuse("address_unsafe_storage", peer.address_read)
        self.file.unlink()
        outside.rename(self.file)
        self.file.chmod(0o640)
        self.refuse("address_unsafe_storage", peer.address_read)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o640)

    def test_owner_ignored_mount_and_acl_fail_closed(self):
        with mock.patch.object(peer, "_preset_check_ownership", side_effect=peer._preset_error("preset_ownership_unenforced")):
            self.refuse("address_ownership_unenforced", peer.address_read)
            self.refuse("address_ownership_unenforced", peer.address_mutate, "add", "worker", self.entry)
        with mock.patch.object(peer, "_preset_check_acl", side_effect=peer._preset_error("preset_unsafe_acl")):
            self.refuse("address_unsafe_acl", peer.address_read)
        self.assertFalse(self.app.exists())

    def test_atomic_replace_failure_and_postcommit_classification(self):
        peer.address_mutate("add", "worker", self.entry)
        before = self.file.read_bytes()
        with mock.patch.object(peer.os, "replace", side_effect=OSError("private diagnostic")):
            self.refuse("address_unsafe_storage", peer.address_mutate, "add", "other", selected("Other"))
        self.assertEqual(self.file.read_bytes(), before)
        real_fsync = os.fsync
        def fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("private diagnostic")
            return real_fsync(fd)
        with mock.patch.object(peer.os, "fsync", side_effect=fsync):
            self.refuse("address_commit_unconfirmed", peer.address_mutate, "add", "other", selected("Other"))
        self.assertEqual(set(peer.address_read()), {"worker", "other"})
        self.assertEqual(sorted(p.name for p in self.app.iterdir()), ["addresses.json", "addresses.lock"])

    def test_capacity_and_concurrent_adds_and_single_winner_cas(self):
        self.write_raw(b" " * (peer.ADDRESS_MAX_BYTES + 1))
        self.refuse("address_capacity", peer.address_read)
        self.file.unlink()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda n: peer.address_mutate("add", "entry" + str(n), selected("Worker " + str(n))), range(8)))
        revision = results[0]["revision"]
        def reselect(label):
            try:
                peer.address_mutate("reselect", "entry0", selected(label), revision)
                return "success"
            except peer.CcPeerError as error:
                return error.details["reason"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reselect, ("First", "Second")))
        self.assertEqual(sorted(outcomes), ["address_revision_mismatch", "success"])
        self.assertEqual(len(peer.address_read()), 8)

    def test_inherited_entry_limit_and_duplicate_stored_labels(self):
        entry = {"bindingId": str(uuid.uuid4()), **self.entry}
        entries = {"entry" + str(n): {**entry, "label": "Worker " + str(n)} for n in range(129)}
        self.refuse("address_capacity", peer._address_decode,
                    json.dumps({"schemaVersion": 1, "addresses": entries}).encode())
        entries = {"first": entry, "second": {**entry, "bindingId": str(uuid.uuid4())}}
        self.refuse("address_duplicate_label", peer._address_decode,
                    json.dumps({"schemaVersion": 1, "addresses": entries}).encode())

    def test_lock_deadline_and_unsafe_lock_preserve_store(self):
        peer.address_mutate("add", "worker", self.entry)
        lock = self.app / "addresses.lock"
        before = self.file.read_bytes()
        fd = os.open(lock, os.O_RDWR)
        try:
            peer.fcntl.flock(fd, peer.fcntl.LOCK_EX | peer.fcntl.LOCK_NB)
            with mock.patch.object(peer, "PRESET_LOCK_SECONDS", 0.01):
                self.refuse("address_busy", peer.address_mutate, "add", "other", selected("Other"))
        finally:
            os.close(fd)
        lock.chmod(0o640)
        self.refuse("address_unsafe_storage", peer.address_mutate, "add", "other", selected("Other"))
        self.assertEqual(self.file.read_bytes(), before)

    def test_original_file_identity_rechecked_before_commit(self):
        peer.address_mutate("add", "worker", self.entry)
        before = self.file.read_bytes()
        outside = self.root / "preserved"
        real_fsync = os.fsync
        swapped = False
        def fsync(fd):
            nonlocal swapped
            real_fsync(fd)
            if not swapped:
                swapped = True
                self.file.rename(outside)
                self.file.symlink_to(outside)
        with mock.patch.object(peer.os, "fsync", side_effect=fsync):
            self.refuse("address_unsafe_storage", peer.address_mutate, "add", "other", selected("Other"))
        self.assertTrue(self.file.is_symlink())
        self.assertEqual(outside.read_bytes(), before)
        self.assertFalse(any(p.name.startswith(".addresses-") for p in self.app.iterdir()))

    def test_directory_identity_rechecked_before_commit(self):
        peer.address_mutate("add", "worker", self.entry)
        before = self.file.read_bytes()
        original_directory = peer._preset_directory
        moved = self.root / "moved"
        calls = 0
        def directory(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.app.rename(moved)
                self.app.mkdir(mode=0o700)
            return original_directory(*args, **kwargs)
        with mock.patch.object(peer, "_preset_directory", side_effect=directory):
            self.refuse("address_storage_changed", peer.address_mutate, "add", "other", selected("Other"))
        self.assertEqual((moved / "addresses.json").read_bytes(), before)
        self.assertEqual(list(self.app.iterdir()), [])
