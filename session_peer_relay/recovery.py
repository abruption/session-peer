"""Explicit, resumable lost-key recovery without reviving restored identities."""
import base64
import hashlib
import json
import re
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from .identity import fingerprint, private_read
from .store import Rejected
from .wire import direct_address, validate_relay_url


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _uuid(value):
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise Rejected('invalid_operation_id') from None
    if parsed.version != 4 or str(parsed) != value:
        raise Rejected('invalid_operation_id')
    return value


def _derived(plan_id, label):
    return str(uuid.uuid5(uuid.UUID(plan_id), label))


def _routes(value):
    if not isinstance(value, dict) or not value or not set(value) <= {'direct', 'relay'}:
        raise Rejected('invalid_recovery_routes')
    if not all(isinstance(item, str) for item in value.values()):
        raise Rejected('invalid_recovery_routes')
    try:
        if 'direct' in value:
            direct_address(value['direct'])
        if 'relay' in value:
            validate_relay_url(value['relay'])
    except (ValueError, Rejected):
        raise Rejected('invalid_recovery_routes') from None
    return value


def _load(store):
    row = store.db.execute('SELECT value FROM metadata WHERE key="recovery_plan"').fetchone()
    if not row:
        raise Rejected('recovery_plan_not_found')
    value = json.loads(row[0])
    if not isinstance(value, dict) or value.get('schemaVersion') != 1:
        raise Rejected('invalid_recovery_plan')
    return value


def _save(store, plan):
    store.db.execute('INSERT OR REPLACE INTO metadata VALUES("recovery_plan",?)',
                     (_canonical(plan),))


def _sign(store, payload):
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(
        private_read(store.identity_root/'identity.key').encode(), None)
    raw = key.sign(_canonical(payload).encode(), ec.ECDSA(hashes.SHA256()))
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _verify(certificate, payload, proof):
    try:
        if not isinstance(proof, str) or not re.fullmatch(r'[A-Za-z0-9_-]{80,144}', proof):
            raise ValueError()
        padding = '=' * (-len(proof) % 4)
        cert = x509.load_pem_x509_certificate(certificate.encode())
        cert.public_key().verify(base64.urlsafe_b64decode(proof+padding),
                                 _canonical(payload).encode(), ec.ECDSA(hashes.SHA256()))
    except Exception:
        raise Rejected('invalid_recovery_proof') from None


def begin(restored, fresh, operation_id):
    _uuid(operation_id)
    if not restored.recovery_required():
        raise Rejected('restored_state_required')
    tombstone = restored.db.execute(
        'SELECT principal,generation,snapshot,reason FROM recovery_tombstones LIMIT 1').fetchone()
    if not tombstone:
        raise Rejected('recovery_tombstone_required')
    existing = fresh.db.execute('SELECT value FROM metadata WHERE key="recovery_plan"').fetchone()
    if existing:
        plan = json.loads(existing[0])
        if plan.get('id') != operation_id or plan.get('oldPrincipal') != tombstone[0]:
            raise Rejected('recovery_operation_conflict')
        return status(fresh)
    if fresh.db.execute('SELECT COUNT(*) FROM peers').fetchone()[0]:
        raise Rejected('fresh_state_required')
    peers = []
    for ident, cert, state, routes, capabilities in restored.db.execute(
            'SELECT id,cert,status,routes,capabilities FROM peers ORDER BY id'):
        if state != 'paired':
            continue
        peers.append({'principal': ident, 'certificate': cert, 'routes': json.loads(routes),
                      'capabilities': json.loads(capabilities),
                      'operationId': _derived(operation_id, 'peer:'+ident), 'status': 'pending'})
    native = []
    for peer, ident, state in restored.db.execute(
            'SELECT peer,id,status FROM requests ORDER BY peer,id'):
        native.append({'peer': peer, 'requestId': ident,
                       'classification': 'already_processed' if state == 'done' else 'unknown'})
    managed = restored.db.execute('SELECT value FROM metadata WHERE key="control_name"').fetchone()
    plan = {'schemaVersion': 1, 'id': operation_id, 'status': 'pending',
            'oldPrincipal': tombstone[0], 'oldGeneration': tombstone[1],
            'snapshotAt': tombstone[2], 'newPrincipal': fresh.device,
            'control': {'required': bool(managed), 'name': managed[0] if managed else None,
                        'operationId': operation_id, 'status': 'pending'},
            'peers': peers, 'nativeEffects': native, 'outgoingReceipts': [], 'operations': {}}
    fresh.db.execute('BEGIN IMMEDIATE')
    try:
        fresh.db.execute('INSERT INTO metadata VALUES("recovery_origin",?)',
                         (_canonical({'planId': operation_id, 'oldPrincipal': tombstone[0]}),))
        _save(fresh, plan)
        fresh.db.execute('COMMIT')
    except BaseException:
        fresh.db.execute('ROLLBACK')
        raise
    return status(fresh)


