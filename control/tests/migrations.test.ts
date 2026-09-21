import Database from "better-sqlite3";
import { describe, expect, it } from "vitest";
import {
  FIRST_PARTY_SCHEMA_VERSION,
  runFirstPartyMigrations,
  validateFirstPartySchema,
} from "../src/server/migrations.js";

function memory() {
  const db = new Database(":memory:");
  db.pragma("foreign_keys = ON");
  return db;
}

function tableNames(db: Database.Database) {
  return (db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    .all() as { name: string }[]).map((row) => row.name);
}

function alphaSchema(db: Database.Database) {
  db.exec(`
    CREATE TABLE user (id TEXT PRIMARY KEY,email TEXT NOT NULL);
    INSERT INTO user VALUES('alpha-user','alpha@example.test');
    CREATE TABLE relay_public_signups (providerId TEXT NOT NULL,accountId TEXT NOT NULL,status TEXT NOT NULL,expiresAt INTEGER NOT NULL,createdAt INTEGER NOT NULL,PRIMARY KEY(providerId,accountId));
    CREATE TABLE relay_device_claims (id TEXT PRIMARY KEY,userId TEXT NOT NULL,sessionId TEXT NOT NULL,expiresAt INTEGER NOT NULL);
    CREATE TABLE relay_devices (principal TEXT PRIMARY KEY,userId TEXT NOT NULL,keyFingerprint TEXT NOT NULL,certificateFingerprint TEXT NOT NULL,certificatePEM TEXT NOT NULL,keyGeneration INTEGER NOT NULL,name TEXT NOT NULL,revoked INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX relay_devices_owner ON relay_devices(userId);
    CREATE TABLE relay_challenges (id TEXT PRIMARY KEY,userId TEXT NOT NULL,operation TEXT NOT NULL,payload TEXT NOT NULL,message TEXT NOT NULL,expiresAt INTEGER NOT NULL);
    CREATE INDEX relay_challenge_expiry ON relay_challenges(expiresAt);
    CREATE TABLE relay_operations (operationId TEXT PRIMARY KEY,userId TEXT NOT NULL,requestHash TEXT NOT NULL,result TEXT);
    CREATE INDEX relay_operations_owner ON relay_operations(userId);
    CREATE TABLE relay_contract_metadata (name TEXT PRIMARY KEY,value TEXT NOT NULL);
    INSERT INTO relay_contract_metadata VALUES('registration','zero_based_v1');
    CREATE TABLE relay_public_revision (id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL);
    INSERT INTO relay_public_revision VALUES(1,73);
  `);
}

describe("first-party control migrations", () => {
  it("migrates a fresh database completely before service construction", () => {
    const db = memory();
    try {
      expect(runFirstPartyMigrations(db)).toBe(FIRST_PARTY_SCHEMA_VERSION);
      expect(validateFirstPartySchema(db)).toBe(FIRST_PARTY_SCHEMA_VERSION);
      expect(db.prepare("SELECT version FROM session_peer_migrations").all())
        .toEqual([{ version: 1 }]);
      expect(db.prepare("SELECT revision FROM relay_public_revision WHERE id=1").get())
        .toEqual({ revision: 0 });
    } finally { db.close(); }
  });

  it("upgrades an alpha schema without losing identities tombstones receipts or revision", () => {
    const db = memory();
    try {
      alphaSchema(db);
      const principal = "a".repeat(64);
      db.prepare("INSERT INTO relay_devices VALUES(?,?,?,?,?,?,?,?)")
        .run(principal, "owner", principal, principal, "certificate", 2, "retired", 1);
      const receipt = JSON.stringify({ operationId: "11111111-1111-4111-8111-111111111111",
        committed: true, principal, keyFingerprint: principal, keyGeneration: 2 });
      db.prepare("INSERT INTO relay_operations VALUES(?,?,?,?)")
        .run("11111111-1111-4111-8111-111111111111", "owner", "digest", receipt);
      db.prepare("INSERT INTO relay_public_signups VALUES(?,?,?,?,?)")
        .run("github", "42", "active", 0, 10);
      db.prepare("INSERT INTO relay_device_claims VALUES(?,?,?,?)")
        .run("claim", "owner", "session", 20);
      runFirstPartyMigrations(db);
      expect(validateFirstPartySchema(db)).toBe(1);
      expect(db.prepare("SELECT principal,keyGeneration,revoked FROM relay_devices").get())
        .toEqual({ principal, keyGeneration: 2, revoked: 1 });
      expect(db.prepare("SELECT result FROM relay_operations").get()).toEqual({ result: receipt });
      expect(db.prepare("SELECT status FROM relay_public_signups").get()).toEqual({ status: "active" });
      expect(db.prepare("SELECT id FROM relay_device_claims").get()).toEqual({ id: "claim" });
      expect(db.prepare("SELECT revision FROM relay_public_revision").get()).toEqual({ revision: 73 });
      expect(db.prepare("SELECT * FROM user").get()).toEqual({
        id: "alpha-user", email: "alpha@example.test",
      });
    } finally { db.close(); }
  });

  it("is idempotent and reports the installed version", () => {
    const db = memory();
    try {
      runFirstPartyMigrations(db);
      const first = db.prepare("SELECT * FROM session_peer_migrations").all();
      expect(runFirstPartyMigrations(db)).toBe(1);
      expect(db.prepare("SELECT * FROM session_peer_migrations").all()).toEqual(first);
    } finally { db.close(); }
  });

  it("validates old partial future and corrupted schemas without mutation", () => {
    for (const kind of ["empty", "partial", "future", "corrupt"] as const) {
      const db = memory();
      try {
        if (kind === "partial") db.exec("CREATE TABLE relay_devices(principal TEXT)");
        if (kind === "future") {
          runFirstPartyMigrations(db);
          db.prepare("INSERT INTO session_peer_migrations VALUES(2,0)").run();
        }
        if (kind === "corrupt") {
          runFirstPartyMigrations(db);
          db.exec("DROP INDEX relay_devices_owner");
        }
        const before = db.serialize();
        expect(() => validateFirstPartySchema(db)).toThrow("migration_required");
        expect(db.serialize().equals(before)).toBe(true);
      } finally { db.close(); }
    }
  });

  it("rolls back an interrupted migration before recording completion", () => {
    const db = memory();
    try {
      expect(() => runFirstPartyMigrations(db, {
        afterSchema: () => { throw new Error("fixture_interruption"); },
      })).toThrow("fixture_interruption");
      expect(tableNames(db)).toEqual([]);
    } finally { db.close(); }
  });

  it("does not expose schema changes when ledger completion fails", () => {
    const db = memory();
    try {
      db.exec(`CREATE TABLE session_peer_migrations(version INTEGER PRIMARY KEY,appliedAt INTEGER NOT NULL);
        CREATE TRIGGER fail_migration BEFORE INSERT ON session_peer_migrations
        BEGIN SELECT RAISE(ABORT,'fixture_commit_failure'); END;`);
      expect(() => runFirstPartyMigrations(db)).toThrow("fixture_commit_failure");
      expect(tableNames(db)).toEqual(["session_peer_migrations"]);
      expect(db.prepare("SELECT * FROM session_peer_migrations").all()).toEqual([]);
    } finally { db.close(); }
  });

  it("accepts restart only after a committed migration", () => {
    const db = memory();
    try {
      runFirstPartyMigrations(db);
      expect(validateFirstPartySchema(db)).toBe(1);
      expect(runFirstPartyMigrations(db)).toBe(1);
      expect(validateFirstPartySchema(db)).toBe(1);
    } finally { db.close(); }
  });
});
