import { afterEach, expect, it, vi } from "vitest";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { fixture } from "./fixtures.js";

let f: Awaited<ReturnType<typeof fixture>> | undefined;
afterEach(() => { vi.restoreAllMocks(); f?.cleanup(); f = undefined; });

// Product callers: main.tsx uses session/social/sign-out/device approval;
// Python control.login uses unauthenticated device/code and device/token.
// Configured GitHub/Google authorize URLs return to GET callback routes.
// The pinned callback handler redirects failures to GET /error. These providers
// use the default query response mode; form_post callbacks are not configured.
const routes = [
  ["/api/auth/get-session", "GET", true],
  ["/api/auth/error", "GET", false],
  ["/api/auth/sign-out", "POST", true],
  ["/api/auth/sign-in/social", "POST", false],
  ["/api/auth/callback/github", "GET", false],
  ["/api/auth/callback/google", "GET", false],
  ["/api/auth/device", "GET", false],
  ["/api/auth/device/approve", "POST", false],
  ["/api/auth/device/deny", "POST", false],
  ["/api/auth/device/code", "POST", false],
  ["/api/auth/device/token", "POST", false],
] as const;

it("dispatches only the required exact auth paths, methods and transports", async () => {
  f = await fixture({ providers: {
    github: { clientId: "fixture-github", clientSecret: "fixture-github-secret" },
    google: { clientId: "fixture-google", clientSecret: "fixture-google-secret" },
  } });
  const browser = { cookie: f.cookie, origin: f.config.origin };
  const code = await (await f.request("/api/auth/device/code", { client_id: "session-peer-cli" }, {})).json();
  expect((await f.request("/api/auth/device?user_code=" + code.user_code, undefined, browser)).status).toBe(200);
  const handler = vi.spyOn(f.auth, "handler").mockImplementation(async () => Response.json({ routed: true }, {
    headers: { "set-cookie": "fixture-cookie=fixture-value; Secure; HttpOnly", "set-auth-token": "fixture-signed-token" },
  }));
  for (const [path, method, bearer] of routes) {
    const queryPath = path === "/api/auth/device" ? path + "?user_code=" + code.user_code : path;
    const body = path === "/api/auth/device/code" ? { client_id: "session-peer-cli" }
      : method === "POST" ? { userCode: code.user_code } : undefined;
    const headers = path === "/api/auth/device/code" || path === "/api/auth/device/token" ? {} : browser;
    handler.mockClear();
    const response = await f.request(queryPath, body, headers, method);
    expect(response.status, path).toBe(200);
    expect(handler, path).toHaveBeenCalledOnce();
    expect(response.headers.has("set-cookie"), path).toBe(true);

    handler.mockClear();
    for (const wrongMethod of ["GET", "POST", "HEAD", "PUT", "DELETE"].filter(value => value !== method))
      expect((await f.request(queryPath, undefined, browser, wrongMethod)).status, path + " " + wrongMethod).toBe(405);
    expect(handler).not.toHaveBeenCalled();
    const copied = await f.request(queryPath, body, { ...f.ownerHeaders, origin: f.config.origin }, method);
    expect(copied.status, path).toBe(bearer ? 200 : 401);
    expect(copied.headers.has("set-cookie"), path).toBe(false);
    expect(copied.headers.has("set-auth-token"), path).toBe(false);
    expect(handler.mock.calls.length, path).toBe(bearer ? 1 : 0);

    handler.mockClear();
    expect((await f.request(queryPath, body, { ...browser, ...f.ownerHeaders }, method)).status, path).toBe(401);
    expect(handler).not.toHaveBeenCalled();
  }
});

it("rejects credential APIs and every route alias before dispatch or state changes", async () => {
  f = await fixture();
  const browser = { cookie: f.cookie, origin: f.config.origin };
  const before = ["user", "account", "session", "deviceCode"].map(table =>
    f!.db.prepare(`SELECT * FROM "${table}" ORDER BY id`).all());
  const handler = vi.spyOn(f.auth, "handler");
  const unused = ["get-access-token", "refresh-token", "account-info", "list-accounts", "link-social",
    "unlink-account", "update-user", "delete-user", "list-sessions", "revoke-session", "revoke-sessions",
    "revoke-other-sessions", "sign-up/email", "sign-in/email", "unknown"];
  const paths = unused.map(path => "/api/auth/" + path);
  for (const [path] of routes) paths.push(path + "/", path + "//", path.replace("/auth/", "/auth//"),
    path.replace(/\/([^/]+)$/, (_, segment: string) => "/%" + segment.charCodeAt(0).toString(16) + segment.slice(1)),
    "/api/auth/" + path.slice("/api/auth/".length).toUpperCase());
  // Explicit encoded spellings avoid depending on an upstream decoding policy.
  paths.push("/api/auth/%67et-session", "/api/auth/get%2Dsession", "/api/auth/device%2Fapprove",
    "/api/auth/%2Fdevice", "/api/auth/device/approve%2F", "/api/auth/callback/google/", "/api/auth/callback/unknown");
  for (const path of paths)
    for (const headers of [browser, { ...f.ownerHeaders, origin: f.config.origin }])
      for (const method of ["GET", "POST"])
        expect((await f.request(path, method === "POST" ? {} : undefined, headers, method)).status, path).toBe(404);
  expect(handler).not.toHaveBeenCalled();
  expect(["user", "account", "session", "deviceCode"].map(table =>
    f!.db.prepare(`SELECT * FROM "${table}" ORDER BY id`).all())).toEqual(before);
});

