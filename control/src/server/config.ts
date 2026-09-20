import { readFileSync, lstatSync } from "node:fs";
import { dirname, resolve } from "node:path";
export type Provider = "github" | "google";
export interface Config {
  origin: string;
  /** Optional loopback-only operator endpoint exposed through Authelia. */
  adminOrigin?: string;
  production: boolean;
  dataDir: string;
  publicDir: string;
  secret: string;
  allowlist: { provider: Provider; accountId: string }[];
  /** Explicit opt-in for verified public OAuth signup. Existing users remain valid when disabled. */
  publicSignupEnabled: boolean;
  providers: Partial<
    Record<Provider, { clientId: string; clientSecret: string }>
  >;
  googleDiscovery?: { expectedEmail: string; expiresAt: number };
}
function readSecret(path: string, env: NodeJS.ProcessEnv) {
  const absolute = resolve(path);
  const st = lstatSync(absolute);
  const credentialDir = env.CREDENTIALS_DIRECTORY;
  const systemd =
    !!credentialDir &&
    resolve(credentialDir).startsWith("/run/credentials/") &&
    dirname(absolute) === resolve(credentialDir) &&
    st.uid === 0 &&
    !(st.mode & 0o227);
  if (
    !st.isFile() ||
    st.isSymbolicLink() ||
    st.size > 4096 ||
    (!systemd && (st.uid !== process.getuid?.() || st.mode & 0o077))
  )
    throw new Error("unsafe_secret_file");
  return readFileSync(absolute, "utf8").trim();
}
export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const production = env.NODE_ENV !== "development" && env.NODE_ENV !== "test";
  const origin =
    env.SESSION_PEER_CONTROL_ORIGIN ?? "https://relay.abruption.dev";
  const url = new URL(origin);
  if (
    url.origin !== origin ||
    url.username ||
    url.password ||
    (production && url.protocol !== "https:") ||
    (!production &&
      url.protocol !== "https:" &&
      !["127.0.0.1", "localhost"].includes(url.hostname))
  )
    throw new Error("invalid_control_origin");
  let adminOrigin: string | undefined;
  if (env.SESSION_PEER_ADMIN_ORIGIN) {
    const adminUrl = new URL(env.SESSION_PEER_ADMIN_ORIGIN);
    if (
      adminUrl.origin !== env.SESSION_PEER_ADMIN_ORIGIN ||
      adminUrl.username ||
      adminUrl.password ||
      (production && adminUrl.protocol !== "https:") ||
      (!production &&
        adminUrl.protocol !== "https:" &&
        !["127.0.0.1", "localhost"].includes(adminUrl.hostname))
    )
      throw new Error("invalid_admin_origin");
    adminOrigin = adminUrl.origin;
  }
  const secret = env.BETTER_AUTH_SECRET_FILE
    ? readSecret(env.BETTER_AUTH_SECRET_FILE, env)
    : env.BETTER_AUTH_SECRET;
  if (!secret || secret.length < 32) throw new Error("auth_secret_required");
  const allowlist: Config["allowlist"] = JSON.parse(
    env.SESSION_PEER_ALLOWED_ACCOUNTS ?? "[]",
  );
  if (
    !Array.isArray(allowlist) ||
    allowlist.some(
      (a) =>
        !a ||
        !["github", "google"].includes(a.provider) ||
        typeof a.accountId !== "string" ||
        !a.accountId ||
        a.accountId.length > 256,
    ) ||
    allowlist.length > 32
  )
    throw new Error("invalid_account_allowlist");
  const publicSignup = env.SESSION_PEER_PUBLIC_SIGNUP ?? "false";
  if (publicSignup !== "true" && publicSignup !== "false")
    throw new Error("invalid_public_signup");
  const providers: Config["providers"] = {};
  for (const provider of ["github", "google"] as const) {
    const prefix = provider.toUpperCase();
    const clientId = env[`${prefix}_CLIENT_ID`];
    const clientSecret = env[`${prefix}_CLIENT_SECRET_FILE`]
      ? readSecret(env[`${prefix}_CLIENT_SECRET_FILE`]!, env)
      : env[`${prefix}_CLIENT_SECRET`];
    if (!!clientId !== !!clientSecret)
      throw new Error("incomplete_oauth_credentials");
    if (clientId && clientSecret)
      providers[provider] = { clientId, clientSecret };
  }
  let googleDiscovery: Config["googleDiscovery"];
  const expectedEmail = env.SESSION_PEER_GOOGLE_DISCOVERY_EMAIL;
  const until = env.SESSION_PEER_GOOGLE_DISCOVERY_UNTIL;
  if (expectedEmail || until) {
    const expiresAt = Number(until);
    if (!expectedEmail || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(expectedEmail)
        || expectedEmail.length > 254 || !providers.google || !until
        || !Number.isSafeInteger(expiresAt) || expiresAt <= Date.now()/1000
        || expiresAt > Date.now()/1000 + 1800)
      throw new Error("invalid_google_discovery_configuration");
    googleDiscovery = { expectedEmail, expiresAt };
  }
  return {
    origin,
    ...(adminOrigin ? { adminOrigin } : {}),
    production,
    secret,
    allowlist,
    publicSignupEnabled: publicSignup === "true",
    providers,
    ...(googleDiscovery ? { googleDiscovery } : {}),
    dataDir: env.SESSION_PEER_CONTROL_DATA ?? "./state/private",
    publicDir: env.SESSION_PEER_RELAY_PUBLIC ?? "./state/relay-public",
  };
}
