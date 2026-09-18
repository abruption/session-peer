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
  fchmodSync,
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
  operationId,
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
   CREATE TABLE IF NOT EXISTS relay_operations (operationId TEXT PRIMARY KEY,userId TEXT NOT NULL,requestHash TEXT NOT NULL,result TEXT);
   CREATE INDEX IF NOT EXISTS relay_operations_owner ON relay_operations(userId);
   CREATE TABLE IF NOT EXISTS relay_state_revision (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision>=0 AND revision<=9007199254740991));
   INSERT OR IGNORE INTO relay_state_revision VALUES (1,0);`);
    // Earlier unpublished candidates stored an SPKI hash under keyFingerprint.
    // Never reinterpret old live state/receipts silently as certificate DER.
    const legacy = db
      .prepare(
        "SELECT count(*) AS n FROM relay_devices WHERE keyFingerprint<>certificateFingerprint",
      )
      .get() as { n: number };
    assert(legacy.n === 0, "contract_migration_required", 503);
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
    // mkdir's mode is filtered by the service umask. Only this validated
    // public directory is readable across DynamicUser identities.
    chmodSync(this.publicDir, 0o755);
    this.publish();
  }
  publish() {
    this.publishRevision(this.reserveStateRevision());
  }
  private reserveStateRevision(): number {
    try {
      // Commit reservations independently of device mutations. A publication
      // can become visible before a later mutation/file failure; never reuse
      // that revision with a different payload after rollback or restart.
      assert(!this.db.inTransaction, "revision_transaction_overlap", 503);
      return this.db.transaction(() => {
        const row = this.db
          .prepare("SELECT revision FROM relay_state_revision WHERE id=1")
          .get() as { revision: number } | undefined;
        assert(
          row && Number.isSafeInteger(row.revision) && row.revision >= 0 &&
            row.revision < Number.MAX_SAFE_INTEGER,
          "state_revision_exhausted",
          503,
        );
        const revision = row.revision + 1;
        this.db
          .prepare("UPDATE relay_state_revision SET revision=? WHERE id=1")
          .run(revision);
        return revision;
      }).immediate();
    } catch {
      this.healthy = false;
      throw new ControlError("state_publication_failed", 503);
    }
  }
  private publishRevision(revision: number) {
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
      revision,
      issuer: this.config.origin,
      audience: this.config.origin,
      issuedAt: now,
      expiresAt: now + 180,
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
        fchmodSync(fd, 0o644);
        fsyncSync(fd);
      } finally {
        closeSync(fd);
      }
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
  private operationRecord(userId: string, p: Registration) {
    const row = this.db
      .prepare("SELECT * FROM relay_operations WHERE operationId=?")
      .get(p.operationId) as
      | { userId: string; requestHash: string; result: string | null }
      | undefined;
    if (row)
      assert(
        row.userId === userId && row.requestHash === sha256(canonical(p)),
        "operation_conflict",
        409,
      );
    return row;
  }
  private reserveOperation(userId: string, p: Registration) {
    const row = this.operationRecord(userId, p);
    if (row) {
      assert(row.result === null, "operation_already_committed", 409);
      return;
    }
    const count = this.db
      .prepare("SELECT count(*) AS n FROM relay_operations WHERE userId=?")
      .get(userId) as { n: number };
    assert(count.n < 4096, "operation_limit", 409);
    this.db
      .prepare("INSERT INTO relay_operations VALUES (?,?,?,NULL)")
      .run(p.operationId, userId, sha256(canonical(p)));
  }
  operation(userId: string, id: string) {
    operationId(id);
    const row = this.db
      .prepare(
        "SELECT result FROM relay_operations WHERE operationId=? AND userId=?",
      )
      .get(id, userId) as { result: string | null } | undefined;
    // Identical response for an absent ID and another owner's ID.
    assert(row, "operation_not_found", 404);
    return row.result === null
      ? { operationId: id, committed: false }
      : JSON.parse(row.result);
  }
  private validateRegistration(userId: string, p: Registration) {
    assert(p.keyGeneration === p.expectedGeneration + 1, "invalid_generation");
    const current = this.db
      .prepare("SELECT * FROM relay_devices WHERE principal=?")
      .get(p.principal) as DeviceRow | undefined;
    if (current) {
      assert(current.userId === userId, "device_not_found", 404);
      assert(!current.revoked, "device_revoked", 403);
      assert(
        current.keyGeneration === p.expectedGeneration,
        "generation_conflict",
        409,
      );
    } else assert(p.expectedGeneration === 0, "generation_conflict", 409);
    const next = certificate(p.certificatePEM, this.now());
    assert(
      !current ||
        next.certificateFingerprint !== current.certificateFingerprint,
      "unchanged_certificate",
      409,
    );
    return { current, next };
  }
  challenge(userId: string, input: unknown) {
    const o = object(input);
    fields(o, ["operation", "payload"]);
    assert(
      o.operation === "register" || o.operation === "admission",
      "invalid_operation",
    );
    const payload =
      o.operation === "register"
        ? registration(o.payload)
        : admission(o.payload);
    if (o.operation === "register") {
      const p = registration(payload);
      const row = this.operationRecord(userId, p);
      assert(!row?.result, "operation_already_committed", 409);
      this.validateRegistration(userId, p);
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
    const issuedAt = Math.floor(this.now() / 1000);
    const expiresAt = issuedAt + 60;
    const body = canonical(payload);
    const proofMessage = [
      "session-peer-control-v1:",
      this.config.origin,
      o.operation,
      challengeId,
      nonce,
      sha256(body),
    ].join("\n");
    this.db.transaction(() => {
      if (o.operation === "register")
        this.reserveOperation(userId, registration(payload));
      this.db
        .prepare("INSERT INTO relay_challenges VALUES (?,?,?,?,?,?)")
        .run(
          challengeId,
          userId,
          o.operation,
          body,
          proofMessage,
          expiresAt * 1000,
        );
    })();
    return { challengeId, nonce, issuedAt, expiresAt, proofMessage };
  }
  private consume(userId: string, operation: string, input: unknown) {
    const o = object(input);
    assert(
      typeof o.challengeId === "string" && typeof o.proof === "string",
      "invalid_proof",
    );
    const excluded =
      operation === "register"
        ? ["challengeId", "proof", "previousKeyProof"]
        : ["challengeId", "proof"];
    const payload = Object.fromEntries(
      Object.entries(o).filter(([k]) => !excluded.includes(k)),
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
    return { payload, cert, challengeId: c.id, proofMessage: c.message };
  }
  register(userId: string, input: unknown) {
    assert(this.healthy, "state_unavailable", 503);
    const o = object(input);
    fields(o, [
      "principal",
      "certificatePEM",
      "keyGeneration",
      "name",
      "operationId",
      "expectedGeneration",
      "challengeId",
      "proof",
      ...(Object.hasOwn(o, "previousKeyProof") ? ["previousKeyProof"] : []),
    ]);
    const p = registration(
      Object.fromEntries(
        Object.entries(o).filter(
          ([k]) => !["challengeId", "proof", "previousKeyProof"].includes(k),
        ),
      ),
    );
    assert(
      typeof o.challengeId === "string" &&
        typeof o.proof === "string" &&
        (!Object.hasOwn(o, "previousKeyProof") ||
          typeof o.previousKeyProof === "string"),
      "invalid_proof",
    );
    const existing = this.operationRecord(userId, p);
    assert(existing, "operation_not_found", 404);
    if (existing.result !== null) return JSON.parse(existing.result);
    const revision = this.reserveStateRevision();
    return this.db.transaction(() => {
      const row = this.operationRecord(userId, p);
      assert(row, "operation_not_found", 404);
      // Historical receipt only: no new mutation, proof reexecution or revival.
      if (row.result !== null) return JSON.parse(row.result);
      const { current, next } = this.validateRegistration(userId, p);
      const proof = this.consume(userId, "register", o);
      if (current) {
        assert(
          typeof o.previousKeyProof === "string",
          "previous_key_proof_required",
        );
        // Only the old stored certificate possession check ignores expiry.
        verifyProof(
          proof.proofMessage,
          o.previousKeyProof,
          certificate(current.certificatePEM, this.now(), false).key,
        );
        const changed = this.db
          .prepare(
            "UPDATE relay_devices SET certificatePEM=?,certificateFingerprint=?,keyFingerprint=?,keyGeneration=? WHERE principal=? AND userId=? AND keyGeneration=? AND revoked=0",
          )
          .run(
            p.certificatePEM,
            next.certificateFingerprint,
            next.keyFingerprint,
            p.expectedGeneration + 1,
            p.principal,
            userId,
            p.expectedGeneration,
          );
        assert(changed.changes === 1, "generation_conflict", 409);
        this.db
          .prepare("DELETE FROM relay_challenges WHERE userId=?")
          .run(userId);
      } else {
        assert(
          !Object.hasOwn(o, "previousKeyProof"),
          "unexpected_previous_key_proof",
        );
        const n = this.db
          .prepare("SELECT count(*) AS n FROM relay_devices WHERE userId=?")
          .get(userId) as { n: number };
        assert(n.n < 32, "device_limit", 409);
        this.db
          .prepare("INSERT INTO relay_devices VALUES (?,?,?,?,?,?,?,0)")
          .run(
            p.principal,
            userId,
            next.keyFingerprint,
            next.certificateFingerprint,
            p.certificatePEM,
            1,
            p.name,
          );
        this.db
          .prepare("DELETE FROM relay_challenges WHERE id=?")
          .run(proof.challengeId);
      }
      const result = {
        operationId: p.operationId,
        committed: true,
        principal: p.principal,
        keyFingerprint: next.keyFingerprint,
        keyGeneration: p.expectedGeneration + 1,
      };
      this.db
        .prepare(
          "UPDATE relay_operations SET result=? WHERE operationId=? AND userId=?",
        )
        .run(JSON.stringify(result), p.operationId, userId);
      this.publishRevision(revision);
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
    this.device(id, userId, false);
    const revision = this.reserveStateRevision();
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
      this.publishRevision(revision);
      return { principal: id, revoked: true };
    })();
  }
}
