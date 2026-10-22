"""Offline trusted-config storage tests; external-volume fixtures are synthetic.

The fixture bypasses ownership-enforcement mount detection. A test-only
SESSION_PEER_TEST_CONFIG_UNSAFE_ANCESTOR can explicitly select one ancestor
whose group-write bit is normalized. Other native ACL, inode, owner and mode
checks still execute. This does not prove safety of that mount; a separate
native descriptor test requires ignore-ownership mounts be refused.
"""

import errno
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import session_peer as peer


@unittest.skipUnless(sys.platform == "linux" and shutil.which("ssh"), "native Linux OpenSSH config-only check")
class NativeTrustedSshConfig(unittest.TestCase):
    def test_native_config_parse_uses_selected_file_and_forced_host_key_policy(self):
        # No connection, Match exec, credentials, or default user config. This
        # native acceptance check uses real ownership/ACL checks, without mocks.
        with tempfile.TemporaryDirectory(prefix="codex-ssh-config-") as temp:
            path = Path(temp).resolve() / "selected config"
            path.write_text("Host fixture-host\n  HostName fixture.invalid\n  User fixture-user\n"
                            "  StrictHostKeyChecking no\n  ControlMaster auto\n"
                            "  IdentityFile none\n  IdentityAgent none\n", encoding="utf-8")
            path.chmod(0o600)
            selected = peer.select_trusted_ssh_config(str(path))
            token = peer.SSH_CONFIG_SELECTION.set(selected)
            try:
                done = subprocess.run(peer.trusted_ssh_command([], "fixture-host", prefix=("-G",)),
                                      capture_output=True, text=True, timeout=5)
            finally:
                peer.SSH_CONFIG_SELECTION.reset(token)
            self.assertEqual(done.returncode, 0, "native config-only parse failed")
            values = dict(line.split(" ", 1) for line in done.stdout.splitlines() if " " in line)
            self.assertEqual(values["user"], "fixture-user")
            self.assertEqual(values["hostname"], "fixture.invalid")
            self.assertEqual(values["stricthostkeychecking"], "true")
            self.assertEqual(values["controlmaster"], "false")


