"""Structured previews consume original facts without transport or submission effects."""
import argparse
import contextlib
import io
import json
import unittest
from unittest import mock

import session_peer as peer

THREAD = '01900000-0000-7000-8000-000000000001'
NONREFLECTED_VALUE = 'PRIVATE-message-path-host-transcript'


class StructuredPreflight(unittest.TestCase):
    def invoke(self, flags=(), *, target='worker'):
        out, err = io.StringIO(), io.StringIO()
        argv = ['send', '--to', target, '--no-from', '--no-reply-to', '--message', NONREFLECTED_VALUE,
                '--dry-run', '--explain-json', '--no-update-notice', *flags]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = peer.main(argv)
        return code, json.loads(out.getvalue()), err.getvalue()

    def test_invalid_combinations_fail_before_input_updates_transport(self):
        for flags in ([], ['--dry-run', '--explain'], ['--dry-run', '--device', 'fixture'],
                      ['--dry-run', '--request-ack'], ['--dry-run', '--preset', 'fixture'],
                      ['--dry-run', '--address', 'fixture'], ['--dry-run', '--output-format', 'text'],
                      ['--dry-run', '--host', 'one', '--host', 'two'],
                      ['--dry-run', '--_handoff-native-context', 'fixture']):
            with self.subTest(flags=flags), mock.patch.object(peer, 'read_message') as read, \
                    mock.patch.object(peer, 'prepare_client_update') as updates, \
                    mock.patch.object(peer, 'cmd_send') as send, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                peer.main(['send', '--to', 'worker', '--explain-json', *flags])
            self.assertEqual(caught.exception.code, 2)
            read.assert_not_called()
            updates.assert_not_called()
            send.assert_not_called()

    def test_classifier_agrees_with_existing_text_and_safe_projection(self):
        args = argparse.Namespace(to='codex:' + THREAD, wake=False)
        cases = [({'dryRun': True, 'ok': True}, 'passed', 'passed for this dry run'),
                 ({'dryRun': True, 'status': 'unknown'}, 'unknown', 'result unknown'),
                 ({'dryRun': True, 'submitted': None}, 'unknown', 'result unknown'),
                 ({'dryRun': True, 'submitted': True}, 'unexpected_submission', 'unexpected submission evidence'),
                 ({'dryRun': False}, 'unexpected_submission', 'unexpected submission evidence'),
                 ({'status': 'queued'}, 'unexpected_submission', 'unexpected submission evidence'),
                 ({'dryRun': True, 'consumptionConfirmed': True}, 'unexpected_submission', 'unexpected submission evidence'),
                 ({'ok': 0, 'dryRun': True}, 'unknown', 'result unknown'),
                 ({'ok': True, 'dryRun': True, 'submitted': 'unknown'}, 'unknown', 'result unknown'),
                 ({'ok': False, 'dryRun': True}, 'not_confirmed', 'not confirmed'),
                 ({'dryRun': True, 'reason': 'sqlite_home_configuration'}, 'not_confirmed', 'not confirmed'),
                 ({'status': 'validated', 'reason': 'sqlite_home_configuration'}, 'not_confirmed', 'not confirmed'),
                 ({}, 'not_confirmed', 'not confirmed')]
        for facts, expected, text in cases:
            facts.update(error=NONREFLECTED_VALUE, codexHome=NONREFLECTED_VALUE, target={'id': NONREFLECTED_VALUE}, body=NONREFLECTED_VALUE)
            before = json.dumps(facts)
            result = peer.structured_delivery_preflight(args, facts)
            self.assertEqual(result['checked']['validation'], expected)
            self.assertIn(text, peer.render_delivery_explanation(args, facts))
            self.assertEqual(result['ok'], expected == 'passed')
            self.assertFalse(result['retryAllowed'])
            self.assertNotIn(NONREFLECTED_VALUE, json.dumps(result))
            self.assertEqual(before, json.dumps(facts))

    def test_claude_actual_dryrun_resolves_once_without_post(self):
        row = {'pid': 42, 'name': 'worker', 'alive': True, 'reachable': True, 'socket': '/fixture.sock'}
        with mock.patch.object(peer, 'discover', return_value=[row]) as discover, \
                mock.patch.object(peer, 'post_to_socket', side_effect=AssertionError('native post')), \
                mock.patch.object(peer.subprocess, 'Popen', side_effect=AssertionError('child')):
            code, result, err = self.invoke()
        self.assertEqual(code, 0)
        self.assertTrue(result['ok'])
        self.assertNotIn(NONREFLECTED_VALUE, json.dumps(result))
        self.assertEqual(err, '')
        discover.assert_called_once_with(include_unreachable=True)

    def test_uri_failure_before_route_resolution_retains_agent_and_not_run(self):
        uri = ('session-peer://v1/reply?agent=codex&session=' + THREAD +
               '&transport=ssh&host=fixture&codexHome=%2Ffixture')
        with mock.patch.object(peer, 'prepare_trusted_ssh_config', side_effect=peer.CcPeerError('private')), \
                mock.patch.object(peer.LocalTransport, 'execute') as local, \
                mock.patch.object(peer, 'SshTransport') as remote, \
                mock.patch.object(peer.subprocess, 'Popen') as child:
            code, value, _ = self.invoke(target=uri)
        self.assertEqual(code, 1)
        self.assertEqual(value['checked']['agent'], 'codex')
        self.assertEqual(value['checked']['validation'], 'not_run')
        self.assertEqual(value['limitations']['submission'], 'not_attempted')
        self.assertEqual(value['operatorActions'], ['resolve_validation_failure_before_send'])
        for action in (local, remote, child):
            action.assert_not_called()

    def test_registered_antigravity_dryrun_never_sends_bridge_request(self):
        registration = {'id': THREAD, 'generation': 'fixture', 'antigravityHome': '/fixture'}
        with mock.patch.object(peer, 'agy_registrations', return_value=[registration]), \
                mock.patch.object(peer, 'agy_rpc') as bridge, \
                mock.patch.object(peer.subprocess, 'Popen') as child:
            code, value, _ = self.invoke(target='antigravity:' + THREAD)
        self.assertEqual(code, 0)
        self.assertTrue(value['ok'])
        self.assertEqual(value['checked']['agent'], 'antigravity')
        bridge.assert_not_called()
        child.assert_not_called()

    def test_ssh_projects_original_claude_facts_before_compatibility_shaping(self):
        for facts, expected in (({'dryRun': False}, 'unexpected_submission'),
                                ({'submitted': None, 'dryRun': True}, 'unknown'),
                                ({}, 'not_confirmed'), ({'dryRun': True}, 'passed')):
            raw = {'ok': True, 'error': NONREFLECTED_VALUE, 'target': {'name': NONREFLECTED_VALUE}, **facts}
            with self.subTest(facts=facts), mock.patch.object(peer, 'tailscale_status', return_value={}), \
                    mock.patch.object(peer, 'SshTransport') as transport, \
                    mock.patch.object(peer.ClaudeAdapter, 'remote_submission', side_effect=AssertionError('shaping')):
                transport.return_value.host = NONREFLECTED_VALUE
                transport.return_value.ssh_opts = []
                transport.return_value.execute.return_value = raw
                code, result, err = self.invoke(['--host', 'fixture'])
            self.assertEqual(result['checked']['validation'], expected)
            self.assertEqual(code, 0 if expected == 'passed' else 1)
            self.assertNotIn(NONREFLECTED_VALUE, json.dumps(result))
            argv = transport.return_value.execute.call_args.args[0]
            self.assertIn('--dry-run', argv)
            self.assertNotIn('--explain-json', argv)
            self.assertEqual(transport.return_value.execute.call_count, 1)
            self.assertEqual(err, '')

    def test_refusal_and_unexpected_exceptions_have_only_safe_facts(self):
        for exc, expected in ((peer.CcPeerError(NONREFLECTED_VALUE, {'reason': 'sqlite_home_configuration', 'path': NONREFLECTED_VALUE}), 'not_confirmed'),
                              (RuntimeError(NONREFLECTED_VALUE), 'unknown')):
            with mock.patch.object(peer.LocalTransport, 'execute', side_effect=exc):
                code, value, _ = self.invoke()
            self.assertEqual(code, 1)
            self.assertEqual(value['checked']['validation'], expected)
            self.assertNotIn(NONREFLECTED_VALUE, json.dumps(value))

    def test_failed_checks_before_destination_are_not_run(self):
        with mock.patch.object(peer, 'check_message', side_effect=peer.CcPeerError(NONREFLECTED_VALUE)):
            code, value, _ = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(value['checked']['validation'], 'not_run')
        self.assertNotIn(NONREFLECTED_VALUE, json.dumps(value))


