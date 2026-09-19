"""Authenticated online-only blind relay. Never imports endpoint identity keys."""
import asyncio
import hashlib
from http import HTTPStatus
from http.cookies import SimpleCookie
import json
import secrets
import time

from websockets.asyncio.server import serve

from .wire import MAX_FRAME


class Relay:
    def __init__(self, accounts, *, capture=None, control=None):
        # Provisioned admission hashes are independent of end-to-end TLS identities.
        self.accounts = accounts
        self.control = control
        self.sessions = {}
        self.waiting = {}
        self.connections = set()
        self.capture = capture  # in-memory adversarial test hook, never enabled by CLI
        self.bytes = 0
        self.forwarded_frames = 0
        self.rejected = 0
        self.requests = []

    def response(self, connection, status, text):
        response = connection.respond(status, text)
        response.headers['Cache-Control'] = 'no-store'
        return response

    async def process_request(self, connection, request):
        now = time.monotonic()
        self.requests = [stamp for stamp in self.requests if stamp > now-1]
        if len(self.requests) >= 20:
            self.rejected += 1
            return self.response(connection, HTTPStatus.TOO_MANY_REQUESTS, 'rate_limited\n')
        self.requests.append(now)
        self.sessions = {key: value for key, value in self.sessions.items() if value[0] > now}
        if request.path == '/v1/session':
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
            if not account or len(self.sessions) >= 100:
                self.rejected += 1
                return self.response(connection, HTTPStatus.UNAUTHORIZED, 'unauthorized\n')
            token = secrets.token_urlsafe(32)
            self.sessions[token] = (now+120, account)
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
            return self.response(connection, HTTPStatus.UNAUTHORIZED, 'unauthorized\n')
        if self.control and not self.control.active(ticket[1]):
            return self.response(connection, HTTPStatus.UNAUTHORIZED, 'unauthorized\n')
        if self.control:
            current = [getattr(item, 'lab_account', {}) for item in self.connections]
            account = ticket[1]
            if (sum(item.get('userId') == account['userId'] for item in current) >= 8
                    or sum(item.get('devicePrincipal') == account['devicePrincipal'] for item in current) >= 4):
                return self.response(connection, HTTPStatus.SERVICE_UNAVAILABLE, 'capacity\n')
        if len(self.connections) >= 10:
            return self.response(connection, HTTPStatus.SERVICE_UNAVAILABLE, 'capacity\n')
        self.connections.add(connection)
        async def release_slot():
            await connection.wait_closed()
            self.connections.discard(connection)
        asyncio.create_task(release_slot())
        self.sessions.pop(cookie['session_peer'].value, None)
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
        if self.control:
            async def watch_authorization():
                while True:
                    await asyncio.sleep(1)
                    if not self.control.active(account):
                        await ws.close(1008, 'authorization_revoked')
                        return
            watcher = asyncio.create_task(watch_authorization())
        if slot is None:
            slot = {'members': {}, 'ready': asyncio.Event()}
            self.waiting[key] = slot
        try:
            if account['role'] in slot['members']:
                await ws.close(1013, 'role_busy')
                return
            slot['members'][account['role']] = ws
            if other_role in slot['members']:
                # Both forwarding handlers exist before attach notification.
                self.waiting.pop(key, None)
                slot['ready'].set()
            ready = asyncio.create_task(slot['ready'].wait())
            closed = asyncio.create_task(ws.wait_closed())
            try:
                await asyncio.wait({ready, closed}, timeout=60 if account['role'] == 'receiver' else 10, return_when=asyncio.FIRST_COMPLETED)
                if not slot['ready'].is_set() or closed.done():
                    return
            finally:
                ready.cancel()
                closed.cancel()
                await asyncio.gather(ready, closed, return_exceptions=True)
            other = slot['members'][other_role]
            await ws.send(json.dumps({'relayAttached': True}))
            forwarded_bytes = 0
            async with asyncio.timeout(max(0, ws.lab_expiry-time.monotonic())):
                async for data in ws:
                    if not isinstance(data, bytes):
                        await ws.close(1008, 'binary_only')
                        break
                    self.bytes += len(data)
                    forwarded_bytes += len(data)
                    self.forwarded_frames += 1
                    if forwarded_bytes > 32*1024*1024:
                        await ws.close(1013, 'byte_budget')
                        break
                    if self.capture is not None:
                        self.capture.append(data)
                    await asyncio.wait_for(other.send(data), 2)
        except Exception:
            # No request headers, tokens, body or endpoint fingerprints in logs.
            pass
        finally:
            if watcher:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            self.connections.discard(ws)
            if slot['members'].get(account['role']) is ws:
                slot['members'].pop(account['role'], None)
                if self.waiting.get(key) is slot:
                    self.waiting.pop(key, None)
                other = slot['members'].get(other_role)
                if other:
                    await other.close(1001, 'peer_closed')
            await ws.close()

    async def start(self, host, port):
        return await serve(self.handler, host, port, process_request=self.process_request,
                           compression=None, max_size=MAX_FRAME, max_queue=4,
                           write_limit=32768, ping_interval=10, ping_timeout=10,
                           open_timeout=5, close_timeout=2)
