import type Database from "better-sqlite3";

export const FIRST_PARTY_SCHEMA_VERSION = 1;

type MigrationHooks = {
  afterSchema?: (version: number) => void;
  beforeRecord?: (version: number) => void;
};

const REQUIRED_TABLES = [
  "relay_public_signups",
  "relay_device_claims",
  "relay_devices",
  "relay_challenges",
  "relay_operations",
  "relay_contract_metadata",
  "relay_public_revision",
  "session_peer_migrations",
] as const;

const REQUIRED_INDEXES = [
  "relay_devices_owner",
  "relay_challenge_expiry",
  "relay_operations_owner",
] as const;

function objects(db: Database.Database, type: "table" | "index") {
  return new Set(
    (db.prepare("SELECT name FROM sqlite_master WHERE type=?").all(type) as { name: string }[])
      .map((row) => row.name),
  );
}

function tableColumns(db: Database.Database, table: string) {
  return new Set(
    (db.prepare(`PRAGMA table_info(${table})`).all() as { name: string }[])
      .map((row) => row.name),
  );
}

function requireColumns(
  db: Database.Database,
  table: string,
  expected: string[],
) {
  const present = tableColumns(db, table);
  if (expected.some((name) => !present.has(name)))
    throw new Error(`migration_required:invalid_${table}`);
}

