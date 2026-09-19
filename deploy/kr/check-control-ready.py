"""Staging helper: bounded loopback health + fresh public-state validation."""
import argparse
import http.client
import json
import math
import os
import re
import stat
import time
from urllib.parse import urlsplit


def validate_state(value, origin, now):
    if (not isinstance(value, dict) or type(value.get('schemaVersion')) is not int
            or value['schemaVersion'] != 1):
        raise ValueError('schema')
    if value.get('issuer') != origin or value.get('audience') != origin:
        raise ValueError('origin')
    issued, expires = value.get('issuedAt'), value.get('expiresAt')
    if any(type(n) not in (int, float) or not math.isfinite(n) for n in (issued, expires)):
        raise ValueError('time')
    if not issued <= now + 5 or not now < expires <= issued + 180:
        raise ValueError('freshness')
    # Python's persisted highwater requires this producer field.
    if (type(value.get('revision')) is not int
            or not 1 <= value['revision'] <= 9007199254740991):
        raise ValueError('revision')
    jwks = value.get('jwks')
    keys = jwks.get('keys') if isinstance(jwks, dict) else None
    if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
        raise ValueError('jwks')
    for key in keys:
        if (not isinstance(key, dict) or key.get('kty') != 'EC'
                or key.get('crv') != 'P-256' or key.get('alg') != 'ES256'
                or key.get('use') != 'sig' or 'd' in key
                or not isinstance(key.get('kid'), str) or not key['kid']
                or any(not isinstance(key.get(k), str)
                       or not re.fullmatch(r'[A-Za-z0-9_-]{43}', key[k]) for k in ('x', 'y'))):
            raise ValueError('jwk')
    devices = value.get('devices')
    if not isinstance(devices, dict):
        raise ValueError('devices')
    for principal, device in devices.items():
        if (not re.fullmatch(r'[a-f0-9]{64}', principal)
                or not isinstance(device, dict)
                or not isinstance(device.get('userId'), str) or not device['userId']
                or not isinstance(device.get('keyFingerprint'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', device['keyFingerprint'])
                or type(device.get('generation')) is not int or device['generation'] < 0
                or type(device.get('revoked')) is not bool):
            raise ValueError('device')


def check(path, origin, port):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
    try:
        connection.request('GET', '/healthz', headers={'Host': urlsplit(origin).netloc})
        response = connection.getresponse()
        body = response.read(4097)
        if response.status != 200 or len(body) > 4096 or json.loads(body).get('ok') is not True:
            raise ValueError('health')
    finally:
        connection.close()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as source:
        mode = os.fstat(source.fileno())
        if not stat.S_ISREG(mode.st_mode) or mode.st_mode & 0o022:
            raise ValueError('file')
        raw = source.read(1048577)
        if len(raw) > 1048576:
            raise ValueError('size')
    validate_state(json.loads(raw), origin, time.time())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--port', type=int, default=3770)
    args = parser.parse_args()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            check(args.state, args.origin, args.port)
            print('control_ready')
            return 0
        except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException):
            time.sleep(0.2)
    print('control_not_ready')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
