import asyncio
import hashlib
import json
import secrets
import time
import unittest
import urllib.request
from types import SimpleNamespace

from tests.relay import test_native_relay as platform_guard
from websockets.datastructures import Headers

from session_peer_relay.relay import Relay, RelayLimits
from session_peer_relay.wire import MAX_FRAME, relay_stream


class ResponseConnection:
    def respond(self, status, text):
        return SimpleNamespace(status_code=status, headers=Headers(), body=text)


class RelayCapacity(unittest.IsolatedAsyncioTestCase):
    def test_limits_validate_bounds_and_consistency(self):
        self.assertEqual(RelayLimits().validate().global_connections, 10)
        for limits in (
            RelayLimits(handshake_rate=0),
            RelayLimits(pending_sessions=10001),
            RelayLimits(global_connections=1),
            RelayLimits(user_connections=9, global_connections=8),
            RelayLimits(device_connections=5, user_connections=4),
            RelayLimits(connection_byte_budget=MAX_FRAME-1),
        ):
            with self.subTest(limits=limits), self.assertRaisesRegex(ValueError, 'invalid_relay_limits'):
                limits.validate()

    async def test_rate_session_global_user_and_device_capacity_are_distinct(self):
        account = {'role': 'client', 'room': 'room', 'userId': 'secret-user-id', 'devicePrincipal': 'secret-device-principal'}
        class Control:
            calls = 0
            def authorize(self, token, proof):
                self.calls += 1
                return account
            def active(self, value):
                return True
        control = Control()
        relay = Relay([], control=control, limits=RelayLimits(
            handshake_rate=2, pending_sessions=1, global_connections=4,
            user_connections=2, device_connections=1))
        connection = ResponseConnection()
        request = lambda path, headers=(): SimpleNamespace(path=path, headers=Headers(headers))
        self.assertEqual((await relay.process_request(connection, request('/missing'))).status_code, 404)
        self.assertEqual((await relay.process_request(connection, request('/missing'))).status_code, 404)
        self.assertEqual((await relay.process_request(connection, request('/missing'))).status_code, 429)
        self.assertEqual(relay.metrics()['counters']['rateRejected'], 1)
        relay.requests.clear()
        relay.sessions['full'] = (time.monotonic()+60, account)
        response = await relay.process_request(connection, request('/v1/session', {
            'Authorization': 'Bearer valid', 'X-Session-Peer-Proof': 'proof'}))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(control.calls, 0, 'capacity must not consume admission proof')
        relay.requests.clear()
        relay.sessions = {'ticket': (time.monotonic()+60, account)}
        class Existing: pass
        existing = Existing(); existing.lab_account = account
        relay.connections.add(existing)
        response = await relay.process_request(connection, request('/v1/connect', {
            'Cookie': 'session_peer=ticket'}))
        self.assertEqual(response.status_code, 503)
        self.assertIn('ticket', relay.sessions, 'capacity retry keeps the one-use session')
        relay.requests.clear()
        first = Existing(); first.lab_account = {**account, 'devicePrincipal': 'one'}
        second = Existing(); second.lab_account = {**account, 'devicePrincipal': 'two'}
        relay.connections = {first, second}
        response = await relay.process_request(connection, request('/v1/connect', {
            'Cookie': 'session_peer=ticket'}))
        self.assertEqual(response.status_code, 503)
        relay.requests.clear()
        relay.connections = {object() for _ in range(4)}
        response = await relay.process_request(connection, request('/v1/connect', {
            'Cookie': 'session_peer=ticket'}))
        self.assertEqual(response.status_code, 503)
        metrics = relay.metrics()
        self.assertEqual(metrics['counters']['sessionCapacityRejected'], 1)
        self.assertEqual(metrics['counters']['connectionCapacityRejected'], 3)
        self.assertNotIn('secret-user-id', json.dumps(metrics))
        self.assertNotIn('secret-device-principal', json.dumps(metrics))

    async def test_waiting_cleanup_and_byte_budget_counter(self):
        relay = Relay([], limits=RelayLimits(connection_byte_budget=MAX_FRAME))
        class Socket:
            def __init__(self, role, frames):
                self.lab_account = {'role': role, 'room': 'bounded'}
                self.lab_expiry = time.monotonic()+5
                self.frames = frames
                self.closed = asyncio.Event()
                self.close_code = None
            async def send(self, value):
                return None
            async def close(self, code=1000, reason=''):
                self.close_code = code
                self.closed.set()
            async def wait_closed(self):
                await self.closed.wait()
            def __aiter__(self):
                async def values():
                    if self.frames is None:
                        await self.closed.wait()
                        return
                    for value in self.frames:
                        yield value
                return values()
        client = Socket('client', [b'x'*MAX_FRAME, b'y'])
        receiver = Socket('receiver', None)
        await asyncio.wait_for(asyncio.gather(relay.handler(receiver), relay.handler(client)), 3)
        self.assertEqual(relay.waiting, {})
        self.assertEqual(relay.metrics()['current']['activeConnections'], 0)
        self.assertEqual(relay.metrics()['counters']['byteBudgetClosed'], 1)

    async def test_bounded_real_websocket_load_saturates_and_recovers(self):
        receiver_token, client_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        accounts = [
            {'role': role, 'room': 'load', 'hash': hashlib.sha256(token.encode()).hexdigest()}
            for role, token in (('receiver', receiver_token), ('client', client_token))
        ]
        relay = Relay(accounts, limits=RelayLimits(
            handshake_rate=100, pending_sessions=10, global_connections=2,
            user_connections=2, device_connections=1))
        server = await relay.start('127.0.0.1', 0)
        metrics_server = await relay.start_metrics(0)
        relay_port = server.sockets[0].getsockname()[1]
        metrics_port = metrics_server.sockets[0].getsockname()[1]
        url = f'ws://127.0.0.1:{relay_port}/v1/connect'
        try:
            receiver_task = asyncio.create_task(relay_stream(url, receiver_token))
            client = await relay_stream(url, client_token)
            receiver = await receiver_task
            await client.send(b'bounded-load')
            self.assertEqual(await receiver.recv(), b'bounded-load')
            with self.assertRaises(Exception):
                await relay_stream(url, client_token, attach_timeout=1)
            def read_metrics():
                with urllib.request.urlopen(f'http://127.0.0.1:{metrics_port}/metrics') as response:
                    return json.load(response)
            metrics = await asyncio.to_thread(read_metrics)
            self.assertEqual(metrics['current']['activeConnections'], 2)
            self.assertEqual(metrics['counters']['forwardedBytes'], len(b'bounded-load'))
            await client.close(); await receiver.close()
            deadline = time.monotonic()+2
            while relay.connections and time.monotonic() < deadline:
                await asyncio.sleep(.01)
            receiver_task = asyncio.create_task(relay_stream(url, receiver_token))
            client = await relay_stream(url, client_token)
            receiver = await receiver_task
            await client.close(); await receiver.close()
        finally:
            server.close(); metrics_server.close()
            await server.wait_closed(); await metrics_server.wait_closed()


if __name__ == '__main__':
    unittest.main()
