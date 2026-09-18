"""Opt-in Node/Python contract tests with seeded, disposable first-party sessions.

Run npm ci && npm run build in control/, then set SESSION_PEER_CONTROL_INTEGRATION=1.
Only the test HTTP transport replaces public TLS; production OAuth is not mocked
or enabled in the application. Native effects use the existing local socket fixture.
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
import urllib.request
import uuid
from unittest import mock

from tests import test_native_relay as native_tests
from session_peer_relay import control
from session_peer_relay.auth import ControlAdmission
from session_peer_relay.identity import private_write
from session_peer_relay.rotation import rotate
from session_peer_relay.store import Rejected, Store


@unittest.skipUnless(os.environ.get('SESSION_PEER_CONTROL_INTEGRATION') == '1',
                     'explicit Node control integration environment required')
class ControlIntegration(unittest.IsolatedAsyncioTestCase):
    call = native_tests.NativeRelay.call

    async def asyncSetUp(self):
        await native_tests.NativeRelay.asyncSetUp(self)
        self.addAsyncCleanup(native_tests.NativeRelay.asyncTearDown, self)
        fixture = Path(__file__).parent/'fixtures/control-server.mjs'
        node_root = self.root/'control'
        node_root.mkdir(mode=0o700)
        log = (node_root/'process.log').open('w')
        self.addCleanup(log.close)
        self.node = subprocess.Popen(['node', str(fixture), str(node_root)], stdout=log, stderr=log)
        async def stop():
            if self.node.poll() is None:
                self.node.terminate()
            try:
                await asyncio.to_thread(self.node.wait, 5)
            except subprocess.TimeoutExpired:
                self.node.kill()
                await asyncio.to_thread(self.node.wait)
        self.addAsyncCleanup(stop)
        ready = node_root/'ready.json'
        deadline = time.monotonic()+15
        while not ready.exists():
            if self.node.poll() is not None or time.monotonic() > deadline:
                self.fail('Node fixture failed to start; inspect its private process.log')
            await asyncio.sleep(0.05)
        self.info = json.loads(ready.read_text())
        self.auth = ControlAdmission(self.info['stateFile'], self.info['origin'])
        self.addCleanup(self.auth.close)
        build_opener = urllib.request.build_opener
        info = self.info
        class TestTransport:
            def __init__(self, *handlers):
                self.opener = build_opener(*handlers)
            def open(self, request, timeout):
                # Preserve Origin and all auth headers; route only fixture traffic.
                if not request.full_url.startswith(info['origin']+'/api/'):
                    raise AssertionError('unexpected external request')
                path = request.full_url[len(info['origin']):]
                local = urllib.request.Request('http://127.0.0.1:'+str(info['port'])+path,
                    data=request.data, headers=dict(request.header_items()), method=request.get_method())
                return self.opener.open(local, timeout=timeout)
        transport = mock.patch('urllib.request.build_opener', TestTransport)
        transport.start()
        self.addCleanup(transport.stop)
        for store in (self.client, self.host):
            self.login(store)
            control.enroll(store, 'fixture-device', str(uuid.uuid4()))

    def login(self, store, account=0):
        private_write(store.root/'login.json', json.dumps({'server': self.info['origin'],
            'token': self.info['accounts'][account]['token'], 'expiresAt': time.time()+300}))

    def headers(self, store):
        return control.DeviceCredential(store, self.host.device, 'client').headers(
            'wss://relay.example.test/v1/connect')

    def authorize(self, headers):
        return self.auth.authorize(headers['Authorization'].removeprefix('Bearer '),
                                   headers['X-Session-Peer-Proof'])

    async def test_real_node_enrollment_admission_and_revocation(self):
        account = self.authorize(self.headers(self.client))
        self.assertEqual(account['keyFingerprint'], self.client.key_id)
        self.assertEqual(account['keyGeneration'], 0)
        self.assertEqual(account['receiverPrincipal'], self.host.device)
        self.assertTrue(self.auth.active(account))
        self.assertEqual(Path(self.info['stateFile']).parent.stat().st_mode & 0o777, 0o755)
        self.assertEqual(Path(self.info['stateFile']).stat().st_mode & 0o777, 0o644)
        control.call(self.info['origin'], '/api/relay/devices/'+self.client.device+'/revoke', {},
                     self.info['accounts'][0]['token'])
        self.assertFalse(self.auth.active(account))
        with self.assertRaises(Rejected):
            self.headers(self.client)

    async def test_managed_rotation_preserves_native_receipt_and_lost_response_retry(self):
        ident, operation = str(uuid.uuid4()), str(uuid.uuid4())
        body = {'target': 'review', 'message': 'cross-language rotation fixture'}
        self.assertTrue((await self.call('send', body, ident))['ok'])
        old_account = self.authorize(self.headers(self.client))
        actual = self.receiver.dispatch
        interrupted = False
        async def lose(peer, value):
            nonlocal interrupted
            result = await actual(peer, value)
            if value.get('op') == 'rotation.commit' and not interrupted:
                interrupted = True
                return {'ok': False, 'status': 'unknown'}
            return result
        self.receiver.dispatch = lose
        first = await rotate(self.client, operation, 'direct', None, use_login=True)
        self.assertFalse(first['ok'])
        result = await rotate(self.client, operation, 'direct', None, use_login=True)
        self.assertTrue(result['ok'], result)
        self.assertFalse(self.auth.active(old_account))
        account = self.authorize(self.headers(self.client))
        self.assertEqual(account['keyGeneration'], 1)
        self.assertEqual(account['keyFingerprint'], self.client.key_id)
        self.assertTrue((await self.call('send', body, ident))['duplicate'])
        self.assertEqual(len(self.effects), 1)
        devices = control.call(self.info['origin'], '/api/relay/devices',
                               token=self.info['accounts'][0]['token'])['devices']
        self.assertEqual(next(d for d in devices if d['principal'] == self.client.device)['name'],
                         'fixture-device')
        outcome = control.call(self.info['origin'], '/api/relay/operations/'+operation,
                               token=self.info['accounts'][0]['token'])
        self.assertNotIn('error', outcome)

    async def test_other_owner_cannot_join_receiver_room(self):
        other = Store(self.root/'other-account')
        try:
            self.login(other, 1)
            control.enroll(other, 'other-account', str(uuid.uuid4()))
            with self.assertRaises(Rejected):
                self.headers(other)
        finally:
            other.close()
