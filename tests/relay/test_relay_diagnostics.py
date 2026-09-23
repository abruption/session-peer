"""Metadata-only lifecycle evidence and scaled stale-room fixtures."""
import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from session_peer_relay import app
from session_peer_relay.cli import parser
from session_peer_relay.relay import Relay
from session_peer_relay.transport_errors import TransportFailure


class FakeWebSocket:
    def __init__(self, role, *, stalled=False):
        self.lab_account = {'room': 'SECRET-ROOM', 'role': role}
        self.lab_expiry = time.monotonic() + 10
        self.stalled = stalled
        self.closed = asyncio.Event()
        self.close_code = None
        self.sent = []

    async def send(self, value):
        if self.stalled:
            await self.closed.wait()
        self.sent.append(value)

    async def wait_closed(self):
        await self.closed.wait()

    async def close(self, code=1000, reason=''):
        self.close_code = code
        self.closed.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.closed.wait()
        raise StopAsyncIteration


class RelayLifecycle(unittest.IsolatedAsyncioTestCase):
    async def wait_for(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(.002)

    async def test_idle_receiver_expiry_is_counted_without_identity(self):
        relay = Relay([], diagnostic_events=True)
        relay.receiver_wait = .02  # scaled fixture; production bound stays 60 s
        receiver = FakeWebSocket('receiver')
        with self.assertLogs('session_peer_relay.relay', level='WARNING') as logs:
            await relay.handler(receiver)
        self.assertEqual(relay.metrics()['counters']['receiverIdleExpired'], 1)
        self.assertEqual(relay.metrics()['counters']['roomsClosedBeforeAttach'], 1)
        self.assertEqual(relay.metrics()['current']['waitingRooms'], 0)
        self.assertTrue(any('receiver_idle_expiry' in row for row in logs.output))
        self.assertNotIn('SECRET-ROOM', '\n'.join(logs.output))

    async def test_re_admission_delay_longer_than_client_wait_leaves_no_pair(self):
        relay = Relay([])
        relay.receiver_wait = .01
        relay.client_wait = .02  # scaled model of the production 10 s client wait
        first_receiver = FakeWebSocket('receiver')
        await relay.handler(first_receiver)
        self.assertEqual(relay.metrics()['counters']['receiverIdleExpired'], 1)
        client = FakeWebSocket('client')
        client_task = asyncio.create_task(relay.handler(client))
        await self.wait_for(lambda: relay.metrics()['current']['waitingRooms'] == 1)
        # A receiver admission/upgrade delayed beyond the client wait cannot
        # rescue that request, even if the next receiver subsequently connects.
        await asyncio.sleep(.04)
        late_receiver = FakeWebSocket('receiver')
        receiver_task = asyncio.create_task(relay.handler(late_receiver))
        try:
            await asyncio.wait_for(client_task, 1)
            self.assertEqual(relay.metrics()['counters']['clientWaitExpired'], 1)
            self.assertEqual(relay.metrics()['counters']['roomsPaired'], 0)
        finally:
            await late_receiver.close()
            receiver_task.cancel()
            await asyncio.gather(receiver_task, return_exceptions=True)

    async def test_stalled_receiver_consumes_room_then_next_client_times_out(self):
        relay = Relay([], diagnostic_events=True)
        relay.client_wait = .03  # scaled fixture; production bound stays 10 s
        receiver = FakeWebSocket('receiver', stalled=True)
        first = FakeWebSocket('client')
        second = FakeWebSocket('client')
        tasks = []
        with self.assertLogs('session_peer_relay.relay', level='WARNING') as logs:
            try:
                tasks.append(asyncio.create_task(relay.handler(receiver)))
                await self.wait_for(lambda: relay.metrics()['current']['waitingRooms'] == 1)
                tasks.append(asyncio.create_task(relay.handler(first)))
                await self.wait_for(lambda: relay.metrics()['counters']['roomsPaired'] == 1)
                self.assertEqual(relay.metrics()['current']['waitingRooms'], 0)
                self.assertFalse(receiver.sent)  # attach is blocked on the receiver leg
                await asyncio.wait_for(relay.handler(second), 1)
                counters = relay.metrics()['counters']
                self.assertEqual(counters['clientWaitExpired'], 1)
                self.assertEqual(counters['roomsPaired'], 1)
                self.assertEqual(counters['attachSentClient'], 1)
                self.assertEqual(counters['attachSentReceiver'], 0)
                self.assertEqual(relay.metrics()['current']['waitingRooms'], 0)
            finally:
                for ws in (receiver, first, second):
                    await ws.close()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        self.assertTrue(any('room_paired' in row for row in logs.output))
        self.assertNotIn('SECRET-ROOM', '\n'.join(logs.output))


class ReceiverLifecycle(unittest.IsolatedAsyncioTestCase):
    def test_diagnostic_events_are_explicit_opt_in(self):
        device = parser('device')
        relay = parser('relay')
        self.assertFalse(device.parse_args(['serve', '--policy', '/fixture']).diagnostic_events)
        self.assertTrue(device.parse_args(['serve', '--policy', '/fixture', '--diagnostic-events']).diagnostic_events)
        self.assertFalse(relay.parse_args(['serve', '--accounts', '/fixture']).diagnostic_events)
        self.assertTrue(relay.parse_args(['serve', '--accounts', '/fixture', '--diagnostic-events']).diagnostic_events)

    async def test_expected_idle_expiry_is_not_failure_warning(self):
        receiver = app.Receiver(Mock(), {'targets': {'worker': {'agent': 'claude', 'target': 'worker'}},
                                         'peers': {}}, diagnostic_events=True)
        calls = 0

        async def connect(url, credential, *, attach_timeout, on_event):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise asyncio.CancelledError()
            on_event('websocket_open', elapsed_ms=2)
            raise TransportFailure('relay_attach', 'connection_closed', close_code=1000)

        with patch.object(app, 'relay_stream', side_effect=connect), \
             patch.object(app, 'time', SimpleNamespace(monotonic=Mock(side_effect=[0, 60]))), \
             patch.object(app.asyncio, 'sleep', new=AsyncMock()), \
             patch.object(app.logging, 'getLogger') as logger:
            with self.assertRaises(asyncio.CancelledError):
                await receiver.relay_listener('wss://relay.example.test/v1/connect', 'SECRET')
        rows = [str(call) for call in logger.return_value.warning.call_args_list]
        self.assertTrue(any('idle_expiry' in row for row in rows))
        self.assertFalse(any('relay_connection_failed' in row for row in rows))
        self.assertNotIn('SECRET', '\n'.join(rows))

    async def test_consumed_room_is_not_reused_for_next_setup_failure(self):
        receiver = app.Receiver(Mock(), {'targets': {'worker': {'agent': 'claude', 'target': 'worker'}},
                                         'peers': {}}, diagnostic_events=True)
        calls = 0

        async def connect(url, credential, *, attach_timeout, on_event):
            nonlocal calls
            calls += 1
            if calls == 1:
                on_event('websocket_open', elapsed_ms=2)
                on_event('attach_received', elapsed_ms=3)
                return object()
            if calls == 2:
                raise TransportFailure('relay_admission', 'timeout', transient=True)
            raise asyncio.CancelledError()

        with patch.object(receiver, 'spawn') as spawn, \
             patch.object(app, 'relay_stream', side_effect=connect), \
             patch.object(app, 'time', SimpleNamespace(monotonic=Mock(side_effect=[0, 1, 2, 3]))), \
             patch.object(app.asyncio, 'sleep', new=AsyncMock()), \
             patch.object(app.logging, 'getLogger') as logger:
            with self.assertRaises(asyncio.CancelledError):
                await receiver.relay_listener('wss://relay.example.test/v1/connect', 'SECRET')
        spawn.assert_called_once()
        rows = [str(call) for call in logger.return_value.warning.call_args_list]
        self.assertTrue(any('setup_failed' in row for row in rows))
        self.assertFalse(any('websocket_closed' in row for row in rows))


if __name__ == '__main__':
    unittest.main()