it.each(["cookie", "bearer"] as const)("preserves actual %s sign-out without exposing provider credentials", async transport => {
  f = await fixture({ providers: {
    google: { clientId: "fixture-google", clientSecret: "fixture-google-secret" },
    github: { clientId: "fixture-github", clientSecret: "fixture-github-secret" },
  } });
  for (const provider of f.context.socialProviders) expect(provider.createEndSessionURL).toBeUndefined();
  const response = await f.request("/api/auth/sign-out", {}, {
    ...(transport === "cookie" ? { cookie: f.cookie } : f.ownerHeaders), origin: f.config.origin,
  });
  expect(response.status).toBe(200);
  expect(await response.json()).toEqual({ success: true });
  if (transport === "bearer") {
    expect(response.headers.getSetCookie()).toEqual([]);
    expect(response.headers.has("set-auth-token")).toBe(false);
  }
  expect((await f.request("/api/relay/devices")).status).toBe(401);
  expect((await f.request("/api/relay/devices", undefined, f.otherHeaders)).status).toBe(200);
});

it("preserves the pinned error landing page and query handling without credentials or mutations", async () => {
  f = await fixture();
  const sessions = f.db.prepare("SELECT * FROM session ORDER BY id").all();
  const landingHeaders: Record<string, string>[] = [{}, { cookie: f.cookie }];
  const malicious = "<script>alert('fixture')</script>";
  for (const query of ["", "?error=state_mismatch", "?error=" + encodeURIComponent(malicious) +
    "&error_description=" + encodeURIComponent(malicious)]) {
    const path = "/api/auth/error" + query;
    const expected = await f.auth.handler(new Request(f.config.origin + path));
    expect(expected.status).toBe(200);
    const expectedBody = await expected.text();
    for (const headers of landingHeaders) {
      const response = await f.request(path, undefined, headers);
      expect(response.status).toBe(expected.status);
      expect(response.headers.get("content-type")).toBe(expected.headers.get("content-type"));
      expect(response.headers.get("cache-control")).toBe("no-store");
      expect(response.headers.get("referrer-policy")).toBe("no-referrer");
      expect(response.headers.get("x-content-type-options")).toBe("nosniff");
      expect(response.headers.get("content-security-policy")).toContain("frame-ancestors 'none'");
      expect(response.headers.getSetCookie()).toEqual([]);
      expect(response.headers.has("set-auth-token")).toBe(false);
      const body = await response.text();
      expect(body).toBe(expectedBody);
      expect(body).not.toContain(malicious);
      expect(body).not.toContain(f.ownerHeaders.authorization.slice("Bearer ".length));
      expect(body).not.toContain(f.otherHeaders.authorization.slice("Bearer ".length));
    }
    expect((await f.request(path, undefined, f.ownerHeaders)).status).toBe(401);
    expect((await f.request(path, undefined, { cookie: f.cookie, ...f.ownerHeaders })).status).toBe(401);
  }
  expect(f.db.prepare("SELECT * FROM session ORDER BY id").all()).toEqual(sessions);
  // No product flow calls the upstream health endpoint.
  expect((await f.request("/api/auth/ok", undefined, {})).status).toBe(404);
});

