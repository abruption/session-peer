import { describe, it, expect, afterEach } from "vitest";
import {
  randomUUID,
  sign,
  verify,
  createHash,
  createPublicKey,
  X509Certificate,
} from "node:crypto";
import { readFileSync, renameSync, statSync } from "node:fs";
import { join } from "node:path";
import { importJWK, jwtVerify } from "jose";
import { fixture, identity } from "./fixtures.js";
import { RelayControl } from "../src/server/relay-control.js";
import { openDatabase } from "../src/server/storage.js";
import { certificate, room } from "../src/server/protocol.js";
let f: Awaited<ReturnType<typeof fixture>> | undefined;
afterEach(() => {
  f?.cleanup();
  f = undefined;
});
describe("relay device boundary", () => {
  it("publishes cross-UID readable state under umask 0077 without replacing the directory or exposing private state", async () => {
    const previous = process.umask(0o077);
    try {
      f = await fixture();
      const directory = statSync(f.config.publicDir);
      const statePath = join(f.config.publicDir, "state.json");
      const firstFile = statSync(statePath);
      expect(directory.mode & 0o777).toBe(0o755);
      expect(firstFile.mode & 0o777).toBe(0o644);
      expect(statSync(f.config.dataDir).mode & 0o777).toBe(0o700);
      expect(statSync(join(f.config.dataDir, "control.sqlite")).mode & 0o777).toBe(0o600);
      expect(statSync(join(f.config.dataDir, "signing-key.pem")).mode & 0o777).toBe(0o600);
      f.advance(60000);
      f.control.publish();
      expect(statSync(f.config.publicDir).ino).toBe(directory.ino);
      expect(statSync(statePath).ino).not.toBe(firstFile.ino);
      expect(statSync(statePath).mode & 0o777).toBe(0o644);
      const state = JSON.parse(readFileSync(statePath, "utf8"));
      expect(state.expiresAt - state.issuedAt).toBe(180);
    } finally {
      process.umask(previous);
    }
  });
  it("registers proof-bound P256 devices and signs a 60s owner/room admission", async () => {
    f = await fixture();
    const d = identity(f.root, "Device", "a");
    const r = identity(f.root, "Receiver", "b");
    for (const x of [d, r])
      f.control.register(
        f.owner.id,
        f.proven(f.owner.id, "register", x.payload, x.privateKey),
      );
    const body = {
      role: "client",
      devicePrincipal: d.payload.principal,
      receiverPrincipal: r.payload.principal,
    };
    const result = await f.control.admit(
      f.owner.id,
      f.proven(f.owner.id, "admission", body, d.privateKey),
    );
    const state = JSON.parse(
      readFileSync(join(f.config.publicDir, "state.json"), "utf8"),
    );
    const key = await importJWK(state.jwks.keys[0], "ES256");
    const verified = await jwtVerify(result.token, key, {
      issuer: f.config.origin,
      audience: f.config.origin,
      algorithms: ["ES256"],
    });
    expect(verified.payload.sub).toBe(f.owner.id);
    expect(verified.payload.receiverPrincipal).toBe(r.payload.principal);
    expect(verified.protectedHeader).toMatchObject({
      alg: "ES256",
      typ: "JWT",
      kid: state.jwks.keys[0].kid,
    });
    expect(verified.payload.exp! - verified.payload.iat!).toBe(60);
    expect(verified.payload.room).toBe(room(f.owner.id, r.payload.principal));
    const cnf = (verified.payload.cnf as any).jwk;
    expect(cnf).toMatchObject({ kty: "EC", crv: "P-256" });
    expect(Object.keys(cnf).sort()).toEqual(["crv", "kty", "x", "y"]);
    const expectedRoom = createHash("sha256")
      .update(Buffer.from(f.owner.id + "\0" + r.payload.principal, "utf8"))
      .digest("hex");
    expect(verified.payload.room).toBe(expectedRoom);
    expect(result.room).toBe(expectedRoom);
    // Python's relay proof is separate from the control nonce proof and binds
    // the entire JWT. Test the header encoding/message against native crypto.
    const message = "session-peer-admission-v1:" + result.token;
    const relayProof = sign("sha256", Buffer.from(message, "utf8"), {
      key: d.privateKey,
      dsaEncoding: "der",
    }).toString("base64url");
    const deviceKey = createPublicKey({ key: cnf, format: "jwk" });
    expect(
      verify(
        "sha256",
        Buffer.from(message, "utf8"),
        { key: deviceKey, dsaEncoding: "der" },
        Buffer.from(relayProof, "base64url"),
      ),
    ).toBe(true);
    expect(
      verify(
        "sha256",
        Buffer.from(message + "\n", "utf8"),
        { key: deviceKey, dsaEncoding: "der" },
        Buffer.from(relayProof, "base64url"),
      ),
    ).toBe(false);
    expect(
      verify(
        "sha256",
        Buffer.from(message, "utf8"),
        { key: r.privateKey, dsaEncoding: "der" },
        Buffer.from(relayProof, "base64url"),
      ),
    ).toBe(false);
    const cert = new X509Certificate(d.payload.certificatePEM);
    expect(state.devices[d.payload.principal].keyFingerprint).toBe(
      createHash("sha256").update(cert.raw).digest("hex"),
    );
    expect(state.devices[d.payload.principal].keyFingerprint).not.toBe(
      createHash("sha256")
        .update(cert.publicKey.export({ format: "der", type: "spki" }))
        .digest("hex"),
    );
    expect(state.expiresAt - state.issuedAt).toBe(180);
    expect(state.issuedAt).toBeLessThan(100000000000);
    expect(JSON.stringify(state)).not.toMatch(
      /email|certificatePEM|PRIVATE KEY|token/i,
    );
  });
  it("rejects replay, changed payload, different users, expiry and invalid proofs", async () => {
    f = await fixture();
    const d = identity(f.root, "Device", "a");
    const req = f.proven(f.owner.id, "register", d.payload, d.privateKey);
    expect(() =>
      f!.control.register(f!.owner.id, { ...req, name: "changed" }),
    ).toThrow("operation_conflict");
    expect(() => f!.control.register(f!.other.id, req)).toThrow(
      "operation_conflict",
    );
    expect(() =>
      f!.control.register(f!.owner.id, { ...req, proof: "bad" }),
    ).toThrow("invalid_proof");
    f.control.register(f.owner.id, req);
    expect(f.control.register(f.owner.id, req).committed).toBe(true);
    const expired = identity(f.root, "Expired", "c");
    const late = f.proven(
      f.owner.id,
      "register",
      expired.payload,
      expired.privateKey,
    );
    f.advance(60001);
    expect(() => f!.control.register(f!.owner.id, late)).toThrow(
      "invalid_or_expired_challenge",
    );
  });
  it("denies cross-owner admission, list leakage, principal takeover and key replacement", async () => {
    f = await fixture();
    const d = identity(f.root, "Device", "a");
    const alternate = identity(f.root, "DifferentKey", "b");
    f.control.register(
      f.owner.id,
      f.proven(f.owner.id, "register", d.payload, d.privateKey),
    );
    expect(f.control.list(f.other.id)).toEqual([]);
    expect(() =>
      f!.control.challenge(f!.other.id, {
        operation: "admission",
        payload: {
          role: "receiver",
          devicePrincipal: d.payload.principal,
          receiverPrincipal: d.payload.principal,
        },
      }),
    ).toThrow("device_not_found");
    expect(() =>
      f!.control.register(
        f!.other.id,
        f!.proven(
          f!.other.id,
          "register",
          { ...d.payload, operationId: randomUUID() },
          d.privateKey,
        ),
      ),
    ).toThrow("device_not_found");
    const replacement = {
      ...alternate.payload,
      principal: d.payload.principal,
      keyGeneration: 2,
      expectedGeneration: 1,
      operationId: randomUUID(),
    };
    expect(() =>
      f!.control.register(
        f!.owner.id,
        f!.proven(f!.owner.id, "register", replacement, alternate.privateKey),
      ),
    ).toThrow("previous_key_proof_required");
  });
  it("revokes without the lost key, retains a tombstone and rejects future admission/re-register", async () => {
    f = await fixture();
    const d = identity(f.root, "Device", "a");
    f.control.register(
      f.owner.id,
      f.proven(f.owner.id, "register", d.payload, d.privateKey),
    );
    expect(() => f!.control.revoke(f!.other.id, d.payload.principal)).toThrow(
      "device_not_found",
    );
    f.control.revoke(f.owner.id, d.payload.principal);
    const state = JSON.parse(
      readFileSync(join(f.config.publicDir, "state.json"), "utf8"),
    );
    expect(state.devices[d.payload.principal].revoked).toBe(true);
    expect(() =>
      f!.control.challenge(f!.owner.id, {
        operation: "admission",
        payload: {
          role: "receiver",
          devicePrincipal: d.payload.principal,
          receiverPrincipal: d.payload.principal,
        },
      }),
    ).toThrow("device_revoked");
    expect(() =>
      f!.control.register(
        f!.owner.id,
        f!.proven(
          f!.owner.id,
          "register",
          { ...d.payload, operationId: randomUUID() },
          d.privateKey,
        ),
      ),
    ).toThrow("device_revoked");
  });
  it("rolls back revocation if atomic state publication fails and returns failure", async () => {
    f = await fixture();
    const d = identity(f.root, "Device", "a");
    f.control.register(
      f.owner.id,
      f.proven(f.owner.id, "register", d.payload, d.privateKey),
    );
    renameSync(f.config.publicDir, f.config.publicDir + "-away");
    expect(() => f!.control.revoke(f!.owner.id, d.payload.principal)).toThrow(
      "state_publication_failed",
    );
    expect(f.control.list(f.owner.id)[0].revoked).toBe(false);
    expect(f.control.healthy).toBe(false);
  });
  it("bounds active challenges and rejects invalid principal/generation/receiver role", async () => {
    f = await fixture();
    const d = identity(f.root, "Device", "a");
    expect(() =>
      f!.control.challenge(f!.owner.id, {
        operation: "register",
        payload: { ...d.payload, keyGeneration: 0 },
      }),
    ).toThrow("invalid_generation");
    expect(() =>
      f!.control.challenge(f!.owner.id, {
        operation: "register",
        payload: { ...d.payload, principal: "../../" },
      }),
    ).toThrow("invalid_principal");
    for (let i = 0; i < 16; i++)
      f.control.challenge(f.owner.id, {
        operation: "register",
        payload: d.payload,
      });
    expect(() =>
      f!.control.challenge(f!.owner.id, {
        operation: "register",
        payload: d.payload,
      }),
    ).toThrow("too_many_challenges");
  });
});

