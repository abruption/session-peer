"""Paired receiver/client with explicitly authorized native agent endpoints."""
import argparse
import asyncio
import contextlib
import hashlib
import json
import logging
from pathlib import Path
import time
import uuid

import session_peer as core
from .identity import context, fingerprint
from .store import Store, Rejected
from .wire import Secure, Tcp, Ws, relay_stream, direct_address
from .native import Policy, Native
from .rotation import remote_prepare, remote_commit, remote_status
from .transport_errors import failure, NoAuthenticatedRoute, TransportFailure


class Receiver:
    def __init__(self, store, policy, *, diagnostic_events=False):
        self.store = store
        self.policy = Policy(policy)
        self.native = Native()
        self.tasks = set()
        self.connections = set()
        self.rejected = 0
        self.relay_failure_last_logged = float('-inf')
        self.diagnostic_events = diagnostic_events

    def lifecycle_event(self, event, **values):
        if self.diagnostic_events:
            logging.getLogger(__name__).warning('relay_lifecycle %s',
                json.dumps({'event': event, 'eventTimeUtcMs': int(time.time()*1000),
                            **values}, sort_keys=True))

    async def watch_peer(self, channel):
        while True:
            await asyncio.sleep(.2)
            try:
                row = self.store.peer(self.store.principal(channel.peer))
            except Rejected:
                await channel.close()
                return
            if not row or row['status'] == 'revoked' or (
                    row['status'] == 'pending' and row['expires'] < time.time()):
                await channel.close()
                return

    async def dispatch(self, peer, value):
        if value.get('op') == 'pair.prepare' and peer is None:
            return self.store.prepare(value)
        if value.get('op') == 'pair.commit' and peer:
            return self.store.commit(peer)
        key = peer
        peer = self.store.principal(key)
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
        restricted = self.store.key_status(key) != 'active' or self.store.db.execute(
            'SELECT 1 FROM rotations WHERE peer=? AND status="prepared"', (peer,)).fetchone()
        if restricted and op not in ('probe', 'status', 'rotation.prepare', 'rotation.commit', 'rotation.status'):
            raise Rejected('key_rotation_restricted')
        if op == 'probe':
            return {'ok': True, 'device': self.store.device, 'receiverReady': True,
                    'features': ['identity-rotation-v1']}
        if op == 'status':
            return self.store.status(peer, value['body'])
        if op == 'rotation.prepare':
            if self.store.recovery_required():
                raise Rejected('recovery_required')
            return remote_prepare(self.store, peer, key, value['body'])
        if op == 'rotation.commit':
            if self.store.recovery_required():
                raise Rejected('recovery_required')
            return remote_commit(self.store, peer, key, value['body'])
        if op == 'rotation.status':
            return remote_status(self.store, peer, value['body'])
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
            result = await self.native.invoke(binding, 'resolve', text)
            if result.get('reason') == 'codex_executable_not_found':
                self.lifecycle_event('native_preflight_refused', operation='resolve',
                                     reason='codex_executable_not_found')
            return result
        canonical = json.dumps({'binding': binding, 'message': text}, sort_keys=True, separators=(',', ':'))
        existing = self.store.begin(peer, value['id'], canonical)
        if existing is not None:
            return existing
        result = await self.native.invoke(binding, 'send', text)
        if result.get('reason') == 'codex_executable_not_found':
            self.lifecycle_event('native_preflight_refused', operation='send',
                                 reason='codex_executable_not_found')
        return self.store.finish(peer, value['id'], result)

    async def handle(self, raw):
        if len(self.connections) >= 8:
            await raw.close()
            return
        self.connections.add(raw)
        channel = None
        watch = None
        try:
            channel = Secure(raw, context(self.store.identity_root, True, self.store.trusted()), server=True)
            started = time.monotonic()
            try:
                await channel.handshake()
            except Exception as exc:
                if isinstance(raw, Ws):
                    self.lifecycle_event('peer_tls', outcome='failed',
                        elapsedMs=round((time.monotonic()-started)*1000),
                        reason=failure('peer_tls', exc).diagnostic()['reason'],
                        attemptId=getattr(raw, 'attempt_id', None))
                raise
            if isinstance(raw, Ws):
                self.lifecycle_event('peer_tls', outcome='ok',
                    elapsedMs=round((time.monotonic()-started)*1000),
                    attemptId=getattr(raw, 'attempt_id', None))
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
        gap_started = None
        websocket_opened = None
        def observed(event, *, elapsed_ms, attempt_id=None):
            nonlocal gap_started, websocket_opened
            now = time.monotonic()
            if event == 'websocket_open':
                websocket_opened = now
                if gap_started is not None:
                    self.lifecycle_event('reconnect_gap', elapsedMs=round((now-gap_started)*1000))
                    gap_started = None
            self.lifecycle_event(event, elapsedMs=elapsed_ms, attemptId=attempt_id)
        while True:
            try:
                raw = await relay_stream(url, credential, attach_timeout=65, on_event=observed)
                delay = .5
                self.spawn(raw)
                websocket_opened = None  # Attached socket is consumed; the next is not open yet.
                gap_started = time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                detail = failure('relay_connect', exc)
                now = time.monotonic()
                idle = (detail.stage == 'relay_attach' and detail.close_code == 1000
                        and detail.close_source == 'received'
                        and websocket_opened is not None and 50 <= now-websocket_opened <= 70)
                # A normal Relay close of a room that stayed open is an expected
                # idle expiry, not a failure: reconnect promptly instead of
                # escalating the backoff. Rooms closed within a second keep the
                # exponential backoff so a misbehaving Relay cannot cause a hot loop.
                expired = (detail.stage == 'relay_attach' and detail.close_code == 1000
                           and detail.close_source == 'received'
                           and websocket_opened is not None and now-websocket_opened >= 1)
                self.lifecycle_event('websocket_closed' if websocket_opened is not None else 'setup_failed',
                    reason='idle_expiry_like' if idle else detail.diagnostic()['reason'],
                    stage=detail.stage, closeCode=detail.close_code, closeSource=detail.close_source,
                    websocketAgeMs=round((now-websocket_opened)*1000) if websocket_opened is not None else None)
                websocket_opened = None
                gap_started = now
                # Expected idle expiry is a lifecycle event, not a failure warning.
                if not idle and now - self.relay_failure_last_logged >= 60:
                    self.relay_failure_last_logged = now
                    logging.getLogger(__name__).warning('relay_connection_failed %s',
                        json.dumps(detail.diagnostic(), sort_keys=True))
                if expired:
                    delay = .5
                await asyncio.sleep(delay)
                delay = .5 if expired else min(5, delay*2)

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def request(store, peer, op, body=None, ident=None):
    return {'v': 1, 'sender': store.device, 'receiver': peer, 'id': ident or str(uuid.uuid4()),
            'expires': time.time()+60, 'op': op, 'body': body}


