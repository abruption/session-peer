import tempfile
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

try:
    from session_peer_relay import recovery, rotation
    from session_peer_relay.store import Store, Rejected
except ModuleNotFoundError:
    raise unittest.SkipTest('optional relay dependencies not installed')


class RecoveryGeneration(unittest.IsolatedAsyncioTestCase):
    async def test_rotated_peers_recover_and_rotate_again_with_v1_and_v2_approvals(self):
        for generation in (0, 1, 3):
            for legacy in (False, True):
                with self.subTest(generation=generation, legacy=legacy), tempfile.TemporaryDirectory() as directory:
                    old, peer, fresh = [Store(Path(directory)/n) for n in ('old', 'peer', 'fresh')]
                    try:
                        old.remember(peer.invite({'direct': '127.0.0.1:1'}))
                        peer.remember(old.invite({'direct': '127.0.0.1:2'}))
                        target = old
                        async def exchange(store, remote, op, body=None, **kwargs):
                            if op == 'rotation.prepare':
                                return rotation.remote_prepare(target, peer.device, peer.key_id, body)
                            if op == 'rotation.commit':
                                from session_peer_relay.identity import fingerprint, private_read
                                key = fingerprint(private_read(store.identity_root/'identity.pem'))
                                return rotation.remote_commit(target, peer.device, key, body)
                            return rotation.remote_status(target, peer.device, body)
                        with patch('session_peer_relay.app.exchange', side_effect=exchange):
                            for _ in range(generation):
                                self.assertTrue((await rotation.rotate(peer, str(uuid.uuid4()), 'direct', None))['ok'])
                            old.db.execute('INSERT INTO recovery_tombstones VALUES(?,?,?,?)',
                                           (old.device, old.generation, 1234, 'fixture'))
                            recovery.begin(old, fresh, str(uuid.uuid4()))
                            request = recovery.peer_request(fresh, peer.device, {'direct': '127.0.0.1:3'})
                            approval = recovery.peer_approve(peer, request)
                            self.assertEqual(approval, recovery.peer_approve(peer, request))
                            if legacy:
                                approval.pop('peerGeneration')
                                approval['schemaVersion'] = 1
                                approval['proof'] = recovery._sign(peer, {k: v for k, v in approval.items() if k != 'proof'})
                                if generation:
                                    plan = recovery._load(fresh)
                                    original = plan['peers'][0].pop('generation')
                                    with patch.object(recovery, '_load', return_value=plan):
                                        with self.assertRaisesRegex(Rejected, 'recovery_generation_required'):
                                            recovery.peer_commit(fresh, approval)
                                    plan['peers'][0]['generation'] = original
                            else:
                                for bad in (True, -1, generation + 1):
                                    forged = {**approval, 'peerGeneration': bad}
                                    with self.assertRaises(Rejected):
                                        recovery.peer_commit(fresh, forged)
                                    forged['proof'] = recovery._sign(peer, {k: v for k, v in forged.items() if k != 'proof'})
                                    with self.assertRaises(Rejected):
                                        recovery.peer_commit(fresh, forged)
                            result = recovery.peer_commit(fresh, approval)
                            self.assertEqual(result, recovery.peer_commit(fresh, approval))
                            self.assertEqual(fresh.db.execute('SELECT generation FROM peer_keys WHERE principal=?',
                                                             (peer.device,)).fetchone()[0], generation)
                            recovery.activate(old, fresh)
                            target = fresh
                            self.assertTrue((await rotation.rotate(peer, str(uuid.uuid4()), 'direct', None))['ok'])
                            self.assertEqual(peer.generation, generation + 1)
                    finally:
                        for store in (fresh, peer, old): store.close()
