import { it, expect } from "vitest";
import { mkdtempSync, rmSync, readFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn, execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";
it("starts real compiled server only on loopback; enforces host, body limit and static/API behavior without OAuth", async () => {
  const root = mkdtempSync(join(tmpdir(), "sp-control-http-"));
  const port = 38771;
  const origin = `http://127.0.0.1:${port}`;
  const env = {
    ...process.env,
    NODE_ENV: "development",
    BETTER_AUTH_SECRET: randomBytes(32).toString("base64url"),
    SESSION_PEER_CONTROL_ORIGIN: origin,
    SESSION_PEER_CONTROL_DATA: join(root, "private"),
    SESSION_PEER_RELAY_PUBLIC: join(root, "public"),
    SESSION_PEER_ALLOWED_ACCOUNTS: "[]",
    PORT: String(port),
  };
  const serverPath = fileURLToPath(
    new URL("../dist/server/main.js", import.meta.url),
  );
  // This is a fixture database/secret under a private temp dir, never an OAuth mock.
  execFileSync(
    process.execPath,
    [
      fileURLToPath(
        new URL("../node_modules/tsx/dist/cli.mjs", import.meta.url),
      ),
      fileURLToPath(new URL("../src/server/migrate.ts", import.meta.url)),
    ],
    { env, stdio: "pipe" },
  );
  const child = spawn(process.execPath, [serverPath], {
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let logs = "";
  child.stdout.on("data", (x) => (logs += x));
  child.stderr.on("data", (x) => (logs += x));
  try {
    let ready = false;
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 50));
      if (logs.includes("loopback only")) {
        ready = true;
        break;
      }
    }
    expect(ready).toBe(true);
    expect((await fetch(origin + "/healthz")).status).toBe(200);
    const html = await (await fetch(origin + "/login")).text();
    expect(html).toContain('id="root"');
    expect(await (await fetch(origin + "/admin/metrics")).text()).toContain('id="root"');
    const asset = /src="([^"]+\.js)"/.exec(html)![1];
    expect((await fetch(origin + asset)).status).toBe(200);
    const webAssets = fileURLToPath(
      new URL("../dist/web/assets/", import.meta.url),
    );
    const googleButton = readdirSync(webAssets).find(
      (name) => /^google-signin-dark-2x-[A-Za-z0-9_-]+\.png$/.test(name),
    );
    expect(googleButton).toBeTruthy();
    const imageResponse = await fetch(origin + "/assets/" + googleButton);
    expect(imageResponse.status).toBe(200);
    expect(imageResponse.headers.get("content-type")).toBe("image/png");
    expect((await fetch(origin + "/api/relay/devices")).status).toBe(401);
    expect((await fetch(origin + "/api/admin/metrics")).status).toBe(401);
    const { request } = await import("node:http");
    const hostStatus = await new Promise<number>((resolve, reject) => {
      const r = request(
        origin + "/healthz",
        { headers: { host: "attacker.invalid" } },
        (res) => {
          res.resume();
          resolve(res.statusCode!);
        },
      );
      r.on("error", reject);
      r.end();
    });
    expect(hostStatus).toBe(400);
    expect(
      (
        await fetch(origin + "/api/relay/challenge", {
          method: "POST",
          body: "x".repeat(17000),
        })
      ).status,
    ).toBe(413);
    const signedOut = await fetch(origin + "/api/auth/sign-out", {
      method: "POST",
      headers: { origin, "content-type": "application/json" },
      body: "{}",
    });
    expect(signedOut.status).toBe(200);
    expect(signedOut.headers.getSetCookie().length).toBeGreaterThan(1);
    let limited = false;
    for (let i = 0; i < 70; i++) {
      const attempt = await fetch(origin + "/api/auth/device/code", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-session-peer-ip": "198.51.100." + (i + 1),
          "x-forwarded-for": "198.51.100." + (i + 1),
        },
        body: JSON.stringify({ client_id: "session-peer-cli" }),
      });
      if (attempt.status === 429) {
        limited = true;
        break;
      }
    }
    expect(limited).toBe(true);
    const bypass = await fetch(origin + "/api/auth/device/code", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-session-peer-ip": "203.0.113.1",
      },
      body: JSON.stringify({ client_id: "session-peer-cli" }),
    });
    expect(bypass.status).toBe(429);
    const state = JSON.parse(
      readFileSync(join(root, "public", "state.json"), "utf8"),
    );
    expect(state.expiresAt - state.issuedAt).toBe(180);
    expect(state.devices).toEqual({});
    expect(logs).not.toContain(env.BETTER_AUTH_SECRET);
  } finally {
    child.kill("SIGTERM");
    await new Promise<void>((resolve) => child.once("exit", () => resolve()));
    rmSync(root, { recursive: true, force: true });
  }
}, 15000);
