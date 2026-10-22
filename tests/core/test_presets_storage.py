"""Offline route-preset storage boundaries; no native agent or SSH execution."""
import concurrent.futures
import copy
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

import session_peer as peer


@unittest.skipIf(peer.IS_WINDOWS or peer.fcntl is None, "POSIX presets only")
class PresetStorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="codex-presets-", dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.root.chmod(0o700)
        self.addCleanup(mock.patch.stopall)
        mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)}).start()
        self.app = self.root / "session-peer"
        self.file = self.app / "destinations.json"
        self.route = {"transport": "ssh", "agent": "codex", "host": "user@fixture-host", "codexHome": "/fixture/home"}

    def write_raw(self, raw):
        self.app.mkdir(mode=0o700, exist_ok=True)
        self.file.write_bytes(raw)
        self.file.chmod(0o600)

    def write_store(self, value):
        self.write_raw(json.dumps(value).encode("utf-8"))

    def refuse(self, reason, function, *args, **kwargs):
        with self.assertRaises(peer.CcPeerError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.details.get("reason"), reason)
        self.assertNotIn(str(self.root), str(caught.exception))
        return caught.exception

    def test_missing_read_does_not_initialize_or_lock(self):
        self.assertEqual(peer.preset_read(), {})
        self.refuse("preset_not_found", peer.preset_lookup, "fixture")
        self.assertEqual(list(self.root.iterdir()), [])
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "absent") }):
            self.assertEqual(peer.preset_read(), {})
        self.assertEqual(list(self.root.iterdir()), [])

    def test_add_lookup_copies_and_private_storage(self):
        original = copy.deepcopy(self.route)
        result = peer.preset_mutate("add", "fixture", self.route)
        self.assertEqual(self.route, original)
        self.assertEqual(result["route"], original)
        route, revision = peer.preset_lookup("fixture")
        route["host"] = "changed"
        self.assertEqual(peer.preset_lookup("fixture"), (original, revision))
        self.assertEqual(revision, result["revision"])
        for path, mode in ((self.app, 0o700), (self.file, 0o600), (self.app / "destinations.lock", 0o600)):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)

    def test_revision_canonical_order_and_exact_route_values(self):
        revision = peer.preset_revision("fixture", self.route)
        self.assertEqual(revision, peer.preset_revision("fixture", dict(reversed(list(self.route.items())))))
        self.assertRegex(revision, r"^dp1:[0-9a-f]{64}$")
        for field, value in (("host", "other-host"), ("codexHome", "/fixture/home/")):
            changed = dict(self.route, **{field: value})
            self.assertNotEqual(revision, peer.preset_revision("fixture", changed))
        self.assertNotEqual(revision, peer.preset_revision("other", self.route))

    def test_replace_remove_require_matching_revision(self):
        before = peer.preset_mutate("add", "fixture", self.route)
        raw = self.file.read_bytes()
        for action in ("replace", "remove"):
            entry = self.route if action == "replace" else None
            self.refuse("preset_revision_required", peer.preset_mutate, action, "fixture", entry)
            self.refuse("preset_revision_mismatch", peer.preset_mutate, action, "fixture", entry, "dp1:" + "0" * 64)
            self.assertEqual(self.file.read_bytes(), raw)
        changed = dict(self.route, host="other-host")
        after = peer.preset_mutate("replace", "fixture", changed, before["revision"])
        self.refuse("preset_revision_mismatch", peer.preset_mutate, "remove", "fixture", None, before["revision"])
        removed = peer.preset_mutate("remove", "fixture", None, after["revision"])
        self.assertTrue(removed["removed"])
        self.assertEqual(removed["route"], changed)
        self.assertEqual(peer.preset_read(), {})

    def test_duplicate_add_does_not_replace(self):
        peer.preset_mutate("add", "fixture", self.route)
        raw = self.file.read_bytes()
        self.refuse("preset_already_exists", peer.preset_mutate, "add", "fixture", dict(self.route, host="other"))
        self.assertEqual(self.file.read_bytes(), raw)

    def test_names_routes_and_unrecognized_fields_rejected_before_io(self):
        for name in ("", "A", "a/b", "a " , "1fixture", "a" * 65, "日本語"):
            self.refuse("preset_invalid_name", peer.preset_mutate, "add", name, self.route)
        bad = [None, {}, dict(self.route, target="id"), dict(self.route, generation="tg1:x"),
               dict(self.route, bin="arbitrary"), dict(self.route, sshOptions=[]),
               dict(self.route, host="a@@b"), dict(self.route, host="@host"),
               dict(self.route, host="user:password@host"), dict(self.route, host="-oProxyCommand=x"),
               dict(self.route, host="host;command"), dict(self.route, host="a\n"),
               dict(self.route, host="a\x85"), dict(self.route, host="x" * 1025),
               dict(self.route, codexHome="relative"), dict(self.route, codexHome="//host/path"),
               dict(self.route, codexHome="C:\\home"), dict(self.route, codexHome="/x\x7f"),
               dict(self.route, codexHome="/" + "x" * 4096),
               dict(self.route, codexHome="/\ud800"), dict(self.route, agent="antigravity"),
               {"transport": "local", "agent": "claude", "host": "host"},
               {"transport": "local", "agent": "claude", "codexHome": "/x"}]
        for route in bad:
            self.refuse("preset_invalid_route", peer.preset_mutate, "add", "fixture", route)
        self.assertFalse(self.app.exists())

    def test_local_claude_and_codex_allowlists(self):
        for name, route in (("claude", {"transport": "local", "agent": "claude"}),
                            ("codex", {"transport": "local", "agent": "codex", "codexHome": "/fixture"})):
            peer.preset_mutate("add", name, route)
            self.assertEqual(peer.preset_lookup(name)[0], route)

    def test_corrupt_json_schema_utf8_and_duplicate_keys_fail_closed(self):
        valid = {"schemaVersion": 1, "presets": {"fixture": self.route}}
        corrupt = [b"", b"\xff", b"{}{}", b"{} trailing", b"\xef\xbb\xbf{}", b"{",
                   b'{"schemaVersion":1,"schemaVersion":1,"presets":{}}',
                   b'{"schemaVersion":1,"presets":{"x":{},"\\u0078":{}}}',
                   b'{"schemaVersion":NaN,"presets":{}}',
                   json.dumps(dict(valid, schemaVersion=True)).encode(),
                   json.dumps(dict(valid, schemaVersion=1.0)).encode(),
                   json.dumps(dict(valid, unexpected="field")).encode(),
                   json.dumps(dict(valid, presets=[])).encode()]
        for raw in corrupt:
            self.write_raw(raw)
            self.refuse("preset_corrupt", peer.preset_read)
            self.refuse("preset_corrupt", peer.preset_mutate, "add", "other", self.route)
            self.assertEqual(self.file.read_bytes(), raw)

    def test_capacity_bytes_entries_and_failed_write_preservation(self):
        self.write_raw(b" " * (peer.PRESET_MAX_BYTES + 1))
        self.refuse("preset_capacity", peer.preset_read)
        routes = {"a" + str(index): {"transport": "local", "agent": "claude"} for index in range(128)}
        self.write_store({"schemaVersion": 1, "presets": routes})
        self.assertEqual(len(peer.preset_read()), 128)
        before = self.file.read_bytes()
        self.refuse("preset_capacity", peer.preset_mutate, "add", "overflow", self.route)
        self.assertEqual(self.file.read_bytes(), before)
        routes["overflow"] = self.route
        self.write_store({"schemaVersion": 1, "presets": routes})
        self.refuse("preset_capacity", peer.preset_read)

    def test_unsafe_directory_file_mode_and_uid_not_repaired(self):
        peer.preset_mutate("add", "fixture", self.route)
        for path, mode in ((self.app, 0o750), (self.file, 0o640), (self.file, 0o700)):
            old = stat.S_IMODE(path.stat().st_mode)
            path.chmod(mode)
            self.refuse("preset_unsafe_storage", peer.preset_read)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)
            path.chmod(old)
        with mock.patch.object(peer.os, "geteuid", return_value=os.geteuid() + 1):
            self.refuse("preset_unsafe_storage", peer.preset_read)
        self.assertTrue(self.file.exists())

    def test_symlink_file_directory_parent_and_hardlink_not_followed(self):
        peer.preset_mutate("add", "fixture", self.route)
        original = self.file.read_bytes()
        outside = self.root / "outside.json"
        self.file.rename(outside)
        self.file.symlink_to(outside)
        self.refuse("preset_unsafe_storage", peer.preset_read)
        self.refuse("preset_unsafe_storage", peer.preset_mutate, "add", "other", self.route)
        self.assertTrue(self.file.is_symlink())
        self.assertEqual(outside.read_bytes(), original)
        self.file.unlink()
        os.link(outside, self.file)
        self.refuse("preset_unsafe_storage", peer.preset_read)
        self.file.unlink()
        outside.rename(self.file)
        moved = self.root / "moved"
        self.app.rename(moved)
        self.app.symlink_to(moved, target_is_directory=True)
        self.refuse("preset_unsafe_storage", peer.preset_read)
        self.assertTrue(self.app.is_symlink())
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.app)}):
            self.refuse("preset_unsafe_storage", peer.preset_read)

    def test_fifo_not_blocked_and_read_does_not_create_lock(self):
        self.app.mkdir(mode=0o700)
        os.mkfifo(self.file, 0o600)
        self.refuse("preset_unsafe_storage", peer.preset_read)
        self.assertTrue(stat.S_ISFIFO(self.file.lstat().st_mode))
        self.assertFalse((self.app / "destinations.lock").exists())

    def test_unsafe_lock_is_preserved(self):
        peer.preset_mutate("add", "fixture", self.route)
        before = self.file.read_bytes()
        lock = self.app / "destinations.lock"
        lock.chmod(0o660)
        self.refuse("preset_unsafe_storage", peer.preset_mutate, "add", "other", self.route)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o660)

    def test_lock_wait_is_bounded_and_does_not_write(self):
        peer.preset_mutate("add", "fixture", self.route)
        fd = os.open(self.app / "destinations.lock", os.O_RDWR)
        self.addCleanup(os.close, fd)
        peer.fcntl.flock(fd, peer.fcntl.LOCK_EX | peer.fcntl.LOCK_NB)
        before = self.file.read_bytes()
        with mock.patch.object(peer, "PRESET_LOCK_SECONDS", 0.02):
            self.refuse("preset_busy", peer.preset_mutate, "add", "other", self.route)
        self.assertEqual(self.file.read_bytes(), before)

    def test_concurrent_writers_preserve_independent_adds_and_cas(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda n: peer.preset_mutate("add", "entry" + str(n), self.route), range(12)))
        self.assertEqual(len(peer.preset_read()), 12)
        revision = results[0]["revision"]
        def replace(host):
            try:
                peer.preset_mutate("replace", "entry0", dict(self.route, host=host), revision)
                return "success"
            except peer.CcPeerError as error:
                return error.details.get("reason")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(replace, ("first", "second")))
        self.assertEqual(sorted(outcomes), ["preset_revision_mismatch", "success"])
        self.assertEqual(len(peer.preset_read()), 12)

    def test_atomic_replace_failure_preserves_previous_store_and_removes_own_temp(self):
        peer.preset_mutate("add", "fixture", self.route)
        before = self.file.read_bytes()
        with mock.patch.object(peer.os, "replace", side_effect=OSError("private diagnostic")):
            error = self.refuse("preset_unsafe_storage", peer.preset_mutate, "add", "other", self.route)
        self.assertNotIn("private diagnostic", str(error))
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.app.iterdir()), ["destinations.json", "destinations.lock"])

    def test_atomic_write_rechecks_destination_and_preserves_replacement(self):
        peer.preset_mutate("add", "fixture", self.route)
        outside = self.root / "preserved.json"
        before = self.file.read_bytes()
        real_fsync = os.fsync
        def replace_during_flush(fd):
            real_fsync(fd)
            self.file.rename(outside)
            self.file.symlink_to(outside)
        with mock.patch.object(peer.os, "fsync", side_effect=replace_during_flush):
            self.refuse("preset_unsafe_storage", peer.preset_mutate, "add", "other", self.route)
        self.assertTrue(self.file.is_symlink())
        self.assertEqual(outside.read_bytes(), before)
        self.assertFalse(any(path.name.startswith(".destinations-") for path in self.app.iterdir()))

    def test_encoded_write_budget_is_enforced_under_entry_quota(self):
        large = dict(self.route, codexHome="/" + "字" * 4000)
        peer.preset_mutate("add", "first", large)
        peer.preset_mutate("add", "second", large)
        before = self.file.read_bytes()
        self.refuse("preset_capacity", peer.preset_mutate, "add", "third", large)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(len(peer.preset_read()), 2)

    def test_unsafe_ancestor_and_symlink_lock_do_not_get_repaired(self):
        peer.preset_mutate("add", "fixture", self.route)
        before = self.file.read_bytes()
        self.root.chmod(0o770)
        try:
            self.refuse("preset_unsafe_storage", peer.preset_read)
            self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o770)
        finally:
            self.root.chmod(0o700)
        lock = self.app / "destinations.lock"
        outside = self.root / "preserved.lock"
        lock.rename(outside)
        lock.symlink_to(outside)
        self.refuse("preset_unsafe_storage", peer.preset_mutate, "add", "other", self.route)
        self.assertTrue(lock.is_symlink())
        self.assertEqual(self.file.read_bytes(), before)

    def test_default_home_location_and_read_only_access_have_no_side_effects(self):
        with mock.patch.dict(os.environ), mock.patch.object(peer.Path, "home", return_value=self.root):
            os.environ.pop("XDG_CONFIG_HOME", None)
            self.assertEqual(peer.preset_read(), {})
            self.assertFalse((self.root / ".config").exists())
            peer.preset_mutate("add", "fixture", self.route)
            location = self.root / ".config" / "session-peer"
            lock = location / "destinations.lock"
            lock.unlink()
            self.assertEqual(peer.preset_lookup("fixture")[0], self.route)
            self.assertFalse(lock.exists())

    def test_relative_config_root_and_windows_rejected_before_io(self):
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative"}):
            self.refuse("preset_invalid_config_root", peer.preset_read)
        with mock.patch.object(peer, "IS_WINDOWS", True), mock.patch.object(peer.os, "open") as opening:
            self.refuse("preset_platform_unsupported", peer.preset_read)
            self.refuse("preset_platform_unsupported", peer.preset_mutate, "add", "fixture", self.route)
            opening.assert_not_called()
        self.assertFalse(self.app.exists())

    def test_config_root_controls_surrogates_and_size_rejected_before_io(self):
        invalid = ("/fixture/\x00", "/fixture/\n", "/fixture/\x7f", "/fixture/\x85",
                   "/fixture/\ud800", "/" + "a" * 4096, "")
        for value in invalid:
            # os.environ itself rejects NUL, so provide the invalid configuration
            # through its read interface without mutating the actual environment.
            real_get = os.environ.get
            def configured(name, default=None):
                return value if name == "XDG_CONFIG_HOME" else real_get(name, default)
            with mock.patch.object(peer.os.environ, "get", side_effect=configured), mock.patch.object(peer.os, "open") as opening:
                self.refuse("preset_invalid_config_root", peer.preset_read)
                self.refuse("preset_invalid_config_root", peer.preset_mutate, "add", "fixture", self.route)
                opening.assert_not_called()
