import { timingSafeEqual } from "node:crypto";
import { isIP } from "node:net";

function canonicalIP(value: string): string | undefined {
  if (value.includes("%")) return undefined;
  if (isIP(value) === 4) return value;
  if (isIP(value) !== 6) return undefined;
  const normalized = new URL(`http://[${value}]/`).hostname.slice(1, -1);
  if (normalized.startsWith("::ffff:")) {
    const groups = normalized.slice(7).split(":");
    if (groups.length === 2) {
      const n = groups.map((part) => parseInt(part, 16));
      return [n[0] >> 8, n[0] & 255, n[1] >> 8, n[1] & 255].join(".");
    }
  }
  return normalized;
}

export function sanitizeClientIP(headers: Headers, remote: string | undefined, secret?: string): void {
  const socketIP = canonicalIP(remote ?? "") ?? "unknown";
  const token = headers.get("x-session-peer-proxy-token") ?? "";
  const clientIP = canonicalIP(headers.get("x-session-peer-client-ip") ?? "");
  const loopback = socketIP === "::1" || socketIP.startsWith("127.");
  const authorized = secret && loopback && Buffer.byteLength(token) === Buffer.byteLength(secret)
    && timingSafeEqual(Buffer.from(token), Buffer.from(secret));
  // The proxy must overwrite BOTH dedicated headers, not append client input.
  // X-Forwarded-For, CF-Connecting-IP and the internal header never authorize it.
  headers.set("x-session-peer-ip", authorized && clientIP ? clientIP : socketIP);
  headers.delete("x-session-peer-proxy-token");
  headers.delete("x-session-peer-client-ip");
}
