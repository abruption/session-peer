import { describe, it, expect, afterEach } from "vitest";
import { randomUUID, sign } from "node:crypto";
import { readFileSync, renameSync } from "node:fs";
import { join } from "node:path";
import { importJWK, jwtVerify } from "jose";
import { fixture, identity } from "./fixtures.js";
import { certificate, room } from "../src/server/protocol.js";
let f: Awaited<ReturnType<typeof fixture>> | undefined;
afterEach(() => {
  f?.cleanup();
  f = undefined;
});
describe("relay device boundary", () => {
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
    expect(verified.payload.exp! - verified.payload.iat!).toBe(60);
    expect(verified.payload.room).toBe(room(f.owner.id, r.payload.principal));
    expect((verified.payload.cnf as any).jwk.d).toBeUndefined();
    expect(state.devices[d.payload.principal].keyFingerprint).toBe(
      certificate(d.payload.certificatePEM).keyFingerprint,
    );
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
    ).toThrow("invalid_or_expired_challenge");
    expect(() => f!.control.register(f!.other.id, req)).toThrow(
      "invalid_or_expired_challenge",
    );
    expect(() =>
      f!.control.register(f!.owner.id, { ...req, proof: "bad" }),
    ).toThrow("invalid_proof");
    f.control.register(f.owner.id, req);
    expect(() => f!.control.register(f!.owner.id, req)).toThrow(
      "invalid_or_expired_challenge",
    );
    const late = f.proven(f.owner.id, "register", d.payload, d.privateKey);
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
        f!.proven(f!.other.id, "register", d.payload, d.privateKey),
      ),
    ).toThrow("principal_conflict");
    const replacement = {
      ...alternate.payload,
      principal: d.payload.principal,
      keyGeneration: 2,
    };
    expect(() =>
      f!.control.register(
        f!.owner.id,
        f!.proven(f!.owner.id, "register", replacement, alternate.privateKey),
      ),
    ).toThrow("principal_conflict");
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
        f!.proven(f!.owner.id, "register", d.payload, d.privateKey),
      ),
    ).toThrow("principal_conflict");
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

