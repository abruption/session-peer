"""Explicit laboratory commands; never starts services from normal CLI usage."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import signal
import time

from .app import Receiver, pair, exchange
from .identity import private_write
from .relay import Relay
from .store import Store


async def run(args):
    # Headers, cookies and request bodies must never enter websocket debug logs.
    logging.getLogger('websockets').setLevel(logging.CRITICAL+1)
    if args.command == 'relay':
        accounts = json.loads(Path(args.accounts).read_text())
        relay = Relay(accounts)
        server = await relay.start(args.bind, args.port)
        print(json.dumps({'ready': True, 'port': server.sockets[0].getsockname()[1]}), flush=True)
        try:
            await lifetime(args.seconds)
        finally:
            server.close()
            await server.wait_closed()
            print(json.dumps({'bytes': relay.bytes, 'frames': relay.forwarded_frames,
                              'rejected': relay.rejected}), flush=True)
        return
    store = Store(args.state)
    try:
        if args.command == 'init':
            print(json.dumps({'device': store.device}))
        elif args.command == 'invite':
            routes = {}
            if args.direct:
                routes['direct'] = args.direct
            if args.relay:
                routes['relay'] = args.relay
            private_write(args.out, json.dumps(store.invite(routes)))
            print(json.dumps({'invitationSaved': True, 'device': store.device}))
        elif args.command == 'revoke':
            store.revoke(args.peer)
            print(json.dumps({'revoked': True}))
        elif args.command == 'serve':
            receiver = Receiver(store)
            server = await receiver.listen(args.bind, args.port)
            task = None
            if args.relay:
                task = asyncio.create_task(receiver.relay_listener(args.relay,
                          Path(args.admission_file).read_text().strip()))
            print(json.dumps({'ready': True, 'port': server.sockets[0].getsockname()[1],
                              'device': store.device}), flush=True)
            try:
                await lifetime(args.seconds)
            finally:
                if task:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                server.close()
                await server.wait_closed()
                await receiver.close()
        elif args.command == 'pair':
            print(json.dumps(await pair(store, json.loads(Path(args.invite).read_text()), args.route,
                  Path(args.admission_file).read_text().strip() if args.admission_file else None)))
        elif args.command == 'request':
            start = time.monotonic()
            result = await exchange(store, args.peer, args.op, args.message, args.id, args.route,
                  Path(args.admission_file).read_text().strip() if args.admission_file else None)
            print(json.dumps({**result, 'elapsedMs': round((time.monotonic()-start)*1000, 2)}))
            if not result.get('ok'):
                return 1
    finally:
        store.close()
    return 0


async def lifetime(seconds):
    event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, event.set)
    try:
        await asyncio.wait_for(event.wait(), seconds)
    except asyncio.TimeoutError:
        pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['init', 'invite', 'serve', 'pair', 'request', 'relay', 'revoke'])
    p.add_argument('--state')
    p.add_argument('--bind', default='127.0.0.1')
    p.add_argument('--port', type=int, default=0)
    p.add_argument('--seconds', type=int, default=1800)
    p.add_argument('--out')
    p.add_argument('--direct')
    p.add_argument('--relay')
    p.add_argument('--accounts')
    p.add_argument('--admission-file')
    p.add_argument('--invite')
    p.add_argument('--route', choices=['auto', 'direct', 'relay'], default='auto')
    p.add_argument('--peer')
    p.add_argument('--op', choices=['list', 'send', 'status'], default='list')
    p.add_argument('--message')
    p.add_argument('--id')
    args = p.parse_args()
    if not 1 <= args.seconds <= 1800:
        p.error('lifetime must be 1..1800 seconds')
    if args.command == 'pair' and args.route == 'auto':
        p.error('pair requires an explicit direct or relay route')
    try:
        return asyncio.run(run(args))
    except Exception as exc:
        # Error class only: never render credential-bearing HTTP exceptions.
        print(json.dumps({'ok': False, 'errorType': type(exc).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