def status(fresh):
    plan = _load(fresh)
    native = [{k: item[k] for k in ('peer', 'requestId', 'classification')}
              for item in plan['nativeEffects']]
    outgoing = [{k: item[k] for k in ('peer', 'requestId', 'classification')}
                for item in plan['outgoingReceipts']]
    peers = [{'principal': item['principal'], 'routes': item['routes'],
              'operationId': item['operationId'], 'status': item['status']}
             for item in plan['peers']]
    gates = []
    ownership = 'direct_only'
    if plan['control']['required']:
        try:
            from .control import session
            session(fresh)
            ownership = 'authenticated'
        except (OSError, ValueError, KeyError, TypeError, Rejected):
            ownership = 'login_required'
    if plan['control']['required'] and plan['control']['status'] != 'committed':
        if ownership != 'authenticated':
            gates.append('control_login')
        gates.append('control_fence')
    gates.extend('native:'+x['peer']+':'+x['requestId'] for x in native
                 if x['classification'] == 'unknown')
    gates.extend('outgoing:'+x['peer']+':'+x['requestId'] for x in outgoing
                 if x['classification'] == 'unknown')
    gates.extend('peer:'+x['principal'] for x in peers if x['status'] != 'committed')
    if plan['status'] != 'active':
        gates.append('activation')
    phase = ('activation' if not gates or gates == ['activation'] else
             'inspection' if any(x.startswith(('native:', 'outgoing:')) for x in gates) else
             'fencing' if 'control_fence' in gates else
             're-pairing')
    return {'ok': True, 'recovery': {'schemaVersion': 1, 'operationId': plan['id'],
            'phase': phase, 'status': plan['status'], 'restoredIdentity': {
                'principal': plan['oldPrincipal'], 'generation': plan['oldGeneration'],
                'snapshotAt': plan['snapshotAt'], 'archival': True},
            'freshIdentity': {'principal': plan['newPrincipal'], 'generation': 0},
            'control': {**{k: plan['control'][k] for k in ('required', 'operationId', 'status')},
                        'ownership': ownership},
            'knownPeers': peers, 'nativeEffects': native, 'outgoingReceipts': outgoing,
            'unresolvedOutgoingReceipts': [x for x in outgoing if x['classification'] == 'unknown'],
            'remainingGates': sorted(gates)}}


