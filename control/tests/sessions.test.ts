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

it("does not expose unused Better Auth update-user through the public auth router", async () => {
  f = await fixture();
  const headers = { ...f.ownerHeaders, origin: f.config.origin, "content-type": "application/json" };
  // Pin the upstream behavior that made the transport boundary vulnerable.
  const upstream = await f.auth.handler(new Request(f.config.origin + "/api/auth/update-user", {
    method: "POST", headers, body: JSON.stringify({ name: "Synthetic owner" }),
  }));
  expect(upstream.status).toBe(200);
  const signedCookie = upstream.headers.getSetCookie().find((cookie) =>
    cookie.startsWith(f!.context.authCookies.sessionToken.name + "="))!;
  expect(signedCookie).toBeTruthy();
  expect(upstream.headers.get("set-auth-token")).toBeTruthy();
  // A signed cookie is transport authentication, not evidence of a human:
  // without response filtering the bearer can become a session-management cookie.
  expect((await f.request("/api/control/sessions", undefined, {
    cookie: signedCookie.split(";")[0], origin: f.config.origin,
  })).status).toBe(200);
  const session = await ownerSession();
  ageSession(session.id, 23);
  const copiedCookie = { cookie: signedCookie.split(";")[0], origin: f.config.origin };
  const code = await (await f.request("/api/auth/device/code", { client_id: "session-peer-cli" }, {})).json();
  expect((await f.request("/api/auth/device?user_code=" + code.user_code, undefined, copiedCookie)).status).toBe(200);
  expect((await f.request("/api/auth/device/approve", { userCode: code.user_code }, copiedCookie)).status).toBe(200);
  const redeemed = await f.request("/api/auth/device/token", {
    grant_type: "urn:ietf:params:oauth:grant-type:device_code",
    device_code: code.device_code, client_id: "session-peer-cli",
  }, {});
  expect(redeemed.status).toBe(200);
  const token = (await redeemed.json()).access_token;
  const renewed = f.db.prepare("SELECT createdAt,expiresAt FROM session WHERE token=?").get(token) as
    { createdAt: string; expiresAt: string };
  expect(Date.parse(renewed.expiresAt) - Date.parse(renewed.createdAt)).toBeLessThanOrEqual(86400_000);
  expect(Date.parse(renewed.expiresAt)).toBeGreaterThan(Date.parse(row(session.id).expiresAt) + 22 * 3600_000);
  const response = await f.request("/api/auth/update-user", { name: "Synthetic owner again" }, headers);
  expect(response.status).toBe(404);
  expect(response.headers.getSetCookie()).toEqual([]);
  expect(response.headers.has("set-auth-token")).toBe(false);
  const cookieResponse = await f.request("/api/auth/update-user", { name: "Cookie owner" }, browser());
  expect(cookieResponse.status).toBe(404);
  expect(cookieResponse.headers.getSetCookie()).toEqual([]);
});

it("fails closed on malformed and numeric legacy dates while capping supported SQLite dates", async () => {
  f = await fixture();
  const adapterSession = await ownerSession();
  const adapterRow = row(adapterSession.id);
  expect(adapterRow.createdAt).toMatch(/^\d{4}-\d\d-\d\dT/);
  expect(adapterRow.expiresAt).toMatch(/^\d{4}-\d\d-\d\dT/);
  const cases = [
    ["garbage", "2026-10-05T00:00:00.000Z", null],
    ["", "2026-10-05T00:00:00.000Z", null],
    [1727000000000, 1728000000000, null],
    ["2026-10-03T00:00:00.000Z", "garbage", null],
    ["2026-10-03 00:00:00", "2026-10-05 00:00:00", "2026-10-04T00:00:00.000Z"],
    ["2026-10-03T09:00:00+09:00", "2026-10-05T09:00:00+09:00", "2026-10-04T00:00:00.000Z"],
    ["2026-10-03 00:00:00", "2026-10-03 12:00:00", "2026-10-03 12:00:00"],
  ] as const;
  const ids: string[] = [];
  for (const [createdAt, expiresAt] of cases) {
    const session = (await f.context.internalAdapter.createSession(f.owner.id))!;
    ids.push(session.id);
    f.db.prepare("UPDATE session SET createdAt=?,expiresAt=? WHERE id=?").run(createdAt, expiresAt, session.id);
  }
  capExistingSessions(f.db);
  cases.forEach(([, , expected], index) => {
    const stored = row(ids[index]);
    if (expected === null) expect(stored).toBeUndefined();
    else expect(stored.expiresAt).toBe(expected);
  });
  expect(row(adapterSession.id)).toEqual(adapterRow);
});

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
    const response = await f.request("/api/auth/get-session", undefined, headers);
    expect(response.status).toBe(200);
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(response.headers.has("set-auth-token")).toBe(false);
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
  expect(f.db.pragma("foreign_keys", { simple: true })).toBe(1);
  expect(f.db.pragma("foreign_key_list(relay_device_claims)")).toEqual([]);
  const addClaim = f.db.prepare("INSERT INTO relay_device_claims VALUES(?,?,?,?)");
  addClaim.run("cli-claim", f.owner.id, cli!.id, Date.now() + 300_000);
  addClaim.run("browser-claim", f.owner.id, session.id, Date.now() + 300_000);
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
  const rejectedHeaders: [Record<string, string>, number, string][] = [
    [{}, 401, "browser_session_required"],
    [f.ownerHeaders, 401, "browser_session_required"],
    [{ ...browser(), ...f.ownerHeaders }, 401, "browser_session_required"],
    [{ cookie: f.cookie }, 403, "csrf_rejected"],
    [{ cookie: f.cookie, origin: "https://evil.invalid" }, 403, "csrf_rejected"],
    [{ cookie: f.cookie, "sec-fetch-site": "cross-site" }, 403, "csrf_rejected"],
  ];
  for (const [headers, status, error] of rejectedHeaders) {
    for (const [path, body] of [["/api/control/sessions", undefined], ["/api/control/sessions/revoke-others", {}]] as const) {
      const response = await f.request(path, body, headers);
      expect(response.status).toBe(status);
      expect(await response.json()).toEqual({ error });
    }
  }
  expect((await f.request("/api/control/sessions/revoke-all", { userId: f.other.id }, browser())).status).toBe(400);
  expect((await f.request("/api/control/sessions/revoke-others", {}, browser())).status).toBe(200);
  expect(await f.auth.api.getSession({ headers: new Headers({ authorization: "Bearer " + cli!.token }) })).toBeNull();
  expect(await f.auth.api.getSession({ headers: new Headers(browser()) })).toBeTruthy();
  expect(await f.auth.api.getSession({ headers: new Headers(f.otherHeaders) })).toBeTruthy();
  for (const path of ["/api/auth/list-sessions", "/api/auth/list-sessions/", "/api/auth//list-sessions", "/api/auth/list%2Dsessions", "/api/auth/LIST-SESSIONS", "/api/auth/revoke-session", "/api/auth/revoke-sessions", "/api/auth/revoke-other-sessions"])
    expect((await f.request(path, path.includes("list-sessions") ? undefined : {}, browser())).status).toBe(404);
});

