"""Mocked platform APIs and root discovery; no native delivery/MDM evidence."""
import base64
import ctypes
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import session_peer as peer


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

    def read_cf(self, cf):
        with mock.patch.object(peer.sys, "platform", "darwin"), \
             mock.patch.object(ctypes, "CDLL", return_value=cf):
            return peer.codex_managed_preference_values()

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
