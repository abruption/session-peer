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

export type AdminDetailView = "users" | "signups" | "devices" | "operations";
export type AdminDetailFilter = "all" | "active" | "pending" | "committed" | "revoked";

const DETAIL_LIMIT = 100;
const principalHint = (value: unknown) => {
  const text = typeof value === "string" ? value : "";
  return text.length > 20 ? `${text.slice(0, 12)}…${text.slice(-8)}` : text;
};

/** Allowlisted operator detail fields. Never expose credentials, certificates or proof payloads. */
export function adminMetricDetails(
  db: Database.Database,
  view: AdminDetailView,
  filter: AdminDetailFilter = "all",
) {
  if (view === "users") {
    if (filter !== "all") throw new Error("invalid_detail_filter");
    const rows = db.prepare(`SELECT u.name,u.email,u.emailVerified,u.createdAt,
      group_concat(DISTINCT a.providerId) AS providers,
      count(DISTINCT CASE WHEN d.revoked=0 THEN d.principal END) AS activeDevices,
      count(DISTINCT CASE WHEN d.revoked<>0 THEN d.principal END) AS revokedDevices
      FROM "user" u LEFT JOIN account a ON a.userId=u.id
      LEFT JOIN relay_devices d ON d.userId=u.id
      GROUP BY u.id ORDER BY u.createdAt DESC LIMIT ?`).all(DETAIL_LIMIT);
    return { view, filter, limit: DETAIL_LIMIT, rows };
  }
  if (view === "signups") {
    if (!["all", "active", "pending"].includes(filter))
      throw new Error("invalid_detail_filter");
    const where = filter === "all" ? "" : "WHERE s.status=?";
    const statement = db.prepare(`SELECT s.providerId AS provider,s.status,
      s.createdAt,s.expiresAt,u.name AS userName,u.email AS userEmail
      FROM relay_public_signups s
      LEFT JOIN account a ON a.providerId=s.providerId AND a.accountId=s.accountId
      LEFT JOIN "user" u ON u.id=a.userId ${where}
      ORDER BY s.createdAt DESC LIMIT ?`);
    const rows = filter === "all"
      ? statement.all(DETAIL_LIMIT)
      : statement.all(filter, DETAIL_LIMIT);
    return { view, filter, limit: DETAIL_LIMIT, rows };
  }
  if (view === "devices") {
    if (!["all", "active", "revoked"].includes(filter))
      throw new Error("invalid_detail_filter");
    const where = filter === "active"
      ? "WHERE d.revoked=0"
      : filter === "revoked"
        ? "WHERE d.revoked<>0"
        : "";
    const rows = db.prepare(`SELECT d.name,u.name AS ownerName,u.email AS ownerEmail,
      group_concat(DISTINCT a.providerId) AS providers,
      substr(d.principal,1,12)||'…'||substr(d.principal,-8) AS principalHint,
      d.keyGeneration,d.revoked
      FROM relay_devices d LEFT JOIN "user" u ON u.id=d.userId
      LEFT JOIN account a ON a.userId=d.userId ${where}
      GROUP BY d.principal ORDER BY d.revoked,d.name LIMIT ?`).all(DETAIL_LIMIT);
    return { view, filter, limit: DETAIL_LIMIT, rows };
  }
  if (!["all", "committed", "pending"].includes(filter))
    throw new Error("invalid_detail_filter");
  const where = filter === "committed"
    ? "WHERE o.result IS NOT NULL"
    : filter === "pending"
      ? "WHERE o.result IS NULL"
      : "";
  const raw = db.prepare(`SELECT o.operationId,u.name AS ownerName,
    u.email AS ownerEmail,o.result FROM relay_operations o
    LEFT JOIN "user" u ON u.id=o.userId ${where}
    ORDER BY o.rowid DESC LIMIT ?`).all(DETAIL_LIMIT) as {
      operationId: string;
      ownerName: string | null;
      ownerEmail: string | null;
      result: string | null;
    }[];
  const rows = raw.map(({ result, ...row }) => {
    let receipt: Record<string, unknown> = {};
    if (result) {
      try {
        receipt = JSON.parse(result) as Record<string, unknown>;
      } catch {
        receipt = {};
      }
    }
    return {
      ...row,
      committed: result !== null,
      principalHint: principalHint(receipt.principal),
      keyGeneration:
        typeof receipt.keyGeneration === "number" &&
        Number.isSafeInteger(receipt.keyGeneration)
        ? receipt.keyGeneration
        : null,
    };
  });
  return { view, filter, limit: DETAIL_LIMIT, rows };
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
