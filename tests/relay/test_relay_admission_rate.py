import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.relay import test_native_relay as platform_guard
from websockets.datastructures import Headers

from session_peer_relay import relay as relay_module
from session_peer_relay.cli import manage, parser
from session_peer_relay.identity import private_write
from session_peer_relay.relay import Relay, RelayLimits
from session_peer_relay.store import Rejected

TOKEN = 'valid-admission-token'
SECRET = 'p' * 40


class Connection:
    def __init__(self, address=None):
        self.remote_address = address

    def respond(self, status, text):
        return SimpleNamespace(status_code=status, headers=Headers(), body=text)


def request(path, headers=()):
    return SimpleNamespace(path=path, headers=Headers(headers))


def make_relay(**options):
    limits = RelayLimits(handshake_rate=options.pop('handshake_rate', 20),
                         client_handshake_rate=options.pop('client_handshake_rate', 5))
    accounts = [{'role': 'client', 'room': 'room', 'hash': hashlib.sha256(TOKEN.encode()).hexdigest()}]
    return Relay(accounts, limits=limits, **options)


async def admit(relay, connection, headers=()):
    return (await relay.process_request(connection, request(
        '/v1/session', {'Authorization': 'Bearer ' + TOKEN, **dict(headers)}))).status_code


async def attempt(relay, connection, headers=()):
    return (await relay.process_request(connection, request(
        '/v1/session', {'Authorization': 'Bearer wrong', **dict(headers)}))).status_code


