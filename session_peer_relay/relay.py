"""Authenticated online-only blind relay. Never imports endpoint identity keys."""
import asyncio
from dataclasses import asdict, dataclass
import hashlib
from http import HTTPStatus
from http.cookies import SimpleCookie
import json
import logging
import secrets
import time

from websockets.asyncio.server import serve

from .wire import MAX_FRAME


@dataclass(frozen=True)
class RelayLimits:
    handshake_rate: int = 20
    pending_sessions: int = 100
    global_connections: int = 10
    user_connections: int = 8
    device_connections: int = 4
    connection_byte_budget: int = 32 * 1024 * 1024

    def validate(self):
        bounds = {
            'handshake_rate': (1, 1000),
            'pending_sessions': (1, 10000),
            'global_connections': (2, 10000),
            'user_connections': (1, 1000),
            'device_connections': (1, 1000),
            'connection_byte_budget': (MAX_FRAME, 1024 * 1024 * 1024),
        }
        for name, (minimum, maximum) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError('invalid_relay_limits')
        if (self.device_connections > self.user_connections
                or self.user_connections > self.global_connections):
            raise ValueError('invalid_relay_limits')
        return self


class Relay:
    def __init__(self, accounts, *, capture=None, control=None, limits=None, diagnostic_events=False):
        # Provisioned admission hashes are independent of end-to-end TLS identities.
        self.accounts = accounts
        self.control = control
        self.limits = (limits or RelayLimits()).validate()
        self.sessions = {}
        self.waiting = {}
        self.connections = set()
        self.capture = capture  # in-memory adversarial test hook, never enabled by CLI
        self.diagnostic_events = diagnostic_events
        self.bytes = 0
        self.forwarded_frames = 0
        self.rejected = 0
        self.requests = []
        self.started_at = time.time()
        self.started_monotonic = time.monotonic()
        # Fixed production bounds; tests may shorten them on an isolated Relay.
        self.receiver_wait = 60
        self.client_wait = 10
        self.counters = {
            'handshakes': 0,
            'sessionsIssued': 0,
            'connectionsAccepted': 0,
            'rateRejected': 0,
            'sessionCapacityRejected': 0,
            'connectionCapacityRejected': 0,
            'unauthorizedRejected': 0,
            'byteBudgetClosed': 0,
            'roomsOpened': 0,
            'roomsPaired': 0,
            'attachSentReceiver': 0,
            'attachSentClient': 0,
            'receiverIdleExpired': 0,
            'clientWaitExpired': 0,
            'roomsClosedBeforeAttach': 0,
        }

    def diagnostic_event(self, event, **values):
        if self.diagnostic_events:
            logging.getLogger(__name__).warning('relay_room %s',
                json.dumps({'event': event, **values}, sort_keys=True))

    def metrics(self):
        now = time.monotonic()
        self.sessions = {key: value for key, value in self.sessions.items() if value[0] > now}
        return {
            'schemaVersion': 1,
            'generatedAt': int(time.time() * 1000),
            'uptimeSeconds': max(0, int(now - self.started_monotonic)),
            'capacity': asdict(self.limits),
            'current': {
                'activeConnections': len(self.connections),
                'waitingRooms': len(self.waiting),
                'pendingSessions': len(self.sessions),
            },
            'counters': {
                **self.counters,
                'forwardedFrames': self.forwarded_frames,
                'forwardedBytes': self.bytes,
            },
        }

    def response(self, connection, status, text):
        response = connection.respond(status, text)
        response.headers['Cache-Control'] = 'no-store'
        return response

    async def process_request(self, connection, request):
        now = time.monotonic()
        self.counters['handshakes'] += 1
        self.requests = [stamp for stamp in self.requests if stamp > now-1]
        if len(self.requests) >= self.limits.handshake_rate:
            self.rejected += 1
            self.counters['rateRejected'] += 1
            return self.response(connection, HTTPStatus.TOO_MANY_REQUESTS, 'rate_limited\n')
        self.requests.append(now)
        self.sessions = {key: value for key, value in self.sessions.items() if value[0] > now}
        if request.path == '/v1/session':
            # Capacity rejection must not consume a control admission JTI.
            if len(self.sessions) >= self.limits.pending_sessions:
                self.rejected += 1
                self.counters['sessionCapacityRejected'] += 1
                return self.response(connection, HTTPStatus.SERVICE_UNAVAILABLE, 'capacity\n')
            auth = request.headers.get('Authorization', '')
            if self.control:
                try:
                    account = self.control.authorize(auth.removeprefix('Bearer '), request.headers.get('X-Session-Peer-Proof', '')) if auth.startswith('Bearer ') else None
                except ValueError:
                    account = None
            else:
                digest = hashlib.sha256(auth.removeprefix('Bearer ').encode()).hexdigest()
                account = next((a for a in self.accounts if auth.startswith('Bearer ')
                                and secrets.compare_digest(digest, a['hash'])), None)
            if not account:
                self.rejected += 1
                self.counters['unauthorizedRejected'] += 1
                return self.response(connection, HTTPStatus.UNAUTHORIZED, 'unauthorized\n')
            token = secrets.token_urlsafe(32)
            self.sessions[token] = (now+120, account)
            self.counters['sessionsIssued'] += 1
            response = self.response(connection, HTTPStatus.OK, '{"ok":true}\n')
            response.headers['Set-Cookie'] = 'session_peer='+token+'; Path=/v1/; Secure; HttpOnly; SameSite=Strict; Max-Age=120'
            return response
        if request.path != '/v1/connect':
            return self.response(connection, HTTPStatus.NOT_FOUND, 'not_found\n')
        cookie = SimpleCookie()
        try:
            cookie.load(request.headers.get('Cookie', ''))
            ticket = self.sessions.get(cookie['session_peer'].value)
        except (KeyError, ValueError):
            ticket = None
        if not ticket:
            self.rejected += 1
            self.counters['unauthorizedRejected'] += 1
            return self.response(connection, HTTPStatus.UNAUTHORIZED, 'unauthorized\n')
        if self.control and not self.control.active(ticket[1]):
            self.rejected += 1
            self.counters['unauthorizedRejected'] += 1
            return self.response(connection, HTTPStatus.UNAUTHORIZED, 'unauthorized\n')
        if self.control:
            current = [getattr(item, 'lab_account', {}) for item in self.connections]
            account = ticket[1]
            if (sum(item.get('userId') == account['userId'] for item in current) >= self.limits.user_connections
                    or sum(item.get('devicePrincipal') == account['devicePrincipal'] for item in current) >= self.limits.device_connections):
                self.rejected += 1
                self.counters['connectionCapacityRejected'] += 1
                return self.response(connection, HTTPStatus.SERVICE_UNAVAILABLE, 'capacity\n')
        if len(self.connections) >= self.limits.global_connections:
            self.rejected += 1
            self.counters['connectionCapacityRejected'] += 1
            return self.response(connection, HTTPStatus.SERVICE_UNAVAILABLE, 'capacity\n')
        self.connections.add(connection)
        async def release_slot():
            await connection.wait_closed()
            self.connections.discard(connection)
        asyncio.create_task(release_slot())
        self.sessions.pop(cookie['session_peer'].value, None)
        self.counters['connectionsAccepted'] += 1
        connection.lab_account = ticket[1]
        connection.lab_expiry = ticket[0]
        return None

    async def handler(self, ws):
        self.connections.add(ws)
        account = ws.lab_account
        key = account['room']
        other_role = 'client' if account['role'] == 'receiver' else 'receiver'
        slot = self.waiting.get(key)
        watcher = None
        attached = False
        close_reason = 'socket_closed'
        if self.control:
            async def watch_authorization():
                while True:
                    await asyncio.sleep(1)
                    if not self.control.active(account):
                        await ws.close(1008, 'authorization_revoked')
                        return
            watcher = asyncio.create_task(watch_authorization())
        if slot is None:
            slot = {'members': {}, 'joined': {}, 'ready': asyncio.Event(),
                    'opened': time.monotonic(), 'id': secrets.token_hex(8)}
            self.waiting[key] = slot
            self.counters['roomsOpened'] += 1
            self.diagnostic_event('room_open', roomId=slot['id'])
        try:
            if account['role'] in slot['members']:
                close_reason = 'role_busy'
                await ws.close(1013, 'role_busy')
                return
            slot['members'][account['role']] = ws
            slot['joined'][account['role']] = time.monotonic()
            if other_role in slot['members']:
                # Both forwarding handlers exist before attach notification.
                self.waiting.pop(key, None)
                slot['ready'].set()
                self.counters['roomsPaired'] += 1
                receiver_age = time.monotonic()-slot['joined']['receiver']
                self.diagnostic_event('room_paired', roomId=slot['id'],
                    receiverWsAgeMs=max(0, round(receiver_age*1000)))
            ready = asyncio.create_task(slot['ready'].wait())
            closed = asyncio.create_task(ws.wait_closed())
            try:
                await asyncio.wait({ready, closed}, timeout=self.receiver_wait if account['role'] == 'receiver' else self.client_wait, return_when=asyncio.FIRST_COMPLETED)
                if not slot['ready'].is_set() or closed.done():
                    if not closed.done() and not slot['ready'].is_set():
                        close_reason = 'receiver_idle_expiry' if account['role'] == 'receiver' else 'client_wait_expiry'
                        counter = 'receiverIdleExpired' if account['role'] == 'receiver' else 'clientWaitExpired'
                        self.counters[counter] += 1
                    return
            finally:
                ready.cancel()
                closed.cancel()
                await asyncio.gather(ready, closed, return_exceptions=True)
            other = slot['members'][other_role]
            await ws.send(json.dumps({'relayAttached': True}))
            self.counters['attachSentReceiver' if account['role'] == 'receiver' else 'attachSentClient'] += 1
            self.diagnostic_event('attach_sent', roomId=slot['id'], role=account['role'])
            attached = True
            close_reason = 'attached_closed'
            forwarded_bytes = 0
            async with asyncio.timeout(max(0, ws.lab_expiry-time.monotonic())):
                async for data in ws:
                    if not isinstance(data, bytes):
                        await ws.close(1008, 'binary_only')
                        break
                    self.bytes += len(data)
                    forwarded_bytes += len(data)
                    self.forwarded_frames += 1
                    if forwarded_bytes > self.limits.connection_byte_budget:
                        self.counters['byteBudgetClosed'] += 1
                        await ws.close(1013, 'byte_budget')
                        break
                    if self.capture is not None:
                        self.capture.append(data)
                    await asyncio.wait_for(other.send(data), 2)
        except Exception:
            # No request headers, tokens, body or endpoint fingerprints in logs.
            close_reason = 'forwarding_error'
        finally:
            if watcher:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            self.connections.discard(ws)
            if slot['members'].get(account['role']) is ws:
                slot['members'].pop(account['role'], None)
                if self.waiting.get(key) is slot:
                    self.waiting.pop(key, None)
                    self.counters['roomsClosedBeforeAttach'] += 1
                    self.diagnostic_event('room_close', roomId=slot['id'],
                        reason=close_reason, ageMs=max(0, round((time.monotonic()-slot['opened'])*1000)))
                other = slot['members'].get(other_role)
                if other:
                    await other.close(1001, 'peer_closed')
            if attached:
                code = getattr(ws, 'close_code', None)
                self.diagnostic_event('stream_close', roomId=slot['id'], role=account['role'],
                    reason=close_reason, closeCode=code if type(code) is int and 1000 <= code <= 4999 else None)
            await ws.close()

    async def start(self, host, port):
        return await serve(self.handler, host, port, process_request=self.process_request,
                           compression=None, max_size=MAX_FRAME, max_queue=4,
                           write_limit=32768, ping_interval=10, ping_timeout=10,
                           open_timeout=5, close_timeout=2)

    async def start_metrics(self, port):
        async def metrics_request(connection, request):
            host = request.headers.get('Host', '').split(':', 1)[0]
            if request.path != '/metrics' or host != '127.0.0.1':
                return self.response(connection, HTTPStatus.NOT_FOUND, 'not_found\n')
            response = self.response(connection, HTTPStatus.OK,
                                     json.dumps(self.metrics(), separators=(',', ':'))+'\n')
            response.headers['Content-Type'] = 'application/json'
            return response

        async def unreachable_handler(ws):
            await ws.close()

        return await serve(unreachable_handler, '127.0.0.1', port,
                           process_request=metrics_request, compression=None,
                           open_timeout=2, close_timeout=1)
