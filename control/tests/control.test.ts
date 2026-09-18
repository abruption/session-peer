import { describe, it, expect, afterEach } from "vitest";
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
