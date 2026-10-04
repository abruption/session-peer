"""An invitation grants pairing, not authority to select another principal."""
import pathlib
import tempfile
import unittest

try:
    from session_peer_relay.store import Store, Rejected
except ImportError:
    raise unittest.SkipTest('optional relay dependencies unavailable')


class PairingPrincipal(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = pathlib.Path(directory.name)
        self.receiver, self.attacker, self.victim = [Store(root / name) for name in ('r', 'a', 'v')]
        for store in (self.receiver, self.attacker, self.victim):
            self.addCleanup(store.close)
        self.invite = self.receiver.invite({})

    def prepare(self, **claims):
        return self.receiver.prepare(dict(invitation=self.invite['id'], secret=self.invite['secret'],
                                          certificate=self.attacker.cert, **claims))

    def test_unproven_principal_cannot_be_registered_or_consume_invitation(self):
        for generation in (0, 1, 100):
            with self.subTest(generation=generation), self.assertRaisesRegex(Rejected, 'unproven_principal'):
                self.prepare(principal=self.victim.device, generation=generation)
            self.assertIsNone(self.receiver.peer(self.victim.device))
            self.assertEqual(self.receiver.db.execute('SELECT count(*) FROM peer_keys').fetchone()[0], 0)
            self.assertIsNone(self.receiver.db.execute('SELECT peer FROM invites').fetchone()[0])
        # The rightful holder can still reserve and commit the same invitation.
        self.receiver.prepare(dict(invitation=self.invite['id'], secret=self.invite['secret'],
                                   certificate=self.victim.cert))
        self.assertTrue(self.receiver.commit(self.victim.key_id)['ok'])

    def test_generation_zero_matches_certificate(self):
        self.assertTrue(self.prepare(principal=self.attacker.device, generation=0)['ok'])
        self.assertTrue(self.receiver.commit(self.attacker.key_id)['ok'])

    def test_unanchored_generation_is_not_an_identity_proof(self):
        for generation in (True, -1, '0', 1):
            with self.subTest(generation=generation), self.assertRaises(Rejected):
                self.prepare(principal=self.attacker.device, generation=generation)

    def test_known_active_rotated_binding_can_be_reused_but_not_changed(self):
        self.receiver.register_key(self.victim.device, self.attacker.cert, 2)
        with self.assertRaises(Rejected):
            self.prepare(principal=self.victim.device, generation=3)
        self.assertTrue(self.prepare(principal=self.victim.device, generation=2)['ok'])

    def test_pending_or_retired_key_does_not_authorize_pairing(self):
        for status in ('pending', 'retired', 'revoked'):
            self.receiver.db.execute('DELETE FROM peer_keys')
            self.receiver.register_key(self.victim.device, self.attacker.cert, 2)
            self.receiver.db.execute('UPDATE peer_keys SET status=?', (status,))
            with self.subTest(status=status), self.assertRaises(Rejected):
                self.prepare(principal=self.victim.device, generation=2)
