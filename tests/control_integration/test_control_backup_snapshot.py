import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/ops/abruption-kr/session-peer-backup-snapshot.py"


def load_snapshot_module():
    spec = importlib.util.spec_from_file_location("session_peer_backup_snapshot", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@unittest.skipIf(os.name == "nt", "Linux control backup snapshot contract")
class ControlBackupSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.module = load_snapshot_module()
        self.db = self.root / "source.sqlite"
        with sqlite3.connect(self.db) as connection:
            connection.executescript("""
                CREATE TABLE session_peer_migrations(
                    version INTEGER PRIMARY KEY, appliedAt INTEGER NOT NULL
                );
                INSERT INTO session_peer_migrations VALUES(1,1);
                CREATE TABLE relay_devices(principal TEXT PRIMARY KEY);
                INSERT INTO relay_devices VALUES('fixture');
            """)
        self.module.CONTROL_DB = self.db
        self.module.FILES = tuple(Path(value) for value in (
            "/private/signing-key.pem",
            "/private/discovery.json",
            "/public/state.json",
            "/replay/spent-tickets.json",
        ))
        for source in self.module.FILES:
            (self.root / str(source).lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
        key = self.root / "private/signing-key.pem"
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(key)],
            check=True, capture_output=True,
        )
        public = subprocess.run(
            ["openssl", "pkey", "-in", str(key), "-pubout", "-outform", "DER"],
            check=True, capture_output=True,
        ).stdout
        kid = hashlib.sha256(public).hexdigest()
        (self.root / "public/state.json").write_text(json.dumps({
            "revision": 9, "devices": {"fixture": {}},
            "jwks": {"keys": [{"kid": kid}]},
        }))
        (self.root / "replay/spent-tickets.json").write_text(json.dumps({
            "revision": 8, "digest": "fixture-digest", "spent": {"ticket": 1},
        }))

    def tearDown(self):
        self.temp.cleanup()

    def test_snapshot_records_schema_integrity_key_and_revision_fence(self):
        snapshot = self.root / "snapshot"
        snapshot.mkdir()
        database, tables, version = self.module.database_snapshot(snapshot)
        # Put the copied product files at their paths inside the snapshot root.
        for source in self.module.FILES:
            relative = Path(str(source).lstrip("/"))
            target = snapshot / relative
            fixture = self.root / relative
            if fixture.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(fixture.read_bytes())
        contract = self.module.snapshot_contract(snapshot, version)
        self.assertEqual(database["integrity"], "ok")
        self.assertEqual(tables["relay_devices"], 1)
        self.assertEqual(contract["controlSchemaVersion"], 1)
        self.assertEqual(contract["publicStateRevision"], 9)
        self.assertEqual(contract["replayRevision"], 8)
        self.assertTrue(contract["replayDigestPresent"])

    def test_snapshot_rejects_schema_and_revision_rollback(self):
        with sqlite3.connect(self.db) as connection:
            connection.execute("UPDATE session_peer_migrations SET version=2")
        with self.assertRaisesRegex(RuntimeError, "control_schema_migration_required"):
            self.module.database_snapshot(self.root / "future")

        snapshot = self.root / "contract"
        for source in self.module.FILES:
            relative = Path(str(source).lstrip("/"))
            target = snapshot / relative
            source = self.root / relative
            if source.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
        (snapshot / "replay/spent-tickets.json").write_text(json.dumps({
            "revision": 10, "digest": "newer-than-control", "spent": {},
        }))
        with self.assertRaisesRegex(RuntimeError, "snapshot_revision_fence"):
            self.module.snapshot_contract(snapshot, 1)

    def test_help_and_invalid_arguments_do_not_touch_services(self):
        with mock.patch.object(self.module, "run") as run, mock.patch.object(
            self.module.os, "geteuid", side_effect=AssertionError("root check reached")
        ):
            for args, code in ((["--help"], 0), (["--unexpected"], 2), ([], 2)):
                with self.subTest(args=args), self.assertRaises(SystemExit) as exit_info:
                    self.module.main(args)
                self.assertEqual(exit_info.exception.code, code)
            run.assert_not_called()

    def test_snapshot_requires_explicit_run_flag(self):
        self.module.BASE = self.root / "snapshots"
        with mock.patch.object(self.module.os, "geteuid", return_value=0), mock.patch.object(
            self.module.os, "umask", return_value=0o077
        ), mock.patch.object(self.module, "run", side_effect=RuntimeError("snapshot_started")):
            with self.assertRaisesRegex(RuntimeError, "snapshot_started"):
                self.module.main(["--run"])


if __name__ == "__main__":
    unittest.main()
