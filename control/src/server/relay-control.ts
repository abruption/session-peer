import Database from "better-sqlite3";
import {
  randomBytes,
  randomUUID,
  generateKeyPairSync,
  createPrivateKey,
  createPublicKey,
  type KeyObject,
} from "node:crypto";
import {
  writeFileSync,
  openSync,
  closeSync,
  fsyncSync,
  renameSync,
  unlinkSync,
  readFileSync,
  lstatSync,
  mkdirSync,
  chmodSync,
} from "node:fs";
import { join, resolve } from "node:path";
import { SignJWT } from "jose";
import type { Config } from "./config.js";
import { privateDirectory } from "./storage.js";
import {
  admission,
  assert,
  canonical,
  certificate,
  ControlError,
  fields,
  object,
  principal,
  registration,
  rotation,
  room,
  sha256,
  verifyProof,
  type Registration,
} from "./protocol.js";
interface DeviceRow {
  principal: string;
  userId: string;
  keyFingerprint: string;
  certificateFingerprint: string;
  certificatePEM: string;
  keyGeneration: number;
  name: string;
  revoked: number;
}
interface ChallengeRow {
  id: string;
  userId: string;
  operation: string;
  payload: string;
  message: string;
  expiresAt: number;
}
export class RelayControl {
  private signingKey: KeyObject;
  private kid: string;
  private publicJwk: JsonWebKey;
  private publicDir: string;
  healthy = true;
  constructor(
    private db: Database.Database,
    private config: Config,
    private now: () => number = Date.now,
  ) {
    db.exec(`CREATE TABLE IF NOT EXISTS relay_devices (principal TEXT PRIMARY KEY, userId TEXT NOT NULL, keyFingerprint TEXT NOT NULL, certificateFingerprint TEXT NOT NULL, certificatePEM TEXT NOT NULL, keyGeneration INTEGER NOT NULL, name TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
   CREATE INDEX IF NOT EXISTS relay_devices_owner ON relay_devices(userId);
   CREATE TABLE IF NOT EXISTS relay_challenges (id TEXT PRIMARY KEY,userId TEXT NOT NULL,operation TEXT NOT NULL,payload TEXT NOT NULL,message TEXT NOT NULL,expiresAt INTEGER NOT NULL);
   CREATE INDEX IF NOT EXISTS relay_challenge_expiry ON relay_challenges(expiresAt);
   CREATE TABLE IF NOT EXISTS relay_rotation_receipts (operationId TEXT PRIMARY KEY,userId TEXT NOT NULL,requestHash TEXT NOT NULL,result TEXT NOT NULL);
   CREATE INDEX IF NOT EXISTS relay_rotation_owner ON relay_rotation_receipts(userId);`);
    const privateDir = privateDirectory(config.dataDir);
    const keyPath = join(privateDir, "signing-key.pem");
    try {
      const st = lstatSync(keyPath);
      assert(
        st.isFile() &&
          !st.isSymbolicLink() &&
          st.uid === process.getuid?.() &&
          !(st.mode & 0o077),
        "unsafe_signing_key",
      );
      this.signingKey = createPrivateKey(readFileSync(keyPath));
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
      this.signingKey = generateKeyPairSync("ec", {
        namedCurve: "prime256v1",
      }).privateKey;
      writeFileSync(
        keyPath,
        this.signingKey.export({ format: "pem", type: "pkcs8" }),
        { mode: 0o600, flag: "wx" },
      );
    }
    assert(
      this.signingKey.asymmetricKeyType === "ec" &&
        this.signingKey.asymmetricKeyDetails?.namedCurve === "prime256v1",
      "invalid_signing_key",
    );
    const publicKey = createPublicKey(this.signingKey);
    this.publicJwk = publicKey.export({ format: "jwk" });
    this.kid = sha256(publicKey.export({ format: "der", type: "spki" }));
    this.publicDir = resolve(config.publicDir);
    assert(
      this.publicDir !== privateDir &&
        !this.publicDir.startsWith(privateDir + "/") &&
        !privateDir.startsWith(this.publicDir + "/"),
      "public_private_overlap",
    );
    mkdirSync(this.publicDir, { recursive: true, mode: 0o755 });
    const st = lstatSync(this.publicDir);
    assert(
      st.isDirectory() &&
        !st.isSymbolicLink() &&
        st.uid === process.getuid?.() &&
        !(st.mode & 0o022),
      "unsafe_public_directory",
    );
    this.publish();
  }
  publish() {
    const devices: Record<string, unknown> = {};
    for (const d of this.db
      .prepare("SELECT * FROM relay_devices ORDER BY principal")
      .all() as DeviceRow[])
      devices[d.principal] = {
        userId: d.userId,
        keyFingerprint: d.keyFingerprint,
        generation: d.keyGeneration,
        revoked: !!d.revoked,
      };
    const now = Math.floor(this.now() / 1000);
    const snapshot = {
      schemaVersion: 1,
      issuer: this.config.origin,
      audience: this.config.origin,
      issuedAt: now,
      expiresAt: now + 10,
      jwks: {
        keys: [{ ...this.publicJwk, kid: this.kid, alg: "ES256", use: "sig" }],
      },
      devices,
    };
    const temp = join(this.publicDir, ".state-" + randomUUID());
    const path = join(this.publicDir, "state.json");
    try {
      try {
        assert(!lstatSync(path).isSymbolicLink(), "unsafe_public_state");
      } catch (e) {
        if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
      }
      const fd = openSync(temp, "wx", 0o644);
      try {
        writeFileSync(fd, JSON.stringify(snapshot));
        fsyncSync(fd);
      } finally {
        closeSync(fd);
      }
      chmodSync(temp, 0o644);
      renameSync(temp, path);
      const dirfd = openSync(this.publicDir, "r");
      try {
        fsyncSync(dirfd);
      } finally {
        closeSync(dirfd);
      }
      this.healthy = true;
    } catch (e) {
      this.healthy = false;
      try {
        unlinkSync(temp);
      } catch {}
      throw new ControlError("state_publication_failed", 503);
    }
  }
  list(userId: string) {
    return (
      this.db
        .prepare(
          "SELECT * FROM relay_devices WHERE userId=? ORDER BY name,principal",
        )
        .all(userId) as DeviceRow[]
    ).map((d) => ({
      principal: d.principal,
      name: d.name,
      keyGeneration: d.keyGeneration,
      keyFingerprint: d.keyFingerprint,
      revoked: !!d.revoked,
    }));
  }
  private device(id: string, userId: string, active = true) {
    const d = this.db
      .prepare("SELECT * FROM relay_devices WHERE principal=?")
      .get(id) as DeviceRow | undefined;
    assert(d && d.userId === userId, "device_not_found", 404);
    assert(!active || !d.revoked, "device_revoked", 403);
    return d;
  }
  challenge(userId: string, input: unknown) {
    const o = object(input);
    fields(o, ["operation", "payload"]);
    assert(
      o.operation === "register" ||
        o.operation === "admission" ||
        o.operation === "rotate",
      "invalid_operation",
    );
    const payload =
      o.operation === "register"
        ? registration(o.payload)
        : o.operation === "rotate"
          ? rotation(o.payload)
          : admission(o.payload);
    if (o.operation === "register")
      certificate((payload as Registration).certificatePEM, this.now());
    else if (o.operation === "rotate") {
      const p = rotation(payload);
      this.validateRotation(userId, p);
      assert(
        !this.rotationReceipt(userId, p),
        "operation_already_completed",
        409,
      );
    } else {
      const a = admission(payload);
      this.device(a.devicePrincipal, userId);
      this.device(a.receiverPrincipal, userId);
    }
    this.db
      .prepare("DELETE FROM relay_challenges WHERE expiresAt<=?")
      .run(this.now());
    const count = this.db
      .prepare("SELECT count(*) AS n FROM relay_challenges WHERE userId=?")
      .get(userId) as { n: number };
    assert(count.n < 16, "too_many_challenges", 429);
    const challengeId = randomUUID();
    const nonce = randomBytes(32).toString("base64url");
    const expiresAt = this.now() + 60000;
    const body = canonical(payload);
    const proofMessage = [
      "session-peer-control-v1",
      this.config.origin,
      o.operation,
      challengeId,
      nonce,
      sha256(body),
    ].join("\n");
    this.db
      .prepare("INSERT INTO relay_challenges VALUES (?,?,?,?,?,?)")
      .run(challengeId, userId, o.operation, body, proofMessage, expiresAt);
    return o.operation === "rotate"
      ? {
          challengeId,
          nonce,
          expiresAt,
          proofMessage,
          oldProofMessage: proofMessage + "\nold-key",
          newProofMessage: proofMessage + "\nnew-key",
        }
      : { challengeId, nonce, expiresAt, proofMessage };
  }
  private consume(userId: string, operation: string, input: unknown) {
    const o = object(input);
    assert(
      typeof o.challengeId === "string" && typeof o.proof === "string",
      "invalid_proof",
    );
    const payload = Object.fromEntries(
      Object.entries(o).filter(([k]) => k !== "challengeId" && k !== "proof"),
    );
    operation === "register" ? registration(payload) : admission(payload);
    const c = this.db
      .prepare("SELECT * FROM relay_challenges WHERE id=?")
      .get(o.challengeId) as ChallengeRow | undefined;
    assert(
      c &&
        c.userId === userId &&
        c.operation === operation &&
        c.expiresAt > this.now() &&
        c.payload === canonical(payload),
      "invalid_or_expired_challenge",
    );
    const pem =
      operation === "register"
        ? registration(payload).certificatePEM
        : this.device(admission(payload).devicePrincipal, userId)
            .certificatePEM;
    const cert = certificate(pem, this.now());
    verifyProof(c.message, o.proof, cert.key);
    return { payload, cert, challengeId: c.id };
  }
  register(userId: string, input: unknown) {
    assert(this.healthy, "state_unavailable", 503);
    return this.db.transaction(() => {
      const proof = this.consume(userId, "register", input);
      const p = registration(proof.payload);
      const current = this.db
        .prepare("SELECT * FROM relay_devices WHERE principal=?")
        .get(p.principal) as DeviceRow | undefined;
      if (current)
        assert(
          current.userId === userId &&
            !current.revoked &&
            current.keyGeneration === p.keyGeneration &&
            current.certificateFingerprint ===
              proof.cert.certificateFingerprint,
          "principal_conflict",
          409,
        );
      else {
        const n = this.db
          .prepare("SELECT count(*) AS n FROM relay_devices WHERE userId=?")
          .get(userId) as { n: number };
        assert(n.n < 32, "device_limit", 409);
        this.db
          .prepare("INSERT INTO relay_devices VALUES (?,?,?,?,?,?,?,0)")
          .run(
            p.principal,
            userId,
            proof.cert.keyFingerprint,
            proof.cert.certificateFingerprint,
            p.certificatePEM,
            p.keyGeneration,
            p.name,
          );
      }
      this.db
        .prepare("DELETE FROM relay_challenges WHERE id=?")
        .run(proof.challengeId);
      this.publish();
      return {
        principal: p.principal,
        keyFingerprint: proof.cert.keyFingerprint,
        keyGeneration: p.keyGeneration,
        revoked: false,
      };
    })();
  }
  private rotationReceipt(userId: string, p: ReturnType<typeof rotation>) {
    const row = this.db
      .prepare("SELECT * FROM relay_rotation_receipts WHERE operationId=?")
      .get(p.operationId) as
      { userId: string; requestHash: string; result: string } | undefined;
    if (!row) return undefined;
    assert(
      row.userId === userId && row.requestHash === sha256(canonical(p)),
      "operation_conflict",
      409,
    );
    return JSON.parse(row.result) as {
      operationId: string;
      principal: string;
      keyFingerprint: string;
      keyGeneration: number;
      completed: true;
    };
  }
  private validateRotation(userId: string, p: ReturnType<typeof rotation>) {
    const current = this.device(p.principal, userId);
    assert(
      current.keyGeneration === p.expectedGeneration,
      "generation_conflict",
      409,
    );
    const next = certificate(p.newCertificatePEM, this.now());
    assert(
      next.certificateFingerprint !== current.certificateFingerprint,
      "unchanged_certificate",
      409,
    );
    return { current, next };
  }
  rotate(userId: string, id: string, input: unknown) {
    principal(id);
    assert(this.healthy, "state_unavailable", 503);
    const o = object(input);
    fields(o, [
      "principal",
      "expectedGeneration",
      "newCertificatePEM",
      "operationId",
      "challengeId",
      "oldProof",
      "newProof",
    ]);
    const p = rotation(
      Object.fromEntries(
        Object.entries(o).filter(
          ([k]) => !["challengeId", "oldProof", "newProof"].includes(k),
        ),
      ),
    );
    assert(p.principal === id, "principal_mismatch");
    assert(
      typeof o.challengeId === "string" &&
        typeof o.oldProof === "string" &&
        typeof o.newProof === "string",
      "invalid_proof",
    );
    return this.db.transaction(() => {
      // A completed retry returns a historical receipt only. It cannot modify a
      // device, revive a tombstone, or require reexecution after a lost response.
      this.device(id, userId, false);
      const receipt = this.rotationReceipt(userId, p);
      if (receipt) return receipt;
      const { current, next } = this.validateRotation(userId, p);
      const c = this.db
        .prepare("SELECT * FROM relay_challenges WHERE id=?")
        .get(o.challengeId) as ChallengeRow | undefined;
      assert(
        c &&
          c.userId === userId &&
          c.operation === "rotate" &&
          c.expiresAt > this.now() &&
          c.payload === canonical(p),
        "invalid_or_expired_challenge",
      );
      // An expired stored certificate still identifies the old key for renewal;
      // only this possession check ignores dates. New certs/admission do not.
      verifyProof(
        c.message + "\nold-key",
        o.oldProof,
        certificate(current.certificatePEM, this.now(), false).key,
      );
      verifyProof(c.message + "\nnew-key", o.newProof, next.key);
      const count = this.db
        .prepare(
          "SELECT count(*) AS n FROM relay_rotation_receipts WHERE userId=?",
        )
        .get(userId) as { n: number };
      assert(count.n < 4096, "rotation_receipt_limit", 409);
      const result = {
        operationId: p.operationId,
        principal: id,
        keyFingerprint: next.keyFingerprint,
        keyGeneration: current.keyGeneration + 1,
        completed: true as const,
      };
      this.db
        .prepare(
          "UPDATE relay_devices SET certificatePEM=?,certificateFingerprint=?,keyFingerprint=?,keyGeneration=? WHERE principal=? AND userId=? AND keyGeneration=? AND revoked=0",
        )
        .run(
          p.newCertificatePEM,
          next.certificateFingerprint,
          next.keyFingerprint,
          result.keyGeneration,
          id,
          userId,
          p.expectedGeneration,
        );
      this.db
        .prepare("INSERT INTO relay_rotation_receipts VALUES (?,?,?,?)")
        .run(
          p.operationId,
          userId,
          sha256(canonical(p)),
          JSON.stringify(result),
        );
      // Invalidate outstanding proofs from the old generation, including races.
      this.db
        .prepare("DELETE FROM relay_challenges WHERE userId=?")
        .run(userId);
      this.publish();
      return result;
    })();
  }
  async admit(userId: string, input: unknown) {
    assert(this.healthy, "state_unavailable", 503);
    const result = this.db.transaction(() => {
      const proof = this.consume(userId, "admission", input);
      const a = admission(proof.payload);
      const d = this.device(a.devicePrincipal, userId);
      this.device(a.receiverPrincipal, userId);
      this.db
        .prepare("DELETE FROM relay_challenges WHERE id=?")
        .run(proof.challengeId);
      return { a, d, cert: proof.cert };
    })();
    const now = Math.floor(this.now() / 1000);
    const expiresAt = now + 60;
    const token = await new SignJWT({
      devicePrincipal: result.a.devicePrincipal,
      receiverPrincipal: result.a.receiverPrincipal,
      keyFingerprint: result.d.keyFingerprint,
      keyGeneration: result.d.keyGeneration,
      role: result.a.role,
      room: room(userId, result.a.receiverPrincipal),
      cnf: { jwk: result.cert.jwk },
    })
      .setProtectedHeader({ alg: "ES256", kid: this.kid, typ: "JWT" })
      .setIssuer(this.config.origin)
      .setAudience(this.config.origin)
      .setSubject(userId)
      .setIssuedAt(now)
      .setExpirationTime(expiresAt)
      .setJti(randomUUID())
      .sign(this.signingKey);
    // Revocation may occur while asynchronous crypto runs. Never return an admission
    // for a device or receiver revoked during issuance.
    const current = this.device(result.a.devicePrincipal, userId);
    assert(
      current.keyGeneration === result.d.keyGeneration &&
        current.keyFingerprint === result.d.keyFingerprint,
      "generation_conflict",
      409,
    );
    this.device(result.a.receiverPrincipal, userId);
    assert(this.healthy, "state_unavailable", 503);
    return { token, expiresAt, room: room(userId, result.a.receiverPrincipal) };
  }
  revoke(userId: string, id: string) {
    principal(id);
    assert(this.healthy, "state_unavailable", 503);
    return this.db.transaction(() => {
      this.device(id, userId, false);
      this.db
        .prepare(
          "UPDATE relay_devices SET revoked=1 WHERE principal=? AND userId=?",
        )
        .run(id, userId);
      this.db
        .prepare("DELETE FROM relay_challenges WHERE userId=?")
        .run(userId);
      this.publish();
      return { principal: id, revoked: true };
    })();
  }
}
