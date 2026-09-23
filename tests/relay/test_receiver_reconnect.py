"""Receiver reconnect behavior (#163): idle-expiry backoff, keepalive, role_busy metrics."""
import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from session_peer_relay import app, wire
from session_peer_relay.transport_errors import TransportFailure


class ReceiverIdleExpiryBackoff(unittest.IsolatedAsyncioTestCase):
    async def sleeps_for(self, rooms):
        """rooms: (open seconds, close code, close source) per attempt."""
        receiver = app.Receiver(Mock(), {'targets': {'worker': {'agent': 'claude', 'target': 'worker'}},
                                         'peers': {}})
        clock, sleeps, calls = [0.0], [], [0]

        async def connect(url, credential, *, attach_timeout, on_event):
            if calls[0] == len(rooms):
                raise asyncio.CancelledError()
            age, code, source = rooms[calls[0]]
            calls[0] += 1
            on_event('websocket_open', elapsed_ms=1)
            clock[0] += age
            raise TransportFailure('relay_attach', 'connection_closed',
                                   close_code=code, close_source=source)

        async def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds

        with patch.object(app, 'relay_stream', side_effect=connect), \
             patch.object(app, 'time', SimpleNamespace(monotonic=lambda: clock[0], time=time.time)), \
             patch.object(app.asyncio, 'sleep', new=AsyncMock(side_effect=sleep)):
            with self.assertRaises(asyncio.CancelledError):
                await receiver.relay_listener('wss://relay.example.test/v1/connect', 'SECRET')
        return sleeps

    async def test_expected_idle_expiry_reconnects_without_escalation(self):
        self.assertEqual(await self.sleeps_for([(60, 1000, 'received')] * 6), [.5] * 6)

    async def test_short_rooms_keep_exponential_backoff(self):
        self.assertEqual(await self.sleeps_for([(.2, 1000, 'received')] * 6), [.5, 1, 2, 4, 5, 5])

    async def test_locally_sent_or_abnormal_close_keeps_backoff(self):
        rooms = [(60, 1000, 'sent'), (60, 1011, 'sent'), (60, 1001, 'received')]
        self.assertEqual(await self.sleeps_for(rooms), [.5, 1, 2])

    async def test_idle_expiry_after_failures_resets_to_prompt_reconnect(self):
        rooms = [(.2, 1000, 'received')] * 3 + [(60, 1000, 'received')] * 2
        self.assertEqual(await self.sleeps_for(rooms), [.5, 1, 2, .5, .5])


class RelayLegKeepalive(unittest.IsolatedAsyncioTestCase):
    async def test_relay_legs_use_ten_second_keepalive(self):
        ws = SimpleNamespace(recv=AsyncMock(return_value='{"relayAttached": true}'), close=AsyncMock())
        with patch.object(wire, 'admission', return_value='session_peer=SECRET'), \
             patch.object(wire, 'PinnedConnect', new=AsyncMock(return_value=ws)) as connect:
            await wire.relay_stream('ws://127.0.0.1:2/v1/connect', 'SECRET')
        kwargs = connect.await_args.kwargs
        self.assertEqual((kwargs['ping_interval'], kwargs['ping_timeout']), (10, 10))



class RelayRoleBusyMetrics(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_role_is_refused_and_counted_per_role(self):
        from session_peer_relay.relay import Relay

        class Socket:
            def __init__(self, role):
                self.lab_account = {'room': 'SECRET-ROOM', 'role': role}
                self.lab_expiry = time.monotonic() + 10
                self.closed = asyncio.Event()
                self.close_code = None

            async def wait_closed(self):
                await self.closed.wait()

            async def close(self, code=1000, reason=''):
                if not self.closed.is_set():
                    self.close_code = code
                self.closed.set()

        relay = Relay([], diagnostic_events=True)
        relay.receiver_wait = relay.client_wait = .3
        with self.assertLogs('session_peer_relay.relay', level='WARNING') as logs:
            for role in ('receiver', 'client'):
                first, second = Socket(role), Socket(role)
                waiting = asyncio.create_task(relay.handler(first))
                async with asyncio.timeout(1):
                    while relay.metrics()['current']['waitingRooms'] != 1:
                        await asyncio.sleep(.002)
                await relay.handler(second)
                self.assertEqual(second.close_code, 1013)
                self.assertIsNone(first.close_code)
                await first.close()
                await waiting
        for role in ('receiver', 'client'):
            self.assertTrue(any('"role_busy"' in row and f'"role": "{role}"' in row
                                for row in logs.output))
        self.assertNotIn('SECRET-ROOM', '\n'.join(logs.output))
        counters = relay.metrics()['counters']
        self.assertEqual((counters['receiverRoleBusy'], counters['clientRoleBusy']), (1, 1))


if __name__ == '__main__':
    unittest.main()
