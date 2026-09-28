import hashlib
import unittest
from types import SimpleNamespace

from tests.relay import test_native_relay as platform_guard
from websockets.datastructures import Headers

from session_peer_relay import relay as relay_module
from session_peer_relay.relay import Relay, RelayLimits

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


if __name__ == '__main__':
    unittest.main()