@unittest.skipUnless(os.name == "posix", "POSIX storage contract")
class TrustedSshConfigStorage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ssh-config-storage-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "ssh.conf"
        self.path.write_bytes(b"Host example\n  HostName example.invalid\n")
        self.path.chmod(0o600)
        self.mount = mock.patch.object(peer, "_ssh_config_check_ownership")
        self.mount.start()
        self.addCleanup(self.mount.stop)
        fixture_ancestor = os.environ.get("SESSION_PEER_TEST_CONFIG_UNSAFE_ANCESTOR")
        if fixture_ancestor:
            volume = Path(fixture_ancestor).resolve()
            self.assertIn(volume, self.root.parents, "synthetic ancestor is outside the test path")
            volume_info = volume.stat()
            volume_id = (volume_info.st_dev, volume_info.st_ino)
            real_metadata = peer._ssh_config_metadata
            def synthetic_volume_metadata(info, overflow_uid, *, directory=False):
                if directory and (getattr(info, "st_dev", None),
                                  getattr(info, "st_ino", None)) == volume_id:
                    info = SimpleNamespace(st_uid=info.st_uid,
                                           st_mode=info.st_mode & ~0o020)
                return real_metadata(info, overflow_uid, directory=directory)
            patch = mock.patch.object(peer, "_ssh_config_metadata",
                                      side_effect=synthetic_volume_metadata)
            patch.start()
            self.addCleanup(patch.stop)

    def select(self):
        return peer.select_trusted_ssh_config(str(self.path))

    def assertRefused(self, action, reason=None):
        with self.assertRaises(peer.CcPeerError) as caught:
            action()
        self.assertNotIn(str(self.path), str(caught.exception))
        if reason:
            self.assertIn(reason, str(caught.exception))
        return caught.exception

    def test_accepts_readable_file_and_immutable_selection(self):
        self.path.chmod(0o644)
        selected = self.select()
        self.assertEqual(selected.path, str(self.path))
        selected.revalidate()
        self.assertNotIn(str(self.path), repr(selected))
        with self.assertRaises(AttributeError):
            selected.path = "/other"

    def test_invalid_paths(self):
        for path in ("relative", "/", "//tmp/config", "/a/../config",
                     "/a/\nconfig", "/a/\x7fconfig", "/a/\x85config", "/a/\ud800"):
            with self.subTest(path=repr(path)):
                self.assertRefused(lambda: peer.select_trusted_ssh_config(path))

    def test_modes_and_hardlinks(self):
        for mode in (0o620, 0o602, 0o4600, 0o2600, 0o1600):
            self.path.chmod(mode)
            self.assertRefused(self.select)
        self.path.chmod(0o600)
        os.link(self.path, self.root / "link")
        self.assertRefused(self.select)

    def test_symlink_file_and_component(self):
        target = self.root / "target"
        self.path.rename(target)
        self.path.symlink_to(target)
        self.assertRefused(self.select)
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertRefused(lambda: peer.select_trusted_ssh_config(str(alias / "target")))

    def test_fifo_and_directory_refused_without_blocking(self):
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        self.assertRefused(self.select)
        self.path.unlink()
        self.path.mkdir()
        self.assertRefused(self.select)

    def test_size_boundary(self):
        self.path.write_bytes(b"#" * 65536)
        self.select()
        self.path.write_bytes(b"#" * 65537)
        self.assertRefused(self.select, "ssh_config_capacity")

    def test_revalidation_content_replacement_and_mode(self):
        for mutation in ("content", "replace", "mode"):
            with self.subTest(mutation=mutation):
                self.path.chmod(0o600)
                self.path.write_bytes(b"Host alpha\n")
                selected = self.select()
                if mutation == "content":
                    self.path.write_bytes(b"Host bravo\n")
                elif mutation == "replace":
                    replacement = self.root / "replacement"
                    replacement.write_bytes(self.path.read_bytes())
                    replacement.chmod(0o600)
                    replacement.replace(self.path)
                else:
                    self.path.chmod(0o640)
                self.assertRefused(selected.revalidate, "ssh_config_storage_changed")

    def test_unsafe_parent(self):
        self.root.chmod(0o777)
        self.addCleanup(self.root.chmod, 0o700)
        self.assertRefused(self.select)

    def test_owner_and_overflow_uid_metadata(self):
        real = self.path.stat()
        fields = {name: getattr(real, name) for name in
                  ("st_mode", "st_uid", "st_nlink")}
        fields["st_uid"] = os.geteuid() + 1
        self.assertRefused(lambda: peer._ssh_config_metadata(
            SimpleNamespace(**fields), None))
        fields["st_uid"] = os.geteuid()
        self.assertRefused(lambda: peer._ssh_config_metadata(
            SimpleNamespace(**fields), os.geteuid()), "ssh_config_ownership_unverifiable")

    def test_root_sticky_parent_and_unknown_owner(self):
        safe = SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o1777)
        peer._ssh_config_metadata(safe, 65534, directory=True)
        for uid, mode in ((os.geteuid() + 1, 0o700), (0, 0o777), (65534, 0o700)):
            with self.subTest(uid=uid, mode=mode):
                self.assertRefused(lambda: peer._ssh_config_metadata(
                    SimpleNamespace(st_uid=uid, st_mode=stat.S_IFDIR | mode),
                    65534, directory=True))

    def test_linux_overflow_ownership_proof_unavailable(self):
        with mock.patch.object(peer.sys, "platform", "linux"):
            with mock.patch("builtins.open", mock.mock_open(read_data=b"65534\n")):
                self.assertEqual(peer._ssh_config_overflow_uid(), 65534)
            with mock.patch("builtins.open", side_effect=OSError("private path")):
                self.assertRefused(peer._ssh_config_overflow_uid,
                                   "ssh_config_ownership_unverifiable")

    def test_hash_change_detected_even_when_identity_matches(self):
        with mock.patch.object(peer, "_ssh_config_identity", return_value=("synthetic",)):
            selected = self.select()
            self.path.write_bytes(b"different content")
            self.assertRefused(selected.revalidate, "ssh_config_storage_changed")

    def test_changed_during_read(self):
        real_read = os.read
        def mutate(fd, size):
            result = real_read(fd, size)
            if result:
                self.path.write_bytes(b"changed")
            return result
        with mock.patch.object(peer.os, "read", side_effect=mutate):
            self.assertRefused(self.select, "ssh_config_storage_changed")

    def test_acl_policy_mocks(self):
        with mock.patch.object(peer.sys, "platform", "darwin"):
            for tags in ((1,), (1, 2)):
                with mock.patch.object(peer, "_ssh_config_darwin_acl_tags", return_value=tags):
                    self.assertRefused(lambda: peer._ssh_config_check_acl(42, private=False),
                                       "ssh_config_unsafe_acl")
            with mock.patch.object(peer, "_ssh_config_darwin_acl_tags", return_value=(2,)):
                peer._ssh_config_check_acl(42, private=False)
        with mock.patch.object(peer.sys, "platform", "linux"):
            with mock.patch.object(peer.os, "getxattr", create=True, return_value=b"acl"):
                self.assertRefused(lambda: peer._ssh_config_check_acl(42, private=False))
            with mock.patch.object(peer.os, "getxattr", create=True,
                                   side_effect=OSError(errno.ENOTSUP, "not supported")):
                self.assertRefused(lambda: peer._ssh_config_check_acl(42, private=False),
                                   "ssh_config_acl_unverifiable")

    def test_mount_ignores_ownership_refused(self):
        self.mount.stop()
        with mock.patch.object(peer.sys, "platform", "darwin"):
            with mock.patch.object(peer, "_ssh_config_darwin_mount_flags", return_value=0x00200000):
                self.assertRefused(lambda: peer._ssh_config_check_ownership(42),
                                   "ssh_config_ownership_unenforced")

    @unittest.skipUnless(peer.sys.platform == "darwin", "Darwin native mount API")
    def test_native_mount_policy(self):
        self.mount.stop()
        fd = os.open(self.path, os.O_RDONLY)
        try:
            flags = peer._ssh_config_darwin_mount_flags(fd)
            if flags & 0x00200000:
                self.assertRefused(lambda: peer._ssh_config_check_ownership(fd),
                                   "ssh_config_ownership_unenforced")
            else:
                peer._ssh_config_check_ownership(fd)
        finally:
            os.close(fd)

    def test_primary_failure_survives_close_failure(self):
        with mock.patch.object(peer.os, "close", side_effect=OSError("private diagnostic")):
            with self.assertRaisesRegex(peer.CcPeerError, "original"):
                with peer._ssh_config_cleanup_scope(peer.os.close, 42):
                    raise peer._ssh_config_error("original")


