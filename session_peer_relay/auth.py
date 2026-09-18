"""Optional control-service admission: short-lived ES256 tickets and device proof."""
import base64
import hashlib
import fcntl
import json
import math
import os
from pathlib import Path
import re
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from .identity import private_path, private_read, private_write


class AdmissionDenied(ValueError):
    pass


def initialize_replay(path):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_path(path.parent, True)
    # Explicit operator bootstrap only. A running service never recreates lost state.
    not_before = math.ceil(time.time())+65
    value = {'schemaVersion': 1, 'spent': {}, 'revision': 0, 'digest': None, 'notBefore': not_before}
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as target:
        json.dump(value, target)
        target.flush(); os.fsync(target.fileno())
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return {'ok': True, 'initialized': True, 'admissionNotBefore': not_before}


def decode(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise AdmissionDenied('invalid_base64')
    return base64.urlsafe_b64decode(value + '='*((-len(value)) % 4))


def public_key(jwk):
    if not isinstance(jwk, dict) or jwk.get('kty') != 'EC' or jwk.get('crv') != 'P-256' or 'd' in jwk:
        raise AdmissionDenied('invalid_public_key')
    x, y = decode(jwk.get('x')), decode(jwk.get('y'))
    if len(x) != 32 or len(y) != 32:
        raise AdmissionDenied('invalid_public_key')
    return ec.EllipticCurvePublicNumbers(int.from_bytes(x, 'big'), int.from_bytes(y, 'big'), ec.SECP256R1()).public_key()


def room_id(user, receiver):
    return hashlib.sha256((user+'\0'+receiver).encode()).hexdigest()


class ControlAdmission:
    def __init__(self, state_file, issuer, replay_file=None):
        self.state_file = Path(state_file)
        self.issuer = issuer.rstrip('/')
        if not self.issuer.startswith('https://'):
            raise ValueError('auth_issuer_requires_https')
        self.replay_file = Path(replay_file) if replay_file else None
        self.replay_lock = None
        if self.replay_file:
            if not self.replay_file.exists():
                raise ValueError('admission_replay_state_missing')
            self.replay_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            private_path(self.replay_file.parent, True)
            lock = self.replay_file.with_suffix('.lock')
            fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            self.replay_lock = os.fdopen(fd, 'w')
            private_path(lock)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.replay_lock.close()
                raise ValueError('admission_state_in_use') from None
        try:
            self._load_replay()
        except BaseException:
            self.close()
            raise

    def _load_replay(self):
        saved = json.loads(private_read(self.replay_file, 262144)) if self.replay_file else {'schemaVersion': 1, 'spent': {}, 'revision': 0, 'digest': None, 'notBefore': 0}
        if not isinstance(saved, dict) or saved.get('schemaVersion') != 1 or type(saved.get('revision')) is not int or saved['revision'] < 0:
            raise ValueError('invalid_admission_replay_state')
        self.used = saved.get('spent')
        self.not_before = saved.get('notBefore')
        if type(self.not_before) not in (int, float) or not math.isfinite(self.not_before) or self.not_before < 0:
            raise ValueError('invalid_admission_replay_state')
        self.highest_revision, self.state_digest = saved['revision'], saved.get('digest')
        if self.highest_revision and (not isinstance(self.state_digest, str)
                or not re.fullmatch(r'[a-f0-9]{64}', self.state_digest)):
            raise ValueError('invalid_admission_replay_state')
        if not isinstance(self.used, dict) or len(self.used) > 1000 or any(
                not isinstance(k, str) or not 16 <= len(k) <= 128 or type(v) not in (int, float)
                or not math.isfinite(v) for k, v in self.used.items()):
            raise ValueError('invalid_admission_replay_state')

    def close(self):
        if self.replay_lock:
            self.replay_lock.close()

    def persist(self, *, used=None, revision=None, digest=None):
        revision = self.highest_revision if revision is None else revision
        digest = self.state_digest if digest is None else digest
        used = self.used if used is None else used
        if self.replay_file:
            private_write(self.replay_file, json.dumps({'schemaVersion': 1, 'spent': used,
                                                       'revision': revision, 'digest': digest,
                                                       'notBefore': self.not_before}))
        self.used, self.highest_revision, self.state_digest = used, revision, digest

    def state(self):
        # Published directory is mounted read-only into the blind relay. It contains
        # public verification keys and opaque ownership/revocation metadata only.
        with self.state_file.open('rb') as source:
            raw = source.read(1024*1024+1)
        if len(raw) > 1024*1024:
            raise AdmissionDenied('auth_state_too_large')
        value = json.loads(raw)
        now = time.time()
        if (value.get('schemaVersion') != 1 or value.get('issuer') != self.issuer
                or value.get('audience') != self.issuer or not isinstance(value.get('devices'), dict)
                or type(value.get('issuedAt')) not in (int, float)
                or type(value.get('expiresAt')) not in (int, float)
                or not now < value['expiresAt'] <= value['issuedAt']+180
                or not value['issuedAt'] <= now+5):
            raise AdmissionDenied('invalid_auth_state')
        revision = value.get('revision')
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if (type(revision) is not int or revision < 1 or revision < self.highest_revision
                or (revision == self.highest_revision and digest != self.state_digest)):
            raise AdmissionDenied('auth_state_rollback')
        if revision > self.highest_revision:
            self.persist(revision=revision, digest=digest)
        return value

    def active(self, account):
        try:
            state = self.state()
            device = state['devices'][account['devicePrincipal']]
            receiver = state['devices'][account['receiverPrincipal']]
            return (device['revoked'] is False and receiver['revoked'] is False
                    and device['userId'] == receiver['userId'] == account['userId']
                    and device['keyFingerprint'] == account['keyFingerprint']
                    and device['generation'] == account['keyGeneration'])
        except Exception:
            return False

    def authorize(self, token, proof):
        try:
            return self._authorize(token, proof)
        except Exception:
            # Never leak token, certificate, user identity or parsing exceptions.
            raise AdmissionDenied('admission_denied') from None

    def _authorize(self, token, proof):
        if not isinstance(token, str) or len(token) > 8192 or not isinstance(proof, str) or len(proof) > 512:
            raise AdmissionDenied('invalid_ticket')
        header_part, payload_part, signature_part = token.split('.')
        header, claims = json.loads(decode(header_part)), json.loads(decode(payload_part))
        if header.get('alg') != 'ES256' or header.get('crit') or not isinstance(header.get('kid'), str):
            raise AdmissionDenied('invalid_algorithm')
        state = self.state()
        keys = [key for key in state['jwks']['keys'] if key.get('kid') == header['kid']]
        if len(keys) != 1:
            raise AdmissionDenied('unknown_signing_key')
        signature = decode(signature_part)
        if len(signature) != 64:
            raise AdmissionDenied('invalid_signature')
        public_key(keys[0]).verify(encode_dss_signature(int.from_bytes(signature[:32], 'big'), int.from_bytes(signature[32:], 'big')),
                                  (header_part+'.'+payload_part).encode(), ec.ECDSA(hashes.SHA256()))
        now = time.time()
        if (claims.get('iss') != self.issuer or claims.get('aud') != self.issuer
                or type(claims.get('iat')) is not int or type(claims.get('exp')) is not int
                or not now < claims['exp'] <= claims['iat']+60 or claims['iat'] > now+5
                or claims['iat'] < self.not_before
                or claims.get('role') not in ('client', 'receiver')
                or not isinstance(claims.get('jti'), str) or not 16 <= len(claims['jti']) <= 128
                or not isinstance(claims.get('sub'), str) or not 1 <= len(claims['sub']) <= 256
                or type(claims.get('keyGeneration')) is not int):
            raise AdmissionDenied('invalid_claims')
        for field in ('devicePrincipal', 'receiverPrincipal', 'keyFingerprint'):
            if not isinstance(claims.get(field), str) or not re.fullmatch(r'[a-f0-9]{64}', claims[field]):
                raise AdmissionDenied('invalid_identity')
        if claims['role'] == 'receiver' and claims['devicePrincipal'] != claims['receiverPrincipal']:
            raise AdmissionDenied('invalid_role')
        if claims.get('room') != room_id(claims['sub'], claims['receiverPrincipal']):
            raise AdmissionDenied('invalid_room')
        public_key(claims['cnf']['jwk']).verify(decode(proof), b'session-peer-admission-v1:'+token.encode(), ec.ECDSA(hashes.SHA256()))
        account = {k: claims[k] for k in ('devicePrincipal', 'receiverPrincipal', 'keyFingerprint', 'keyGeneration', 'role', 'room')}
        account['userId'] = claims['sub']
        if not self.active(account):
            raise AdmissionDenied('device_revoked')
        used = {jti: expiry for jti, expiry in self.used.items() if expiry > now}
        if claims['jti'] in used or len(used) >= 1000:
            raise AdmissionDenied('reused_ticket')
        used[claims['jti']] = claims['exp']
        # Commit before issuing a cookie; a lost response burns this ticket.
        self.persist(used=used)
        return account
