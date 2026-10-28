"""Direct receiver stage diagnostics: bounded metadata, no native agent effects."""
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


if sys.version_info < (3, 11) or os.name != 'posix':
    raise unittest.SkipTest('Direct receiver requires Unix Python 3.11+')
try:
    from session_peer_relay import app, cli
    from session_peer_relay.identity import private_write
    from session_peer_relay.store import Store
except ImportError:
    raise unittest.SkipTest('optional relay dependencies absent')


POLICY = {'targets': {'fixture': {'agent': 'claude', 'target': 'fixture'}}, 'peers': {}}
SENTINEL = 'private-diagnostic-sentinel'


def diagnostic_rows(lines):
    rows = [json.loads(line.split('relay_lifecycle ', 1)[1]) for line in lines
            if 'relay_lifecycle ' in line]
    return [row for row in rows if row.get('event') == 'direct_transport']


class DirectDiagnostics(unittest.TestCase):
    def receiver(self, enabled=True):
        return app.Receiver(None, POLICY, diagnostic_events=enabled)

    def test_opt_out_collects_progress_without_emitting(self):
        receiver = self.receiver(False)
        with mock.patch.object(receiver, 'lifecycle_event') as emit:
            receiver.direct_event('accepted')
            receiver.direct_event('peer_tls', outcome='ok', elapsed_ms=1)
            receiver.direct_event('peer_tls', outcome='failed', elapsed_ms=2, reason='timeout')
        emit.assert_not_called()
        self.assertEqual(receiver.direct_diagnostic_counters,
                         {'accepted': 1, 'tlsCompleted': 1, 'tlsFailed': 1})

    def test_monotonic_per_phase_limit_keeps_suppressed_counters(self):
        receiver = self.receiver()
        with mock.patch.object(app.time, 'monotonic', return_value=100) as clock, \
             mock.patch.object(app.time, 'time', return_value=1000) as utc, \
             self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
            for _ in range(25):
                receiver.direct_event('accepted')
            for _ in range(10):
                receiver.direct_event('peer_tls', outcome='ok', elapsed_ms=3)
            for _ in range(5):
                receiver.direct_event('peer_tls', outcome='failed', elapsed_ms=4, reason='timeout')
            clock.return_value = 159.999
            utc.return_value = 10**12  # Wall-clock changes cannot reset a rate limit.
            receiver.direct_event('accepted')
            receiver.direct_event('peer_tls', outcome='ok', elapsed_ms=5)
            self.assertEqual(len(logs.output), 2)
            clock.return_value = 160
            receiver.direct_event('accepted')
            receiver.direct_event('peer_tls', outcome='ok', elapsed_ms=6)
        rows = diagnostic_rows(logs.output)
        self.assertEqual([row['phase'] for row in rows],
                         ['accepted', 'peer_tls', 'accepted', 'peer_tls'])
        self.assertEqual(rows[-1]['counters'],
                         {'accepted': 27, 'tlsCompleted': 12, 'tlsFailed': 5})
        self.assertEqual(rows[-1]['elapsedMs'], 6)
        self.assertNotIn('reason', rows[-1])

    def test_fixed_fields_redact_unknown_reasons_and_cap_numbers(self):
        receiver = self.receiver()
        maximum = (1 << 53) - 1
        receiver.direct_diagnostic_counters['tlsFailed'] = maximum
        with self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
            receiver.direct_event('peer_tls', outcome='failed', elapsed_ms=maximum + 1,
                                  reason=SENTINEL)
        row = diagnostic_rows(logs.output)[0]
        self.assertEqual(set(row), {'event', 'eventTimeUtcMs', 'phase', 'outcome',
                                    'elapsedMs', 'reason', 'counters'})
        self.assertEqual(row['event'], 'direct_transport')
        self.assertEqual(row['reason'], 'connection_failed')
        self.assertEqual(row['elapsedMs'], maximum)
        self.assertEqual(row['counters']['tlsFailed'], maximum)
        self.assertNotIn(SENTINEL, '\n'.join(logs.output))
        with mock.patch.object(receiver, 'lifecycle_event') as emit:
            receiver.direct_event(SENTINEL)
            receiver.direct_event('peer_tls', outcome=SENTINEL, reason=SENTINEL)
        emit.assert_not_called()

    def test_logger_failure_is_best_effort_and_still_rate_limited(self):
        receiver = self.receiver()
        with mock.patch.object(app.time, 'monotonic', return_value=10), \
             mock.patch.object(receiver, 'lifecycle_event', side_effect=RuntimeError(SENTINEL)) as emit:
            for _ in range(100):
                receiver.direct_event('accepted')
                receiver.direct_event('peer_tls', outcome='ok', elapsed_ms=1)
        self.assertEqual(emit.call_count, 2)
        self.assertEqual(receiver.direct_diagnostic_counters,
                         {'accepted': 100, 'tlsCompleted': 100, 'tlsFailed': 0})


class DirectCloseDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def test_close_emits_one_zero_progress_snapshot_without_network(self):
        receiver = app.Receiver(None, POLICY, diagnostic_events=True)
        with mock.patch.object(app.asyncio, 'open_connection', side_effect=AssertionError('network')), \
             self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
            await receiver.close()
            await receiver.close()
        rows = diagnostic_rows(logs.output)
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {'event', 'eventTimeUtcMs', 'phase', 'counters'})
        self.assertEqual(rows[0]['phase'], 'summary')
        self.assertEqual(rows[0]['counters'], {'accepted': 0, 'tlsCompleted': 0, 'tlsFailed': 0})

    async def test_summary_keeps_suppressed_progress_as_separate_shutdown_event(self):
        receiver = app.Receiver(None, POLICY, diagnostic_events=True)
        with mock.patch.object(app.time, 'monotonic', return_value=10), \
             self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
            for _ in range(20):
                receiver.direct_event('accepted')
                receiver.direct_event('peer_tls', outcome='ok', elapsed_ms=1)
            receiver.direct_event('peer_tls', outcome='failed', elapsed_ms=2, reason='timeout')
            await receiver.close()
            await receiver.close()
        rows = diagnostic_rows(logs.output)
        self.assertEqual([row['phase'] for row in rows], ['accepted', 'peer_tls', 'summary'])
        self.assertEqual(rows[-1]['counters'], {'accepted': 20, 'tlsCompleted': 20, 'tlsFailed': 1})

    async def test_close_logging_failure_is_not_retried_or_propagated(self):
        receiver = app.Receiver(None, POLICY, diagnostic_events=True)
        with mock.patch.object(receiver, 'lifecycle_event', side_effect=RuntimeError(SENTINEL)) as emit:
            await receiver.close()
            await receiver.close()
        self.assertEqual(emit.call_count, 1)
        self.assertTrue(receiver.direct_diagnostic_summary_attempted)

    async def test_close_with_diagnostics_disabled_emits_nothing(self):
        receiver = app.Receiver(None, POLICY, diagnostic_events=False)
        with mock.patch.object(receiver, 'lifecycle_event') as emit:
            await receiver.close()
            await receiver.close()
        emit.assert_not_called()


class DirectLoopbackDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='codex-direct-diagnostics-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.host, self.client = Store(self.root / 'receiver'), Store(self.root / 'client')
        self.addCleanup(self.client.close)
        self.addCleanup(self.host.close)
        policy = {**POLICY, 'peers': {
            self.client.device: {'capabilities': ['list'], 'targets': ['fixture']}}}
        self.receiver = app.Receiver(self.host, policy, diagnostic_events=True)
        self.receiver.native.invoke = mock.AsyncMock(side_effect=AssertionError('native effect'))
        self.server = await self.receiver.listen('127.0.0.1', 0)
        self.addAsyncCleanup(self.stop_server)
        port = self.server.sockets[0].getsockname()[1]
        self.routes = {'direct': '127.0.0.1:' + str(port)}

    async def stop_server(self):
        self.server.close()
        await self.receiver.close()
        await self.server.wait_closed()

    async def drained(self):
        async with asyncio.timeout(3):
            while self.receiver.tasks:
                await asyncio.sleep(.005)

    async def paired_probe(self):
        result = await app.pair(self.client, self.host.invite(self.routes), 'direct')
        self.assertTrue(result['ok'])
        result = await app.exchange(self.client, self.host.device, 'probe', route='direct')
        self.assertTrue(result['ok'])
        await self.drained()
        self.receiver.native.invoke.assert_not_awaited()
        self.assertFalse(self.receiver.connections)
        self.assertFalse(self.receiver.direct_preauth)
        self.assertFalse(self.receiver.authenticated)

    async def test_real_pair_and_probe_report_callback_and_tls_not_native_readiness(self):
        with self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
            await self.paired_probe()
        rows = diagnostic_rows(logs.output)
        self.assertEqual(len(rows), 2)  # One event per phase, not one per connection.
        self.assertEqual([row['phase'] for row in rows], ['accepted', 'peer_tls'])
        self.assertEqual(rows[1]['outcome'], 'ok')
        self.assertGreaterEqual(self.receiver.direct_diagnostic_counters['accepted'], 3)
        self.assertGreaterEqual(self.receiver.direct_diagnostic_counters['tlsCompleted'], 3)
        self.assertEqual(self.receiver.direct_diagnostic_counters['tlsFailed'], 0)
        encoded = json.dumps(rows)
        for private in (self.client.device, self.host.device, self.routes['direct'], str(self.root)):
            self.assertNotIn(private, encoded)
        self.assertTrue(all('attemptId' not in row and 'device' not in row for row in rows))

    async def test_direct_tls_timeout_reports_failure_and_preserves_cleanup(self):
        host, port = self.routes['direct'].split(':')
        with self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
            reader, writer = await asyncio.open_connection(host, int(port))
            try:
                # Accepted callback occurs before a TLS handshake can complete.
                async with asyncio.timeout(1):
                    while not self.receiver.direct_diagnostic_counters['accepted']:
                        await asyncio.sleep(.005)
                await self.drained()
                self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b'')
            finally:
                writer.close()
                await writer.wait_closed()
        rows = diagnostic_rows(logs.output)
        self.assertEqual([row['phase'] for row in rows], ['accepted', 'peer_tls'])
        self.assertEqual(rows[1]['outcome'], 'failed')
        self.assertEqual(rows[1]['reason'], 'timeout')
        self.assertEqual(self.receiver.direct_diagnostic_counters,
                         {'accepted': 1, 'tlsCompleted': 0, 'tlsFailed': 1})
        self.assertFalse(self.receiver.connections)
        self.receiver.native.invoke.assert_not_awaited()

    async def test_real_pair_and_probe_succeed_when_direct_logging_fails(self):
        with mock.patch.object(self.receiver, 'lifecycle_event', side_effect=RuntimeError(SENTINEL)):
            await self.paired_probe()
        self.assertGreaterEqual(self.receiver.direct_diagnostic_counters['tlsCompleted'], 3)

    async def test_classifier_failure_cannot_replace_original_direct_handshake_exception(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.receiver.diagnostic_events = enabled
                original = ValueError(SENTINEL)
                channel = mock.Mock()
                channel.handshake = mock.AsyncMock(side_effect=original)
                channel.close = mock.AsyncMock()
                channel.recv = mock.AsyncMock(side_effect=AssertionError('handshake must fail'))
                raw = app.Tcp(mock.Mock(), mock.Mock())
                observations = []
                direct_event = self.receiver.direct_event

                def observe(phase, **values):
                    active_before = sys.exception()
                    direct_event(phase, **values)
                    observations.append((phase, values.get('exception'), active_before, sys.exception()))

                with mock.patch.object(app, 'context'), \
                     mock.patch.object(app, 'Secure', return_value=channel), \
                     mock.patch.object(app, 'failure', side_effect=RuntimeError(SENTINEL)) as classify, \
                     mock.patch.object(self.receiver, 'lifecycle_event') as emit, \
                     mock.patch.object(self.receiver, 'direct_event', side_effect=observe):
                    rejected_before = self.receiver.rejected
                    await self.receiver.handle(raw)
                self.assertEqual(observations, [('peer_tls', original, original, original)])
                self.assertEqual(classify.call_count, int(enabled))
                self.assertEqual(self.receiver.rejected, rejected_before + 1)
                channel.recv.assert_not_awaited()
                channel.close.assert_awaited_once()
                emit.assert_not_called()
                self.receiver.native.invoke.assert_not_awaited()

    async def test_admission_refusal_increments_only_callback_progress(self):
        occupied = {object() for _ in range(app.DIRECT_PREAUTH_LIMIT)}
        self.receiver.direct_preauth.update(occupied)
        host, port = self.routes['direct'].split(':')
        try:
            with self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
                reader, writer = await asyncio.open_connection(host, int(port))
                try:
                    with contextlib.suppress(ConnectionResetError):
                        self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b'')
                finally:
                    writer.close()
                    with contextlib.suppress(ConnectionResetError):
                        await writer.wait_closed()
        finally:
            self.receiver.direct_preauth.difference_update(occupied)
        rows = diagnostic_rows(logs.output)
        self.assertEqual([row['phase'] for row in rows], ['accepted'])
        self.assertEqual(self.receiver.direct_diagnostic_counters,
                         {'accepted': 1, 'tlsCompleted': 0, 'tlsFailed': 0})
        self.assertEqual(self.receiver.admission_counters['directPreauthRefused'], 1)
        self.assertFalse(self.receiver.tasks)
        self.receiver.native.invoke.assert_not_awaited()

    async def test_websocket_tls_keeps_its_existing_event_and_no_direct_progress(self):
        raw = app.Ws(mock.Mock(), attempt_id='fixture-attempt')
        channel = mock.Mock(peer=None)
        channel.handshake = mock.AsyncMock()
        channel.recv = mock.AsyncMock(return_value={'op': 'fixture'})
        channel.send = mock.AsyncMock()
        channel.close = mock.AsyncMock()
        with mock.patch.object(app, 'context'), \
             mock.patch.object(app, 'Secure', return_value=channel), \
             mock.patch.object(self.receiver, 'dispatch', new_callable=mock.AsyncMock, return_value={'ok': True}), \
             self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
            await self.receiver.handle(raw)
        self.assertEqual(diagnostic_rows(logs.output), [])
        all_rows = [json.loads(line.split('relay_lifecycle ', 1)[1]) for line in logs.output]
        self.assertEqual(len(all_rows), 1)
        self.assertEqual(all_rows[0]['event'], 'peer_tls')
        self.assertEqual(all_rows[0]['attemptId'], 'fixture-attempt')
        self.assertEqual(self.receiver.direct_diagnostic_counters,
                         {'accepted': 0, 'tlsCompleted': 0, 'tlsFailed': 0})
        self.receiver.native.invoke.assert_not_awaited()

    async def test_shutdown_cancellation_does_not_report_a_tls_failure(self):
        started = asyncio.Event()
        original_handshake = app.Secure.handshake

        async def handshake(channel):
            started.set()
            return await original_handshake(channel)

        host, port = self.routes['direct'].split(':')
        with mock.patch.object(app.Secure, 'handshake', new=handshake), \
             self.assertLogs('session_peer_relay.app', level='WARNING') as logs:
            reader, writer = await asyncio.open_connection(host, int(port))
            try:
                await asyncio.wait_for(started.wait(), 1)
                self.server.close()
                await self.receiver.close()
                await self.receiver.close()
                await self.server.wait_closed()
                self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b'')
            finally:
                writer.close()
                await writer.wait_closed()
        rows = diagnostic_rows(logs.output)
        self.assertEqual([row['phase'] for row in rows], ['accepted', 'summary'])
        self.assertEqual(rows[-1]['counters'], {'accepted': 1, 'tlsCompleted': 0, 'tlsFailed': 0})
        self.assertFalse(self.receiver.connections)
        self.receiver.native.invoke.assert_not_awaited()

    async def test_startup_keeps_legacy_ready_without_claiming_a_direct_roundtrip(self):
        root = self.root / 'cli-receiver'
        store = Store(root)
        store.close()
        policy = root / 'policy.json'
        private_write(policy, json.dumps(POLICY))
        args = cli.parser('device').parse_args([
            'serve', '--state', str(root), '--policy', str(policy),
            '--bind', '127.0.0.1', '--port', '0', '--seconds', '1'])
        with contextlib.redirect_stdout(io.StringIO()) as output, \
             mock.patch.object(cli, 'lifetime', new_callable=mock.AsyncMock), \
             mock.patch.object(app, 'Secure', side_effect=AssertionError('implicit TLS probe')), \
             mock.patch.object(app.Native, 'invoke', new_callable=mock.AsyncMock) as native:
            result = await cli.manage('device', args)
        row = json.loads(output.getvalue())
        self.assertTrue(result['stopped'])
        self.assertTrue(row['ok'])
        self.assertTrue(row['ready'])
        self.assertGreater(row['directPort'], 0)
        self.assertIs(row['directReadyConfirmed'], False)
        self.assertIs(row['relayReadyConfirmed'], False)
        native.assert_not_awaited()
