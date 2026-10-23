"""Offline runtime preference integration; no user state, network or installers."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import unittest
from unittest import mock

import session_peer


class RuntimeNoticeDismissal(unittest.TestCase):
    def setUp(self):
        self.peer = session_peer  # Missing generated code must fail, not fall back.
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(self.peer, '__version__', '1.0.0'))
        self.stack.enter_context(mock.patch.object(self.peer, '_CLIENT_UPDATE_NOTICE', None))
        self.stack.enter_context(mock.patch.object(self.peer, '_SKILL_UPDATE_NOTICES', []))
        self.read = self.stack.enter_context(mock.patch.object(self.peer, 'read_runtime_notice_preference',
            return_value={'status': 'clear', 'dismissedVersion': None}))
        self.write = self.stack.enter_context(mock.patch.object(self.peer, 'write_runtime_notice_preference',
            return_value={'status': 'set', 'dismissedVersion': '2.0.0', 'changed': True}))
        self.latest = self.stack.enter_context(mock.patch.object(self.peer, 'latest_release',
            side_effect=AssertionError('unexpected network')))
        self.cache_write = self.stack.enter_context(mock.patch.object(self.peer, 'write_update_cache'))
        self.distribution = self.stack.enter_context(mock.patch.object(self.peer, 'installed_as_distribution', return_value=False))
        self.stack.enter_context(mock.patch.object(self.peer, 'installed_skills', return_value=[]))
        self.stack.enter_context(mock.patch.dict(os.environ, {self.peer.UPDATE_NOTICE_ENV: ''}))

    def args(self, **changes):
        return argparse.Namespace(command='send', no_update_notice=False, host=[], **changes)

    def cache(self, latest='2.0.0'):
        return mock.patch.object(self.peer, 'read_update_cache', return_value={
            'status': 'fresh', 'latest': latest, 'checkedAt': 1000})

    def main(self, argv, *, ambient=False):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            if ambient:
                with mock.patch.object(self.peer.sys, 'argv', ['session-peer', *argv]):
                    result = self.peer.main()
            else:
                result = self.peer.main(argv)
        return result, output.getvalue()

    def test_exact_dismissal_later_release_and_clear_are_runtime_only(self):
        self.read.return_value = {'status': 'set', 'dismissedVersion': '2.0.0'}
        with self.cache():
            self.assertIsNone(self.peer.prepare_client_update(self.args(), now=1001))
        with self.cache('2.0.1'):
            self.assertEqual(self.peer.prepare_client_update(self.args(), now=1001)['latest'], '2.0.1')
        self.read.return_value = {'status': 'clear', 'dismissedVersion': None}
        with self.cache():
            self.assertEqual(self.peer.prepare_client_update(self.args(), now=1001)['latest'], '2.0.0')
        self.assertEqual(self.read.call_count, 3)
        self.latest.assert_not_called()
        self.cache_write.assert_not_called()

    def test_invalid_preference_or_read_failure_does_not_hide_availability(self):
        for preference in ({'status': 'invalid', 'dismissedVersion': None},
                           {'status': 'unsupported', 'dismissedVersion': None}):
            self.read.return_value = preference
            with self.cache():
                self.assertEqual(self.peer.prepare_client_update(self.args(), now=1001)['status'], 'available')
        self.read.side_effect = OSError('fixture unreadable')
        with self.cache():
            self.assertEqual(self.peer.prepare_client_update(self.args(), now=1001)['status'], 'available')

    def test_global_opt_out_and_irrelevant_candidate_do_not_read_preference(self):
        with self.cache(), mock.patch.dict(os.environ, {self.peer.UPDATE_NOTICE_ENV: 'true'}):
            self.assertIsNone(self.peer.prepare_client_update(self.args(), now=1001))
        with self.cache():
            args = self.args()
            args.no_update_notice = True
            self.assertIsNone(self.peer.prepare_client_update(args, now=1001))
        with self.cache('1.0.0'):
            self.assertIsNone(self.peer.prepare_client_update(self.args(), now=1001))
        self.read.assert_not_called()

    def test_stale_cache_preserves_existing_refresh_without_preference_read(self):
        launch = mock.Mock()
        with mock.patch.object(self.peer, 'read_update_cache', return_value={'status': 'expired'}):
            self.assertIsNone(self.peer.prepare_client_update(self.args(), launcher=launch))
        launch.assert_called_once_with()
        self.read.assert_not_called()
        self.latest.assert_not_called()

    def test_preference_operations_are_offline_and_precede_package_ownership(self):
        for option, selected, state in (
                (['--dismiss-runtime-notice', 'v2.0.0'], '2.0.0', 'set'),
                (['--clear-runtime-notice-dismissal'], None, 'clear')):
            self.write.return_value = {'status': state, 'dismissedVersion': selected, 'changed': True}
            with mock.patch.object(self.peer.subprocess, 'Popen', side_effect=AssertionError('unexpected launch')), \
                    mock.patch.object(self.peer, 'push_to_remote', side_effect=AssertionError('unexpected SSH')), \
                    mock.patch.object(self.peer, 'verified_release_download', side_effect=AssertionError('unexpected install')):
                code, output = self.main(['update', *option, '--json'], ambient=True)
            result = json.loads(output)
            self.assertEqual(code, 0)
            self.assertEqual(result['operation'], 'runtime_notice_preference')
            self.assertEqual(result['category'], 'runtime')
            self.assertFalse(result['updated'])
            self.assertEqual(result['dismissedVersion'], selected)
            self.assertNotIn('latest', result)
            self.write.assert_called_with(selected)
        self.distribution.assert_not_called()
        self.latest.assert_not_called()
        self.read.assert_not_called()
        self.cache_write.assert_not_called()

    def test_conflicting_routes_or_versions_reject_before_advisory_preparation(self):
        invalid = [
            ['--dismiss-runtime-notice', '2.0.0', '--check'],
            ['--dismiss-runtime-notice', '2.0.0', '--clear-runtime-notice-dismissal'],
            ['--dismiss-runtime-notice', '2.0.0', '--host', 'elsewhere'],
            ['--clear-runtime-notice-dismissal', '--ssh-opt=-p'],
            ['--clear-runtime-notice-dismissal', '--ssh-identity'],
            ['--clear-runtime-notice-dismissal', '--require-ssh-host-key', 'SHA256:' + 'a' * 43],
        ]
        invalid += [['--dismiss-runtime-notice', value] for value in ('1.2', '1.2.3rc1', '01.2.3', '１.2.3')]
        for options in invalid:
            with self.subTest(options=options), \
                    mock.patch.object(self.peer, 'prepare_client_update') as ambient, \
                    mock.patch.object(self.peer, 'prepare_skill_updates') as skill, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.main(['update', *options], ambient=True)
            ambient.assert_not_called()
            skill.assert_not_called()
        self.write.assert_not_called()
        self.latest.assert_not_called()

    def test_future_ssh_configuration_fields_are_rejected_before_advisory(self):
        parsed = self.peer.build_parser().parse_args(['update', '--clear-runtime-notice-dismissal'])
        parsed.ssh_config_file = '/fixture/config'
        with mock.patch.object(self.peer, 'build_parser') as parser, \
                mock.patch.object(self.peer, 'prepare_client_update') as ambient, \
                mock.patch.object(self.peer, 'prepare_skill_updates') as skill:
            parser.return_value.parse_args.return_value = parsed
            parser.return_value.error.side_effect = SystemExit(2)
            with self.assertRaises(SystemExit):
                self.main(['update', '--clear-runtime-notice-dismissal'], ambient=True)
        ambient.assert_not_called()
        skill.assert_not_called()
        self.write.assert_not_called()

    def test_explicit_checks_remain_truthful_for_managed_and_standalone(self):
        self.read.return_value = {'status': 'set', 'dismissedVersion': '2.0.0'}
        self.latest.side_effect = None
        self.latest.return_value = ('v2.0.0', 'offline-fixture-url')
        for managed in (False, True):
            self.distribution.return_value = managed
            code, output = self.main(['update', '--check', '--json', '--no-update-notice'])
            result = json.loads(output)
            self.assertEqual(code, 0)
            self.assertEqual(result['latest'], 'v2.0.0')
            self.assertTrue(result['outdated'])
            self.assertTrue(result['runtimeNoticeDismissed'])
            self.assertEqual(result['runtimeNoticePreference']['dismissedVersion'], '2.0.0')
            if managed:
                self.assertEqual(result['managedBy'], 'package-manager')
            code, human = self.main(['update', '--check', '--no-update-notice'])
            self.assertEqual(code, 0)
            self.assertIn('v2.0.0 available', human)
            self.assertIn('Automatic notice for this available release is dismissed.', human)
            self.assertIn('--clear-runtime-notice-dismissal', human)

    def test_human_check_distinguishes_nonmatching_or_current_dismissal(self):
        for latest, selected in (('2.0.0', '1.5.0'), ('1.0.0', '1.0.0')):
            self.read.return_value = {'status': 'set', 'dismissedVersion': selected}
            with mock.patch.object(self.peer, 'latest_release', return_value=(latest, 'offline-fixture-url')):
                code, output = self.main(['update', '--check'])
            self.assertEqual(code, 0)
            self.assertIn('Stored runtime notice dismissal does not hide this availability result.', output)
            self.assertIn('Selected version: ' + selected, output)
            self.assertNotIn('this available release is dismissed', output)

    def test_explicit_check_exposes_invalid_preference_and_never_marks_current_dismissed(self):
        self.latest.side_effect = None
        self.latest.return_value = ('v2.0.0', 'offline-fixture-url')
        self.read.return_value = {'status': 'invalid', 'dismissedVersion': None,
            'reason': 'runtime_notice_preference_schema'}
        code, output = self.main(['update', '--check', '--json'])
        result = json.loads(output)
        self.assertEqual(code, 0)
        self.assertTrue(result['outdated'])
        self.assertFalse(result['runtimeNoticeDismissed'])
        self.assertEqual(result['runtimeNoticePreference']['status'], 'invalid')
        self.read.return_value = {'status': 'set', 'dismissedVersion': '1.0.0'}
        self.latest.return_value = ('v1.0.0', 'offline-fixture-url')
        code, output = self.main(['update', '--check', '--json'])
        result = json.loads(output)
        self.assertEqual(code, 0)
        self.assertFalse(result['outdated'])
        self.assertFalse(result['runtimeNoticeDismissed'])

    def test_explicit_preference_operation_still_runs_with_global_opt_out(self):
        with mock.patch.dict(os.environ, {self.peer.UPDATE_NOTICE_ENV: '1'}):
            code, output = self.main(['update', '--dismiss-runtime-notice', '2.0.0',
                '--no-update-notice', '--json'], ambient=True)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['dismissedVersion'], '2.0.0')
        self.write.assert_called_once_with('2.0.0')
        self.read.assert_not_called()

    def test_refused_preference_write_preserves_normal_error_shape_and_no_update(self):
        self.write.side_effect = self.peer.CcPeerError('Runtime notice preference refused',
            {'reason': 'runtime_notice_preference_unsafe', 'updated': False})
        code, output = self.main(['update', '--dismiss-runtime-notice', '2.0.0', '--json'], ambient=True)
        result = json.loads(output)
        self.assertEqual(code, self.peer.EXIT_ERROR)
        self.assertFalse(result['updated'])
        self.assertEqual(result['reason'], 'runtime_notice_preference_unsafe')
        self.assertEqual(result['command'], 'update')
        self.latest.assert_not_called()
        self.distribution.assert_not_called()

    def test_multi_host_reads_once_and_remote_calls_keep_notice_opt_out(self):
        self.read.return_value = {'status': 'set', 'dismissedVersion': '2.0.0'}
        with self.cache(), mock.patch.object(self.peer, 'tailscale_status', return_value={}), \
                mock.patch.object(self.peer, 'resolve_ssh_destination', side_effect=lambda host, status: host), \
                mock.patch.object(self.peer, 'tailscale_ssh_options', return_value=[]), \
                mock.patch.object(self.peer, 'ssh_user_metadata', return_value={}), \
                mock.patch.object(self.peer, 'run_remote', return_value={'sessions': []}) as remote, \
                mock.patch.object(self.peer, 'remote_installed_version', return_value='1.0.0'):
            code, output = self.main(['list', '--host', 'one', '--host', 'two', '--json'], ambient=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.read.call_count, 1)
        self.assertEqual(remote.call_count, 2)
        self.assertTrue(all('--no-update-notice' in call.args[1] for call in remote.call_args_list))
        self.assertTrue(all('clientUpdate' not in item for item in json.loads(output)))

    def test_remote_check_keeps_remote_version_comparison_without_preference_read(self):
        with mock.patch.object(self.peer, 'tailscale_status', return_value={}), \
                mock.patch.object(self.peer, 'resolve_ssh_destination', side_effect=lambda host, status: host), \
                mock.patch.object(self.peer, 'tailscale_ssh_options', return_value=[]), \
                mock.patch.object(self.peer, 'ssh_user_metadata', return_value={}), \
                mock.patch.object(self.peer, 'remote_installed_version', return_value='0.9.0'):
            code, output = self.main(['update', '--check', '--host', 'one', '--json'])
        result = json.loads(output)
        self.assertEqual(code, 0)
        self.assertTrue(result['outdated'])
        self.assertEqual(result['remoteVersion'], '0.9.0')
        self.assertNotIn('runtimeNoticePreference', result)
        self.read.assert_not_called()

    def test_skill_notices_and_primary_command_result_are_unchanged(self):
        skill = {'location': 'agents', 'current': '1.0.0', 'latest': '2.0.0', 'command': 'owning-manager'}
        self.read.side_effect = OSError('fixture preference unavailable')
        with self.cache(), mock.patch.object(self.peer, 'prepare_skill_updates', return_value=[skill]), \
                mock.patch.object(self.peer, 'collect_listing', return_value={'ok': True, 'sessions': []}), \
                mock.patch.object(self.peer, 'render_listing', return_value='fixture listing'):
            code, output = self.main(['list', '--json'], ambient=True)
        result = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(result['sessions'], [])
        self.assertIn('clientUpdate', result)
        self.assertEqual(result['skillUpdates'], [skill])

    def test_real_cli_remote_check_reads_only_calling_client_notice_preference(self):
        # The client advisory is independent of the remote result: no per-host
        # preference read or remote-version suppression is introduced.
        self.read.return_value = {'status': 'set', 'dismissedVersion': '2.0.0'}
        with self.cache(), mock.patch.object(self.peer, 'tailscale_status', return_value={}), \
                mock.patch.object(self.peer, 'resolve_ssh_destination', side_effect=lambda host, status: host), \
                mock.patch.object(self.peer, 'tailscale_ssh_options', return_value=[]), \
                mock.patch.object(self.peer, 'ssh_user_metadata', return_value={}), \
                mock.patch.object(self.peer, 'remote_installed_version', return_value='0.9.0') as remote:
            code, output = self.main(['update', '--check', '--host', 'one', '--host', 'two', '--json'], ambient=True)
        result = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(len(result), 2)
        self.read.assert_called_once_with()
        self.assertEqual(remote.call_count, 2)
        for item in result:
            self.assertTrue(item['outdated'])
            self.assertEqual(item['remoteVersion'], '0.9.0')
            self.assertNotIn('runtimeNoticePreference', item)
            self.assertNotIn('clientUpdate', item)
