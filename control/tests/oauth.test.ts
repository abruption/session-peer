import { it, expect, afterEach, vi } from "vitest";
import { generateKeyPairSync } from "node:crypto";
import { SignJWT } from "jose";
import { betterAuth } from "better-auth";
import { supportsIdTokenSignIn } from "@better-auth/core/oauth2";
import { fixture } from "./fixtures.js";
import { allowedUser, authorizeAccount } from "../src/server/auth.js";
let fixtureIdToken: string;
let f: Awaited<ReturnType<typeof fixture>> | undefined;
afterEach(() => {
  vi.unstubAllGlobals();
  f?.cleanup();
  f = undefined;
});
const providers = {
  github: {
    clientId: "fixture-github-client",
    clientSecret: "fixture-github-secret",
  },
  google: {
    clientId: "fixture-google-client",
    clientSecret: "fixture-google-secret",
  },
};
async function setup(
  subject = "allowed-oauth",
  email = "oauth@test.invalid",
  publicSignupEnabled = false,
) {
  f = await fixture({
    providers,
    allowlist: [
      { provider: "github", accountId: "fixture-owner" },
      { provider: "google", accountId: "fixture-other" },
      { provider: "github", accountId: "allowed-oauth" },
      { provider: "google", accountId: "allowed-oauth" },
    ],
    publicSignupEnabled,
  });
  const { privateKey, publicKey } = generateKeyPairSync("rsa", {
    modulusLength: 2048,
  });
  const idToken = await new SignJWT({
    email,
    email_verified: true,
    name: "Fixture OAuth",
  })
    .setProtectedHeader({ alg: "RS256", kid: "fixture-google-key" })
    .setIssuer("https://accounts.google.com")
    .setAudience(providers.google.clientId)
    .setSubject(subject)
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(privateKey);
  fixtureIdToken = idToken;
  const fetchMock = vi.fn(async (input: string | URL | Request) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    let body: unknown;
    if (url === "https://github.com/login/oauth/access_token")
      body = {
        access_token: "fixture-provider-token",
        token_type: "bearer",
        scope: "read:user,user:email",
      };
    else if (url === "https://api.github.com/user")
      body = {
        id: subject,
        login: "fixture-oauth",
        name: "Fixture OAuth",
        email,
      };
    else if (url === "https://api.github.com/user/emails")
      body = [{ email, primary: true, verified: true }];
    else if (url === "https://oauth2.googleapis.com/token")
      body = {
        access_token: "fixture-provider-token",
        refresh_token: "fixture-provider-refresh-token",
        token_type: "bearer",
        expires_in: 300,
        id_token: idToken,
      };
    else if (url === "https://www.googleapis.com/oauth2/v3/certs")
      body = {
        keys: [
          {
            ...publicKey.export({ format: "jwk" }),
            kid: "fixture-google-key",
            alg: "RS256",
            use: "sig",
          },
        ],
      };
    else throw new Error("unexpected_fixture_network");
    return Response.json(body);
  });
  // Test-only network replacement: no real provider credentials or requests.
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

for (const provider of ["github", "google"] as const) {
  it("admits one verified public "+provider+" identity when public signup is open", async () => {
    await setup("public-oauth", "public@test.invalid", true);
    const started = await authorize(provider);
    const callback = await f!.request(
      "/api/auth/callback/"+provider+"?code=fixture-code&state="+
        encodeURIComponent(started.state),
      undefined,
      { cookie: started.cookie },
    );
    expect(callback.status).toBe(302);
    expect(callback.headers.get("location")).toBe("/devices");
    const account = f!.db.prepare(
      "SELECT userId FROM account WHERE providerId=? AND accountId=?",
    ).get(provider, "public-oauth") as { userId: string };
    expect(allowedUser(f!.db, { ...f!.config, publicSignupEnabled: false }, account.userId)).toBe(true);
    expect(f!.db.prepare(
      "SELECT status,expiresAt FROM relay_public_signups WHERE providerId=? AND accountId=?",
    ).get(provider, "public-oauth")).toEqual({ status: "active", expiresAt: 0 });
  });
}

