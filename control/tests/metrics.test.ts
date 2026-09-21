import Database from "better-sqlite3";
import { expect, it } from "vitest";
import { adminMetricDetails, relayMetrics } from "../src/server/metrics.js";

it("returns useful operator details without raw credentials, certificates or payloads", () => {
  const db = new Database(":memory:");
  try {
    db.exec(`
      CREATE TABLE "user" (id TEXT PRIMARY KEY,name TEXT,email TEXT,emailVerified INTEGER,createdAt TEXT);
      CREATE TABLE account (id TEXT PRIMARY KEY,accountId TEXT,providerId TEXT,userId TEXT);
      CREATE TABLE relay_public_signups (providerId TEXT,accountId TEXT,status TEXT,expiresAt INTEGER,createdAt INTEGER);
      CREATE TABLE relay_devices (principal TEXT PRIMARY KEY,userId TEXT,keyFingerprint TEXT,certificateFingerprint TEXT,certificatePEM TEXT,keyGeneration INTEGER,name TEXT,revoked INTEGER);
      CREATE TABLE relay_operations (operationId TEXT PRIMARY KEY,userId TEXT,requestHash TEXT,result TEXT);
    `);
    db.prepare('INSERT INTO "user" VALUES (?,?,?,?,?)').run(
      "user-secret-id",
      "Operator",
      "operator@example.test",
      1,
      "2026-09-20T00:00:00.000Z",
    );
    db.prepare("INSERT INTO account VALUES (?,?,?,?)").run(
      "account-row",
      "provider-secret-subject",
      "github",
      "user-secret-id",
    );
    db.prepare("INSERT INTO relay_public_signups VALUES (?,?,?,?,?)").run(
      "github",
      "provider-secret-subject",
      "active",
      0,
      1_789_000_000,
    );
    const principal = "a".repeat(64);
    db.prepare("INSERT INTO relay_devices VALUES (?,?,?,?,?,?,?,?)").run(
      principal,
      "user-secret-id",
      "fingerprint-secret",
      "fingerprint-secret",
      "certificate-secret-pem",
      2,
      "Laptop",
      0,
    );
    db.prepare("INSERT INTO relay_operations VALUES (?,?,?,?)").run(
      "11111111-1111-4111-8111-111111111111",
      "user-secret-id",
      "request-hash-secret",
      JSON.stringify({ principal, keyGeneration: 2, proof: "proof-secret" }),
    );

    const users = adminMetricDetails(db, "users");
    const signups = adminMetricDetails(db, "signups", "active");
    const devices = adminMetricDetails(db, "devices", "active");
    const operations = adminMetricDetails(db, "operations", "committed");
    expect(users.rows).toHaveLength(1);
    expect(signups.rows).toHaveLength(1);
    expect(devices.rows).toHaveLength(1);
    expect(operations.rows).toHaveLength(1);
    expect(operations.rows[0]).toMatchObject({
      operationId: "11111111-1111-4111-8111-111111111111",
      committed: true,
      principalHint: "aaaaaaaaaaaa…aaaaaaaa",
      keyGeneration: 2,
    });
    const output = JSON.stringify({ users, signups, devices, operations });
    expect(output).not.toContain("user-secret-id");
    expect(output).not.toContain("provider-secret-subject");
    expect(output).not.toContain("certificate-secret-pem");
    expect(output).not.toContain("request-hash-secret");
    expect(output).not.toContain("proof-secret");
    expect(output).not.toContain(principal);
  } finally {
    db.close();
  }
});

it("accepts only the fixed non-identifying relay aggregate schema", async () => {
  const payload = {
    schemaVersion: 1,
    generatedAt: 1_789_000_000_000,
    uptimeSeconds: 300,
    capacity: {
      handshake_rate: 20, pending_sessions: 100, global_connections: 10,
      user_connections: 8, device_connections: 4,
      connection_byte_budget: 33_554_432,
    },
    current: { activeConnections: 2, waitingRooms: 1, pendingSessions: 3 },
    counters: {
      handshakes: 10, sessionsIssued: 8, connectionsAccepted: 6,
      rateRejected: 1, sessionCapacityRejected: 2,
      connectionCapacityRejected: 3, unauthorizedRejected: 4,
      byteBudgetClosed: 5, forwardedFrames: 9, forwardedBytes: 1024,
    },
  };
  const config = { relayMetricsUrl: "http://127.0.0.1:3768/metrics" } as never;
  const result = await relayMetrics(config, async () =>
    new Response(JSON.stringify(payload), { status: 200 }));
  const { schemaVersion: _schemaVersion, ...aggregate } = payload;
  expect(result).toEqual({ available: true, ...aggregate });
  expect(JSON.stringify(result)).not.toMatch(/secret-user|secret-principal|secret-ticket|secret-proof|secret-token/i);
  expect(await relayMetrics(config, async () =>
    new Response(JSON.stringify({ ...payload, current: { userId: "secret" } }), { status: 200 })))
    .toEqual({ available: false });
  expect(await relayMetrics({} as never)).toEqual({ available: false });
});
