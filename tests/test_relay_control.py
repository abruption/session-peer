"""Browser-login secret handling and device-proof client contract."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from tests import test_native_relay as platform_guard
from session_peer_relay.control import login, origin, DeviceCredential, enroll
from session_peer_relay.identity import private_write
from session_peer_relay.store import Store, Rejected


class ControlClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name)/'device')
        self.server = 'https://relay.example.test'

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    async def test_login_polls_and_keeps_private_token_out_of_output(self):
        code = {'verification_uri': self.server+'/device', 'user_code': 'ABCD-EFGH',
                'device_code': 'SECRET-DEVICE-CODE-UNIQUE', 'expires_in': 600, 'interval': 5}
        token = 'SECRET-SESSION-TOKEN-UNIQUE'
        output = io.StringIO()
        with patch('session_peer_relay.control.call', side_effect=[code, Rejected('slow_down'),
                Rejected('authorization_pending'), {'access_token': token, 'token_type': 'Bearer', 'expires_in': 600}]), \
             patch('session_peer_relay.control.asyncio.sleep', new_callable=AsyncMock) as sleep, \
             contextlib.redirect_stdout(output):
            result = await login(self.store, self.server, True)
        self.assertTrue(result['loggedIn'])
        self.assertEqual([x.args[0] for x in sleep.call_args_list], [5, 10, 10])
        self.assertNotIn(token, output.getvalue())
        self.assertNotIn(code['device_code'], output.getvalue())
        path = self.store.root/'login.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(path.read_text())['token'], token)

    async def test_denied_login_does_not_write_credentials(self):
        code = {'verification_uri': self.server+'/device', 'user_code': 'ABCD',
                'device_code': '1234567890123456', 'expires_in': 600, 'interval': 5}
        with patch('session_peer_relay.control.call', side_effect=[code, Rejected('access_denied')]), \
             patch('session_peer_relay.control.asyncio.sleep', new_callable=AsyncMock), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(Rejected, 'access_denied'):
                await login(self.store, self.server, True)
        self.assertFalse((self.store.root/'login.json').exists())

    async def test_verification_link_cannot_redirect_to_another_origin(self):
        with patch('session_peer_relay.control.call', return_value={'verification_uri': 'https://evil.test/device'}):
            with self.assertRaisesRegex(Rejected, 'invalid_verification_origin'):
                await login(self.store, self.server, True)
        for value in ['http://remote.test', 'https://user:secret@relay.test', 'https://relay.test/other', 'https://relay.test/?token=x']:
            with self.assertRaises(Rejected):
                origin(value)

    async def test_enrollment_signs_only_domain_separated_challenge(self):
        private_write(self.store.root/'login.json', json.dumps({'server': self.server, 'token': 'secret', 'expiresAt': time.time()+600}))
        with patch('session_peer_relay.control.call', return_value={'challengeId': 'x', 'proofMessage': 'arbitrary-signing-request'}):
            with self.assertRaisesRegex(Rejected, 'invalid_control_challenge'):
                enroll(self.store, 'test', 'operation')
        credential = DeviceCredential(self.store, 'f'*64, 'client')
        with self.assertRaisesRegex(Rejected, 'control_relay_origin_mismatch'):
            credential.headers('wss://different.test/v1/connect')

    async def test_committed_enrollment_queries_receipt_without_new_signature(self):
        import uuid
        ident = str(uuid.uuid4())
        private_write(self.store.root/'login.json', json.dumps({'server': self.server, 'token': 'secret', 'expiresAt': time.time()+600}))
        receipt = {'operationId': ident, 'committed': True, 'principal': self.store.device,
                   'keyGeneration': 0, 'keyFingerprint': self.store.key_id}
        with patch('session_peer_relay.control.call', side_effect=[Rejected('operation_already_committed'), receipt]) as call, \
             patch('session_peer_relay.control.sign') as sign:
            self.assertEqual(enroll(self.store, 'test', ident), receipt)
            self.assertEqual(call.call_args.args[1], '/api/relay/operations/'+ident)
            sign.assert_not_called()
        with patch('session_peer_relay.control.call', side_effect=[Rejected('operation_already_committed'), {**receipt, 'keyGeneration': 1}]):
            with self.assertRaisesRegex(Rejected, 'invalid_operation_receipt'):
                enroll(self.store, 'test', ident)
        with patch('session_peer_relay.control.call', side_effect=Rejected('operation_conflict')) as call:
            with self.assertRaisesRegex(Rejected, 'operation_conflict'):
                enroll(self.store, 'changed-name', ident)
            self.assertEqual(call.call_count, 1)
