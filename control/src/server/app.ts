import { readFile } from "node:fs/promises";
import { resolve, join, extname } from "node:path";
import type Database from "better-sqlite3";
import { allowedUser, operatorUser, type Auth } from "./auth.js";
import type { Config } from "./config.js";
import {
  adminMetricDetails,
  adminMetrics,
  relayMetrics,
  type AdminDetailFilter,
  type AdminDetailView,
} from "./metrics.js";
import { ControlError, assert } from "./protocol.js";
import type { RelayControl } from "./relay-control.js";
const MAX_BODY = 16384;
export class BoundedRateLimiter {
  private readonly buckets = new Map<string, { start: number; count: number }>();
  constructor(
    private readonly limit = 60,
    private readonly windowMs = 60_000,
    private readonly maxEntries = 4096,
    private readonly now: () => number = Date.now,
  ) {
    if (limit < 1 || windowMs < 1 || maxEntries < 1)
      throw new Error("invalid_rate_limiter");
  }
  check(key: string) {
    const now = this.now();
    for (const [candidate, bucket] of this.buckets)
      if (now - bucket.start >= this.windowMs) this.buckets.delete(candidate);
    let bucket = this.buckets.get(key);
    if (!bucket) {
      if (this.buckets.size >= this.maxEntries) return false;
      bucket = { start: now, count: 0 };
      this.buckets.set(key, bucket);
    }
    bucket.count++;
    return bucket.count <= this.limit;
  }
  get size() { return this.buckets.size; }
}
export function sameOrigin(request: Request, origin: string) {
  const supplied = request.headers.get("origin");
  return (
    supplied === origin ||
    (!supplied &&
      request.headers.get("sec-fetch-site") === "same-origin" &&
      new URL(request.url).origin === origin)
  );
}

