import Database from "better-sqlite3";
import { betterAuth } from "better-auth";
import { github } from "@better-auth/core/social-providers";
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
type SignupRow = { status: "pending" | "active"; expiresAt: number };
const PUBLIC_SIGNUP_RESERVATION_SECONDS = 600;

function preparePublicSignup(db: Database.Database) {
  db.exec(`CREATE TABLE IF NOT EXISTS relay_public_signups (
    providerId TEXT NOT NULL,
    accountId TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','active')),
    expiresAt INTEGER NOT NULL,
    createdAt INTEGER NOT NULL,
    PRIMARY KEY(providerId,accountId)
  )`);
}

/**
 * Verify or reserve one provider identity. The short IMMEDIATE transaction
 * keeps concurrent OAuth callbacks from racing the same reservation.
 */
export function authorizeAccount(
  db: Database.Database,
  config: Config,
  provider: string,
  accountId: string,
  now = Math.floor(Date.now() / 1000),
): boolean {
  if (allowedAccount(config, provider, accountId)) return true;
  preparePublicSignup(db);
  return db.transaction(() => {
    db.prepare(`DELETE FROM relay_public_signups
      WHERE status='pending' AND expiresAt<?
      AND NOT EXISTS (
        SELECT 1 FROM account
        WHERE account.providerId=relay_public_signups.providerId
          AND account.accountId=relay_public_signups.accountId
      )`).run(now);
    const existingAccount = db
      .prepare("SELECT 1 FROM account WHERE providerId=? AND accountId=?")
      .get(provider, accountId);
    const slot = db
      .prepare("SELECT status,expiresAt FROM relay_public_signups WHERE providerId=? AND accountId=?")
      .get(provider, accountId) as SignupRow | undefined;
    if (existingAccount && slot) {
      db.prepare(`INSERT INTO relay_public_signups
        (providerId,accountId,status,expiresAt,createdAt) VALUES(?,?,'active',0,?)
        ON CONFLICT(providerId,accountId) DO UPDATE SET status='active',expiresAt=0`)
        .run(provider, accountId, now);
      return true;
    }
    // Never adopt a legacy or orphan account merely because public signup is
    // configured. Every public identity needs its own verified reservation.
    if (existingAccount) return false;
    if (slot?.status === "active" || (slot?.status === "pending" && slot.expiresAt >= now))
      return true;
    if (!config.publicSignupEnabled) return false;
    db.prepare(`INSERT INTO relay_public_signups
      (providerId,accountId,status,expiresAt,createdAt) VALUES(?,?,'pending',?,?)
      ON CONFLICT(providerId,accountId) DO UPDATE SET
        status='pending',expiresAt=excluded.expiresAt,createdAt=excluded.createdAt`)
      .run(provider, accountId, now + PUBLIC_SIGNUP_RESERVATION_SECONDS, now);
    return true;
  }).immediate();
}

function publicAccountAllowed(
  db: Database.Database,
  provider: string,
  accountId: string,
): boolean {
  preparePublicSignup(db);
  const account = db
    .prepare("SELECT 1 FROM account WHERE providerId=? AND accountId=?")
    .get(provider, accountId);
  if (!account) return false;
  const slot = db
    .prepare("SELECT status FROM relay_public_signups WHERE providerId=? AND accountId=?")
    .get(provider, accountId) as Pick<SignupRow, "status"> | undefined;
  if (!slot) return false;
  if (slot.status === "pending")
    db.prepare("UPDATE relay_public_signups SET status='active',expiresAt=0 WHERE providerId=? AND accountId=?")
      .run(provider, accountId);
  return true;
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
    allowedAccount(config, a.providerId, a.accountId) ||
    publicAccountAllowed(db, a.providerId, a.accountId),
  );
}
export function operatorUser(
  db: Database.Database,
  config: Config,
  userId: string,
): boolean {
  const accounts = db
    .prepare("SELECT providerId, accountId FROM account WHERE userId = ?")
    .all(userId) as { providerId: string; accountId: string }[];
  return accounts.some((account) =>
    allowedAccount(config, account.providerId, account.accountId),
  );
}
export function createAuth(db: Database.Database, config: Config) {
  preparePublicSignup(db);
  const githubProvider = config.providers.github ? github(config.providers.github) : undefined;
  return betterAuth({
    appName: "session-peer",
    database: db,
    baseURL: config.origin,
    basePath: "/api/auth",
    secret: config.secret,
    trustedOrigins: [config.origin],
    emailAndPassword: { enabled: false },
    socialProviders: { ...config.providers, ...(githubProvider ? {
      github: { ...config.providers.github!, getUserInfo: async (tokens: Parameters<typeof githubProvider.getUserInfo>[0]) => {
        const profile = await githubProvider.getUserInfo(tokens);
        // Reject before Better Auth creates a user. A denied account-create hook
        // alone can leave an orphan user (and consume its unique email address).
        return profile && authorizeAccount(db, config, "github", String(profile.data.id)) ? profile : null;
      } },
    } : {}), ...(config.providers.google ? {
      google: { ...config.providers.google, getUserInfo: verifiedGoogleUserInfo(
        config,
        (accountId) => authorizeAccount(db, config, "google", accountId),
      ) },
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
            allowedAccount(config, account.providerId, account.accountId) ||
            !!db.prepare(`SELECT 1 FROM relay_public_signups
              WHERE providerId=? AND accountId=?
                AND (status='active' OR (status='pending' AND expiresAt>=?))`)
              .get(
                account.providerId,
                account.accountId,
                Math.floor(Date.now() / 1000),
              ),
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
