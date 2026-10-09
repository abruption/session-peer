"""Private fixtures/fake control and receiver only; no hosted service/model sends."""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

if sys.version_info < (3, 11) or os.name != 'posix':
    raise unittest.SkipTest('Relay setup requires Unix Python 3.11+')
try:
    from session_peer_relay import setup
except ImportError:
    raise unittest.SkipTest('Relay dependencies absent')
import session_peer as core
from session_peer_relay.identity import private_write
from session_peer_relay.store import Store, Rejected

THREAD = '01900000-0000-7000-8000-000000000001'
PEER = 'a' * 64


class Setup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='codex-setup-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base/'state'
        self.defaults = ['setup', '--mode', 'relay', '--state', str(self.root)]

    def args(self, *tail):
        return core.build_parser().parse_args(self.defaults+list(tail))

    def call(self, *tail):
        return setup.run(self.args(*tail))

    def initialize(self):
        result = self.call('--action', 'init', '--apply')
        self.assertTrue(result['ok'], result)
        return result

    def login_state(self, expired=False):
        private_write(self.root/'login.json', json.dumps({'server': 'https://control.example',
            'token': 'fixture-token-never-disclosed', 'expiresAt': time.time()+(-10 if expired else 3600)}))

    def rows(self):
        return {'ok': True, 'sessions': [{'agent': 'claude', 'pid': 321, 'name': 'fixture', 'startedAt': 1}], 'discovery': {}}

    def policy_args(self):
        return ('--action', 'policy', '--target', '321', '--peer', PEER)

    def test_clean_plan_and_targets_never_construct_store_or_write_state(self):
        with mock.patch.object(setup, 'Store', side_effect=AssertionError('inventory mutation')), \
                mock.patch.object(core, 'collect_listing', return_value=self.rows()):
            self.assertTrue(self.call()['ok'])
            self.assertTrue(self.call('--action', 'targets')['metadataOnly'])
        self.assertFalse(self.root.exists())

    def test_existing_inventory_does_not_create_wal_keys_or_modify_files(self):
        self.initialize()
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with mock.patch.object(setup, 'Store', side_effect=AssertionError('inventory mutation')):
            self.assertTrue(self.call()['ok'])
        after = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.assertEqual(before, after)

    def test_each_mutation_requires_apply_and_init_never_replaces_keys(self):
        self.assertEqual(self.call('--action', 'init')['reason'], 'setup_explicit_apply_required')
        self.assertFalse(self.root.exists())
        initial = self.initialize()
        key = (self.root/'identity.key').read_bytes()
        self.assertEqual(self.initialize()['device'], initial['device'])
        self.assertEqual((self.root/'identity.key').read_bytes(), key)
        for p in self.root.iterdir():
            if p.is_file():
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)

    def test_partial_identity_and_unsafe_or_symlink_state_are_not_initialized(self):
        self.root.mkdir(mode=0o700)
        private_write(self.root/'identity.key', 'incomplete fixture')
        self.assertFalse(self.call('--action', 'init', '--apply')['ok'])
        self.assertFalse((self.root/'identity.pem').exists())
        self.root.chmod(0o755)
        self.assertFalse(self.call()['ok'])
        link = self.base/'link'
        link.symlink_to(self.root, target_is_directory=True)
        args = self.args()
        args.state = str(link)
        self.assertFalse(setup.run(args)['ok'])

    def test_preexisting_empty_directory_is_not_claimed_as_preserved_identity(self):
        self.root.mkdir(mode=0o700)
        self.assertFalse(self.initialize()['preservedExistingIdentity'])
        self.assertTrue(self.initialize()['preservedExistingIdentity'])

    def test_missing_database_or_rotated_key_requires_manual_recovery_without_init(self):
        self.initialize()
        old_key = (self.root/'identity.key').read_bytes()
        (self.root/'device.sqlite').unlink()
        with mock.patch.object(setup, 'Store') as store:
            result = self.call('--action', 'init', '--apply')
        self.assertEqual(result['reason'], 'setup_state_incomplete_manual_recovery_required')
        store.assert_not_called()
        self.assertFalse((self.root/'device.sqlite').exists())
        self.assertEqual((self.root/'identity.key').read_bytes(), old_key)
        # Separate state with current WAL metadata pointing to a lost rotated key.
        self.root = self.base/'rotated'
        self.defaults = ['setup', '--mode', 'relay', '--state', str(self.root)]
        self.initialize()
        relative = 'keys/01900000-0000-7000-8000-000000000001'
        state = Store(self.root)
        try:
            state.db.execute('INSERT OR REPLACE INTO metadata VALUES("identity_directory",?)', (relative,))
        finally:
            state.close()
        with mock.patch.object(setup, 'Store') as store:
            result = self.call('--action', 'init', '--apply')
        self.assertEqual(result['reason'], 'setup_state_incomplete_manual_recovery_required')
        store.assert_not_called()
        self.assertFalse((self.root/relative).exists())

    def test_all_identity_files_lost_with_retained_journal_never_creates_new_state(self):
        self.initialize()
        original = (self.root/'setup.json').read_bytes()
        for name in ('identity.pem', 'identity.key', 'device.sqlite'):
            (self.root/name).unlink()
        with mock.patch.object(setup, 'Store') as store:
            result = self.call('--action', 'init', '--apply')
        self.assertEqual(result['reason'], 'setup_state_incomplete_manual_recovery_required')
        store.assert_not_called()
        self.assertEqual((self.root/'setup.json').read_bytes(), original)
        self.assertFalse((self.root/'identity.key').exists())
        self.assertFalse((self.root/'device.sqlite').exists())

    def test_headless_login_uses_existing_api_and_keeps_tokens_out_of_output(self):
        self.initialize()
        async def login(store, origin, no_browser):
            self.assertEqual(origin, 'https://control.example')
            self.assertTrue(no_browser)
            self.login_state()
            return {'ok': True, 'loggedIn': True, 'device': store.device}
        with mock.patch.object(setup.control, 'login', side_effect=login):
            result = self.call('--action', 'login', '--server', 'https://control.example', '--no-browser', '--apply')
        self.assertTrue(result['loggedIn'])
        self.assertNotIn('fixture-token', json.dumps(result))
        self.assertNotIn('fixture-token', (self.root/'setup.json').read_text())

    def test_expired_login_refuses_enrollment_before_control_mutation(self):
        self.initialize()
        self.login_state(expired=True)
        with mock.patch.object(setup.control, 'enroll') as enroll:
            result = self.call('--action', 'enroll', '--name', 'fixture', '--apply')
        self.assertEqual(result['reason'], 'login_expired')
        enroll.assert_not_called()

    def test_unknown_enrollment_retains_uuid_payload_and_reconciles_original(self):
        self.initialize()
        self.login_state()
        operation_ids = []
        def enroll(store, name, operation, **prepared):
            operation_ids.append(operation)
            journal = json.loads((self.root/'setup.json').read_text())
            self.assertEqual(journal['enrollment']['operationId'], operation)
            self.assertEqual(journal['enrollment']['state'], 'unknown')
            self.assertEqual(prepared['prepared_payload'], journal['enrollment']['payload'])
            if len(operation_ids) == 1:
                raise Rejected('timeout')
            return {'ok': True, 'operationId': operation, 'principal': store.device,
                    'keyFingerprint': store.key_id, 'keyGeneration': store.generation, 'committed': True}
        with mock.patch.object(setup.control, 'enroll', side_effect=enroll):
            self.assertFalse(self.call('--action', 'enroll', '--name', 'fixture', '--apply')['ok'])
            self.assertEqual(self.call('--action', 'enroll', '--name', 'changed', '--apply')['reason'], 'setup_enrollment_intent_changed')
            self.assertTrue(self.call('--action', 'enroll', '--name', 'fixture', '--apply')['committed'])
            self.assertTrue(self.call('--action', 'enroll', '--name', 'fixture', '--apply')['reconciled'])
        self.assertEqual(operation_ids[0], operation_ids[1])
        self.assertEqual(len(operation_ids), 2)

    def test_actual_enroll_primitive_recovers_committed_receipt_after_lost_response(self):
        self.initialize()
        self.login_state()
        saved = {}
        mutations = []
        def call(server, path, body=None, token=None):
            if path == '/api/relay/challenge':
                if 'receipt' in saved:
                    self.assertEqual(body['payload'], saved['payload'])
                    raise Rejected('operation_already_committed')
                saved['payload'] = body['payload']
                return {'challengeId': 'fixture-challenge', 'proofMessage': 'session-peer-control-v1:fixture'}
            if path == '/api/relay/devices':
                mutations.append(body['operationId'])
                saved['receipt'] = {'operationId': body['operationId'], 'principal': body['principal'],
                    'keyFingerprint': setup.fingerprint(body['certificatePEM']),
                    'keyGeneration': body['keyGeneration'], 'committed': True}
                raise Rejected('timeout')
            if path.startswith('/api/relay/operations/'):
                self.assertEqual(path.rsplit('/', 1)[1], saved['receipt']['operationId'])
                return saved['receipt']
            raise AssertionError('unexpected API path')
        with mock.patch.object(setup.control, 'call', side_effect=call):
            self.assertFalse(self.call('--action', 'enroll', '--name', 'fixture', '--apply')['ok'])
            self.assertTrue(self.call('--action', 'enroll', '--name', 'fixture', '--apply')['committed'])
        self.assertEqual(len(mutations), 1)

    def test_cancel_does_not_cancel_or_replace_original_enrollment(self):
        self.initialize()
        self.login_state()
        with mock.patch.object(setup.control, 'enroll', side_effect=Rejected('timeout')):
            self.call('--action', 'enroll', '--name', 'fixture', '--apply')
        before = json.loads((self.root/'setup.json').read_text())['enrollment']
        result = self.call('--action', 'cancel', '--apply')
        self.assertFalse(result['operationCancelled'])
        self.assertEqual(before, json.loads((self.root/'setup.json').read_text())['enrollment'])

    def test_same_der_changed_pem_text_refuses_before_network_and_retains_payload(self):
        self.initialize()
        self.login_state()
        with mock.patch.object(setup.control, 'enroll', side_effect=Rejected('timeout')):
            self.call('--action', 'enroll', '--name', 'fixture', '--apply')
        saved = json.loads((self.root/'setup.json').read_text())['enrollment']
        certificate = (self.root/'identity.pem').read_text()
        private_write(self.root/'identity.pem', certificate+'\n')
        self.assertEqual(setup.fingerprint(certificate), setup.fingerprint(certificate+'\n'))
        with mock.patch.object(setup.control, 'enroll') as enroll, \
                mock.patch.object(setup.control, 'call') as call:
            result = self.call('--action', 'enroll', '--name', 'fixture', '--apply')
        self.assertEqual(result['reason'], 'setup_enrollment_payload_changed')
        enroll.assert_not_called()
        call.assert_not_called()
        self.assertEqual(json.loads((self.root/'setup.json').read_text())['enrollment'], saved)

    def test_actual_request_uses_original_payload_and_origin_after_file_changes(self):
        self.initialize()
        self.login_state()
        original_enroll = setup.control.enroll
        seen = []
        def mutate_then_enroll(store, name, operation, **prepared):
            private_write(self.root/'identity.pem', store.cert+'\n')
            private_write(self.root/'login.json', json.dumps({'server': 'https://changed.example',
                'token': 'changed-fixture-token', 'expiresAt': time.time()+3600}))
            return original_enroll(store, name, operation, **prepared)
        def call(server, path, body=None, token=None):
            self.assertEqual(server, 'https://control.example')
            self.assertEqual(token, 'fixture-token-never-disclosed')
            saved = json.loads((self.root/'setup.json').read_text())['enrollment']['payload']
            if path == '/api/relay/challenge':
                self.assertEqual(body['payload'], saved)
                seen.append(dict(body['payload']))
                return {'challengeId': 'fixture', 'proofMessage': 'session-peer-control-v1:fixture'}
            self.assertEqual({key: body[key] for key in saved}, saved)
            return {'operationId': body['operationId'], 'principal': body['principal'],
                    'keyFingerprint': setup.fingerprint(body['certificatePEM']),
                    'keyGeneration': body['keyGeneration'], 'committed': True}
        with mock.patch.object(setup.control, 'enroll', side_effect=mutate_then_enroll), \
                mock.patch.object(setup.control, 'call', side_effect=call):
            self.assertTrue(self.call('--action', 'enroll', '--name', 'fixture', '--apply')['ok'])
        self.assertEqual(len(seen), 1)

    def test_policy_preview_then_exclusive_apply_least_privilege_no_overwrite(self):
        self.initialize()
        with mock.patch.object(core, 'collect_listing', return_value=self.rows()), \
                mock.patch.object(core.LocalTransport, 'execute', return_value={'ok': True}) as native:
            preview = self.call(*self.policy_args())
            self.assertEqual(preview['policyPreview']['peers'][PEER]['capabilities'], ['list'])
            self.assertFalse((self.root/'receiver-policy.json').exists())
            applied = self.call(*self.policy_args(), '--apply')
            self.assertTrue(applied['changed'])
            unchanged = self.call(*self.policy_args(), '--apply')
            self.assertFalse(unchanged['changed'])
            original = (self.root/'receiver-policy.json').read_bytes()
            denied = self.call(*self.policy_args(), '--apply', '--capability', 'send')
            self.assertEqual(denied['reason'], 'setup_existing_policy_preserved')
            self.assertEqual((self.root/'receiver-policy.json').read_bytes(), original)
        self.assertTrue(all(call.args[2].dry_run for call in native.call_args_list))

    def test_duplicate_stale_or_changed_target_cannot_apply_policy(self):
        self.initialize()
        for rows in ({'sessions': [], 'discovery': {}}, {**self.rows(), 'sessions': self.rows()['sessions']*2}):
            with mock.patch.object(core, 'collect_listing', return_value=rows), mock.patch.object(core.LocalTransport, 'execute') as native:
                result = self.call(*self.policy_args(), '--apply')
            self.assertEqual(result['reason'], 'setup_target_missing_or_ambiguous')
            native.assert_not_called()
        with mock.patch.object(core, 'collect_listing', side_effect=[self.rows(), {'sessions': [], 'discovery': {}}]), \
                mock.patch.object(core.LocalTransport, 'execute', return_value={'ok': True}):
            self.assertFalse(self.call(*self.policy_args(), '--apply')['ok'])
        self.assertFalse((self.root/'receiver-policy.json').exists())

    def test_policy_preview_does_not_construct_store(self):
        with mock.patch.object(setup, 'Store', side_effect=AssertionError('Store constructed')), \
                mock.patch.object(core, 'collect_listing', return_value=self.rows()), \
                mock.patch.object(core.LocalTransport, 'execute', return_value={'ok': True}):
            self.assertTrue(self.call(*self.policy_args())['ok'])
        self.assertFalse(self.root.exists())

    def test_existing_receiver_lock_is_detected_without_start_or_service_mutation(self):
        self.initialize()
        path = self.root/'receiver.lock'
        private_write(path, '')
        with path.open('r') as lock:
            setup.fcntl.flock(lock, setup.fcntl.LOCK_EX)
            result = self.call()
            self.assertTrue(result['inventory']['receiverRunning'])
            self.assertEqual(self.call('--action', 'receiver', '--apply')['reason'], 'receiver_already_running')

    def test_invitation_created_privately_once_and_ambiguous_creation_not_repeated(self):
        self.initialize()
        output = self.root/'invitation.json'
        result = self.call('--action', 'invite', '--out', str(output), '--direct', '127.0.0.1:3770', '--apply')
        self.assertTrue(result['invitationSaved'])
        self.assertNotIn(json.loads(output.read_text())['secret'], json.dumps(result))
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.call('--action', 'invite', '--out', str(output), '--direct', '127.0.0.1:3770', '--apply')['reason'], 'setup_invitation_reconcile_required')
        work = setup.Workflow(self.root)
        work.phase('invite', 'pending')
        self.assertEqual(self.call('--action', 'invite', '--out', str(self.root/'other.json'), '--direct', '127.0.0.1:3770', '--apply')['reason'], 'setup_invitation_reconcile_required')

    def test_existing_pair_api_and_metadata_readiness_no_send(self):
        self.initialize()
        other = Store(self.base/'other')
        try:
            invitation = other.invite({'direct': '127.0.0.1:3770'})
            path = self.root/'received.json'
            private_write(path, json.dumps(invitation))
            async def paired(store, invite, route, credential):
                self.assertIsNone(credential)
                store.remember(invite)
                return {'ok': True, 'paired': True}
            with mock.patch.object(setup, 'pair', side_effect=paired) as pair:
                self.assertTrue(self.call('--action', 'pair', '--invite', str(path), '--apply')['paired'])
                self.assertTrue(self.call('--action', 'pair', '--invite', str(path), '--apply')['resumed'])
            self.assertEqual(pair.call_count, 1)
            with mock.patch.object(setup, 'exchange', new_callable=mock.AsyncMock, side_effect=[{'ok': True, 'receiverReady': True}, {'ok': True, 'sessions': []}]) as exchange:
                result = self.call('--action', 'ready', '--peer', other.device, '--apply')
            self.assertTrue(result['ok'])
            self.assertTrue(result['metadataOnly'])
            self.assertFalse(result['messageSubmitted'])
            self.assertEqual([call.args[2] for call in exchange.call_args_list], ['probe', 'list'])
            with mock.patch.object(setup, 'exchange', new_callable=mock.AsyncMock, return_value={'ok': False, 'reason': 'operation_denied'}):
                self.assertFalse(self.call('--action', 'ready', '--peer', other.device, '--apply')['ok'])
        finally:
            other.close()

    def test_interactive_cancel_and_eof_do_not_initialize(self):
        with mock.patch('builtins.input', side_effect=[str(self.root), 'no']), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(setup.run(self.args('--interactive'))['cancelled'])
        self.assertFalse(self.root.exists())
        with mock.patch('builtins.input', side_effect=EOFError), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(setup.run(self.args('--interactive'))['_exit'], 130)

    def test_identity_change_and_pid_reuse_before_policy_apply_refuse(self):
        self.initialize()
        store = Store(self.root)
        try:
            store.db.execute('UPDATE metadata SET value="1" WHERE key="generation"')
        finally:
            store.close()
        self.login_state()
        with mock.patch.object(setup.control, 'enroll') as enroll:
            self.assertEqual(self.call('--action', 'enroll', '--name', 'fixture', '--apply')['reason'], 'setup_identity_changed')
        enroll.assert_not_called()
        # Separate fresh state for the pre-apply PID/start-time boundary.
        self.root = self.base/'policy-state'
        self.defaults = ['setup', '--mode', 'relay', '--state', str(self.root)]
        self.initialize()
        newer = self.rows()
        newer['sessions'][0]['startedAt'] = 2
        with mock.patch.object(core, 'collect_listing', side_effect=[self.rows(), newer]), \
                mock.patch.object(core.LocalTransport, 'execute', return_value={'ok': True}):
            self.assertEqual(self.call(*self.policy_args(), '--apply')['reason'], 'setup_target_changed')
        self.assertFalse((self.root/'receiver-policy.json').exists())

    def test_foreground_receiver_is_separate_opt_in_no_background_install(self):
        self.initialize()
        private_write(self.root/'receiver-policy.json', json.dumps({'targets': {'main': {'agent': 'claude', 'target': '321'}}, 'peers': {}}))
        with mock.patch.object(setup, 'manage', new_callable=mock.AsyncMock, return_value={'ok': True, 'stopped': True}) as manage:
            self.assertTrue(self.call('--action', 'receiver', '--apply')['stopped'])
        self.assertEqual(manage.call_args.args[0], 'device')
        self.assertEqual(manage.call_args.args[1].action, 'serve')
        self.assertEqual(manage.call_args.args[1].bind, '127.0.0.1')