describe("same-principal rotation", () => {
  async function setup() {
    f = await fixture();
    const old = identity(f.root, "Old", "a");
    const next = identity(f.root, "New", "b", 10);
    f.control.register(
      f.owner.id,
      f.proven(f.owner.id, "register", old.payload, old.privateKey),
    );
    const payload = {
      principal: old.payload.principal,
      expectedGeneration: 1,
      newCertificatePEM: next.payload.certificatePEM,
      operationId: randomUUID(),
    };
    return { old, next, payload };
  }
  it("requires both keys, increments once, keeps identity/owner/name and reconciles a lost response", async () => {
    const { old, next, payload } = await setup();
    const req = f!.rotated(
      f!.owner.id,
      payload,
      old.privateKey,
      next.privateKey,
    );
    const receipt = f!.control.rotate(f!.owner.id, payload.principal, req);
    expect(receipt.keyGeneration).toBe(2);
    expect(f!.control.rotate(f!.owner.id, payload.principal, req)).toEqual(
      receipt,
    );
    expect(f!.control.list(f!.owner.id)[0]).toMatchObject({
      principal: payload.principal,
      name: "Old",
      keyGeneration: 2,
      revoked: false,
      keyFingerprint: certificate(next.payload.certificatePEM).keyFingerprint,
    });
    expect(f!.control.list(f!.other.id)).toEqual([]);
    expect(
      (
        f!.db
          .prepare("SELECT count(*) n FROM relay_rotation_receipts")
          .get() as any
      ).n,
    ).toBe(1);
    const state = JSON.parse(
      readFileSync(join(f!.config.publicDir, "state.json"), "utf8"),
    );
    expect(state.devices[payload.principal].generation).toBe(2);
    const a = {
      role: "receiver",
      devicePrincipal: payload.principal,
      receiverPrincipal: payload.principal,
    };
    const wrong = f!.proven(f!.owner.id, "admission", a, old.privateKey);
    await expect(f!.control.admit(f!.owner.id, wrong)).rejects.toThrow(
      "invalid_proof",
    );
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
  it("rejects login-only replacement, swapped proof domains, payload changes, wrong owner and route", async () => {
    const { old, next, payload } = await setup();
    const req = f!.rotated(
      f!.owner.id,
      payload,
      old.privateKey,
      next.privateKey,
    );
    for (const bad of [
      { ...req, oldProof: "bad" },
      { ...req, newProof: "bad" },
      { ...req, oldProof: req.newProof, newProof: req.oldProof },
    ])
      expect(() =>
        f!.control.rotate(f!.owner.id, payload.principal, bad),
      ).toThrow("invalid_proof");
    expect(() =>
      f!.control.rotate(f!.other.id, payload.principal, req),
    ).toThrow("device_not_found");
    expect(() =>
      f!.control.rotate(f!.owner.id, next.payload.principal, req),
    ).toThrow("principal_mismatch");
    expect(() =>
      f!.control.rotate(f!.owner.id, payload.principal, {
        ...req,
        operationId: randomUUID(),
      }),
    ).toThrow("invalid_or_expired_challenge");
    const c = f!.control.challenge(f!.owner.id, {
      operation: "rotate",
      payload,
    });
    const undomained = sign(
      "sha256",
      Buffer.from(c.proofMessage),
      old.privateKey,
    ).toString("base64url");
    expect(() =>
      f!.control.rotate(f!.owner.id, payload.principal, {
        ...req,
        challengeId: c.challengeId,
        oldProof: undomained,
      }),
    ).toThrow("invalid_proof");
    expect(f!.control.list(f!.owner.id)[0].keyGeneration).toBe(1);
  });
  it("rejects stale generation, conflicting operation ID, expired challenges and revoked retries without revival", async () => {
    const { old, next, payload } = await setup();
    const req = f!.rotated(
      f!.owner.id,
      payload,
      old.privateKey,
      next.privateKey,
    );
    const receipt = f!.control.rotate(f!.owner.id, payload.principal, req);
    expect(() =>
      f!.control.rotate(f!.owner.id, payload.principal, {
        ...req,
        expectedGeneration: 2,
      }),
    ).toThrow("operation_conflict");
    expect(() =>
      f!.control.challenge(f!.owner.id, {
        operation: "rotate",
        payload: { ...payload, operationId: randomUUID() },
      }),
    ).toThrow("generation_conflict");
    const later = {
      ...payload,
      expectedGeneration: 2,
      newCertificatePEM: old.payload.certificatePEM,
      operationId: randomUUID(),
    };
    const late = f!.rotated(
      f!.owner.id,
      later,
      next.privateKey,
      old.privateKey,
    );
    f!.advance(60001);
    expect(() =>
      f!.control.rotate(f!.owner.id, payload.principal, late),
    ).toThrow("invalid_or_expired_challenge");
    f!.control.revoke(f!.owner.id, payload.principal);
    expect(f!.control.rotate(f!.owner.id, payload.principal, req)).toEqual(
      receipt,
    );
    expect(f!.control.list(f!.owner.id)[0].revoked).toBe(true);
    expect(() =>
      f!.control.rotate(f!.owner.id, payload.principal, late),
    ).toThrow("device_revoked");
    expect(() =>
      f!.control.challenge(f!.owner.id, {
        operation: "rotate",
        payload: later,
      }),
    ).toThrow("device_revoked");
    const state = JSON.parse(
      readFileSync(join(f!.config.publicDir, "state.json"), "utf8"),
    );
    expect(state.devices[payload.principal].revoked).toBe(true);
  });
  it("renews an expired stored certificate using its old key but requires a valid replacement", async () => {
    const { old, next, payload } = await setup();
    f!.advance(3 * 86400000);
    expect(() =>
      f!.control.challenge(f!.owner.id, {
        operation: "rotate",
        payload: { ...payload, newCertificatePEM: old.payload.certificatePEM },
      }),
    ).toThrow("certificate_expired_or_not_valid");
    const req = f!.rotated(
      f!.owner.id,
      payload,
      old.privateKey,
      next.privateKey,
    );
    expect(
      f!.control.rotate(f!.owner.id, payload.principal, req).keyGeneration,
    ).toBe(2);
  });
  it("invalidates old outstanding challenges and refuses admission issued across a rotation", async () => {
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
    f!.control.rotate(
      f!.owner.id,
      payload.principal,
      f!.rotated(f!.owner.id, payload, old.privateKey, next.privateKey),
    );
    await expect(racing).rejects.toThrow("generation_conflict");
    await expect(f!.control.admit(f!.owner.id, waiting)).rejects.toThrow(
      "invalid_or_expired_challenge",
    );
  });
  it("rolls back rotation and its receipt on publication failure", async () => {
    const { old, next, payload } = await setup();
    const req = f!.rotated(
      f!.owner.id,
      payload,
      old.privateKey,
      next.privateKey,
    );
    renameSync(f!.config.publicDir, f!.config.publicDir + "-away");
    expect(() =>
      f!.control.rotate(f!.owner.id, payload.principal, req),
    ).toThrow("state_publication_failed");
    expect(f!.control.list(f!.owner.id)[0].keyGeneration).toBe(1);
    expect(
      (
        f!.db
          .prepare("SELECT count(*) n FROM relay_rotation_receipts")
          .get() as any
      ).n,
    ).toBe(0);
    expect(f!.control.healthy).toBe(false);
  });
});
