"""Installed-version metadata must not discard source-streamed discovery."""
import contextlib
import io
import json
import subprocess
import unittest
from unittest import mock

import session_peer as peer


class ListVersionProbe(unittest.TestCase):
    def setUp(self):
        self.listing = {
            'ok': True,
            'sessions': [{'agent': 'claude', 'pid': 7, 'name': 'worker', 'cwd': '/project',
                          'alive': True, 'reachable': True, 'status': 'idle'}],
            'discovery': {'claude': {'status': 'ok', 'sessionCount': 1}},
            'codexHome': '/configured/home',
            'sshUser': 'deploy', 'sshUserSource': 'explicit',
        }
        for patcher in (
            mock.patch.object(peer, 'tailscale_status', return_value={}),
            mock.patch.object(peer, 'resolve_ssh_destination',
                              side_effect=lambda host, status: host + '.example.test'),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(peer.SshTransport, 'execute', return_value=self.listing)
        self.primary = patcher.start()
        self.addCleanup(patcher.stop)

    def invoke(self, *options):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = peer.main(['list', '--no-update-notice', *options])
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_discovery_retained(self, result, host='deploy@fixture'):
        self.assertEqual(result['host'], host + '.example.test')
        self.assertEqual(result['sshHost'], host)
        for key in ('sessions', 'discovery', 'sshUser', 'sshUserSource', 'codexHome'):
            self.assertEqual(result[key], self.listing[key])
        self.assertEqual(result['version'], peer.__version__)

    def test_real_secondary_probe_failures_preserve_successful_discovery(self):
        outcomes = (
            ('timeout', subprocess.TimeoutExpired(['ssh', 'private-process-argument'], 30)),
            ('invalid_response', subprocess.CompletedProcess([], 0, b'not a version\n', b'')),
            ('invalid_response', subprocess.CompletedProcess([], 0, b'\xff', b'')),
            ('transport_failed', subprocess.CompletedProcess([], 255, b'', b'Connection closed')),
            ('transport_failed', OSError('private-process-argument\x1b[2J')),
        )
        for reason, outcome in outcomes:
            with self.subTest(reason=reason, outcome=type(outcome).__name__), \
                 mock.patch.object(peer.subprocess, 'run', side_effect=[outcome]) as run:
                code, output, error = self.invoke('--host', 'deploy@fixture', '--json')
            result = json.loads(output)
            self.assertEqual(code, 0)
            self.assertTrue(result['ok'])
            self.assert_discovery_retained(result)
            self.assertEqual(result['remoteVersionProbe'], {'status': 'unknown', 'reason': reason})
            self.assertNotIn('remoteVersion', result)
            self.assertNotIn('error', result)
            self.assertNotIn('private-process-argument', output)
            self.assertEqual(error, '')
            run.assert_called_once()
            self.assertIn('deploy@fixture', run.call_args.args[0])

    def test_probe_diagnostics_are_bounded_in_json_and_human_output(self):
        private = 'private-process-argument\x1b[2J\nsecret-host'
        failures = (
            (peer.CcPeerError(private, {'sshFailure': private, 'sshUser': private,
                                       'process': private}), 'invalid_response'),
            (RuntimeError(private), 'probe_failed'),
        )
        for failure, reason in failures:
            for as_json in (False, True):
                with self.subTest(reason=reason, json=as_json), \
                     mock.patch.object(peer, 'remote_installed_version', side_effect=failure):
                    code, output, error = self.invoke('--host', 'deploy@fixture',
                                                      *(['--json'] if as_json else []))
                self.assertEqual(code, 0)
                self.assertEqual(error, '')
                self.assertNotIn('private-process-argument', output)
                self.assertNotIn('secret-host', output)
                self.assertNotIn('\x1b', output)
                if as_json:
                    result = json.loads(output)
                    self.assert_discovery_retained(result)
                    self.assertEqual(result['remoteVersionProbe'],
                                     {'status': 'unknown', 'reason': reason})
                else:
                    self.assertIn('Installed session-peer version unknown', output)
                    self.assertIn(reason, output)
                    self.assertIn('worker', output)

    def test_normal_and_uninstalled_remote_output_are_unchanged(self):
        for version in (peer.__version__, '0.9.0', None):
            with self.subTest(version=version), \
                 mock.patch.object(peer, 'remote_installed_version', return_value=version):
                code, output, error = self.invoke('--host', 'deploy@fixture', '--json')
            expected = peer.json_result('list', {
                'host': 'deploy@fixture.example.test', 'sshHost': 'deploy@fixture',
                **self.listing, 'version': peer.__version__,
                **({'remoteVersion': version} if version else {}),
            })
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output), expected)
            self.assertEqual(error, '')

    def test_primary_partial_failure_is_not_overwritten_by_probe_failure(self):
        partial = {**self.listing, 'ok': False, 'error': 'Discovery failed for: codex'}
        self.primary.return_value = partial
        with mock.patch.object(peer, 'remote_installed_version',
                               side_effect=peer.CcPeerError('probe failed', {'sshFailure': 'timeout'})):
            code, output, _ = self.invoke('--host', 'deploy@fixture', '--json')
        result = json.loads(output)
        self.assertEqual(code, peer.EXIT_ERROR)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], partial['error'])
        self.assert_discovery_retained(result)
        self.assertEqual(result['remoteVersionProbe']['reason'], 'timeout')

    def test_multiple_successful_hosts_remain_successful_when_probes_fail(self):
        with mock.patch.object(peer, 'remote_installed_version',
                               side_effect=peer.CcPeerError('probe failed', {'sshFailure': 'timeout'})) as probe:
            code, output, _ = self.invoke('--host', 'one', '--host', 'two', '--json')
        results = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(len(results), 2)
        for host, result in zip(('one', 'two'), results):
            self.assertTrue(result['ok'])
            self.assert_discovery_retained(result, host)
            self.assertEqual(result['remoteVersionProbe']['reason'], 'timeout')

    def test_multiple_hosts_preserve_primary_failure_and_continue(self):
        failure = peer.CcPeerError('primary transport failed', {'sshFailure': 'transport_failed'})
        partial = {**self.listing, 'ok': False, 'error': 'Discovery failed for: codex'}
        self.primary.side_effect = [failure, self.listing, partial]
        with mock.patch.object(peer, 'remote_installed_version', side_effect=[
            peer.CcPeerError('secondary timeout', {'sshFailure': 'timeout'}), None,
        ]) as probe:
            code, output, _ = self.invoke('--host', 'bad', '--host', 'good',
                                          '--host', 'partial', '--json')
        results = json.loads(output)
        self.assertEqual(code, peer.EXIT_ERROR)
        self.assertEqual([result['ok'] for result in results], [False, True, False])
        self.assertEqual([result['sshHost'] for result in results], ['bad', 'good', 'partial'])
        self.assertEqual(self.primary.call_count, 3)
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(results[0]['error'], 'primary transport failed')
        self.assertEqual(results[0]['sshFailure'], 'transport_failed')
        self.assertNotIn('remoteVersionProbe', results[0])
        self.assert_discovery_retained(results[1], 'good')
        self.assertEqual(results[2]['sessions'], self.listing['sessions'])
        self.assertEqual(results[2]['error'], partial['error'])
        self.assertNotIn('remoteVersionProbe', results[2])
