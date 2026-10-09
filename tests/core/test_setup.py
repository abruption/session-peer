"""The setup choice and missing-runtime paths remain dependency-free."""
import contextlib
import io
import json
import unittest
from unittest import mock

import session_peer as core


class SetupChoices(unittest.TestCase):
    def test_choice_plan_json_and_text_have_no_optional_import_or_installer(self):
        for flags in (['--json'], ['--output-format', 'text']):
            with mock.patch.object(core, 'optional_relay', side_effect=AssertionError('optional import')), \
                    mock.patch.object(core, 'installed_as_distribution', return_value=False), \
                    mock.patch.object(core.subprocess, 'run', side_effect=AssertionError('installer')), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(core.main(['setup', *flags]), 0)
            self.assertEqual(json.loads(output.getvalue())['choices'], ['local', 'ssh', 'relay'])
            self.assertFalse(json.loads(output.getvalue())['changed'])

    def test_unsupported_relay_runtime_gives_guidance_before_import(self):
        with mock.patch.object(core.sys, 'version_info', (3, 9)), \
                mock.patch.object(core, 'installed_as_distribution', return_value=False), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(core.main(['setup', '--mode', 'relay', '--json']), 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result['reason'], 'relay_runtime_unsupported')
        self.assertIn('Keep the existing CLI', result['guidance']['nextAction'])

    def test_pipx_uv_and_venv_guidance_retains_manager_without_execution(self):
        for prefix, manager in (('/fixture/pipx/venvs/session-peer', 'pipx'),
                                ('/fixture/uv/tools/session-peer', 'uv'),
                                ('/fixture/venv', 'venv')):
            with self.subTest(manager=manager), \
                    mock.patch.object(core, 'installed_as_distribution', return_value=True), \
                    mock.patch.object(core.sys, 'prefix', prefix), \
                    mock.patch.object(core.sys, 'base_prefix', '/fixture/python'), \
                    mock.patch.object(core.subprocess, 'run', side_effect=AssertionError('installer')):
                guide = core.relay_install_guidance()
            self.assertEqual(guide['installation'], manager)
            self.assertIn('session-peer[relay]', guide['command'])

    def test_cli_only_cannot_apply_relay_actions_and_bad_interactive_mode_refuses(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(core.main(['setup', '--mode', 'local', '--action', 'init', '--apply', '--json']), 1)
        self.assertEqual(json.loads(output.getvalue())['reason'], 'setup_action_unsupported')
        with mock.patch('builtins.input', return_value='invalid'), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(core.main(['setup', '--interactive', '--json']), 1)
        self.assertEqual(json.loads(output.getvalue())['reason'], 'invalid_setup_mode')


if __name__ == '__main__':
    unittest.main()
