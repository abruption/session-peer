"""Opt-in Node/Python contract tests with seeded, disposable first-party sessions.

Run npm ci && npm run build in control/, then set SESSION_PEER_CONTROL_INTEGRATION=1.
Only the test HTTP transport replaces public TLS; production OAuth is not mocked
or enabled in the application. Native effects use the existing local socket fixture.
"""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
import urllib.request
import uuid
from unittest import mock

from tests.relay import test_native_relay as native_tests
from websockets.exceptions import ConnectionClosed
from session_peer_relay import control
from session_peer_relay import cli
from session_peer_relay.app import open_channel
from session_peer_relay.relay import Relay
from session_peer_relay import wire
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
        fixture = Path(__file__).parents[1] / 'fixtures' / 'control-server.mjs'
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
                if request.full_url.startswith(info['origin']+'/api/'):
                    port = info['port']
                elif request.full_url == info['origin']+'/v1/session' and 'relayPort' in info:
                    port = info['relayPort']
                else:
                    raise AssertionError('unexpected external request')
                path = request.full_url[len(info['origin']):]
                local = urllib.request.Request('http://127.0.0.1:'+str(port)+path,
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

    async def test_sanitized_alpha_database_migrates_without_losing_authority(self):
        root = self.root/'alpha-control'
        root.mkdir(mode=0o700)
        log = (root/'process.log').open('w')
        self.addCleanup(log.close)
        fixture = Path(__file__).parents[1] / 'fixtures' / 'control-server.mjs'
        env = {**os.environ, 'SESSION_PEER_CONTROL_ALPHA_FIXTURE': '1'}
        process = subprocess.Popen(['node', str(fixture), str(root)], env=env,
                                   stdout=log, stderr=log)
        try:
            ready = root/'ready.json'
            deadline = time.monotonic()+15
            while not ready.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    self.fail('Alpha Node fixture failed to migrate; inspect its private process.log')
                await asyncio.sleep(0.05)
            preserved = json.loads(ready.read_text())['migrationPreserved']
            self.assertEqual(preserved['user'], {
                'id': 'alpha-user', 'email': 'alpha@example.invalid'})
            self.assertEqual(preserved['device']['keyGeneration'], 2)
            self.assertEqual(preserved['device']['revoked'], 1)
            self.assertEqual(preserved['operation']['operationId'],
                             '00000000-0000-4000-8000-000000000115')
            self.assertEqual(json.loads(preserved['operation']['result']),
                             {'committed': True})
            self.assertEqual(preserved['revision'], 42)  # startup publishes the next revision
            self.assertEqual(preserved['schema'], 1)
        finally:
            if process.poll() is None:
                process.terminate()
            await asyncio.to_thread(process.wait, 5)

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

    async def test_enrollment_cli_success_and_same_operation_recovery_exit_zero(self):
        root = self.root/'cli-device'
        store = Store(root)
        self.login(store)
        principal = store.device
        store.close()
        operation = str(uuid.uuid4())
        argv = ['enroll', '--state', str(root), '--name', 'cli-test', '--operation-id', operation]
        outputs = []
        states = []
        for _ in range(2):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = await asyncio.to_thread(cli.main, 'device', argv)
            self.assertEqual(status, 0)
            result = json.loads(output.getvalue())
            self.assertIs(result['ok'], True)
            self.assertIs(result['committed'], True)
            self.assertEqual(result['operationId'], operation)
            self.assertEqual(result['principal'], principal)
            self.assertEqual(result['keyGeneration'], 0)
            outputs.append(result)
            states.append(json.loads(Path(self.info['stateFile']).read_text()))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(states[0], states[1])

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

    async def test_managed_relay_exchange_encrypts_native_payload_and_closes_revoked_connection(self):
        # Replace fixture outer TLS only; admission/cookie/WS, pinned inner TLS,
        # native adapter and live revocation checks all use production code.
        self.listener.cancel()
        await asyncio.gather(self.listener, return_exceptions=True)
        self.relay.close()
        await self.relay.wait_closed()
        managed = Relay([], control=self.auth, capture=self.frames)
        self.relay = await managed.start('127.0.0.1', 0)
        self.info['relayPort'] = self.relay.sockets[0].getsockname()[1]
        self.url = self.info['origin'].replace('https://', 'wss://')+'/v1/connect'
        actual_connect = wire.PinnedConnect
        def local_connect(url, **kwargs):
            if url != self.url:
                raise AssertionError('unexpected websocket target')
            return actual_connect('ws://127.0.0.1:'+str(self.info['relayPort'])+'/v1/connect', **kwargs)
        with mock.patch.object(wire, 'PinnedConnect', local_connect):
            self.client_token = control.DeviceCredential(self.client, self.host.device, 'client')
            self.receiver_token = control.DeviceCredential(self.host, self.host.device, 'receiver')
            self.listener = asyncio.create_task(self.receiver.relay_listener(self.url, self.receiver_token))
            record = self.client.peer(self.host.device)
            routes = {**record['routes'], 'relay': self.url}
            self.client.db.execute('UPDATE peers SET routes=? WHERE id=?', (json.dumps(routes), self.host.device))
            marker = 'managed-encrypted-fixture-'+str(uuid.uuid4())
            ident, operation = str(uuid.uuid4()), str(uuid.uuid4())
            body = {'target': 'review', 'message': marker}
            result = await self.call('send', body, ident, route='relay')
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['route'], 'relay')
            self.assertFalse(result['consumptionConfirmed'])
            self.assertEqual(len(self.effects), 1)
            self.assertTrue(self.frames)
            self.assertNotIn(marker.encode(), b''.join(self.frames))
            old_key = self.client.key_id
            actual_dispatch = self.receiver.dispatch
            interrupted = False
            async def lose_commit(peer, value):
                nonlocal interrupted
                response = await actual_dispatch(peer, value)
                if value.get('op') == 'rotation.commit' and not interrupted:
                    interrupted = True
                    # Drop the actual fixture WebSocket after durable commit,
                    # before Receiver.handle can send its response.
                    for raw in list(self.receiver.connections):
                        await raw.close()
                return response
            self.receiver.dispatch = lose_commit
            uncertain = await rotate(self.client, operation, 'relay', None, use_login=True)
            self.assertTrue(interrupted)
            self.assertFalse(uncertain['ok'])
            # Keep the deliberate retry outside the real relay's 20-handshake/s
            # budget; a burst-limit failure is not the fault under test here.
            await asyncio.sleep(1.05)
            rotated = await rotate(self.client, operation, 'relay', None, use_login=True)
            self.assertTrue(rotated['ok'], rotated)
            self.assertNotEqual(self.client.key_id, old_key)
            self.assertEqual(self.client.generation, 1)
            await asyncio.sleep(1.05)
            duplicate = await self.call('send', body, ident, route='relay')
            self.assertTrue(duplicate['ok'], duplicate)
            self.assertTrue(duplicate['duplicate'])
            self.assertEqual(len(self.effects), 1)
            self.assertNotIn(marker.encode(), b''.join(self.frames))
            channel = await open_channel(self.client, record['certificate'], routes, 'relay', self.client_token)
            try:
                control.call(self.info['origin'], '/api/relay/devices/'+self.client.device+'/revoke', {},
                             self.info['accounts'][0]['token'])
                with self.assertRaises((ConnectionClosed, EOFError)):
                    await asyncio.wait_for(channel.recv(), 3)
                # A closed client transport is necessary but not sufficient: let
                # the server finish its close handshake and release its slots.
                async def released():
                    while any(getattr(ws, 'lab_account', {}).get('devicePrincipal') == self.client.device
                              for ws in managed.connections):
                        await asyncio.sleep(0.01)
                await asyncio.wait_for(released(), 3)
            finally:
                await channel.close()
                self.listener.cancel()
                await asyncio.gather(self.listener, return_exceptions=True)
