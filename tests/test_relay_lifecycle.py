"""Identity lifecycle tests against real TLS and a deterministic native socket."""
import json
import unittest
import uuid
from unittest import mock

from tests import test_native_relay as native_tests
from session_peer_relay.app import exchange, open_channel, request
from session_peer_relay.rotation import local_prepare, remote_prepare, rotate
from session_peer_relay.store import Store, Rejected


class Lifecycle(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = native_tests.NativeRelay.asyncSetUp
    asyncTearDown = native_tests.NativeRelay.asyncTearDown
    call = native_tests.NativeRelay.call

    async def test_rotation_preserves_principal_and_receipt_across_restart(self):
        principal = self.client.device
        before_key = self.client.key_id
        ident = str(uuid.uuid4())
        body = {'target': 'review', 'message': 'one native effect'}
        first = await self.call('send', body, ident)
        self.assertTrue(first['ok'])
        operation = str(uuid.uuid4())
        result = await rotate(self.client, operation, 'direct', None)
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.client.device, principal)
        self.assertNotEqual(self.client.key_id, before_key)
        duplicate = await self.call('send', body, ident, 'relay')
        self.assertTrue(duplicate['duplicate'], duplicate)
        self.assertEqual(len(self.effects), 1)
        self.client.close()
        self.client = Store(self.root/'client')
        self.assertEqual(self.client.device, principal)
        self.assertEqual(self.client.generation, 1)
        self.assertEqual((await rotate(self.client, operation, 'direct', None))['rotation'], 'active')
        self.assertTrue((await self.call('send', body, ident))['duplicate'])

    async def test_prepared_key_and_old_key_cannot_send_and_conflict_is_rejected(self):
        operation = str(uuid.uuid4())
        prepared = local_prepare(self.client, operation)
        result = await self.call('rotation.prepare', prepared['proposal'])
        self.assertEqual(result['rotation'], 'prepared')
        result = await self.call('send', {'target': 'review', 'message': 'blocked'})
        self.assertEqual(result['reason'], 'key_rotation_restricted')
        old_root = self.client.identity_root
        self.client.identity_root = self.client.root/prepared['directory']
        result = await self.call('send', {'target': 'review', 'message': 'blocked'})
        self.assertEqual(result['reason'], 'key_rotation_restricted')
        self.client.identity_root = old_root
        wrong = {**prepared['proposal'], 'generation': 88}
        with self.assertRaises(Rejected):
            remote_prepare(self.host, self.client.device, self.client.key_id, wrong)
        self.assertEqual(self.effects, [])

    async def test_lost_commit_response_resumes_with_same_keys_and_id(self):
        original = self.receiver.dispatch
        interrupted = False
        async def lose(peer, value):
            nonlocal interrupted
            result = await original(peer, value)
            if value.get('op') == 'rotation.commit' and not interrupted:
                interrupted = True
                # Simulate a lost response after durable commit, without retrying native work.
                return {'ok': False, 'status': 'unknown'}
            return result
        self.receiver.dispatch = lose
        operation = str(uuid.uuid4())
        first = await rotate(self.client, operation, 'direct', None)
        self.assertFalse(first['ok'], first)
        self.client.close()
        self.client = Store(self.root/'client')
        resumed = await rotate(self.client, operation, 'direct', None)
        self.assertTrue(resumed['ok'], resumed)
        self.assertEqual(self.client.generation, 1)
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM rotations').fetchone()[0], 1)

    async def test_revocation_survives_rotation_and_blocks_resume(self):
        operation = str(uuid.uuid4())
        await rotate(self.client, operation, 'direct', None)
        self.host.revoke(self.client.device)
        with self.assertRaises(Rejected):
            await self.call('list')

    async def test_exclusive_state_lock_refuses_active_clients(self):
        with self.assertRaisesRegex(Rejected, 'device_state_busy'):
            Store(self.client.root, exclusive=True)

    async def test_invalid_receiver_config_releases_lock_even_with_retained_traceback(self):
        from types import SimpleNamespace
        from session_peer_relay.cli import manage
        from session_peer_relay.identity import private_write
        policy = self.root/'invalid-policy.json'
        private_write(policy, 'invalid json')
        args = SimpleNamespace(action='serve', state=str(self.root/'failed-receiver'),
                               policy=str(policy), bind='127.0.0.1', port=0, relay=None)
        errors = []
        for _ in range(2):
            try:
                await manage('device', args)
            except Exception as error:
                errors.append(error)
        self.assertEqual(len(errors), 2)
        self.assertTrue(all(isinstance(e, json.JSONDecodeError) for e in errors))

    async def test_backup_restore_is_quarantined_and_keeps_receipts(self):
        from session_peer_relay.lifecycle import backup, restore, diagnostics
        from session_peer_relay.identity import private_write
        ident = str(uuid.uuid4())
        body = {'target': 'review', 'message': 'record before snapshot'}
        self.assertTrue((await self.call('send', body, ident))['ok'])
        policy = self.root/'policy.json'
        private_write(policy, json.dumps(self.policy))
        snapshot = self.root/'snapshot'
        backup(self.host, snapshot, policy)
        destination = self.root/'restored'
        result = restore(snapshot, destination)
        self.assertFalse(result['sendEnabled'])
        recovered = Store(destination)
        try:
            self.assertTrue(diagnostics(recovered)['recoveryRequired'])
            self.assertEqual(recovered.status(self.client.device, ident)['messageId'], ident)
            self.assertEqual(recovered.status(self.client.device, str(uuid.uuid4()))['status'], 'unknown')
            with self.assertRaisesRegex(Rejected, 'recovery_required'):
                recovered.begin(self.client.device, str(uuid.uuid4()), 'post snapshot ambiguity')
            self.assertEqual(len(self.effects), 1)
        finally:
            recovered.close()

    async def test_full_journal_keeps_duplicate_and_unknown_lookup(self):
        from session_peer_relay.lifecycle import diagnostics
        self.host.db.executemany('INSERT INTO requests VALUES(?,?,?,"pending",NULL)',
                                [(self.client.device, str(uuid.uuid4()), 'digest') for _ in range(10000)])
        result = diagnostics(self.host)
        self.assertEqual(result['journal']['level'], 'full')
        with self.assertRaisesRegex(Rejected, 'journal_full'):
            self.host.begin(self.client.device, str(uuid.uuid4()), 'new request')
        ident = self.host.db.execute('SELECT id FROM requests LIMIT 1').fetchone()[0]
        self.assertFalse(self.host.status(self.client.device, ident)['retryAllowed'])
        operation = str(uuid.uuid4())
        self.assertTrue((await rotate(self.client, operation, 'direct', None))['ok'])
        self.host.revoke(self.client.device)
        self.assertEqual(self.host.peer(self.client.device)['status'], 'revoked')

    async def test_interrupted_restore_never_publishes_usable_state(self):
        from session_peer_relay.lifecycle import backup, restore
        from session_peer_relay.identity import private_write
        policy = self.root/'restore-policy.json'
        private_write(policy, json.dumps(self.policy))
        snapshot, destination = self.root/'snapshot', self.root/'restored'
        backup(self.client, snapshot, policy)
        with mock.patch('session_peer_relay.lifecycle.sqlite3.connect', side_effect=RuntimeError('crash before quarantine')):
            with self.assertRaises(RuntimeError):
                restore(snapshot, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob('.restore-*')), [])
        abandoned = self.root/'interrupted-staging'
        abandoned.mkdir(mode=0o700)
        private_write(abandoned/'restore-incomplete', 'incomplete')
        with self.assertRaisesRegex(Rejected, 'restore_incomplete'):
            Store(abandoned)

    async def test_restored_sender_blocks_effects_rotation_and_pairing(self):
        from session_peer_relay.lifecycle import backup, restore
        from session_peer_relay.identity import private_write
        from session_peer_relay.control import enroll
        policy = self.root/'restore-policy.json'
        private_write(policy, json.dumps(self.policy))
        ident = str(uuid.uuid4())
        self.assertTrue((await self.call('send', {'target': 'review', 'message': 'before snapshot'}, ident))['ok'])
        snapshot, destination = self.root/'snapshot', self.root/'restored'
        backup(self.client, snapshot, policy)
        restore(snapshot, destination)
        recovered = Store(destination)
        try:
            with self.assertRaisesRegex(Rejected, 'recovery_required'):
                await exchange(recovered, self.host.device, 'send', {'target': 'review', 'message': 'blocked'}, str(uuid.uuid4()), 'direct')
            with self.assertRaisesRegex(Rejected, 'recovery_required'):
                await rotate(recovered, str(uuid.uuid4()), 'direct', None)
            with self.assertRaisesRegex(Rejected, 'recovery_required'):
                recovered.invite({})
            with self.assertRaisesRegex(Rejected, 'recovery_required'):
                enroll(recovered, 'restored')
            status = await exchange(recovered, self.host.device, 'status', ident, route='direct')
            self.assertEqual(status['messageId'], ident)
            self.assertEqual(len(self.effects), 1)
            self.assertEqual(recovered.generation, 0)
        finally:
            recovered.close()

    async def test_retired_old_key_can_never_submit_again(self):
        original_root = self.client.identity_root
        ident = str(uuid.uuid4())
        self.assertTrue((await rotate(self.client, ident, 'direct', None))['ok'])
        self.client.identity_root = original_root
        result = await self.call('send', {'target': 'review', 'message': 'retired'})
        self.assertEqual(result['reason'], 'key_rotation_restricted')
        self.host.db.execute('UPDATE peer_keys SET expires=0 WHERE status="retired"')
        with self.assertRaises(Rejected):
            await self.call('list')
        self.assertEqual(self.effects, [])

    async def test_receiver_rotation_updates_pins_but_preserves_routes(self):
        from session_peer_relay.app import Receiver
        other = Receiver(self.client, {'targets': self.policy['targets'], 'peers': {
            self.host.device: {'capabilities': ['list', 'send'], 'targets': ['review']}}})
        listener = await other.listen('127.0.0.1', 0)
        try:
            self.host.db.execute('UPDATE peers SET routes=? WHERE id=?',
                (json.dumps({'direct': '127.0.0.1:'+str(listener.sockets[0].getsockname()[1])}), self.client.device))
            before = self.client.peer(self.host.device)
            result = await rotate(self.host, str(uuid.uuid4()), 'direct', None)
            self.assertTrue(result['ok'], result)
            after = self.client.peer(self.host.device)
            self.assertNotEqual(before['certificate'], after['certificate'])
            self.assertEqual(before['routes'], after['routes'])
            self.assertTrue((await self.call('list'))['ok'])
            # A newly paired device can consume a rotated receiver's invitation.
            from session_peer_relay.app import pair
            extra = Store(self.root/'extra')
            try:
                invite = self.host.invite(before['routes'])
                self.assertEqual(invite['v'], 2)
                self.assertTrue((await pair(extra, invite, 'direct'))['ok'])
            finally:
                extra.close()
        finally:
            listener.close(); await listener.wait_closed(); await other.close()
