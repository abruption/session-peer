"""Offline snapshot fencing for new pairing tables; no native or network calls."""
import json
import time
import unittest
from unittest import mock

# Reuse the platform/dependency guard and private state fixture, not its tests.
from tests.relay import test_pairing_offers as offers
from session_peer_relay.identity import private_write
from session_peer_relay.lifecycle import backup, restore
from session_peer_relay.pairing_links import encode_link, link_digest
from session_peer_relay.store import Store, Rejected


class OfferRestore(unittest.TestCase):
    setUp = offers.Offers.setUp
    prepare = offers.Offers.prepare
    commit = offers.Offers.commit

    def test_eight_day_restored_pairing_history_is_immutable_under_lifecycle_calls(self):
        routes = {'direct': '127.0.0.1:1'}
        consumed = self.host.create_offer(routes, self.client.key_id)
        self.prepare(consumed)
        self.commit(consumed)
        incoming = self.other.create_offer(routes, self.host.key_id)
        digest = link_digest(encode_link(incoming, self.host.key_id))
        self.host.save_offer_intent(incoming, digest, self.host.key_id)
        reserved = self.host.create_offer(routes, self.other.key_id)
        self.prepare(reserved, client=self.other)
        policy = self.root/'forensic-policy.json'
        private_write(policy, json.dumps({'targets': {
            'fixture': {'agent': 'claude', 'target': 'fixture'}}, 'peers': {}}))
        snapshot = self.root/'forensic-snapshot'
        backup(self.host, snapshot, policy)
        destination = self.root/'forensic-restored'
        restore(snapshot, destination)
        recovered = Store(destination)
        self.addCleanup(recovered.close)
        before = recovered.db.serialize()
        changes = recovered.db.total_changes
        actions = (
            lambda: recovered.prepare({'invitation': reserved['id'], 'secret': reserved['secret'],
                                        'certificate': self.other.cert, 'offer': True}),
            lambda: recovered.commit(self.client.key_id, consumed['id'], authenticated_key=self.client.key_id, offer=True),
            lambda: recovered.create_offer(routes, 'a'*64),
            lambda: recovered.cancel_offer(reserved['id']),
            lambda: recovered.stage(incoming),
            lambda: recovered.remember(incoming),
            lambda: recovered.discard_pairing_stage(reserved['id']),
            lambda: recovered.invite(routes),
            lambda: recovered.offer_identity('a'*64),
            lambda: recovered.save_offer_intent(incoming, digest, recovered.key_id),
            lambda: recovered.receiver_offer_identity(incoming, digest, recovered.key_id),
        )
        with mock.patch('time.time', return_value=time.time()+8*86400):
            for action in actions:
                with self.assertRaisesRegex(Rejected, '^recovery_required$'):
                    action()
                self.assertEqual(recovered.db.total_changes, changes)
                self.assertTrue(recovered.db.serialize() == before, 'restored pairing evidence changed')
            for invite, expected in ((consumed, 'consumed'), (reserved, 'reserved')):
                result = recovered.offer_status(invite['id'])
                self.assertEqual(result['status'], expected)
                self.assertTrue(result['historical'])
                self.assertTrue(result['recoveryRequired'])
                self.assertEqual(recovered.db.total_changes, changes)
                self.assertTrue(recovered.db.serialize() == before, 'diagnostics rewrote restored pairing evidence')

    def test_snapshot_keeps_all_new_tables_but_never_reactivates_authority(self):
        routes = {'direct': '127.0.0.1:1'}
        consumed = self.host.create_offer(routes, self.client.key_id)
        self.prepare(consumed)
        self.commit(consumed)
        cancelled = self.host.create_offer(routes, self.other.key_id)
        self.host.cancel_offer(cancelled['id'])
        incoming = self.other.create_offer(routes, self.host.key_id)
        digest = link_digest(encode_link(incoming, self.host.key_id))
        self.host.save_offer_intent(incoming, digest, self.host.key_id)
        reserved = self.host.create_offer(routes, self.other.key_id)
        self.prepare(reserved, client=self.other)
        tables = ('pairing_offers', 'pairing_reservations', 'pairing_limits', 'pairing_intents')
        counts = {table: self.host.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                  for table in tables}
        policy = self.root/'policy.json'
        private_write(policy, json.dumps({'targets': {
            'fixture': {'agent': 'claude', 'target': 'fixture'}}, 'peers': {}}))
        snapshot = self.root/'snapshot'
        backup(self.host, snapshot, policy)
        # The live receiver commits after the snapshot; restoring must not make
        # the older reserved invitation usable again, even with the right key.
        self.commit(reserved, client=self.other)
        destination = self.root/'restored'
        restore(snapshot, destination)
        recovered = Store(destination)
        self.addCleanup(recovered.close)
        self.assertTrue(recovered.recovery_required())
        for table, count in counts.items():
            self.assertEqual(recovered.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0], count)
        self.assertEqual(recovered.offer_status(consumed['id'])['status'], 'consumed')
        self.assertEqual(recovered.offer_status(cancelled['id'])['status'], 'cancelled')
        self.assertEqual(recovered.offer_status(reserved['id'])['status'], 'reserved')
        for invitation, client in ((consumed, self.client), (reserved, self.other)):
            with self.assertRaisesRegex(Rejected, 'recovery_required'):
                recovered.commit(client.key_id, invitation['id'],
                                 authenticated_key=client.key_id, offer=True)
            with self.assertRaisesRegex(Rejected, 'recovery_required'):
                recovered.prepare({'invitation': invitation['id'], 'secret': invitation['secret'],
                                   'certificate': client.cert, 'offer': True})
        with self.assertRaisesRegex(Rejected, 'recovery_required'):
            recovered.create_offer(routes, 'a'*64)