def reconcile(fresh, operation_id, direction, peer, request_id, classification):
    _uuid(operation_id); _uuid(request_id)
    if direction not in ('native', 'outgoing') or classification not in (
            'already_processed', 'not_processed', 'unknown'):
        raise Rejected('invalid_reconciliation')
    if not isinstance(peer, str) or not re.fullmatch(r'[a-f0-9]{64}', peer):
        raise Rejected('invalid_principal')
    plan = _load(fresh)
    digest = hashlib.sha256(_canonical([direction, peer, request_id, classification]).encode()).hexdigest()
    previous = plan['operations'].get(operation_id)
    if previous:
        if previous != digest:
            raise Rejected('recovery_operation_conflict')
        return status(fresh)
    records = plan['nativeEffects'] if direction == 'native' else plan['outgoingReceipts']
    found = next((x for x in records if x['peer'] == peer and x['requestId'] == request_id), None)
    if direction == 'native' and not found:
        raise Rejected('native_effect_not_found')
    if not found:
        found = {'peer': peer, 'requestId': request_id, 'classification': classification}
        records.append(found)
    else:
        found['classification'] = classification
    plan['operations'][operation_id] = digest
    _save(fresh, plan)
    return status(fresh)


def peer_request(fresh, peer, routes):
    plan = _load(fresh)
    item = next((x for x in plan['peers'] if x['principal'] == peer), None)
    if not item:
        raise Rejected('recovery_peer_not_found')
    _routes(routes); _routes(item['routes'])
    payload = {'schemaVersion': 1, 'recoveryId': plan['id'],
               'operationId': item['operationId'], 'oldPrincipal': plan['oldPrincipal'],
               'newPrincipal': fresh.device, 'certificate': fresh.cert,
               'expectedPeer': peer, 'routes': routes, 'peerRoutes': item['routes']}
    return {**payload, 'proof': _sign(fresh, payload)}


def peer_approve(peer_store, request):
    required = {'schemaVersion', 'recoveryId', 'operationId', 'oldPrincipal', 'newPrincipal',
                'certificate', 'expectedPeer', 'routes', 'peerRoutes', 'proof'}
    if not isinstance(request, dict) or set(request) != required or request.get('schemaVersion') != 1:
        raise Rejected('invalid_recovery_request')
    if peer_store.recovery_required():
        raise Rejected('recovery_required')
    _uuid(request['recoveryId'])
    if str(uuid.uuid5(uuid.UUID(request['recoveryId']), 'peer:'+request['expectedPeer'])) != request['operationId']:
        raise Rejected('invalid_operation_id')
    if request['expectedPeer'] != peer_store.device or fingerprint(request['certificate']) != request['newPrincipal']:
        raise Rejected('recovery_identity_mismatch')
    _routes(request['routes']); _routes(request['peerRoutes'])
    payload = {k: request[k] for k in request if k != 'proof'}
    _verify(request['certificate'], payload, request['proof'])
    digest = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    prior = peer_store.db.execute('SELECT hash,response FROM recovery_approvals WHERE id=?',
                                  (request['operationId'],)).fetchone()
    if prior:
        if prior[0] != digest:
            raise Rejected('recovery_operation_conflict')
        return json.loads(prior[1])
    old = peer_store.peer(request['oldPrincipal'])
    if not old or old['status'] not in ('paired', 'revoked'):
        raise Rejected('old_identity_not_paired')
    if peer_store.peer(request['newPrincipal']):
        raise Rejected('new_identity_already_known')
    response_payload = {'schemaVersion': 1, 'recoveryId': request['recoveryId'],
                        'operationId': request['operationId'], 'oldPrincipal': request['oldPrincipal'],
                        'newPrincipal': request['newPrincipal'], 'peerPrincipal': peer_store.device,
                        'certificate': peer_store.cert, 'routes': request['peerRoutes'],
                        'capabilities': old['capabilities'], 'requestHash': digest}
    response = {**response_payload, 'proof': _sign(peer_store, response_payload)}
    encoded = _canonical(response)
    peer_store.db.execute('BEGIN IMMEDIATE')
    try:
        peer_store.revoke(request['oldPrincipal'])
        peer_store.register_key(request['newPrincipal'], request['certificate'], 0)
        peer_store.db.execute('INSERT INTO peers VALUES(?,?,?,?,?,?)',
            (request['newPrincipal'], request['certificate'], 'paired', 0,
             _canonical(request['routes']), _canonical(old['capabilities'])))
        peer_store.db.execute('INSERT INTO recovery_approvals VALUES(?,?,?,?,?)',
            (request['operationId'], digest, request['oldPrincipal'], request['newPrincipal'], encoded))
        peer_store.db.execute('COMMIT')
    except BaseException:
        peer_store.db.execute('ROLLBACK')
        raise
    return response