class CoreSetup(unittest.TestCase):
    def test_local_and_ssh_choices_do_not_import_optional_relay(self):
        for mode in ('local', 'ssh'):
            argv = ['setup', '--mode', mode] + (['--host', 'fixture'] if mode == 'ssh' else [])
            with mock.patch.object(core, 'optional_relay', side_effect=AssertionError('optional import')), \
                    mock.patch.object(core, 'cmd_list', return_value=0) as listing, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(core.main(argv), 0)
            listing.assert_called_once()

    def test_missing_extras_runtime_and_manager_guidance_are_explicit(self):
        for reason in ('relay_dependencies_missing', 'relay_runtime_unsupported'):
            with mock.patch.object(core, 'optional_relay', side_effect=core.CcPeerError('fixture', {'reason': reason})), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(core.main(['setup', '--mode', 'relay', '--json']), 1)
            self.assertEqual(json.loads(out.getvalue())['reason'], reason)
        with mock.patch.object(core, 'installed_as_distribution', return_value=False):
            guide = core.relay_install_guidance()
        self.assertIn('Keep the existing CLI', guide['nextAction'])
        self.assertIn('session-peer[relay]', guide['example'])


class SetupLoopback(unittest.IsolatedAsyncioTestCase):
    async def test_real_invitation_tls_pair_probe_and_list_with_fake_native_endpoint(self):
        from session_peer_relay.app import Receiver
        with tempfile.TemporaryDirectory(prefix='codex-setup-loopback-') as directory:
            base = Path(directory)
            args = core.build_parser().parse_args(['setup', '--mode', 'relay', '--state', str(base/'client'), '--action', 'init', '--apply'])
            client = await setup.execute(args)
            server_store = Store(base/'receiver')
            policy = {'targets': {'main': {'agent': 'claude', 'target': '321'}},
                      'peers': {client['device']: {'capabilities': ['list'], 'targets': ['main']}}}
            receiver = Receiver(server_store, policy)
            fake_native = mock.Mock()
            fake_native.invoke = mock.AsyncMock(return_value={'ok': True, 'sessions': [], 'discovery': {'claude': {'status': 'ok'}}})
            receiver.native = fake_native
            server = await receiver.listen('127.0.0.1', 0)
            try:
                invitation = server_store.invite({'direct': '127.0.0.1:'+str(server.sockets[0].getsockname()[1])})
                path = base/'client'/'received.json'
                private_write(path, json.dumps(invitation))
                args.action, args.invite, args.route = 'pair', str(path), 'direct'
                self.assertTrue((await setup.execute(args))['ok'])
                args.action, args.peer = 'ready', server_store.device
                result = await setup.execute(args)
                self.assertTrue(result['ok'], result)
                self.assertTrue(result['metadataOnly'])
                self.assertFalse(result['messageSubmitted'])
                self.assertEqual(fake_native.invoke.call_count, 1)
                self.assertEqual(fake_native.invoke.call_args.args[1], 'list')
            finally:
                server.close()
                await server.wait_closed()
                await receiver.close()
                server_store.close()


if __name__ == '__main__':
    unittest.main()
