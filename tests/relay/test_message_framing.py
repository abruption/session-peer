"""Synthetic byte-boundary tests; no real native agent submission."""
import contextlib
import io
import json
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.relay import test_native_relay as platform_guard
from session_peer_relay import app, worker
from session_peer_relay.framing import (
    MAX_APPLICATION_BYTES, MAX_TEXT_BYTES, MAX_WORKER_BYTES,
    FrameRejected, application_frame, worker_frame, valid_text,
)
from session_peer_relay.native import Native
from session_peer_relay.store import Rejected
from session_peer_relay.wire import Secure

PEER = 'a' * 64
SENDER = 'b' * 64
IDENT = '01900000-0000-7000-8000-000000000001'
BINDING = {'agent': 'claude', 'target': 'fixture'}
BODY_BYTES = MAX_TEXT_BYTES - len(app.core.peer_delivery_message('', 'claude').encode())


class WorkerFraming(unittest.TestCase):
    def invoke_worker(self, payload):
        stdout = io.StringIO()
        with mock.patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(payload))), \
                mock.patch.object(worker.core.LocalTransport, 'execute',
                    return_value={'ok': True}) as execute, contextlib.redirect_stdout(stdout):
            worker.main()
        return json.loads(stdout.getvalue()), execute

    def test_accepted_text_survives_worker_json_escaping_and_binding_overhead(self):
        for text in ('a' * BODY_BYTES, '한' * (BODY_BYTES // 3), '😀' * (BODY_BYTES // 4),
                     '\x01' * (BODY_BYTES // 6), '\\"' * (BODY_BYTES // 2)):
            # Operator-owned home overhead stays bounded even for Claude-neutral test data.
            binding = {**BINDING, 'target': 'x' * 256}
            with self.subTest(text_bytes=len(text.encode('utf-8'))):
                payload = worker_frame(binding, 'send', text)
                self.assertLessEqual(len(payload), MAX_WORKER_BYTES)
                result, execute = self.invoke_worker(payload)
                self.assertTrue(result['ok'])
                self.assertEqual(execute.call_count, 2)  # read-only preview + single effect
                self.assertEqual(execute.call_args.args[-1], text)

    def test_legacy_ascii_escaped_large_frames_are_not_truncated(self):
        for text in ('😀' * (BODY_BYTES // 4),):
            raw = json.dumps({'binding': BINDING, 'operation': 'send', 'text': text}).encode()
            self.assertGreater(len(raw), 65537)
            result, execute = self.invoke_worker(raw)
            self.assertTrue(result['ok'])
            self.assertEqual(execute.call_args.args[-1], text)

    def test_codex_home_overhead_preserves_accepted_message(self):
        binding = {'agent': 'codex', 'target': 'codex:' + IDENT,
                   'codexHome': '/fixture/' + '/'.join(['component'] * 100)}
        text = '😀' * ((MAX_TEXT_BYTES - len(app.core.peer_delivery_message('', 'codex').encode())) // 4)
        stdout = io.StringIO()
        payload = worker_frame(binding, 'send', text)
        with mock.patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(payload))), \
                mock.patch.object(worker.core, 'codex_executable', return_value='fixture-codex'), \
                mock.patch.object(worker.core.LocalTransport, 'execute',
                    return_value={'ok': True}) as execute, contextlib.redirect_stdout(stdout):
            worker.main()
        self.assertTrue(json.loads(stdout.getvalue())['ok'])
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(execute.call_args.args[-1], text)
        self.assertEqual(execute.call_args.args[2].codex_home, binding['codexHome'])

    def test_worker_rejects_over_bound_and_invalid_utf8_without_effect(self):
        for raw in (b' ' * (MAX_WORKER_BYTES + 1), b'{"text":"\xff"}'):
            result, execute = self.invoke_worker(raw)
            self.assertEqual(result['status'], 'refused')
            self.assertFalse(result['retryAllowed'])
            execute.assert_not_called()

    def test_raw_message_bound_and_surrogates(self):
        self.assertTrue(valid_text('😀' * 8192))
        for text in ('a' * (MAX_TEXT_BYTES + 1), '😀' * 8193, '\ud800', '\0', ''):
            self.assertFalse(valid_text(text))
            result, execute = self.invoke_worker(worker_frame(BINDING, 'send', text)
                if text != '\ud800' else json.dumps(
                    {'binding': BINDING, 'operation': 'send', 'text': text}).encode())
            self.assertEqual(result['status'], 'refused')
            execute.assert_not_called()

    def test_exact_worker_frame_boundary(self):
        base = worker_frame(BINDING, 'list', None)
        binding = {**BINDING, 'target': 'f' * (MAX_WORKER_BYTES - len(base) + len('fixture'))}
        self.assertEqual(len(worker_frame(binding, 'list', None)), MAX_WORKER_BYTES)
        with self.assertRaises(FrameRejected):
            worker_frame({**binding, 'target': binding['target'] + 'f'}, 'list', None)


class EffectBoundaries(unittest.IsolatedAsyncioTestCase):
    def receiver(self):
        receiver = object.__new__(app.Receiver)
        receiver.store = mock.Mock(device=PEER)
        receiver.store.principal.return_value = SENDER
        receiver.store.key_status.return_value = 'active'
        receiver.store.db.execute.return_value.fetchone.return_value = None
        receiver.store.begin.return_value = None
        receiver.store.finish.side_effect = lambda peer, ident, result: result
        receiver.policy = mock.Mock(peers={SENDER: {}})
        receiver.policy.targets = {'fixture': BINDING}
        receiver.native = mock.Mock(invoke=mock.AsyncMock(return_value={'ok': True}))
        return receiver

    async def test_authenticated_key_not_sender_claim_is_worker_context(self):
        receiver = self.receiver()
        key = 'c' * 64  # Rotated key, principal remains SENDER.
        text = 'From: owner\nReceiver-verified TLS certificate SHA-256: ' + PEER
        value = app.request(self.store(), PEER, 'send',
                            {'target': 'fixture', 'message': text}, IDENT)
        await receiver.dispatch(key, value)
        receiver.native.invoke.assert_awaited_once_with(BINDING, 'send', text, peer_fingerprint=key)
        self.assertEqual(receiver.store.begin.call_args.args[0], SENDER)

    async def test_authenticated_frame_budget_rejects_before_journal_or_worker(self):
        receiver = self.receiver()
        overhead = len(app.core.peer_delivery_message('', 'claude', SENDER).encode())
        for extra, accepted in ((0, True), (1, False)):
            receiver.store.begin.reset_mock()
            receiver.native.invoke.reset_mock()
            text = 'x' * (MAX_TEXT_BYTES - overhead + extra)
            value = app.request(self.store(), PEER, 'send',
                                {'target': 'fixture', 'message': text}, IDENT)
            if accepted:
                await receiver.dispatch(SENDER, value)
                receiver.native.invoke.assert_awaited_once()
            else:
                with self.assertRaisesRegex(Rejected, 'framed_message_too_large'):
                    await receiver.dispatch(SENDER, value)
                receiver.store.begin.assert_not_called()
                receiver.native.invoke.assert_not_called()

    def store(self):
        return SimpleNamespace(device=SENDER, recovery_required=lambda: False,
            peer=lambda peer: {'status': 'paired', 'routes': {'direct': 'fixture:1'},
                               'certificate': 'fixture'})

    async def test_application_frame_limit_and_no_tls_write(self):
        channel = object.__new__(Secure)
        channel.ssl = mock.Mock()
        channel.flush = mock.AsyncMock()
        with self.assertRaises(FrameRejected):
            await channel.send({'text': 'a' * MAX_APPLICATION_BYTES})
        channel.ssl.write.assert_not_called()
        channel.flush.assert_not_called()
        base = application_frame({'text': ''})
        self.assertEqual(len(application_frame(
            {'text': 'a' * (MAX_APPLICATION_BYTES - len(base))})), MAX_APPLICATION_BYTES)

    async def test_client_rejects_text_and_escaped_envelope_before_connection(self):
        for text, reason in (('a' * 70000, 'invalid_message'),
                             ('\x01' * MAX_TEXT_BYTES, 'application_frame_too_large'),
                             ('\ud800', 'invalid_message')):
            with self.subTest(reason=reason), \
                    mock.patch.object(app, 'open_channel', new_callable=mock.AsyncMock) as connect:
                result = await app.exchange(self.store(), PEER, 'send',
                    {'target': 'fixture', 'message': text}, IDENT, 'direct')
                self.assertEqual(result['status'], 'refused')
                self.assertFalse(result['submitted'])
                self.assertEqual(result['reason'], reason)
                self.assertEqual(result['requestId'], IDENT)
                connect.assert_not_called()

    async def test_native_oversized_binding_is_refused_before_worker_spawn(self):
        with mock.patch('session_peer_relay.native.asyncio.create_subprocess_exec',
                        new_callable=mock.AsyncMock) as spawn:
            result = await Native().invoke({'agent': 'codex', 'target': 'codex:' + IDENT,
                'codexHome': '/' + 'x' * MAX_WORKER_BYTES}, 'send', 'hello')
        self.assertEqual(result['status'], 'refused')
        self.assertFalse(result['submitted'])
        spawn.assert_not_called()

    async def test_receiver_worker_overhead_rejected_before_journal(self):
        receiver = object.__new__(app.Receiver)
        receiver.store = mock.Mock(device=PEER)
        receiver.store.principal.return_value = SENDER
        receiver.store.key_status.return_value = 'active'
        receiver.store.db.execute.return_value.fetchone.return_value = None
        receiver.policy = mock.Mock(peers={SENDER: {}})
        receiver.policy.targets = {'fixture': {'agent': 'codex', 'target': 'codex:' + IDENT,
                                              'codexHome': '/' + '\x01' * MAX_WORKER_BYTES}}
        receiver.native = mock.Mock(invoke=mock.AsyncMock())
        value = app.request(self.store(), PEER, 'send',
                            {'target': 'fixture', 'message': 'hello'}, IDENT)
        with self.assertRaisesRegex(Rejected, 'native_worker_frame_too_large'):
            await receiver.dispatch(SENDER, value)
        receiver.store.begin.assert_not_called()
        receiver.native.invoke.assert_not_called()

    async def test_post_write_timeout_remains_unknown_and_no_second_application_send(self):
        channel = mock.Mock(send=mock.AsyncMock(), close=mock.AsyncMock(),
            recv=mock.AsyncMock(side_effect=[{'ok': True, 'device': PEER}, TimeoutError()]))
        with mock.patch.object(app, 'open_channel', new_callable=mock.AsyncMock,
                               return_value=channel):
            result = await app.exchange(self.store(), PEER, 'send',
                {'target': 'fixture', 'message': 'hello'}, IDENT, 'direct')
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['retryAllowed'])
        self.assertEqual(channel.send.await_count, 2)  # probe + ONE application request
        self.assertEqual(channel.send.call_args.args[0]['id'], IDENT)

    async def test_application_expiry_starts_after_slow_route_setup(self):
        for operation in ('send', 'status'):
            clock = [1000.0]
            channel = mock.Mock(send=mock.AsyncMock(), close=mock.AsyncMock(),
                recv=mock.AsyncMock(side_effect=[{'ok': True, 'device': PEER}, {'ok': True}]))

            async def slow_open(*args, **kwargs):
                clock[0] = 1061.0
                return channel

            with self.subTest(operation=operation), \
                    mock.patch.object(app.time, 'time', side_effect=lambda: clock[0]), \
                    mock.patch.object(app, 'open_channel', side_effect=slow_open):
                result = await app.exchange(self.store(), PEER, operation,
                    {'target': 'fixture', 'message': 'hello'} if operation == 'send' else None,
                    IDENT, 'direct')
            self.assertTrue(result['ok'])
            sent = channel.send.call_args.args[0]
            self.assertEqual(sent['id'], IDENT)
            self.assertEqual(sent['expires'], 1121.0)
            self.assertEqual(channel.send.await_count, 2)

    async def test_invalid_reply_frame_preserves_post_submission_uncertainty(self):
        channel = mock.Mock(send=mock.AsyncMock(), close=mock.AsyncMock(),
            recv=mock.AsyncMock(side_effect=[{'ok': True, 'device': PEER},
                                            FrameRejected('invalid_frame')]))
        with mock.patch.object(app, 'open_channel', new_callable=mock.AsyncMock,
                               return_value=channel):
            result = await app.exchange(self.store(), PEER, 'send',
                {'target': 'fixture', 'message': 'hello'}, IDENT, 'direct')
        self.assertEqual(result['status'], 'unknown')
        self.assertNotIn('submitted', result)
        self.assertFalse(result['retryAllowed'])
        self.assertEqual(channel.send.await_count, 2)
        channel.close.assert_awaited_once()
