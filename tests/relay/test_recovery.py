"""Lost-key recovery state machine and offline peer approval tests."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest import mock

from session_peer_relay import recovery
from session_peer_relay.store import Rejected, Store


class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = Store(self.root/'restored')
        self.peer = Store(self.root/'peer')
        self._pair_records(self.old, self.peer, '127.0.0.1:41001', '127.0.0.1:41002')
        self.old.db.execute('CREATE TABLE IF NOT EXISTS recovery_tombstones('
            'principal TEXT PRIMARY KEY,generation INTEGER NOT NULL,snapshot REAL NOT NULL,reason TEXT NOT NULL)')
        self.old.db.execute('INSERT INTO recovery_tombstones VALUES(?,?,?,?)',
                            (self.old.device, self.old.generation, 1234.5, 'fixture'))
        self.old.db.execute('INSERT OR REPLACE INTO metadata VALUES("recovery_required","{}")')
        self.fresh = Store(self.root/'fresh')
        self.plan_id = str(uuid.uuid4())

    def tearDown(self):
        for store in (self.fresh, self.peer, self.old):
            try:
                store.close()
            except Exception:
                pass
        self.tmp.cleanup()

    def _pair_records(self, left, right, left_route, right_route):
        left.register_key(right.device, right.cert)
        left.db.execute('INSERT INTO peers VALUES(?,?,?,?,?,?)',
            (right.device, right.cert, 'paired', 0, json.dumps({'direct': left_route}),
             '["list","send"]'))
        right.register_key(left.device, left.cert)
        right.db.execute('INSERT INTO peers VALUES(?,?,?,?,?,?)',
            (left.device, left.cert, 'paired', 0, json.dumps({'direct': right_route}),
             '["list","send"]'))

    def test_direct_recovery_is_deterministic_resumable_and_keeps_archive_quarantined(self):
        done, unknown = str(uuid.uuid4()), str(uuid.uuid4())
        self.old.db.execute('INSERT INTO requests VALUES(?,?,?,"done",?)',
            (self.peer.device, done, 'a', json.dumps({'ok': True})))
        self.old.db.execute('INSERT INTO requests VALUES(?,?,?,"pending",NULL)',
            (self.peer.device, unknown, 'b'))
        first = recovery.begin(self.old, self.fresh, self.plan_id)
        self.assertEqual(first, recovery.begin(self.old, self.fresh, self.plan_id))
        self.assertEqual(first, recovery.status(self.fresh))
        report = first['recovery']
        self.assertEqual(report['restoredIdentity']['generation'], 0)
        self.assertNotIn('certificate', json.dumps(report).lower())
        self.assertIn('native:'+self.peer.device+':'+unknown, report['remainingGates'])
        self.assertTrue(self.fresh.recovery_required())

        # Removing the legacy marker cannot revive the archived principal: the
        # terminal tombstone is a separate durable authority boundary.
        self.old.db.execute('DELETE FROM metadata WHERE key="recovery_required"')
        self.assertTrue(self.old.recovery_required())
        with self.assertRaisesRegex(Rejected, 'recovery_required'):
            self.old.begin(self.peer.device, str(uuid.uuid4()), 'must stay archived')

        classify = str(uuid.uuid4())
        recovery.reconcile(self.fresh, classify, 'native', self.peer.device,
                           unknown, 'not_processed')
        self.assertEqual(recovery.reconcile(self.fresh, classify, 'native', self.peer.device,
                                            unknown, 'not_processed'), recovery.status(self.fresh))
        with self.assertRaisesRegex(Rejected, 'recovery_operation_conflict'):
            recovery.reconcile(self.fresh, classify, 'native', self.peer.device,
                               unknown, 'already_processed')

        request = recovery.peer_request(self.fresh, self.peer.device,
                                        {'direct': '127.0.0.1:42002'})
        approval = recovery.peer_approve(self.peer, request)
        # Lost approval responses are replayed byte-for-byte without a second mutation.
        self.assertEqual(approval, recovery.peer_approve(self.peer, request))
        self.assertEqual(self.peer.peer(self.old.device)['status'], 'revoked')
        self.assertEqual(self.peer.peer(self.fresh.device)['status'], 'paired')
        recovery.peer_commit(self.fresh, approval)
        self.assertEqual(recovery.peer_commit(self.fresh, approval), recovery.status(self.fresh))
        activated = recovery.activate(self.old, self.fresh)
        self.assertEqual(activated, recovery.activate(self.old, self.fresh))
        self.assertEqual(activated['recovery']['status'], 'active')
        self.assertFalse(self.fresh.recovery_required())
        self.assertTrue(self.old.recovery_required())

    def test_unknown_receipt_offline_peer_and_partial_commit_block_activation(self):
        second = Store(self.root/'second-peer')
        try:
            self._pair_records(self.old, second, '127.0.0.1:43001', '127.0.0.1:43002')
            recovery.begin(self.old, self.fresh, self.plan_id)
            receipt = str(uuid.uuid4())
            recovery.reconcile(self.fresh, str(uuid.uuid4()), 'outgoing', self.peer.device,
                               receipt, 'unknown')
            request = recovery.peer_request(self.fresh, self.peer.device,
                                            {'direct': '127.0.0.1:44001'})
            recovery.peer_commit(self.fresh, recovery.peer_approve(self.peer, request))
            report = recovery.status(self.fresh)['recovery']
            self.assertIn('outgoing:'+self.peer.device+':'+receipt, report['remainingGates'])
            self.assertIn('peer:'+second.device, report['remainingGates'])
            with self.assertRaisesRegex(Rejected, 'recovery_gates_incomplete'):
                recovery.activate(self.old, self.fresh)
        finally:
            second.close()

    def test_approval_rejects_tampering_and_unrelated_old_identity(self):
        recovery.begin(self.old, self.fresh, self.plan_id)
        request = recovery.peer_request(self.fresh, self.peer.device,
                                        {'direct': '127.0.0.1:45001'})
        tampered = {**request, 'routes': {'direct': '127.0.0.1:9'}}
        with self.assertRaisesRegex(Rejected, 'invalid_recovery_proof'):
            recovery.peer_approve(self.peer, tampered)
        request = {**request, 'oldPrincipal': 'a'*64}
        payload = {k: request[k] for k in request if k != 'proof'}
        request['proof'] = recovery._sign(self.fresh, payload)
        with self.assertRaisesRegex(Rejected, 'old_identity_not_paired'):
            recovery.peer_approve(self.peer, request)

    def test_lost_archived_private_key_does_not_block_safe_fresh_activation(self):
        recovery.begin(self.old, self.fresh, self.plan_id)
        request = recovery.peer_request(self.fresh, self.peer.device,
                                        {'direct': '127.0.0.1:46001'})
        recovery.peer_commit(self.fresh, recovery.peer_approve(self.peer, request))
        old_root = self.old.root
        self.old.close()
        (old_root/'identity.key').unlink()
        self.old = Store(old_root)
        self.assertTrue(self.old.recovery_required())
        self.assertEqual(recovery.activate(self.old, self.fresh)['recovery']['status'], 'active')
        self.assertFalse((old_root/'identity.key').exists())

    def test_phase_crashes_roll_back_and_resume_with_fixed_identifiers(self):
        with mock.patch('session_peer_relay.recovery._save', side_effect=RuntimeError('begin crash')):
            with self.assertRaisesRegex(RuntimeError, 'begin crash'):
                recovery.begin(self.old, self.fresh, self.plan_id)
        self.assertIsNone(self.fresh.db.execute(
            'SELECT value FROM metadata WHERE key="recovery_origin"').fetchone())
        recovery.begin(self.old, self.fresh, self.plan_id)
        request = recovery.peer_request(self.fresh, self.peer.device,
                                        {'direct': '127.0.0.1:47001'})
        actual_register = self.peer.register_key
        with mock.patch.object(self.peer, 'register_key', side_effect=RuntimeError('approval crash')):
            with self.assertRaisesRegex(RuntimeError, 'approval crash'):
                recovery.peer_approve(self.peer, request)
        self.assertEqual(self.peer.peer(self.old.device)['status'], 'paired')
        self.assertIsNone(self.peer.peer(self.fresh.device))
        approval = recovery.peer_approve(self.peer, request)
        self.assertIsNotNone(actual_register)

        actual_save = recovery._save
        with mock.patch('session_peer_relay.recovery._save', side_effect=RuntimeError('commit crash')):
            with self.assertRaisesRegex(RuntimeError, 'commit crash'):
                recovery.peer_commit(self.fresh, approval)
        self.assertIsNone(self.fresh.peer(self.peer.device))
        recovery.peer_commit(self.fresh, approval)

        with mock.patch('session_peer_relay.recovery._save', side_effect=RuntimeError('activate crash')):
            with self.assertRaisesRegex(RuntimeError, 'activate crash'):
                recovery.activate(self.old, self.fresh)
        self.assertTrue(self.fresh.recovery_required())
        self.assertIsNotNone(actual_save)
        self.assertEqual(recovery.activate(self.old, self.fresh)['recovery']['status'], 'active')


if __name__ == '__main__':
    unittest.main()
