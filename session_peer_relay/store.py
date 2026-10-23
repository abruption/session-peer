"""Device pairing and durable intent-before-effect journal."""
import hashlib
import contextlib
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


_NO_PAIRING_ATTEMPT = object()


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
        CREATE TABLE IF NOT EXISTS pairing_offers(id TEXT PRIMARY KEY,client_key TEXT NOT NULL,
            principal TEXT NOT NULL,generation INTEGER NOT NULL,state TEXT NOT NULL,
            created REAL NOT NULL,terminal REAL,receipt TEXT);
        CREATE TABLE IF NOT EXISTS pairing_reservations(peer TEXT PRIMARY KEY,invitation TEXT UNIQUE NOT NULL,
            client_key TEXT NOT NULL,created_peer INTEGER NOT NULL,created_key INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS pairing_limits(scope TEXT PRIMARY KEY,attempts TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pairing_intents(id TEXT PRIMARY KEY,digest TEXT NOT NULL,
            receiver TEXT NOT NULL,receiver_key TEXT NOT NULL,client_key TEXT NOT NULL);
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
        with self._pairing_transaction():
            return self._invite_locked(routes)

    def _invite_locked(self, routes, *, offer_id=None):
        if self.recovery_required():
            raise Rejected('recovery_required')
        secret = secrets.token_urlsafe(32)
        if offer_id is not None:
            try:
                valid = (type(offer_id) is str and str(uuid.UUID(offer_id)) == offer_id
                         and uuid.UUID(offer_id).version == 4)
            except (ValueError, AttributeError, TypeError):
                valid = False
            if not valid:
                raise Rejected('invalid_pairing_offer_id')
        ident = offer_id if offer_id is not None else str(uuid.uuid4())
        if self.db.execute('SELECT 1 FROM invites WHERE id=?', (ident,)).fetchone():
            raise Rejected('pairing_offer_exists')
        expires = time.time()+600
        self.db.execute('INSERT INTO invites VALUES(?,?,?,NULL)',
                        (ident, hashlib.sha256(secret.encode()).hexdigest(), expires))
        result = {'v': 1, 'id': ident, 'secret': secret, 'expires': expires,
                  'device': self.device, 'certificate': self.cert, 'routes': routes}
        if self.generation:
            result.update(v=2, keyFingerprint=self.key_id, keyGeneration=self.generation)
        return result

    @contextlib.contextmanager
    def _pairing_transaction(self, *, creation=False, attempt=_NO_PAIRING_ATTEMPT, read_only_quarantine=False):
        self.db.execute('BEGIN IMMEDIATE')
        savepoint = False
        try:
            if self.recovery_required():
                if not read_only_quarantine:
                    raise Rejected('recovery_required')
                # Restored history is evidence, not current lifecycle state.
                # No expiry, pruning or rate accounting may rewrite it.
                yield
                self.db.execute('COMMIT')
                return
            now = time.time()
            self._expire_pairings_locked(now)
            if creation:
                if self._pairing_charge_locked('create', 5, now):
                    raise Rejected('pairing_rate_limited')
            if attempt is not _NO_PAIRING_ATTEMPT:
                if self._pairing_charge_locked('prepare', 32, now):
                    raise Rejected('pairing_rate_limited')
                offer_scope = None
                if type(attempt) is str and self.db.execute('SELECT 1 FROM pairing_offers WHERE id=?', (attempt,)).fetchone():
                    offer_scope = 'offer:'+attempt
                    if self._pairing_charge_locked(offer_scope, 8, now):
                        raise Rejected('pairing_rate_limited')
            self.db.execute('SAVEPOINT pairing_work')
            savepoint = True
            yield
            self.db.execute('RELEASE pairing_work')
            self.db.execute('COMMIT')
        except Rejected:
            # Failed guesses consume durable quota, but never partial trust.
            if savepoint:
                self.db.execute('ROLLBACK TO pairing_work')
                self.db.execute('RELEASE pairing_work')
            self.db.execute('COMMIT')
            raise
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _pairing_charge_locked(self, scope, limit, now):
        row = self.db.execute('SELECT attempts FROM pairing_limits WHERE scope=?', (scope,)).fetchone()
        attempts = [value for value in json.loads(row[0]) if value > now-60] if row else []
        if len(attempts) >= limit:
            return True
        attempts.append(now)
        self.db.execute('INSERT INTO pairing_limits VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET attempts=excluded.attempts',
                        (scope, json.dumps(attempts)))
        return False

    def _release_reservation_locked(self, invitation):
        row = self.db.execute('SELECT peer,client_key,created_peer,created_key FROM pairing_reservations WHERE invitation=?',
                              (invitation,)).fetchone()
        if row:
            peer, key, created_peer, created_key = row
            pending = self.db.execute('SELECT status FROM peers WHERE id=?', (peer,)).fetchone()
            if pending == ('pending',):
                if created_peer:
                    self.db.execute('DELETE FROM peers WHERE id=?', (peer,))
                if created_key:
                    self.db.execute('DELETE FROM peer_keys WHERE fingerprint=? AND status="active"', (key,))
            self.db.execute('DELETE FROM pairing_reservations WHERE invitation=?', (invitation,))

    def _expire_pairings_locked(self, now):
        for (ident,) in self.db.execute('SELECT r.invitation FROM pairing_reservations r JOIN peers p ON p.id=r.peer '
                                        'WHERE p.status="pending" AND p.expires<=? '
                                        'AND NOT EXISTS (SELECT 1 FROM invites i WHERE '
                                        '(i.id=r.invitation OR i.peer=r.peer) AND i.expires>?)', (now, now)).fetchall():
            self._release_reservation_locked(ident)
        for ident, is_offer in self.db.execute('SELECT i.id,o.id FROM invites i LEFT JOIN pairing_offers o ON o.id=i.id '
                                              'WHERE i.expires<=? AND i.expires>0', (now,)).fetchall():
            self._release_reservation_locked(ident)
            self.db.execute('UPDATE pairing_offers SET state="expired",terminal=? WHERE id=? AND state IN ("open","reserved")',
                            (now, ident))
            if is_offer is None:
                self.db.execute('UPDATE invites SET expires=0 WHERE id=?', (ident,))
        # Old versions had no ownership rows. Remove only expired, unreserved
        # pending peer state with no surviving invitation authority; keep keys.
        self.db.execute('DELETE FROM peers WHERE status="pending" AND expires<=? '
                        'AND NOT EXISTS (SELECT 1 FROM pairing_reservations r WHERE r.peer=peers.id) '
                        'AND NOT EXISTS (SELECT 1 FROM invites i WHERE i.peer=peers.id AND i.expires>?)', (now, now))
        for (ident,) in self.db.execute('SELECT id FROM pairing_offers WHERE terminal<?', (now-7*86400,)).fetchall():
            self.db.execute('DELETE FROM invites WHERE id=?', (ident,))
            self.db.execute('DELETE FROM pairing_offers WHERE id=?', (ident,))
            self.db.execute('DELETE FROM pairing_limits WHERE scope=?', ('offer:'+ident,))

    def _offer_identity_locked(self, expected_key):
        if type(expected_key) is not str or re.fullmatch(r'[a-f0-9]{64}', expected_key) is None:
            raise Rejected('invalid_client_key')
        row = self.db.execute('SELECT principal,generation,status FROM peer_keys WHERE fingerprint=?', (expected_key,)).fetchone()
        if not row:
            return {'principal': expected_key, 'keyFingerprint': expected_key, 'generation': 0}
        peer = self.peer(row[0])
        if row[2] != 'active' or (peer and peer['status'] in ('pending', 'revoked')):
            raise Rejected('client_key_unavailable')
        return {'principal': row[0], 'keyFingerprint': expected_key, 'generation': row[1]}

    def offer_identity(self, expected_key):
        with self._pairing_transaction():
            return self._offer_identity_locked(expected_key)

    def create_offer(self, routes, expected_key, *, offer_id=None, expected_identity=None):
        with self._pairing_transaction(creation=True):
            try:
                identity = self._offer_identity_locked(expected_key)
            except Rejected:
                if expected_identity is not None:
                    raise Rejected('pairing_identity_changed') from None
                raise
            if expected_identity is not None and expected_identity != identity:
                raise Rejected('pairing_identity_changed')
            existing = self.peer(identity['principal'])
            if existing and existing['status'] == 'paired':
                raise Rejected('principal_already_paired')
            if self.db.execute('SELECT COUNT(*) FROM pairing_offers').fetchone()[0] >= 1024:
                raise Rejected('pairing_offer_capacity')
            if self.db.execute('SELECT COUNT(*) FROM pairing_offers WHERE state IN ("open","reserved")').fetchone()[0] >= 8:
                raise Rejected('pairing_offer_capacity')
            invitation = self._invite_locked(routes, offer_id=offer_id)
            self.db.execute('INSERT INTO pairing_offers VALUES(?,?,?,?,"open",?,NULL,NULL)',
                            (invitation['id'], expected_key, identity['principal'], identity['generation'], time.time()))
            # A committed offer must be representable by the public bounded
            # link codec. Invalid local routes never leave an unusable offer.
            from .pairing_links import encode_link
            try:
                encode_link(invitation, expected_key)
            except ValueError:
                raise Rejected('invalid_pairing_link') from None
            return invitation

    def _offer_status_locked(self, ident):
        row = self.db.execute('SELECT o.state,i.expires,o.principal,o.client_key,o.generation FROM pairing_offers o '
                              'JOIN invites i ON i.id=o.id WHERE o.id=?', (ident,)).fetchone()
        if not row:
            raise Rejected('pairing_offer_unknown')
        return {'ok': True, 'offerId': ident, 'status': row[0], 'expires': row[1],
                'client': {'principal': row[2], 'keyFingerprint': row[3], 'generation': row[4]}}

    def offer_status(self, offer_id):
        with self._pairing_transaction(read_only_quarantine=True):
            result = self._offer_status_locked(offer_id)
            if self.recovery_required():
                result.update(recoveryRequired=True, historical=True)
            return result

    def cancel_offer(self, offer_id):
        with self._pairing_transaction():
            status = self._offer_status_locked(offer_id)
            if status['status'] in ('open', 'reserved'):
                self._release_reservation_locked(offer_id)
                self.db.execute('UPDATE pairing_offers SET state="cancelled",terminal=? WHERE id=?', (time.time(), offer_id))
                self.db.execute('UPDATE invites SET expires=0 WHERE id=?', (offer_id,))
            return self._offer_status_locked(offer_id)

    def prepare(self, request):
        attempt = request.get('invitation') if type(request) is dict else None
        with self._pairing_transaction(attempt=attempt):
            if type(request) is not dict:
                raise Rejected('invalid_invitation')
            return self._prepare_locked(request)

    def _prepare_locked(self, request):
        if self.recovery_required():
            raise Rejected('recovery_required')
        now = time.time()
        if type(request.get('invitation')) is not str:
            raise Rejected('invalid_invitation')
        row = self.db.execute('SELECT hash,expires,peer FROM invites WHERE id=?',
                              (request.get('invitation'),)).fetchone()
        secret = request.get('secret')
        try:
            secret_hash = hashlib.sha256(secret.encode()).hexdigest() if isinstance(secret, str) else None
        except UnicodeError:
            raise Rejected('invalid_invitation') from None
        if (not row or row[1] <= now or not isinstance(secret, str)
                or not secrets.compare_digest(row[0], secret_hash)):
            raise Rejected('invalid_invitation')
        pem = request.get('certificate', '')
        if not isinstance(pem, str) or len(pem) > 8192:
            raise Rejected('invalid_certificate')
        try:
            key = fingerprint(pem)
        except (ValueError, TypeError, UnicodeError):
            raise Rejected('invalid_certificate') from None
        offer = self.db.execute('SELECT client_key,principal,generation,state FROM pairing_offers WHERE id=?',
                                (request.get('invitation'),)).fetchone()
        if bool(offer) != (request.get('offer') is True):
            raise Rejected('pairing_offer_required')
        if offer and (offer[0] != key or offer[3] not in ('open', 'reserved')):
            raise Rejected('invalid_pairing_offer')
        peer = request.get('principal', key)
        generation = request.get('generation', 0)
        if (not isinstance(peer, str) or not re.fullmatch(r'[a-f0-9]{64}', peer)
                or type(generation) is not int or generation < 0):
            raise Rejected('invalid_principal')
        if offer and (peer, generation) != (offer[1], offer[2]):
            raise Rejected('invalid_client_identity')
        # An invitation permits a new key, not impersonation of a policy principal.
        # TLS commit proves possession of `pem`, not ownership of a caller-chosen
        # stable identity. Rotated keys require an already trusted local binding
        # (authenticated rotation or a receiver invitation pinned by the operator).
        if peer != key or generation != 0:
            anchor = self.db.execute(
                'SELECT principal,cert,generation,status FROM peer_keys WHERE fingerprint=?',
                (key,)).fetchone()
            if anchor != (peer, pem, generation, 'active'):
                raise Rejected('unproven_principal')
        if row[2] and row[2] != peer:
            raise Rejected('invitation_already_reserved')
        existing = self.peer(peer)
        if existing and existing['status'] == 'revoked':
            raise Rejected('revoked_device')
        if existing and existing['certificate'] != pem:
            raise Rejected('principal_already_paired')
        if row[2] and existing and existing['status'] == 'paired':
            raise Rejected('invitation_consumed')
        owner = self.db.execute('SELECT invitation,client_key FROM pairing_reservations WHERE peer=?', (peer,)).fetchone()
        if existing and existing['status'] == 'pending' and not owner:
            owner = self._adopt_legacy_reservation_locked(peer, key, existing, request['invitation'])
        if owner and owner != (request['invitation'], key):
            raise Rejected('peer_already_reserved')
        if existing and existing['status'] == 'pending' and not owner:
            raise Rejected('peer_already_reserved')
        if existing and existing['status'] == 'paired':
            raise Rejected('principal_already_paired')
        key_exists = self.db.execute('SELECT principal,status FROM peer_keys WHERE fingerprint=?', (key,)).fetchone()
        if key_exists and key_exists != (peer, 'active'):
            raise Rejected('key_already_used')
        # Acceptance linearizes at this final server-clock check before trust
        # mutations. It does not make wall-clock time and durable fsync atomic.
        if row[1] <= time.time():
            raise Rejected('invalid_invitation')
        self.db.execute('UPDATE invites SET peer=? WHERE id=?', (peer, request['invitation']))
        # The certificate fingerprint and key binding were validated above;
        # do not repeat certificate parsing after the acceptance check.
        self.db.execute('INSERT OR IGNORE INTO peer_keys VALUES(?,?,?,?,"active",0)', (key, peer, pem, generation))
        if not owner:
            self.db.execute('INSERT INTO pairing_reservations VALUES(?,?,?,?,?)',
                            (peer, request['invitation'], key, int(existing is None), int(key_exists is None)))
        if existing is None:
            self.db.execute('INSERT INTO peers VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                            'status=excluded.status,expires=excluded.expires',
                            (peer, pem, 'pending', row[1], '{}', '["list","send"]'))
        if offer:
            self.db.execute('UPDATE pairing_offers SET state="reserved" WHERE id=?', (request['invitation'],))
        result = {'ok': True, 'pairing': 'pending', 'device': self.device,
                  'features': ['identity-rotation-v1', 'pairing-offer-v1']}
        if offer:
            result['offerId'] = request['invitation']
        return result

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

    def commit(self, peer, invitation=None, *, authenticated_key=None, offer=False):
        with self._pairing_transaction():
            return self._commit_locked(peer, invitation, authenticated_key=authenticated_key, offer=offer)

    def _commit_locked(self, peer, invitation, *, authenticated_key=None, offer=False):
        if self.recovery_required():
            raise Rejected('recovery_required')
        key = authenticated_key if authenticated_key is not None else peer
        principal = self.principal(key)
        if peer not in (key, principal) or self.key_status(key) != 'active':
            raise Rejected('invalid_client_identity')
        peer = principal
        row = self.peer(peer)
        if not row or row['status'] not in ('pending', 'paired') or (
                row['status'] == 'pending' and row['expires'] <= time.time()):
            raise Rejected('pairing_not_pending')
        supplied_invitation = invitation
        reservation = self.db.execute('SELECT invitation,client_key FROM pairing_reservations WHERE peer=?', (peer,)).fetchone()
        if row['status'] == 'pending' and not reservation:
            reservation = self._adopt_legacy_reservation_locked(peer, key, row, invitation)
        if invitation is None and reservation:
            invitation = reservation[0]
        bound = self.db.execute('SELECT client_key,principal,state,receipt FROM pairing_offers WHERE id=?', (invitation,)).fetchone()
        if bound:
            if not offer or authenticated_key is None or supplied_invitation is None or bound[:2] != (key, peer):
                raise Rejected('pairing_offer_required')
            if bound[2] == 'consumed' and row['status'] == 'paired':
                return json.loads(bound[3])
            if bound[2] != 'reserved':
                raise Rejected('pairing_not_pending')
        elif offer:
            raise Rejected('invalid_pairing_offer')
        if reservation and reservation != (invitation, key):
            raise Rejected('pairing_not_pending')
        if row['status'] == 'pending' and not reservation:
            raise Rejected('pairing_not_pending')
        if row['status'] == 'pending' and row['expires'] <= time.time():
            raise Rejected('pairing_not_pending')
        self.db.execute('UPDATE peers SET status="paired",expires=0 WHERE id=?', (peer,))
        if invitation is not None:
            self.db.execute('UPDATE invites SET expires=0 WHERE id=?', (invitation,))
            self.db.execute('DELETE FROM pairing_reservations WHERE invitation=?', (invitation,))
        result = {'ok': True, 'pairing': 'paired', 'device': self.device}
        if bound:
            result.update(offerId=invitation, features=['pairing-offer-v1'])
            self.db.execute('UPDATE pairing_offers SET state="consumed",terminal=?,receipt=? WHERE id=?',
                            (time.time(), json.dumps(result), invitation))
        return result

    def _adopt_legacy_reservation_locked(self, peer, key, existing, invitation=None):
        """Adopt only a provably unique, live pre-offer pending reservation."""
        if existing['status'] != 'pending' or fingerprint(existing['certificate']) != key:
            return None
        anchor = self.db.execute('SELECT principal,cert,generation,status FROM peer_keys WHERE fingerprint=?', (key,)).fetchone()
        if (not anchor or anchor[0] != peer or anchor[1] != existing['certificate'] or
                type(anchor[2]) is not int or anchor[2] < 0 or anchor[3] != 'active'):
            return None
        candidates = self.db.execute('SELECT i.id,i.expires,o.id FROM invites i LEFT JOIN pairing_offers o ON o.id=i.id '
                                     'WHERE i.peer=? AND i.expires>?', (peer, time.time())).fetchall()
        if (len(candidates) != 1 or candidates[0][2] is not None or
                candidates[0][1] != existing['expires'] or
                (invitation is not None and invitation != candidates[0][0])):
            return None
        ident = candidates[0][0]
        if self.db.execute('SELECT 1 FROM pairing_reservations WHERE invitation=?', (ident,)).fetchone():
            return None
        self.db.execute('INSERT INTO pairing_reservations VALUES(?,?,?,?,?)', (peer, ident, key, 1, 0))
        return ident, key

    def stage(self, invite):
        with self._pairing_transaction():
            return self._stage_locked(invite)

    def discard_pairing_stage(self, invitation):
        with self._pairing_transaction():
            self._release_reservation_locked(invitation)

    def _stage_locked(self, invite):
        existing = self.peer(invite['device'])
        if existing and existing['certificate'] != invite['certificate']:
            raise Rejected('principal_already_paired')
        if existing and existing['status'] == 'revoked':
            raise Rejected('revoked_device')
        if existing and existing['status'] == 'paired':
            return
        key = fingerprint(invite['certificate'])
        owner = self.db.execute('SELECT invitation,client_key FROM pairing_reservations WHERE peer=?', (invite['device'],)).fetchone()
        if owner and owner != (invite['id'], key):
            raise Rejected('peer_already_reserved')
        if existing and existing['status'] == 'pending' and not owner:
            raise Rejected('peer_already_reserved')
        key_exists = self.db.execute('SELECT 1 FROM peer_keys WHERE fingerprint=?', (key,)).fetchone()
        self.register_key(invite['device'], invite['certificate'], invite.get('keyGeneration', 0))
        if not owner:
            self.db.execute('INSERT INTO pairing_reservations VALUES(?,?,?,?,?)',
                            (invite['device'], invite['id'], key, int(existing is None), int(key_exists is None)))
        self.db.execute('INSERT OR REPLACE INTO peers VALUES(?,?,?,?,?,?)',
            (invite['device'], invite['certificate'], 'pending', invite['expires'],
             json.dumps(invite['routes']), '["list","send"]'))

    def remember(self, invite):
        with self._pairing_transaction():
            return self._remember_locked(invite)

    def _remember_locked(self, invite):
        if fingerprint(invite['certificate']) != invite.get('keyFingerprint', invite['device']):
            raise Rejected('pin_mismatch')
        existing = self.peer(invite['device'])
        if existing and existing['status'] == 'revoked':
            raise Rejected('revoked_device')
        if existing and existing['certificate'] != invite['certificate']:
            raise Rejected('principal_already_paired')
        if existing and existing['status'] == 'pending':
            owner = self.db.execute('SELECT invitation FROM pairing_reservations WHERE peer=?', (invite['device'],)).fetchone()
            if owner and owner != (invite['id'],):
                raise Rejected('peer_already_reserved')
        self.register_key(invite['device'], invite['certificate'], invite.get('keyGeneration', 0))
        if existing and existing['status'] == 'paired':
            # A receipt query confirms pairing; it does not reset operator
            # configured routes or capabilities from an old invitation.
            return
        self.db.execute('INSERT OR REPLACE INTO peers VALUES(?,?,?,?,?,?)',
            (invite['device'], invite['certificate'], 'paired', 0,
             json.dumps(invite['routes']), '["list","send"]'))
        self.db.execute('DELETE FROM pairing_reservations WHERE peer=? AND invitation=?', (invite['device'], invite['id']))

    def save_offer_intent(self, invite, digest, expected_key):
        """Persist only public confirmation facts, before staging or networking.

        Unlike lifecycle operations, cold-expired rejection performs no expiry
        cleanup or other database writes. A saved exact intent alone permits
        expired receipt reconciliation, never another preparation.
        """
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.recovery_required():
                raise Rejected('recovery_required')
            identity, existing = self._receiver_offer_identity_locked(invite, digest, expected_key)
            key = identity['keyFingerprint']
            previous = self.peer(invite['device'])
            facts = (digest, identity['principal'], key, expected_key)
            if not existing:
                if invite['expires'] <= time.time():
                    raise Rejected('invalid_invitation')
                if previous and previous['status'] == 'paired':
                    raise Rejected('invitation_consumed')
                if self.db.execute('SELECT COUNT(*) FROM pairing_intents').fetchone()[0] >= 1024:
                    raise Rejected('pairing_intent_capacity')
                self.db.execute('INSERT INTO pairing_intents VALUES(?,?,?,?,?)', (invite['id'], *facts))
            self.db.execute('COMMIT')
            return bool(existing)
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _receiver_offer_identity_locked(self, invite, digest, expected_key):
        if (type(digest) is not str or re.fullmatch(r'[a-f0-9]{64}', digest) is None
                or expected_key != self.key_id):
            raise Rejected('invalid_pairing_intent')
        key = fingerprint(invite['certificate'])
        identity = (invite['device'], key, invite.get('keyGeneration', 0))
        facts = (digest, identity[0], key, expected_key)
        existing = self.db.execute('SELECT digest,receiver,receiver_key,client_key FROM pairing_intents WHERE id=?',
                                   (invite['id'],)).fetchone()
        if existing and existing != facts:
            raise Rejected('pairing_intent_conflict')
        anchor = self.db.execute('SELECT principal,cert,generation,status FROM peer_keys WHERE fingerprint=?', (key,)).fetchone()
        expected_anchor = (identity[0], invite['certificate'], identity[2], 'active')
        if ((anchor and anchor != expected_anchor) or
                ((identity[0] != key or identity[2] != 0) and anchor != expected_anchor)):
            raise Rejected('unproven_receiver_principal')
        previous = self.peer(identity[0])
        if previous and previous['status'] == 'revoked':
            raise Rejected('revoked_device')
        if previous and previous['certificate'] != invite['certificate']:
            raise Rejected('principal_already_paired')
        if previous and self._expired_pending_projection_locked(identity[0], previous):
            previous = None
        if previous and previous['status'] == 'pending' and (not existing or anchor != expected_anchor):
            raise Rejected('receiver_pairing_pending')
        if invite['expires'] <= time.time() and not existing:
            raise Rejected('invalid_invitation')
        return {'principal': identity[0], 'keyFingerprint': key, 'generation': identity[2]}, bool(existing)

    def _expired_pending_projection_locked(self, peer, existing):
        """Read-only view of expired staging; no key or history is discarded."""
        now = time.time()
        if existing['status'] != 'pending' or existing['expires'] > now:
            return False
        if self.db.execute('SELECT 1 FROM invites WHERE peer=? AND expires>?', (peer, now)).fetchone():
            return False
        owner = self.db.execute('SELECT invitation,client_key FROM pairing_reservations WHERE peer=?', (peer,)).fetchone()
        if owner:
            if owner[1] != fingerprint(existing['certificate']):
                return False
            if self.db.execute('SELECT 1 FROM invites WHERE id=? AND expires>?', (owner[0], now)).fetchone():
                return False
        return True

    def receiver_offer_identity(self, invite, digest, expected_client_key):
        """Read-only receiver confirmation, including exact-intent recovery."""
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.recovery_required():
                raise Rejected('recovery_required')
            identity, unused = self._receiver_offer_identity_locked(invite, digest, expected_client_key)
            self.db.execute('COMMIT')
            return identity
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

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