it("keeps verified public signup reservations stable across retries and expiry", async () => {
  f = await fixture({ publicSignupEnabled: true });
  expect(authorizeAccount(f.db, f.config, "github", "first-public", 100)).toBe(true);
  expect(authorizeAccount(f.db, f.config, "github", "first-public", 101)).toBe(true);
  expect(authorizeAccount(f.db, f.config, "google", "second-public", 101)).toBe(true);
  expect(f.db.prepare("SELECT COUNT(*) AS n FROM relay_public_signups").get()).toEqual({ n: 2 });
  expect(authorizeAccount(f.db, f.config, "google", "second-public", 702)).toBe(true);
  expect(f.db.prepare(
    "SELECT accountId FROM relay_public_signups ORDER BY accountId",
  ).all()).toEqual([{ accountId: "second-public" }]);
});

it("closing signup does not evict an existing public identity", async () => {
  f = await fixture({ publicSignupEnabled: true });
  const now = Math.floor(Date.now() / 1000);
  expect(authorizeAccount(
    f.db,
    { ...f.config, allowlist: [], publicSignupEnabled: true },
    "github",
    "fixture-owner",
    now,
  )).toBe(false);
  expect(authorizeAccount(f.db, f.config, "github", "public-existing", now)).toBe(true);
  const user = await (await f.auth.$context).internalAdapter.createUser(
    { name: "Public", email: "public-existing@test.invalid", emailVerified: true },
    { method: "admin" },
  );
  await (await f.auth.$context).internalAdapter.createAccount({
    userId: user.id, providerId: "github", accountId: "public-existing",
  });
  expect(allowedUser(f.db, { ...f.config, publicSignupEnabled: false }, user.id)).toBe(true);
  expect(authorizeAccount(
    f.db, { ...f.config, publicSignupEnabled: false }, "github", "public-new", now + 1,
  )).toBe(false);
});
function cookies(response: Response) {
  return response.headers
    .getSetCookie()
    .map((c) => c.split(";")[0])
    .join("; ");
}
async function authorize(provider: "github" | "google") {
  const start = await f!.request(
    "/api/auth/sign-in/social",
    { provider, callbackURL: "/devices" },
    { origin: f!.config.origin },
  );
  expect(start.status).toBe(200);
  const url = new URL((await start.json()).url);
  expect(url.searchParams.get("redirect_uri")).toBe(
    f!.config.origin + "/api/auth/callback/" + provider,
  );
  expect(url.searchParams.get("code_challenge")).toBeTruthy();
  return { state: url.searchParams.get("state")!, cookie: cookies(start) };
}
for (const provider of ["github", "google"] as const) {
  it(
    "accepts allowlisted " +
      provider +
      " through the real callback with mocked provider transport",
    async () => {
      const fetchMock = await setup();
      const started = await authorize(provider);
      const callback = await f!.request(
        "/api/auth/callback/" +
          provider +
          "?code=fixture-code&state=" +
          encodeURIComponent(started.state),
        undefined,
        { cookie: started.cookie },
      );
      expect(callback.status).toBe(302);
      expect(callback.headers.get("location")).toBe("/devices");
      const response = await f!.request("/api/relay/devices", undefined, {
        cookie: cookies(callback),
      });
      expect(response.status).toBe(200);
      const account = f!.db
        .prepare("SELECT * FROM account WHERE accountId=? AND providerId=?")
        .get("allowed-oauth", provider) as any;
      expect(account.userId).not.toBe(f!.owner.id);
      expect(account.accessToken).not.toBe("fixture-provider-token");
      expect(fetchMock).toHaveBeenCalled();
    },
  );
}
it("rejects tampered OAuth state before token exchange", async () => {
  const fetchMock = await setup();
  const started = await authorize("github");
  const callback = await f!.request(
    "/api/auth/callback/github?code=fixture-code&state=wrong-state",
    undefined,
    { cookie: started.cookie },
  );
  expect(callback.status).toBe(302);
  expect(callback.headers.get("location")).toContain("error=");
  expect(fetchMock).not.toHaveBeenCalled();
  const landingURL = new URL(callback.headers.get("location")!, f!.config.origin);
  expect(landingURL.pathname).toBe("/api/auth/error");
  const upstreamLanding = await f!.auth.handler(new Request(landingURL, {
    headers: { cookie: started.cookie },
  }));
  expect(upstreamLanding.status).toBe(200);
  const landingHeaders: Record<string, string>[] = [{}, { cookie: started.cookie }];
  for (const headers of landingHeaders) {
    const landing = await f!.request(landingURL.pathname + landingURL.search, undefined, headers);
    expect(landing.status).toBe(200);
    expect(landing.headers.get("content-type")).toContain("text/html");
    expect(landing.headers.getSetCookie()).toEqual([]);
    expect(landing.headers.has("set-auth-token")).toBe(false);
    expect(await landing.text()).toContain("state_mismatch");
  }
  expect(
    (
      await f!.request("/api/relay/devices", undefined, {
        cookie: cookies(callback),
      })
    ).status,
  ).toBe(401);
});
it.each(["github", "google"] as const)("denies an unallowlisted %s subject before creating any user, account or session", async (provider) => {
  await setup("not-allowed");
  const before = ["user", "account", "session"].map(table =>
    f!.db.prepare(`SELECT COUNT(*) AS count FROM "${table}"`).get());
  const started = await authorize(provider);
  const callback = await f!.request(
    "/api/auth/callback/"+provider+"?code=fixture-code&state=" +
      encodeURIComponent(started.state),
    undefined,
    { cookie: started.cookie },
  );
  expect(callback.headers.get("location")).toContain("error=");
  expect(
    f!.db.prepare("SELECT * FROM account WHERE accountId='not-allowed'").get(),
  ).toBeUndefined();
  expect(f!.db.prepare("SELECT id FROM user WHERE email='oauth@test.invalid'").get()).toBeUndefined();
  expect(["user", "account", "session"].map(table =>
    f!.db.prepare(`SELECT COUNT(*) AS count FROM "${table}"`).get())).toEqual(before);
  expect(
    (
      await f!.request("/api/relay/devices", undefined, {
        cookie: cookies(callback),
      })
    ).status,
  ).toBe(401);
});
it("does not link an allowlisted Google identity to an existing GitHub owner by matching email", async () => {
  await setup("allowed-oauth", "owner@test.invalid");
  const started = await authorize("google");
  const callback = await f!.request(
    "/api/auth/callback/google?code=fixture-code&state=" +
      encodeURIComponent(started.state),
    undefined,
    { cookie: started.cookie },
  );
  expect(callback.headers.get("location")).toContain("error=");
  expect(
    f!.db
      .prepare("SELECT * FROM account WHERE accountId='allowed-oauth'")
      .get(),
  ).toBeUndefined();
  expect(
    (
      await f!.request("/api/relay/devices", undefined, {
        cookie: cookies(callback),
      })
    ).status,
  ).toBe(401);
});

