import { it, expect, afterEach } from "vitest";
import { fixture, identity } from "./fixtures.js";
let f: Awaited<ReturnType<typeof fixture>> | undefined;
afterEach(() => {
  f?.cleanup();
  f = undefined;
});
it("requires real BetterAuth sessions and enforces account allowlist per request", async () => {
  f = await fixture();
  expect((await f.request("/api/relay/devices", undefined, {})).status).toBe(
    401,
  );
  expect((await f.request("/api/relay/devices")).status).toBe(200);
  f.config.allowlist = [];
  expect((await f.request("/api/relay/devices")).status).toBe(403);
  expect(await f.context.internalAdapter.createSession(f.owner.id)).toBeNull();
});
it("blocks cross-origin cookie and bearer requests, allows cookie same origin and header-only CLI", async () => {
  f = await fixture();
  const d = identity(f.root, "Device", "a");
  const body = { operation: "register", payload: d.payload };
  expect(
    (
      await f.request("/api/relay/challenge", body, {
        cookie: f.cookie,
        origin: "https://attacker.invalid",
      })
    ).status,
  ).toBe(403);
  expect(
    (
      await f.request("/api/relay/challenge", body, {
        ...f.ownerHeaders,
        origin: "https://attacker.invalid",
      })
    ).status,
  ).toBe(403);
  expect(
    (await f.request("/api/relay/challenge", body, { cookie: f.cookie }))
      .status,
  ).toBe(403);
  expect(
    (
      await f.request("/api/relay/challenge", body, {
        cookie: f.cookie,
        origin: f.config.origin,
      })
    ).status,
  ).toBe(200);
  expect((await f.request("/api/relay/challenge", body)).status).toBe(200);
});
it("issues first-party device session only after code verification and explicit approval", async () => {
  f = await fixture();
  const issued = await f.request(
    "/api/auth/device/code",
    { client_id: "session-peer-cli" },
    {},
  );
  expect(issued.status).toBe(200);
  const code = await issued.json();
  const poll = {
    grant_type: "urn:ietf:params:oauth:grant-type:device_code",
    device_code: code.device_code,
    client_id: "session-peer-cli",
  };
  expect(
    (await (await f.request("/api/auth/device/token", poll, {})).json()).error,
  ).toBe("authorization_pending");
  const headers = { cookie: f.cookie, origin: f.config.origin };
  const claim = await f.request(
    "/api/auth/device?user_code=" + code.user_code,
    undefined,
    headers,
  );
  expect(claim.status).toBe(200);
  expect(
    (
      await f.request(
        "/api/auth/device/approve",
        { userCode: code.user_code },
        headers,
      )
    ).status,
  ).toBe(200);
  // Avoid throttling the fixture's second poll; real clients must obey returned interval.
  f.db.prepare("UPDATE deviceCode SET lastPolledAt=NULL").run();
  const tokenResponse = await f.request("/api/auth/device/token", poll, {});
  expect(tokenResponse.status).toBe(200);
  const token = await tokenResponse.json();
  expect(token.access_token).toBeTruthy();
  expect(
    (
      await f.request("/api/relay/devices", undefined, {
        authorization: "Bearer " + token.access_token,
      })
    ).status,
  ).toBe(200);
  expect((await f.request("/api/auth/device/token", poll, {})).status).not.toBe(
    200,
  );
});
it("rejects untrusted device clients, code expiry and explicit denial", async () => {
  f = await fixture();
  expect(
    (await f.request("/api/auth/device/code", { client_id: "unknown" }, {}))
      .status,
  ).toBe(400);
  const code = await (
    await f.request(
      "/api/auth/device/code",
      { client_id: "session-peer-cli" },
      {},
    )
  ).json();
  const headers = { cookie: f.cookie, origin: f.config.origin };
  expect(
    (
      await f.request(
        "/api/auth/device?user_code=" + code.user_code,
        undefined,
        headers,
      )
    ).status,
  ).toBe(200);
  expect(
    (
      await f.request(
        "/api/auth/device/deny",
        { userCode: code.user_code },
        headers,
      )
    ).status,
  ).toBe(200);
  const poll = {
    grant_type: "urn:ietf:params:oauth:grant-type:device_code",
    device_code: code.device_code,
    client_id: "session-peer-cli",
  };
  expect(
    (await (await f.request("/api/auth/device/token", poll, {})).json()).error,
  ).toBe("access_denied");
  const expired = await (
    await f.request(
      "/api/auth/device/code",
      { client_id: "session-peer-cli" },
      {},
    )
  ).json();
  f.db
    .prepare("UPDATE deviceCode SET expiresAt=? WHERE userCode=?")
    .run(new Date(Date.now() - 1000).toISOString(), expired.user_code);
  expect(
    (
      await f.request(
        "/api/auth/device?user_code=" + expired.user_code,
        undefined,
        headers,
      )
    ).status,
  ).toBe(400);
});
it("binds claimed device code to its original browser session, not another user", async () => {
  f = await fixture();
  const code = await (
    await f.request(
      "/api/auth/device/code",
      { client_id: "session-peer-cli" },
      {},
    )
  ).json();
  expect(
    (
      await f.request(
        "/api/auth/device?user_code=" + code.user_code,
        undefined,
        { cookie: f.cookie, origin: f.config.origin },
      )
    ).status,
  ).toBe(200);
  // A bearer is never accepted as browser approval, even for an allowed account.
  expect(
    (
      await f.request(
        "/api/auth/device/approve",
        { userCode: code.user_code },
        { ...f.otherHeaders, origin: f.config.origin },
      )
    ).status,
  ).toBe(401);
  const otherSession = await f.context.internalAdapter.createSession(
    f.other.id,
  );
  if (!otherSession) throw new Error();
  const { serializeSignedCookie } = await import("better-call");
  const otherCookie = (
    await serializeSignedCookie(
      f.context.authCookies.sessionToken.name,
      otherSession.token,
      f.config.secret,
    )
  ).split(";")[0];
  expect(
    (
      await f.request(
        "/api/auth/device/approve",
        { userCode: code.user_code },
        { cookie: otherCookie, origin: f.config.origin },
      )
    ).status,
  ).not.toBe(200);
});
it("requires the exact browser session that claimed a code, including another session of the same user", async () => {
  f = await fixture();
  const code = await (
    await f.request(
      "/api/auth/device/code",
      { client_id: "session-peer-cli" },
      {},
    )
  ).json();
  const headers = { cookie: f.cookie, origin: f.config.origin };
  expect(
    (
      await f.request(
        "/api/auth/device?user_code=" + code.user_code,
        undefined,
        headers,
      )
    ).status,
  ).toBe(200);
  const next = await f.context.internalAdapter.createSession(f.owner.id);
  if (!next) throw new Error("fixture");
  const { serializeSignedCookie } = await import("better-call");
  const cookie = (
    await serializeSignedCookie(
      f.context.authCookies.sessionToken.name,
      next.token,
      f.config.secret,
    )
  ).split(";")[0];
  const otherHeaders = { cookie, origin: f.config.origin };
  expect(
    (
      await f.request(
        "/api/auth/device?user_code=" + code.user_code,
        undefined,
        otherHeaders,
      )
    ).status,
  ).toBe(403);
  expect(
    (
      await f.request(
        "/api/auth/device/approve",
        { userCode: code.user_code },
        otherHeaders,
      )
    ).status,
  ).toBe(403);
  expect(
    (
      await f.request(
        "/api/auth/device/deny",
        { userCode: code.user_code },
        headers,
      )
    ).status,
  ).toBe(200);
});
it("revocation API is owner-only and never requires a lost key", async () => {
  f = await fixture();
  const d = identity(f.root, "Device", "a");
  f.control.register(
    f.owner.id,
    f.proven(f.owner.id, "register", d.payload, d.privateKey),
  );
  const url = "/api/relay/devices/" + d.payload.principal + "/revoke";
  expect((await f.request(url, {}, f.otherHeaders)).status).toBe(404);
  expect(
    (await f.request(url, {}, { cookie: f.cookie, origin: f.config.origin }))
      .status,
  ).toBe(200);
  expect(f.control.list(f.owner.id)[0].revoked).toBe(true);
});
it("rejects oversized bodies and unsupported routes, returns no cache/security headers", async () => {
  f = await fixture();
  const r = await f.request("/api/relay/challenge", {
    extra: "x".repeat(17000),
  });
  expect(r.status).toBe(413);
  expect((await f.request("/api/relay/challenge", {})).status).toBe(400);
  const response = await f.request("/api/relay/devices");
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(response.headers.get("content-security-policy")).toContain(
    "frame-ancestors 'none'",
  );
  expect((await f.request("/.env", undefined, {})).status).toBe(404);
  expect((await f.request("/api/relay/unknown")).status).toBe(404);
});
it("does not enable password signup, fake OAuth or automatic email linking", async () => {
  f = await fixture();
  expect(f.auth.options.account?.accountLinking?.enabled).toBe(false);
  const r = await f.request(
    "/api/auth/sign-up/email",
    {
      name: "Intruder",
      email: "x@test.invalid",
      password: "test-only-password",
    },
    { origin: f.config.origin },
  );
  expect(r.status).not.toBe(200);
  expect(
    (await (await f.request("/api/control/config", undefined, {})).json())
      .providers,
  ).toEqual([]);
  const other = await f.context.internalAdapter.createAccount({
    userId: f.owner.id,
    providerId: "github",
    accountId: "unlisted",
  });
  expect(other).toBeNull();
});
