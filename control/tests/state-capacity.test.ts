import { expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { fixture, identity } from "./fixtures.js";
import { RelayControl, PUBLIC_STATE_MAX_BYTES, serializePublicState } from "../src/server/relay-control.js";
import { openDatabase } from "../src/server/storage.js";

it("bounds UTF-8 serialized bytes below, at and above the limit including revoked rows", () => {
  const snapshot = { revision: Number.MAX_SAFE_INTEGER, issuedAt: Number.MAX_SAFE_INTEGER,
    expiresAt: Number.MAX_SAFE_INTEGER, devices: { fixture: { revoked: true, userId: "한😀" } }, padding: "" };
  const size = Buffer.byteLength(JSON.stringify(snapshot));
  for (const delta of [-1, 0, 1]) {
    const value = { ...snapshot, padding: "x".repeat(PUBLIC_STATE_MAX_BYTES - size + delta) };
    if (delta > 0) expect(() => serializePublicState(value)).toThrow("public_state_capacity_exceeded");
    else expect(Buffer.byteLength(serializePublicState(value))).toBe(PUBLIC_STATE_MAX_BYTES + delta);
  }
});

it("rejects growth without losing tombstones, readiness or restart/readability", async () => {
  const f = await fixture();
  try {
    const d = identity(f.root, "fixture", "a");
    f.control.register(f.owner.id, f.proven(f.owner.id, "register", d.payload, d.privateKey));
    f.control.revoke(f.owner.id, d.payload.principal);
    const path = join(f.config.publicDir, "state.json");
    const snapshot = JSON.parse(readFileSync(path, "utf8"));
    const worst = { ...snapshot, revision: Number.MAX_SAFE_INTEGER,
      issuedAt: Number.MAX_SAFE_INTEGER, expiresAt: Number.MAX_SAFE_INTEGER };
    // Synthetic variable-length ownership data fills the exact writer budget.
    const padding = "x".repeat(PUBLIC_STATE_MAX_BYTES - Buffer.byteLength(JSON.stringify(worst)));
    f.db.prepare("UPDATE relay_devices SET userId=userId || ?").run(padding);
    f.control.publish();
    const committed = JSON.parse(readFileSync(path, "utf8"));
    const next = identity(f.root, "next", "b");
    const req = f.proven(f.owner.id, "register", next.payload, next.privateKey);
    expect(() => f.control.register(f.owner.id, req)).toThrow("public_state_capacity_exceeded");
    expect(f.control.operation(f.owner.id, next.payload.operationId).committed).toBe(false);
    expect(f.control.list(f.owner.id)).toEqual([]);
    expect(f.control.isHealthy()).toBe(true);
    const repaired = JSON.parse(readFileSync(path, "utf8"));
    expect(repaired.devices).toEqual(committed.devices);
    expect(repaired.devices[d.payload.principal].revoked).toBe(true);
    expect(repaired.revision).toBeGreaterThan(committed.revision);
    expect(Buffer.byteLength(readFileSync(path))).toBeLessThanOrEqual(PUBLIC_STATE_MAX_BYTES);
    const second = openDatabase(f.config.dataDir);
    try { expect(new RelayControl(second, f.config).isHealthy()).toBe(true); }
    finally { second.close(); }
  } finally { f.cleanup(); }
});
