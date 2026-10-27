"""Bounded plain-TCP metadata probe; no TLS, session state or application input."""
import argparse
import asyncio
import json
import selectors
import sys
import time


def emit(**data):
    print(json.dumps(data, sort_keys=True), flush=True)


async def client(host, port):
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 3)
        emit(event="connected")
        writer.write(b"direct341-echo")
        await asyncio.wait_for(writer.drain(), 2)
        data = await asyncio.wait_for(reader.readexactly(14), 2)
        emit(event="result", echo=data == b"direct341-echo")
        return data == b"direct341-echo"
    except (OSError, TimeoutError, asyncio.IncompleteReadError) as error:
        emit(event="result", echo=False, error=type(error).__name__)
        return False
    finally:
        if writer is not None:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 1)
            except (OSError, TimeoutError):
                pass


async def main(args):
    if args.mode == "client":
        return await client(args.connect, args.port)
    writers = set()
    accepted = 0

    async def handle(reader, writer):
        nonlocal accepted
        accepted += 1
        writers.add(writer)
        emit(event="accepted", count=accepted)
        try:
            data = await asyncio.wait_for(reader.read(64), 3)
            emit(event="received", bytes=len(data))
            writer.write(data)
            await asyncio.wait_for(writer.drain(), 2)
        finally:
            writer.close()
            writers.discard(writer)

    server = await asyncio.start_server(handle, args.bind, args.port)
    emit(event="ready", port=server.sockets[0].getsockname()[1], selector=args.selector)
    try:
        if args.mode == "self":
            await client(args.connect or args.bind, server.sockets[0].getsockname()[1])
        else:
            await asyncio.sleep(args.seconds)
    finally:
        server.close()
        for writer in tuple(writers):
            writer.close()
        await asyncio.wait_for(server.wait_closed(), 4)
        emit(event="closed", accepted=accepted)


parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=("self", "server", "client"))
parser.add_argument("--bind", default="127.0.0.1")
parser.add_argument("--connect")
parser.add_argument("--port", type=int, default=0)
parser.add_argument("--seconds", type=int, choices=range(1, 21), default=20)
parser.add_argument("--selector", choices=("kqueue", "select"), default="kqueue")
args = parser.parse_args()
factory = selectors.KqueueSelector if args.selector == "kqueue" else selectors.SelectSelector
loop = asyncio.SelectorEventLoop(factory())
try:
    loop.run_until_complete(main(args))
finally:
    loop.close()
