import builtins
import unittest
from unittest.mock import patch
import session_peer as core


class InstallGuidance(unittest.TestCase):
    def test_manager_detection_has_no_side_effects_or_private_paths(self):
        for prefix, manager in [('/fixture/pipx/venvs/session-peer', 'pipx'),
                                ('/fixture/uv/tools/session-peer', 'uv'),
                                ('/fixture/venv', 'venv')]:
            with self.subTest(manager=manager), patch.object(core, 'installed_as_distribution', return_value=True), patch.object(core.sys, 'prefix', prefix), patch.object(core.sys, 'base_prefix', '/base'):
                value = core.relay_install_guidance()
                self.assertEqual(value['installation'], manager)
                self.assertIn('session-peer[relay]', value['command'])
                self.assertNotIn('/fixture', str(value))
        with patch.object(core, 'installed_as_distribution', return_value=False):
            self.assertEqual(core.relay_install_guidance()['installation'], 'standalone_or_unknown')
        with patch.object(core, 'installed_as_distribution', return_value=True), patch.object(core.sys, 'prefix', '/base'), patch.object(core.sys, 'base_prefix', '/base'):
            self.assertNotIn('command', core.relay_install_guidance())

    def test_missing_extra_and_old_python_never_install(self):
        original = builtins.__import__
        def missing(name, *args, **kwargs):
            if name == 'session_peer_relay': raise ImportError('fixture')
            return original(name, *args, **kwargs)
        with patch.object(core, 'installed_as_distribution', return_value=False), patch('builtins.__import__', side_effect=missing), patch.object(core.sys, 'version_info', (3, 11)), patch.object(core.os, 'name', 'posix'):
            with self.assertRaises(core.CcPeerError) as caught: core.optional_relay()
            self.assertEqual(caught.exception.details['reason'], 'relay_dependencies_missing')
        with patch.object(core, 'installed_as_distribution', return_value=False), patch.object(core.sys, 'version_info', (3, 10)):
            with self.assertRaises(core.CcPeerError) as caught: core.optional_relay()
            self.assertEqual(caught.exception.details['reason'], 'relay_runtime_unsupported')
