"""Paired receiver/client with explicitly authorized native agent endpoints."""
import argparse
import asyncio
import contextlib
import hashlib
import json
from pathlib import Path
import time
import uuid

import session_peer as core
from .identity import context, fingerprint
from .store import Store, Rejected
from .wire import Secure, Tcp, relay_stream, direct_address
from .native import Policy, Native


class Receiver:
    def __init__(self, store, policy):
        self.store = store
        self.policy = Policy(policy)
        self.native = Native()
        self.tasks = set()
        self.connections = set()
        self.rejected = 0

    async def watch_peer(self, channel):
        while True:
            await asyncio.sleep(.2)
            row = self.store.peer(channel.peer)
            if not row or row['status'] == 'revoked' or (
                    row['status'] == 'pending' and row['expires'] < time.time()):
                await channel.close()
                return

    async def dispatch(self, peer, value):
        if value.get('op') == 'pair.prepare' and peer is None:
            return self.store.prepare(value)
        if value.get('op') == 'pair.commit' and peer:
            return self.store.commit(peer)
        self.store.authorize(peer, value.get('op'))
        if (set(value) != {'v', 'sender', 'receiver', 'id', 'expires', 'op', 'body'}
                or type(value['v']) is not int or value['v'] != 1 or value['sender'] != peer or value['receiver'] != self.store.device
                or not isinstance(value['expires'], (int, float))
                or not time.time() < value['expires'] <= time.time()+65
                or not isinstance(value['id'], str)):
            raise Rejected('invalid_request')
        try:
            if str(uuid.UUID(value['id'])) != value['id']:
                raise ValueError('noncanonical_uuid')
        except ValueError:
            raise Rejected('invalid_request_id')
        if peer not in self.policy.peers:
            raise Rejected('peer_policy_denied')
        op = value['op']
        if op == 'probe':
            return {'ok': True, 'device': self.store.device, 'receiverReady': True}
        if op == 'status':
            return self.store.status(peer, value['body'])
        if op == 'list':
            aliases = self.policy.authorize(peer, 'list')
            if value['body'] not in (None, {}):
                raise Rejected('invalid_list_request')
            parts = await asyncio.gather(*(self.native.invoke(self.policy.targets[name], 'list') for name in aliases))
            sessions, errors = [], []
            for name, part in zip(aliases, parts):
                if not part.get('ok'):
                    errors.append({'target': name, 'reason': part.get('reason', 'discovery_failed')})
                sessions.extend({**row, 'target': name, 'nativeTarget': self.policy.targets[name]['target']}
                                for row in part.get('sessions', []))
            return {'ok': not errors, 'sessions': sessions, 'errors': errors}
        body = value['body']
        if not isinstance(body, dict) or set(body) != {'target', 'message'}:
            raise Rejected('invalid_body')
        alias, text = body['target'], body['message']
        if not isinstance(alias, str):
            raise Rejected('invalid_target')
        self.policy.authorize(peer, 'send', alias)
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 32768 or '\0' in text:
            raise Rejected('invalid_message')
        binding = self.policy.targets[alias]
        if op == 'resolve':
            return await self.native.invoke(binding, 'resolve', text)
        canonical = json.dumps({'binding': binding, 'message': text}, sort_keys=True, separators=(',', ':'))
        existing = self.store.begin(peer, value['id'], canonical)
        if existing is not None:
            return existing
        result = await self.native.invoke(binding, 'send', text)
        return self.store.finish(peer, value['id'], result)

    async def handle(self, raw):
        if len(self.connections) >= 8:
            await raw.close()
            return
        self.connections.add(raw)
        channel = None
        watch = None
        try:
            channel = Secure(raw, context(self.store.root, True, self.store.trusted()), server=True)
            await channel.handshake()
            if channel.peer:
                watch = asyncio.create_task(self.watch_peer(channel))
            # Bound unauthenticated pairing attempts per TLS connection.
            budget = 100 if channel.peer else 1
            for _ in range(budget):
                request = await channel.recv()
                try:
                    result = await self.dispatch(channel.peer, request)
                except Rejected as exc:
                    self.rejected += 1
                    result = {'ok': False, 'status': 'refused', 'reason': str(exc),
                              'consumptionConfirmed': False, 'retryAllowed': False}
                except Exception:
                    self.rejected += 1
                    result = {'ok': False, 'status': 'unknown', 'reason': 'unknown',
                              'retryAllowed': False, 'consumptionConfirmed': False}
                if len(json.dumps(result, ensure_ascii=False).encode()) > 60*1024:
                    result = {'ok': False, 'reason': 'result_too_large', 'retryAllowed': False,
                              'consumptionConfirmed': False}
                await channel.send(result)
        except Exception:
            self.rejected += 1
        finally:
            if watch:
                watch.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watch
            await (channel.close() if channel is not None else raw.close())
            self.connections.discard(raw)

    def spawn(self, raw):
        task = asyncio.create_task(self.handle(raw))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def listen(self, host, port):
        return await asyncio.start_server(lambda r, w: self.spawn(Tcp(r, w)), host, port, limit=65536)

    async def relay_listener(self, url, credential):
        delay = .5
        while True:
            try:
                raw = await relay_stream(url, credential, attach_timeout=65)
                delay = .5
                self.spawn(raw)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(delay)
                delay = min(5, delay*2)

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def request(store, peer, op, body=None, ident=None):
    return {'v': 1, 'sender': store.device, 'receiver': peer, 'id': ident or str(uuid.uuid4()),
            'expires': time.time()+60, 'op': op, 'body': body}


