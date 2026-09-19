import { openSync, closeSync, writeFileSync, fsyncSync, linkSync, unlinkSync,
  readFileSync, fstatSync, constants } from "node:fs";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { google, verifyGoogleIdToken, type GoogleOptions } from "@better-auth/core/social-providers";
import { tryGetCurrentAuthEndpointContext } from "@better-auth/core/context";
import type { Config } from "./config.js";
import { privateDirectory } from "./storage.js";

const storage = { openSync, closeSync, writeFileSync, fsyncSync, linkSync, unlinkSync };
export function publishGoogleDiscovery(directory: string, record: unknown, io = storage) {
  const temporary = join(directory, ".google-discovery-"+randomUUID());
  try {
    const fd = io.openSync(temporary, "wx", 0o600);
    try { io.writeFileSync(fd, JSON.stringify(record)); io.fsyncSync(fd); }
    finally { io.closeSync(fd); }
    // link, unlike rename, cannot overwrite another callback's completed record.
    io.linkSync(temporary, join(directory, "google-account-discovery.json"));
    const fdDir = io.openSync(directory, "r");
    try { io.fsyncSync(fdDir); } finally { io.closeSync(fdDir); }
  } finally {
    try { io.unlinkSync(temporary); } catch {}
  }
}

/** Explicit operator confirmation, including persistence after an ambiguous fsync. */
export function confirmGoogleDiscovery(config: Config) {
  const expected = config.googleDiscovery;
  if (!expected || expected.expiresAt <= Date.now()/1000) throw new Error("discovery_window_closed");
  const directory = privateDirectory(config.dataDir);
  const fd = openSync(join(directory, "google-account-discovery.json"), constants.O_RDONLY | constants.O_NOFOLLOW);
  let record;
  try {
    const st = fstatSync(fd);
    if (!st.isFile() || st.uid !== process.getuid?.() || st.mode & 0o077 || st.size > 4096)
      throw new Error("unsafe_discovery_record");
    record = JSON.parse(readFileSync(fd, "utf8"));
    if (record.schemaVersion !== 1 || record.provider !== "google"
        || record.expectedEmail !== expected.expectedEmail
        || record.clientId !== config.providers.google?.clientId
        || !["https://accounts.google.com", "accounts.google.com"].includes(record.issuer)
        || typeof record.accountId !== "string" || !record.accountId || record.accountId.length > 256
        || !Number.isSafeInteger(record.verifiedAt) || record.verifiedAt > Date.now()/1000+5
        || record.verifiedAt < expected.expiresAt-1800)
      throw new Error("invalid_discovery_record");
    fsyncSync(fd);
  } finally { closeSync(fd); }
  const fdDir = openSync(directory, "r");
  try { fsyncSync(fdDir); } finally { closeSync(fdDir); }
  return { ok: true, persistenceConfirmed: true, provider: "google",
           accountId: record.accountId, verifiedAt: record.verifiedAt };
}

/** Normal OAuth processing remains in Better Auth; discovery never signs in. */
export function verifiedGoogleUserInfo(
  config: Config,
  authorize?: (accountId: string) => boolean,
): GoogleOptions["getUserInfo"] {
  const credentials = config.providers.google!;
  const provider = google(credentials);
  return async (tokens: Parameters<typeof provider.getUserInfo>[0]) => {
    if (!tokens.idToken) return null;
    const verified = await verifyGoogleIdToken({
      token: tokens.idToken, audience: credentials.clientId,
      ...(tokens.expectedIdTokenNonce ? { nonce: tokens.expectedIdTokenNonce } : {}),
    });
    if (!verified || typeof verified.sub !== "string" || !verified.sub || verified.sub.length > 256)
      return null;
    const profile = await provider.getUserInfo(tokens);
    if (!profile || profile.data.sub !== verified.sub || profile.user.email !== verified.email
        || profile.user.emailVerified !== verified.email_verified) return null;
    const discovery = config.googleDiscovery;
    if (!discovery)
      return (authorize?.(verified.sub) ?? config.allowlist.some(account =>
        account.provider === "google" && account.accountId === verified.sub))
        ? profile : null;

    // Request-scoped context, reached only after native state/PKCE code exchange.
    // Direct sign-in with an ID token must never write an operator discovery file.
    const ctx = tryGetCurrentAuthEndpointContext();
    const url = ctx?.request ? new URL(ctx.request.url) : undefined;
    if (!url || url.origin !== config.origin || url.pathname !== "/api/auth/callback/google"
        || ctx?.params?.id !== "google" || Date.now()/1000 >= discovery.expiresAt
        || verified.email_verified !== true || verified.email !== discovery.expectedEmail)
      return null;
    const directory = privateDirectory(config.dataDir);
    try {
      publishGoogleDiscovery(directory, { schemaVersion: 1, provider: "google",
          accountId: verified.sub, expectedEmail: discovery.expectedEmail,
          verifiedAt: Math.floor(Date.now()/1000), issuer: verified.iss,
          clientId: credentials.clientId });
    } catch {
      // Includes existing file: never replace an identity or grant access on retry.
      return null;
    }
    // Operator must separately allowlist the verified subject and disable this mode.
    return null;
  };
}
