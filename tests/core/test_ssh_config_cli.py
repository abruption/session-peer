"""Trusted config selection is invocation-local and reaches every SSH spawn.

All config selection and process boundaries are mocked: these tests never load
user SSH configuration, execute hooks, connect, or submit a native message.
"""
import contextlib
from dataclasses import dataclass
import io
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

import session_peer as peer


CONFIG = '/private/fixture/secret-ssh-config'
FLAGS = ['--ssh-config', CONFIG, '--trust-ssh-config']
SAFETY = ['-oStrictHostKeyChecking=yes', '-oUpdateHostKeys=no',
          '-oForwardAgent=no', '-oPermitLocalCommand=no', '-oBatchMode=yes',
          '-oControlMaster=no', '-oControlPath=none', '-oControlPersist=no']


@dataclass(frozen=True)
class SelectedConfig:
    path: str
    revalidate: object


class UnsupportedTrustedConfigCli(unittest.TestCase):
    def test_windows_refuses_before_selection(self):
        output, error = io.StringIO(), io.StringIO()
        with mock.patch.object(peer, 'IS_WINDOWS', True), \
             mock.patch.object(peer, 'select_trusted_ssh_config') as selector, \
             mock.patch.object(peer.subprocess, 'run') as run, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = peer.main(['list', '--host', 'fixture', *FLAGS, '--json'])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['reason'], 'ssh_config_platform_unsupported')
        selector.assert_not_called()
        run.assert_not_called()


