"""Offline route-preset storage boundaries; no native agent or SSH execution."""
import concurrent.futures
import copy
import ctypes
import errno
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
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

    def test_directory_fsync_failure_reports_commit_unconfirmed_without_rollback(self):
        peer.preset_mutate("add", "fixture", self.route)
        real_fsync = os.fsync
        def fail_directory_fsync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("private diagnostic")
            return real_fsync(fd)
        with mock.patch.object(peer.os, "fsync", side_effect=fail_directory_fsync):
            error = self.refuse("preset_commit_unconfirmed", peer.preset_mutate, "add", "other", self.route)
        self.assertIn("inspect configuration before retrying", str(error))
        self.assertNotIn("private diagnostic", str(error))
        self.assertEqual(set(peer.preset_read()), {"fixture", "other"})
        self.assertFalse(any(path.name.startswith(".destinations-") for path in self.app.iterdir()))

    def test_interrupt_immediately_after_rename_is_not_masked_by_cleanup(self):
        peer.preset_mutate("add", "fixture", self.route)
        real_replace = os.replace
        def replace_then_interrupt(*args, **kwargs):
            real_replace(*args, **kwargs)
            raise KeyboardInterrupt()
        with mock.patch.object(peer.os, "replace", side_effect=replace_then_interrupt):
            with self.assertRaises(KeyboardInterrupt):
                peer.preset_mutate("add", "other", self.route)
        self.assertEqual(set(peer.preset_read()), {"fixture", "other"})
        self.assertFalse(any(path.name.startswith(".destinations-") for path in self.app.iterdir()))

    def test_interrupt_is_not_masked_by_temporary_unlink_io_failure(self):
        peer.preset_mutate("add", "fixture", self.route)
        before = self.file.read_bytes()
        with mock.patch.object(peer.os, "replace", side_effect=KeyboardInterrupt()), mock.patch.object(peer.os, "unlink", side_effect=OSError(errno.EIO, "private cleanup diagnostic")):
            with self.assertRaises(KeyboardInterrupt):
                peer.preset_mutate("add", "other", self.route)
        self.assertEqual(self.file.read_bytes(), before)
        remaining = [path for path in self.app.iterdir() if path.name.startswith(".destinations-")]
        self.assertEqual(len(remaining), 1)
        remaining[0].unlink()  # Only the dedicated fixture's unlinked temp remains.

    def test_cleanup_reports_normal_errors_but_never_swallows_new_interrupts(self):
        def failed_cleanup():
            raise OSError(errno.EIO, "private cleanup diagnostic")
        error = self.refuse("preset_cleanup_failed", peer._preset_cleanup, failed_cleanup)
        self.assertNotIn("private cleanup diagnostic", str(error))
        def interrupted_cleanup():
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            try:
                raise peer._preset_error("original_failure")
            finally:
                peer._preset_cleanup(interrupted_cleanup)

    def test_handled_caller_exception_does_not_hide_normal_scope_or_acl_cleanup_failure(self):
        def failed_cleanup():
            raise OSError(errno.EIO, "private cleanup diagnostic")
        api = self.darwin_api(())
        api.acl_free.return_value = -1
        try:
            raise ValueError("already handled by caller")
        except ValueError:
            with self.assertRaises(peer.CcPeerError) as caught:
                with peer._preset_cleanup_scope(failed_cleanup):
                    pass
            self.assertEqual(caught.exception.details["reason"], "preset_cleanup_failed")
            with mock.patch.object(ctypes, "CDLL", return_value=api):
                self.refuse("preset_acl_unverifiable", peer._preset_darwin_acl_tags, 123)
        api.acl_free.assert_called_once_with(100)

    def test_handled_caller_exception_does_not_hide_successful_mutation_close_failure(self):
        peer.preset_mutate("add", "fixture", self.route)
        lock_identity = (self.app / "destinations.lock").stat()
        real_close = os.close
        def close_then_fail(fd):
            info = os.fstat(fd)
            real_close(fd)
            if (info.st_dev, info.st_ino) == (lock_identity.st_dev, lock_identity.st_ino):
                raise OSError(errno.EIO, "private close diagnostic")
        try:
            raise ValueError("already handled by caller")
        except ValueError:
            with mock.patch.object(peer.os, "close", side_effect=close_then_fail):
                self.refuse("preset_commit_unconfirmed", peer.preset_mutate, "add", "other", self.route)
        self.assertEqual(set(peer.preset_read()), {"fixture", "other"})

    def test_read_interrupt_is_not_masked_by_descriptor_close_error(self):
        peer.preset_mutate("add", "fixture", self.route)
        identity = self.file.stat()
        real_close = os.close
        def close_then_fail(fd):
            info = os.fstat(fd)
            real_close(fd)
            if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
                raise OSError(errno.EIO, "private close diagnostic")
        with mock.patch.object(peer.os, "read", side_effect=KeyboardInterrupt()), mock.patch.object(peer.os, "close", side_effect=close_then_fail):
            with self.assertRaises(KeyboardInterrupt):
                peer.preset_read()
        self.assertEqual(set(peer.preset_read()), {"fixture"})

    def test_foreign_owned_nonwritable_ancestor_is_rejected_before_creation(self):
        ancestor = self.root / "ancestor"
        ancestor.mkdir(mode=0o755)
        config = ancestor / "config"
        config.mkdir(mode=0o700)
        identity = ancestor.stat()
        real_fstat = os.fstat
        def foreign_owner(fd):
            info = real_fstat(fd)
            if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
                return SimpleNamespace(st_uid=os.geteuid() + 1, st_mode=info.st_mode)
            return info
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config)}), mock.patch.object(peer.os, "fstat", side_effect=foreign_owner):
            self.refuse("preset_unsafe_storage", peer.preset_read)
            self.refuse("preset_unsafe_storage", peer.preset_mutate, "add", "fixture", self.route)
        self.assertFalse((config / "session-peer").exists())

    def test_read_detects_file_swap_and_preserves_both_files(self):
        peer.preset_mutate("add", "fixture", self.route)
        before = self.file.read_bytes()
        replacement = self.app / "replacement.json"
        replacement.write_bytes(before)
        replacement.chmod(0o600)
        preserved = self.app / "preserved.json"
        real_read = os.read
        swapped = False
        def read_and_swap(fd, count):
            nonlocal swapped
            chunk = real_read(fd, count)
            if not swapped:
                swapped = True
                self.file.rename(preserved)
                replacement.rename(self.file)
            return chunk
        with mock.patch.object(peer.os, "read", side_effect=read_and_swap):
            self.refuse("preset_storage_changed", peer.preset_read)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(preserved.read_bytes(), before)

    def test_first_creation_concurrent_writers_do_not_lose_entries(self):
        self.assertFalse(self.app.exists())
        barrier = threading.Barrier(6)
        def create(index):
            barrier.wait(timeout=5)
            return peer.preset_mutate("add", "first" + str(index), self.route)
        # This test asserts update serialization, not the production lock's
        # one-second wait deadline (covered by test_lock_wait_is_bounded...).
        with mock.patch.object(peer, "PRESET_LOCK_SECONDS", 5.0), concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(create, range(6)))
        self.assertEqual(len(results), 6)
        self.assertEqual(set(peer.preset_read()), {"first" + str(index) for index in range(6)})

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

    def darwin_api(self, tags=()):
        api = SimpleNamespace(acl_get_fd_np=mock.Mock(return_value=100),
                              acl_valid=mock.Mock(return_value=0),
                              acl_free=mock.Mock(return_value=0))
        position = [0]
        def entry(acl, entry_id, output):
            if position[0] == len(tags):
                ctypes.set_errno(errno.EINVAL)
                return -1
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = 1000 + position[0]
            position[0] += 1
            return 0
        def tag(entry_pointer, output):
            ctypes.cast(output, ctypes.POINTER(ctypes.c_int))[0] = tags[entry_pointer.value - 1000]
            return 0
        api.acl_get_entry = mock.Mock(side_effect=entry)
        api.acl_get_tag_type = mock.Mock(side_effect=tag)
        return api

    def test_darwin_acl_empty_handle_absence_and_cleanup(self):
        for tags in ((), (1,), (2, 2)):
            api = self.darwin_api(tags)
            with mock.patch.object(ctypes, "CDLL", return_value=api):
                self.assertEqual(peer._preset_darwin_acl_tags(123), tags)
            api.acl_get_fd_np.assert_called_once_with(123, 0x100)
            api.acl_free.assert_called_once_with(100)
        api = self.darwin_api()
        def absent(*args):
            ctypes.set_errno(errno.ENOENT)
            return None
        api.acl_get_fd_np.side_effect = absent
        with mock.patch.object(ctypes, "CDLL", return_value=api):
            self.assertEqual(peer._preset_darwin_acl_tags(123), ())
        api.acl_free.assert_not_called()

    def test_darwin_acl_failures_unknown_tags_and_bounds_fail_closed(self):
        for getter_errno in (0, errno.EACCES, errno.EBADF, errno.EOPNOTSUPP):
            api = self.darwin_api()
            def rejected(*args):
                ctypes.set_errno(getter_errno)
                return None
            api.acl_get_fd_np.side_effect = rejected
            with mock.patch.object(ctypes, "CDLL", return_value=api):
                self.refuse("preset_acl_unverifiable", peer._preset_darwin_acl_tags, 123)
            api.acl_free.assert_not_called()
        for tags in ((3,), (2,) * 129):
            api = self.darwin_api(tags)
            with mock.patch.object(ctypes, "CDLL", return_value=api):
                self.refuse("preset_acl_unverifiable", peer._preset_darwin_acl_tags, 123)
            api.acl_free.assert_called_once_with(100)
        for operation in ("acl_valid", "acl_get_tag_type", "acl_free"):
            api = self.darwin_api((2,))
            getattr(api, operation).return_value = -1
            getattr(api, operation).side_effect = None
            with mock.patch.object(ctypes, "CDLL", return_value=api):
                self.refuse("preset_acl_unverifiable", peer._preset_darwin_acl_tags, 123)
            api.acl_free.assert_called_once_with(100)
        api = self.darwin_api((2,))
        def invalid_entry(*args):
            ctypes.set_errno(errno.EIO)
            return -1
        api.acl_get_entry.side_effect = invalid_entry
        with mock.patch.object(ctypes, "CDLL", return_value=api):
            self.refuse("preset_acl_unverifiable", peer._preset_darwin_acl_tags, 123)
        api.acl_free.assert_called_once_with(100)

    def test_darwin_acl_entry_interrupt_is_not_masked_by_free_failure(self):
        api = self.darwin_api((2,))
        api.acl_get_entry.side_effect = KeyboardInterrupt()
        api.acl_free.return_value = -1
        with mock.patch.object(ctypes, "CDLL", return_value=api):
            with self.assertRaises(KeyboardInterrupt):
                peer._preset_darwin_acl_tags(123)
        api.acl_free.assert_called_once_with(100)

    def test_darwin_acl_policy_all_private_entries_refused_ancestor_deny_only_allowed(self):
        with mock.patch.object(peer.sys, "platform", "darwin"):
            for tags in ((), (2,), (2, 2)):
                with mock.patch.object(peer, "_preset_darwin_acl_tags", return_value=tags):
                    peer._preset_check_acl(123, private=False, directory=True)
                    if tags:
                        self.refuse("preset_unsafe_acl", peer._preset_check_acl, 123, private=True)
                    else:
                        peer._preset_check_acl(123, private=True)
            for tags, reason in (((1,), "preset_unsafe_acl"), ((2, 1), "preset_unsafe_acl"),
                                 ((3,), "preset_acl_unverifiable")):
                with mock.patch.object(peer, "_preset_darwin_acl_tags", return_value=tags):
                    self.refuse(reason, peer._preset_check_acl, 123, private=False, directory=True)

    def test_linux_acl_access_default_and_unverifiable_policy(self):
        def absent(fd, attribute):
            raise OSError(errno.ENODATA, "private diagnostic")
        with mock.patch.object(peer.sys, "platform", "linux"), mock.patch.object(peer.os, "getxattr", side_effect=absent, create=True) as get:
            peer._preset_check_acl(123, private=True, directory=True)
            self.assertEqual([call.args[1] for call in get.call_args_list], ["system.posix_acl_access", "system.posix_acl_default"])
        for attribute in ("system.posix_acl_access", "system.posix_acl_default"):
            def present(fd, name):
                if name == attribute:
                    return b"opaque ACL bytes"
                raise OSError(errno.ENODATA, "private diagnostic")
            with mock.patch.object(peer.sys, "platform", "linux"), mock.patch.object(peer.os, "getxattr", side_effect=present, create=True):
                self.refuse("preset_unsafe_acl", peer._preset_check_acl, 123, private=True, directory=True)
        for code in (errno.EOPNOTSUPP, errno.EACCES, errno.EBADF):
            with mock.patch.object(peer.sys, "platform", "linux"), mock.patch.object(peer.os, "getxattr", side_effect=OSError(code, "private diagnostic"), create=True):
                error = self.refuse("preset_acl_unverifiable", peer._preset_check_acl, 123, private=True)
                self.assertNotIn("private diagnostic", str(error))

    def linux_acl_bytes(self, owner_permissions):
        # Linux UAPI POSIX_ACL_XATTR_VERSION=2 and five fixed-size entries.
        # The named-user entry has a zero mask, granting it no effective access.
        entries = ((1, owner_permissions, 0xffffffff), (2, 4, os.geteuid() + 1),
                   (4, 0, 0xffffffff), (16, 0, 0xffffffff), (32, 0, 0xffffffff))
        return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in entries)

    @unittest.skipUnless(sys.platform == "linux", "Linux POSIX ACL fixture only")
    def test_native_linux_temp_file_acl_presence_is_refused(self):
        path = self.root / "acl-fixture"
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        applied = False
        try:
            peer._preset_check_acl(fd, private=True)
            try:
                os.setxattr(fd, "system.posix_acl_access", self.linux_acl_bytes(6))
                applied = True
            except OSError as error:
                if error.errno == errno.EOPNOTSUPP:
                    self.skipTest("dedicated fixture filesystem does not support POSIX ACL setup")
                raise
            self.refuse("preset_unsafe_acl", peer._preset_check_acl, fd, private=True)
            self.assertEqual(stat.S_IMODE(os.fstat(fd).st_mode), 0o600)
            os.removexattr(fd, "system.posix_acl_access")
            applied = False
            peer._preset_check_acl(fd, private=True)
        finally:
            try:
                if applied:
                    os.removexattr(fd, "system.posix_acl_access")
            finally:
                os.close(fd)

    @unittest.skipUnless(sys.platform == "linux", "Linux POSIX default ACL fixture only")
    def test_native_linux_temp_directory_default_acl_presence_is_refused(self):
        path = self.root / "acl-directory"
        path.mkdir(mode=0o700)
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        applied = False
        try:
            peer._preset_check_acl(fd, private=True, directory=True)
            try:
                os.setxattr(fd, "system.posix_acl_default", self.linux_acl_bytes(7))
                applied = True
            except OSError as error:
                if error.errno == errno.EOPNOTSUPP:
                    self.skipTest("dedicated fixture filesystem does not support POSIX default ACL setup")
                raise
            self.refuse("preset_unsafe_acl", peer._preset_check_acl, fd, private=True, directory=True)
            self.assertEqual(stat.S_IMODE(os.fstat(fd).st_mode), 0o700)
            os.removexattr(fd, "system.posix_acl_default")
            applied = False
            peer._preset_check_acl(fd, private=True, directory=True)
        finally:
            try:
                if applied:
                    os.removexattr(fd, "system.posix_acl_default")
            finally:
                os.close(fd)

    def test_acl_checks_cover_held_app_file_lock_and_temp_descriptors(self):
        real_check = peer._preset_check_acl
        observations = []
        def observe(fd, *, private, directory=False):
            info = os.fstat(fd)
            observations.append((private, directory, info.st_ino, info.st_size))
            return real_check(fd, private=private, directory=directory)
        with mock.patch.object(peer, "_preset_check_acl", side_effect=observe):
            peer.preset_mutate("add", "fixture", self.route)
            peer.preset_read()
        app_inode = self.app.stat().st_ino
        lock_inode = (self.app / "destinations.lock").stat().st_ino
        file_inode = self.file.stat().st_ino
        self.assertTrue(any(private and directory and inode == app_inode for private, directory, inode, size in observations))
        self.assertTrue(any(private and not directory and inode == lock_inode for private, directory, inode, size in observations))
        file_sizes = [size for private, directory, inode, size in observations if private and not directory and inode == file_inode]
        self.assertIn(0, file_sizes)  # Newly created temporary file before payload.
        self.assertTrue(any(size > 0 for size in file_sizes))

    def test_acl_refusal_before_commit_preserves_previous_store(self):
        peer.preset_mutate("add", "fixture", self.route)
        before = self.file.read_bytes()
        real_check = peer._preset_check_acl
        lock_inode = (self.app / "destinations.lock").stat().st_ino
        file_inode = self.file.stat().st_ino
        def unsafe_temp(fd, *, private, directory=False):
            info = os.fstat(fd)
            if private and not directory and info.st_ino not in (lock_inode, file_inode):
                raise peer._preset_error("preset_unsafe_acl")
            return real_check(fd, private=private, directory=directory)
        with mock.patch.object(peer, "_preset_check_acl", side_effect=unsafe_temp):
            self.refuse("preset_unsafe_acl", peer.preset_mutate, "add", "other", self.route)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertFalse(any(path.name.startswith(".destinations-") for path in self.app.iterdir()))

    @unittest.skipUnless(sys.platform == "darwin", "Darwin ACL fixture only")
    def test_native_darwin_temp_file_acl_is_rejected_without_user_config_changes(self):
        path = self.root / "acl-fixture"
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        try:
            self.assertEqual(peer._preset_darwin_acl_tags(fd), ())
            result = subprocess.run(["/bin/chmod", "+a", "everyone allow read", str(path)], capture_output=True)
            self.assertEqual(result.returncode, 0, "dedicated temporary ACL setup failed")
            try:
                self.assertEqual(peer._preset_darwin_acl_tags(fd), (1,))
                self.refuse("preset_unsafe_acl", peer._preset_check_acl, fd, private=True)
            finally:
                cleared = subprocess.run(["/bin/chmod", "-N", str(path)], capture_output=True)
                self.assertEqual(cleared.returncode, 0, "dedicated temporary ACL cleanup failed")
        finally:
            os.close(fd)

    def test_unreviewed_posix_platform_is_rejected_before_io(self):
        with mock.patch.object(peer.sys, "platform", "freebsd14"), mock.patch.object(peer.os, "open") as opening:
            self.refuse("preset_platform_unsupported", peer.preset_read)
            self.refuse("preset_platform_unsupported", peer.preset_mutate, "add", "fixture", self.route)
            opening.assert_not_called()

    def test_darwin_mount_explicit_64bit_abi_and_flag_only_result(self):
        def populate(fd, output):
            self.assertEqual(fd, 123)
            self.assertEqual(ctypes.sizeof(output._obj), 2168)
            self.assertEqual(type(output._obj).f_flags.offset, 64)
            output._obj.f_flags = 0x00200000
            return 0
        api = SimpleNamespace(fstatfs64=mock.Mock(side_effect=populate))
        with mock.patch.object(ctypes, "CDLL", return_value=api):
            self.assertEqual(peer._preset_darwin_mount_flags(123), 0x00200000)
        self.assertEqual(api.fstatfs64.restype, ctypes.c_int)

    def test_darwin_mount_missing_symbol_failed_query_and_abi_rejected(self):
        for api in (SimpleNamespace(), SimpleNamespace(fstatfs64=mock.Mock(return_value=-1))):
            with mock.patch.object(ctypes, "CDLL", return_value=api):
                self.refuse("preset_mount_unverifiable", peer._preset_darwin_mount_flags, 123)
        real_sizeof = ctypes.sizeof
        for pointer_size, structure_size in ((4, 2168), (8, 2160)):
            def incompatible(value):
                if value is ctypes.c_void_p:
                    return pointer_size
                if isinstance(value, type) and issubclass(value, ctypes.Structure):
                    return structure_size
                return real_sizeof(value)
            with mock.patch.object(ctypes, "sizeof", side_effect=incompatible), mock.patch.object(ctypes, "CDLL") as loading:
                self.refuse("preset_mount_unverifiable", peer._preset_darwin_mount_flags, 123)
                loading.assert_not_called()

    def test_darwin_ignore_ownership_is_refused_without_affecting_linux(self):
        with mock.patch.object(peer.sys, "platform", "darwin"):
            with mock.patch.object(peer, "_preset_darwin_mount_flags", return_value=0):
                peer._preset_check_ownership(123)
            with mock.patch.object(peer, "_preset_darwin_mount_flags", return_value=0x00200000):
                self.refuse("preset_ownership_unenforced", peer._preset_check_ownership, 123)
        with mock.patch.object(peer.sys, "platform", "linux"), mock.patch.object(peer, "_preset_darwin_mount_flags") as lookup:
            peer._preset_check_ownership(123)
            lookup.assert_not_called()

    def test_private_and_ancestor_mount_refusal_precedes_acl_lookup(self):
        with mock.patch.object(peer, "_preset_check_ownership", side_effect=peer._preset_error("preset_ownership_unenforced")), mock.patch.object(peer, "_preset_check_acl") as acl:
            self.refuse("preset_ownership_unenforced", peer._preset_check_fd, 123, private=True)
            self.refuse("preset_ownership_unenforced", peer._preset_check_fd, 123, private=False, directory=True)
            acl.assert_not_called()
        with mock.patch.object(peer, "_preset_check_ownership") as ownership, mock.patch.object(peer, "_preset_check_acl") as acl:
            peer._preset_check_fd(123, private=False, directory=True)
            ownership.assert_called_once_with(123)
            acl.assert_called_once_with(123, private=False, directory=True)