async def open_channel(store, certificate, routes, route, credential=None, bootstrap=False):
    if route == 'direct':
        host, port = direct_address(routes['direct'])
        raw = Tcp(*await asyncio.wait_for(asyncio.open_connection(host, port), 5))
    else:
        raw = await relay_stream(routes['relay'], credential)
    channel = Secure(raw, context(store.root, False, [certificate], present=not bootstrap),
                     expected=fingerprint(certificate))
    try:
        await channel.handshake()
        return channel
    except BaseException:
        await raw.close()
        raise


async def pair(store, invite, route, credential=None):
    if (invite.get('v') != 1 or invite['expires'] < time.time()
            or fingerprint(invite['certificate']) != invite['device']):
        raise Rejected('invalid_invitation')
    previous = store.peer(invite['device'])
    if previous and previous['status'] == 'paired':
        raise Rejected('invitation_consumed')
    if previous and previous['status'] == 'pending':
        # Resume by proving the same key, not by consuming the invitation again.
        try:
            return await finish_pair(store, invite, route, credential)
        except Exception:
            pass  # prepare is itself idempotent for this invitation and public key
    store.stage(invite)
    channel = await open_channel(store, invite['certificate'], invite['routes'], route, credential, True)
    try:
        await channel.send({'op': 'pair.prepare', 'invitation': invite['id'],
                            'secret': invite['secret'], 'certificate': store.cert})
        prepared = await channel.recv()
        if not prepared.get('ok'):
            raise Rejected(prepared.get('reason', 'pairing_failed'))
    finally:
        await channel.close()
    return await finish_pair(store, invite, route, credential)


async def finish_pair(store, invite, route, credential):
    # No send/list access before possession of the newly proposed key is proven.
    channel = await open_channel(store, invite['certificate'], invite['routes'], route, credential)
    try:
        await channel.send({'op': 'pair.commit'})
        committed = await channel.recv()
        if not committed.get('ok'):
            raise Rejected('pairing_not_committed')
        store.remember(invite)
        return committed
    finally:
        await channel.close()


async def exchange(store, peer, op, body=None, ident=None, route='auto', credential=None):
    record = store.peer(peer)
    if not record or record['status'] != 'paired':
        raise Rejected('unpaired_device')
    routes = record['routes']

    async def ready(kind):
        channel = await open_channel(store, record['certificate'], routes, kind, credential)
        try:
            await channel.send(request(store, peer, 'probe'))
            response = await channel.recv()
            if not response.get('ok') or response.get('device') != peer:
                raise Rejected('peer_not_ready')
            return kind, channel
        except BaseException:
            await channel.close()
            raise

    kinds = [kind for kind in ('direct', 'relay') if kind in routes] if route == 'auto' else [route]
    tasks = {asyncio.create_task(ready(kind)): kind for kind in kinds}
    winner = None
    try:
        pending = set(tasks)
        while pending and winner is None:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in sorted(done, key=lambda t: tasks[t] != 'direct'):
                if not task.cancelled() and task.exception() is None:
                    if winner is None:
                        winner = task.result()
                    else:
                        await task.result()[1].close()
        if winner is None:
            raise Rejected('no_authenticated_route')
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for task in tasks:
            if (not task.cancelled() and task.exception() is None
                    and (winner is None or task.result()[1] is not winner[1])):
                await task.result()[1].close()
    kind, channel = winner
    value = request(store, peer, op, body, ident)
    try:
        # Exactly one application submission, after path selection. No failover resend.
        await channel.send(value)
        result = await channel.recv()
        return {**result, 'route': kind, 'receiverAccepted': result.get('ok', False),
                'relayAttached': kind == 'relay', 'requestId': value['id']}
    except Exception:
        return {'ok': False, 'status': 'unknown', 'requestId': value['id'],
                'route': kind, 'retryAllowed': False, 'consumptionConfirmed': False}
    finally:
        await channel.close()
