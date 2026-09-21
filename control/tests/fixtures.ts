import { mkdtempSync, readFileSync, rmSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { sign, createPrivateKey, randomUUID } from "node:crypto";
import { serializeSignedCookie } from "better-call";
import { getMigrations } from "better-auth/db/migration";
import { openDatabase } from "../src/server/storage.js";
import { createAuth } from "../src/server/auth.js";
import { RelayControl } from "../src/server/relay-control.js";
import { createApp } from "../src/server/app.js";
import type { Config } from "../src/server/config.js";
import type { Registration } from "../src/server/protocol.js";
import { certificate } from "../src/server/protocol.js";
import { runFirstPartyMigrations } from "../src/server/migrations.js";
export function identity(
  root: string,
  name: string,
  _character: string,
  days = 2,
) {
  const key = join(root, name + ".key");
  const cert = join(root, name + ".crt");
  execFileSync(
    "openssl",
    [
      "req",
      "-x509",
      "-newkey",
      "ec",
      "-pkeyopt",
      "ec_paramgen_curve:P-256",
      "-nodes",
      "-keyout",
      key,
      "-out",
      cert,
      "-subj",
      "/CN=fixture",
      "-days",
      String(days),
    ],
    { stdio: "pipe" },
  );
  const privateKey = createPrivateKey(readFileSync(key));
  const payload: Registration = {
    principal: certificate(readFileSync(cert, "utf8")).certificateFingerprint,
    certificatePEM: readFileSync(cert, "utf8"),
    keyGeneration: 0,
    name,
    operationId: randomUUID(),
  };
  return { payload, privateKey };
}
let fixtureCounter = 0;
export async function fixture(overrides: Partial<Config> = {}) {
  const testIP = "192.0.2." + ++fixtureCounter;
  const root = mkdtempSync(join(tmpdir(), "sp-control-"));
  mkdirSync(join(root, "private"), { mode: 0o700 });
  const config: Config = {
    origin: "https://relay.test",
    production: true,
    secret: "test-only-local-secret-never-production-000000",
    dataDir: join(root, "private"),
    publicDir: join(root, "public"),
    publicSignupEnabled: false,
    providers: {},
    allowlist: [
      { provider: "github", accountId: "fixture-owner" },
      { provider: "google", accountId: "fixture-other" },
    ],
    ...overrides,
  };
  const db = openDatabase(config.dataDir);
  const auth = createAuth(db, config);
  await (await getMigrations(auth.options)).runMigrations();
  runFirstPartyMigrations(db);
  const context = await auth.$context;
  const owner = await context.internalAdapter.createUser(
    { name: "Owner", email: "owner@test.invalid", emailVerified: true },
    { method: "admin" },
  );
  const other = await context.internalAdapter.createUser(
    { name: "Other", email: "other@test.invalid", emailVerified: true },
    { method: "admin" },
  );
  await context.internalAdapter.createAccount({
    userId: owner.id,
    providerId: "github",
    accountId: "fixture-owner",
  });
  await context.internalAdapter.createAccount({
    userId: other.id,
    providerId: "google",
    accountId: "fixture-other",
  });
  const session = await context.internalAdapter.createSession(owner.id);
  const otherSession = await context.internalAdapter.createSession(other.id);
  if (!session || !otherSession) throw new Error("fixture_session");
  const cookie = (
    await serializeSignedCookie(
      context.authCookies.sessionToken.name,
      session.token,
      config.secret,
    )
  ).split(";")[0];
  let offset = 0;
  const control = new RelayControl(db, config, () => Date.now() + offset);
  const app = createApp(auth, db, control, config, root);
  const ownerHeaders = { authorization: `Bearer ${session.token}` };
  const otherHeaders = { authorization: `Bearer ${otherSession.token}` };
  async function request(
    path: string,
    body?: unknown,
    headers: Record<string, string> = ownerHeaders,
    method?: string,
  ) {
    return app(
      new Request(config.origin + path, {
        method: method ?? (body === undefined ? "GET" : "POST"),
        headers: {
          "x-session-peer-ip": testIP,
          ...headers,
          ...(body === undefined ? {} : { "content-type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    );
  }
  function proven(
    userId: string,
    operation: string,
    payload: unknown,
    key: Parameters<typeof sign>[2],
  ) {
    const c = control.challenge(userId, { operation, payload });
    return {
      ...(payload as object),
      challengeId: c.challengeId,
      proof: sign("sha256", Buffer.from(c.proofMessage), key).toString(
        "base64url",
      ),
    };
  }
  function rotated(
    userId: string,
    payload: unknown,
    oldKey: Parameters<typeof sign>[2],
    newKey: Parameters<typeof sign>[2],
  ) {
    const c = control.challenge(userId, { operation: "register", payload });
    return {
      ...(payload as object),
      challengeId: c.challengeId,
      previousKeyProof: sign(
        "sha256",
        Buffer.from(c.proofMessage),
        oldKey,
      ).toString("base64url"),
      proof: sign("sha256", Buffer.from(c.proofMessage), newKey).toString(
        "base64url",
      ),
    };
  }
  return {
    rotated,
    root,
    config,
    db,
    auth,
    context,
    control,
    app,
    owner,
    other,
    ownerHeaders,
    otherHeaders,
    cookie,
    request,
    proven,
    advance: (ms: number) => {
      offset += ms;
    },
    cleanup: () => {
      db.close();
      rmSync(root, { recursive: true, force: true });
    },
  };
}
