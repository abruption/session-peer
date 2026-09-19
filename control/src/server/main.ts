import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { loadConfig } from "./config.js";
import { openDatabase } from "./storage.js";
import { createAuth } from "./auth.js";
import { RelayControl } from "./relay-control.js";
import { createApp } from "./app.js";
import { createWatchdog } from "./watchdog.js";
process.umask(0o077);
const config = loadConfig();
const db = openDatabase(config.dataDir);
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
const watchdog = createWatchdog(() => server.listening && control.isHealthy());
server.requestTimeout = 10000;
server.headersTimeout = 10000;
server.maxHeadersCount = 50;
const timer = setInterval(() => {
  try {
    control.publish();
  } catch {
    console.error("relay_state_refresh_failed");
  }
}, 60000);
timer.unref();
server.listen(port, "127.0.0.1", () => {
  void watchdog.start().then(() => {
    console.log("session-peer control ready (loopback only)");
  }).catch(() => {
    console.error("control_watchdog_start_failed");
    process.exit(1);
  });
});
function stop() {
  watchdog.stop();
  clearInterval(timer);
  server.close(() => {
    db.close();
    process.exit(0);
  });
}
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
