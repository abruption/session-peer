"""Bounded diagnostics and offline, quarantined state snapshots."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time

from .identity import private_path, private_read, private_write
from .store import Rejected


def diagnostics(store):
    count, pending = store.db.execute('SELECT COUNT(*),COALESCE(SUM(status="pending"),0) FROM requests').fetchone()
    level = 'full' if count >= 10000 else 'critical' if count >= 9500 else 'warning' if count >= 8500 else 'notice' if count >= 7000 else 'normal'
    sizes = {name: (store.root/name).stat().st_size if (store.root/name).exists() else 0
             for name in ('device.sqlite', 'device.sqlite-wal', 'device.sqlite-shm')}
    return {'ok': True, 'device': store.device, 'keyFingerprint': store.key_id,
            'generation': store.generation, 'recoveryRequired': store.recovery_required(),
            'journal': {'count': count, 'limit': 10000, 'remaining': max(0, 10000-count),
                        'pendingUnknown': pending, 'level': level, 'bytes': sizes},
            'diskFreeBytes': shutil.disk_usage(store.root).free}


def backup(store, destination, policy):
    destination = Path(destination).expanduser().absolute()
    if destination == store.root or store.root in destination.parents:
        raise Rejected('backup_must_be_outside_device_state')
    policy_text = private_read(policy)
    from .native import Policy
    Policy(json.loads(policy_text))
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    private_path(destination, True)
    files = ['identity.key', 'identity.pem']
    if (store.root/'keys').exists():
        private_path(store.root/'keys', True)
        for directory in sorted((store.root/'keys').iterdir()):
            if directory.name.startswith('.rotation-'):
                # An interrupted pre-publication staging directory is not active
                # and was never referenced by a peer or metadata transaction.
                continue
            private_path(directory, True)
            files.extend(str((directory/name).relative_to(store.root)) for name in ('identity.key', 'identity.pem'))
    for name in files:
        private_write(destination/name, private_read(store.root/name))
    private_write(destination/'policy.json', policy_text)
    snapshot = sqlite3.connect(destination/'device.sqlite')
    try:
        (destination/'device.sqlite').chmod(0o600)
        store.db.backup(snapshot)
    finally:
        snapshot.close()
    files += ['device.sqlite', 'policy.json']
    manifest = {'schemaVersion': 1, 'createdAt': time.time(), 'device': store.device,
                'generation': store.generation, 'keyFingerprint': store.key_id,
                'requestCount': diagnostics(store)['journal']['count'],
                'files': {name: hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in files}}
    private_write(destination/'manifest.json', json.dumps(manifest, sort_keys=True))
    return {'ok': True, 'backup': str(destination), 'device': store.device,
            'requestCount': manifest['requestCount'], 'containsPrivateKeys': True,
            'encrypted': False, 'restoreRequiresReconciliation': True}


def restore(source, destination):
    source, destination = Path(source).expanduser(), Path(destination).expanduser()
    private_path(source, True)
    manifest = json.loads(private_read(source/'manifest.json'))
    if manifest.get('schemaVersion') != 1 or not isinstance(manifest.get('files'), dict):
        raise Rejected('invalid_backup_manifest')
    files = manifest['files']
    if not {'identity.key', 'identity.pem', 'device.sqlite', 'policy.json'} <= set(files):
        raise Rejected('incomplete_backup')
    for name, digest in files.items():
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or str(path) != name:
            raise Rejected('invalid_backup_path')
        if name not in ('identity.key', 'identity.pem', 'device.sqlite', 'policy.json'):
            if len(path.parts) != 3 or path.parts[0] != 'keys' or path.parts[2] not in ('identity.key', 'identity.pem'):
                raise Rejected('invalid_backup_path')
        for parent in path.parents:
            private_path(source/parent, True)
        private_path(source/path)
        if (source/path).stat().st_size > 128*1024*1024:
            raise Rejected('backup_file_too_large')
        if hashlib.sha256((source/path).read_bytes()).hexdigest() != digest:
            raise Rejected('backup_hash_mismatch')
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    private_path(destination, True)
    for name in files:
        target = destination/name
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open('xb') as out:
            os.chmod(target, 0o600)
            out.write((source/name).read_bytes())
            out.flush(); os.fsync(out.fileno())
    db = sqlite3.connect(destination/'device.sqlite')
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise Rejected('backup_database_corrupt')
        db.execute('INSERT OR REPLACE INTO metadata VALUES("recovery_required",?)', (json.dumps({'snapshotAt': manifest['createdAt'], 'reason': 'possible_post_snapshot_effects'}),))
        db.commit()
    finally:
        db.close()
    return {'ok': True, 'restored': str(destination), 'recoveryRequired': True,
            'sendEnabled': False, 'retryAllowed': False,
            'reason': 'reconcile_receipts_and_fence_old_identity_before_recovery'}
