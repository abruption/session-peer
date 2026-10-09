"""Owned protocol inbox only: record metadata and a body-free write counter."""
import json
import os
from pathlib import Path
import socket
import sys


directory, endpoint, counter, name = map(Path, sys.argv[1:])
pid = os.getpid()
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
    server.bind(str(endpoint))
    server.listen(4)
    counter.write_text("0", encoding="ascii")
    (directory / (str(pid) + ".json")).write_text(json.dumps({
        "pid": pid, "name": str(name), "status": "idle", "cwd": str(directory),
        "messagingSocketPath": str(endpoint), "startedAt": 1000}), encoding="utf-8")
    print(json.dumps({"pid": pid}), flush=True)
    writes = 0
    while True:
        connection, _ = server.accept()
        with connection:
            connection.settimeout(2)
            raw = bytearray()
            while len(raw) < 65536:
                chunk = connection.recv(min(4096, 65536 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            if raw:
                writes += 1
                counter.write_text(str(writes), encoding="ascii")
            connection.sendall(b"1")
