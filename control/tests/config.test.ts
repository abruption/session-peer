import { it, expect } from "vitest";
import { loadConfig } from "../src/server/config.js";
it("fails closed without a secret and validates exact origins/allowlists", () => {
  expect(() => loadConfig({})).toThrow("auth_secret_required");
  expect(() =>
    loadConfig({
      BETTER_AUTH_SECRET: "x".repeat(40),
      SESSION_PEER_CONTROL_ORIGIN: "http://relay.example",
    }),
  ).toThrow("invalid_control_origin");
  expect(() =>
    loadConfig({
      BETTER_AUTH_SECRET: "x".repeat(40),
      SESSION_PEER_CONTROL_ORIGIN: "https://relay.example/",
    }),
  ).toThrow("invalid_control_origin");
  expect(() =>
    loadConfig({
      BETTER_AUTH_SECRET: "x".repeat(40),
      SESSION_PEER_ALLOWED_ACCOUNTS: '[{"provider":"email","accountId":"x"}]',
    }),
  ).toThrow("invalid_account_allowlist");
  const c = loadConfig({ BETTER_AUTH_SECRET: "x".repeat(40) });
  expect(c.allowlist).toEqual([]);
  expect(c.providers).toEqual({});
  expect(c.publicSignupEnabled).toBe(false);
  expect(c.adminOrigin).toBeUndefined();
  expect(c.relayMetricsUrl).toBeUndefined();
  expect(
    loadConfig({
      NODE_ENV: "test",
      BETTER_AUTH_SECRET: "x".repeat(40),
      SESSION_PEER_ADMIN_ORIGIN: "http://127.0.0.1:3771",
    }).adminOrigin,
  ).toBe("http://127.0.0.1:3771");
  expect(() =>
    loadConfig({
      BETTER_AUTH_SECRET: "x".repeat(40),
      SESSION_PEER_ADMIN_ORIGIN: "http://admin.example",
    }),
  ).toThrow("invalid_admin_origin");
  expect(loadConfig({
    BETTER_AUTH_SECRET: "x".repeat(40),
    SESSION_PEER_RELAY_METRICS_URL: "http://127.0.0.1:3768/metrics",
  }).relayMetricsUrl).toBe("http://127.0.0.1:3768/metrics");
  for (const value of [
    "https://127.0.0.1:3768/metrics",
    "http://localhost:3768/metrics",
    "http://127.0.0.1:3768/other",
    "http://127.0.0.1:3768/metrics?secret=x",
  ]) expect(() => loadConfig({
    BETTER_AUTH_SECRET: "x".repeat(40),
    SESSION_PEER_RELAY_METRICS_URL: value,
  })).toThrow("invalid_relay_metrics_url");
  expect(() =>
    loadConfig({
      BETTER_AUTH_SECRET: "x".repeat(40),
      SESSION_PEER_ADMIN_ORIGIN: "https://admin.example/path",
    }),
  ).toThrow("invalid_admin_origin");
  expect(loadConfig({
    BETTER_AUTH_SECRET: "x".repeat(40),
    SESSION_PEER_PUBLIC_SIGNUP: "true",
  }).publicSignupEnabled).toBe(true);
  expect(loadConfig({
    BETTER_AUTH_SECRET: "x".repeat(40),
    SESSION_PEER_PUBLIC_SIGNUP: "false",
  }).publicSignupEnabled).toBe(false);
  for (const value of ["1", "TRUE", "yes", "0"]) {
    expect(() => loadConfig({
      BETTER_AUTH_SECRET: "x".repeat(40),
      SESSION_PEER_PUBLIC_SIGNUP: value,
    })).toThrow("invalid_public_signup");
  }
});

it("requires protected regular secret files, rejecting world-readable and symlink input", async () => {
  const { mkdtempSync, writeFileSync, chmodSync, symlinkSync, rmSync } =
    await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const root = mkdtempSync(join(tmpdir(), "sp-config-"));
  const path = join(root, "auth-secret");
  try {
    writeFileSync(path, "local-fixture-secret-only-not-real-0000000", {
      mode: 0o600,
    });
    expect(
      loadConfig({ BETTER_AUTH_SECRET_FILE: path }).secret.length,
    ).toBeGreaterThan(32);
    chmodSync(path, 0o644);
    expect(() => loadConfig({ BETTER_AUTH_SECRET_FILE: path })).toThrow(
      "unsafe_secret_file",
    );
    chmodSync(path, 0o600);
    const alias = join(root, "alias");
    symlinkSync(path, alias);
    expect(() => loadConfig({ BETTER_AUTH_SECRET_FILE: alias })).toThrow(
      "unsafe_secret_file",
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
