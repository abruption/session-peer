#!/usr/bin/env python3
"""Opt-in native agentapi parser probe against a bounded loopback stub.

Never uses a real language server, valid recipient, credentials, or model.
Not discovered or executed by the default unittest suite.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading


RECIPIENT = 'syntactically-invalid-session-peer-probe'
BODIES = ('hello', '-x', '--help', '- item', '--', '- first\n-- second\n한국어')


def read_exact(conn, size):
    data = b''
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise EOFError('native client closed before its request')
        data += chunk
    return data


def frame(kind, flags, stream, data=b''):
    return len(data).to_bytes(3, 'big') + bytes([kind, flags]) + stream.to_bytes(4, 'big') + data


def varint(data, index):
    value, shift = 0, 0
    while shift < 70:
        ch = data[index]
        index += 1
        value |= (ch & 127) << shift
        if not ch & 128:
            return value, index
        shift += 7
    raise ValueError('oversized protobuf varint')


def protobuf_fields(data):
    result, index = [], 0
    while index < len(data):
        tag, index = varint(data, index)
        field, kind = tag >> 3, tag & 7
        if kind == 2:
            length, index = varint(data, index)
            if length > len(data) - index:
                raise ValueError('truncated protobuf string')
            value = data[index:index + length].decode('utf-8')
            index += length
        elif kind == 0:
            value, index = varint(data, index)
        else:
            raise ValueError('unexpected protobuf field type')
        result.append({'field': field, 'wire_type': kind, 'value': value})
    return result


def probe(executable, root, text, delimiter=True):
    capture = {}
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(3)
        port = listener.getsockname()[1]

        def serve():
            try:
                with listener.accept()[0] as conn:
                    conn.settimeout(3)
                    if read_exact(conn, 24) != b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n':
                        raise ValueError('unexpected HTTP/2 preface')
                    conn.sendall(frame(4, 0, 0))
                    data = b''
                    for _ in range(32):
                        header = read_exact(conn, 9)
                        size = int.from_bytes(header[:3], 'big')
                        if size > 65536:
                            raise ValueError('oversized HTTP/2 frame')
                        kind, flags = header[3:5]
                        payload = read_exact(conn, size)
                        if kind == 4 and not flags & 1:
                            conn.sendall(frame(4, 1, 0))
                        elif kind == 6 and not flags & 1:
                            conn.sendall(frame(6, 1, 0, payload))
                        elif kind == 0:
                            data += payload
                            if len(data) > 65536:
                                raise ValueError('oversized gRPC request')
                            if len(data) >= 5 and len(data) >= 5 + int.from_bytes(data[1:5], 'big'):
                                if data[0] != 0:
                                    raise ValueError('unexpected compressed request')
                                capture['protobuf_fields'] = protobuf_fields(data[5:5 + int.from_bytes(data[1:5], 'big')])
                                # No successful RPC response or delivery is possible.
                                return
                    raise ValueError('HTTP/2 frame limit reached')
            except Exception as exc:
                capture['fixture_error'] = str(exc)

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        env = {'HOME': str(root), 'PATH': os.defpath,
               'ANTIGRAVITY_LS_ADDRESS': '127.0.0.1:' + str(port)}
        args = ['agentapi', 'send-message', '--title=session-peer',
                *(['--'] if delimiter else []), RECIPIENT, text]
        try:
            done = subprocess.run([str(executable), *args], env=env, cwd=root,
                                  capture_output=True, text=True, timeout=5)
        finally:
            worker.join(timeout=4)
        evidence = {'body': text, 'delimiter': delimiter, 'exit': done.returncode,
                    'capture': capture, 'stdout': done.stdout, 'stderr': done.stderr}
        print(json.dumps(evidence, ensure_ascii=False))
        if worker.is_alive() or 'fixture_error' in capture:
            raise AssertionError('bounded fixture failed')
        fields = {entry['field']: entry['value'] for entry in capture.get('protobuf_fields', [])}
        if fields != {1: text, 2: RECIPIENT, 5: 'session-peer'}:
            raise AssertionError('native parser changed recipient, body, or title')
        if done.returncode == 0 or 'Unavailable' not in done.stdout:
            raise AssertionError('expected native RPC failure was not reported')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agy-bin', type=Path, required=True, help='explicit installed agy executable')
    parser.add_argument('--scratch-root', type=Path, required=True, help='approved existing temporary root')
    args = parser.parse_args()
    executable = args.agy_bin.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='codex-issue-237-agy-', dir=args.scratch_root) as scratch:
        root = Path(scratch)
        root.chmod(0o700)
        env = {'HOME': str(root), 'PATH': os.defpath}
        version = subprocess.run([str(executable), '--version'], env=env, cwd=root,
                                 capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        print(json.dumps({'probe': 'native agentapi + bounded loopback HTTP/2 stub',
                          'version': version, 'recipient': RECIPIENT,
                          'auth': 'empty HOME, minimal environment, no tokens',
                          'delivery': 'stub closes connection without a response'}))
        for text in BODIES:
            probe(executable, root, text)
        probe(executable, root, 'hello', delimiter=False)


if __name__ == '__main__':
    main()