class CodexStructuredDryrun(unittest.TestCase):
    def setUp(self):
        import os
        from pathlib import Path
        import sqlite3
        import tempfile
        from tests.codex.support import isolate_native_layers
        directory = tempfile.TemporaryDirectory(prefix='codex-preflight-core-', dir=os.environ.get('SESSION_PEER_TEST_TMP'))
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        isolate_native_layers(self, self.root)
        for patcher in (mock.patch.dict(os.environ, {}, clear=True),
                        mock.patch.object(peer, 'known_codex_homes', return_value=[self.root]),
                        mock.patch.object(peer, 'codex_executable', return_value='fixture-codex')):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.rollout = self.root / 'rollout.jsonl'
        self.rollout.write_text('{}\n')
        with contextlib.closing(sqlite3.connect(self.root / 'state_5.sqlite')) as conn:
            conn.execute('CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, updated_at INTEGER, archived INTEGER, rollout_path TEXT)')
            conn.execute('INSERT INTO threads VALUES (?,?,?,?,?,?)', (THREAD, 'fixture', str(self.root), 1, 0, str(self.rollout)))
            conn.commit()

    def invoke(self, wake=False, body=NONREFLECTED_VALUE):
        out = io.StringIO()
        argv = ['send', '--to', 'codex:' + THREAD, '--codex-home', str(self.root),
                '--allow-inactive-codex-home', '--dry-run', '--explain-json', '--no-from',
                '--no-reply-to', '--no-update-notice', '--message', body]
        if wake:
            argv.append('--wake')
        with contextlib.redirect_stdout(out):
            code = peer.main(argv)
        return code, json.loads(out.getvalue())

    def test_real_queue_dryrun_and_wake_preflight_skip_effect_boundaries(self):
        import subprocess
        before = (self.root / 'state_5.sqlite').read_bytes()
        for wake in (False, True):
            with self.subTest(wake=wake), \
                    mock.patch.object(peer.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'codex-cli 0.154.0\n', '')) as probe, \
                    mock.patch.object(peer.subprocess, 'Popen', side_effect=AssertionError('native queue/model')), \
                    mock.patch.object(peer, 'run_codex_wake', side_effect=AssertionError('wake/model')), \
                    mock.patch.object(peer, 'codex_wake_guard', side_effect=AssertionError('budget directory')), \
                    mock.patch.object(peer, 'wake_target_rate_reserve', side_effect=AssertionError('budget')):
                code, result = self.invoke(wake)
            self.assertEqual(code, 0, result)
            self.assertTrue(result['ok'])
            self.assertEqual(result['checked']['wake'], 'validated' if wake else 'not_requested')
            self.assertEqual(probe.call_count, 1 if wake else 0)
            self.assertNotIn(str(self.root), json.dumps(result))
            self.assertEqual((self.root / 'state_5.sqlite').read_bytes(), before)
            self.assertFalse((self.root / 'session-peer' / 'wake-locks').exists())

    def test_storage_refusal_precedes_version_queue_and_wake_budget(self):
        (self.root / 'config.toml').write_text('sqlite_home = "private-relocation"\n')
        with mock.patch.object(peer.subprocess, 'run', side_effect=AssertionError('version/queue')) as run, \
                mock.patch.object(peer.subprocess, 'Popen', side_effect=AssertionError('queue/model')) as child, \
                mock.patch.object(peer, 'wake_target_rate_reserve', side_effect=AssertionError('budget')) as reserve:
            code, result = self.invoke(wake=True)
        self.assertEqual(code, 1)
        self.assertFalse(result['ok'])
        self.assertNotIn('private-relocation', json.dumps(result))
        self.assertEqual(result['refusalReason'], 'sqlite_home_configuration')
        for action in (run, child, reserve):
            action.assert_not_called()

    def test_interrupted_wake_probe_cannot_queue_or_reserve_budget(self):
        with mock.patch.object(peer.subprocess, 'run', side_effect=KeyboardInterrupt), \
                mock.patch.object(peer.subprocess, 'Popen', side_effect=AssertionError('queue/model')) as child, \
                mock.patch.object(peer, 'wake_target_rate_reserve', side_effect=AssertionError('budget')) as reserve:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = peer.main(['send', '--to', 'codex:' + THREAD, '--codex-home', str(self.root),
                    '--allow-inactive-codex-home', '--dry-run', '--explain-json', '--wake', '--no-from',
                    '--no-reply-to', '--message', NONREFLECTED_VALUE])
        self.assertEqual(code, 130)
        self.assertEqual(out.getvalue(), '')
        child.assert_not_called()
        reserve.assert_not_called()
        self.assertFalse((self.root / 'session-peer' / 'wake-locks').exists())

    def test_timed_out_wake_probe_cannot_queue_or_reserve_budget(self):
        import subprocess
        with mock.patch.object(peer.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 5)), \
                mock.patch.object(peer.subprocess, 'Popen', side_effect=AssertionError('queue/model')) as child, \
                mock.patch.object(peer, 'wake_target_rate_reserve', side_effect=AssertionError('budget')) as reserve:
            code, result = self.invoke(wake=True)
        self.assertEqual(code, 1)
        self.assertFalse(result['ok'])
        child.assert_not_called()
        reserve.assert_not_called()
        self.assertFalse((self.root / 'session-peer' / 'wake-locks').exists())

    def test_framed_native_message_byte_budget_still_refuses_before_effects(self):
        with mock.patch.object(peer.subprocess, 'Popen', side_effect=AssertionError('queue/model')) as child, \
                mock.patch.object(peer, 'wake_target_rate_reserve', side_effect=AssertionError('budget')) as reserve:
            code, value = self.invoke(body='界' * 12000)
        self.assertEqual(code, 1)
        self.assertFalse(value['ok'])
        self.assertNotIn('界', json.dumps(value, ensure_ascii=False))
        child.assert_not_called()
        reserve.assert_not_called()
