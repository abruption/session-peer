"""Explicit fixture-only real-device measurements; never invokes native agents."""
import argparse
import asyncio
import json
from pathlib import Path
import statistics
import time
import uuid

from .app import exchange, open_channel, request
from .identity import private_write
from .store import Store


async def measure(args):
    store = Store(args.state)
    credential = Path(args.admission_file).read_text().strip()
    output = {'samples': {}, 'checks': {}}
    try:
        for route in ('direct', 'relay'):
            samples = []
            for index in range(args.count):
                start = time.monotonic()
                result = await exchange(store, args.peer, 'send', 'fixture-benchmark-'+str(index),
                                        route=route, credential=credential)
                samples.append({'ms': round((time.monotonic()-start)*1000, 2),
                                'ok': result.get('ok', False), 'route': result.get('route')})
                await asyncio.sleep(.1)
            times = sorted(item['ms'] for item in samples if item['ok'])
            output['samples'][route] = {'runs': samples, 'successes': len(times),
                'p50Ms': statistics.median(times) if times else None,
                'maxMs': max(times) if times else None}
            print(json.dumps({'route': route, 'successes': len(times), 'count': args.count}), flush=True)
        result = await exchange(store, args.peer, 'list', route='auto', credential=credential)
        output['checks']['autoDirect'] = result.get('ok') and result.get('route') == 'direct'
        record = store.peer(args.peer)
        routes = record['routes']
        store.db.execute('UPDATE peers SET routes=? WHERE id=?',
                         (json.dumps({**routes, 'direct': '127.0.0.1:1'}), args.peer))
        try:
            result = await exchange(store, args.peer, 'list', route='auto', credential=credential)
            output['checks']['autoFallbackRelay'] = result.get('ok') and result.get('route') == 'relay'
        finally:
            store.db.execute('UPDATE peers SET routes=? WHERE id=?', (json.dumps(routes), args.peer))
        ident = str(uuid.uuid4())
        channel = await open_channel(store, record['certificate'], routes, 'relay', credential)
        await channel.send(request(store, args.peer, 'send', 'lost-response-fixture', ident))
        await asyncio.sleep(.7)
        await channel.close()  # Deliberately discard the response; do not issue a new ID.
        status = await exchange(store, args.peer, 'status', ident, route='relay', credential=credential)
        duplicate = await exchange(store, args.peer, 'send', 'lost-response-fixture', ident,
                                   route='direct', credential=credential)
        output['checks']['lostResponseReconciled'] = status.get('submitted') is True
        output['checks']['crossRouteDuplicateSuppressed'] = duplicate.get('duplicate') is True
        output['lostResponseMessageId'] = ident
        output['ok'] = (all(output['checks'].values()) and
                         all(item['successes'] == args.count for item in output['samples'].values()))
        private_write(args.out, json.dumps(output, indent=2))
        print(json.dumps({'checks': output['checks'], 'ok': output['ok']}), flush=True)
        return 0 if output['ok'] else 1
    finally:
        store.close()


async def steady_measure(store, peer, route, credential, count=10):
    record = store.peer(peer)
    channel = await open_channel(store, record['certificate'], record['routes'], route, credential)
    values = []
    try:
        for _ in range(count):
            start = time.monotonic()
            await channel.send(request(store, peer, 'list'))
            result = await channel.recv()
            if not result.get('ok'):
                raise RuntimeError('Steady request failed')
            values.append(round((time.monotonic()-start)*1000, 2))
        return {'count': count, 'p50Ms': statistics.median(values), 'maxMs': max(values)}
    finally:
        await channel.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--state', required=True)
    p.add_argument('--peer', required=True)
    p.add_argument('--admission-file', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--count', type=int, default=10)
    args = p.parse_args()
    if not 1 <= args.count <= 20:
        p.error('count must be 1..20')
    raise SystemExit(asyncio.run(measure(args)))
