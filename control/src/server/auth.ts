import Database from "better-sqlite3";
import { betterAuth } from "better-auth";
import { bearer, deviceAuthorization } from "better-auth/plugins";
import type { Config } from "./config.js";
import { verifiedGoogleUserInfo } from "./google-discovery.js";
export function allowedAccount(
  config: Config,
  provider: string,
  accountId: string,
): boolean {
  return config.allowlist.some(
    (a) => a.provider === provider && a.accountId === accountId,
  );
}
export function allowedUser(
  db: Database.Database,
  config: Config,
  userId: string,
): boolean {
  const accounts = db
    .prepare("SELECT providerId, accountId FROM account WHERE userId = ?")
    .all(userId) as { providerId: string; accountId: string }[];
  return accounts.some((a) =>
    allowedAccount(config, a.providerId, a.accountId),
  );
}
export function createAuth(db: Database.Database, config: Config) {
  return betterAuth({
    appName: "session-peer",
    database: db,
    baseURL: config.origin,
    basePath: "/api/auth",
    secret: config.secret,
    trustedOrigins: [config.origin],
    emailAndPassword: { enabled: false },
    socialProviders: { ...config.providers, ...(config.providers.google ? {
      google: { ...config.providers.google, getUserInfo: verifiedGoogleUserInfo(config) },
    } : {}) },
    account: {
      accountLinking: { enabled: false, allowUnlinkingAll: false },
      encryptOAuthTokens: true,
    },
    session: {
      expiresIn: 86400,
      updateAge: 3600,
      cookieCache: { enabled: false },
    },
    advanced: {
      ipAddress: { ipAddressHeaders: ["x-session-peer-ip"] },
      useSecureCookies: config.production,
      defaultCookieAttributes: {
        httpOnly: true,
        sameSite: "lax",
        secure: config.production,
      },
    },
    rateLimit: { enabled: true, window: 60, max: 60 },
    logger: { disabled: true },
    databaseHooks: {
      account: {
        create: {
          before: async (account) =>
            allowedAccount(config, account.providerId, account.accountId),
        },
      },
      session: {
        create: {
          before: async (session) => allowedUser(db, config, session.userId),
        },
      },
    },
    plugins: [
      deviceAuthorization({
        verificationUri: `${config.origin}/device`,
        expiresIn: "5m",
        interval: "5s",
        validateClient: (clientId) => clientId === "session-peer-cli",
      }),
      bearer(),
    ],
  });
}
export type Auth = ReturnType<typeof createAuth>;