@unittest.skipIf(peer.IS_WINDOWS, 'selected-config and handoff/identity execution are POSIX-only')
class TrustedConfigCli(unittest.TestCase):
    def setUp(self):
        self.config = SelectedConfig(CONFIG, mock.Mock())
        self.selector = mock.patch.object(peer, 'select_trusted_ssh_config', return_value=self.config).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(peer, 'tailscale_status', return_value={}).start()
        mock.patch.object(peer, 'resolve_ssh_destination', side_effect=lambda host, status: host).start()

    def invoke(self, *argv, standalone=False):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), \
             mock.patch.object(peer.sys, 'argv', ['session-peer', *argv]):
            try:
                code = peer.main(None if standalone else list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), error.getvalue()

    @contextlib.contextmanager
    def selected(self):
        token = peer.SSH_CONFIG_SELECTION.set(self.config)
        try:
            yield
        finally:
            peer.SSH_CONFIG_SELECTION.reset(token)

    def assert_selected(self, argv):
        index = argv.index('-F')
        self.assertEqual(argv[index + 1], CONFIG)
        self.assertEqual(argv[index - len(SAFETY):index], SAFETY)
        self.assertEqual(argv.count('-F'), 1)

    def test_all_host_commands_select_once_and_restore_context(self):
        for command in ('list', 'send', 'doctor', 'update'):
            seen = []
            def dispatch(args):
                seen.append(peer.SSH_CONFIG_SELECTION.get())
                return 0
            extra = ['--to', 'worker', '-m', 'hello'] if command == 'send' else []
            outer = object()
            token = peer.SSH_CONFIG_SELECTION.set(outer)
            try:
                with self.subTest(command=command), mock.patch.object(peer, 'cmd_' + command, side_effect=dispatch):
                    self.selector.reset_mock()
                    code, _, _ = self.invoke(command, '--host', 'fixture', *FLAGS, *extra)
                    self.assertEqual(code, 0)
                    self.assertEqual(seen, [self.config])
                    self.selector.assert_called_once_with(CONFIG)
                    self.assertIs(peer.SSH_CONFIG_SELECTION.get(), outer)
            finally:
                peer.SSH_CONFIG_SELECTION.reset(token)

    def test_opt_out_clears_inherited_context_and_restores_after_error(self):
        with self.selected(), mock.patch.object(peer, 'cmd_list') as dispatch:
            def fail(args):
                self.assertIsNone(peer.SSH_CONFIG_SELECTION.get())
                raise peer.CcPeerError('fixture refusal')
            dispatch.side_effect = fail
            code, _, _ = self.invoke('list', '--host', 'fixture', '--json')
            self.assertEqual(code, 1)
            self.assertIs(peer.SSH_CONFIG_SELECTION.get(), self.config)
        self.selector.assert_not_called()
        self.config.revalidate.assert_not_called()

    def test_invalid_combinations_fail_before_io_advisories_or_stdin(self):
        cases = [
            ['list', '--host', 'fixture', '--ssh-config', CONFIG],
            ['list', '--host', 'fixture', '--trust-ssh-config'],
            ['list', '--host', 'fixture', *FLAGS, '--ssh-config', CONFIG],
            ['list', '--host', 'fixture', *FLAGS, '--trust-ssh-config'],
            ['list', *FLAGS],
            ['setup', *FLAGS],
            ['send', '--host', 'fixture', '--device', 'a' * 64, '--to', 'worker', *FLAGS],
            ['send', '--host', 'fixture', '--to', 'session-peer://v1/reply/fixture', *FLAGS],
        ]
        for argv in cases:
            with self.subTest(argv=argv), mock.patch.object(peer.subprocess, 'run') as run, \
                 mock.patch.object(peer.sys, 'stdin') as stdin, \
                 mock.patch.object(peer, 'prepare_client_update') as client, \
                 mock.patch.object(peer, 'prepare_skill_updates') as skills:
                self.selector.reset_mock()
                code, _, _ = self.invoke(*argv, standalone=True)
                self.assertNotEqual(code, 0)
                self.selector.assert_not_called()
                run.assert_not_called()
                stdin.read.assert_not_called()
                client.assert_not_called()
                skills.assert_not_called()

    def test_opt_out_helper_preserves_exact_argv_without_config_io(self):
        token = peer.SSH_CONFIG_SELECTION.set(None)
        try:
            self.assertEqual(peer.trusted_ssh_command(['-p', '2222'], 'fixture', 'remote',
                             prefix=('-G',), identity_options=('-oKnownHostsCommand=helper',)),
                             ['ssh', '-G', '-oKnownHostsCommand=helper', '-p', '2222', 'fixture', 'remote'])
        finally:
            peer.SSH_CONFIG_SELECTION.reset(token)
        self.selector.assert_not_called()
        self.config.revalidate.assert_not_called()

    def test_identity_pinning_and_safety_precede_selected_config(self):
        identity = ['-oKnownHostsCommand=pin-helper', '-oStrictHostKeyChecking=yes']
        with self.selected():
            result = peer.trusted_ssh_command(['-p', '2222'], 'fixture', 'remote',
                                             prefix=('-G',), identity_options=identity)
        self.assertEqual(result, ['ssh', '-G', *identity, *SAFETY, '-F', CONFIG,
                                  '-p', '2222', 'fixture', 'remote'])
        self.config.revalidate.assert_called_once_with()

    def test_raw_config_flags_remain_rejected_even_when_trusted(self):
        with self.selected():
            for opts in (['-F', CONFIG], ['-F' + CONFIG], ['-oProxyCommand=arbitrary']):
                with self.subTest(opts=opts), self.assertRaises(peer.CcPeerError):
                    peer.check_ssh_options(opts)

    def test_metadata_identity_and_version_spawns_use_selected_config(self):
        cases = [
            (lambda: peer.ssh_user_metadata('fixture', []), 'user deploy\n'),
            (lambda: peer.ssh_identity_configuration('fixture', []), 'hostname fixture\nport 22\n'),
            (lambda: peer.remote_installed_version('deploy@fixture', [], {}), 'session-peer 1.2.1\n'),
        ]
        for call, stdout in cases:
            with self.subTest(stdout=stdout), self.selected(), \
                 mock.patch.object(peer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout, '')) as run:
                self.config.revalidate.reset_mock()
                call()
                run.assert_called_once()
                self.assert_selected(run.call_args.args[0])
                self.config.revalidate.assert_called_once_with()

    def test_metadata_then_effect_revalidates_and_refuses_changed_config(self):
        self.config.revalidate.side_effect = [None, peer.CcPeerError('Trusted SSH config changed')]
        with self.selected(), mock.patch.object(peer.Path, 'read_text', return_value='source'), \
             mock.patch.object(peer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'user deploy\n', '')) as run, \
             self.assertRaises(peer.CcPeerError):
            peer.run_remote('fixture', ['send', '--to', 'worker', '--b64', 'eA=='], [])
        run.assert_called_once()
        self.assertIn('-G', run.call_args.args[0])
        self.assertEqual(self.config.revalidate.call_count, 2)

    def test_bounded_metadata_spawn_uses_same_selection(self):
        completed = SimpleNamespace(returncode=0, stdout=b'user deploy\n', reason=None,
                                    interrupted=False, stdout_overflow=False,
                                    stderr_overflow=False, cleanup_failed=False)
        budget = (peer.handoff_now() + 3, peer.handoff_now() + 8)
        with self.selected(), mock.patch.object(peer, 'handoff_stream_child', return_value=completed) as child:
            peer.ssh_handoff_configuration('fixture', [], budget)
        child.assert_called_once()
        self.assert_selected(child.call_args.args[0])
        self.assertIn('-G', child.call_args.args[0])
        self.config.revalidate.assert_called_once_with()

    def test_reverse_probe_does_not_inherit_forward_config(self):
        with self.selected(), mock.patch.object(peer, 'is_self_ssh_destination', return_value=False), \
             mock.patch.object(peer.shutil, 'which', return_value='/fixture/ssh'), \
             mock.patch.object(peer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'user deploy\n', '')) as run:
            result = peer.probe_return_route('return-fixture')
            self.assertIs(peer.SSH_CONFIG_SELECTION.get(), self.config)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertNotIn('-F', call.args[0])
            self.assertNotIn(CONFIG, call.args[0])
        self.config.revalidate.assert_not_called()

    def test_bounded_effect_spawn_uses_same_selection_and_identity_options(self):
        payload = {'schemaVersion': 1, 'command': 'send', 'ok': True, 'submitted': True}
        completed = SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode(),
                                    reason=None, interrupted=False, stdout_overflow=False,
                                    stderr_overflow=False, cleanup_failed=False, spawned=True)
        budget = (peer.handoff_now() + 3, peer.handoff_now() + 8)
        with self.selected(), mock.patch.object(peer, 'handoff_stream_child', return_value=completed) as child, \
             mock.patch.object(peer, 'ssh_handoff_request'), \
             mock.patch.object(peer, 'handoff_validate_remote_argv'), \
             mock.patch.object(peer, 'handoff_validate_remote_response', side_effect=lambda result, context: result):
            result = peer._run_remote_handoff_dispatch('deploy@fixture', ['send'], [],
                ['-oKnownHostsCommand=pin-helper'], budget, {'phase': 'effect'})
        self.assertTrue(result['submitted'])
        child.assert_called_once()
        command = child.call_args.args[0]
        self.assert_selected(command)
        self.assertLess(command.index('-oKnownHostsCommand=pin-helper'), command.index('-F'))
        self.assertEqual(child.call_args.args[2:4], budget)

    def test_identity_pin_reaches_actual_dispatch_before_trusted_config(self):
        fingerprint = 'SHA256:' + 'A' * 43
        payload = {'schemaVersion': 1, 'command': 'send', 'ok': True, 'submitted': True}
        outcomes = [subprocess.CompletedProcess([], 0, b'hostname fixture\nport 22\n', b''),
                    subprocess.CompletedProcess([], 0, json.dumps(payload).encode(), b'')]
        proof = {'decision': 'observed', 'fingerprint': fingerprint, 'algorithm': 'ssh-ed25519'}
        with self.selected(), mock.patch.object(peer.subprocess, 'run', side_effect=outcomes) as run, \
             mock.patch.object(peer.tempfile, 'TemporaryDirectory') as temporary, \
             mock.patch.object(peer.Path, 'chmod'), mock.patch.object(peer.os, 'open', return_value=123), \
             mock.patch.object(peer.os, 'fdopen'), mock.patch.object(peer.Path, 'read_text', return_value='source'), \
             mock.patch.object(peer, 'ssh_key_receipt', return_value=proof):
            temporary.return_value.__enter__.return_value = '/fixture/identity'
            result = peer.run_remote_with_identity('deploy@fixture', ['send'], [], expected=fingerprint)
        self.assertTrue(result['submitted'])
        self.assertEqual(result['sshIdentity']['status'], 'verified')
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assert_selected(call.args[0])
        effect = run.call_args.args[0]
        for option in ('-oStrictHostKeyChecking=yes', '-oUserKnownHostsFile=none',
                       '-oGlobalKnownHostsFile=none', '-oHostKeyAlias=session-peer-pinned'):
            self.assertLess(effect.index(option), effect.index('-F'))
        self.assertTrue(any(option.startswith('-oKnownHostsCommand=') for option in effect[:effect.index('-F')]))

    def test_complete_send_evidence_survives_transport_failure(self):
        payload = {'schemaVersion': 1, 'command': 'send', 'ok': False, 'submitted': True,
                   'status': 'queued', 'queueId': 'fixture-queue', 'consumptionConfirmed': False}
        with self.selected(), mock.patch.object(peer.Path, 'read_text', return_value='source'), \
             mock.patch.object(peer.subprocess, 'run', return_value=subprocess.CompletedProcess(
                 [], 255, json.dumps(payload), 'Permission denied')) as run:
            result = peer.run_remote('deploy@fixture', ['send'], [])
        self.assertEqual(result, {**payload, 'sshUser': 'deploy', 'sshUserSource': 'explicit'})
        self.assert_selected(run.call_args.args[0])

    def test_selected_path_is_redacted_from_transport_diagnostics(self):
        calls = [lambda: peer.run_remote('deploy@fixture', ['list'], []),
                 lambda: peer.remote_installed_version('deploy@fixture', [], {}),
                 lambda: peer.push_to_remote('deploy@fixture', [], {})]
        for call in calls:
            with self.subTest(call=call), self.selected(), \
                 mock.patch.object(peer.Path, 'read_text', return_value='source'), \
                 mock.patch.object(peer.Path, 'read_bytes', return_value=b'source'), \
                 mock.patch.object(peer.subprocess, 'run', return_value=subprocess.CompletedProcess(
                     [], 255, b'', ('cannot open ' + CONFIG).encode())), \
                 self.assertRaises(peer.CcPeerError) as caught:
                call()
            self.assertNotIn(CONFIG, str(caught.exception))
            self.assertNotIn(CONFIG, json.dumps(caught.exception.details))

    def test_cli_config_is_not_forwarded_to_remote_arguments(self):
        with mock.patch.object(peer, 'run_remote', return_value={'ok': True, 'target': {'name': 'worker'}}) as remote:
            code, _, _ = self.invoke('send', '--host', 'deploy@fixture', '--to', 'worker',
                                     '-m', 'hello', '--no-from', '--no-reply-to', '--json', *FLAGS)
        self.assertEqual(code, 0)
        args = remote.call_args.args[1]
        for value in (CONFIG, '--ssh-config', '--trust-ssh-config'):
            self.assertNotIn(value, args)

    def test_optional_list_probe_change_preserves_successful_discovery(self):
        listing = {'ok': True, 'sessions': [{'name': 'worker', 'agent': 'claude',
                                           'pid': 7, 'alive': True, 'reachable': True}]}
        self.config.revalidate.side_effect = peer.CcPeerError('Trusted SSH config changed')
        with mock.patch.object(peer.SshTransport, 'execute', return_value=listing), \
             mock.patch.object(peer.subprocess, 'run') as run:
            code, output, _ = self.invoke('list', '--host', 'deploy@fixture', '--json', *FLAGS)
        self.assertEqual(code, 0)
        result = json.loads(output)
        self.assertTrue(result['ok'])
        self.assertEqual(result['sessions'], listing['sessions'])
        self.assertEqual(result['remoteVersionProbe']['status'], 'unknown')
        run.assert_not_called()

    def test_update_fresh_verification_change_preserves_commit_evidence(self):
        self.config.revalidate.side_effect = [None, None, peer.CcPeerError('Trusted SSH config changed')]
        outcomes = [subprocess.CompletedProcess([], 0, 'session-peer 0.1.0\n', ''),
                    subprocess.CompletedProcess([], 0, 'session-peer ' + peer.__version__ + '\n', '')]
        with mock.patch.object(peer.Path, 'read_bytes', return_value=b'fixture source'), \
             mock.patch.object(peer.subprocess, 'run', side_effect=outcomes) as run:
            code, output, _ = self.invoke('update', '--host', 'deploy@fixture', '--json', *FLAGS)
        self.assertEqual(code, 1)
        result = json.loads(output)
        self.assertTrue(result['committed'])
        self.assertEqual(result['commitStatus'], 'committed')
        self.assertEqual(result['verificationStatus'], 'unknown')
        self.assertFalse(result['retryAllowed'])
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assert_selected(call.args[0])
