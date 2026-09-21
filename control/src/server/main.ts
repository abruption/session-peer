import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { loadConfig } from "./config.js";
import { openDatabase } from "./storage.js";
import { createAuth } from "./auth.js";
import { RelayControl } from "./relay-control.js";
import { createAdminMetricsApp, createApp } from "./app.js";
import { createWatchdog } from "./watchdog.js";
import { validateFirstPartySchema } from "./migrations.js";
process.umask(0o077);
const config = loadConfig();
const db = openDatabase(config.dataDir);
validateFirstPartySchema(db);
const auth = createAuth(db, config);
const control = new RelayControl(db, config);
const app = createApp(
  auth,
  db,
  control,
  config,
  fileURLToPath(new URL("../web/", import.meta.url)),
);
const port = Number(process.env.PORT ?? 3770);
if (!Number.isSafeInteger(port) || port < 1024 || port > 65535)
  throw new Error("invalid_port");
const adminPortText = process.env.SESSION_PEER_ADMIN_PORT;
if (!!config.adminOrigin !== !!adminPortText)
  throw new Error("incomplete_admin_listener_configuration");
const adminPort = adminPortText ? Number(adminPortText) : undefined;
if (
  adminPort !== undefined &&
  (!Number.isSafeInteger(adminPort) ||
    adminPort < 1024 ||
    adminPort > 65535 ||
    adminPort === port)
)
  throw new Error("invalid_admin_port");
const server = createServer(async (incoming, outgoing) => {
  try {
    if (incoming.headers.host !== new URL(config.origin).host) {
      outgoing.writeHead(400);
      outgoing.end();
      return;
    }
    if (!incoming.url?.startsWith("/") || incoming.url.startsWith("//")) {
      outgoing.writeHead(400);
      outgoing.end();
      return;
    }
    const chunks: Buffer[] = [];
    let size = 0;
    for await (const chunk of incoming) {
      size += Buffer.byteLength(chunk);
      if (size > 16384) {
        outgoing.writeHead(413);
        outgoing.end();
        return;
      }
      chunks.push(Buffer.from(chunk));
    }
    const headers = new Headers();
    for (const [k, v] of Object.entries(incoming.headers)) {
      if (Array.isArray(v)) v.forEach((value) => headers.append(k, value));
      else if (v) headers.set(k, v);
    }
    headers.set(
      "x-session-peer-ip",
      incoming.socket.remoteAddress ?? "127.0.0.1",
    );
    const method = incoming.method ?? "GET";
    const body = ["GET", "HEAD"].includes(method)
      ? undefined
      : Buffer.concat(chunks);
    const response = await app(
      new Request(config.origin + incoming.url, { method, headers, body }),
    );
    const responseHeaders = Object.fromEntries(
      [...response.headers.entries()].filter(([name]) => name !== "set-cookie"),
    );
    const cookies = response.headers.getSetCookie();
    if (cookies.length) outgoing.setHeader("set-cookie", cookies);
    outgoing.writeHead(response.status, responseHeaders);
    outgoing.end(Buffer.from(await response.arrayBuffer()));
  } catch {
    outgoing.writeHead(500, { "content-type": "application/json" });
    outgoing.end('{"error":"internal_error"}');
  }
});
const adminApp = config.adminOrigin
  ? createAdminMetricsApp(db, control, config)
  : undefined;
const adminServer = adminApp
  ? createServer(async (incoming, outgoing) => {
      try {
        if (
          !["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(
            incoming.socket.remoteAddress ?? "",
          ) ||
          incoming.headers.host !== new URL(config.adminOrigin!).host
        ) {
          outgoing.writeHead(400);
          outgoing.end();
          return;
        }
        if (!incoming.url?.startsWith("/") || incoming.url.startsWith("//")) {
          outgoing.writeHead(400);
          outgoing.end();
          return;
        }
        const method = incoming.method ?? "GET";
        const response = await adminApp(
          new Request(config.adminOrigin! + incoming.url, { method }),
        );
        outgoing.writeHead(
          response.status,
          Object.fromEntries(response.headers),
        );
        outgoing.end(Buffer.from(await response.arrayBuffer()));
      } catch {
        outgoing.writeHead(500, { "content-type": "application/json" });
        outgoing.end('{"error":"internal_error"}');
      }
    })
  : undefined;
const watchdog = createWatchdog(
  () =>
    server.listening &&
    (!adminServer || adminServer.listening) &&
    control.isHealthy(),
);
server.requestTimeout = 10000;
server.headersTimeout = 10000;
server.maxHeadersCount = 50;
if (adminServer) {
  adminServer.requestTimeout = 5000;
  adminServer.headersTimeout = 5000;
  adminServer.maxHeadersCount = 20;
}
const timer = setInterval(() => {
  try {
    control.publish();
  } catch {
    console.error("relay_state_refresh_failed");
  }
}, 60000);
timer.unref();
function ready() {
  void watchdog.start().then(() => {
    console.log("session-peer control ready (loopback only)");
  }).catch(() => {
    console.error("control_watchdog_start_failed");
    process.exit(1);
  });
}
server.listen(port, "127.0.0.1", () => {
  if (adminServer) adminServer.listen(adminPort!, "127.0.0.1", ready);
  else ready();
});
function stop() {
  watchdog.stop();
  clearInterval(timer);
  let open = adminServer ? 2 : 1;
  const closed = () => {
    if (--open === 0) {
      db.close();
      process.exit(0);
    }
  };
  server.close(closed);
  adminServer?.close(closed);
}
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
