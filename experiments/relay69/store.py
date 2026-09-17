"""Test-only state, pairing and conservative durable submission journal."""
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

from .identity import fingerprint, initialize


class Rejected(ValueError):
    pass


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.device = initialize(self.root)
        self.cert = (self.root/'identity.pem').read_text()
        self.db = sqlite3.connect(self.root/'lab.sqlite', isolation_level=None)
        (self.root/'lab.sqlite').chmod(0o600)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS invites(id TEXT PRIMARY KEY, hash TEXT, expires REAL, peer TEXT);
        CREATE TABLE IF NOT EXISTS peers(id TEXT PRIMARY KEY, cert TEXT, status TEXT, expires REAL,
                                         routes TEXT, capabilities TEXT);
        CREATE TABLE IF NOT EXISTS requests(peer TEXT,id TEXT,hash TEXT,status TEXT,result TEXT,
                                          PRIMARY KEY(peer,id));
        CREATE TABLE IF NOT EXISTS effects(peer TEXT,id TEXT,hash TEXT);
        ''')

    def close(self):
        self.db.close()

    def invite(self, routes):
        secret = secrets.token_urlsafe(32)
        ident = str(uuid.uuid4())
        expires = time.time()+600
        self.db.execute('INSERT INTO invites VALUES(?,?,?,NULL)',
                        (ident, hashlib.sha256(secret.encode()).hexdigest(), expires))
        return {'v': 1, 'id': ident, 'secret': secret, 'expires': expires,
                'device': self.device, 'certificate': self.cert, 'routes': routes}

    def prepare(self, request):
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
        peer = fingerprint(pem)
        if row[2] and row[2] != peer:
            raise Rejected('invitation_already_reserved')
        existing = self.peer(peer)
        if row[2] and existing and existing['status'] == 'paired':
            raise Rejected('invitation_consumed')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('UPDATE invites SET peer=? WHERE id=?', (peer, request['invitation']))
            self.db.execute('INSERT INTO peers VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                            'status=excluded.status,expires=excluded.expires',
                            (peer, pem, 'pending', row[1], '{}', '["list","send"]'))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        return {'ok': True, 'pairing': 'pending', 'device': self.device}

    def peer(self, ident):
        row = self.db.execute('SELECT cert,status,expires,routes,capabilities FROM peers WHERE id=?',
                              (ident,)).fetchone()
        if not row:
            return None
        return {'certificate': row[0], 'status': row[1], 'expires': row[2],
                'routes': json.loads(row[3]), 'capabilities': json.loads(row[4])}

    def trusted(self):
        return [row[0] for row in self.db.execute(
            'SELECT cert FROM peers WHERE status="paired" OR (status="pending" AND expires>?)',
            (time.time(),))]

    def commit(self, peer):
        row = self.peer(peer)
        if not row or row['status'] not in ('pending', 'paired') or (
                row['status'] == 'pending' and row['expires'] < time.time()):
            raise Rejected('pairing_not_pending')
        self.db.execute('UPDATE peers SET status="paired",expires=0 WHERE id=?', (peer,))
        self.db.execute('UPDATE invites SET expires=0 WHERE peer=?', (peer,))
        return {'ok': True, 'pairing': 'paired', 'device': self.device}

    def stage(self, invite):
        self.db.execute('INSERT OR REPLACE INTO peers VALUES(?,?,?,?,?,?)',
            (invite['device'], invite['certificate'], 'pending', invite['expires'],
             json.dumps(invite['routes']), '["list","send"]'))

    def remember(self, invite):
        if fingerprint(invite['certificate']) != invite['device']:
            raise Rejected('pin_mismatch')
        self.db.execute('INSERT OR REPLACE INTO peers VALUES(?,?,?,?,?,?)',
            (invite['device'], invite['certificate'], 'paired', 0,
             json.dumps(invite['routes']), '["list","send"]'))

    def revoke(self, peer):
        self.db.execute('UPDATE peers SET status="revoked" WHERE id=?', (peer,))

    def authorize(self, peer, op):
        row = self.peer(peer)
        if not row or row['status'] != 'paired':
            raise Rejected('unpaired_device')
        if op in ('list', 'send') and op not in row['capabilities']:
            raise Rejected('operation_denied')
        if op not in ('list', 'send', 'probe', 'status'):
            raise Rejected('operation_denied')

    def status(self, peer, ident):
        row = self.db.execute('SELECT status,result FROM requests WHERE peer=? AND id=?',
                              (peer, ident)).fetchone()
        if not row:
            return {'ok': True, 'status': 'not_found'}
        if row[0] == 'done':
            return json.loads(row[1])
        return {'ok': False, 'status': 'unknown', 'messageId': ident,
                'consumptionConfirmed': False, 'retryAllowed': False}

    def submit(self, peer, ident, text, action):
        digest = hashlib.sha256(text.encode()).hexdigest()
        row = self.db.execute('SELECT hash FROM requests WHERE peer=? AND id=?', (peer, ident)).fetchone()
        if row:
            if row[0] != digest:
                raise Rejected('message_id_conflict')
            return {**self.status(peer, ident), 'duplicate': True}
        if self.db.execute('SELECT COUNT(*) FROM requests').fetchone()[0] >= 10000:
            raise Rejected('journal_full')
        # Synchronous commit precedes the adapter side effect. Pending records are
        # never retried, including after restart: there is no atomic native inbox transaction.
        self.db.execute('INSERT INTO requests VALUES(?,?,?,"pending",NULL)', (peer, ident, digest))
        result = action()
        result = {**result, 'messageId': ident, 'consumptionConfirmed': False}
        self.db.execute('UPDATE requests SET status="done",result=? WHERE peer=? AND id=?',
                        (json.dumps(result), peer, ident))
        return result
