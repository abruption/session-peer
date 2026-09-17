"""Opt-in relay lab integration tests; no native agent or public network used."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import sys
import tempfile
import time
import unittest
import uuid

if sys.version_info < (3, 11):
    raise unittest.SkipTest('relay experiment requires Python 3.11+')
try:
    import websockets
    import cryptography
except ImportError:
    raise unittest.SkipTest('optional relay experiment dependencies not installed')

from experiments.relay69.app import Receiver, exchange, open_channel, pair, request
from experiments.relay69.identity import context, fingerprint
from experiments.relay69.relay import Relay
from experiments.relay69.store import Store, Rejected
from experiments.relay69.wire import Secure, Tcp, MAX_MESSAGE, relay_stream


class RelayLab(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.host = Store(self.root/'host')
        self.client = Store(self.root/'client')
        self.receiver = Receiver(self.host)
        self.listener = await self.receiver.listen('127.0.0.1', 0)
        self.direct = '127.0.0.1:'+str(self.listener.sockets[0].getsockname()[1])
        self.host_token, self.client_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.capture = []
        accounts = [{'hash': hashlib.sha256(token.encode()).hexdigest(), 'room': 'test', 'role': role}
                    for token, role in ((self.host_token, 'receiver'), (self.client_token, 'client'))]
        self.relay = Relay(accounts, capture=self.capture)
        self.relay_server = await self.relay.start('127.0.0.1', 0)
        self.url = 'ws://127.0.0.1:'+str(self.relay_server.sockets[0].getsockname()[1])+'/v1/connect'
        self.relay_task = asyncio.create_task(self.receiver.relay_listener(self.url, self.host_token))
        self.invite = self.host.invite({'direct': self.direct, 'relay': self.url})

    async def asyncTearDown(self):
        self.relay_task.cancel()
        await asyncio.gather(self.relay_task, return_exceptions=True)
        self.listener.close()
        await self.listener.wait_closed()
        await self.receiver.close()
        self.relay_server.close()
        await self.relay_server.wait_closed()
        self.client.close()
        self.host.close()
        self.directory.cleanup()

    async def pair(self, route='direct'):
        return await pair(self.client, self.invite, route, self.client_token)

    async def test_pair_direct_send_and_duplicate(self):
        await self.pair()
        ident = str(uuid.uuid4())
        for duplicate in (False, True):
            result = await exchange(self.client, self.host.device, 'send', 'hello', ident, 'direct')
            self.assertTrue(result['ok'], result)
            self.assertEqual(result.get('duplicate', False), duplicate)
            self.assertFalse(result['consumptionConfirmed'])
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM effects').fetchone()[0], 1)
        result = await exchange(self.client, self.host.device, 'send', 'different', ident, 'direct')
        self.assertEqual(result['reason'], 'message_id_conflict')

    async def test_pair_over_relay_payload_is_opaque(self):
        await self.pair('relay')
        secret = 'sentinel-plaintext-'+secrets.token_hex(20)
        result = await exchange(self.client, self.host.device, 'send', secret,
                                route='relay', credential=self.client_token)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['route'], 'relay')
        self.assertNotIn(secret.encode(), b''.join(self.capture))
        self.assertNotIn(self.invite['secret'].encode(), b''.join(self.capture))
        self.assertNotIn(b'PRIVATE KEY', b''.join(self.capture))
        self.assertTrue(self.capture)

    async def test_auto_uses_relay_when_direct_is_closed(self):
        await self.pair()
        self.listener.close()
        await self.listener.wait_closed()
        result = await exchange(self.client, self.host.device, 'list', credential=self.client_token)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['route'], 'relay')

    async def test_relay_outage_does_not_break_direct(self):
        await self.pair()
        self.relay_server.close()
        await self.relay_server.wait_closed()
        result = await exchange(self.client, self.host.device, 'list', credential=self.client_token)
        self.assertTrue(result['ok'])
        self.assertEqual(result['route'], 'direct')

    async def test_pairing_expiry_reuse_and_wrong_secret(self):
        wrong = {**self.invite, 'secret': 'wrong'}
        with self.assertRaises(Rejected):
            await pair(self.client, wrong, 'direct')
        with self.assertRaises(Rejected):
            await pair(self.client, {**self.invite, 'expires': time.time()-1}, 'direct')
        await self.pair()
        with self.assertRaises(Rejected):
            await self.pair()

    async def test_revocation_closes_existing_connection_and_rotation_repairs(self):
        await self.pair()
        channel = await open_channel(self.client, self.host.cert, self.invite['routes'], 'direct')
        self.host.revoke(self.client.device)
        await asyncio.sleep(.4)
        with self.assertRaises(Exception):
            await channel.send(request(self.client, self.host.device, 'probe'))
            await channel.recv()
        await channel.close()
        rotated = Store(self.root/'rotated')
        try:
            invitation = self.host.invite({'direct': self.direct})
            await pair(rotated, invitation, 'direct')
            result = await exchange(rotated, self.host.device, 'list', route='direct')
            self.assertTrue(result['ok'])
        finally:
            rotated.close()
        with self.assertRaises(Rejected):
            await self.pair()

    async def test_pin_substitution_fails(self):
        stranger = Store(self.root/'stranger')
        try:
            with self.assertRaises(Rejected):
                await pair(self.client, {**self.invite, 'certificate': stranger.cert}, 'direct')
            with self.assertRaises(ssl.SSLError):
                await open_channel(self.client, stranger.cert, self.invite['routes'], 'direct', bootstrap=True)
        finally:
            stranger.close()

    async def test_pair_pending_commit_reconciliation(self):
        prepared = {'invitation': self.invite['id'], 'secret': self.invite['secret'],
                    'certificate': self.client.cert}
        self.host.prepare(prepared)
        self.assertEqual(self.host.prepare(prepared)['pairing'], 'pending')
        channel = await open_channel(self.client, self.host.cert, self.invite['routes'], 'direct')
        try:
            for _ in range(2):
                await channel.send({'op': 'pair.commit'})
                self.assertEqual((await channel.recv())['pairing'], 'paired')
        finally:
            await channel.close()

    async def test_wrong_sender_receiver_expiry_and_unauthorized_operation(self):
        await self.pair()
        for field, value in [('sender', 'other'), ('receiver', 'other'),
                             ('expires', time.time()-1), ('op', 'shell')]:
            msg = request(self.client, self.host.device, 'send', 'no effect')
            msg[field] = value
            with self.subTest(field=field), self.assertRaises(Rejected):
                self.receiver.dispatch(self.client.device, msg)
        self.host.db.execute('UPDATE peers SET capabilities=? WHERE id=?', ('["list"]', self.client.device))
        with self.assertRaises(Rejected):
            self.receiver.dispatch(self.client.device, request(self.client, self.host.device, 'send', 'x'))
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM effects').fetchone()[0], 0)

    async def test_crash_after_effect_is_unknown_after_restart_and_not_reexecuted(self):
        await self.pair()
        ident = str(uuid.uuid4())
        def crash():
            self.host.db.execute('INSERT INTO effects VALUES(?,?,?)', (self.client.device, ident, 'hash'))
            raise RuntimeError('simulated crash after effect')
        with self.assertRaises(RuntimeError):
            self.host.submit(self.client.device, ident, 'message', crash)
        reopened = Store(self.host.root)
        try:
            result = reopened.submit(self.client.device, ident, 'message', lambda: self.fail('reexecuted'))
            self.assertEqual(result['status'], 'unknown')
            self.assertFalse(result['retryAllowed'])
            self.assertEqual(reopened.db.execute('SELECT COUNT(*) FROM effects').fetchone()[0], 1)
        finally:
            reopened.close()

    async def test_oversized_and_tampered_tls_record_rejected(self):
        await self.pair()
        channel = await open_channel(self.client, self.host.cert, self.invite['routes'], 'direct')
        with self.assertRaises(ValueError):
            await channel.send({'data': 'x'*MAX_MESSAGE})
        original = channel.raw.send
        async def tamper(data):
            changed = bytearray(data)
            changed[-1] ^= 1
            await original(changed)
        channel.raw.send = tamper
        try:
            await channel.send(request(self.client, self.host.device, 'send', 'not delivered'))
            with self.assertRaises(Exception):
                await channel.recv()
        finally:
            await channel.close()
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM effects').fetchone()[0], 0)

    async def test_unauthenticated_relay_rejected(self):
        with self.assertRaises(Exception):
            await relay_stream(self.url, 'invalid')
        self.assertGreater(self.relay.rejected, 0)

    async def test_plain_client_cannot_list_before_pairing(self):
        channel = await open_channel(self.client, self.host.cert, self.invite['routes'], 'direct', bootstrap=True)
        try:
            await channel.send(request(self.client, self.host.device, 'list'))
            self.assertEqual((await channel.recv())['reason'], 'unpaired_device')
        finally:
            await channel.close()

    async def test_lost_pair_commit_response_reconciles_without_reusing_secret(self):
        self.client.stage(self.invite)
        self.host.prepare({'invitation': self.invite['id'], 'secret': self.invite['secret'],
                           'certificate': self.client.cert})
        self.host.commit(self.client.device)
        result = await pair(self.client, self.invite, 'direct')
        self.assertEqual(result['pairing'], 'paired')
        self.assertEqual(self.client.peer(self.host.device)['status'], 'paired')

    async def test_relay_capacity_and_admission_budget_are_bounded(self):
        from types import SimpleNamespace
        from websockets.datastructures import Headers
        class Connection:
            def respond(self, status, text):
                return SimpleNamespace(status_code=status, headers=Headers())
        connection = Connection()
        self.relay.requests = []
        for _ in range(20):
            result = await self.relay.process_request(connection,
                SimpleNamespace(path='/v1/session', headers=Headers({'Authorization': 'Bearer wrong'})))
            self.assertEqual(result.status_code, 401)
        result = await self.relay.process_request(connection,
                SimpleNamespace(path='/v1/session', headers=Headers()))
        self.assertEqual(result.status_code, 429)
        self.relay.requests = []
        self.relay.sessions['ticket'] = (time.monotonic()+60, {'role': 'client', 'room': 'test'})
        self.relay.connections.update(object() for _ in range(10))
        result = await self.relay.process_request(connection, SimpleNamespace(
            path='/v1/connect', headers=Headers({'Cookie': 'relay69=ticket'})))
        self.assertEqual(result.status_code, 503)
        self.relay.connections.clear()

    async def test_slow_forwarding_times_out_without_unbounded_application_queue(self):
        class Socket:
            def __init__(self, role, slow=False):
                self.lab_account = {'role': role, 'room': 'slow'}
                self.lab_expiry = time.monotonic()+60
                self.closed = asyncio.Event()
                self.slow = slow
            async def send(self, data):
                if self.slow and isinstance(data, bytes):
                    await asyncio.sleep(10)
            async def close(self, *args):
                self.closed.set()
            async def wait_closed(self):
                await self.closed.wait()
            async def frames(self):
                if not self.slow:
                    yield b'x'*256
                await self.closed.wait()
            def __aiter__(self):
                return self.frames()
        a, b = Socket('client'), Socket('receiver', True)
        start = time.monotonic()
        await asyncio.wait_for(asyncio.gather(self.relay.handler(a), self.relay.handler(b)), 4)
        self.assertLess(time.monotonic()-start, 3.5)
        self.assertTrue(a.closed.is_set() and b.closed.is_set())

    async def test_replayed_tls_record_cannot_submit_twice(self):
        await self.pair()
        channel = await open_channel(self.client, self.host.cert, self.invite['routes'], 'direct')
        captured = []
        original = channel.raw.send
        async def record(data):
            captured.append(data)
            await original(data)
        channel.raw.send = record
        try:
            await channel.send(request(self.client, self.host.device, 'send', 'one effect'))
            self.assertTrue((await channel.recv())['ok'])
            await original(captured[0])
            with self.assertRaises(Exception):
                await channel.recv()
        finally:
            await channel.close()
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM effects').fetchone()[0], 1)

    async def test_malicious_inbound_length_is_rejected_before_body(self):
        import struct
        from experiments.relay69.wire import MAX_MESSAGE
        await self.pair()
        channel = await open_channel(self.client, self.host.cert, self.invite['routes'], 'direct')
        try:
            channel.ssl.write(struct.pack('!I', MAX_MESSAGE+1))
            await channel.flush()
            with self.assertRaises(Exception):
                await channel.recv()
        finally:
            await channel.close()
        self.assertEqual(self.host.db.execute('SELECT COUNT(*) FROM effects').fetchone()[0], 0)

    async def test_relay_origin_credentials_and_expired_cookies_fail_closed(self):
        from experiments.relay69.wire import validate_relay_url, PinnedConnect
        from types import SimpleNamespace
        from websockets.datastructures import Headers
        for url in ('ws://public.example/v1/connect', 'wss://user:pass@example/v1/connect',
                    'wss://example/v1/connect?token=secret', 'wss://example/v1/connect#secret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_relay_url(url)
        validate_relay_url('wss://example/v1/connect')
        error = ValueError('redirect')
        self.assertIs(PinnedConnect('wss://example/v1/connect').process_redirect(error), error)
        class Connection:
            def respond(self, status, text):
                return SimpleNamespace(status_code=status, headers=Headers())
        self.relay.sessions['expired'] = (time.monotonic()-1, {'role': 'client', 'room': 'test'})
        result = await self.relay.process_request(Connection(), SimpleNamespace(
            path='/v1/connect', headers=Headers({'Cookie': 'relay69=expired'})))
        self.assertEqual(result.status_code, 401)

    async def test_device_keys_are_distinct_and_private(self):
        self.assertNotEqual(self.host.device, self.client.device)
        for store in (self.host, self.client):
            self.assertEqual((store.root/'identity.key').stat().st_mode & 0o777, 0o600)
            self.assertEqual(store.root.stat().st_mode & 0o777, 0o700)
            self.assertNotIn('PRIVATE KEY', store.cert)
