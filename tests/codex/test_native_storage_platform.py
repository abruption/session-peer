"""Mocked platform APIs and root discovery; no native delivery/MDM evidence."""
import argparse
import base64
import contextlib
import ctypes
import os
from pathlib import Path
import tempfile
import sqlite3
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock

import session_peer as peer
from tests.codex.support import THREAD, isolate_native_layers

REAL_QUEUE_PREFERENCE_POLICY = peer.codex_queue_preference_policy


class QueuePreferenceVersions(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        isolate_native_layers(self, self.root)
        self.args = argparse.Namespace(to="codex:" + THREAD, codex_home=str(self.root),
            codex_bin="fixture", dry_run=False, wake=False, all=False,
            allow_inactive_codex_home=True)
        with contextlib.closing(sqlite3.connect(self.root / "state_5.sqlite")) as db:
            db.execute("CREATE TABLE threads(id TEXT,title TEXT,cwd TEXT,updated_at INTEGER,archived INTEGER,rollout_path TEXT)")
            db.execute("INSERT INTO threads VALUES(?, 'fixture', ?, 1, 0, '')", (THREAD, str(self.root)))
            db.commit()

    def probe(self, stdout=b"codex-cli 0.162.1\n", **changes):
        fields = dict(stdout=stdout, stderr=b"diagnostic-fixture", returncode=0, reason=None,
            stdout_overflow=False, cleanup_failed=False, spawned=True, interrupted=False)
        fields.update(changes)
        return SimpleNamespace(**fields)

    def ordinary_values(self, *, forced_only=True):
        return [] if forced_only else [base64.b64encode(b'sqlite_home="ordinary-fixture"').decode("ascii")]

    def test_policy_is_exact_reviewed_version_not_an_ordering_rule(self):
        for version in ("codex-cli 0.154.0", "codex-cli 0.162.0", "codex-cli 0.162.2", "codex-cli 0.162.1-vendor", None):
            with self.subTest(version=version):
                self.assertTrue(peer.codex_preferences_for_version(version))
        self.assertFalse(peer.codex_preferences_for_version("codex-cli 0.162.1"))

    def test_mac_probe_uses_selected_plan_bounded_runner_and_never_echoes_output(self):
        cases = ((self.probe(), False), (self.probe(b"codex-cli 0.154.0"), True),
                 (self.probe(b"unexpected-fixture"), True), (self.probe(b"\xff"), True),
                 (self.probe(returncode=1), True), (self.probe(reason="process_deadline"), True),
                 # Even complete reviewed-version output with abnormal exit
                 # uses the conservative mode, not an unproven clean query.
                 (self.probe(returncode=-9), True),  # POSIX SIGKILL, mocked on every OS
                 (self.probe(stdout_overflow=True), True), (self.probe(b"x" * 4097), True))
        for done, expected in cases:
            with self.subTest(expected=expected), mock.patch.object(peer.sys, "platform", "darwin"), \
                 mock.patch.object(peer.time, "monotonic", return_value=10), \
                 mock.patch.object(peer, "handoff_stream_child", return_value=done) as child:
                result = REAL_QUEUE_PREFERENCE_POLICY("fixture", self.root, self.root)
            self.assertIs(result, expected)
            self.assertEqual(child.call_args.args[:4], (["fixture", "--version"], b"", 13, 15))
            self.assertEqual(child.call_args.kwargs["cwd"], self.root)
            self.assertEqual(child.call_args.kwargs["env"]["CODEX_HOME"], str(self.root))

    def test_unclean_probe_refuses_and_interruption_propagates(self):
        for options in ({"cleanup_failed": True}, {"spawned": None}, {"interrupted": True}):
            with self.subTest(options=options), mock.patch.object(peer.sys, "platform", "darwin"), \
                 mock.patch.object(peer, "handoff_stream_child", return_value=self.probe(**options)):
                with self.assertRaises(KeyboardInterrupt if options.get("interrupted") else peer.CcPeerError) as caught:
                    REAL_QUEUE_PREFERENCE_POLICY("fixture", self.root, self.root)
            self.assertNotIn("diagnostic-fixture", str(caught.exception))

    def test_non_mac_does_not_probe(self):
        with mock.patch.object(peer.sys, "platform", "linux"), mock.patch.object(peer, "handoff_stream_child") as child:
            self.assertFalse(REAL_QUEUE_PREFERENCE_POLICY("fixture", self.root, self.root))
        child.assert_not_called()

    def test_queue_and_dry_run_use_version_policy_without_rejecting_unknown_version(self):
        for version in (b"codex-cli 0.154.0", b"codex-cli 0.162.1", b"unknown-fixture"):
            for dry_run in (True, False):
                self.args.dry_run = dry_run
                expected_refusal = version != b"codex-cli 0.162.1"
                with self.subTest(version=version, dry_run=dry_run), \
                     mock.patch.object(peer.sys, "platform", "darwin"), \
                     mock.patch.object(peer, "codex_queue_preference_policy", wraps=REAL_QUEUE_PREFERENCE_POLICY), \
                     mock.patch.object(peer, "codex_managed_preference_values", side_effect=self.ordinary_values), \
                     mock.patch.object(peer, "handoff_stream_child", return_value=self.probe(version)) as probe, \
                     mock.patch.object(peer, "resolve_codex_home", return_value=(self.root, {})), \
                     mock.patch.object(peer, "revalidate_codex_home"), \
                     mock.patch.object(peer, "codex_executable", return_value="fixture"), \
                     mock.patch.object(peer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0,
                         "Queued message fixture-id for thread " + THREAD + ".\n", "")) as queue:
                    if expected_refusal:
                        with self.assertRaises(peer.CcPeerError) as caught:
                            peer._queue_codex(self.args, "fixture")
                        self.assertEqual(caught.exception.details["reason"], "sqlite_home_managed_configuration")
                        queue.assert_not_called()
                    else:
                        result = peer._queue_codex(self.args, "fixture")
                        self.assertEqual(result["status"], "validated" if dry_run else "queued")
                        self.assertEqual(queue.call_count, 0 if dry_run else 1)
                    probe.assert_called_once()
        # An unknown version is not itself a refusal in the absence of a
        # relevant ordinary setting; no new native compatibility is claimed.
        with mock.patch.object(peer.sys, "platform", "darwin"), \
             mock.patch.object(peer, "handoff_stream_child", return_value=self.probe(b"unknown-fixture")):
            mode = REAL_QUEUE_PREFERENCE_POLICY("fixture", self.root, self.root)
            peer.check_codex_storage(self.root, cwd=self.root, include_ordinary_preferences=mode)


