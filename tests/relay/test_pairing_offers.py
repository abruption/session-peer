"""Offline offers and loopback TLS; no external or native agent is contacted."""
import asyncio
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

if os.name != 'posix' or sys.version_info < (3, 11):
    raise unittest.SkipTest('optional relay requires POSIX and Python 3.11+')
try:
    import cryptography
    import websockets
except ModuleNotFoundError as exc:
    if exc.name not in ('cryptography', 'websockets'):
        raise
    raise unittest.SkipTest('optional relay dependencies unavailable') from None

from session_peer_relay import app
from session_peer_relay.pairing_links import encode_link, link_digest
from session_peer_relay.store import Store, Rejected


class Offers(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='codex-offer-', dir=os.environ.get('SESSION_PEER_TEST_TMP'))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.host, self.client, self.other = [Store(self.root/name) for name in ('host', 'client', 'other')]
        for store in (self.host, self.client, self.other):
            self.addCleanup(store.close)

    def offer(self):
        return self.host.create_offer({'direct': '127.0.0.1:1'}, self.client.key_id)

    def prepare(self, invite, *, client=None, **overrides):
        client = client or self.client
        request = {'invitation': invite['id'], 'secret': invite['secret'], 'certificate': client.cert, 'offer': True}
        request.update(overrides)
        return self.host.prepare(request)

    def commit(self, invite, *, client=None):
        client = client or self.client
        return self.host.commit(client.key_id, invite['id'], authenticated_key=client.key_id, offer=True)

    def test_offer_binds_exact_client_and_never_stores_secret(self):
        invite = self.offer()
        self.assertEqual(self.host.offer_identity(self.client.key_id),
                         {'principal': self.client.key_id, 'keyFingerprint': self.client.key_id, 'generation': 0})
        with self.assertRaises(Rejected):
            self.prepare(invite, client=self.other)
        self.assertIsNone(self.host.peer(self.other.device))
        prepared = self.prepare(invite)
        self.assertEqual(prepared['offerId'], invite['id'])
        self.assertIn('pairing-offer-v1', prepared['features'])
        self.assertEqual(self.host.offer_status(invite['id'])['status'], 'reserved')
        dump = '\n'.join(self.host.db.iterdump())
        self.assertNotIn(invite['secret'], dump)
        self.assertNotIn('secret', json.dumps(self.host.offer_status(invite['id'])))

    def test_preallocated_offer_id_is_canonical_unique_and_status_reconcilable(self):
        ident = str(uuid.uuid4())
        invite = self.host.create_offer({'direct': '127.0.0.1:1'}, self.client.key_id, offer_id=ident)
        self.assertEqual(invite['id'], ident)
        self.assertEqual(self.host.offer_status(ident)['status'], 'open')
        with self.assertRaisesRegex(Rejected, '^pairing_offer_exists$'):
            self.host.create_offer({'direct': '127.0.0.1:1'}, self.client.key_id, offer_id=ident)
        for invalid in ('not-an-id', str(uuid.uuid4()).upper(), str(uuid.uuid1())):
            with self.assertRaisesRegex(Rejected, '^invalid_pairing_offer_id$'):
                self.host.create_offer({'direct': '127.0.0.1:1'}, self.client.key_id, offer_id=invalid)
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM pairing_offers').fetchone()[0], 1)

    def test_creation_identity_cas_and_already_paired_client_refuse_before_mint(self):
        snapshot = self.host.offer_identity(self.client.key_id)
        self.host.register_key('a'*64, self.client.cert, 2)
        with self.assertRaisesRegex(Rejected, '^pairing_identity_changed$'):
            self.host.create_offer({'direct': '127.0.0.1:1'}, self.client.key_id, expected_identity=snapshot)
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM invites').fetchone()[0], 0)
        snapshot = self.host.offer_identity(self.client.key_id)
        self.host.db.execute('UPDATE peer_keys SET status="revoked" WHERE fingerprint=?', (self.client.key_id,))
        with self.assertRaisesRegex(Rejected, '^pairing_identity_changed$'):
            self.host.create_offer({'direct': '127.0.0.1:1'}, self.client.key_id, expected_identity=snapshot)
        self.host.db.execute('DELETE FROM peer_keys WHERE fingerprint=?', (self.client.key_id,))
        invite = self.offer()
        self.prepare(invite)
        self.commit(invite)
        with self.assertRaisesRegex(Rejected, '^principal_already_paired$'):
            self.offer()
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM pairing_offers').fetchone()[0], 1)

    def test_unencodable_offer_routes_roll_back_invitation_and_metadata(self):
        routes = ({}, {'direct': '호스트.invalid:1'}, {'direct': 'x'*17000+':1'})
        for value in routes:
            with self.assertRaisesRegex(Rejected, '^invalid_pairing_link$') as error:
                self.host.create_offer(value, self.client.key_id)
            self.assertIsNone(error.exception.__cause__)
            self.assertEqual(str(error.exception), 'invalid_pairing_link')
            for table in ('invites', 'pairing_offers', 'pairing_reservations', 'peers', 'peer_keys'):
                self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0], 0)
        self.assertTrue(self.offer())

    def test_no_legacy_prepare_or_commit_downgrade(self):
        invite = self.offer()
        with self.assertRaises(Rejected):
            self.prepare(invite, offer=False)
        self.prepare(invite)
        with self.assertRaises(Rejected):
            self.host.commit(self.client.key_id)
        with self.assertRaises(Rejected):
            self.host.commit(self.client.key_id, invite['id'], authenticated_key=self.client.key_id)
        with self.assertRaises(Rejected):
            self.host.commit(self.client.key_id, authenticated_key=self.client.key_id, offer=True)
        self.assertEqual(self.host.peer(self.client.device)['status'], 'pending')
        self.assertTrue(self.commit(invite)['ok'])
        legacy = self.host.invite({})
        with self.assertRaises(Rejected):
            self.prepare(legacy, client=self.other)

    def test_consumed_receipt_exact_key_idempotent_after_expiry_without_undoing_revoke(self):
        invite = self.offer()
        self.prepare(invite)
        result = self.commit(invite)
        with mock.patch('time.time', return_value=invite['expires']+1):
            self.assertEqual(self.commit(invite), result)
            with self.assertRaises(Rejected):
                self.commit(invite, client=self.other)
        self.host.revoke(self.client.device)
        with self.assertRaises(Rejected):
            self.commit(invite)
        self.assertEqual(self.host.peer(self.client.device)['status'], 'revoked')

    def test_cancellation_only_removes_owned_pending_trust(self):
        invite = self.offer()
        self.prepare(invite)
        self.assertEqual(self.host.cancel_offer(invite['id'])['status'], 'cancelled')
        self.assertIsNone(self.host.peer(self.client.device))
        self.assertIsNone(self.host.db.execute('SELECT 1 FROM peer_keys WHERE fingerprint=?', (self.client.key_id,)).fetchone())
        with self.assertRaises(Rejected):
            self.commit(invite)
        self.host.register_key(self.client.device, self.client.cert)
        second = self.offer()
        self.prepare(second)
        self.host.cancel_offer(second['id'])
        self.assertIsNone(self.host.peer(self.client.device))
        self.assertEqual(self.host.key_status(self.client.key_id), 'active')
        self.assertIsNotNone(self.host.db.execute('SELECT 1 FROM peer_keys WHERE fingerprint=?', (self.client.key_id,)).fetchone())

    def test_consumed_cancel_preserves_completed_pair_and_anchor(self):
        invite = self.offer()
        self.prepare(invite)
        self.commit(invite)
        self.assertEqual(self.host.cancel_offer(invite['id'])['status'], 'consumed')
        self.assertEqual(self.host.peer(self.client.device)['status'], 'paired')
        self.assertEqual(self.host.key_status(self.client.key_id), 'active')

    def test_expiry_atomically_releases_pending_and_refuses_commit(self):
        invite = self.offer()
        self.prepare(invite)
        with mock.patch('time.time', return_value=invite['expires']+1):
            with self.assertRaises(Rejected):
                self.commit(invite)
            self.assertEqual(self.host.offer_status(invite['id'])['status'], 'expired')
        self.assertIsNone(self.host.peer(self.client.device))

    def test_expiry_during_certificate_validation_cannot_create_pending_authority(self):
        invite = self.offer()
        clock = [invite['expires']-1]
        from session_peer_relay import store as store_module
        original = store_module.fingerprint
        def parse_then_expire(pem):
            result = original(pem)
            clock[0] = invite['expires']
            return result
        with mock.patch('time.time', side_effect=lambda: clock[0]), \
                mock.patch.object(store_module, 'fingerprint', side_effect=parse_then_expire):
            with self.assertRaisesRegex(Rejected, '^invalid_invitation$'):
                self.prepare(invite)
        self.assertIsNone(self.host.peer(self.client.device))
        self.assertIsNone(self.host.db.execute('SELECT 1 FROM peer_keys WHERE fingerprint=?', (self.client.key_id,)).fetchone())
        self.assertIsNone(self.host.db.execute('SELECT 1 FROM pairing_reservations').fetchone())
        self.assertEqual(self.host.db.execute('SELECT peer FROM invites WHERE id=?', (invite['id'],)).fetchone(), (None,))
        self.assertEqual(self.host.offer_status(invite['id'])['status'], 'open')

    def test_expiry_during_commit_binding_validation_cannot_promote_pending_peer(self):
        invite = self.offer()
        self.prepare(invite)
        clock = [invite['expires']-1]
        database = self.host.db
        proxy = mock.Mock(wraps=database)
        def query_then_expire(sql, *args, **kwargs):
            result = database.execute(sql, *args, **kwargs)
            if sql.startswith('SELECT client_key,principal,state,receipt FROM pairing_offers'):
                clock[0] = invite['expires']
            return result
        proxy.execute.side_effect = query_then_expire
        with mock.patch('time.time', side_effect=lambda: clock[0]), \
                mock.patch.object(self.host, 'db', proxy):
            with self.assertRaisesRegex(Rejected, '^pairing_not_pending$'):
                self.commit(invite)
        self.assertEqual(self.host.peer(self.client.device)['status'], 'pending')
        self.assertEqual(self.host.db.execute('SELECT state,receipt FROM pairing_offers WHERE id=?', (invite['id'],)).fetchone(), ('reserved', None))
        self.assertIsNotNone(self.host.db.execute('SELECT 1 FROM pairing_reservations WHERE invitation=?', (invite['id'],)).fetchone())

    def test_offer_identity_does_not_fallback_for_pending_retired_or_revoked(self):
        invite = self.offer()
        self.prepare(invite)
        with self.assertRaises(Rejected):
            self.host.offer_identity(self.client.key_id)
        self.host.cancel_offer(invite['id'])
        self.host.register_key(self.client.device, self.client.cert)
        for status in ('pending', 'retired', 'revoked'):
            self.host.db.execute('UPDATE peer_keys SET status=? WHERE fingerprint=?', (status, self.client.key_id))
            with self.assertRaises(Rejected):
                self.host.offer_identity(self.client.key_id)

    def test_rotated_identity_comes_only_from_exact_active_anchor(self):
        principal = 'a'*64
        self.host.register_key(principal, self.client.cert, 4)
        self.assertEqual(self.host.offer_identity(self.client.key_id)['principal'], principal)
        invite = self.offer()
        with self.assertRaises(Rejected):
            self.prepare(invite)
        self.prepare(invite, principal=principal, generation=4)
        self.assertTrue(self.commit(invite)['ok'])

    def test_invitation_reservation_cannot_overwrite_another_or_downgrade_paired(self):
        first, second = self.offer(), self.offer()
        self.prepare(first)
        with self.assertRaises(Rejected):
            self.prepare(second)
        self.assertEqual(self.host.offer_status(first['id'])['status'], 'reserved')
        self.commit(first)
        with self.assertRaises(Rejected):
            self.prepare(second)
        self.assertEqual(self.host.peer(self.client.device)['status'], 'paired')

    def test_creation_quota_active_quota_and_persistence(self):
        now = time.time()
        with mock.patch('time.time', return_value=now):
            for unused in range(5):
                self.offer()
            with self.assertRaisesRegex(Rejected, 'rate_limited'):
                self.offer()
        reopened = Store(self.host.root)
        try:
            with mock.patch('time.time', return_value=now):
                with self.assertRaisesRegex(Rejected, 'rate_limited'):
                    reopened.create_offer({'direct': '127.0.0.1:1'}, self.client.key_id)
            with mock.patch('time.time', return_value=now+61):
                for unused in range(3):
                    reopened.create_offer({'direct': '127.0.0.1:1'}, self.client.key_id)
                with self.assertRaisesRegex(Rejected, 'capacity'):
                    reopened.create_offer({'direct': '127.0.0.1:1'}, self.client.key_id)
        finally:
            reopened.close()

    def test_full_quota_rejects_without_writes_or_extending_window(self):
        now = time.time()
        with mock.patch('time.time', return_value=now):
            for unused in range(5):
                self.offer()
        before = self.host.db.total_changes
        attempts = self.host.db.execute('SELECT attempts FROM pairing_limits WHERE scope="create"').fetchone()[0]
        with mock.patch('time.time', return_value=now+59):
            with self.assertRaisesRegex(Rejected, 'rate_limited'):
                self.offer()
        self.assertEqual(self.host.db.total_changes, before)
        self.assertEqual(self.host.db.execute('SELECT attempts FROM pairing_limits WHERE scope="create"').fetchone()[0], attempts)
        with mock.patch('time.time', return_value=now+60):
            self.assertIsNotNone(self.offer())

    def test_full_global_quota_never_allocates_or_updates_offer_bucket(self):
        invite = self.offer()
        for unused in range(32):
            with self.assertRaises(Rejected):
                self.host.prepare({'invitation': str(uuid.uuid4())})
        before = self.host.db.total_changes
        with self.assertRaisesRegex(Rejected, 'rate_limited'):
            self.prepare(invite)
        self.assertEqual(self.host.db.total_changes, before)
        self.assertIsNone(self.host.db.execute('SELECT 1 FROM pairing_limits WHERE scope=?', ('offer:'+invite['id'],)).fetchone())

    def test_full_offer_bucket_does_not_extend_but_denials_charge_remaining_global_quota(self):
        invite = self.offer()
        now = time.time()
        with mock.patch('time.time', return_value=now):
            for unused in range(8):
                with self.assertRaises(Rejected):
                    self.prepare(invite, secret='incorrect')
        scope = 'offer:'+invite['id']
        attempts = self.host.db.execute('SELECT attempts FROM pairing_limits WHERE scope=?', (scope,)).fetchone()[0]
        with mock.patch('time.time', return_value=now+59):
            with self.assertRaisesRegex(Rejected, 'rate_limited'):
                self.prepare(invite)
        self.assertEqual(self.host.db.execute('SELECT attempts FROM pairing_limits WHERE scope=?', (scope,)).fetchone()[0], attempts)
        global_attempts = json.loads(self.host.db.execute('SELECT attempts FROM pairing_limits WHERE scope="prepare"').fetchone()[0])
        self.assertEqual(len(global_attempts), 9)
        with mock.patch('time.time', return_value=now+60):
            self.assertTrue(self.prepare(invite)['ok'])

    def test_expired_premigration_pending_state_releases_peer_but_preserves_anchor(self):
        invitation = self.host.invite({})
        self.host.prepare({'invitation': invitation['id'], 'secret': invitation['secret'], 'certificate': self.client.cert})
        self.host.db.execute('DELETE FROM pairing_reservations')
        with mock.patch('time.time', return_value=invitation['expires']+1):
            identity = self.host.offer_identity(self.client.key_id)
            self.assertEqual(identity['principal'], self.client.device)
            self.assertIsNone(self.host.peer(self.client.device))
            self.assertEqual(self.host.key_status(self.client.key_id), 'active')
            fresh = self.offer()
            self.assertTrue(self.prepare(fresh)['ok'])
        self.assertEqual(self.host.db.execute('SELECT expires FROM invites WHERE id=?', (invitation['id'],)).fetchone(), (0,))

    def test_expired_premigration_pending_with_live_ambiguous_authority_stays_protected(self):
        invitation = self.host.invite({})
        self.host.prepare({'invitation': invitation['id'], 'secret': invitation['secret'], 'certificate': self.client.cert})
        self.host.db.execute('DELETE FROM pairing_reservations')
        second = self.host.invite({})
        self.host.db.execute('UPDATE invites SET peer=?,expires=? WHERE id=?',
                             (self.client.device, invitation['expires']+100, second['id']))
        with mock.patch('time.time', return_value=invitation['expires']+1):
            with self.assertRaises(Rejected):
                self.host.offer_identity(self.client.key_id)
        self.assertEqual(self.host.peer(self.client.device)['status'], 'pending')
        self.assertEqual(self.host.key_status(self.client.key_id), 'active')

    def test_expired_premigration_legacy_pending_can_prepare_a_fresh_file_invitation(self):
        invitation = self.host.invite({})
        self.host.prepare({'invitation': invitation['id'], 'secret': invitation['secret'], 'certificate': self.client.cert})
        self.host.db.execute('DELETE FROM pairing_reservations')
        with mock.patch('time.time', return_value=invitation['expires']+1):
            fresh = self.host.invite({})
            self.assertTrue(self.host.prepare({'invitation': fresh['id'], 'secret': fresh['secret'],
                                              'certificate': self.client.cert})['ok'])
        self.assertEqual(self.host.db.execute('SELECT invitation FROM pairing_reservations').fetchone(), (fresh['id'],))

    def test_failed_guesses_persist_offer_quota_and_unknown_ids_allocate_no_rows(self):
        invite = self.offer()
        for unused in range(8):
            with self.assertRaises(Rejected):
                self.prepare(invite, secret='incorrect')
        with self.assertRaisesRegex(Rejected, 'rate_limited'):
            self.prepare(invite)
        before = self.host.db.execute('SELECT COUNT(*) FROM pairing_limits').fetchone()[0]
        for unused in range(4):
            with self.assertRaises(Rejected):
                self.host.prepare({'invitation': str(uuid.uuid4()), 'secret': 'incorrect'})
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM pairing_limits').fetchone()[0], before)
        self.assertIsNone(self.host.peer(self.client.device))

    def test_global_prepare_limit_is_durable_even_without_known_invitation(self):
        for unused in range(32):
            with self.assertRaises(Rejected):
                self.host.prepare({'invitation': str(uuid.uuid4()), 'secret': 'incorrect'})
        with self.assertRaisesRegex(Rejected, 'rate_limited'):
            self.prepare(self.offer())

    def test_every_malformed_prepare_including_false_id_consumes_global_quota(self):
        invalid = ({'invitation': False}, {'invitation': []}, None, {}, True)
        for index in range(32):
            with self.assertRaises(Rejected):
                self.host.prepare(invalid[index % len(invalid)])
        self.assertEqual(self.host.db.execute('SELECT scope FROM pairing_limits').fetchall(), [('prepare',)])
        with self.assertRaisesRegex(Rejected, 'rate_limited'):
            self.host.prepare({'invitation': False})

    def test_unambiguous_premigration_legacy_reservation_is_adopted_for_commit(self):
        invitation = self.host.invite({})
        self.host.prepare({'invitation': invitation['id'], 'secret': invitation['secret'], 'certificate': self.client.cert})
        self.host.db.execute('DELETE FROM pairing_reservations')
        self.assertTrue(self.host.commit(self.client.key_id)['ok'])
        self.assertEqual(self.host.peer(self.client.device)['status'], 'paired')
        self.assertEqual(self.host.db.execute('SELECT expires FROM invites WHERE id=?', (invitation['id'],)).fetchone(), (0,))

    def test_premigration_legacy_prepare_adopts_only_its_exact_live_invitation(self):
        invitation = self.host.invite({})
        request = {'invitation': invitation['id'], 'secret': invitation['secret'], 'certificate': self.client.cert}
        self.host.prepare(request)
        self.host.db.execute('DELETE FROM pairing_reservations')
        self.assertTrue(self.host.prepare(request)['ok'])
        self.assertEqual(self.host.db.execute('SELECT invitation FROM pairing_reservations').fetchone(), (invitation['id'],))

    def test_ambiguous_premigration_reservations_remain_unmodified_and_refused(self):
        invitation = self.host.invite({})
        self.host.prepare({'invitation': invitation['id'], 'secret': invitation['secret'], 'certificate': self.client.cert})
        self.host.db.execute('DELETE FROM pairing_reservations')
        other = self.host.invite({})
        self.host.db.execute('UPDATE invites SET peer=? WHERE id=?', (self.client.device, other['id']))
        with self.assertRaises(Rejected):
            self.host.commit(self.client.key_id)
        self.assertEqual(self.host.peer(self.client.device)['status'], 'pending')
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM pairing_reservations').fetchone()[0], 0)

    def test_premigration_offer_ownership_is_never_inferred(self):
        invitation = self.offer()
        self.prepare(invitation)
        self.host.db.execute('DELETE FROM pairing_reservations')
        with self.assertRaises(Rejected):
            self.commit(invitation)
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM pairing_reservations').fetchone()[0], 0)

    def test_premigration_expiry_or_certificate_mismatch_cannot_be_adopted(self):
        invitation = self.host.invite({})
        self.host.prepare({'invitation': invitation['id'], 'secret': invitation['secret'], 'certificate': self.client.cert})
        self.host.db.execute('DELETE FROM pairing_reservations')
        self.host.db.execute('UPDATE peers SET expires=expires+1 WHERE id=?', (self.client.device,))
        with self.assertRaises(Rejected):
            self.host.commit(self.client.key_id)
        with self.assertRaises(Rejected):
            self.host.commit(self.other.key_id)

    def test_terminal_retention_prunes_bound_invitation_together(self):
        invite = self.offer()
        self.host.cancel_offer(invite['id'])
        with mock.patch('time.time', return_value=time.time()+7*86400+1):
            with self.assertRaisesRegex(Rejected, 'unknown'):
                self.host.offer_status(invite['id'])
        self.assertIsNone(self.host.db.execute('SELECT 1 FROM invites WHERE id=?', (invite['id'],)).fetchone())
        self.assertIsNone(self.host.db.execute('SELECT 1 FROM pairing_offers WHERE id=?', (invite['id'],)).fetchone())

    def test_cross_connection_prepare_race_has_single_owner(self):
        invitations = [self.offer(), self.offer()]
        barrier = threading.Barrier(2)
        def attempt(invite):
            store = Store(self.host.root)
            try:
                barrier.wait(timeout=2)
                try:
                    store.prepare({'invitation': invite['id'], 'secret': invite['secret'],
                                   'certificate': self.client.cert, 'offer': True})
                    return True
                except Rejected:
                    return False
            finally:
                store.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, invitations))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM pairing_reservations').fetchone()[0], 1)

    def test_cancel_commit_race_has_one_terminal_state_without_partial_trust(self):
        invite = self.offer()
        self.prepare(invite)
        barrier = threading.Barrier(2)
        def operation(commit):
            store = Store(self.host.root)
            try:
                barrier.wait(timeout=2)
                try:
                    if commit:
                        return store.commit(self.client.key_id, invite['id'], authenticated_key=self.client.key_id, offer=True)
                    return store.cancel_offer(invite['id'])
                except Rejected:
                    return None
            finally:
                store.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(operation, (True, False)))
        status = self.host.offer_status(invite['id'])['status']
        self.assertIn(status, ('cancelled', 'consumed'))
        peer = self.host.peer(self.client.device)
        if status == 'consumed':
            self.assertEqual(peer['status'], 'paired')
        else:
            self.assertIsNone(peer)
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM pairing_reservations').fetchone()[0], 0)

    def test_terminal_cap_fails_closed_until_safe_paired_pruning(self):
        invite = self.offer()
        self.host.cancel_offer(invite['id'])
        now = time.time()
        ids = [str(uuid.uuid4()) for unused in range(1023)]
        self.host.db.execute('BEGIN IMMEDIATE')
        try:
            self.host.db.executemany('INSERT INTO invites VALUES(?,?,0,NULL)', [(ident, 'a'*64) for ident in ids])
            self.host.db.executemany('INSERT INTO pairing_offers VALUES(?,?,?,?,"cancelled",?,?,NULL)',
                                    [(ident, self.client.key_id, self.client.device, 0, now, now) for ident in ids])
            self.host.db.execute('COMMIT')
        except BaseException:
            self.host.db.execute('ROLLBACK')
            raise
        with self.assertRaisesRegex(Rejected, 'capacity'):
            self.offer()
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM pairing_offers').fetchone()[0], 1024)
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM invites').fetchone()[0], 1024)
        with mock.patch('time.time', return_value=now+7*86400+1):
            fresh = self.offer()
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM pairing_offers').fetchone()[0], 1)
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM invites').fetchone()[0], 1)
        self.assertNotIn(fresh['id'], ids)


