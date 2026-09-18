import { openSync, closeSync, writeFileSync, fsyncSync } from "node:fs";
import { join } from "node:path";
import { google, verifyGoogleIdToken, type GoogleOptions } from "@better-auth/core/social-providers";
import { tryGetCurrentAuthEndpointContext } from "@better-auth/core/context";
import type { Config } from "./config.js";
import { privateDirectory } from "./storage.js";

/** Normal OAuth processing remains in Better Auth; discovery never signs in. */
export function verifiedGoogleUserInfo(config: Config): GoogleOptions["getUserInfo"] {
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
    if (!discovery) return profile;

    // Request-scoped context, reached only after native state/PKCE code exchange.
    // Direct sign-in with an ID token must never write an operator discovery file.
    const ctx = tryGetCurrentAuthEndpointContext();
    const url = ctx?.request ? new URL(ctx.request.url) : undefined;
    if (!url || url.origin !== config.origin || url.pathname !== "/api/auth/callback/google"
        || ctx?.params?.id !== "google" || Date.now()/1000 >= discovery.expiresAt
        || verified.email_verified !== true || verified.email !== discovery.expectedEmail)
      return null;
    const directory = privateDirectory(config.dataDir);
    const path = join(directory, "google-account-discovery.json");
    try {
      const fd = openSync(path, "wx", 0o600);
      try {
        writeFileSync(fd, JSON.stringify({ schemaVersion: 1, provider: "google",
          accountId: verified.sub, expectedEmail: discovery.expectedEmail,
          verifiedAt: Math.floor(Date.now()/1000), issuer: verified.iss,
          clientId: credentials.clientId }));
        fsyncSync(fd);
      } finally { closeSync(fd); }
      const dirfd = openSync(directory, "r");
      try { fsyncSync(dirfd); } finally { closeSync(dirfd); }
    } catch {
      // Includes existing file: never replace an identity or grant access on retry.
      return null;
    }
    // Operator must separately allowlist the verified subject and disable this mode.
    return null;
  };
}
