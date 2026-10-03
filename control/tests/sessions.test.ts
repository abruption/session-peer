import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, expect, it } from "vitest";
import { betterAuth } from "better-auth";
import { bearer } from "better-auth/plugins";
import { capExistingSessions, SESSION_LIFETIME_SECONDS } from "../src/server/auth.js";
import { createApp } from "../src/server/app.js";
import { fixture } from "./fixtures.js";

let f: Awaited<ReturnType<typeof fixture>> | undefined;
afterEach(() => { f?.cleanup(); f = undefined; });
function ageSession(id: string, hours: number, remaining = 1) {
  f!.db.prepare("UPDATE session SET createdAt=?,updatedAt=?,expiresAt=? WHERE id=?").run(
    new Date(Date.now() - hours * 3600_000).toISOString(),
    new Date(Date.now() - hours * 3600_000).toISOString(),
    new Date(Date.now() + remaining * 3600_000).toISOString(), id,
  );
}
function row(id: string) {
  return f!.db.prepare("SELECT id,createdAt,expiresAt FROM session WHERE id=?").get(id) as
    { id: string; createdAt: string; expiresAt: string };
}
async function ownerSession() {
  return (await f!.auth.api.getSession({ headers: new Headers(f!.ownerHeaders) }))!.session;
}
function browser() { return { cookie: f!.cookie, origin: f!.config.origin }; }

it("pins the Better Auth baseline: bearer getSession, auth HTTP and relay requests slide a 1h remainder to 24h", async () => {
  const lock = JSON.parse(readFileSync(resolve("package-lock.json"), "utf8"));
  expect(lock.packages["node_modules/better-auth"].version).toBe("1.7.5");
  f = await fixture();
  const session = await ownerSession();
  const baseline = betterAuth({ database: f.db, baseURL: f.config.origin,
    basePath: "/api/auth", secret: f.config.secret,
    session: { expiresIn: 86400, updateAge: 3600, cookieCache: { enabled: false } },
    plugins: [bearer()], logger: { disabled: true },
  });
  const app = createApp(baseline as unknown as typeof f.auth, f.db, f.control, f.config, f.root);
  for (const path of [null, "/api/auth/get-session", "/api/relay/devices"]) {
    ageSession(session.id, 23);
    if (path) expect((await app(new Request(f.config.origin + path, { headers: f.ownerHeaders }))).status).toBe(200);
    else expect(await baseline.api.getSession({ headers: new Headers(f.ownerHeaders) })).toBeTruthy();
    expect(Date.parse(row(session.id).expiresAt) - Date.now()).toBeGreaterThan(23.9 * 3600_000);
  }
});

it("caps existing sliding sessions by creation, preserves earlier expiry and rejects renewal on every auth entrypoint", async () => {
  f = await fixture();
  const session = await ownerSession();
  const shorter = await f.context.internalAdapter.createSession(f.owner.id);
  ageSession(session.id, 23, 24);
  const earlier = row(shorter!.id).expiresAt;
  capExistingSessions(f.db);
  const capped = row(session.id).expiresAt;
  expect(Date.parse(capped) - Date.parse(row(session.id).createdAt)).toBe(SESSION_LIFETIME_SECONDS * 1000);
  expect(row(shorter!.id).expiresAt).toBe(earlier);
  for (const headers of [f.ownerHeaders, browser()]) {
    expect(await f.auth.api.getSession({ headers: new Headers(headers) })).toBeTruthy();
    expect((await f.request("/api/auth/get-session", undefined, headers)).status).toBe(200);
    expect((await f.request("/api/relay/devices", undefined, headers)).status).toBe(200);
    expect((await f.request("/api/control/me", undefined, headers)).status).toBe(200);
    expect(row(session.id).expiresAt).toBe(capped);
  }
  expect(await f.context.internalAdapter.updateSession(session.token, {
    expiresAt: new Date(Date.now() + 10 * 86400_000),
  })).toBeNull();
  expect(row(session.id).expiresAt).toBe(capped);
});

it("caps newly issued sessions even when an adapter caller proposes a longer expiry", async () => {
  f = await fixture();
  const createdAt = new Date(Date.now() - 3600_000);
  const session = await f.context.internalAdapter.createSession(f.owner.id, false, {
    createdAt, expiresAt: new Date(Date.now() + 10 * 86400_000),
  }, true);
  expect(session).toBeTruthy();
  expect(session!.expiresAt.getTime()).toBe(createdAt.getTime() + SESSION_LIFETIME_SECONDS * 1000);
  expect(await f.context.internalAdapter.updateSession(session!.token, { createdAt: new Date() })).toBeNull();
});

