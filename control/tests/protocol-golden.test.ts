import { it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { canonical, certificate, registration, room, sha256, verifyProof } from "../src/server/protocol.js";

// Generated independently using Python json/hashlib and OpenSSL. Contains only
// synthetic payloads, public certificates and DER signatures; no private keys.
const golden = JSON.parse(readFileSync(new URL("./fixtures/control-contract-golden.json", import.meta.url), "utf8"));

it("matches shared zero-based certificate/proof/room golden vectors", () => {
  expect(room(golden.userId, golden.initial.payload.principal)).toBe(golden.room);
  const original = certificate(golden.initial.payload.certificatePEM, 0, false);
  const replacement = certificate(golden.rotation.payload.certificatePEM, 0, false);
  expect(original.keyFingerprint).toBe(golden.initial.payload.principal);
  expect(replacement.keyFingerprint).not.toBe(golden.rotation.payload.principal);
  expect(golden.rotation.payload.principal).toBe(golden.initial.payload.principal);
  for (const vector of [golden.initial, golden.rotation]) {
    expect(registration(vector.payload)).toEqual(vector.payload);
    const c = vector.challenge;
    expect(c.proofMessage).toBe([
      "session-peer-control-v1:", golden.origin, "register", c.challengeId,
      c.nonce, sha256(canonical(vector.payload)),
    ].join("\n"));
    expect(c.expiresAt - c.issuedAt).toBe(60);
    expect(() => verifyProof(c.proofMessage, vector.proof, vector === golden.initial ? original.key : replacement.key)).not.toThrow();
  }
  expect(() => verifyProof(golden.rotation.challenge.proofMessage, golden.rotation.previousKeyProof, original.key)).not.toThrow();
  expect(() => verifyProof(golden.rotation.challenge.proofMessage + "\n", golden.rotation.proof, replacement.key)).toThrow("invalid_proof");
});
