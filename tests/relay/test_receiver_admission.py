"""Receiver admission (#233): isolated TLS peers, bounded lanes and cleanup."""
import asyncio
import contextlib
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from tests.relay import test_native_relay as platform_guard
from websockets.exceptions import ConnectionClosed
from session_peer_relay import app, wire
from session_peer_relay.relay import Relay
from session_peer_relay.identity import context, fingerprint
from session_peer_relay.store import Store
from session_peer_relay.transport_errors import NoAuthenticatedRoute


class ReceiverAdmission(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='codex-receiver-admission-')
        self.root = Path(self.directory.name)
        self.host, self.client = Store(self.root/'host'), Store(self.root/'client')
        self.receiver = app.Receiver(self.host, {
            'targets': {'review': {'agent': 'claude', 'target': 'fixture'}},
            'peers': {self.client.device: {'capabilities': ['list'], 'targets': ['review']}},
        })
        self.server = await self.receiver.listen('127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.receiver_token, self.client_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.relay = Relay([
            {'hash': hashlib.sha256(token.encode()).hexdigest(), 'room': 'fixture', 'role': role}
            for token, role in ((self.receiver_token, 'receiver'), (self.client_token, 'client'))
        ])
        self.relay_server = await self.relay.start('127.0.0.1', 0)
        self.url = 'ws://127.0.0.1:'+str(self.relay_server.sockets[0].getsockname()[1])+'/v1/connect'
        self.relay_listener = asyncio.create_task(self.receiver.relay_listener(self.url, self.receiver_token))
        self.invite = self.host.invite({'direct': '127.0.0.1:'+str(self.port), 'relay': self.url})
        self.clients = []
        self.channels = []
        await app.pair(self.client, self.invite, 'direct')
        await self.wait_for(lambda: not self.receiver.connections)
        await self.wait_for(lambda: self.relay.metrics()['current']['waitingRooms'] == 1)

    async def asyncTearDown(self):
        self.relay_listener.cancel()
        await asyncio.gather(self.relay_listener, return_exceptions=True)
        self.server.close()
        await self.receiver.close()
        await self.server.wait_closed()
        for channel in self.channels:
            with contextlib.suppress(Exception):
                await channel.close()
        for reader, writer in self.clients:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
        self.relay_server.close()
        await self.relay_server.wait_closed()
        self.assert_empty()
        self.client.close()
        self.host.close()
        self.directory.cleanup()

    async def wait_for(self, predicate, timeout=3):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(.005)

    def assert_empty(self):
        self.assertFalse(self.receiver.connections)
        self.assertFalse(self.receiver.tasks)
        self.assertFalse(self.receiver.direct_preauth)
        self.assertFalse(self.receiver.relay_preauth)
        self.assertFalse(self.receiver.authenticated)
        self.assertFalse([task for task in asyncio.all_tasks() if not task.done()
                          and task.get_coro().__qualname__ in
                          ('Receiver.handle', 'Receiver.watch_peer')])

    async def idle(self, count, slow_tls=False):
        start = len(self.clients)
        for _ in range(count):
            reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
            self.clients.append((reader, writer))
            if slow_tls:
                # A TLS record/ClientHello prefix that never completes.
                writer.write(b'\x16\x03\x01\x00\x80\x01')
                await writer.drain()
        return self.clients[start:]

    async def probe(self, route='direct'):
        return await app.exchange(self.client, self.host.device, 'probe', route=route,
                                  credential=self.client_token)

    async def test_eight_idle_sockets_allow_direct_and_relay_and_preserve_refusal(self):
        await self.idle(8)
        await self.wait_for(lambda: len(self.receiver.direct_preauth) == 8)
        self.receiver.diagnostic_events = True
        with self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
            self.assertTrue((await self.probe())['ok'])
            result = await self.probe('relay')
            self.assertTrue(result['ok'])
            refusal = await app.exchange(self.client, self.host.device, 'list', {'invalid': True},
                                         route='relay', credential=self.client_token)
        self.assertEqual({key: refusal[key] for key in ('ok', 'status', 'reason',
                                                      'consumptionConfirmed', 'retryAllowed')},
                         {'ok': False, 'status': 'refused', 'reason': 'invalid_list_request',
                          'consumptionConfirmed': False, 'retryAllowed': False})
        events = [json.loads(row.split('relay_lifecycle ', 1)[1]) for row in logs.output]
        self.assertTrue(any(row['event'] == 'peer_tls' and row['outcome'] == 'ok'
                            and row['attemptId'] == result['attemptId'] for row in events))
        self.assertNotIn(self.client_token, '\n'.join(logs.output))
        # Success occurred while the attack connections were still admitted.
        self.assertEqual(len(self.receiver.direct_preauth), 8)

    async def test_eight_slow_tls_sockets_allow_direct_and_relay(self):
        await self.idle(8, slow_tls=True)
        await self.wait_for(lambda: len(self.receiver.direct_preauth) == 8)
        self.assertTrue((await self.probe())['ok'])
        self.assertTrue((await self.probe('relay'))['ok'])
        self.assertEqual(len(self.receiver.direct_preauth), 8)

    async def test_slow_tls_has_short_absolute_timeout_and_releases_descriptors(self):
        started = time.monotonic()
        sockets = await self.idle(8, slow_tls=True)
        await self.wait_for(lambda: len(self.receiver.direct_preauth) == 8)
        descriptors = [raw.writer.get_extra_info('socket') for raw in self.receiver.connections]
        # Periodic bytes do not restart the absolute handshake deadline.
        async def trickle(writer):
            with contextlib.suppress(OSError):
                while True:
                    await asyncio.sleep(.1)
                    writer.write(b'\x00')
                    await writer.drain()
        trickles = [asyncio.create_task(trickle(writer)) for _, writer in sockets]
        try:
            await self.wait_for(lambda: not self.receiver.tasks, app.PREAUTH_TLS_TIMEOUT+1)
        finally:
            for task in trickles:
                task.cancel()
            await asyncio.gather(*trickles, return_exceptions=True)
        self.assertLess(time.monotonic()-started, wire.TIMEOUT)
        self.assertTrue(all(socket.fileno() == -1 for socket in descriptors))
        self.assert_empty()

    async def test_certless_timeout_refusal_and_authenticated_idle_budget(self):
        paired = await app.open_channel(self.client, self.host.cert, self.invite['routes'], 'direct')
        self.channels.append(paired)
        certless = await app.open_channel(self.client, self.host.cert, self.invite['routes'],
                                          'direct', bootstrap=True)
        self.channels.append(certless)
        await self.wait_for(lambda: len(self.receiver.authenticated) == 1
                            and len(self.receiver.direct_preauth) == 1)
        started = time.monotonic()
        await self.wait_for(lambda: not self.receiver.direct_preauth,
                            app.CERTLESS_REQUEST_TIMEOUT+1)
        self.assertLess(time.monotonic()-started, 45)
        self.assertEqual(len(self.receiver.authenticated), 1)
        await paired.send(app.request(self.client, self.host.device, 'probe'))
        self.assertTrue((await paired.recv())['ok'])
        refused = await app.open_channel(self.client, self.host.cert, self.invite['routes'],
                                         'direct', bootstrap=True)
        self.channels.append(refused)
        await refused.send(app.request(self.client, self.host.device, 'list'))
        response = await refused.recv()
        self.assertEqual(response['reason'], 'unpaired_device')
        self.assertEqual(response['status'], 'refused')
        self.assertFalse(response['retryAllowed'])
        self.assertFalse(response['consumptionConfirmed'])

    async def test_direct_flood_is_bounded_and_relay_has_reserved_admission(self):
        await self.idle(app.DIRECT_PREAUTH_LIMIT)
        await self.wait_for(lambda: len(self.receiver.direct_preauth) == app.DIRECT_PREAUTH_LIMIT)
        descriptors = [raw.writer.get_extra_info('socket') for raw in self.receiver.connections]
        excess = await self.idle(48)
        for reader, _ in excess:
            self.assertEqual(await asyncio.wait_for(reader.read(1), .5), b'')
        self.assertEqual(len(self.receiver.tasks), app.DIRECT_PREAUTH_LIMIT)
        self.assertEqual(len(self.receiver.connections), app.DIRECT_PREAUTH_LIMIT)
        # A saturated direct pre-auth lane can still refuse a paired direct
        # client: the budget is bounded, not an arbitrary-flood guarantee.
        with self.assertRaises(NoAuthenticatedRoute):
            await self.probe()
        self.assertTrue((await self.probe('relay'))['ok'])
        for _, writer in self.clients:
            writer.close()
        await self.wait_for(lambda: not self.receiver.tasks)
        self.assert_empty()
        self.assertTrue(all(socket.fileno() == -1 for socket in descriptors))
        self.assertTrue((await self.probe())['ok'])

    async def test_authenticated_cap_is_independent_and_stays_eight(self):
        for _ in range(app.AUTHENTICATED_LIMIT):
            channel = await app.open_channel(self.client, self.host.cert, self.invite['routes'], 'direct')
            self.channels.append(channel)
        await self.wait_for(lambda: len(self.receiver.authenticated) == 8)
        extra = await app.open_channel(self.client, self.host.cert, self.invite['routes'], 'direct')
        self.channels.append(extra)
        await self.wait_for(lambda: not self.receiver.direct_preauth)
        self.assertEqual(len(self.receiver.authenticated), 8)
        self.assertEqual(self.receiver.admission_counters['authenticatedRefused'], 1)
        with self.assertRaises((EOFError, OSError)):
            await extra.recv()
        await self.channels[0].send(app.request(self.client, self.host.device, 'probe'))
        self.assertTrue((await self.channels[0].recv())['ok'])

    async def test_reserved_relay_lane_is_bounded_and_cleans_up(self):
        attached = []
        try:
            for expected in range(1, app.RELAY_PREAUTH_LIMIT+1):
                await self.wait_for(lambda: self.relay.metrics()['current']['waitingRooms'] == 1)
                raw = await wire.relay_stream(self.url, self.client_token)
                attached.append(raw)
                await self.wait_for(lambda: len(self.receiver.relay_preauth) == expected)
            await self.wait_for(lambda: self.relay.metrics()['current']['waitingRooms'] == 1)
            excess = await wire.relay_stream(self.url, self.client_token)
            attached.append(excess)
            with self.assertRaises(Exception):
                await asyncio.wait_for(excess.recv(), .5)
            self.assertEqual(len(self.receiver.relay_preauth), app.RELAY_PREAUTH_LIMIT)
            self.assertEqual(len(self.receiver.tasks), app.RELAY_PREAUTH_LIMIT)
            self.assertTrue((await self.probe())['ok'])
        finally:
            for raw in attached:
                await raw.close()
        await self.wait_for(lambda: not self.receiver.tasks)
        self.assert_empty()
        self.assertTrue((await self.probe('relay'))['ok'])

    async def test_relay_handshake_timeout_keeps_diagnostic_and_releases_budget(self):
        self.receiver.diagnostic_events = True
        with self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
            raw = await wire.relay_stream(self.url, self.client_token)
            try:
                await self.wait_for(lambda: len(self.receiver.relay_preauth) == 1)
                await self.wait_for(lambda: not self.receiver.tasks, app.PREAUTH_TLS_TIMEOUT+1)
            finally:
                await raw.close()
        self.assert_empty()
        events = [json.loads(row.split('relay_lifecycle ', 1)[1]) for row in logs.output]
        failures = [row for row in events if row['event'] == 'peer_tls' and row['outcome'] == 'failed']
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]['reason'], 'timeout')
        self.assertLess(failures[0]['elapsedMs'], wire.TIMEOUT*1000)
        self.assertTrue((await self.probe('relay'))['ok'])

    async def test_bootstrap_pairing_survives_eight_idle_sockets_in_both_lanes(self):
        await self.idle(8)
        await self.wait_for(lambda: len(self.receiver.direct_preauth) == 8)
        for route in ('direct', 'relay'):
            with self.subTest(route=route):
                newcomer = Store(self.root/('new-'+route))
                try:
                    invite = self.host.invite(self.invite['routes'])
                    result = await app.pair(newcomer, invite, route, self.client_token)
                    self.assertTrue(result['ok'])
                    self.assertEqual(result['pairing'], 'paired')
                    self.assertEqual(self.host.peer(newcomer.device)['status'], 'paired')
                finally:
                    newcomer.close()
        self.assertEqual(len(self.receiver.direct_preauth), 8)

    async def test_close_cancels_mixed_inflight_connections_and_peer_watch(self):
        paired = await app.open_channel(self.client, self.host.cert, self.invite['routes'], 'direct')
        self.channels.append(paired)
        certless = await app.open_channel(self.client, self.host.cert, self.invite['routes'],
                                          'direct', bootstrap=True)
        self.channels.append(certless)
        await self.idle(2, slow_tls=True)
        relay = await wire.relay_stream(self.url, self.client_token)
        try:
            await self.wait_for(lambda: len(self.receiver.relay_preauth) == 1
                                and len(self.receiver.direct_preauth) == 3
                                and len(self.receiver.authenticated) == 1)
            await self.receiver.close()
            self.assert_empty()
        finally:
            await relay.close()
        with self.assertRaises(NoAuthenticatedRoute):
            await self.probe()
        self.assert_empty()

    async def test_failed_tls_releases_admission(self):
        reader, writer = (await self.idle(1))[0]
        await self.wait_for(lambda: len(self.receiver.direct_preauth) == 1)
        writer.write(b'invalid TLS record')
        await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.read(1), .5), b'')
        await self.wait_for(lambda: not self.receiver.tasks)
        self.assert_empty()
        self.assertTrue((await self.probe())['ok'])

    async def test_cancel_before_handler_starts_releases_both_lanes(self):
        # Exercise the window between synchronous reservation and first task run.
        for relay in (False, True):
            transport = Mock()
            if relay:
                raw = wire.Ws(SimpleNamespace(transport=transport))
            else:
                raw = wire.Tcp(None, SimpleNamespace(transport=transport))
            self.receiver.spawn(raw)
            task = next(iter(self.receiver.tasks))
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await self.wait_for(lambda: not self.receiver.tasks)
            self.assert_empty()
            transport.abort.assert_called_once()

    def fake_raw(self, relay=False, abort_error=False):
        transport = Mock()
        if abort_error:
            transport.abort.side_effect = OSError('SECRET-abort-error')
        if relay:
            return wire.Ws(SimpleNamespace(transport=transport, close=AsyncMock()))
        return wire.Tcp(None, SimpleNamespace(transport=transport, close=Mock(),
                                             wait_closed=AsyncMock()))

    async def test_abort_errors_during_prestart_cancellation_and_handler_exception(self):
        self.receiver.diagnostic_events = True
        for relay in (False, True):
            raw = self.fake_raw(relay, abort_error=True)
            with self.assertLogs('session_peer_relay.app', level='WARNING') if not relay else contextlib.nullcontext():
                self.receiver.spawn(raw)
                task = next(iter(self.receiver.tasks))
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await self.wait_for(lambda: not self.receiver.tasks)
            self.assert_empty()
        self.assertEqual(self.receiver.admission_counters['abortFailed'], 2)
        errors = []
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda loop, detail: errors.append(detail))
        try:
            raw = self.fake_raw(abort_error=True)
            with patch.object(self.receiver, 'handle', new=AsyncMock(side_effect=RuntimeError('SECRET-handler-error'))):
                self.receiver.spawn(raw)
                await self.wait_for(lambda: not self.receiver.tasks)
            self.assert_empty()
            self.assertEqual(self.receiver.admission_counters['handlerFailed'], 1)
            self.assertEqual(self.receiver.admission_counters['abortFailed'], 3)
            self.assertFalse(errors)
            self.assertTrue((await self.probe())['ok'])
        finally:
            loop.set_exception_handler(previous)

    async def test_abort_error_in_handler_finally_releases_admission(self):
        entered = asyncio.Event()
        original_handshake = wire.Secure.handshake
        async def observed_handshake(channel):
            entered.set()
            return await original_handshake(channel)
        # Admission is reserved before handle starts. Wait for the actual TLS
        # coroutine so cancellation exercises its finally on every Python version.
        with patch.object(wire.Secure, 'handshake', new=observed_handshake):
            reader, _ = (await self.idle(1))[0]
            await asyncio.wait_for(entered.wait(), .5)
            raw = next(iter(self.receiver.connections))
            descriptor = raw.writer.get_extra_info('socket')
            # The normal close releases the real descriptor; inject an abort
            # error to verify admission and task cleanup still run afterward.
            with patch.object(raw, 'abort', side_effect=OSError('SECRET-abort-error')):
                for task in self.receiver.tasks:
                    task.cancel()
                await self.wait_for(lambda: not self.receiver.tasks)
        self.assertEqual(await asyncio.wait_for(reader.read(1), .5), b'')
        self.assertEqual(descriptor.fileno(), -1)
        self.assertEqual(self.receiver.admission_counters['abortFailed'], 1)
        self.assert_empty()

    async def test_saturation_counters_and_diagnostics_are_bounded_and_sanitized(self):
        self.receiver.diagnostic_events = True
        async def blocked(raw):
            await asyncio.Future()
        with self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
            for relay, limit in ((False, app.DIRECT_PREAUTH_LIMIT), (True, app.RELAY_PREAUTH_LIMIT)):
                with patch.object(self.receiver, 'handle', new=blocked):
                    for _ in range(limit):
                        self.receiver.spawn(self.fake_raw(relay))
                    for _ in range(50):
                        rejected = self.fake_raw(relay, abort_error=True)
                        self.receiver.spawn(rejected)
                        if relay:
                            rejected.ws.transport.close.assert_called_once()
                        else:
                            rejected.writer.close.assert_called_once()
                self.assertEqual(len(self.receiver.tasks), app.DIRECT_PREAUTH_LIMIT if not relay
                                 else app.DIRECT_PREAUTH_LIMIT+app.RELAY_PREAUTH_LIMIT)
            self.assertEqual(self.receiver.admission_counters['directPreauthRefused'], 50)
            self.assertEqual(self.receiver.admission_counters['relayPreauthRefused'], 50)
            self.assertEqual(self.receiver.admission_counters['abortFailed'], 100)
            await self.receiver.close()
        self.assertEqual(len(logs.output), 1)
        event = json.loads(logs.output[0].split('relay_lifecycle ', 1)[1])
        self.assertEqual(event['event'], 'receiver_admission')
        self.assertEqual(event['reason'], 'direct_preauth_full')
        self.assertEqual(set(event), {'event', 'eventTimeUtcMs', 'reason', 'counters'})
        self.assertNotIn('SECRET', logs.output[0])
        self.assert_empty()
        next_minute = self.receiver.admission_last_logged+60
        with patch.object(app, 'time', SimpleNamespace(monotonic=lambda: next_minute, time=time.time)), \
                self.assertLogs('session_peer_relay.app', level='WARNING') as renewed:
            self.receiver.spawn(self.fake_raw())
            self.receiver.spawn(self.fake_raw())
        self.assertEqual(len(renewed.output), 1)
        counters = json.loads(renewed.output[0].split('relay_lifecycle ', 1)[1])['counters']
        self.assertEqual(counters['directPreauthRefused'], 50)
        self.assertEqual(counters['relayPreauthRefused'], 50)
        self.assertEqual(counters['abortFailed'], 100)
        self.assert_empty()

    async def test_close_rejects_new_spawn_during_and_after_shutdown(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        raw = self.fake_raw()
        async def handler(raw):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                await finish.wait()
        with patch.object(self.receiver, 'handle', side_effect=handler):
            self.receiver.spawn(raw)
            await entered.wait()
            closing = asyncio.create_task(self.receiver.close())
            await self.wait_for(lambda: self.receiver.closing)
            rejected = self.fake_raw(abort_error=True)
            self.receiver.spawn(rejected)
            self.assertEqual(len(self.receiver.tasks), 1)
            finish.set()
            await closing
        self.assert_empty()
        self.receiver.spawn(self.fake_raw(relay=True, abort_error=True))
        self.assert_empty()
        self.assertEqual(self.receiver.admission_counters['closingRefused'], 2)
        self.assertEqual(self.receiver.admission_counters['abortFailed'], 2)

    async def test_delayed_real_tls_succeeds_before_deadline_and_refuses_after(self):
        class GatedFirstSend:
            def __init__(self, raw):
                self.raw = raw
                self.entered, self.allow = asyncio.Event(), asyncio.Event()
            async def send(self, data):
                if not self.entered.is_set():
                    self.entered.set()
                    await self.allow.wait()
                await self.raw.send(data)
            async def recv(self):
                return await self.raw.recv()
            async def close(self):
                await self.raw.close()

        self.receiver.native.invoke = AsyncMock()
        for route in ('direct', 'relay'):
            for over_deadline in (False, True):
                with self.subTest(route=route, over_deadline=over_deadline):
                    raw = (wire.Tcp(*await asyncio.open_connection('127.0.0.1', self.port))
                           if route == 'direct' else await wire.relay_stream(self.url, self.client_token))
                    delayed = GatedFirstSend(raw)
                    channel = wire.Secure(delayed, context(self.client.identity_root, False, [self.host.cert]),
                                          expected=fingerprint(self.host.cert))
                    self.channels.append(channel)
                    handshake = asyncio.create_task(channel.handshake())
                    try:
                        await delayed.entered.wait()
                        await self.wait_for(lambda: len(self.receiver.connections) == 1)
                        started = time.monotonic()
                        if over_deadline:
                            await self.wait_for(lambda: not self.receiver.tasks,
                                                app.PREAUTH_TLS_TIMEOUT+1)
                            self.assertGreaterEqual(time.monotonic()-started, app.PREAUTH_TLS_TIMEOUT-.1)
                            delayed.allow.set()
                            with self.assertRaises((EOFError, OSError, ConnectionClosed)) as refused:
                                await handshake
                            if isinstance(refused.exception, ConnectionClosed):
                                self.assertEqual(refused.exception.rcvd.code, 1001)
                            self.assert_empty()
                        else:
                            await asyncio.sleep(.25)
                            delayed.allow.set()
                            await handshake
                            self.assertLess(time.monotonic()-started, app.PREAUTH_TLS_TIMEOUT)
                            await channel.send(app.request(self.client, self.host.device, 'probe'))
                            self.assertTrue((await channel.recv())['ok'])
                    finally:
                        handshake.cancel()
                        await asyncio.gather(handshake, return_exceptions=True)
                        await channel.close()
                        await self.wait_for(lambda: not self.receiver.tasks)
                    self.receiver.native.invoke.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
