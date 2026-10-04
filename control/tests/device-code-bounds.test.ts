import { it, expect, afterEach } from "vitest";
import { fixture } from "./fixtures.js";
import {
  DEVICE_CODE_PRUNE_INTERVAL_MS,
  DEVICE_CODE_RETENTION_MS,
  DeviceCodeGate,
  MAX_PENDING_DEVICE_CODES,
} from "../src/server/app.js";
let f: Awaited<ReturnType<typeof fixture>> | undefined;
afterEach(() => {
  f?.cleanup();
  f = undefined;
});
const rows = () =>
  (f!.db.prepare("SELECT COUNT(*) AS n FROM deviceCode").get() as { n: number }).n;
const issue = () =>
  f!.request("/api/auth/device/code", { client_id: "session-peer-cli" }, {});
function cloneRows(count: number, expiresAt: string) {
  const columns = (f!.db.prepare("PRAGMA table_info(deviceCode)").all() as { name: string }[])
    .map((column) => column.name);
  const template = f!.db.prepare("SELECT * FROM deviceCode LIMIT 1").get() as Record<string, unknown>;
  const insert = f!.db.prepare(
    `INSERT INTO deviceCode (${columns.join(",")}) VALUES (${columns.map(() => "?").join(",")})`,
  );
  f!.db.transaction(() => {
    for (let i = 0; i < count; i++) {
      const row: Record<string, unknown> = { ...template, id: "bulk-" + i + "-" + expiresAt,
        deviceCode: "bulk-device-" + i + expiresAt, userCode: "BULK" + i + expiresAt, expiresAt };
      insert.run(...columns.map((name) => row[name] ?? null));
    }
  })();
}

it("accepts only the first-party client_id field for unauthenticated device codes", async () => {
  f = await fixture();
  for (const body of [
    { client_id: "session-peer-cli", scope: "x".repeat(8000) },
    { client_id: "session-peer-cli", user_id: "x".repeat(8000) },
    { client_id: "x".repeat(65) },
    ["session-peer-cli"],
    {},
  ]) {
    const response = await f.request("/api/auth/device/code", body, {});
    expect(response.status).toBe(400);
    expect((await response.json()).error).toBe("invalid_device_request");
  }
  const malformed = await f.app(new Request(f.config.origin + "/api/auth/device/code", {
    method: "POST",
    headers: { "content-type": "application/json", "x-session-peer-ip": "192.0.2.250" },
    body: "{",
  }));
  expect(malformed.status).toBe(400);
  expect(rows()).toBe(0);
  expect((await issue()).status).toBe(200);
  expect(rows()).toBe(1);
  const stored = f.db.prepare("SELECT scope,userId FROM deviceCode").get() as { scope: unknown; userId: unknown };
  expect(stored.scope ?? null).toBeNull();
  expect(stored.userId).toBeNull();
});

it("prunes long-expired codes but keeps recently expired ones for late polls", async () => {
  f = await fixture();
  expect((await issue()).status).toBe(200);
  const now = Date.now();
  cloneRows(3, new Date(now - DEVICE_CODE_RETENTION_MS - 1000).toISOString());
  cloneRows(2, new Date(now - 1000).toISOString());
  expect(rows()).toBe(6);
  new DeviceCodeGate(f.db).admit({ client_id: "session-peer-cli" }, now)();
  expect(rows()).toBe(3);
});

it("refuses new device codes once pending codes reach the global cap", async () => {
  f = await fixture();
  expect((await issue()).status).toBe(200);
  const now = Date.now();
  cloneRows(MAX_PENDING_DEVICE_CODES - 1, new Date(now + 60_000).toISOString());
  const refused = await issue();
  expect(refused.status).toBe(503);
  expect((await refused.json()).error).toBe("device_code_capacity");
  expect(rows()).toBe(MAX_PENDING_DEVICE_CODES);
  // Once those codes expire, issuance resumes without manual cleanup.
  const release = new DeviceCodeGate(f.db).admit({ client_id: "session-peer-cli" }, now + 120_000);
  release();
});

it("holds the cap under concurrent issuance", async () => {
  f = await fixture();
  expect((await issue()).status).toBe(200);
  cloneRows(MAX_PENDING_DEVICE_CODES - 2, new Date(Date.now() + 60_000).toISOString());
  expect(rows()).toBe(MAX_PENDING_DEVICE_CODES - 1);
  const statuses = await Promise.all(Array.from({ length: 20 }, () => issue().then((r) => r.status)));
  expect(statuses.filter((status) => status === 200).length).toBeLessThanOrEqual(1);
  expect(statuses.filter((status) => status !== 200).every((status) => status === 503)).toBe(true);
  expect(rows()).toBeLessThanOrEqual(MAX_PENDING_DEVICE_CODES);
  const refused = await issue();
  expect(refused.status).toBe(503);
  expect(rows()).toBeLessThanOrEqual(MAX_PENDING_DEVICE_CODES);
});

it("releases reservations after refused and failing handlers", async () => {
  f = await fixture();
  expect((await issue()).status).toBe(200);
  cloneRows(MAX_PENDING_DEVICE_CODES - 2, new Date(Date.now() + 60_000).toISOString());
  // One slot remains. Refusals and handler failures must not keep it reserved.
  for (let i = 0; i < 3; i++) {
    const refused = await f.request("/api/auth/device/code", { client_id: "unknown-client" }, {});
    expect(refused.status).toBe(400);
  }
  const original = f.auth.handler;
  f.auth.handler = async () => {
    throw new Error("handler failure");
  };
  try {
    for (let i = 0; i < 3; i++)
      expect((await issue()).status).toBe(500);
  } finally {
    f.auth.handler = original;
  }
  expect((await issue()).status).toBe(200);
  expect(rows()).toBe(MAX_PENDING_DEVICE_CODES);
  expect((await issue()).status).toBe(503);
});

it("prunes expired codes at most once per interval, even with slow issuance", async () => {
  f = await fixture();
  expect((await issue()).status).toBe(200);
  const now = Date.now();
  const stale = (ms: number) => new Date(now - DEVICE_CODE_RETENTION_MS - ms).toISOString();
  const gate = new DeviceCodeGate(f.db);
  const body = { client_id: "session-peer-cli" };
  cloneRows(2, stale(1000));
  gate.admit(body, now)();
  expect(rows()).toBe(1);
  cloneRows(2, stale(2000));
  gate.admit(body, now + 1000)();
  expect(rows()).toBe(3);
  gate.admit(body, now + DEVICE_CODE_PRUNE_INTERVAL_MS)();
  expect(rows()).toBe(1);
});
