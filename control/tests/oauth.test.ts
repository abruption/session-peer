import { it, expect, afterEach, vi } from "vitest";
import { generateKeyPairSync } from "node:crypto";
import { SignJWT } from "jose";
import { fixture } from "./fixtures.js";
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
async function setup(subject = "allowed-oauth", email = "oauth@test.invalid") {
  f = await fixture({
    providers,
    allowlist: [
      { provider: "github", accountId: "fixture-owner" },
      { provider: "google", accountId: "fixture-other" },
      { provider: "github", accountId: "allowed-oauth" },
      { provider: "google", accountId: "allowed-oauth" },
    ],
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

it("rejects a forged client-submitted Google ID token", async () => {
  await setup();
  const forged = fixtureIdToken.slice(0, -10) + "tamperedXX";
  const response = await f!.request(
    "/api/auth/sign-in/social",
    { provider: "google", idToken: { token: forged }, callbackURL: "/devices" },
    { origin: f!.config.origin },
  );
  expect(response.status).toBe(401);
  expect(
    f!.db
      .prepare("SELECT * FROM account WHERE accountId='allowed-oauth'")
      .get(),
  ).toBeUndefined();
});