class NativeStoragePlatforms(unittest.TestCase):
    def windows_api(self, value=r"D:\NativeData", hr=0, null=False, error=False):
        raw = value.encode("utf-16-le", errors="surrogatepass") + b"\x00\x00"
        buffer = ctypes.create_string_buffer(raw)
        shell, ole = mock.Mock(), mock.Mock()
        def lookup(guid, flags, token, output):
            self.assertEqual((flags, token), (0, None))
            self.assertEqual(guid._obj.Data1, 0x62AB5D82)
            self.assertEqual((guid._obj.Data2, guid._obj.Data3), (0xFDC1, 0x4DC3))
            self.assertEqual(tuple(guid._obj.Data4), (0xA9, 0xDD, 0x07, 0x0D, 0x1D, 0x49, 0x5D, 0x97))
            if error:
                raise OSError("fixture")
            if not null:
                ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(buffer)
            return hr
        shell.SHGetKnownFolderPath.side_effect = lookup
        ole.expected_pointer = ctypes.addressof(buffer)
        ole.lookup = shell.SHGetKnownFolderPath
        loader = mock.patch.object(ctypes, "WinDLL", side_effect=[shell, ole], create=True)
        return loader, ole

    def test_known_folder_ignores_environment_and_frees_allocation(self):
        loader, ole = self.windows_api()
        with loader, mock.patch.dict(os.environ, {"ProgramData": "untrusted"}):
            self.assertEqual(peer.codex_windows_program_data(), r"D:\NativeData")
        ole.CoTaskMemFree.assert_called_once()
        self.assertEqual(ole.CoTaskMemFree.call_args.args[0].value, ole.expected_pointer)
        self.assertIs(ole.lookup.restype, ctypes.c_int32)
        self.assertEqual(ole.lookup.argtypes[1:], [ctypes.c_uint32, ctypes.c_void_p,
                                                 ctypes.POINTER(ctypes.c_void_p)])

    def test_known_folder_failure_null_and_error_fallback(self):
        for options in ({"hr": -1}, {"null": True}, {"error": True}):
            with self.subTest(options=list(options)):
                loader, ole = self.windows_api(**options)
                with loader:
                    self.assertEqual(peer.codex_windows_program_data(), r"C:\ProgramData")
                self.assertEqual(ole.CoTaskMemFree.call_count,
                                 0 if options.get("null") or options.get("error") else 1)

    def test_known_folder_success_does_not_fallback_on_invalid_path(self):
        for value in ("", "relative", r"\NativeData", "x" * 32768):
            loader, ole = self.windows_api(value=value)
            with loader:
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer.codex_windows_program_data()
            self.assertEqual(caught.exception.details["reason"], "storage_config_unverifiable")
            ole.CoTaskMemFree.assert_called_once()

    def test_known_folder_preserves_native_utf16_path(self):
        value = "D:\\Native-" + chr(0xd800)
        loader, ole = self.windows_api(value=value)
        with loader:
            self.assertEqual(peer.codex_windows_program_data(), value)
        ole.CoTaskMemFree.assert_called_once()

    @unittest.skipUnless(os.name == "nt", "Windows Known Folder API only")
    def test_windows_api_path_smoke_without_exposing_value(self):
        import ntpath
        self.assertTrue(ntpath.isabs(peer.codex_windows_program_data()))

    def cf_api(self, *, forced=(True, True, False), value_type=7, sync=True,
               copied=30, extract=True):
        cf = mock.Mock()
        cf.CFStringCreateWithCString.side_effect = [10, 20, 21]
        cf.CFPreferencesAppSynchronize.return_value = sync
        cf.CFPreferencesAppValueIsForced.side_effect = list(forced)
        cf.CFPreferencesCopyAppValue.return_value = copied
        cf.CFGetTypeID.return_value = value_type
        cf.CFStringGetTypeID.return_value = 7
        def get_string(value, buffer, size, encoding):
            self.assertEqual(size, peer.MAX_CODEX_CONFIG_BYTES * 2 + 1)
            buffer.value = base64.b64encode(b'model="fixture"\n')
            return extract
        cf.CFStringGetCString.side_effect = get_string
        return cf

    def read_cf(self, cf, **kwargs):
        with mock.patch.object(peer.sys, "platform", "darwin"), \
             mock.patch.object(ctypes, "CDLL", return_value=cf):
            return peer.codex_managed_preference_values(**kwargs)

    def test_wake154_reads_ordinary_preferences_without_forced_gate(self):
        cf = self.cf_api(forced=())
        self.assertEqual(len(self.read_cf(cf, forced_only=False)), 2)
        cf.CFPreferencesAppValueIsForced.assert_not_called()
        self.assertEqual(cf.CFPreferencesCopyAppValue.call_count, 2)
        self.assertEqual(cf.CFRelease.call_args_list,
                         [mock.call(30), mock.call(30), mock.call(21), mock.call(20), mock.call(10)])

    def test_cf_forced_string_read_and_owned_values_released(self):
        cf = self.cf_api()
        self.assertEqual(len(self.read_cf(cf)), 1)
        self.assertEqual(cf.CFRelease.call_args_list,
                         [mock.call(30), mock.call(21), mock.call(20), mock.call(10)])

    def test_cf_nonforced_or_released_force_does_not_read_value(self):
        cf = self.cf_api(forced=(False, False))
        self.assertEqual(self.read_cf(cf), [])
        cf.CFPreferencesCopyAppValue.assert_not_called()
        cf = self.cf_api(forced=(True, False, False), value_type=99)
        self.assertEqual(self.read_cf(cf), [])
        cf.CFGetTypeID.assert_not_called()
        cf.CFRelease.assert_any_call(30)

    def test_cf_missing_value_is_ignored(self):
        cf = self.cf_api(forced=(True, False), copied=0)
        self.assertEqual(self.read_cf(cf), [])
        self.assertNotIn(mock.call(0), cf.CFRelease.call_args_list)

    def test_cf_invalid_type_unbounded_value_or_sync_failure_is_typed_refusal(self):
        for options in ({"value_type": 99}, {"extract": False}, {"sync": False}):
            cf = self.cf_api(**options)
            with self.subTest(options=options), \
                 mock.patch.object(peer.sys, "platform", "darwin"), \
                 mock.patch.object(ctypes, "CDLL", return_value=cf):
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer._refuse_managed_preference_storage()
                self.assertEqual(caught.exception.details["reason"], "storage_config_unverifiable")
            cf.CFRelease.assert_any_call(10)

    def test_cf_not_loaded_on_other_platform(self):
        with mock.patch.object(peer.sys, "platform", "linux"), mock.patch.object(ctypes, "CDLL") as load:
            self.assertEqual(peer.codex_managed_preference_values(), [])
            load.assert_not_called()

    def test_cf_loading_or_missing_symbol_failure_is_typed(self):
        for failure in (OSError("fixture"), AttributeError("fixture")):
            with self.subTest(kind=type(failure).__name__), \
                 mock.patch.object(peer.sys, "platform", "darwin"), \
                 mock.patch.object(ctypes, "CDLL", side_effect=failure):
                with self.assertRaises(peer.CcPeerError) as caught:
                    peer._refuse_managed_preference_storage()
                self.assertEqual(caught.exception.details["reason"], "storage_config_unverifiable")

    def test_cf_key_creation_failure_releases_existing_domain(self):
        cf = self.cf_api()
        cf.CFStringCreateWithCString.side_effect = [10, 0]
        with mock.patch.object(peer.sys, "platform", "darwin"), \
                mock.patch.object(ctypes, "CDLL", return_value=cf):
            with self.assertRaises(peer.CcPeerError) as caught:
                peer._refuse_managed_preference_storage()
        self.assertEqual(caught.exception.details["reason"], "storage_config_unverifiable")
        self.assertEqual(cf.CFRelease.call_args_list, [mock.call(10)])
        cf.CFPreferencesCopyAppValue.assert_not_called()