function migrationOne(db: Database.Database) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS relay_public_signups (
      providerId TEXT NOT NULL,
      accountId TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('pending','active')),
      expiresAt INTEGER NOT NULL,
      createdAt INTEGER NOT NULL,
      PRIMARY KEY(providerId,accountId)
    );
    CREATE TABLE IF NOT EXISTS relay_device_claims (
      id TEXT PRIMARY KEY,
      userId TEXT NOT NULL,
      sessionId TEXT NOT NULL,
      expiresAt INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS relay_devices (
      principal TEXT PRIMARY KEY,
      userId TEXT NOT NULL,
      keyFingerprint TEXT NOT NULL,
      certificateFingerprint TEXT NOT NULL,
      certificatePEM TEXT NOT NULL,
      keyGeneration INTEGER NOT NULL,
      name TEXT NOT NULL,
      revoked INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS relay_devices_owner ON relay_devices(userId);
    CREATE TABLE IF NOT EXISTS relay_challenges (
      id TEXT PRIMARY KEY,
      userId TEXT NOT NULL,
      operation TEXT NOT NULL,
      payload TEXT NOT NULL,
      message TEXT NOT NULL,
      expiresAt INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS relay_challenge_expiry ON relay_challenges(expiresAt);
    CREATE TABLE IF NOT EXISTS relay_operations (
      operationId TEXT PRIMARY KEY,
      userId TEXT NOT NULL,
      requestHash TEXT NOT NULL,
      result TEXT
    );
    CREATE INDEX IF NOT EXISTS relay_operations_owner ON relay_operations(userId);
    CREATE TABLE IF NOT EXISTS relay_contract_metadata (
      name TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS relay_public_revision (
      id INTEGER PRIMARY KEY CHECK(id=1),
      revision INTEGER NOT NULL
    );
  `);

  const legacy = db.prepare(
    "SELECT count(*) AS n FROM relay_devices WHERE keyFingerprint<>certificateFingerprint",
  ).get() as { n: number };
  if (legacy.n) throw new Error("contract_migration_required:legacy_fingerprint");

  const registration = db.prepare(
    "SELECT value FROM relay_contract_metadata WHERE name='registration'",
  ).get() as { value: string } | undefined;
  const stored = db.prepare(
    "SELECT (SELECT count(*) FROM relay_devices) + (SELECT count(*) FROM relay_operations) AS n",
  ).get() as { n: number };
  if (!registration) {
    if (stored.n) throw new Error("contract_migration_required:registration_marker");
    db.prepare(
      "INSERT INTO relay_contract_metadata VALUES ('registration','zero_based_v1')",
    ).run();
  } else if (registration.value !== "zero_based_v1") {
    throw new Error("contract_migration_required:registration_contract");
  }

  const revision = db.prepare(
    "SELECT revision FROM relay_public_revision WHERE id=1",
  ).get() as { revision: number } | undefined;
  if (!revision) {
    if (stored.n) throw new Error("contract_migration_required:revision_missing");
    db.prepare("INSERT INTO relay_public_revision VALUES(1,0)").run();
  } else if (!Number.isSafeInteger(revision.revision) || revision.revision < 0) {
    throw new Error("contract_migration_required:revision_invalid");
  }
}

export function runFirstPartyMigrations(
  db: Database.Database,
  hooks: MigrationHooks = {},
) {
  return db.transaction(() => {
    db.exec(`CREATE TABLE IF NOT EXISTS session_peer_migrations (
      version INTEGER PRIMARY KEY,
      appliedAt INTEGER NOT NULL
    )`);
    const applied = db.prepare(
      "SELECT version FROM session_peer_migrations ORDER BY version",
    ).all() as { version: number }[];
    if (applied.some((row) => !Number.isSafeInteger(row.version) || row.version < 1))
      throw new Error("migration_required:invalid_ledger");
    const current = applied.at(-1)?.version ?? 0;
    if (current > FIRST_PARTY_SCHEMA_VERSION)
      throw new Error("migration_required:future_schema");
    if (current < 1) {
      migrationOne(db);
      hooks.afterSchema?.(1);
      hooks.beforeRecord?.(1);
      db.prepare(
        "INSERT INTO session_peer_migrations(version,appliedAt) VALUES(1,?)",
      ).run(Math.floor(Date.now() / 1000));
    }
    return FIRST_PARTY_SCHEMA_VERSION;
  }).immediate();
}

export function validateFirstPartySchema(db: Database.Database) {
  try {
    if (db.pragma("integrity_check", { simple: true }) !== "ok")
      throw new Error("database_integrity");
    const tables = objects(db, "table");
    if (REQUIRED_TABLES.some((name) => !tables.has(name)))
      throw new Error("missing_table");
    const indexes = objects(db, "index");
    if (REQUIRED_INDEXES.some((name) => !indexes.has(name)))
      throw new Error("missing_index");
    const versions = db.prepare(
      "SELECT version FROM session_peer_migrations ORDER BY version",
    ).all() as { version: number }[];
    if (versions.length !== 1 || versions[0].version !== FIRST_PARTY_SCHEMA_VERSION)
      throw new Error(versions.some((row) => row.version > FIRST_PARTY_SCHEMA_VERSION)
        ? "future_schema" : "old_or_partial_schema");
    requireColumns(db, "relay_public_signups",
      ["providerId", "accountId", "status", "expiresAt", "createdAt"]);
    requireColumns(db, "relay_device_claims", ["id", "userId", "sessionId", "expiresAt"]);
    requireColumns(db, "relay_devices", ["principal", "userId", "keyFingerprint",
      "certificateFingerprint", "certificatePEM", "keyGeneration", "name", "revoked"]);
    requireColumns(db, "relay_challenges", ["id", "userId", "operation", "payload", "message", "expiresAt"]);
    requireColumns(db, "relay_operations", ["operationId", "userId", "requestHash", "result"]);
    const registration = db.prepare(
      "SELECT value FROM relay_contract_metadata WHERE name='registration'",
    ).get() as { value: string } | undefined;
    if (registration?.value !== "zero_based_v1") throw new Error("registration_contract");
    const revision = db.prepare(
      "SELECT revision FROM relay_public_revision WHERE id=1",
    ).get() as { revision: number } | undefined;
    if (!revision || !Number.isSafeInteger(revision.revision) || revision.revision < 0)
      throw new Error("revision_state");
    return FIRST_PARTY_SCHEMA_VERSION;
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("migration_required:"))
      throw error;
    const reason = error instanceof Error ? error.message : "invalid_schema";
    throw new Error(`migration_required:${reason}`);
  }
}
