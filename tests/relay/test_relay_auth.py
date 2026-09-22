"""OAuth admission boundary, independent of an external login provider."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest import mock

from tests.relay import test_native_relay as platform_guard
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from session_peer_relay.auth import ControlAdmission, AdmissionDenied, room_id


def encoded(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def jwk(key):
    point = key.public_key().public_numbers()
    return {'kty': 'EC', 'crv': 'P-256', 'x': encoded(point.x.to_bytes(32, 'big')), 'y': encoded(point.y.to_bytes(32, 'big'))}


class Admission(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'state.json'
        self.signer, self.device_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
        self.device, self.receiver, self.fingerprint = 'a'*64, 'b'*64, 'c'*64
        self.issuer = 'https://relay.example.test'
        self.snapshot = {'issuedAt': int(time.time()), 'expiresAt': int(time.time())+180, 'schemaVersion': 1, 'issuer': self.issuer, 'audience': self.issuer,
                         'jwks': {'keys': [{**jwk(self.signer), 'kid': 'test-key'}]},
                         'devices': {p: {'userId': 'user-one', 'keyFingerprint': self.fingerprint, 'generation': 0, 'revoked': False} for p in (self.device, self.receiver)}}
        self.save()
        self.auth = ControlAdmission(self.path, self.issuer)

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.snapshot['revision'] = self.snapshot.get('revision', 0)+1
        self.path.write_text(json.dumps(self.snapshot))

    def ticket(self, **overrides):
        now = int(time.time())
        claims = {'iss': self.issuer, 'aud': self.issuer, 'iat': now, 'exp': now+60,
                  'sub': 'user-one', 'jti': str(uuid.uuid4()), 'devicePrincipal': self.device,
                  'receiverPrincipal': self.receiver, 'keyFingerprint': self.fingerprint,
                  'keyGeneration': 0, 'role': 'client', 'room': room_id('user-one', self.receiver),
                  'cnf': {'jwk': jwk(self.device_key)}, **overrides}
        header = encoded(json.dumps({'alg': 'ES256', 'kid': 'test-key'}).encode())
        payload = encoded(json.dumps(claims).encode())
        signing = (header+'.'+payload).encode()
        r, s = decode_dss_signature(self.signer.sign(signing, ec.ECDSA(hashes.SHA256())))
        token = signing.decode()+'.'+encoded(r.to_bytes(32, 'big')+s.to_bytes(32, 'big'))
        proof = encoded(self.device_key.sign(b'session-peer-admission-v1:'+token.encode(), ec.ECDSA(hashes.SHA256())))
        return token, proof

    def test_valid_ticket_requires_device_proof_and_cannot_be_reused(self):
        token, proof = self.ticket()
        with self.assertRaises(AdmissionDenied):
            self.auth.authorize(token, encoded(b'wrong'))
        account = self.auth.authorize(token, proof)
        self.assertEqual(account['userId'], 'user-one')
        self.assertTrue(self.auth.active(account))
        with self.assertRaises(AdmissionDenied):
            self.auth.authorize(token, proof)

    def test_revocation_and_generation_change_invalidate_existing_account(self):
        account = self.auth.authorize(*self.ticket())
        self.snapshot['devices'][self.device]['generation'] = 1
        self.save()
        self.assertFalse(self.auth.active(account))
        self.snapshot['devices'][self.device]['generation'] = 0
        self.snapshot['devices'][self.receiver]['revoked'] = True
        self.save()
        self.assertFalse(self.auth.active(account))
        with self.assertRaises(AdmissionDenied):
            self.auth.authorize(*self.ticket())

    def test_wrong_audience_owner_room_expiry_role_are_denied(self):
        for override in ({'aud': 'https://evil.test'}, {'sub': 'user-two'}, {'room': 'chosen-room'},
                         {'exp': int(time.time())-1}, {'exp': int(time.time())+600},
                         {'role': 'receiver'}, {'keyGeneration': 1}):
            with self.subTest(override=override), self.assertRaises(AdmissionDenied):
                self.auth.authorize(*self.ticket(**override))

    def test_cross_user_receiver_and_missing_state_fail_closed(self):
        self.snapshot['devices'][self.receiver]['userId'] = 'other-user'
        self.save()
        with self.assertRaises(AdmissionDenied):
            self.auth.authorize(*self.ticket())
        self.path.unlink()
        with self.assertRaises(AdmissionDenied):
            self.auth.authorize(*self.ticket())

    def test_unknown_signer_and_tampered_payload_are_denied(self):
        ticket = self.ticket()
        self.snapshot['jwks']['keys'] = []
        self.save()
        with self.assertRaises(AdmissionDenied):
            self.auth.authorize(*ticket)

    def test_consumed_ticket_survives_restart_and_locks_other_writers(self):
        replay = Path(self.temp.name)/'spent.json'
        from session_peer_relay.identity import private_write
        private_write(replay, json.dumps({'schemaVersion': 1, 'spent': {}, 'revision': 0, 'digest': None, 'notBefore': 0}))
        first = ControlAdmission(self.path, self.issuer, replay)
        ticket = self.ticket()
        try:
            first.authorize(*ticket)
            with self.assertRaisesRegex(ValueError, 'admission_state_in_use'):
                ControlAdmission(self.path, self.issuer, replay)
        finally:
            first.close()
        second = ControlAdmission(self.path, self.issuer, replay)
        try:
            with self.assertRaises(AdmissionDenied):
                second.authorize(*ticket)
        finally:
            second.close()

    def test_stale_control_snapshot_blocks_admission_and_existing_sessions(self):
        account = self.auth.authorize(*self.ticket())
        self.snapshot['issuedAt'] = time.time()-181
        self.snapshot['expiresAt'] = time.time()-1
        self.save()
        self.assertFalse(self.auth.active(account))
        with self.assertRaises(AdmissionDenied):
            self.auth.authorize(*self.ticket())

    def test_missing_replay_state_refuses_start_and_explicit_bootstrap_waits(self):
        from session_peer_relay.auth import initialize_replay
        replay = Path(self.temp.name)/'spent.json'
        with self.assertRaisesRegex(ValueError, 'admission_replay_state_missing'):
            ControlAdmission(self.path, self.issuer, replay)
        initialized = initialize_replay(replay)
        with self.assertRaises(FileExistsError):
            initialize_replay(replay)
        auth = ControlAdmission(self.path, self.issuer, replay)
        try:
            with self.assertRaises(AdmissionDenied):
                auth.authorize(*self.ticket())
            after = initialized['admissionNotBefore']+1
            with mock.patch('time.time', return_value=after):
                auth.authorize(*self.ticket())
        finally:
            auth.close()
        replay.unlink()
        with self.assertRaisesRegex(ValueError, 'admission_replay_state_missing'):
            ControlAdmission(self.path, self.issuer, replay)

    def test_corrupt_replay_releases_lock_and_disk_failure_never_issues_account(self):
        from session_peer_relay.identity import private_write
        replay = Path(self.temp.name)/'spent.json'
        private_write(replay, '{invalid')
        with self.assertRaises(ValueError):
            ControlAdmission(self.path, self.issuer, replay)
        private_write(replay, json.dumps({'schemaVersion': 1, 'spent': {}, 'revision': 0, 'digest': None, 'notBefore': 0}))
        auth = ControlAdmission(self.path, self.issuer, replay)
        try:
            auth.state()
            with mock.patch('session_peer_relay.auth.private_write', side_effect=OSError('full')):
                with self.assertRaises(AdmissionDenied):
                    auth.authorize(*self.ticket())
            self.assertEqual(auth.used, {})
        finally:
            auth.close()

    def test_rollback_of_public_state_is_blocked_after_restart(self):
        replay = Path(self.temp.name)/'spent.json'
        from session_peer_relay.identity import private_write
        private_write(replay, json.dumps({'schemaVersion': 1, 'spent': {}, 'revision': 0, 'digest': None, 'notBefore': 0}))
        previous = self.path.read_text()
        first = ControlAdmission(self.path, self.issuer, replay)
        account = first.authorize(*self.ticket())
        self.snapshot['devices'][self.device]['revoked'] = True
        self.save()
        self.assertFalse(first.active(account))
        first.close()
        self.path.write_text(previous)
        second = ControlAdmission(self.path, self.issuer, replay)
        try:
            self.assertFalse(second.active(account))
            with self.assertRaises(AdmissionDenied):
                second.authorize(*self.ticket())
        finally:
            second.close()

class ManagedWebSocket(unittest.IsolatedAsyncioTestCase):
    async def test_real_admission_cookie_splice_and_live_revocation(self):
        import asyncio
        from session_peer_relay.relay import Relay
        from session_peer_relay.wire import relay_stream
        helper = Admission()
        helper.setUp()
        relay = Relay([], control=helper.auth)
        server = await relay.start('127.0.0.1', 0)
        url = 'ws://127.0.0.1:'+str(server.sockets[0].getsockname()[1])+'/v1/connect'
        class Credential:
            def __init__(self, receiver=False): self.receiver = receiver
            def headers(self, relay_url):
                token, proof = helper.ticket(**({'role': 'receiver', 'devicePrincipal': helper.receiver} if self.receiver else {}))
                return {'Authorization': 'Bearer '+token, 'X-Session-Peer-Proof': proof}
        receiver = client = None
        waiting = asyncio.create_task(relay_stream(url, Credential(True)))
        try:
            client = await relay_stream(url, Credential())
            receiver = await waiting
            await receiver.send(b'opaque-fixture-frame')
            self.assertEqual(await client.recv(), b'opaque-fixture-frame')
            helper.snapshot['devices'][helper.device]['revoked'] = True
            helper.save()
            with self.assertRaises(Exception):
                await asyncio.wait_for(client.recv(), 3)
        finally:
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
            if client: await client.close()
            if receiver: await receiver.close()
            server.close(); await server.wait_closed()
            helper.tearDown()
