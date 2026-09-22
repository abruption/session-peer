"""Device pairing and durable intent-before-effect journal."""
import hashlib
import fcntl
import json
import os
import re
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

from .identity import fingerprint, initialize, private_path, private_read


class Rejected(ValueError):
    pass


class Store:
    def __init__(self, root, *, exclusive=False):
        self.root = Path(root)
        if (self.root/'restore-incomplete').exists():
            raise Rejected('restore_incomplete')
        # A quarantined archive is usable for local evidence/recovery planning
        # even when the old private key is genuinely lost. Normal states still
        # require a complete key/certificate pair before their database opens.
        quarantined = False
        database = self.root/'device.sqlite'
        if database.exists() and (self.root/'identity.pem').exists():
            private_path(database)
            probe = sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)
            try:
                quarantined = probe.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='recovery_tombstones'"
                ).fetchone() is not None and probe.execute(
                    'SELECT 1 FROM recovery_tombstones LIMIT 1').fetchone() is not None
            finally:
                probe.close()
        self.device = (fingerprint(private_read(self.root/'identity.pem')) if quarantined
                       else initialize(self.root))
        self._archival_quarantine = quarantined
        fd = os.open(self.root/'state.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.lock = os.fdopen(fd, 'w')
        private_path(self.root/'state.lock')
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise Rejected('device_state_busy') from None
        try:
            self._open()
        except BaseException:
            if hasattr(self, 'db'):
                self.db.close()
            self.lock.close()
            raise

    def _open(self):
        self.cert = private_read(self.root/'identity.pem')
        for name in ('device.sqlite', 'device.sqlite-wal', 'device.sqlite-shm'):
            path = self.root/name
            if path.exists() or path.is_symlink():
                private_path(path)
        self.db = sqlite3.connect(self.root/'device.sqlite', isolation_level=None)
        (self.root/'device.sqlite').chmod(0o600)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS invites(id TEXT PRIMARY KEY, hash TEXT, expires REAL, peer TEXT);
        CREATE TABLE IF NOT EXISTS peers(id TEXT PRIMARY KEY, cert TEXT, status TEXT, expires REAL,
                                         routes TEXT, capabilities TEXT);
        CREATE TABLE IF NOT EXISTS requests(peer TEXT,id TEXT,hash TEXT,status TEXT,result TEXT,
                                          PRIMARY KEY(peer,id));
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS peer_keys(fingerprint TEXT PRIMARY KEY,principal TEXT NOT NULL,
            cert TEXT NOT NULL,generation INTEGER NOT NULL,status TEXT NOT NULL,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS rotations(peer TEXT,id TEXT,hash TEXT,proposal TEXT,status TEXT,
            PRIMARY KEY(peer,id));
        CREATE TABLE IF NOT EXISTS recovery_tombstones(principal TEXT PRIMARY KEY,
            generation INTEGER NOT NULL,snapshot REAL NOT NULL,reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS recovery_approvals(id TEXT PRIMARY KEY,hash TEXT NOT NULL,
            old_peer TEXT NOT NULL,new_peer TEXT NOT NULL,response TEXT NOT NULL);
        ''')
        self.db.execute('INSERT OR IGNORE INTO metadata VALUES("principal",?)', (self.device,))
        self.device = self.db.execute('SELECT value FROM metadata WHERE key="principal"').fetchone()[0]
        self.db.execute('INSERT OR IGNORE INTO metadata VALUES("generation","0")')
        row = self.db.execute('SELECT value FROM metadata WHERE key="identity_directory"').fetchone()
        if row and (not re.fullmatch(r'keys/[0-9a-f-]{36}', row[0])
                    or str(uuid.UUID(row[0].split('/')[1])) != row[0].split('/')[1]):
            raise Rejected('invalid_identity_directory')
        self.identity_root = self.root / row[0] if row else self.root
        if self.identity_root != self.root:
            private_path(self.root/'keys', True)
            private_path(self.identity_root, True)
            if not self._archival_quarantine:
                initialize(self.identity_root)
        self.cert = private_read(self.identity_root/'identity.pem')
        self.key_id = fingerprint(self.cert)
        self.generation = int(self.db.execute('SELECT value FROM metadata WHERE key="generation"').fetchone()[0])
        for ident, cert in self.db.execute('SELECT id,cert FROM peers').fetchall():
            self.db.execute('INSERT OR IGNORE INTO peer_keys VALUES(?,?,?,0,"active",0)',
                            (fingerprint(cert), ident, cert))

    def close(self):
        self.db.close()
        self.lock.close()

    def principal(self, key):
        row = self.db.execute('SELECT principal,status,expires FROM peer_keys WHERE fingerprint=?', (key,)).fetchone()
        if row:
            if row[1] == 'revoked' or (row[1] == 'retired' and row[2] < time.time()):
                raise Rejected('retired_key')
            return row[0]
        return key

    def key_status(self, key):
        row = self.db.execute('SELECT status FROM peer_keys WHERE fingerprint=?', (key,)).fetchone()
        return row[0] if row else 'active'

    def register_key(self, principal, cert, generation=0):
        key = fingerprint(cert)
        row = self.db.execute('SELECT principal,status FROM peer_keys WHERE fingerprint=?', (key,)).fetchone()
        if row and (row[0] != principal or row[1] != 'active'):
            raise Rejected('key_already_used')
        if (not isinstance(principal, str) or not re.fullmatch(r'[a-f0-9]{64}', principal)
                or type(generation) is not int or generation < 0):
            raise Rejected('invalid_principal')
        self.db.execute('INSERT OR IGNORE INTO peer_keys VALUES(?,?,?,?,"active",0)', (key, principal, cert, generation))

    def recovery_required(self):
        if self.db.execute('SELECT 1 FROM recovery_tombstones LIMIT 1').fetchone():
            return True
        if self.db.execute('SELECT 1 FROM metadata WHERE key="recovery_required"').fetchone():
            return True
        origin = self.db.execute('SELECT 1 FROM metadata WHERE key="recovery_origin"').fetchone()
        activated = self.db.execute('SELECT 1 FROM metadata WHERE key="recovery_activation"').fetchone()
        return bool(origin and not activated)

    def invite(self, routes):
        if self.recovery_required():
            raise Rejected('recovery_required')
        secret = secrets.token_urlsafe(32)
        ident = str(uuid.uuid4())
        expires = time.time()+600
        self.db.execute('INSERT INTO invites VALUES(?,?,?,NULL)',
                        (ident, hashlib.sha256(secret.encode()).hexdigest(), expires))
        result = {'v': 1, 'id': ident, 'secret': secret, 'expires': expires,
                  'device': self.device, 'certificate': self.cert, 'routes': routes}
        if self.generation:
            result.update(v=2, keyFingerprint=self.key_id, keyGeneration=self.generation)
        return result

    def prepare(self, request):
        if self.recovery_required():
            raise Rejected('recovery_required')
        now = time.time()
        row = self.db.execute('SELECT hash,expires,peer FROM invites WHERE id=?',
                              (request.get('invitation'),)).fetchone()
        secret = request.get('secret')
        if (not row or row[1] < now or not isinstance(secret, str)
                or not secrets.compare_digest(row[0], hashlib.sha256(secret.encode()).hexdigest())):
            raise Rejected('invalid_invitation')
        pem = request.get('certificate', '')
        if not isinstance(pem, str) or len(pem) > 8192:
            raise Rejected('invalid_certificate')
        peer = request.get('principal', fingerprint(pem))
        if not isinstance(peer, str) or not re.fullmatch(r'[a-f0-9]{64}', peer):
            raise Rejected('invalid_principal')
        if row[2] and row[2] != peer:
            raise Rejected('invitation_already_reserved')
        existing = self.peer(peer)
        if existing and existing['status'] == 'revoked':
            raise Rejected('revoked_device')
        if existing and existing['certificate'] != pem:
            raise Rejected('principal_already_paired')
        if row[2] and existing and existing['status'] == 'paired':
            raise Rejected('invitation_consumed')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('UPDATE invites SET peer=? WHERE id=?', (peer, request['invitation']))
            self.register_key(peer, pem, request.get('generation', 0))
            self.db.execute('INSERT INTO peers VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                            'status=excluded.status,expires=excluded.expires',
                            (peer, pem, 'pending', row[1], '{}', '["list","send"]'))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        return {'ok': True, 'pairing': 'pending', 'device': self.device,
                'features': ['identity-rotation-v1']}

    def peer(self, ident):
        row = self.db.execute('SELECT cert,status,expires,routes,capabilities FROM peers WHERE id=?',
                              (ident,)).fetchone()
        if not row:
            return None
        return {'certificate': row[0], 'status': row[1], 'expires': row[2],
                'routes': json.loads(row[3]), 'capabilities': json.loads(row[4])}

    def trusted(self):
        certificates = [row[0] for row in self.db.execute(
            'SELECT cert FROM peers WHERE status="paired" OR (status="pending" AND expires>?)',
            (time.time(),))]
        certificates.extend(row[0] for row in self.db.execute(
            'SELECT k.cert FROM peer_keys k JOIN peers p ON p.id=k.principal '
            'WHERE p.status="paired" AND (k.status="pending" OR (k.status="retired" AND k.expires>?))',
            (time.time(),)))
        return list(dict.fromkeys(certificates))

    def commit(self, peer):
        if self.recovery_required():
            raise Rejected('recovery_required')
        peer = self.principal(peer)
        row = self.peer(peer)
        if not row or row['status'] not in ('pending', 'paired') or (
                row['status'] == 'pending' and row['expires'] < time.time()):
            raise Rejected('pairing_not_pending')
        self.db.execute('UPDATE peers SET status="paired",expires=0 WHERE id=?', (peer,))
        self.db.execute('UPDATE invites SET expires=0 WHERE peer=?', (peer,))
        return {'ok': True, 'pairing': 'paired', 'device': self.device}

    def stage(self, invite):
        existing = self.peer(invite['device'])
        if existing and existing['certificate'] != invite['certificate']:
            raise Rejected('principal_already_paired')
        if existing and existing['status'] == 'revoked':
            raise Rejected('revoked_device')
        self.register_key(invite['device'], invite['certificate'], invite.get('keyGeneration', 0))
        self.db.execute('INSERT OR REPLACE INTO peers VALUES(?,?,?,?,?,?)',
            (invite['device'], invite['certificate'], 'pending', invite['expires'],
             json.dumps(invite['routes']), '["list","send"]'))

    def remember(self, invite):
        if fingerprint(invite['certificate']) != invite.get('keyFingerprint', invite['device']):
            raise Rejected('pin_mismatch')
        self.register_key(invite['device'], invite['certificate'], invite.get('keyGeneration', 0))
        self.db.execute('INSERT OR REPLACE INTO peers VALUES(?,?,?,?,?,?)',
            (invite['device'], invite['certificate'], 'paired', 0,
             json.dumps(invite['routes']), '["list","send"]'))

    def revoke(self, peer):
        self.db.execute('UPDATE peers SET status="revoked" WHERE id=?', (peer,))
        self.db.execute('UPDATE peer_keys SET status="revoked" WHERE principal=?', (peer,))

    def authorize(self, peer, op):
        row = self.peer(peer)
        if not row or row['status'] != 'paired':
            raise Rejected('unpaired_device')
        capability = 'send' if op == 'resolve' else op
        if capability in ('list', 'send') and capability not in row['capabilities']:
            raise Rejected('operation_denied')
        if op not in ('list', 'send', 'resolve', 'probe', 'status', 'rotation.prepare', 'rotation.commit', 'rotation.status'):
            raise Rejected('operation_denied')

    def status(self, peer, ident):
        row = self.db.execute('SELECT status,result FROM requests WHERE peer=? AND id=?',
                              (peer, ident)).fetchone()
        if not row:
            if self.recovery_required():
                return {'ok': False, 'status': 'unknown', 'reason': 'recovery_gap',
                        'consumptionConfirmed': False, 'retryAllowed': False}
            return {'ok': True, 'status': 'not_found'}
        if row[0] == 'done':
            return json.loads(row[1])
        return {'ok': False, 'status': 'unknown', 'messageId': ident,
                'consumptionConfirmed': False, 'retryAllowed': False}

    def begin(self, peer, ident, text):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            result = self._begin_locked(peer, ident, text)
            self.db.execute('COMMIT')
            return result
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _begin_locked(self, peer, ident, text):
        digest = hashlib.sha256(text.encode()).hexdigest()
        row = self.db.execute('SELECT hash FROM requests WHERE peer=? AND id=?', (peer, ident)).fetchone()
        if row:
            if row[0] != digest:
                raise Rejected('message_id_conflict')
            return {**self.status(peer, ident), 'duplicate': True}
        if self.recovery_required():
            raise Rejected('recovery_required')
        if self.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] >= 10000:
            raise Rejected('journal_full')
        # Synchronous commit precedes the adapter side effect. Pending records are
        # never retried, including after restart: there is no atomic native inbox transaction.
        self.db.execute('INSERT INTO requests VALUES(?,?,?,"pending",NULL)', (peer, ident, digest))
        return None

    def finish(self, peer, ident, result):
        if result.get('requestId'):
            result = {**result, 'nativeRequestId': result['requestId']}
        result = {**result, 'messageId': ident, 'consumptionConfirmed': False}
        self.db.execute('UPDATE requests SET status="done",result=? WHERE peer=? AND id=?',
                        (json.dumps(result), peer, ident))
        return result
