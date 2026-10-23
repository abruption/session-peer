"""Isolated preference storage; metadata-controlled positives are not native QA."""
import argparse
import concurrent.futures
import contextlib
import errno
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import session_peer as peer


class RuntimeNoticeVersions(unittest.TestCase):
    def test_strict_bounded_ascii_versions(self):
        for value, expected in (("1.2.3", "1.2.3"), ("v0.0.0", "0.0.0"), ("V12.30.4", "12.30.4")):
            self.assertEqual(peer.runtime_notice_cli_version(value), expected)
        self.assertEqual(peer.runtime_notice_cli_version(str(sys.maxsize)+".0.0"), str(sys.maxsize)+".0.0")
        for value in (None, True, 123, "1.2", "01.2.3", "1.2.3-rc1", "1.2.3+meta", "１.2.3", "1.٢.3",
                      " 1.2.3", "1.2.3\n", "vV1.2.3", "9"*10000, str(sys.maxsize+1)+".0.0"):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(argparse.ArgumentTypeError):
                peer.runtime_notice_cli_version(value)

    def test_unsupported_never_touches_paths_or_posix_storage(self):
        with mock.patch.object(peer.sys, "platform", "win32"), \
                mock.patch.object(peer, "_runtime_notice_directory", side_effect=AssertionError("storage contacted")):
            self.assertEqual(peer.read_runtime_notice_preference()["status"], "unsupported")
            with self.assertRaises(peer.CcPeerError) as error:
                peer.write_runtime_notice_preference("1.2.3")
            self.assertEqual(error.exception.details, {"reason": "runtime_notice_preference_unsupported", "updated": False})