it("uses the actual production error redirect without leaking credentials or changing sessions", () => {
  // Better Auth reads NODE_ENV during module initialization. Isolate that
  // branch in a child instead of changing the shared Vitest process environment.
  const output = execFileSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", `
    import assert from "node:assert/strict";
    import { resolve } from "node:path";
    import { fixture } from "./tests/fixtures.ts";
    import { createApp } from "./src/server/app.ts";
    globalThis.fetch = async () => { throw new Error("unexpected_fixture_network"); };
    const f = await fixture({ providers: {
      google: { clientId: "fixture-google", clientSecret: "fixture-google-secret" },
      github: { clientId: "fixture-github", clientSecret: "fixture-github-secret" },
    } });
    try {
      assert.equal(process.env.NODE_ENV, "production");
      assert.equal(f.config.production, true);
      const syntheticCredentials = ["fixture-provider-access", "fixture-provider-refresh", "fixture-provider-id"];
      f.db.prepare("UPDATE account SET accessToken=?,refreshToken=?,idToken=? WHERE userId=?")
        .run(...syntheticCredentials, f.owner.id);
      const before = ["session", "account"].map(table => f.db.prepare('SELECT * FROM "' + table + '" ORDER BY id').all());
      const app = createApp(f.auth, f.db, f.control, f.config, resolve("dist/web"));
      const home = await app(new Request(f.config.origin + "/"));
      assert.equal(home.status, 200);
      const homeBody = await home.text();
      for (const secret of [...syntheticCredentials, f.ownerHeaders.authorization.slice(7), f.otherHeaders.authorization.slice(7)])
        assert.equal(homeBody.includes(secret), false);
      const callback = await app(new Request(f.config.origin + "/api/auth/callback/google?code=fixture-code&state=invalid-fixture-state"));
      assert.equal(callback.status, 302);
      const errorTarget = new URL(callback.headers.get("location"), f.config.origin);
      assert.equal(errorTarget.origin, f.config.origin);
      assert.equal(errorTarget.pathname, "/api/auth/error");
      assert.equal(errorTarget.searchParams.get("error"), "state_mismatch");
      const malicious = "<script>alert('fixture')</script>";
      const cases = [["", "UNKNOWN", null], [errorTarget.search, "state_mismatch", null],
        ["?error=" + encodeURIComponent(malicious) + "&error_description=" + encodeURIComponent(malicious), "UNKNOWN", malicious]];
      let redirects = 0;
      for (const [query, safeCode, description] of cases) {
        for (const headers of [{}, { cookie: f.cookie }]) {
          const response = await app(new Request(f.config.origin + "/api/auth/error" + query, { headers }));
          assert.equal(response.status, 302);
          const location = response.headers.get("location");
          const target = new URL(location, f.config.origin);
          assert.equal(target.origin, f.config.origin);
          assert.equal(target.pathname, "/");
          assert.equal(target.searchParams.get("error"), safeCode);
          assert.equal(target.searchParams.get("error_description"), description);
          assert.equal(location.includes(malicious), false);
          if (description) assert.equal(location.includes(new URLSearchParams({ error_description: description }).toString()), true);
          assert.equal(await response.text(), "");
          assert.deepEqual(response.headers.getSetCookie(), []);
          assert.equal(response.headers.has("set-auth-token"), false);
          assert.equal(response.headers.get("cache-control"), "no-store");
          assert.equal(response.headers.get("referrer-policy"), "no-referrer");
          assert.equal(response.headers.get("x-content-type-options"), "nosniff");
          assert.equal(response.headers.get("content-security-policy").includes("frame-ancestors 'none'"), true);
          for (const secret of [...syntheticCredentials, f.ownerHeaders.authorization.slice(7), f.otherHeaders.authorization.slice(7)])
            assert.equal(JSON.stringify([...response.headers]).includes(secret), false);
          const landing = await app(new Request(target, { headers }));
          assert.equal(landing.status, 200);
          // Production serves the same static React shell. The App initializes
          // its error state to empty and does not display error/error_description
          // query values; its return link URL-encodes location.search.
          assert.equal(await landing.text(), homeBody);
          redirects++;
        }
      }
      assert.equal((await app(new Request(f.config.origin + "/api/auth/error", { headers: f.ownerHeaders }))).status, 401);
      assert.equal((await app(new Request(f.config.origin + "/api/auth/error", { headers: { cookie: f.cookie, ...f.ownerHeaders } }))).status, 401);
      assert.deepEqual(["session", "account"].map(table => f.db.prepare('SELECT * FROM "' + table + '" ORDER BY id').all()), before);
      process.stdout.write(JSON.stringify({ production: true, redirects, landing: "unchanged-react-shell" }));
    } finally { f.cleanup(); }
  `], {
    cwd: fileURLToPath(new URL("../", import.meta.url)),
    env: { PATH: process.env.PATH, TMPDIR: process.env.TMPDIR, NODE_ENV: "production" },
    encoding: "utf8", timeout: 30_000,
  });
  expect(JSON.parse(output)).toEqual({ production: true, redirects: 6, landing: "unchanged-react-shell" });
});
