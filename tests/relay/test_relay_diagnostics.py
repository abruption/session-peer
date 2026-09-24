"""Metadata-only lifecycle evidence and scaled stale-room fixtures."""
import asyncio
import json
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from tests.relay import test_native_relay as platform_guard
from session_peer_relay import app
from session_peer_relay.cli import parser
from session_peer_relay.relay import Relay
from session_peer_relay.transport_errors import TransportFailure


class FakeWebSocket:
    def __init__(self, role, *, stalled=False, stalled_data=False, frames=None):
        self.lab_account = {'room': 'SECRET-ROOM', 'role': role}
        self.lab_expiry = time.monotonic() + 10
        self.stalled = stalled
        self.stalled_data = stalled_data
        self.frames = list(frames or [])
        self.closed = asyncio.Event()
        self.close_code = None
        self.sent = []

    async def send(self, value):
        if self.stalled or (self.stalled_data and isinstance(value, bytes)):
            await self.closed.wait()
        self.sent.append(value)

    async def wait_closed(self):
        await self.closed.wait()

    async def close(self, code=1000, reason=''):
        if not self.closed.is_set():
            self.close_code = code
        self.closed.set()

    async def remote_close(self, code):
        self.close_code = code
        self.closed.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.frames:
            return self.frames.pop(0)
        await self.closed.wait()
        raise StopAsyncIteration


