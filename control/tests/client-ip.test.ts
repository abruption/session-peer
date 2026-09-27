import { expect, it } from "vitest";
import { sanitizeClientIP } from "../src/server/client-ip.js";
import { fixture } from "./fixtures.js";
import { loadConfig } from "../src/server/config.js";
import { mkdtempSync, writeFileSync, chmodSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
const secret = "fixture-only-not-a-real-proxy-token";
it("requires a private, well-formed opt-in proxy credential", () => {
  const root = mkdtempSync(join(tmpdir(), "proxy-config-"));
  const path = join(root, "fixture-token");
  const env = { BETTER_AUTH_SECRET: "x".repeat(40), SESSION_PEER_TRUSTED_PROXY_TOKEN_FILE: path };
  try {
    writeFileSync(path, secret, {mode: 0o600});
    expect(loadConfig(env).trustedProxyToken).toBe(secret);
    writeFileSync(path, "invalid token");
    expect(() => loadConfig(env)).toThrow("invalid_proxy_token");
    writeFileSync(path, secret);
    chmodSync(path, 0o644);
    expect(() => loadConfig(env)).toThrow("unsafe_secret_file");
  } finally { rmSync(root, {recursive: true}); }
});
function headers(ip: string, token = secret, remote = "127.0.0.1", configured: string | undefined = secret) {
  const h = new Headers({ "x-session-peer-client-ip": ip, "x-session-peer-proxy-token": token,
    "x-forwarded-for": "192.0.2.99", "cf-connecting-ip": "192.0.2.98", "x-session-peer-ip": "192.0.2.97" });
  sanitizeClientIP(h, remote, configured);
  expect(h.has("x-session-peer-proxy-token")).toBe(false);
  expect(h.has("x-session-peer-client-ip")).toBe(false);
  return h;
}
it("requires an authenticated loopback proxy and one valid canonical IP", () => {
  expect(headers("192.0.2.1").get("x-session-peer-ip")).toBe("192.0.2.1");
  expect(headers("192.0.2.1", "wrong").get("x-session-peer-ip")).toBe("127.0.0.1");
  expect(headers("192.0.2.1", secret, "192.0.2.10").get("x-session-peer-ip")).toBe("192.0.2.10");
  const unconfigured = new Headers({"x-session-peer-proxy-token": secret, "x-session-peer-client-ip": "192.0.2.1"});
  sanitizeClientIP(unconfigured, "127.0.0.1");
  expect(unconfigured.get("x-session-peer-ip")).toBe("127.0.0.1");
  for (const ip of ["", "192.0.2.1, 192.0.2.2", "hostname", "::1%lo0", "192.0.2.1:80"])
    expect(headers(ip).get("x-session-peer-ip")).toBe("127.0.0.1");
  expect(headers("2001:0db8:0:0:0:0:0:1").get("x-session-peer-ip")).toBe("2001:db8::1");
  expect(headers("::ffff:192.0.2.1").get("x-session-peer-ip")).toBe("192.0.2.1");
});
it("isolates trusted clients while retaining per-client endpoint 429s", async () => {
  const f = await fixture();
  try {
    const request = (ip: string) => f.request("/api/auth/device/code", {client_id: "session-peer-cli"},
      Object.fromEntries(headers(ip)));
    for (let i = 0; i < 60; i++) expect((await request("192.0.2.220")).status).toBe(200);
    expect((await request("192.0.2.220")).status).toBe(429);
    expect((await request("192.0.2.221")).status).toBe(200);
  } finally { f.cleanup(); }
});
