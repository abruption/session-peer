"""TLS 1.3 over TCP or opaque websocket frames, with bounded JSON messages."""
import asyncio
import hashlib
import json
import ssl
import struct
import urllib.request
import urllib.error
import urllib.parse

from websockets.asyncio.client import connect

MAX_FRAME = 256 * 1024
MAX_MESSAGE = 64 * 1024
TIMEOUT = 8


class Tcp:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    async def recv(self):
        return await self.reader.read(MAX_FRAME)

    async def send(self, data):
        self.writer.write(data)
        await asyncio.wait_for(self.writer.drain(), TIMEOUT)

    async def close(self):
        self.writer.close()
        try:
            await asyncio.wait_for(self.writer.wait_closed(), 2)
        except (OSError, asyncio.TimeoutError):
            pass


class Ws:
    def __init__(self, ws):
        self.ws = ws

    async def recv(self):
        data = await self.ws.recv()
        if not isinstance(data, bytes):
            raise ValueError('Nonbinary relay frame')
        return data

    async def send(self, data):
        for offset in range(0, len(data), MAX_FRAME):
            await asyncio.wait_for(self.ws.send(data[offset:offset+MAX_FRAME]), TIMEOUT)

    async def close(self):
        await self.ws.close()


class PinnedConnect(connect):
    def process_redirect(self, exc):
        # Relay placement/migration is outside this PoC. Never change origins.
        return exc


def direct_address(value):
    parsed = urllib.parse.urlsplit('tcp://' + value)
    if (not parsed.hostname or parsed.port is None or not 1 <= parsed.port <= 65535
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('invalid_direct_route')
    return parsed.hostname, parsed.port


def validate_relay_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme not in ('ws', 'wss') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != '/v1/connect'
            or (parsed.scheme == 'ws' and parsed.hostname not in ('127.0.0.1', '::1', 'localhost'))):
        raise ValueError('Relay must be WSS; plaintext WS is loopback-test-only')


def admission(url, credential):
    validate_relay_url(url)
    target = url.replace('wss://', 'https://', 1).replace('ws://', 'http://', 1)
    target = target.removesuffix('/v1/connect') + '/v1/session'
    req = urllib.request.Request(target, headers={'Authorization': 'Bearer '+credential, 'User-Agent': 'session-peer/0.9-relay'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=TIMEOUT) as response:
            return response.headers['Set-Cookie'].split(';', 1)[0]
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ValueError('Relay admission rejected') from None


async def relay_stream(url, credential, attach_timeout=12):
    cookie = await asyncio.to_thread(admission, url, credential)
    ws = await PinnedConnect(url, additional_headers={'Cookie': cookie}, compression=None,
                       user_agent_header='session-peer/0.9-relay',
                       max_size=MAX_FRAME, max_queue=4, write_limit=32768,
                       open_timeout=TIMEOUT, close_timeout=2)
    try:
        ready = json.loads(await asyncio.wait_for(ws.recv(), attach_timeout))
        if ready != {'relayAttached': True}:
            raise ValueError('Relay attach rejected')
        return Ws(ws)
    except BaseException:
        await ws.close()
        raise


class Secure:
    def __init__(self, raw, ctx, server=False, expected=None):
        self.raw, self.expected = raw, expected
        self.incoming, self.outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        self.ssl = ctx.wrap_bio(self.incoming, self.outgoing, server_side=server)
        self.tx = asyncio.Lock()
        self.peer = None
        self.buffer = bytearray()

    async def flush(self):
        async with self.tx:
            while self.outgoing.pending:
                await self.raw.send(self.outgoing.read(MAX_FRAME))

    async def feed(self):
        data = await self.raw.recv()
        if not data:
            raise EOFError('Connection ended')
        self.incoming.write(data)

    async def handshake(self):
        async with asyncio.timeout(TIMEOUT):
            while True:
                try:
                    self.ssl.do_handshake()
                    await self.flush()
                    break
                except ssl.SSLWantReadError:
                    await self.flush()
                    await self.feed()
            if self.ssl.selected_alpn_protocol() != 'session-peer-device-v1':
                raise ValueError('Protocol mismatch')
            cert = self.ssl.getpeercert(binary_form=True)
            self.peer = hashlib.sha256(cert).hexdigest() if cert else None
            if self.expected and self.peer != self.expected:
                raise ValueError('Peer pin mismatch')
        return self

    async def send(self, value):
        data = json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()
        if len(data) > MAX_MESSAGE:
            raise ValueError('Message too large')
        pending = memoryview(struct.pack('!I', len(data)) + data)
        while pending:
            size = self.ssl.write(pending)
            pending = pending[size:]
            await self.flush()

    async def read_bytes(self, size):
        while len(self.buffer) < size:
            try:
                data = self.ssl.read(min(MAX_MESSAGE+4-len(self.buffer), MAX_FRAME))
                if not data:
                    raise EOFError('TLS connection closed')
                self.buffer.extend(data)
            except ssl.SSLWantReadError:
                await self.flush()
                await self.feed()
        out = bytes(self.buffer[:size])
        del self.buffer[:size]
        return out

    async def recv(self):
        async with asyncio.timeout(45):
            size = struct.unpack('!I', await self.read_bytes(4))[0]
            if not 0 < size <= MAX_MESSAGE:
                raise ValueError('Invalid message size')
            data = json.loads(await self.read_bytes(size))
            if not isinstance(data, dict):
                raise ValueError('Expected request object')
            return data

    async def close(self):
        await self.raw.close()