class AdmissionRate(unittest.IsolatedAsyncioTestCase):
    def test_client_rate_is_bounded(self):
        self.assertEqual(RelayLimits().validate().client_handshake_rate, 5)
        for value in (0, 1001, True):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'invalid_relay_limits'):
                RelayLimits(client_handshake_rate=value).validate()

    async def test_unknown_paths_and_ticketless_connects_do_not_spend_admission_budget(self):
        relay = make_relay()
        connection = Connection()
        for _ in range(200):
            self.assertEqual((await relay.process_request(connection, request('/junk'))).status_code, 404)
            self.assertEqual((await relay.process_request(connection, request(
                '/v1/connect', {'Cookie': 'session_peer=missing'}))).status_code, 401)
        self.assertEqual(await admit(relay, connection), 200)
        counters = relay.metrics()['counters']
        self.assertEqual(counters['notFound'], 200)
        self.assertEqual(counters['rateRejected'], 0)

    async def test_direct_source_cannot_drain_the_global_window(self):
        relay = make_relay()
        noisy = Connection(('203.0.113.5', 50000))
        statuses = [await attempt(relay, noisy) for _ in range(30)]
        self.assertEqual(statuses[:5], [401] * 5)
        self.assertEqual(set(statuses[5:]), {429})
        self.assertEqual(await admit(relay, Connection(('198.51.100.7', 50001))), 200)
        counters = relay.metrics()['counters']
        self.assertEqual(counters['clientRateRejected'], 25)
        self.assertEqual(counters['rateRejected'], 0)

    async def test_global_window_remains_the_backstop(self):
        relay = make_relay(handshake_rate=4, client_handshake_rate=5)
        statuses = [await attempt(relay, Connection((f'203.0.113.{n}', 50000))) for n in range(6)]
        self.assertEqual(statuses, [401] * 4 + [429] * 2)
        self.assertEqual(relay.metrics()['counters']['rateRejected'], 2)

    async def test_loopback_without_proxy_secret_uses_only_the_global_window(self):
        relay = make_relay()
        loopback = Connection(('127.0.0.1', 50000))
        spoof = {'X-Session-Peer-Client-IP': '203.0.113.5', 'X-Forwarded-For': '203.0.113.5'}
        statuses = [await attempt(relay, loopback, spoof) for _ in range(20)]
        self.assertEqual(set(statuses), {401})
        self.assertEqual(relay.client_requests, {})

    async def test_authorized_proxy_headers_identify_the_source(self):
        relay = make_relay(proxy_secret=SECRET)
        proxy = Connection(('127.0.0.1', 50000))
        noisy = {'X-Session-Peer-Proxy-Token': SECRET, 'X-Session-Peer-Client-IP': '203.0.113.5'}
        statuses = [await attempt(relay, proxy, noisy) for _ in range(8)]
        self.assertEqual(statuses, [401] * 5 + [429] * 3)
        other = {'X-Session-Peer-Proxy-Token': SECRET, 'X-Session-Peer-Client-IP': '198.51.100.7'}
        self.assertEqual(await admit(relay, proxy, other), 200)

    async def test_forged_or_remote_proxy_headers_are_ignored(self):
        relay = make_relay(proxy_secret=SECRET)
        forged = {'X-Session-Peer-Proxy-Token': 'x' * 40, 'X-Session-Peer-Client-IP': '203.0.113.5'}
        self.assertEqual(await attempt(relay, Connection(('127.0.0.1', 50000)), forged), 401)
        self.assertEqual(relay.client_requests, {})
        remote = {'X-Session-Peer-Proxy-Token': SECRET, 'X-Session-Peer-Client-IP': '198.51.100.9'}
        self.assertEqual(await attempt(relay, Connection(('203.0.113.8', 50000)), remote), 401)
        self.assertEqual(list(relay.client_requests), ['203.0.113.8'])

    async def test_ipv6_sources_share_a_slash_64_window(self):
        relay = make_relay()
        statuses = [await attempt(relay, Connection((f'2001:db8:1:2::{n:x}', 50000, 0, 0)))
                    for n in range(1, 8)]
        self.assertEqual(statuses, [401] * 5 + [429] * 2)
        self.assertEqual(list(relay.client_requests), ['2001:db8:1:2::/64'])
        mapped = Connection(('::ffff:203.0.113.5', 50000, 0, 0))
        await attempt(relay, mapped)
        self.assertIn('203.0.113.5', relay.client_requests)

    async def test_client_window_table_is_bounded(self):
        relay = make_relay(handshake_rate=1000)
        original = relay_module.MAX_CLIENT_WINDOWS
        relay_module.MAX_CLIENT_WINDOWS = 3
        try:
            for n in range(5):
                await attempt(relay, Connection((f'203.0.113.{n}', 50000)))
            self.assertLessEqual(len(relay.client_requests), 3)
        finally:
            relay_module.MAX_CLIENT_WINDOWS = original

    async def test_global_saturation_across_many_sources_recovers_without_errors(self):
        relay = make_relay()
        clock = [100.0]
        with mock.patch.object(relay_module.time, 'monotonic', lambda: clock[0]):
            statuses = [await attempt(relay, Connection((f'10.{n >> 16 & 255}.{n >> 8 & 255}.{n & 255}', 1)))
                        for n in range(relay_module.MAX_CLIENT_WINDOWS)]
            self.assertEqual(statuses.count(401), 20)
            self.assertEqual(statuses.count(429), relay_module.MAX_CLIENT_WINDOWS - 20)
            self.assertEqual(len(relay.client_requests), 20)
            self.assertTrue(all(relay.client_requests.values()))
            self.assertEqual(await attempt(relay, Connection(('192.0.2.1', 1))), 429)
            clock[0] = 102.0
            self.assertEqual(await attempt(relay, Connection(('192.0.2.2', 1))), 401)
            self.assertEqual(await admit(relay, Connection(('192.0.2.3', 1))), 200)

    async def test_full_table_of_live_windows_falls_back_to_the_global_window(self):
        relay = make_relay(handshake_rate=1000)
        with mock.patch.object(relay_module, 'MAX_CLIENT_WINDOWS', 3):
            for n in range(3):
                await attempt(relay, Connection((f'203.0.113.{n}', 1)))
            self.assertEqual(await attempt(relay, Connection(('198.51.100.1', 1))), 401)
            self.assertNotIn('198.51.100.1', relay.client_requests)
            self.assertEqual(len(relay.client_requests), 3)

    async def test_source_window_expires(self):
        relay = make_relay()
        clock = [100.0]
        source = Connection(('203.0.113.5', 1))
        with mock.patch.object(relay_module.time, 'monotonic', lambda: clock[0]):
            self.assertEqual([await attempt(relay, source) for _ in range(6)], [401] * 5 + [429])
            clock[0] = 101.5
            self.assertEqual(await attempt(relay, source), 401)

    async def test_duplicated_proxy_headers_use_only_the_global_window(self):
        relay = make_relay(proxy_secret=SECRET)
        headers = Headers()
        headers['X-Session-Peer-Proxy-Token'] = SECRET
        headers['X-Session-Peer-Client-IP'] = '203.0.113.5'
        headers['X-Session-Peer-Client-IP'] = '198.51.100.7'
        response = await relay.process_request(Connection(('127.0.0.1', 1)), SimpleNamespace(
            path='/v1/session', headers=headers))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(relay.client_requests, {})

    def test_metrics_keep_the_schema_v1_capacity_contract(self):
        metrics = make_relay().metrics()
        self.assertEqual(metrics['schemaVersion'], 1)
        # control/src/server/metrics.ts accepts exactly these capacity keys.
        self.assertEqual(sorted(metrics['capacity']), sorted([
            'handshake_rate', 'pending_sessions', 'global_connections',
            'user_connections', 'device_connections', 'connection_byte_budget']))
        self.assertEqual(metrics['sourceCapacity'], {'client_handshake_rate': 5})
        self.assertIn('clientRateRejected', metrics['counters'])
        self.assertIn('notFound', metrics['counters'])

    async def test_trusted_proxy_secret_file_must_be_long_enough(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            os.chmod(root, 0o700)
            accounts = root / 'accounts.json'
            private_write(accounts, '[{"role": "client", "room": "room", "hash": "%s"}]' % ('a' * 64))
            short = root / 'proxy-secret'
            private_write(short, 'too-short\n')
            args = parser('relay').parse_args([
                'serve', '--accounts', str(accounts), '--trusted-proxy-secret-file', str(short),
                '--port', '0', '--seconds', '1'])
            with self.assertRaisesRegex(Rejected, 'invalid_trusted_proxy_secret'):
                await manage('relay', args)
            missing = parser('relay').parse_args([
                'serve', '--accounts', str(accounts), '--trusted-proxy-secret-file', str(root / 'absent'),
                '--port', '0', '--seconds', '1'])
            with self.assertRaisesRegex(Rejected, 'invalid_trusted_proxy_secret'):
                await manage('relay', missing)


if __name__ == '__main__':
    unittest.main()
