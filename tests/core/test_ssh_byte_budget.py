import base64
import shlex
import subprocess
import unittest
from unittest import mock
import session_peer as core


class CommandBudget(unittest.TestCase):
    def invoke(self, argv):
        with mock.patch.object(core, 'ssh_user_metadata', return_value={}), mock.patch.object(
                core.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{"ok":true}', '')) as run:
            result = core.run_remote('fixture', argv, [])
            command = run.call_args.args[0][-1]
            self.assertLessEqual(len(command.encode()) + 1, 128 * 1024)
            return result

    def test_exact_command_boundary_including_quoting_and_options(self):
        prefix = ['send', '--to', 'claude:test', '--b64']
        overhead = len(' '.join(shlex.quote(x) for x in ['python3', '-', *prefix, '', '--json']).encode()) - 2
        payload = 'a' * (core.MAX_SSH_COMMAND_BYTES - overhead)
        self.assertTrue(self.invoke([*prefix, payload])['ok'])
        with mock.patch.object(core.subprocess, 'run') as run:
            with self.assertRaises(core.CcPeerError) as caught:
                core.run_remote('fixture', [*prefix, payload + 'a'], [])
            self.assertEqual(caught.exception.details['reason'], 'ssh_command_too_large')
            run.assert_not_called()

    def test_utf8_envelope_and_long_options_are_in_the_same_budget(self):
        for body, accepted in [('a' * 90000, True), ('한' * 40000, False), ('😀' * 30000, False)]:
            encoded = base64.b64encode(('From: fixture\n\n' + body + '\nReply-To: fixture').encode()).decode()
            argv = ['send', '--b64', encoded, '--to', 'claude:test']
            if accepted:
                self.invoke(argv)
            else:
                with mock.patch.object(core.subprocess, 'run') as run:
                    with self.assertRaisesRegex(core.CcPeerError, 'Nothing was sent'):
                        core.run_remote('fixture', argv, [])
                    run.assert_not_called()
        with self.assertRaises(core.CcPeerError):
            self.invoke(['send', '--codex-home', '한' * 50000])

    def test_local_message_validation_is_unchanged(self):
        core.check_message('한' * 40000, remote=False)
