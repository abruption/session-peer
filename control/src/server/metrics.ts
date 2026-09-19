import type Database from "better-sqlite3";
import type { Config } from "./config.js";

function count(db: Database.Database, sql: string, ...parameters: unknown[]) {
  return (db.prepare(sql).get(...parameters) as { n: number }).n;
}

export interface AdminMetrics {
  generatedAt: number;
  serviceHealthy: boolean;
  signup: {
    mode: "closed" | "open";
    registeredUsers: number;
    publicUsers: number;
    pendingReservations: number;
  };
  devices: { total: number; active: number; revoked: number };
  operations: { total: number; committed: number; pending: number };
  stateRevision: number;
}

/** Aggregate, non-identifying operator metrics. Never return account or device IDs. */
export function adminMetrics(
  db: Database.Database,
  config: Config,
  serviceHealthy: boolean,
  now = Date.now(),
): AdminMetrics {
  const nowSeconds = Math.floor(now / 1000);
  const registeredUsers = count(db, 'SELECT COUNT(*) AS n FROM "user"');
  const publicUsers = count(
    db,
    "SELECT COUNT(*) AS n FROM relay_public_signups WHERE status='active'",
  );
  const pendingReservations = count(
    db,
    "SELECT COUNT(*) AS n FROM relay_public_signups WHERE status='pending' AND expiresAt>=?",
    nowSeconds,
  );
  const activeDevices = count(
    db,
    "SELECT COUNT(*) AS n FROM relay_devices WHERE revoked=0",
  );
  const revokedDevices = count(
    db,
    "SELECT COUNT(*) AS n FROM relay_devices WHERE revoked<>0",
  );
  const committedOperations = count(
    db,
    "SELECT COUNT(*) AS n FROM relay_operations WHERE result IS NOT NULL",
  );
  const pendingOperations = count(
    db,
    "SELECT COUNT(*) AS n FROM relay_operations WHERE result IS NULL",
  );
  const revision = db
    .prepare("SELECT revision FROM relay_public_revision WHERE id=1")
    .get() as { revision: number } | undefined;
  return {
    generatedAt: now,
    serviceHealthy,
    signup: {
      mode: config.publicSignupEnabled ? "open" : "closed",
      registeredUsers,
      publicUsers,
      pendingReservations,
    },
    devices: {
      total: activeDevices + revokedDevices,
      active: activeDevices,
      revoked: revokedDevices,
    },
    operations: {
      total: committedOperations + pendingOperations,
      committed: committedOperations,
      pending: pendingOperations,
    },
    stateRevision: revision?.revision ?? 0,
  };
}
