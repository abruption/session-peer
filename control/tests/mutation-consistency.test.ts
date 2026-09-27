import { afterEach, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { readFileSync, renameSync } from "node:fs";
import { join } from "node:path";
import { fixture, identity } from "./fixtures.js";
import { RelayControl } from "../src/server/relay-control.js";
import { openDatabase } from "../src/server/storage.js";

let f: Awaited<ReturnType<typeof fixture>> | undefined;
afterEach(() => { f?.cleanup(); f = undefined; });
const state = () => JSON.parse(readFileSync(join(f!.config.publicDir, "state.json"), "utf8"));
async function expectHealthy() {
  expect(f!.control.isHealthy()).toBe(true);
  expect((await f!.request("/healthz")).status).toBe(200);
  expect(f!.db.prepare("SELECT revision FROM relay_public_revision WHERE id=1").get())
    .toEqual({ revision: state().revision });
}

it("keeps readiness after invalid registration proof and allows the same challenge to succeed", async () => {
  f = await fixture();
  const d = identity(f.root, "device", "a");
  const request = f.proven(f.owner.id, "register", d.payload, d.privateKey);
  const before = state().revision;
  const response = await f.request("/api/relay/devices", { ...request, proof: "bad" });
  expect(response.status).toBe(400);
  await expectHealthy();
  expect(state().revision).toBeGreaterThan(before);
  expect(state().devices).toEqual({});
  expect(f.control.operation(f.owner.id, d.payload.operationId).committed).toBe(false);
  const receipt = f.control.register(f.owner.id, request);
  const committedRevision = state().revision;
  expect(f.control.register(f.owner.id, request)).toEqual(receipt);
  expect(state().revision).toBe(committedRevision);
  await expectHealthy();
});

it("keeps readiness when a competing rotation wins before a stale request", async () => {
  f = await fixture();
  const old = identity(f.root, "old", "a");
  const next = identity(f.root, "next", "b");
  f.control.register(f.owner.id, f.proven(f.owner.id, "register", old.payload, old.privateKey));
  const payload = { ...old.payload, certificatePEM: next.payload.certificatePEM,
    expectedGeneration: 0, keyGeneration: 1, operationId: randomUUID() };
  const losing = f.rotated(f.owner.id, payload, old.privateKey, next.privateKey);
  const winning = f.rotated(f.owner.id, { ...payload, operationId: randomUUID() }, old.privateKey, next.privateKey);
  f.control.register(f.owner.id, winning);
  const committed = state();
  expect(() => f!.control.register(f!.owner.id, losing)).toThrow("generation_conflict");
  await expectHealthy();
  expect(state().devices).toEqual(committed.devices);
  expect(state().revision).toBeGreaterThan(committed.revision);
  expect(f.control.operation(f.owner.id, payload.operationId).committed).toBe(false);
});

it.each(["register", "recover", "revoke"] as const)("fails closed on %s COMMIT failure, then republishes only rolled-back DB state", async (kind) => {
  f = await fixture();
  const old = identity(f.root, "old", "a");
  f.control.register(f.owner.id, f.proven(f.owner.id, "register", old.payload, old.privateKey));
  const next = identity(f.root, "next", "b");
  const payload = kind === "recover"
    ? { ...next.payload, oldPrincipal: old.payload.principal }
    : next.payload;
  const request = kind === "revoke" ? undefined : f.proven(f.owner.id, kind, payload, next.privateKey);
  const run = () => kind === "revoke" ? f!.control.revoke(f!.owner.id, old.payload.principal)
    : kind === "register" ? f!.control.register(f!.owner.id, request)
    : f!.control.recover(f!.owner.id, request);
  const before = state();
  // A deferred FK passes the mutation/publication and fails only at COMMIT.
  f.db.exec(`CREATE TABLE fault_parent(id TEXT PRIMARY KEY);
    CREATE TABLE fault_child(id TEXT REFERENCES fault_parent(id) DEFERRABLE INITIALLY DEFERRED);
    CREATE TRIGGER fault_commit AFTER ${kind === "register" ? "INSERT" : "UPDATE OF revoked"} ON relay_devices
    BEGIN INSERT INTO fault_child VALUES ('missing'); END;`);
  expect(run).toThrow("FOREIGN KEY constraint failed");
  const exposed = state();
  expect(exposed.revision).toBeGreaterThan(before.revision);
  expect(f.control.list(f.owner.id)).toMatchObject([{ principal: old.payload.principal, revoked: false }]);
  if (kind !== "revoke") expect(f.control.operation(f.owner.id, payload.operationId).committed).toBe(false);
  expect(f.control.healthy).toBe(false);
  expect((await f.request("/healthz")).status).toBe(503);
  const admission = { role: "receiver", devicePrincipal: old.payload.principal,
    receiverPrincipal: old.payload.principal };
  await expect(f.control.admit(f.owner.id, admission)).rejects.toThrow("state_unavailable");
  f.db.exec("DROP TRIGGER fault_commit");
  if (kind === "revoke") {
    // Startup can repair a failed COMMIT before the periodic timer runs.
    const recoveryDb = openDatabase(f.config.dataDir);
    try {
      const restarted = new RelayControl(recoveryDb, f.config);
      expect(restarted.isHealthy()).toBe(true);
      expect(state().revision).toBeGreaterThan(exposed.revision);
      expect(state().devices).toEqual(before.devices);
    } finally { recoveryDb.close(); }
  }
  // The normal periodic publication repairs the snapshot with a higher revision.
  f.control.publish();
  expect(state().revision).toBeGreaterThan(exposed.revision);
  expect(state().devices).toEqual(before.devices);
  await expectHealthy();
  const receipt = run();
  if (kind !== "revoke") expect(run()).toEqual(receipt);
  await expectHealthy();
  const second = openDatabase(f.config.dataDir);
  try {
    const restarted = new RelayControl(second, f.config);
    expect(restarted.isHealthy()).toBe(true);
    expect(restarted.list(f.owner.id)).toEqual(f.control.list(f.owner.id));
    if (kind !== "revoke") expect(restarted.operation(f.owner.id, payload.operationId)).toEqual(receipt);
  } finally { second.close(); }
});

it("keeps readiness after invalid recovery proof without fencing either device", async () => {
  f = await fixture();
  const old = identity(f.root, "old", "a");
  const next = identity(f.root, "next", "b");
  f.control.register(f.owner.id, f.proven(f.owner.id, "register", old.payload, old.privateKey));
  const request = f.proven(f.owner.id, "recover", { ...next.payload, oldPrincipal: old.payload.principal }, next.privateKey);
  const before = state();
  expect(() => f!.control.recover(f!.owner.id, { ...request, proof: "bad" })).toThrow("invalid_proof");
  await expectHealthy();
  expect(state().devices).toEqual(before.devices);
  f.control.recover(f.owner.id, request);
  await expectHealthy();
});

it("stays fail-closed if rejection repair cannot publish, then recovers without reusing a revision", async () => {
  f = await fixture();
  const d = identity(f.root, "device", "a");
  const request = f.proven(f.owner.id, "register", d.payload, d.privateKey);
  const before = state().revision;
  renameSync(f.config.publicDir, f.config.publicDir + "-away");
  expect(() => f!.control.register(f!.owner.id, { ...request, proof: "bad" })).toThrow("invalid_proof");
  expect(f.control.healthy).toBe(false);
  expect((await f.request("/healthz")).status).toBe(503);
  expect(() => f!.control.register(f!.owner.id, request)).toThrow("state_unavailable");
  renameSync(f.config.publicDir + "-away", f.config.publicDir);
  f.control.publish();
  expect(state().revision).toBeGreaterThan(before + 1);
  expect(state().devices).toEqual({});
  await expectHealthy();
  f.control.register(f.owner.id, request);
  await expectHealthy();
});
