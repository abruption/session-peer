import { afterEach, expect, it, vi } from "vitest";
import { generateKeyPairSync } from "node:crypto";
import { existsSync, readFileSync, statSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { SignJWT } from "jose";
import { fixture } from "./fixtures.js";
import { loadConfig } from "../src/server/config.js";

let f: Awaited<ReturnType<typeof fixture>> | undefined;
let idToken: string;
let signing: ReturnType<typeof generateKeyPairSync>;
const credentials = { clientId: "discovery-fixture-client", clientSecret: "discovery-fixture-secret" };
const expectedEmail = "owner@test.invalid"; // Existing GitHub user's email is intentional.
afterEach(() => { vi.unstubAllGlobals(); f?.cleanup(); f = undefined; });

async function token(claims: Record<string, unknown> = {}, wrongKey = false) {
  idToken = await new SignJWT({ sub: "verified-google-subject", email: expectedEmail,
    email_verified: true, name: "Fixture", aud: credentials.clientId,
    iss: "https://accounts.google.com", iat: Math.floor(Date.now()/1000),
    exp: Math.floor(Date.now()/1000)+300, ...claims })
    .setProtectedHeader({ alg: "RS256", kid: "fixture-key" })
    .sign(wrongKey ? generateKeyPairSync("rsa", { modulusLength: 2048 }).privateKey : signing.privateKey);
}

async function setup() {
  f = await fixture({ providers: { google: credentials },
    googleDiscovery: { expectedEmail, expiresAt: Math.floor(Date.now()/1000)+600 } });
  signing = generateKeyPairSync("rsa", { modulusLength: 2048 });
  await token();
  const network = vi.fn(async (input: string | URL | Request) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url === "https://oauth2.googleapis.com/token")
      return Response.json({ access_token: "fixture-access", token_type: "bearer", expires_in: 300, id_token: idToken });
    if (url === "https://www.googleapis.com/oauth2/v3/certs")
      return Response.json({ keys: [{ ...signing.publicKey.export({ format: "jwk" }),
        kid: "fixture-key", alg: "RS256", use: "sig" }] });
    throw new Error("unexpected_fixture_network");
  });
  vi.stubGlobal("fetch", network);
  return network;
}

function counts() {
  return ["user", "account", "session", "relay_devices"].map(table =>
    (f!.db.prepare(`SELECT COUNT(*) AS n FROM "${table}"`).get() as { n: number }).n);
}
function file() { return join(f!.config.dataDir, "google-account-discovery.json"); }
async function callback(tamperedState = false) {
  const start = await f!.request("/api/auth/sign-in/social", {
    provider: "google", callbackURL: "/devices",
  }, { origin: f!.config.origin });
  expect(start.status).toBe(200);
  const url = new URL((await start.json()).url);
  expect(url.searchParams.get("code_challenge_method")).toBe("S256");
  const cookie = start.headers.getSetCookie().map(c => c.split(";")[0]).join("; ");
  const state = tamperedState ? "tampered-state" : url.searchParams.get("state")!;
  const response = await f!.request("/api/auth/callback/google?code=fixture-code&state="+
    encodeURIComponent(state), undefined, { cookie });
  expect(response.status).toBe(302);
  expect(response.headers.get("location")).not.toBe("/devices");
  return response;
}

it("captures only a verified subject before email linking, without creating an account or session", async () => {
  await setup();
  const before = counts();
  await callback();
  const record = JSON.parse(readFileSync(file(), "utf8"));
  expect(record.accountId).toBe("verified-google-subject");
  expect(record.provider).toBe("google");
  expect(record.expectedEmail).toBe(expectedEmail);
  expect(statSync(file()).mode & 0o777).toBe(0o600);
  expect(statSync(f!.config.dataDir).mode & 0o777).toBe(0o700);
  expect(Object.keys(record).sort()).toEqual(["accountId", "clientId", "expectedEmail", "issuer", "provider", "schemaVersion", "verifiedAt"].sort());
  expect(readFileSync(file(), "utf8")).not.toContain(idToken);
  expect(counts()).toEqual(before);
});

it.each([
  { name: "audience", claims: { aud: "different-client" }, wrongKey: false },
  { name: "issuer", claims: { iss: "https://other.invalid" }, wrongKey: false },
  { name: "expiry", claims: { exp: 1 }, wrongKey: false },
  { name: "email verification", claims: { email_verified: false }, wrongKey: false },
  { name: "email", claims: { email: "someone-else@test.invalid" }, wrongKey: false },
  { name: "signature", claims: {}, wrongKey: true },
])("rejects invalid $name without discovery or login", async ({ claims, wrongKey }) => {
  await setup();
  const before = counts();
  await token(claims, wrongKey);
  await callback();
  expect(existsSync(file())).toBe(false);
  expect(counts()).toEqual(before);
});

it("rejects tampered state before provider exchange and never captures direct ID-token input", async () => {
  const network = await setup();
  const before = counts();
  await callback(true);
  expect(network).not.toHaveBeenCalled();
  await f!.request("/api/auth/sign-in/social", {
    provider: "google", idToken: { token: idToken }, callbackURL: "/devices",
  }, { origin: f!.config.origin });
  expect(existsSync(file())).toBe(false);
  expect(counts()).toEqual(before);
});

it("never overwrites a captured subject on another authenticated callback", async () => {
  await setup();
  await callback();
  const first = readFileSync(file(), "utf8");
  await token({ sub: "different-subject" });
  await callback();
  expect(readFileSync(file(), "utf8")).toBe(first);
});

it("cannot grant access when discovery expired or its file cannot be created", async () => {
  await setup();
  const before = counts();
  f!.config.googleDiscovery!.expiresAt = 1;
  await callback();
  expect(existsSync(file())).toBe(false);
  f!.config.googleDiscovery!.expiresAt = Math.floor(Date.now()/1000)+60;
  mkdirSync(file(), { mode: 0o700 });
  await callback();
  expect(statSync(file()).isDirectory()).toBe(true);
  expect(counts()).toEqual(before);
});

it("requires an explicit enabled Google provider, exact email and bounded future deadline", () => {
  const base = { BETTER_AUTH_SECRET: "test-only-secret-0000000000000000000000000",
    GOOGLE_CLIENT_ID: credentials.clientId, GOOGLE_CLIENT_SECRET: credentials.clientSecret,
    SESSION_PEER_GOOGLE_DISCOVERY_EMAIL: expectedEmail,
    SESSION_PEER_GOOGLE_DISCOVERY_UNTIL: String(Math.floor(Date.now()/1000)+600) };
  expect(loadConfig(base).googleDiscovery?.expectedEmail).toBe(expectedEmail);
  for (const override of [{ SESSION_PEER_GOOGLE_DISCOVERY_UNTIL: "" },
    { SESSION_PEER_GOOGLE_DISCOVERY_UNTIL: "1" },
    { SESSION_PEER_GOOGLE_DISCOVERY_UNTIL: String(Math.floor(Date.now()/1000)+3600) },
    { SESSION_PEER_GOOGLE_DISCOVERY_EMAIL: "invalid" }])
    expect(() => loadConfig({ ...base, ...override })).toThrow("invalid_google_discovery_configuration");
  expect(loadConfig({ BETTER_AUTH_SECRET: base.BETTER_AUTH_SECRET }).googleDiscovery).toBeUndefined();
});