@unittest.skipUnless(sys.platform in ("linux", "darwin"), "Mac/Linux preference storage")
class RuntimeNoticePreferences(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="codex-update-pref-", dir=os.environ.get("SESSION_PEER_TEST_TMP"))
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config = self.root / "config"
        self.leaf = self.config / "session-peer"
        self.path = self.leaf / "update-notices.json"
        environment = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config)})
        environment.start()
        self.addCleanup(environment.stop)

    @contextlib.contextmanager
    def controlled_metadata(self):
        # Kingston may ignore ownership/mode. Only metadata is controlled;
        # actual directory-relative file I/O, inode binding, locks and rename run.
        original_stat, original_fstat = os.stat, os.fstat
        def safe(info):
            values = {name: getattr(info, name) for name in
                      ("st_mode", "st_uid", "st_nlink", "st_dev", "st_ino", "st_size")}
            values["st_uid"] = os.getuid()
            values["st_mode"] = stat.S_IFMT(info.st_mode) | (0o700 if stat.S_ISDIR(info.st_mode) else 0o600)
            return SimpleNamespace(**values)
        with mock.patch.object(peer.os, "stat", side_effect=lambda *a, **kw: safe(original_stat(*a, **kw))), \
                mock.patch.object(peer.os, "fstat", side_effect=lambda *a, **kw: safe(original_fstat(*a, **kw))):
            yield

    def put(self, raw):
        self.leaf.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.write_bytes(raw)
        self.path.chmod(0o600)

    def test_missing_read_has_no_effect(self):
        with self.controlled_metadata():
            self.assertEqual(peer.read_runtime_notice_preference(), {"status": "missing", "dismissedVersion": None})
        self.assertFalse(self.config.exists())

    def test_unset_or_empty_xdg_uses_only_isolated_home_config(self):
        for index, environment in enumerate(({}, {"XDG_CONFIG_HOME": ""})):
            home = self.root / ("home-" + str(index))
            with mock.patch.object(peer.os, "environ", environment), \
                    mock.patch.object(peer.Path, "home", return_value=home), self.controlled_metadata():
                self.assertEqual(peer.read_runtime_notice_preference()["status"], "missing")
                peer.write_runtime_notice_preference("1.2.3")
        self.assertTrue((home / ".config/session-peer/update-notices.json").is_file())
        self.assertFalse(self.config.exists())

    def test_set_same_clear_and_stable_lock(self):
        with self.controlled_metadata():
            self.assertEqual(peer.write_runtime_notice_preference("v1.2.3"),
                             {"status": "set", "dismissedVersion": "1.2.3", "changed": True})
            lock = (self.leaf / "update-notices.lock").stat().st_ino
            before = self.path.stat().st_ino
            self.assertFalse(peer.write_runtime_notice_preference("1.2.3")["changed"])
            self.assertEqual(self.path.stat().st_ino, before)
            self.assertEqual(peer.read_runtime_notice_preference(), {"status": "set", "dismissedVersion": "1.2.3"})
            self.assertTrue(peer.write_runtime_notice_preference(None)["changed"])
            self.assertEqual(peer.read_runtime_notice_preference(), {"status": "clear", "dismissedVersion": None})
            self.assertFalse(peer.write_runtime_notice_preference(None)["changed"])
            self.assertEqual((self.leaf / "update-notices.lock").stat().st_ino, lock)
        self.assertEqual(json.loads(self.path.read_text()), {"schemaVersion": 1, "runtime": {"dismissedVersion": None}})

    def test_malformed_future_or_noncanonical_state_never_suppresses_or_repairs(self):
        invalid = (b"{", b"[]", b'{"schemaVersion":2,"runtime":{"dismissedVersion":null}}',
                   b'{"schemaVersion":true,"runtime":{"dismissedVersion":null}}',
                   b'{"schemaVersion":1,"schemaVersion":1,"runtime":{"dismissedVersion":null}}',
                   b'{"schemaVersion":1,"runtime":{"dismissedVersion":null,"extra":0}}',
                   b'{"schemaVersion":1,"runtime":{"dismissedVersion":"v1.2.3"}}',
                   b'{"schemaVersion":1,"runtime":{"dismissedVersion":NaN}}', b"x"*4097)
        for raw in invalid:
            self.put(raw)
            before = self.path.stat().st_ino
            with self.controlled_metadata():
                self.assertEqual(peer.read_runtime_notice_preference()["status"], "invalid")
                for version in ("2.3.4", None):
                    with self.assertRaises(peer.CcPeerError) as error:
                        peer.write_runtime_notice_preference(version)
                    self.assertEqual(error.exception.details["reason"], "runtime_notice_preference_invalid")
            self.assertTrue(self.path.read_bytes() == raw, "invalid user state was overwritten")
            self.assertEqual(self.path.stat().st_ino, before)

    def test_unsafe_configured_paths_refuse_without_fallback(self):
        for configured in ("relative/config", "./config", "/a/../b", "/a/./b", "/bad\x00path"):
            with mock.patch.object(peer.os, "environ", {"XDG_CONFIG_HOME": configured}):
                self.assertEqual(peer.read_runtime_notice_preference()["reason"], "runtime_notice_preference_unsafe")
                with self.assertRaises(peer.CcPeerError):
                    peer.write_runtime_notice_preference("1.2.3")
        self.assertFalse(self.config.exists())

    def test_owner_modes_and_sticky_ancestor_rules(self):
        uid = os.getuid()
        info = lambda mode, owner=uid, links=1: SimpleNamespace(st_mode=mode, st_uid=owner, st_nlink=links)
        peer._runtime_notice_directory_stat(info(stat.S_IFDIR | 0o755))
        peer._runtime_notice_directory_stat(info(stat.S_IFDIR | 0o1777, 0))
        peer._runtime_notice_directory_stat(info(stat.S_IFDIR | 0o700), private=True)
        peer._runtime_notice_directory_stat(info(stat.S_IFDIR | 0o2700), private=True)
        peer._runtime_notice_file_stat(info(stat.S_IFREG | 0o600))
        for value, private in ((info(stat.S_IFDIR | 0o777), False),
                               (info(stat.S_IFDIR | 0o700, uid+1000), False),
                               (info(stat.S_IFDIR | 0o755), True), (info(stat.S_IFDIR | 0o500), True)):
            with self.assertRaises(peer.RuntimeNoticePreferenceFailure):
                peer._runtime_notice_directory_stat(value, private=private)
        for value in (info(stat.S_IFREG | 0o644), info(stat.S_IFREG | 0o600, uid+1000),
                      info(stat.S_IFREG | 0o600, links=2), info(stat.S_IFIFO | 0o600)):
            with self.assertRaises(peer.RuntimeNoticePreferenceFailure):
                peer._runtime_notice_file_stat(value)

    def test_symlink_and_fifo_targets_refuse_without_following_or_blocking(self):
        target = self.root / "other"
        target.write_text("untouched")
        self.leaf.mkdir(parents=True, mode=0o700)
        self.path.symlink_to(target)
        with self.controlled_metadata():
            self.assertEqual(peer.read_runtime_notice_preference()["reason"], "runtime_notice_preference_unsafe")
            with self.assertRaises(peer.CcPeerError):
                peer.write_runtime_notice_preference("1.2.3")
        self.assertEqual(target.read_text(), "untouched")
        self.path.unlink()
        try:
            os.mkfifo(self.path, mode=0o600)
        except OSError as exc:
            if exc.errno in (errno.ENOTSUP, errno.EOPNOTSUPP):
                self.skipTest("fixture filesystem has no FIFO support")
            raise
        with self.controlled_metadata():
            self.assertEqual(peer.read_runtime_notice_preference()["reason"], "runtime_notice_preference_unsafe")

    def test_symlink_ancestor_and_stable_lock_refuse(self):
        alternate = self.root / "alternate"
        alternate.mkdir(mode=0o700)
        self.config.symlink_to(alternate, target_is_directory=True)
        with self.controlled_metadata():
            self.assertEqual(peer.read_runtime_notice_preference()["reason"], "runtime_notice_preference_unsafe")
            with self.assertRaises(peer.CcPeerError):
                peer.write_runtime_notice_preference("1.2.3")
        self.assertEqual(list(alternate.iterdir()), [])
        self.config.unlink()
        self.leaf.mkdir(mode=0o700, parents=True)
        target = self.root / "untouched-lock"
        target.write_text("untouched")
        (self.leaf / "update-notices.lock").symlink_to(target)
        with self.controlled_metadata():
            with self.assertRaises(peer.CcPeerError) as error:
                peer.write_runtime_notice_preference("1.2.3")
        self.assertEqual(error.exception.details["reason"], "runtime_notice_preference_unsafe")
        self.assertEqual(target.read_text(), "untouched")
        self.assertFalse(self.path.exists())

    def test_inode_substitution_is_refused(self):
        self.put(b'{"schemaVersion":1,"runtime":{"dismissedVersion":"1.2.3"}}')
        with self.controlled_metadata():
            original = peer.os.fstat
            def substituted(fd):
                info = original(fd)
                if stat.S_ISREG(info.st_mode):
                    fields = dict(vars(info))
                    fields["st_ino"] += 1
                    return SimpleNamespace(**fields)
                return info
            with mock.patch.object(peer.os, "fstat", side_effect=substituted):
                self.assertEqual(peer.read_runtime_notice_preference()["reason"], "runtime_notice_preference_unsafe")

    def test_short_regular_reads_are_completed_within_byte_cap(self):
        self.put(b'{"schemaVersion":1,"runtime":{"dismissedVersion":"1.2.3"}}')
        original = os.read
        with self.controlled_metadata(), mock.patch.object(peer.os, "read", side_effect=lambda fd, size: original(fd, min(size, 3))):
            self.assertEqual(peer.read_runtime_notice_preference()["dismissedVersion"], "1.2.3")

    def test_pre_replace_failure_preserves_previous_complete_preference_and_cleans_temp(self):
        with self.controlled_metadata():
            peer.write_runtime_notice_preference("1.2.3")
            before = self.path.read_bytes()
            with mock.patch.object(peer.os, "replace", side_effect=OSError("private diagnostic")):
                with self.assertRaises(peer.CcPeerError) as error:
                    peer.write_runtime_notice_preference("2.3.4")
            self.assertEqual(str(error.exception), "Runtime notice preference refused")
            self.assertEqual(error.exception.details["reason"], "runtime_notice_preference_write_failed")
            self.assertNotIn("preferenceMayHaveChanged", error.exception.details)
        self.assertTrue(self.path.read_bytes() == before, "failed atomic replacement changed preference")
        self.assertEqual(sorted(path.name for path in self.leaf.iterdir()), ["update-notices.json", "update-notices.lock"])

    def test_post_replace_durability_failure_does_not_claim_no_effect(self):
        original = os.fsync
        def sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("private diagnostic")
            return original(fd)
        with self.controlled_metadata():
            peer.write_runtime_notice_preference("1.2.3")
            with mock.patch.object(peer.os, "fsync", side_effect=sync):
                with self.assertRaises(peer.CcPeerError) as error:
                    peer.write_runtime_notice_preference("2.3.4")
        self.assertTrue(error.exception.details["preferenceMayHaveChanged"])
        self.assertFalse(error.exception.details["updated"])
        self.assertEqual(json.loads(self.path.read_text())["runtime"]["dismissedVersion"], "2.3.4")

    def test_owned_temporary_validation_failure_cleans_only_bound_inode(self):
        with self.controlled_metadata():
            peer.write_runtime_notice_preference("1.2.3")
            before = self.path.read_bytes()
            original_open, original_validate = peer.os.open, peer._runtime_notice_file_stat
            temporary_inodes = set()
            def opening(name, *args, **kwargs):
                fd = original_open(name, *args, **kwargs)
                if isinstance(name, str) and name.startswith(".update-notices-"):
                    temporary_inodes.add(peer.os.fstat(fd).st_ino)
                return fd
            def validating(info):
                if info.st_ino in temporary_inodes:
                    peer._runtime_notice_fail("unsafe")
                return original_validate(info)
            with mock.patch.object(peer.os, "open", side_effect=opening), \
                    mock.patch.object(peer, "_runtime_notice_file_stat", side_effect=validating):
                with self.assertRaises(peer.CcPeerError) as error:
                    peer.write_runtime_notice_preference("2.3.4")
            self.assertEqual(error.exception.details["reason"], "runtime_notice_preference_unsafe")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(sorted(path.name for path in self.leaf.iterdir()), ["update-notices.json", "update-notices.lock"])

    def test_lock_timeout_uses_stable_file_and_original_budget(self):
        clock = [0.0]
        def sleep(seconds):
            clock[0] += seconds
        with self.controlled_metadata(), \
                mock.patch.object(peer.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(peer.time, "sleep", side_effect=sleep), \
                mock.patch.object(peer.fcntl, "flock", side_effect=BlockingIOError()):
            with self.assertRaises(peer.CcPeerError) as error:
                peer.write_runtime_notice_preference("1.2.3")
        self.assertEqual(error.exception.details["reason"], "runtime_notice_preference_busy")
        self.assertLessEqual(clock[0], 2.0)
        self.assertTrue((self.leaf / "update-notices.lock").exists())
        self.assertFalse(self.path.exists())

    def test_real_flock_concurrent_writers_leave_one_complete_preference(self):
        barrier = threading.Barrier(2)
        def write(version):
            barrier.wait(timeout=2)
            return peer.write_runtime_notice_preference(version)
        with self.controlled_metadata():
            # Create and pin the dedicated directory/lock before concurrency.
            peer.write_runtime_notice_preference(None)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(write, ("1.2.3", "2.3.4")))
            current = peer.read_runtime_notice_preference()
        self.assertTrue(all(result["changed"] for result in results))
        self.assertIn(current["dismissedVersion"], ("1.2.3", "2.3.4"))

    def test_concurrent_initial_writers_share_one_new_stable_lock(self):
        barrier = threading.Barrier(2)
        def write(version):
            barrier.wait(timeout=2)
            return peer.write_runtime_notice_preference(version)
        with self.controlled_metadata():
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(write, ("1.2.3", "2.3.4")))
            current = peer.read_runtime_notice_preference()
        self.assertEqual(len(results), 2)
        self.assertIn(current["dismissedVersion"], ("1.2.3", "2.3.4"))
        self.assertEqual(sorted(path.name for path in self.leaf.iterdir()), ["update-notices.json", "update-notices.lock"])

    def test_ambient_unexpected_exception_is_fixed_invalid_without_repairs(self):
        with mock.patch.object(peer, "_runtime_notice_directory", side_effect=RuntimeError("private diagnostic")):
            self.assertEqual(peer.read_runtime_notice_preference(),
                             {"status": "invalid", "dismissedVersion": None, "reason": "runtime_notice_preference_unavailable"})
        self.assertFalse(self.config.exists())

    def test_native_private_path_when_filesystem_enforces_metadata(self):
        state = peer.read_runtime_notice_preference()
        if state["status"] == "invalid" and state.get("reason") == "runtime_notice_preference_unsafe":
            self.skipTest("native task volume ancestors fail ownership/mode policy; controlled positives are not native certification")
        self.assertEqual(state["status"], "missing")
        self.assertTrue(peer.write_runtime_notice_preference("1.2.3")["changed"])
        self.assertEqual(stat.S_IMODE(self.leaf.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
