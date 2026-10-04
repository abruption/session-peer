import { afterEach, expect, it, vi } from "vitest";
import { fixture } from "./fixtures.js";

let f: Awaited<ReturnType<typeof fixture>> | undefined;
afterEach(() => { vi.restoreAllMocks(); f?.cleanup(); f = undefined; });

// Product callers: main.tsx uses session/social/sign-out/device approval;
// Python control.login uses unauthenticated device/code and device/token.
// Configured GitHub/Google authorize URLs return to GET callback routes.
const routes = [
  ["/api/auth/get-session", "GET", true],
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
    const body = method === "POST" ? { userCode: code.user_code } : undefined;
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