class RelayLifecycle(unittest.IsolatedAsyncioTestCase):
    async def wait_for(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(.002)

    async def paired_close_events(self, role, code):
        relay = Relay([], diagnostic_events=True)
        receiver = FakeWebSocket('receiver')
        client = FakeWebSocket('client')
        tasks = []
        with self.assertLogs('session_peer_relay.relay', level='WARNING') as logs:
            try:
                tasks.append(asyncio.create_task(relay.handler(receiver)))
                await self.wait_for(lambda: relay.metrics()['current']['waitingRooms'] == 1)
                tasks.append(asyncio.create_task(relay.handler(client)))
                await self.wait_for(lambda: relay.metrics()['counters']['attachSentReceiver'] == 1
                                    and relay.metrics()['counters']['attachSentClient'] == 1)
                await (receiver if role == 'receiver' else client).remote_close(code)
                await asyncio.wait_for(asyncio.gather(*tasks), 1)
            finally:
                await receiver.close()
                await client.close()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        self.assertNotIn('SECRET-ROOM', '\n'.join(logs.output))
        return [json.loads(row.split('relay_room ', 1)[1]) for row in logs.output
                if 'relay_room ' in row]

    async def test_relay_closes_other_leg_as_peer_closed(self):
        events = await self.paired_close_events('receiver', 1000)
        self.assertTrue(any(row['event'] == 'stream_close' and row['role'] == 'client'
                            and row['reason'] == 'peer_closed' for row in events))

    async def test_attempt_id_is_echoed_only_to_capable_legs(self):
        relay = Relay([], diagnostic_events=True)
        receiver = FakeWebSocket('receiver')  # Older receiver expects the bare frame.
        client = FakeWebSocket('client')
        client.lab_attempt_id = str(uuid.uuid4())
        client.lab_diagnostic_capable = True
        tasks = []
        with self.assertLogs('session_peer_relay.relay', level='WARNING') as logs:
            try:
                tasks.append(asyncio.create_task(relay.handler(receiver)))
                await self.wait_for(lambda: relay.metrics()['current']['waitingRooms'] == 1)
                tasks.append(asyncio.create_task(relay.handler(client)))
                await self.wait_for(lambda: relay.metrics()['counters']['attachSentReceiver'] == 1
                                    and relay.metrics()['counters']['attachSentClient'] == 1)
                self.assertEqual(json.loads(receiver.sent[0]), {'relayAttached': True})
                self.assertEqual(json.loads(client.sent[0]),
                                 {'relayAttached': True, 'attemptId': client.lab_attempt_id})
            finally:
                await receiver.close()
                await client.close()
                await asyncio.wait_for(asyncio.gather(*tasks), 1)
        paired = [json.loads(row.split('relay_room ', 1)[1]) for row in logs.output
                  if 'room_paired' in row]
        self.assertEqual(len(paired), 1)
        self.assertEqual(paired[0]['attemptId'], client.lab_attempt_id)
        self.assertNotIn('SECRET-ROOM', '\n'.join(logs.output))

    async def test_remote_1001_is_not_mislabelled_as_peer_closed(self):
        events = await self.paired_close_events('client', 1001)
        self.assertTrue(any(row['event'] == 'stream_close' and row['role'] == 'client'
                            and row['reason'] == 'remote_going_away' and row['closeCode'] == 1001
                            for row in events))

    async def test_idle_receiver_expiry_is_counted_without_identity(self):
        relay = Relay([], diagnostic_events=True)
        relay.receiver_wait = .02  # scaled fixture; production bound stays 60 s
        receiver = FakeWebSocket('receiver')
        with self.assertLogs('session_peer_relay.relay', level='WARNING') as logs:
            await relay.handler(receiver)
        self.assertEqual(relay.metrics()['counters']['receiverIdleExpired'], 1)
        self.assertEqual(relay.metrics()['counters']['receiverRoomsOpened'], 1)
        self.assertEqual(relay.metrics()['counters']['clientFirstRooms'], 0)
        self.assertEqual(relay.metrics()['counters']['roomsClosedBeforeAttach'], 1)
        self.assertEqual(relay.metrics()['current']['waitingRooms'], 0)
        self.assertTrue(any('receiver_idle_expiry' in row for row in logs.output))
        self.assertTrue(any('"openedBy": "receiver"' in row for row in logs.output))
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
            self.assertEqual(relay.metrics()['counters']['clientFirstRooms'], 1)
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
        self.assertTrue(any('"reason": "attach_notify_failed"' in row for row in logs.output))
        self.assertNotIn('SECRET-ROOM', '\n'.join(logs.output))

    async def test_paired_stream_records_only_per_leg_frame_metadata(self):
        relay = Relay([], diagnostic_events=True)
        receiver_payload = b'receiver-ciphertext-secret'
        client_payload = b'client-ciphertext-secret'
        receiver = FakeWebSocket('receiver', frames=[receiver_payload])
        client = FakeWebSocket('client', frames=[client_payload])
        tasks = []
        with self.assertLogs('session_peer_relay.relay', level='WARNING') as logs:
            try:
                tasks.append(asyncio.create_task(relay.handler(receiver)))
                await self.wait_for(lambda: relay.metrics()['current']['waitingRooms'] == 1)
                tasks.append(asyncio.create_task(relay.handler(client)))
                await self.wait_for(lambda: client_payload in receiver.sent
                                    and receiver_payload in client.sent)
            finally:
                await receiver.close()
                await client.close()
                await asyncio.wait_for(asyncio.gather(*tasks), 1)
        events = [json.loads(row.split('relay_room ', 1)[1]) for row in logs.output
                  if 'relay_room ' in row]
        streams = {row['role']: row for row in events if row['event'] == 'stream_close'}
        self.assertEqual(set(streams), {'client', 'receiver'})
        for role, payload in (('client', client_payload), ('receiver', receiver_payload)):
            row = streams[role]
            self.assertEqual(row['ingressFrames'], 1)
            self.assertEqual(row['ingressBytes'], len(payload))
            self.assertEqual(row['egressCompletedFrames'], 1)
            self.assertEqual(row['egressCompletedBytes'], len(payload))
            self.assertLessEqual(row['firstIngressUtcMs'], row['lastEgressCompletedUtcMs'])
        self.assertNotIn('SECRET-ROOM', '\n'.join(logs.output))
        self.assertNotIn('ciphertext-secret', '\n'.join(logs.output))

    async def test_stream_lifetime_and_forward_timeout_are_distinct(self):
        for expected in ('stream_lifetime_expiry', 'forward_send_timeout'):
            with self.subTest(reason=expected):
                relay = Relay([], diagnostic_events=True)
                receiver = FakeWebSocket('receiver', stalled_data=expected == 'forward_send_timeout')
                client = FakeWebSocket('client', frames=[b'opaque'] if expected == 'forward_send_timeout' else [])
                if expected == 'stream_lifetime_expiry':
                    receiver.lab_expiry = client.lab_expiry = time.monotonic() + .04
                tasks = []
                with self.assertLogs('session_peer_relay.relay', level='WARNING') as logs:
                    try:
                        tasks.append(asyncio.create_task(relay.handler(receiver)))
                        await self.wait_for(lambda: relay.metrics()['current']['waitingRooms'] == 1)
                        tasks.append(asyncio.create_task(relay.handler(client)))
                        await asyncio.wait_for(asyncio.gather(*tasks), 3)
                    finally:
                        await receiver.close()
                        await client.close()
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                self.assertTrue(any('"reason": "'+expected+'"' in row for row in logs.output))
                self.assertTrue(any('"closeCode": 1000' in row for row in logs.output))
                if expected == 'forward_send_timeout':
                    streams = [json.loads(row.split('relay_room ', 1)[1]) for row in logs.output
                               if '"event": "stream_close"' in row and '"role": "client"' in row]
                    self.assertEqual(len(streams), 1)
                    self.assertEqual(streams[0]['ingressFrames'], 1)
                    self.assertEqual(streams[0]['egressCompletedFrames'], 0)
                    self.assertIsNone(streams[0]['firstEgressCompletedUtcMs'])
                self.assertNotIn('SECRET-ROOM', '\n'.join(logs.output))


class ReceiverLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_native_preflight_refusal_has_only_allowlisted_diagnostics(self):
        store = Mock(device='b'*64)
        store.principal.return_value = 'a'*64
        store.key_status.return_value = 'active'
        store.db.execute.return_value.fetchone.return_value = None
        receiver = app.Receiver(store, {
            'targets': {'review': {'agent': 'codex', 'target': 'codex:'+str(uuid.uuid4()),
                                   'codexHome': '/fixture'}},
            'peers': {'a'*64: {'capabilities': ['send'], 'targets': ['review']}},
        }, diagnostic_events=True)
        receiver.native.invoke = AsyncMock(return_value={
            'ok': False, 'status': 'refused', 'reason': 'codex_executable_not_found',
            'retryAllowed': False, 'consumptionConfirmed': False})
        request = {'v': 1, 'sender': 'a'*64, 'receiver': store.device,
                   'id': str(uuid.uuid4()), 'expires': time.time()+30, 'op': 'resolve',
                   'body': {'target': 'review', 'message': 'SECRET-MESSAGE'}}
        with patch.object(app.logging, 'getLogger') as logger:
            result = await receiver.dispatch('certificate', request)
        self.assertEqual(result['status'], 'refused')
        row = logger.return_value.warning.call_args.args[1]
        self.assertIn('codex_executable_not_found', row)
        self.assertNotIn('SECRET-MESSAGE', row)
        self.assertNotIn('/fixture', row)

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
        clock = [0]

        async def connect(url, credential, *, attach_timeout, on_event):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise asyncio.CancelledError()
            on_event('websocket_open', elapsed_ms=2)
            clock[0] = 60
            raise TransportFailure('relay_attach', 'connection_closed', close_code=1000,
                                   close_source='received')

        with patch.object(app, 'relay_stream', side_effect=connect), \
             patch.object(app, 'time', SimpleNamespace(monotonic=lambda: clock[0], time=time.time)), \
             patch.object(app.asyncio, 'sleep', new=AsyncMock()), \
             patch.object(app.logging, 'getLogger') as logger:
            with self.assertRaises(asyncio.CancelledError):
                await receiver.relay_listener('wss://relay.example.test/v1/connect', 'SECRET')
        rows = [str(call) for call in logger.return_value.warning.call_args_list]
        self.assertTrue(any('idle_expiry' in row for row in rows))
        self.assertFalse(any('relay_connection_failed' in row for row in rows))
        self.assertNotIn('SECRET', '\n'.join(rows))

    async def test_sent_close_code_is_not_classified_as_idle_expiry(self):
        receiver = app.Receiver(Mock(), {'targets': {'worker': {'agent': 'claude', 'target': 'worker'}},
                                         'peers': {}}, diagnostic_events=True)
        calls = 0
        clock = [0]

        async def connect(url, credential, *, attach_timeout, on_event):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise asyncio.CancelledError()
            on_event('websocket_open', elapsed_ms=2)
            clock[0] = 60
            raise TransportFailure('relay_attach', 'connection_closed', close_code=1011,
                                   close_source='sent')

        with patch.object(app, 'relay_stream', side_effect=connect), \
             patch.object(app, 'time', SimpleNamespace(monotonic=lambda: clock[0], time=time.time)), \
             patch.object(app.asyncio, 'sleep', new=AsyncMock()), \
             patch.object(app.logging, 'getLogger') as logger:
            with self.assertRaises(asyncio.CancelledError):
                await receiver.relay_listener('wss://relay.example.test/v1/connect', 'SECRET')
        rows = [str(call) for call in logger.return_value.warning.call_args_list]
        self.assertTrue(any('relay_connection_failed' in row for row in rows))
        self.assertFalse(any('idle_expiry_like' in row for row in rows))

    async def test_consumed_room_is_not_reused_for_next_setup_failure(self):
        receiver = app.Receiver(Mock(), {'targets': {'worker': {'agent': 'claude', 'target': 'worker'}},
                                         'peers': {}}, diagnostic_events=True)
        calls = 0
        clock = [0]

        async def connect(url, credential, *, attach_timeout, on_event):
            nonlocal calls
            calls += 1
            if calls == 1:
                clock[0] = 1
                on_event('websocket_open', elapsed_ms=2)
                on_event('attach_received', elapsed_ms=3)
                return object()
            if calls == 2:
                clock[0] = 2
                raise TransportFailure('relay_admission', 'timeout', transient=True)
            clock[0] = 3
            on_event('websocket_open', elapsed_ms=2)
            raise asyncio.CancelledError()

        with patch.object(receiver, 'spawn') as spawn, \
             patch.object(app, 'relay_stream', side_effect=connect), \
             patch.object(app, 'time', SimpleNamespace(monotonic=lambda: clock[0], time=time.time)), \
             patch.object(app.asyncio, 'sleep', new=AsyncMock()), \
             patch.object(app.logging, 'getLogger') as logger:
            with self.assertRaises(asyncio.CancelledError):
                await receiver.relay_listener('wss://relay.example.test/v1/connect', 'SECRET')
        spawn.assert_called_once()
        rows = [str(call) for call in logger.return_value.warning.call_args_list]
        self.assertTrue(any('setup_failed' in row for row in rows))
        self.assertTrue(any('reconnect_gap' in row for row in rows))
        self.assertFalse(any('websocket_closed' in row for row in rows))


if __name__ == '__main__':
    unittest.main()