class OfferTLS(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='codex-offer-tls-', dir=os.environ.get('SESSION_PEER_TEST_TMP'))
        self.root = Path(self.directory.name)
        self.host, self.client = Store(self.root/'h'), Store(self.root/'c')
        self.receiver = app.Receiver(self.host, {'targets': {'unused': {'agent': 'claude', 'target': 'offline-fixture'}},
                                                'peers': {self.client.device: {'capabilities': ['list'], 'targets': ['unused']}}})
        self.listener = await self.receiver.listen('127.0.0.1', 0)
        self.routes = {'direct': '127.0.0.1:'+str(self.listener.sockets[0].getsockname()[1])}
        self.invite = self.host.create_offer(self.routes, self.client.key_id)
        self.digest = link_digest(encode_link(self.invite, self.client.key_id))

    async def asyncTearDown(self):
        self.listener.close()
        await self.listener.wait_closed()
        await self.receiver.close()
        self.client.close()
        self.host.close()
        self.directory.cleanup()

    async def pair(self, invite=None, digest=None):
        return await app.pair(self.client, invite or self.invite, 'direct',
                              offer_digest=digest or self.digest, expected_client_key=self.client.key_id)

    async def test_loopback_tls_success_and_expired_exact_intent_receipt(self):
        result = await self.pair()
        self.assertEqual(result['offerId'], self.invite['id'])
        self.assertEqual(self.host.offer_status(self.invite['id'])['status'], 'consumed')
        with mock.patch('time.time', return_value=self.invite['expires']+1):
            self.assertEqual(await self.pair(), result)
        self.assertEqual(self.client.peer(self.host.device)['status'], 'paired')

    async def test_cold_expiry_wrong_client_and_unanchored_receiver_have_no_writes_or_network(self):
        before = self.client.db.total_changes
        bad = [({'expires': time.time()-1}, self.client.key_id), ({}, 'b'*64),
               ({'v': 2, 'device': 'a'*64, 'keyFingerprint': self.host.key_id, 'keyGeneration': 1}, self.client.key_id)]
        with mock.patch.object(app, 'open_channel', side_effect=AssertionError('unexpected network')):
            for changes, expected in bad:
                with self.assertRaises(Rejected):
                    await app.pair(self.client, {**self.invite, **changes}, 'direct',
                                   offer_digest=self.digest, expected_client_key=expected)
                self.assertEqual(self.client.db.total_changes, before)
        self.assertIsNone(self.client.peer(self.host.device))

    async def test_commit_receipt_lost_reconciles_after_expiry_without_preparing(self):
        with mock.patch.object(self.client, 'remember', side_effect=OSError('offline fixture')):
            with self.assertRaisesRegex(Rejected, '^pairing_local_reconciliation_required$'):
                await self.pair()
        self.assertEqual(self.host.offer_status(self.invite['id'])['status'], 'consumed')
        with mock.patch('time.time', return_value=self.invite['expires']+1), \
                mock.patch.object(self.host, 'prepare', side_effect=AssertionError('expired prepare')):
            self.assertTrue((await self.pair())['ok'])

    async def test_expired_saved_intent_cannot_prepare_unconsumed_offer(self):
        self.client.save_offer_intent(self.invite, self.digest, self.client.key_id)
        with mock.patch('time.time', return_value=self.invite['expires']+1), \
                mock.patch.object(self.host, 'prepare', side_effect=AssertionError('expired prepare')):
            with self.assertRaises(Exception):
                await self.pair()
        self.assertIsNone(self.host.peer(self.client.device))

    async def test_digest_change_and_local_revocation_never_reconcile(self):
        await self.pair()
        with mock.patch.object(app, 'open_channel', side_effect=AssertionError('unexpected network')):
            with self.assertRaisesRegex(Rejected, 'intent_conflict'):
                await self.pair(digest='a'*64)
            self.client.revoke(self.host.device)
            with self.assertRaises(Rejected):
                await self.pair()

    async def test_intent_public_facts_exist_before_any_connection(self):
        def unavailable(*args, **kwargs):
            row = self.client.db.execute('SELECT digest,receiver,receiver_key,client_key FROM pairing_intents WHERE id=?',
                                         (self.invite['id'],)).fetchone()
            self.assertEqual(row, (self.digest, self.host.device, self.host.key_id, self.client.key_id))
            raise OSError('fixture unavailable')
        with mock.patch.object(app, 'open_channel', side_effect=unavailable):
            with self.assertRaises(OSError):
                await self.pair()
        self.assertNotIn(self.invite['secret'], '\n'.join(self.client.db.iterdump()))

    async def test_old_receiver_cannot_downgrade_offer(self):
        original = self.host.prepare
        def legacy(request):
            result = original(request)
            result['features'] = ['identity-rotation-v1']
            return result
        with mock.patch.object(self.host, 'prepare', side_effect=legacy):
            with self.assertRaisesRegex(Rejected, 'unsupported'):
                await self.pair()
        self.assertEqual(self.host.peer(self.client.device)['status'], 'pending')

    async def test_receiver_confirmation_is_readonly_and_allows_only_exact_pending_intent(self):
        self.client.save_offer_intent(self.invite, self.digest, self.client.key_id)
        self.client.stage(self.invite)
        before = self.client.db.total_changes
        identity = self.client.receiver_offer_identity(self.invite, self.digest, self.client.key_id)
        self.assertEqual(identity, {'principal': self.host.device, 'keyFingerprint': self.host.key_id, 'generation': 0})
        self.assertEqual(self.client.db.total_changes, before)
        with self.assertRaises(Rejected):
            self.client.receiver_offer_identity(self.invite, 'a'*64, self.client.key_id)
        self.client.db.execute('DELETE FROM pairing_intents')
        before = self.client.db.total_changes
        with self.assertRaisesRegex(Rejected, 'pending'):
            self.client.receiver_offer_identity(self.invite, self.digest, self.client.key_id)
        self.assertEqual(self.client.db.total_changes, before)

    async def test_premigration_pending_file_flow_resumes_over_real_tls(self):
        legacy = self.host.invite(self.routes)
        self.client.stage(legacy)
        self.host.prepare({'invitation': legacy['id'], 'secret': legacy['secret'], 'certificate': self.client.cert})
        for store in (self.client, self.host):
            store.db.execute('DELETE FROM pairing_reservations')
        result = await app.pair(self.client, legacy, 'direct')
        self.assertTrue(result['ok'])
        self.assertEqual(self.client.peer(self.host.device)['status'], 'paired')
        self.assertEqual(self.host.peer(self.client.device)['status'], 'paired')

    async def test_client_intent_cap_preserves_exact_resume_without_eviction(self):
        self.client.save_offer_intent(self.invite, self.digest, self.client.key_id)
        rows = [(str(uuid.uuid4()), self.digest, self.host.device, self.host.key_id, self.client.key_id)
                for unused in range(1023)]
        self.client.db.execute('BEGIN IMMEDIATE')
        try:
            self.client.db.executemany('INSERT INTO pairing_intents VALUES(?,?,?,?,?)', rows)
            self.client.db.execute('COMMIT')
        except BaseException:
            self.client.db.execute('ROLLBACK')
            raise
        fresh = self.host.create_offer(self.routes, self.client.key_id)
        fresh_digest = link_digest(encode_link(fresh, self.client.key_id))
        before = self.client.db.total_changes
        with self.assertRaisesRegex(Rejected, '^pairing_intent_capacity$'):
            self.client.save_offer_intent(fresh, fresh_digest, self.client.key_id)
        self.assertEqual(self.client.db.total_changes, before)
        self.assertEqual(self.client.db.execute('SELECT COUNT(*) FROM pairing_intents').fetchone()[0], 1024)
        self.assertTrue(self.client.save_offer_intent(self.invite, self.digest, self.client.key_id))
        with mock.patch('time.time', return_value=self.invite['expires']+1):
            self.assertTrue(self.client.save_offer_intent(self.invite, self.digest, self.client.key_id))
        self.assertEqual(self.client.db.execute('SELECT COUNT(*) FROM pairing_intents').fetchone()[0], 1024)
        self.assertIsNotNone(self.client.db.execute('SELECT 1 FROM pairing_intents WHERE id=?', (rows[0][0],)).fetchone())

    async def test_expiry_during_pending_finish_failure_never_falls_back_to_prepare(self):
        self.client.save_offer_intent(self.invite, self.digest, self.client.key_id)
        self.client.stage(self.invite)
        clock = [self.invite['expires']-1]
        calls = []
        async def finish(*args, **kwargs):
            calls.append(True)
            clock[0] = self.invite['expires']+1
            raise Rejected('pairing_not_committed')
        with mock.patch('time.time', side_effect=lambda: clock[0]), \
                mock.patch.object(app, 'finish_pair', side_effect=finish), \
                mock.patch.object(app, 'open_channel', side_effect=AssertionError('expired bootstrap')), \
                mock.patch.object(self.host, 'prepare', side_effect=AssertionError('expired prepare')):
            with self.assertRaises(Rejected):
                await self.pair()
        self.assertEqual(len(calls), 2)
        self.assertIsNone(self.host.peer(self.client.device))

    async def test_expiry_during_bootstrap_connection_closes_without_preparing(self):
        clock = [self.invite['expires']-1]
        channel = mock.Mock()
        channel.send = mock.AsyncMock()
        channel.close = mock.AsyncMock()
        async def connect(*args, **kwargs):
            clock[0] = self.invite['expires']+1
            return channel
        with mock.patch('time.time', side_effect=lambda: clock[0]), \
                mock.patch.object(app, 'open_channel', side_effect=connect) as opened, \
                mock.patch.object(app, 'finish_pair', side_effect=Rejected('pairing_not_committed')), \
                mock.patch.object(self.host, 'prepare', side_effect=AssertionError('expired prepare')):
            with self.assertRaises(Rejected):
                await self.pair()
        opened.assert_awaited_once()
        channel.send.assert_not_awaited()
        channel.close.assert_awaited_once()
        self.assertIsNone(self.host.peer(self.client.device))

    async def test_known_commit_with_local_remember_failure_never_reprepares(self):
        await self.pair()
        self.client.db.execute('UPDATE peers SET status="pending",expires=? WHERE id=?',
                               (self.invite['expires'], self.host.device))
        with mock.patch.object(self.client, 'remember', side_effect=OSError('offline fixture')), \
                mock.patch.object(self.host, 'prepare', side_effect=AssertionError('known completion reprepared')):
            with self.assertRaisesRegex(Rejected, '^pairing_local_reconciliation_required$'):
                await self.pair()
        self.assertEqual(self.host.offer_status(self.invite['id'])['status'], 'consumed')

    async def test_consumed_offer_transient_resume_failure_preserves_next_manual_reconciliation(self):
        native = mock.AsyncMock(side_effect=AssertionError('pairing invoked native effect'))
        with mock.patch.object(self.receiver.native, 'invoke', native):
            with mock.patch.object(self.client, 'remember', side_effect=OSError('offline fixture')):
                with self.assertRaises(app.PairingCompletionKnown):
                    await self.pair()
            self.assertEqual(self.host.offer_status(self.invite['id'])['status'], 'consumed')
            original_open = app.open_channel
            calls = []
            async def transient_once(*args, **kwargs):
                bootstrap = args[5] if len(args) > 5 else kwargs.get('bootstrap', False)
                calls.append(bootstrap)
                if calls == [False]:
                    raise ConnectionError('offline fixture')
                return await original_open(*args, **kwargs)
            original_prepare = self.host.prepare
            with mock.patch.object(app, 'open_channel', side_effect=transient_once), \
                    mock.patch.object(self.host, 'prepare', wraps=original_prepare) as prepared:
                with self.assertRaisesRegex(Rejected, '^pairing_reconciliation_required$'):
                    await self.pair()
            self.assertEqual(calls, [False, True])
            self.assertEqual(prepared.call_count, 1)
            self.assertEqual(self.client.peer(self.host.device)['status'], 'pending')
            self.assertEqual(self.client.key_status(self.host.key_id), 'active')
            self.assertEqual(self.client.db.execute('SELECT COUNT(*) FROM pairing_intents').fetchone()[0], 1)
            with mock.patch.object(self.host, 'prepare', side_effect=AssertionError('manual receipt retry prepared')):
                self.assertTrue((await self.pair())['ok'])
            native.assert_not_awaited()
        self.assertEqual(self.client.peer(self.host.device)['status'], 'paired')
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM pairing_offers').fetchone()[0], 1)

    async def test_saved_intent_without_local_stage_still_attempts_authenticated_receipt_first(self):
        with mock.patch.object(self.client, 'remember', side_effect=OSError('offline fixture')):
            with self.assertRaises(app.PairingCompletionKnown):
                await self.pair()
        self.client.discard_pairing_stage(self.invite['id'])
        self.assertIsNone(self.client.peer(self.host.device))
        with mock.patch.object(self.host, 'prepare', side_effect=AssertionError('saved receipt retry prepared')):
            self.assertTrue((await self.pair())['ok'])

    async def test_consumed_receipt_query_preserves_operator_updated_routes(self):
        await self.pair()
        configured = {'direct': '127.0.0.1:54321'}
        self.client.db.execute('UPDATE peers SET routes=? WHERE id=?', (json.dumps(configured), self.host.device))
        original_open = app.open_channel
        routes_used = []
        async def observe(*args, **kwargs):
            routes_used.append(args[2])
            return await original_open(*args, **kwargs)
        with mock.patch.object(app, 'open_channel', side_effect=observe), \
                mock.patch.object(self.host, 'prepare', side_effect=AssertionError('receipt query prepared')):
            self.assertTrue((await self.pair())['ok'])
        self.assertEqual(routes_used, [self.invite['routes']])
        self.assertEqual(self.client.peer(self.host.device)['routes'], configured)

    async def test_expired_pending_confirmation_is_readonly_and_fresh_staging_preserves_intents(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                # Independent roots make both ownership variants explicit.
                client = Store(self.root/('old-client' if legacy else 'owned-client'))
                try:
                    old = self.host.invite(self.routes)
                    digest = link_digest(encode_link(old, client.key_id))
                    client.save_offer_intent(old, digest, client.key_id)
                    client.stage(old)
                    if legacy:
                        client.db.execute('DELETE FROM pairing_reservations')
                    with mock.patch('time.time', return_value=old['expires']+1):
                        fresh = self.host.invite(self.routes)
                        fresh_digest = link_digest(encode_link(fresh, client.key_id))
                        before = client.db.total_changes
                        identity = client.receiver_offer_identity(fresh, fresh_digest, client.key_id)
                        self.assertEqual(identity['principal'], self.host.device)
                        self.assertEqual(client.db.total_changes, before)
                        client.save_offer_intent(fresh, fresh_digest, client.key_id)
                        client.stage(fresh)
                    self.assertEqual(client.peer(self.host.device)['expires'], fresh['expires'])
                    self.assertEqual(client.db.execute('SELECT invitation FROM pairing_reservations').fetchone(), (fresh['id'],))
                    self.assertIsNotNone(client.db.execute('SELECT 1 FROM pairing_intents WHERE id=?', (old['id'],)).fetchone())
                    self.assertEqual(client.key_status(self.host.key_id), 'active')
                finally:
                    client.close()

    async def test_old_completion_cannot_overwrite_new_owned_pending_routes(self):
        self.client.save_offer_intent(self.invite, self.digest, self.client.key_id)
        self.client.stage(self.invite)
        self.client.discard_pairing_stage(self.invite['id'])
        fresh = self.host.invite({'direct': '127.0.0.1:54321'})
        self.client.stage(fresh)
        before = self.client.peer(self.host.device)
        with self.assertRaisesRegex(Rejected, '^peer_already_reserved$'):
            self.client.remember(self.invite)
        self.assertEqual(self.client.peer(self.host.device), before)
        self.assertEqual(self.client.db.execute('SELECT invitation FROM pairing_reservations').fetchone(), (fresh['id'],))


if __name__ == '__main__':
    unittest.main()