it("enforces session-management methods, JSON bodies and the account rate limit", async () => {
  f = await fixture();
  for (const method of ["PUT", "DELETE"]) {
    const response = await f.request("/api/control/sessions/revoke-all", undefined, browser(), method);
    expect(response.status).toBe(405);
    expect(await response.json()).toEqual({ error: "method_not_allowed" });
  }
  const plain = await f.app(new Request(f.config.origin + "/api/control/sessions/revoke-all", {
    method: "POST", headers: { ...browser(), "content-type": "text/plain" }, body: "{}",
  }));
  expect(plain.status).toBe(415);
  expect(await plain.json()).toEqual({ error: "json_required" });
  // The rejected content type consumed one authenticated request in the window.
  for (let i = 0; i < 59; i++)
    expect((await f.request("/api/control/sessions", undefined, browser())).status).toBe(200);
  const limited = await f.request("/api/control/sessions", undefined, browser());
  expect(limited.status).toBe(429);
  expect(await limited.json()).toEqual({ error: "rate_limited" });
});

it("lets the same owner's browser revoke a leaked CLI login after its relay budget is exhausted", async () => {
  f = await fixture();
  const leaked = await f.context.internalAdapter.createSession(f.owner.id);
  if (!leaked) throw new Error("fixture_session");
  const leakedHeaders = { authorization: "Bearer " + leaked.token };
  for (let i = 0; i < 60; i++)
    expect((await f.request("/api/relay/devices", undefined, leakedHeaders)).status).toBe(200);
  const limited = await f.request("/api/relay/devices", undefined, leakedHeaders);
  expect(limited.status).toBe(429);
  expect(await limited.json()).toEqual({ error: "rate_limited" });
  // Relay limits remain per account, including another login of this owner.
  expect((await f.request("/api/relay/devices")).status).toBe(429);
  const list = await f.request("/api/control/sessions", undefined, browser());
  expect(list.status).toBe(200);
  const body = await list.json();
  expect(body.sessions.some((session: { id: string }) => session.id === leaked.id)).toBe(true);
  expect(JSON.stringify(body)).not.toContain(leaked.token);
  expect((await f.request(`/api/control/sessions/${leaked.id}/revoke`, {}, browser())).status).toBe(200);
  expect((await f.request("/api/relay/devices", undefined, leakedHeaders)).status).toBe(401);
  expect(await f.auth.api.getSession({ headers: new Headers(browser()) })).toBeTruthy();
  expect(await f.auth.api.getSession({ headers: new Headers(f.otherHeaders) })).toBeTruthy();
  // The list and revoke used two requests from the independent browser budget.
  for (let i = 0; i < 58; i++)
    expect((await f.request("/api/control/sessions", undefined, browser())).status).toBe(200);
  expect((await f.request("/api/control/sessions", undefined, browser())).status).toBe(429);
});

it("keeps the CLI's 60-request budget available after browser management reaches its own limit", async () => {
  f = await fixture();
  for (let i = 0; i < 60; i++)
    expect((await f.request("/api/control/sessions", undefined, browser())).status).toBe(200);
  const limited = await f.request("/api/control/sessions/revoke-others", {}, browser());
  expect(limited.status).toBe(429);
  expect(await limited.json()).toEqual({ error: "rate_limited" });
  for (let i = 0; i < 60; i++)
    expect((await f.request("/api/relay/devices")).status).toBe(200);
  expect((await f.request("/api/relay/devices")).status).toBe(429);
});

it("an expired or revoked browser cannot list or revoke another session", async () => {
  f = await fixture();
  const session = await ownerSession();
  ageSession(session.id, 48, -1);
  expect((await f.request("/api/control/sessions", undefined, browser())).status).toBe(401);
  expect((await f.request("/api/control/sessions/revoke-all", {}, browser())).status).toBe(401);
  expect(await f.auth.api.getSession({ headers: new Headers(f.otherHeaders) })).toBeTruthy();
});