it("disables the unused client-submitted Google ID-token branch even for forged input", async () => {
  await setup();
  const forged = fixtureIdToken.slice(0, -10) + "tamperedXX";
  const response = await f!.request(
    "/api/auth/sign-in/social",
    { provider: "google", idToken: { token: forged }, callbackURL: "/devices" },
    { origin: f!.config.origin },
  );
  expect(response.status).toBe(404);
  expect(await response.json()).toMatchObject({ code: "ID_TOKEN_NOT_SUPPORTED" });
  expect(
    f!.db
      .prepare("SELECT * FROM account WHERE accountId='allowed-oauth'")
      .get(),
  ).toBeUndefined();
});

it("pins the synthetic Google credential-to-session baseline and closes both JSON entrypoints", async () => {
  const network = await setup();
  const started = await authorize("google");
  const callback = await f!.request("/api/auth/callback/google?code=fixture-code&state=" +
    encodeURIComponent(started.state), undefined, { cookie: started.cookie });
  expect(callback.headers.get("location")).toBe("/devices");
  const account = f!.db.prepare("SELECT userId FROM account WHERE providerId='google' AND accountId='allowed-oauth'")
    .get() as { userId: string };
  const copiedSession = f!.db.prepare("SELECT id,token FROM session WHERE userId=?").get(account.userId) as
    { id: string; token: string };
  f!.db.prepare("UPDATE session SET createdAt=?,updatedAt=?,expiresAt=? WHERE id=?").run(
    new Date(Date.now() - 23 * 3600_000).toISOString(),
    new Date(Date.now() - 23 * 3600_000).toISOString(),
    new Date(Date.now() + 3600_000).toISOString(), copiedSession.id,
  );
  const bearerHeaders = { authorization: "Bearer " + copiedSession.token, origin: f!.config.origin };
  // Reproduce the pre-patch direct-ID-token configuration with the pinned
  // library, the real configured verifier and exclusively mocked transport.
  const baseline = betterAuth({ ...f!.auth.options, socialProviders: {
    ...f!.auth.options.socialProviders,
    google: { ...providers.google, ...f!.auth.options.socialProviders!.google as object, disableIdTokenSignIn: false },
  } });
  const upstream = (path: string, body: unknown, headers: Record<string, string>) => baseline.handler(
    new Request(f!.config.origin + path, { method: "POST",
      headers: { ...headers, "content-type": "application/json" }, body: JSON.stringify(body) }),
  );
  const accounts = await baseline.handler(new Request(f!.config.origin + "/api/auth/list-accounts", {
    headers: bearerHeaders,
  }));
  expect(accounts.status).toBe(200);
  const selectedAccount = (await accounts.json()).find((value: { providerId: string }) => value.providerId === "google");
  expect(selectedAccount.id).toBeTruthy();
  const credentials = await upstream("/api/auth/get-access-token", { accountId: selectedAccount.id }, bearerHeaders);
  expect(credentials.status).toBe(200);
  const leaked = await credentials.json();
  expect(leaked).toMatchObject({ accessToken: "fixture-provider-token", idToken: fixtureIdToken });
  const refreshed = await upstream("/api/auth/refresh-token", { accountId: selectedAccount.id }, bearerHeaders);
  expect(refreshed.status).toBe(200);
  expect(await refreshed.json()).toMatchObject({ accessToken: "fixture-provider-token",
    refreshToken: "fixture-provider-refresh-token", idToken: fixtureIdToken });
  const mintBody = { provider: "google", idToken: { token: leaked.idToken }, callbackURL: "/devices" };
  const minted = await upstream("/api/auth/sign-in/social", mintBody, { origin: f!.config.origin });
  expect(minted.status).toBe(200);
  const fresh = await minted.json();
  expect(fresh.token).toBeTruthy();
  expect(fresh.token).not.toBe(copiedSession.token);
  expect(minted.headers.getSetCookie().length).toBeGreaterThan(0);
  const freshRow = f!.db.prepare("SELECT createdAt,expiresAt FROM session WHERE token=?").get(fresh.token) as
    { createdAt: string; expiresAt: string };
  expect(Date.parse(freshRow.expiresAt) - Date.now()).toBeGreaterThan(23.9 * 3600_000);

  const sessionsBefore = f!.db.prepare("SELECT id,token,createdAt,expiresAt FROM session ORDER BY id").all();
  network.mockClear();
  for (const path of ["/api/auth/get-access-token", "/api/auth/refresh-token"])
    for (const headers of [bearerHeaders, { cookie: cookies(callback), origin: f!.config.origin }]) {
      const denied = await f!.request(path, { accountId: selectedAccount.id }, headers);
      expect(denied.status).toBe(404);
      expect(await denied.json()).toEqual({ error: "not_found" });
      expect(denied.headers.getSetCookie()).toEqual([]);
      expect(denied.headers.has("set-auth-token")).toBe(false);
    }
  const deniedMint = await f!.request("/api/auth/sign-in/social", mintBody, { origin: f!.config.origin });
  expect(deniedMint.status).toBe(404);
  expect(await deniedMint.json()).toMatchObject({ code: "ID_TOKEN_NOT_SUPPORTED" });
  expect(deniedMint.headers.getSetCookie()).toEqual([]);
  expect(deniedMint.headers.has("set-auth-token")).toBe(false);
  expect(network).not.toHaveBeenCalled();
  expect(f!.db.prepare("SELECT id,token,createdAt,expiresAt FROM session ORDER BY id").all()).toEqual(sessionsBefore);
  expect((await f!.request("/api/relay/devices", undefined, bearerHeaders)).status).toBe(200);
});

it("keeps direct ID-token sign-in disabled after runtime provider overrides are merged", async () => {
  const injectedProviders = { google: { ...providers.google, disableIdTokenSignIn: false,
    verifyIdToken: async () => true } };
  f = await fixture({ providers: injectedProviders });
  const google = f.context.socialProviders.find(provider => provider.id === "google")!;
  expect(google.options?.disableIdTokenSignIn).toBe(true);
  expect(supportsIdTokenSignIn(google)).toBe(false);
  const response = await f.auth.handler(new Request(f.config.origin + "/api/auth/sign-in/social", {
    method: "POST", headers: { origin: f.config.origin, "content-type": "application/json" },
    body: JSON.stringify({ provider: "google", idToken: { token: "synthetic-id-token" } }),
  }));
  expect(response.status).toBe(404);
  expect(await response.json()).toMatchObject({ code: "ID_TOKEN_NOT_SUPPORTED" });
});
