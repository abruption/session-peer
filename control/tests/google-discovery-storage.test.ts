import { it, expect } from "vitest";
import * as fs from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { publishGoogleDiscovery, confirmGoogleDiscovery } from "../src/server/google-discovery.js";
import type { Config } from "../src/server/config.js";

function sample(root: string) {
  const config: Config = { origin: "https://relay.test", production: true,
    secret: "test-only-secret", dataDir: root, publicDir: join(root, "unused"),
    allowlist: [], providers: { google: { clientId: "fixture-client", clientSecret: "fixture-secret" } },
    googleDiscovery: { expectedEmail: "test@example.invalid", expiresAt: Math.floor(Date.now()/1000)+600 } };
  const record = { schemaVersion: 1, provider: "google", accountId: "fixture-subject",
    expectedEmail: config.googleDiscovery!.expectedEmail, verifiedAt: Math.floor(Date.now()/1000),
    issuer: "https://accounts.google.com", clientId: "fixture-client" };
  return { config, record };
}

it.each(["write", "file-sync", "link"])("does not expose a partial result after %s failure and permits retry", (phase) => {
  const root = fs.mkdtempSync(join(tmpdir(), "discovery-fault-"));
  try {
    const { record, config } = sample(root);
    const io = { ...fs,
      writeFileSync: ((fd: number, data: string) => {
        if (phase === "write") { fs.writeSync(fd, "{"); throw new Error("injected"); }
        fs.writeFileSync(fd, data);
      }) as typeof fs.writeFileSync,
      fsyncSync: (fd: number) => {
        if (phase === "file-sync" && fs.fstatSync(fd).isFile()) throw new Error("injected");
        fs.fsyncSync(fd);
      },
      linkSync: (source: fs.PathLike, target: fs.PathLike) => {
        if (phase === "link") throw new Error("injected");
        fs.linkSync(source, target);
      },
    };
    expect(() => publishGoogleDiscovery(root, record, io)).toThrow("injected");
    expect(fs.existsSync(join(root, "google-account-discovery.json"))).toBe(false);
    expect(fs.readdirSync(root)).toEqual([]);
    publishGoogleDiscovery(root, record);
    expect(confirmGoogleDiscovery(config).persistenceConfirmed).toBe(true);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

it("keeps a complete record after directory-sync ambiguity; explicit confirmation persists it without replacement", () => {
  const root = fs.mkdtempSync(join(tmpdir(), "discovery-sync-"));
  try {
    const { record, config } = sample(root);
    expect(() => publishGoogleDiscovery(root, record, { ...fs, fsyncSync(fd) {
      if (fs.fstatSync(fd).isDirectory()) throw new Error("directory-sync");
      fs.fsyncSync(fd);
    } })).toThrow("directory-sync");
    const path = join(root, "google-account-discovery.json");
    const first = fs.readFileSync(path, "utf8");
    expect(JSON.parse(first)).toEqual(record);
    expect(() => publishGoogleDiscovery(root, { ...record, accountId: "replacement" })).toThrow();
    expect(fs.readFileSync(path, "utf8")).toBe(first);
    expect(confirmGoogleDiscovery(config)).toMatchObject({ persistenceConfirmed: true, accountId: record.accountId });
    fs.chmodSync(path, 0o644);
    expect(() => confirmGoogleDiscovery(config)).toThrow("unsafe_discovery_record");
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