it("rejects previously refreshed sessions older than 24h at startup for cookie and bearer use", async () => {
  f = await fixture();
  const session = await ownerSession();
  ageSession(session.id, 48, 24);
  const app = createApp(f.auth, f.db, f.control, f.config, f.root);
  for (const headers of [f.ownerHeaders, browser()]) {
    expect((await app(new Request(f.config.origin + "/api/relay/devices", { headers }))).status).toBe(401);
    expect(await f.auth.api.getSession({ headers: new Headers(headers) })).toBeNull();
  }
});

it("keeps session lists token-free and allows owner-only opaque-ID revocation", async () => {
  f = await fixture();
  const session = await ownerSession();
  const cli = await f.context.internalAdapter.createSession(f.owner.id);
  const other = (await f.auth.api.getSession({ headers: new Headers(f.otherHeaders) }))!.session;
  const res = await f.request("/api/control/sessions", undefined, browser());
  expect(res.status).toBe(200);
  const body = await res.json();
  expect(body.sessions).toHaveLength(2);
  expect(body.sessions.find((s: { id: string }) => s.id === session.id).current).toBe(true);
  expect(Object.keys(body.sessions[0]).sort()).toEqual(["createdAt", "current", "expiresAt", "id", "userAgent"]);
  // Browser fetch GETs send Fetch Metadata rather than an Origin header.
  expect((await f.request("/api/control/sessions", undefined, {
    cookie: f.cookie, "sec-fetch-site": "same-origin",
  })).status).toBe(200);
  for (const secret of [session.token, cli!.token, other.token, other.id]) expect(JSON.stringify(body)).not.toContain(secret);
  expect((await f.request(`/api/control/sessions/${other.id}/revoke`, {}, browser())).status).toBe(404);
  expect(await f.auth.api.getSession({ headers: new Headers(f.otherHeaders) })).toBeTruthy();
  expect((await f.request(`/api/control/sessions/${cli!.id}/revoke`, {}, browser())).status).toBe(200);
  expect(await f.auth.api.getSession({ headers: new Headers({ authorization: "Bearer " + cli!.token }) })).toBeNull();
  expect((await f.request("/api/control/sessions/revoke-all", {}, browser())).status).toBe(200);
  expect((await f.request("/api/relay/devices", undefined, browser())).status).toBe(401);
  expect((await f.request("/api/control/sessions", undefined, browser())).status).toBe(401);
  expect((await f.request("/api/control/sessions/revoke-others", {}, browser())).status).toBe(401);
  expect(await f.auth.api.getSession({ headers: new Headers(f.otherHeaders) })).toBeTruthy();
});

it("revoke-others preserves the current browser and other account and blocks CSRF, bearer, malformed bodies and token lists", async () => {
  f = await fixture();
  const cli = await f.context.internalAdapter.createSession(f.owner.id);
  const rejectedHeaders: Record<string, string>[] = [{}, f.ownerHeaders, { cookie: f.cookie }, { cookie: f.cookie, origin: "https://evil.invalid" }];
  for (const headers of rejectedHeaders) {
    for (const [path, body] of [["/api/control/sessions", undefined], ["/api/control/sessions/revoke-others", {}]] as const)
      expect((await f.request(path, body, headers)).status).toBeGreaterThanOrEqual(400);
  }
  expect((await f.request("/api/control/sessions/revoke-all", { userId: f.other.id }, browser())).status).toBe(400);
  expect((await f.request("/api/control/sessions/revoke-others", {}, browser())).status).toBe(200);
  expect(await f.auth.api.getSession({ headers: new Headers({ authorization: "Bearer " + cli!.token }) })).toBeNull();
  expect(await f.auth.api.getSession({ headers: new Headers(browser()) })).toBeTruthy();
  expect(await f.auth.api.getSession({ headers: new Headers(f.otherHeaders) })).toBeTruthy();
  for (const path of ["/api/auth/list-sessions", "/api/auth/list-sessions/", "/api/auth/revoke-session", "/api/auth/revoke-sessions", "/api/auth/revoke-other-sessions"])
    expect((await f.request(path, path.includes("list-sessions") ? undefined : {}, browser())).status).toBe(404);
});

it("an expired or revoked browser cannot list or revoke another session", async () => {
  f = await fixture();
  const session = await ownerSession();
  ageSession(session.id, 48, -1);
  expect((await f.request("/api/control/sessions", undefined, browser())).status).toBe(401);
  expect((await f.request("/api/control/sessions/revoke-all", {}, browser())).status).toBe(401);
  expect(await f.auth.api.getSession({ headers: new Headers(f.otherHeaders) })).toBeTruthy();
});