/** Aggregate-only endpoint for a separate loopback listener behind Authelia. */
export function createAdminMetricsApp(
  db: Database.Database,
  control: RelayControl,
  config: Config,
) {
  if (!config.adminOrigin) throw new Error("admin_origin_required");
  return async function handleAdminMetrics(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const headers = {
      "cache-control": "no-store",
      "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
      "content-type": "application/json",
      "referrer-policy": "no-referrer",
      "x-content-type-options": "nosniff",
      "x-frame-options": "DENY",
    };
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status, headers });
    if (url.origin !== config.adminOrigin)
      return json({ error: "invalid_origin" }, 400);
    if (url.pathname !== "/session-peer/api/metrics")
      return json({ error: "not_found" }, 404);
    if (request.method !== "GET")
      return json({ error: "method_not_allowed" }, 405);
    const view = url.searchParams.get("view");
    if (!view) {
      const relay = await relayMetrics(config);
      return json(adminMetrics(
        db, config,
        control.isHealthy() && (!config.relayMetricsUrl || relay.available),
        Date.now(), relay,
      ));
    }
    if (
      !["users", "signups", "devices", "operations"].includes(view) ||
      [...url.searchParams.keys()].some((key) => !["view", "filter"].includes(key))
    )
      return json({ error: "invalid_detail_query" }, 400);
    const filter = url.searchParams.get("filter") ?? "all";
    const filters: Record<AdminDetailView, string[]> = {
      users: ["all"],
      signups: ["all", "active", "pending"],
      devices: ["all", "active", "revoked"],
      operations: ["all", "committed", "pending"],
    };
    if (!filters[view as AdminDetailView].includes(filter))
      return json({ error: "invalid_detail_query" }, 400);
    return json(
      adminMetricDetails(
        db,
        view as AdminDetailView,
        filter as AdminDetailFilter,
      ),
    );
  };
}
export function createApp(
  auth: Auth,
  db: Database.Database,
  control: RelayControl,
  config: Config,
  webDir: string,
) {
  const rates = new BoundedRateLimiter();
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  async function handle(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    if (url.origin !== config.origin)
      return json({ error: "invalid_origin" }, 400);
    if (path === "/healthz") {
      const healthy = control.isHealthy();
      return json({ ok: healthy }, healthy ? 200 : 503);
    }
    if (path === "/api/control/config" && request.method === "GET")
      return json({ providers: Object.keys(config.providers) });
    if (path === "/api/control/me" && request.method === "GET") {
      const session = await auth.api.getSession({ headers: request.headers });
      assert(session && allowedUser(db, config, session.user.id), "authentication_required", 401);
      return json({ admin: operatorUser(db, config, session.user.id) });
    }
    if (path === "/api/admin/metrics" && request.method === "GET") {
      assert(
        request.headers.has("cookie") && !request.headers.has("authorization"),
        "browser_session_required",
        401,
      );
      const session = await auth.api.getSession({ headers: request.headers });
      assert(session, "authentication_required", 401);
      assert(operatorUser(db, config, session.user.id), "admin_required", 403);
      return json(adminMetrics(db, config, control.isHealthy()));
    }
    if (path.startsWith("/api/auth/")) {
      const mutating = request.method !== "GET" && request.method !== "HEAD";
      const publicDevice = [
        "/api/auth/device/code",
        "/api/auth/device/token",
      ].includes(path);
      if (
        (mutating && !publicDevice) ||
        [
          "/api/auth/device",
          "/api/auth/device/approve",
          "/api/auth/device/deny",
        ].includes(path)
      )
        assert(sameOrigin(request, config.origin), "csrf_rejected", 403);
      if (publicDevice && request.headers.has("origin"))
        assert(sameOrigin(request, config.origin), "csrf_rejected", 403);
      if (
        [
          "/api/auth/device",
          "/api/auth/device/approve",
          "/api/auth/device/deny",
        ].includes(path)
      ) {
        assert(
          !request.headers.has("authorization") &&
            request.headers.has("cookie"),
          "browser_session_required",
          401,
        );
        const s = await auth.api.getSession({ headers: request.headers });
        assert(
          s && allowedUser(db, config, s.user.id),
          "account_not_allowed",
          403,
        );
        let code: unknown;
        if (path === "/api/auth/device")
          code = url.searchParams.get("user_code");
        else {
          try {
            code = (await request.clone().json()).userCode;
          } catch {
            throw new ControlError("invalid_user_code");
          }
        }
        assert(
          typeof code === "string" && code.length <= 32,
          "invalid_user_code",
        );
        const normalized = code.toUpperCase().replace(/[^A-Z0-9]/g, "");
        const row = db
          .prepare(
            "SELECT id,userId,expiresAt,status FROM deviceCode WHERE userCode=?",
          )
          .get(normalized) as
          | {
              id: string;
              userId: string | null;
              expiresAt: string;
              status: string;
            }
          | undefined;
        const expiresAt = row ? Date.parse(row.expiresAt) : NaN;
        assert(row && expiresAt > Date.now(), "invalid_or_expired_code");
        assert(
          !row.userId || row.userId === s.user.id,
          "code_owned_by_another_user",
          403,
        );
        db.prepare("DELETE FROM relay_device_claims WHERE expiresAt<=?").run(
          Date.now(),
        );
        if (path === "/api/auth/device")
          db.prepare(
            "INSERT OR IGNORE INTO relay_device_claims VALUES (?,?,?,?)",
          ).run(row.id, s.user.id, s.session.id, expiresAt);
        const claim = db
          .prepare(
            "SELECT userId,sessionId FROM relay_device_claims WHERE id=?",
          )
          .get(row.id) as { userId: string; sessionId: string } | undefined;
        assert(
          claim &&
            claim.userId === s.user.id &&
            claim.sessionId === s.session.id,
          "code_not_claimed_by_this_session",
          403,
        );
      }
      assert(
        request.method === "GET" || request.method === "POST",
        "method_not_allowed",
        405,
      );
      return auth.handler(request);
    }
    if (path.startsWith("/api/relay/")) {
      assert(
        request.method === "GET" || request.method === "POST",
        "method_not_allowed",
        405,
      );
      const bearer = request.headers.get("authorization");
      if (request.method === "POST" || request.headers.has("origin")) {
        if (
          bearer &&
          !request.headers.has("cookie") &&
          !request.headers.has("origin")
        )
          assert(/^Bearer [^\s]+$/.test(bearer), "invalid_bearer", 401);
        else assert(sameOrigin(request, config.origin), "csrf_rejected", 403);
      }
      const session = await auth.api.getSession({ headers: request.headers });
      assert(session, "authentication_required", 401);
      assert(
        allowedUser(db, config, session.user.id),
        "account_not_allowed",
        403,
      );
      assert(rates.check(session.user.id), "rate_limited", 429);
      const userId = session.user.id;
      if (path === "/api/relay/devices" && request.method === "GET")
        return json({ devices: control.list(userId) });
      const operation = /^\/api\/relay\/operations\/([a-f0-9-]+)$/.exec(path);
      if (operation && request.method === "GET")
        return json(control.operation(userId, operation[1]));
      if (request.method === "POST") {
        assert(
          request.headers.get("content-type")?.split(";")[0] ===
            "application/json",
          "json_required",
          415,
        );
        const text = await request.text();
        assert(Buffer.byteLength(text) <= MAX_BODY, "body_too_large", 413);
        let body: unknown;
        try {
          body = JSON.parse(text);
        } catch {
          throw new ControlError("invalid_json");
        }
        if (path === "/api/relay/challenge")
          return json(control.challenge(userId, body));
        if (path === "/api/relay/devices")
          return json(control.register(userId, body), 201);
        if (path === "/api/relay/recovery")
          return json(control.recover(userId, body), 201);
        if (path === "/api/relay/admission")
          return json(await control.admit(userId, body));
        const revoke = /^\/api\/relay\/devices\/([a-f0-9]{64})\/revoke$/.exec(
          path,
        );
        if (revoke) return json(control.revoke(userId, revoke[1]));
      }
      return json({ error: "not_found" }, 404);
    }
    if (path.startsWith("/api/")) return json({ error: "not_found" }, 404);
    if (request.method !== "GET" && request.method !== "HEAD")
      return json({ error: "method_not_allowed" }, 405);
    let file: string;
    if (["/", "/login", "/device", "/devices", "/admin/metrics"].includes(path))
      file = join(webDir, "index.html");
    else if (/^\/assets\/[A-Za-z0-9_.-]+$/.test(path))
      file = join(webDir, path);
    else return json({ error: "not_found" }, 404);
    try {
      const data = await readFile(resolve(file));
      const mime: Record<string, string> = {
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".png": "image/png",
        ".svg": "image/svg+xml",
      };
      return new Response(request.method === "HEAD" ? null : data, {
        headers: {
          "content-type": mime[extname(file)] ?? "application/octet-stream",
        },
      });
    } catch {
      return json({ error: "not_found" }, 404);
    }
  }
  return async (request: Request) => {
    let res: Response;
    try {
      res = await handle(request);
    } catch (e) {
      res = json(
        { error: e instanceof ControlError ? e.code : "internal_error" },
        e instanceof ControlError ? e.status : 500,
      );
    }
    res.headers.set("cache-control", "no-store");
    res.headers.set("x-content-type-options", "nosniff");
    res.headers.set("referrer-policy", "no-referrer");
    res.headers.set("x-frame-options", "DENY");
    res.headers.set(
      "content-security-policy",
      "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    );
    if (config.production)
      res.headers.set("strict-transport-security", "max-age=31536000");
    return res;
  };
}