class TrustedSshConfigCommand(unittest.TestCase):
    def test_opt_out_exact_argv_no_io(self):
        token = peer.SSH_CONFIG_SELECTION.set(None)
        try:
            with mock.patch.object(peer.os, "open", side_effect=AssertionError("file I/O")):
                self.assertEqual(peer.trusted_ssh_command(
                    ["-p", "22"], "host", "command", prefix=("-T",), identity_options=("-v",)),
                    ["ssh", "-T", "-v", "-p", "22", "host", "command"])
        finally:
            peer.SSH_CONFIG_SELECTION.reset(token)
    def test_selected_safety_order_revalidation_and_diagnostic(self):
        selected = mock.Mock(path="/private/config")
        token = peer.SSH_CONFIG_SELECTION.set(selected)
        try:
            argv = peer.trusted_ssh_command(["-oBatchMode=no"], "host", "cmd", prefix=("-G",))
            selected.revalidate.assert_called_once_with()
            self.assertEqual(argv[:3], ["ssh", "-G", "-oStrictHostKeyChecking=yes"])
            self.assertLess(argv.index("-oBatchMode=yes"), argv.index("-oBatchMode=no"))
            self.assertEqual(argv[-5:], ["-F", "/private/config", "-oBatchMode=no", "host", "cmd"])
            self.assertEqual(peer.trusted_ssh_diagnostic("bad /private/config"), "bad <ssh-config>")
            selected.revalidate.side_effect = peer._ssh_config_error("changed")
            with self.assertRaises(peer.CcPeerError):
                peer.trusted_ssh_command([], "host")
        finally:
            peer.SSH_CONFIG_SELECTION.reset(token)