def peer_commit(fresh, response):
    required = {'schemaVersion', 'recoveryId', 'operationId', 'oldPrincipal', 'newPrincipal',
                'peerPrincipal', 'certificate', 'routes', 'capabilities', 'requestHash', 'proof'}
    if not isinstance(response, dict) or set(response) != required or response.get('schemaVersion') != 1:
        raise Rejected('invalid_recovery_approval')
    plan = _load(fresh)
    if response['recoveryId'] != plan['id'] or response['oldPrincipal'] != plan['oldPrincipal'] \
            or response['newPrincipal'] != fresh.device:
        raise Rejected('recovery_identity_mismatch')
    item = next((x for x in plan['peers'] if x['principal'] == response['peerPrincipal']), None)
    if not item or item['operationId'] != response['operationId'] \
            or item['certificate'] != response['certificate']:
        raise Rejected('recovery_peer_mismatch')
    payload = {k: response[k] for k in response if k != 'proof'}
    _verify(response['certificate'], payload, response['proof'])
    if item['status'] == 'committed':
        return status(fresh)
    _routes(response['routes'])
    if (not isinstance(response['capabilities'], list)
            or any(value not in ('list', 'send') for value in response['capabilities'])):
        raise Rejected('invalid_recovery_capabilities')
    fresh.db.execute('BEGIN IMMEDIATE')
    try:
        fresh.register_key(item['principal'], response['certificate'], 0)
        fresh.db.execute('INSERT OR REPLACE INTO peers VALUES(?,?,?,?,?,?)',
            (item['principal'], response['certificate'], 'paired', 0,
             _canonical(response['routes']), _canonical(response['capabilities'])))
        item['status'] = 'committed'
        _save(fresh, plan)
        fresh.db.execute('COMMIT')
    except BaseException:
        fresh.db.execute('ROLLBACK')
        raise
    return status(fresh)


def record_control(fresh, receipt):
    plan = _load(fresh)
    if not plan['control']['required']:
        raise Rejected('control_fence_not_required')
    expected = {'operationId': plan['control']['operationId'], 'committed': True,
                'oldPrincipal': plan['oldPrincipal'], 'principal': fresh.device,
                'keyFingerprint': fresh.key_id, 'keyGeneration': 0}
    if not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in expected.items()):
        raise Rejected('invalid_operation_receipt')
    plan['control']['status'] = 'committed'
    _save(fresh, plan)
    return status(fresh)


def activate(restored, fresh):
    plan = _load(fresh)
    tombstone = restored.db.execute('SELECT principal,generation FROM recovery_tombstones LIMIT 1').fetchone()
    if not tombstone or list(tombstone) != [plan['oldPrincipal'], plan['oldGeneration']]:
        raise Rejected('recovery_archive_mismatch')
    current = status(fresh)['recovery']
    remaining = [x for x in current['remainingGates'] if x != 'activation']
    if remaining:
        raise Rejected('recovery_gates_incomplete')
    if plan['status'] == 'active':
        return status(fresh)
    plan['status'] = 'active'
    fresh.db.execute('BEGIN IMMEDIATE')
    try:
        fresh.db.execute('INSERT OR REPLACE INTO metadata VALUES("recovery_activation",?)',
                         (_canonical({'operationId': plan['id'], 'oldPrincipal': plan['oldPrincipal']}),))
        _save(fresh, plan)
        fresh.db.execute('COMMIT')
    except BaseException:
        fresh.db.execute('ROLLBACK')
        raise
    return status(fresh)