async def open_channel(store, certificate, routes, route, credential=None, bootstrap=False,
                       attempt_id=None):
    if route == 'direct':
        host, port = direct_address(routes['direct'])
        raw = Tcp(*await asyncio.wait_for(asyncio.open_connection(host, port), 5))
    else:
        raw = await relay_stream(routes['relay'], credential, attempt_id=attempt_id)
    channel = Secure(raw, context(store.identity_root, False, [certificate], present=not bootstrap),
                     expected=fingerprint(certificate))
    try:
        await channel.handshake()
        return channel
    except TimeoutError:
        with contextlib.suppress(Exception):
            await raw.close()
        raise TransportFailure('peer_tls', 'timeout', transient=True) from None
    except BaseException:
        await raw.close()
        raise


async def pair(store, invite, route, credential=None):
    if store.recovery_required():
        raise Rejected('recovery_required')
    if (type(invite.get('v')) is not int or invite['v'] not in (1, 2) or invite['expires'] < time.time()
            or fingerprint(invite['certificate']) != invite.get('keyFingerprint', invite['device'])):
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
        preparation = {'op': 'pair.prepare', 'invitation': invite['id'],
                       'secret': invite['secret'], 'certificate': store.cert}
        if store.generation:
            preparation.update(principal=store.device, generation=store.generation)
        await channel.send(preparation)
        prepared = await channel.recv()
        if not prepared.get('ok'):
            raise Rejected(prepared.get('reason', 'pairing_failed'))
        if store.generation and 'identity-rotation-v1' not in prepared.get('features', []):
            raise Rejected('rotation_unsupported')
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
    if store.recovery_required() and op not in ('probe', 'status', 'rotation.status'):
        raise Rejected('recovery_required')
    record = store.peer(peer)
    if not record or record['status'] != 'paired':
        raise Rejected('unpaired_device')
    routes = record['routes']

    async def ready_once(kind, attempt_id):
        channel = await open_channel(store, record['certificate'], routes, kind, credential,
                                     attempt_id=attempt_id)
        try:
            await channel.send(request(store, peer, 'probe'))
            response = await channel.recv()
            if not response.get('ok') or response.get('device') != peer:
                raise Rejected('peer_not_ready')
            if op.startswith('rotation.') and 'identity-rotation-v1' not in response.get('features', []):
                raise Rejected('rotation_unsupported')
            return kind, channel, attempt_id
        except TimeoutError:
            with contextlib.suppress(Exception):
                await channel.close()
            raise TransportFailure('peer_probe', 'timeout', transient=True) from None
        except BaseException:
            await channel.close()
            raise

    diagnostics = {}
    history = {}
    setup_attempts = {}

    async def ready(kind):
        # Retry only a connection timeout BEFORE application submission. A fresh
        # admission proof/ticket and channel are acquired; never replay a send.
        for attempt in (1, 2):
            started = time.monotonic()
            started_utc_ms = int(time.time()*1000)
            attempt_id = str(uuid.uuid4()) if kind == 'relay' else None
            try:
                result = await ready_once(kind, attempt_id)
                setup_attempts[kind] = attempt
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                detail = failure('peer_connect', exc)
                diagnostics[kind] = {'route': kind, **detail.diagnostic(), 'attempts': attempt,
                                     'attemptId': attempt_id}
                history.setdefault(kind, []).append({'attempt': attempt, **detail.diagnostic(),
                    'elapsedMs': max(0, round((time.monotonic()-started)*1000)),
                    'attemptId': attempt_id, 'startedAtUtcMs': started_utc_ms})
                # A timeout after attach may have consumed the receiver's only
                # waiting room. Retrying then hides the first failure and cannot
                # safely be treated as a fresh-room recovery.
                if (kind != 'relay' or not detail.transient or attempt == 2
                        or detail.stage not in {'control_request', 'control_response',
                            'control_admission', 'relay_admission'}):
                    raise
                await asyncio.sleep(.5)

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
            raise NoAuthenticatedRoute([{**diagnostics[kind], 'attemptHistory': history[kind]}
                                        for kind in kinds if kind in diagnostics])
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for task in tasks:
            if (not task.cancelled() and task.exception() is None
                    and (winner is None or task.result()[1] is not winner[1])):
                await task.result()[1].close()
    kind, channel, selected_attempt_id = winner
    setup = ({'setupAttempts': setup_attempts[kind], 'setupDegraded': True,
              'setupFailureHistory': history[kind]} if setup_attempts[kind] > 1 else {})
    value = request(store, peer, op, body, ident)
    try:
        # Exactly one application submission, after path selection. No failover resend.
        await channel.send(value)
        result = await channel.recv()
        return {**result, 'route': kind, 'receiverAccepted': result.get('ok', False),
                'relayAttached': kind == 'relay', 'requestId': value['id'],
                'attemptId': selected_attempt_id, **setup}
    except Exception:
        return {'ok': False, 'status': 'unknown', 'requestId': value['id'],
                'route': kind, 'attemptId': selected_attempt_id,
                'retryAllowed': False, 'consumptionConfirmed': False, **setup}
    finally:
        await channel.close()