describe("journaled registration and renewal", () => {
  async function setup() {
    f = await fixture();
    const old = identity(f.root, "Old", "a");
    const next = identity(f.root, "New", "b", 10);
    f.control.register(
      f.owner.id,
      f.proven(f.owner.id, "register", old.payload, old.privateKey),
    );
    const payload = {
      ...old.payload,
      certificatePEM: next.payload.certificatePEM,
      expectedGeneration: 1,
      keyGeneration: 2,
      operationId: randomUUID(),
    };
    return { old, next, payload };
  }
  it("increments once with same-message old/new proofs and exposes owner-only durable receipts", async () => {
    const { old, next, payload } = await setup();
    const req = f!.rotated(
      f!.owner.id,
      payload,
      old.privateKey,
      next.privateKey,
    );
    expect(f!.control.operation(f!.owner.id, payload.operationId)).toEqual({
      operationId: payload.operationId,
      committed: false,
    });
    expect(() =>
      f!.control.operation(f!.other.id, payload.operationId),
    ).toThrow("operation_not_found");
    expect(() => f!.control.operation(f!.other.id, randomUUID())).toThrow(
      "operation_not_found",
    );
    const receipt = f!.control.register(f!.owner.id, req);
    expect(receipt).toMatchObject({
      committed: true,
      keyGeneration: 2,
      principal: payload.principal,
    });
    expect(f!.control.operation(f!.owner.id, payload.operationId)).toEqual(
      receipt,
    );
    expect(f!.control.register(f!.owner.id, req)).toEqual(receipt);
    expect(f!.control.list(f!.owner.id)[0]).toMatchObject({
      name: "Old",
      keyGeneration: 2,
      revoked: false,
      keyFingerprint: certificate(next.payload.certificatePEM).keyFingerprint,
    });
    const secondDb = openDatabase(f!.config.dataDir);
    try {
      const restarted = new RelayControl(secondDb, f!.config);
      expect(restarted.operation(f!.owner.id, payload.operationId)).toEqual(
        receipt,
      );
      expect(restarted.register(f!.owner.id, req)).toEqual(receipt);
    } finally {
      secondDb.close();
    }
    const state = JSON.parse(
      readFileSync(join(f!.config.publicDir, "state.json"), "utf8"),
    );
    expect(state.devices[payload.principal].generation).toBe(2);
    const a = {
      role: "receiver",
      devicePrincipal: payload.principal,
      receiverPrincipal: payload.principal,
    };
    await expect(
      f!.control.admit(
        f!.owner.id,
        f!.proven(f!.owner.id, "admission", a, old.privateKey),
      ),
    ).rejects.toThrow("invalid_proof");
    const accepted = await f!.control.admit(
      f!.owner.id,
      f!.proven(f!.owner.id, "admission", a, next.privateKey),
    );
    const verified = await jwtVerify(
      accepted.token,
      await importJWK(state.jwks.keys[0], "ES256"),
    );
    expect(verified.payload.keyGeneration).toBe(2);
  });
  it("requires the old key and rejects wrong proofs/payloads/owner without committing", async () => {
    const { old, next, payload } = await setup();
    const req = f!.rotated(
      f!.owner.id,
      payload,
      old.privateKey,
      next.privateKey,
    );
    const { previousKeyProof, ...loginOnly } = req;
    expect(() => f!.control.register(f!.owner.id, loginOnly)).toThrow(
      "previous_key_proof_required",
    );
    for (const bad of [
      { ...req, previousKeyProof: "bad" },
      { ...req, proof: "bad" },
      { ...req, previousKeyProof: req.proof },
    ])
      expect(() => f!.control.register(f!.owner.id, bad)).toThrow(
        "invalid_proof",
      );
    expect(() => f!.control.register(f!.other.id, req)).toThrow(
      "operation_conflict",
    );
    expect(() =>
      f!.control.register(f!.owner.id, { ...req, name: "changed" }),
    ).toThrow("operation_conflict");
    expect(() =>
      f!.control.register(f!.owner.id, { ...req, operationId: randomUUID() }),
    ).toThrow("operation_not_found");
    expect(
      f!.control.operation(f!.owner.id, payload.operationId).committed,
    ).toBe(false);
    expect(f!.control.list(f!.owner.id)[0].keyGeneration).toBe(1);
  });
  it("rejects stale generation/operation collisions and never revives revoked identities", async () => {
    const { old, next, payload } = await setup();
    const req = f!.rotated(
      f!.owner.id,
      payload,
      old.privateKey,
      next.privateKey,
    );
    const receipt = f!.control.register(f!.owner.id, req);
    expect(() =>
      f!.control.register(f!.owner.id, {
        ...req,
        expectedGeneration: 2,
        keyGeneration: 3,
      }),
    ).toThrow("operation_conflict");
    expect(() =>
      f!.control.challenge(f!.owner.id, {
        operation: "register",
        payload: { ...payload, operationId: randomUUID() },
      }),
    ).toThrow("generation_conflict");
    const later = {
      ...payload,
      expectedGeneration: 2,
      keyGeneration: 3,
      certificatePEM: old.payload.certificatePEM,
      operationId: randomUUID(),
    };
    const late = f!.rotated(
      f!.owner.id,
      later,
      next.privateKey,
      old.privateKey,
    );
    f!.advance(60001);
    expect(() => f!.control.register(f!.owner.id, late)).toThrow(
      "invalid_or_expired_challenge",
    );
    f!.control.revoke(f!.owner.id, payload.principal);
    expect(f!.control.register(f!.owner.id, req)).toEqual(receipt);
    expect(f!.control.operation(f!.owner.id, payload.operationId)).toEqual(
      receipt,
    );
    expect(f!.control.list(f!.owner.id)[0].revoked).toBe(true);
    expect(() => f!.control.register(f!.owner.id, late)).toThrow(
      "device_revoked",
    );
    expect(() =>
      f!.control.challenge(f!.owner.id, {
        operation: "register",
        payload: later,
      }),
    ).toThrow("device_revoked");
    expect(
      JSON.parse(readFileSync(join(f!.config.publicDir, "state.json"), "utf8"))
        .devices[payload.principal].revoked,
    ).toBe(true);
  });
  it("renews expired old certificates but keeps new certificate validity and generation checks", async () => {
    const { old, next, payload } = await setup();
    f!.advance(3 * 86400000);
    expect(() =>
      f!.control.challenge(f!.owner.id, {
        operation: "register",
        payload: { ...payload, certificatePEM: old.payload.certificatePEM },
      }),
    ).toThrow("certificate_expired_or_not_valid");
    expect(() =>
      f!.control.challenge(f!.owner.id, {
        operation: "register",
        payload: { ...payload, expectedGeneration: 0 },
      }),
    ).toThrow("invalid_generation");
    expect(
      f!.control.register(
        f!.owner.id,
        f!.rotated(f!.owner.id, payload, old.privateKey, next.privateKey),
      ).keyGeneration,
    ).toBe(2);
  });
  it("invalidates old outstanding proofs and refuses tokens issued across a generation change", async () => {
    const { old, next, payload } = await setup();
    const a = {
      role: "receiver",
      devicePrincipal: payload.principal,
      receiverPrincipal: payload.principal,
    };
    const waiting = f!.proven(f!.owner.id, "admission", a, old.privateKey);
    const racing = f!.control.admit(
      f!.owner.id,
      f!.proven(f!.owner.id, "admission", a, old.privateKey),
    );
    f!.control.register(
      f!.owner.id,
      f!.rotated(f!.owner.id, payload, old.privateKey, next.privateKey),
    );
    await expect(racing).rejects.toThrow("generation_conflict");
    await expect(f!.control.admit(f!.owner.id, waiting)).rejects.toThrow(
      "invalid_or_expired_challenge",
    );
  });
  it("keeps the operation uncommitted and rolls back generation if publication fails", async () => {
    const { old, next, payload } = await setup();
    const req = f!.rotated(
      f!.owner.id,
      payload,
      old.privateKey,
      next.privateKey,
    );
    renameSync(f!.config.publicDir, f!.config.publicDir + "-away");
    expect(() => f!.control.register(f!.owner.id, req)).toThrow(
      "state_publication_failed",
    );
    expect(f!.control.list(f!.owner.id)[0].keyGeneration).toBe(1);
    expect(
      f!.control.operation(f!.owner.id, payload.operationId).committed,
    ).toBe(false);
    expect(f!.control.healthy).toBe(false);
  });
  it("returns second-based nonce times, retains pending outcomes after expiry and refuses old SPKI data", async () => {
    f = await fixture();
    const d = identity(f.root, "Device", "a");
    const c = f.control.challenge(f.owner.id, {
      operation: "register",
      payload: d.payload,
    });
    expect(c.proofMessage.startsWith("session-peer-control-v1:")).toBe(true);
    expect(c.proofMessage.endsWith("\n")).toBe(false);
    expect(c.expiresAt - c.issuedAt).toBe(60);
    expect(
      Math.abs(c.issuedAt - Math.floor(Date.now() / 1000)),
    ).toBeLessThanOrEqual(1);
    expect(c.expiresAt).toBeLessThan(100000000000);
    f.advance(60001);
    expect(
      f.control.operation(f.owner.id, d.payload.operationId).committed,
    ).toBe(false);
    const fresh = f.proven(f.owner.id, "register", d.payload, d.privateKey);
    f.control.register(f.owner.id, fresh);
    const cert = new X509Certificate(d.payload.certificatePEM);
    f.db.prepare("UPDATE relay_devices SET keyFingerprint=?").run(
      createHash("sha256")
        .update(cert.publicKey.export({ type: "spki", format: "der" }))
        .digest("hex"),
    );
    expect(() => new RelayControl(f!.db, f!.config)).toThrow(
      "contract_migration_required",
    );
  });
});
