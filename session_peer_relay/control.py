"""Explicit first-party browser login and control-service device enrollment."""
import asyncio
import base64
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .identity import private_read, private_write
from .store import Rejected

CLIENT_ID = 'session-peer-cli'


def origin(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or (parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'))):
        raise Rejected('invalid_control_origin')
    return value.rstrip('/')


def call(server, path, body=None, token=None):
    server = origin(server)
    if not path.startswith('/api/') or '?' in path or '#' in path:
        raise Rejected('invalid_control_path')
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'Origin': server}
    if token:
        headers['Authorization'] = 'Bearer '+token
    req = urllib.request.Request(server+path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        response = urllib.request.build_opener(NoRedirect).open(req, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc
    except Exception:
        raise Rejected('control_unreachable') from None
    with response:
        raw = response.read(65537)
        status = response.code
    try:
        if len(raw) > 65536:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
    except Exception:
        raise Rejected('invalid_control_response') from None
    if status >= 400:
        error = value.get('error', value.get('code', 'control_request_refused'))
        # Only known protocol errors may reach logs/output; server strings may contain secrets.
        known = {'authorization_pending', 'slow_down', 'access_denied', 'expired_token', 'invalid_grant', 'invalid_client'}
        raise Rejected(error if error in known else 'control_request_refused')
    return value


async def login(store, server, no_browser=False):
    server = origin(server)
    result = await asyncio.to_thread(call, server, '/api/auth/device/code', {'client_id': CLIENT_ID})
    uri = result.get('verification_uri')
    if isinstance(uri, str) and uri.startswith('/'):
        uri = server+uri
    parsed = urllib.parse.urlsplit(uri or '')
    if parsed.scheme+'://'+parsed.netloc != server or parsed.path != '/device' or parsed.fragment:
        raise Rejected('invalid_verification_origin')
    if not isinstance(result.get('user_code'), str) or not 1 <= len(result['user_code']) <= 64:
        raise Rejected('invalid_device_authorization')
    interval, ttl = result.get('interval', 5), result.get('expires_in')
    if type(interval) not in (int, float) or not 1 <= interval <= 60 or type(ttl) not in (int, float) or not 1 <= ttl <= 1800:
        raise Rejected('invalid_device_authorization')
    if not isinstance(result.get('device_code'), str) or not 16 <= len(result['device_code']) <= 1024:
        raise Rejected('invalid_device_authorization')
    print(json.dumps({'schemaVersion': 1, 'status': 'authorization_pending',
                      'verificationUri': uri, 'userCode': result['user_code']}), flush=True)
    if not no_browser:
        webbrowser.open(uri)
    deadline = time.monotonic()+ttl
    while time.monotonic() < deadline:
        await asyncio.sleep(interval)
        if time.monotonic() >= deadline:
            break
        try:
            tokens = await asyncio.to_thread(call, server, '/api/auth/device/token',
                {'client_id': CLIENT_ID, 'device_code': result['device_code'],
                 'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'})
        except Rejected as exc:
            if str(exc) == 'authorization_pending':
                continue
            if str(exc) == 'slow_down':
                interval += 5
                continue
            raise
        token = tokens.get('access_token')
        expiry = tokens.get('expires_in')
        if (not isinstance(token, str) or not 16 <= len(token) <= 8192
                or tokens.get('token_type', '').lower() != 'bearer'
                or type(expiry) not in (int, float) or expiry <= 0):
            raise Rejected('invalid_login_response')
        private_write(store.root/'login.json', json.dumps({'server': server, 'token': token, 'expiresAt': time.time()+expiry}))
        return {'ok': True, 'loggedIn': True, 'server': server, 'device': store.device}
    raise Rejected('expired_token')


def session(store):
    value = json.loads(private_read(store.root/'login.json', 16384))
    if value.get('expiresAt', 0) <= time.time():
        raise Rejected('login_expired')
    origin(value['server'])
    return value


def sign(store, message, *, directory=None):
    key = serialization.load_pem_private_key(private_read((directory or store.identity_root)/'identity.key').encode(), None)
    return base64.urlsafe_b64encode(key.sign(message.encode(), ec.ECDSA(hashes.SHA256()))).rstrip(b'=').decode()


def prove(store, operation, payload, path, previous_directory=None):
    login_state = session(store)
    challenge = call(login_state['server'], '/api/relay/challenge', {'operation': operation, 'payload': payload}, login_state['token'])
    message = challenge.get('proofMessage')
    if not isinstance(message, str) or not message.startswith('session-peer-control-v1:') or len(message) > 8192:
        raise Rejected('invalid_control_challenge')
    request = {**payload, 'challengeId': challenge['challengeId'], 'proof': sign(store, message)}
    if previous_directory:
        request['previousKeyProof'] = sign(store, message, directory=previous_directory)
    return call(login_state['server'], path, request, login_state['token'])


def enroll(store, name, operation_id=None):
    operation_id = operation_id or str(uuid.uuid4())
    previous = None
    payload = {'principal': store.device, 'certificatePEM': store.cert,
               'keyGeneration': store.generation, 'name': name, 'operationId': operation_id}
    if store.generation:
        row = store.db.execute('SELECT value FROM metadata WHERE key="local_rotation"').fetchone()
        if not row:
            raise Rejected('previous_key_unavailable')
        previous = store.root/json.loads(row[0])['previousDirectory']
        payload['expectedGeneration'] = store.generation-1
    return prove(store, 'register', payload, '/api/relay/devices', previous)


class DeviceCredential:
    def __init__(self, store, receiver, role):
        self.store, self.receiver, self.role = store, receiver, role

    def for_receiver(self, receiver):
        return DeviceCredential(self.store, receiver, self.role)

    def headers(self, relay_url):
        login_state = session(self.store)
        parsed = urllib.parse.urlsplit(relay_url)
        relay_origin = ('https' if parsed.scheme == 'wss' else 'http')+'://'+parsed.netloc
        if relay_origin != login_state['server']:
            raise Rejected('control_relay_origin_mismatch')
        issued = prove(self.store, 'admission', {'role': self.role, 'devicePrincipal': self.store.device,
                         'receiverPrincipal': self.receiver}, '/api/relay/admission')
        ticket = issued.get('token')
        if not isinstance(ticket, str) or len(ticket) > 8192:
            raise Rejected('invalid_admission_ticket')
        return {'Authorization': 'Bearer '+ticket,
                'X-Session-Peer-Proof': sign(self.store, 'session-peer-admission-v1:'+ticket)}


def rotation_credential(store, saved):
    from types import SimpleNamespace
    proposal = saved['proposal']
    next_identity = SimpleNamespace(root=store.root, device=store.device,
        identity_root=store.root/saved['directory'], cert=proposal['certificate'],
        generation=proposal['generation'])
    payload = {'principal': store.device, 'certificatePEM': proposal['certificate'],
               'keyGeneration': proposal['generation'], 'name': 'session-peer-device',
               'operationId': proposal['id'], 'expectedGeneration': proposal['generation']-1}
    prove(next_identity, 'register', payload, '/api/relay/devices', store.root/saved['previousDirectory'])
    return DeviceCredential(next_identity, None, 'client')
