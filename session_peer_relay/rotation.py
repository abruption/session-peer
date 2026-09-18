"""Explicit, resumable identity rotation; private keys never enter the wire."""
import base64
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .identity import fingerprint, initialize, private_read, private_path
from .store import Rejected


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def operation_id(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise Rejected('invalid_rotation_id') from None
    return value


def remote_status(store, peer, ident):
    operation_id(ident)
    row = store.db.execute('SELECT proposal,status FROM rotations WHERE peer=? AND id=?', (peer, ident)).fetchone()
    if not row:
        return {'ok': False, 'rotation': 'not_found', 'operationId': ident}
    proposal = json.loads(row[0])
    return {'ok': True, 'rotation': row[1], 'operationId': ident,
            'principal': peer, 'generation': proposal['generation'],
            'keyFingerprint': fingerprint(proposal['certificate'])}


def remote_prepare(store, peer, key, proposal):
    required = {'id', 'principal', 'previous', 'generation', 'certificate', 'receivers', 'proof'}
    if not isinstance(proposal, dict) or set(proposal) != required:
        raise Rejected('invalid_rotation')
    ident = operation_id(proposal['id'])
    if (proposal['principal'] != peer or proposal['previous'] != key
            or type(proposal['generation']) is not int
            or not isinstance(proposal['receivers'], list) or store.device not in proposal['receivers']
            or not isinstance(proposal['certificate'], str) or len(proposal['certificate']) > 8192):
        raise Rejected('invalid_rotation')
    try:
        certificate = x509.load_pem_x509_certificate(proposal['certificate'].encode())
        public = certificate.public_key()
        if not isinstance(public, ec.EllipticCurvePublicKey) or not isinstance(public.curve, ec.SECP256R1):
            raise ValueError()
        public.verify(base64.b64decode(proposal['proof'], validate=True),
                      canonical({k: v for k, v in proposal.items() if k != 'proof'}), ec.ECDSA(hashes.SHA256()))
    except Exception:
        raise Rejected('invalid_rotation_proof') from None
    digest = hashlib.sha256(canonical(proposal)).hexdigest()
    store.db.execute('BEGIN IMMEDIATE')
    try:
        existing = store.db.execute('SELECT hash FROM rotations WHERE peer=? AND id=?', (peer, ident)).fetchone()
        if existing:
            if existing[0] != digest:
                raise Rejected('rotation_id_conflict')
            result = remote_status(store, peer, ident)
        else:
            previous = store.db.execute('SELECT generation,status FROM peer_keys WHERE fingerprint=? AND principal=?', (key, peer)).fetchone()
            if not previous or previous[1] != 'active' or proposal['generation'] != previous[0]+1:
                raise Rejected('rotation_generation_conflict')
            if store.db.execute('SELECT 1 FROM rotations WHERE peer=? AND status="prepared"', (peer,)).fetchone():
                raise Rejected('rotation_in_progress')
            new_key = fingerprint(proposal['certificate'])
            if store.db.execute('SELECT 1 FROM peer_keys WHERE fingerprint=?', (new_key,)).fetchone():
                raise Rejected('key_already_used')
            store.db.execute('INSERT INTO peer_keys VALUES(?,?,?,?,"pending",0)', (new_key, peer, proposal['certificate'], proposal['generation']))
            store.db.execute('INSERT INTO rotations VALUES(?,?,?,?,"prepared")', (peer, ident, digest, json.dumps(proposal)))
            result = remote_status(store, peer, ident)
        store.db.execute('COMMIT')
        return result
    except BaseException:
        store.db.execute('ROLLBACK')
        raise


def remote_commit(store, peer, key, ident):
    operation_id(ident)
    store.db.execute('BEGIN IMMEDIATE')
    try:
        row = store.db.execute('SELECT proposal,status FROM rotations WHERE peer=? AND id=?', (peer, ident)).fetchone()
        if not row:
            raise Rejected('rotation_not_prepared')
        proposal = json.loads(row[0])
        if key != fingerprint(proposal['certificate']):
            raise Rejected('new_key_proof_required')
        if row[1] == 'prepared':
            # Old keys are recovery-only for ten minutes; no send/list authority.
            store.db.execute('UPDATE peer_keys SET status="retired",expires=? WHERE principal=? AND status="active"', (time.time()+600, peer))
            store.db.execute('UPDATE peer_keys SET status="active",expires=0 WHERE fingerprint=?', (key,))
            store.db.execute('UPDATE peers SET cert=? WHERE id=?', (proposal['certificate'], peer))
            store.db.execute('UPDATE rotations SET status="committed" WHERE peer=? AND id=?', (peer, ident))
        result = remote_status(store, peer, ident)
        store.db.execute('COMMIT')
        return result
    except BaseException:
        store.db.execute('ROLLBACK')
        raise


def local_prepare(store, ident):
    if store.recovery_required():
        raise Rejected('recovery_required')
    operation_id(ident)
    row = store.db.execute('SELECT value FROM metadata WHERE key="local_rotation"').fetchone()
    if row:
        saved = json.loads(row[0])
        if saved['proposal']['id'] == ident:
            return saved
        if saved['status'] != 'active':
            raise Rejected('rotation_in_progress')
    peers = [r[0] for r in store.db.execute('SELECT id FROM peers WHERE status="paired" ORDER BY id')]
    if not peers:
        raise Rejected('rotation_requires_paired_peer')
    directory = 'keys/'+ident
    (store.root/'keys').mkdir(mode=0o700, exist_ok=True)
    private_path(store.root/'keys', True)
    destination = store.root/directory
    if not destination.exists():
        staging = tempfile.mkdtemp(prefix='.rotation-', dir=store.root/'keys')
        try:
            initialize(staging)
            os.rename(staging, destination)
            fd = os.open(store.root/'keys', os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            if os.path.exists(staging):
                shutil.rmtree(staging)
    initialize(destination)
    certificate = private_read(store.root/directory/'identity.pem')
    proposal = {'id': ident, 'principal': store.device, 'previous': store.key_id,
                'generation': store.generation+1, 'certificate': certificate, 'receivers': peers}
    private = serialization.load_pem_private_key(private_read(store.root/directory/'identity.key').encode(), None)
    proposal['proof'] = base64.b64encode(private.sign(canonical(proposal), ec.ECDSA(hashes.SHA256()))).decode()
    saved = {'proposal': proposal, 'directory': directory, 'status': 'prepared',
             'previousDirectory': str(store.identity_root.relative_to(store.root))}
    control_name = store.db.execute('SELECT value FROM metadata WHERE key="control_name"').fetchone()
    if control_name:
        saved['controlName'] = control_name[0]
    store.db.execute('INSERT OR REPLACE INTO metadata VALUES("local_rotation",?)', (json.dumps(saved),))
    return saved


async def rotate(store, ident, route, credential, *, use_login=False):
    from .app import exchange
    saved = local_prepare(store, ident)
    proposal = saved['proposal']
    if saved['status'] == 'active':
        return {'ok': True, 'rotation': 'active', 'operationId': ident, 'device': store.device,
                'generation': store.generation, 'keyFingerprint': store.key_id}
    if use_login:
        from .control import rotation_credential
        credential = rotation_credential(store, saved)
    # Persisted proposal/key material are reused for every attempt and every peer.
    for peer in proposal['receivers']:
        peer_credential = credential.for_receiver(peer) if hasattr(credential, 'for_receiver') else credential
        try:
            result = await exchange(store, peer, 'rotation.prepare', proposal, route=route, credential=peer_credential)
        except Exception:
            result = {'ok': False}
        if not result.get('ok'):
            # The old key may already be retired after a lost commit response.
            previous_root = store.identity_root
            store.identity_root = store.root/saved['directory']
            try:
                try:
                    result = await exchange(store, peer, 'rotation.status', ident, route=route, credential=peer_credential)
                except Exception:
                    result = {'ok': False}
            finally:
                store.identity_root = previous_root
            if not result.get('ok'):
                return {'ok': False, 'rotation': 'pending', 'operationId': ident, 'retryAllowed': False,
                        'reason': 'rotation_reconciliation_required'}
    old_root = store.identity_root
    store.identity_root = store.root/saved['directory']
    try:
        for peer in proposal['receivers']:
            peer_credential = credential.for_receiver(peer) if hasattr(credential, 'for_receiver') else credential
            try:
                result = await exchange(store, peer, 'rotation.commit', ident, route=route, credential=peer_credential)
            except Exception:
                result = {'ok': False}
            if not result.get('ok'):
                return {'ok': False, 'rotation': 'pending', 'operationId': ident,
                        'reason': 'rotation_reconciliation_required', 'retryAllowed': False}
        store.db.execute('BEGIN IMMEDIATE')
        try:
            saved['status'] = 'active'
            for key, value in [('identity_directory', saved['directory']), ('generation', str(proposal['generation'])), ('local_rotation', json.dumps(saved))]:
                store.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)', (key, value))
            store.db.execute('COMMIT')
        except BaseException:
            store.db.execute('ROLLBACK')
            raise
        store.cert = proposal['certificate']
        store.key_id = fingerprint(store.cert)
        store.generation = proposal['generation']
        return {'ok': True, 'rotation': 'active', 'operationId': ident, 'device': store.device,
                'generation': store.generation, 'keyFingerprint': store.key_id}
    finally:
        if saved['status'] != 'active':
            store.identity_root = old_root