class NativeProjectRoots(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.root = self.base / "home"
        self.root.mkdir()
        self.repo = self.base / "repo"
        self.cwd = self.repo / "a" / "b"
        self.cwd.mkdir(parents=True)
        for patcher in (mock.patch.object(peer, "codex_system_config_paths", return_value=[]),
                        mock.patch.object(peer, "codex_managed_preference_values", return_value=[])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def paths(self):
        return peer.codex_project_config_paths(self.cwd, root=self.root)

    def test_no_marker_or_headless_marker_uses_only_cwd(self):
        self.assertEqual(self.paths(), [self.cwd / ".codex" / "config.toml"])
        (self.repo / ".git").mkdir()
        self.assertEqual(len(self.paths()), 1)

    def test_git_directory_head_or_worktree_pointer_stops_at_closest_root(self):
        (self.repo / ".git").mkdir()
        (self.repo / ".git" / "HEAD").write_text("ref: refs/heads/main")
        self.assertEqual(len(self.paths()), 3)
        (self.cwd.parent / ".git").write_text("gitdir: fixture")
        self.assertEqual(len(self.paths()), 2)
        self.assertNotIn(self.repo / ".codex" / "config.toml", self.paths())

    def test_above_root_and_cwd_config_are_not_native_layers(self):
        (self.repo / ".git").write_text("gitdir: fixture")
        (self.base / ".codex").mkdir()
        (self.base / ".codex" / "config.toml").write_text('sqlite_home="ignored-above-root"')
        (self.cwd / "config.toml").write_text('sqlite_home="ignored-cwd-config"')
        peer.check_codex_storage(self.root, cwd=self.cwd)
        (self.repo / ".codex").mkdir()
        (self.repo / ".codex" / "config.toml").write_text('sqlite_home="fixture"')
        with self.assertRaises(peer.CcPeerError) as caught:
            peer.check_codex_storage(self.root, cwd=self.cwd)
        self.assertEqual(caught.exception.details["reason"], "sqlite_home_project_configuration")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO marker fixture needs POSIX")
    def test_non_directory_marker_is_recognized_without_opening_it(self):
        os.mkfifo(self.repo / ".git")
        self.assertEqual(len(self.paths()), 3)
        (self.repo / ".codex").mkdir()
        (self.repo / ".codex" / "config.toml").write_text('sqlite_home="fixture"')
        with self.assertRaises(peer.CcPeerError) as caught:
            peer.check_codex_storage(self.root, cwd=self.cwd)
        self.assertEqual(caught.exception.details["reason"], "sqlite_home_project_configuration")

    def test_custom_markers_in_known_configuration_retain_superset(self):
        (self.root / "config.toml").write_text('"project_root_markers"=["fixture"]')
        self.assertIn(self.base / ".codex" / "config.toml", self.paths())
        (self.root / "config.toml").write_text('[profiles.unselected]\nproject_root_markers=["fixture"]')
        self.assertEqual(len(self.paths()), 1)

    def test_wake154_ordinary_preference_custom_marker_keeps_superset(self):
        encoded = base64.b64encode(b'project_root_markers=["fixture"]').decode('ascii')
        def values(*, forced_only=True):
            return [] if forced_only else [encoded]
        with mock.patch.object(peer, "codex_managed_preference_values", side_effect=values):
            self.assertEqual(len(self.paths()), 1)
            paths = peer.codex_project_config_paths(self.cwd, root=self.root, include_ordinary_preferences=True)
            self.assertIn(self.base / ".codex" / "config.toml", paths)
            # The new mode reaches the classifier as well, not only path output.
            (self.base / ".codex").mkdir()
            (self.base / ".codex" / "config.toml").write_text('sqlite_home="fixture"')
            peer.check_codex_storage(self.root, cwd=self.cwd)
            with self.assertRaises(peer.CcPeerError) as caught:
                peer.check_codex_storage(self.root, cwd=self.cwd, include_ordinary_preferences=True)
            self.assertEqual(caught.exception.details["reason"], "sqlite_home_project_configuration")

    def test_symlink_marker_fails_closed(self):
        try:
            (self.repo / ".git").symlink_to(self.root, target_is_directory=True)
        except (NotImplementedError, OSError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(peer.CcPeerError) as caught:
            self.paths()
        self.assertEqual(caught.exception.details["reason"], "storage_config_unverifiable")

    def test_project_directory_equal_to_selected_home_is_not_a_second_layer(self):
        home = self.cwd / ".codex"
        home.mkdir()
        with mock.patch.object(peer, "_refuse_configured_storage") as inspect:
            peer.check_codex_storage(home, cwd=self.cwd)
        self.assertEqual(inspect.call_args_list,
                         [mock.call(home / "config.toml", "sqlite_home_configuration")])

    def test_unreadable_root_marker_fails_closed(self):
        original = Path.lstat
        def inspect(path, *args, **kwargs):
            if path.name == ".git":
                raise PermissionError("fixture")
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "lstat", inspect):
            with self.assertRaises(peer.CcPeerError) as caught:
                self.paths()
        self.assertEqual(caught.exception.details["reason"], "storage_config_unverifiable")
