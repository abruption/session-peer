import { afterEach, expect, it } from "vitest";
import { serializeSignedCookie } from "better-call";
import { fixture } from "./fixtures.js";

let f: Awaited<ReturnType<typeof fixture>> | undefined;
afterEach(() => { f?.cleanup(); f = undefined; });

async function claims() {
  f = await fixture();
  const next = await f.context.internalAdapter.createSession(f.owner.id);
  if (!next) throw new Error("fixture_session");
  const otherCookie = (await serializeSignedCookie(f.context.authCookies.sessionToken.name,
    next.token, f.config.secret)).split(";")[0];
  const browsers = [{ cookie: f.cookie, origin: f.config.origin },
    { cookie: otherCookie, origin: f.config.origin }];
  const codes = [];
  for (const browser of browsers) {
    const issued = await f.request("/api/auth/device/code", { client_id: "session-peer-cli" }, {});
    expect(issued.status).toBe(200);
    const code = await issued.json();
    expect((await f.request("/api/auth/device?user_code=" + code.user_code, undefined, browser)).status).toBe(200);
    codes.push(code);
  }
  return { browsers, codes };
}
function state() {
  return ["deviceCode", "relay_device_claims", "session"].map(table =>
    f!.db.prepare(`SELECT * FROM "${table}" ORDER BY id`).all());
}

it.each(["approve", "deny"])("rejects non-JSON transport before %s can process another browser's code", async operation => {
  const { browsers, codes } = await claims();
  expect((await f!.request("/api/auth/device/" + operation, { userCode: codes[1].user_code }, browsers[0])).status).toBe(403);
  const before = state();
  // Probe a possible parse disagreement with two browsers of the same owner:
  // JSON selects the first code; if form parsing were reached, it would select
  // the second field with suffix punctuation normalized by default-code lookup.
  // The pinned JSON-only router must reject this transport before that happens.
  for (const contentType of ["application/x-www-form-urlencoded", "application/x-www-form-urlencoded; charset=UTF-8", "text/plain", ""]) {
    const response = await f!.app(new Request(f!.config.origin + "/api/auth/device/" + operation, {
      method: "POST", headers: { ...browsers[0], ...(contentType ? { "content-type": contentType } : {}) },
      body: JSON.stringify({ userCode: codes[0].user_code, padding: "&userCode=" + codes[1].user_code }),
    }));
    expect(response.status).toBe(415);
    // The pinned router globally restricts media types to JSON before parsing.
    expect(await response.json()).toMatchObject({ code: "UNSUPPORTED_MEDIA_TYPE" });
    expect(state()).toEqual(before);
  }
  const form = await f!.app(new Request(f!.config.origin + "/api/auth/device/" + operation, {
    method: "POST", headers: { ...browsers[0], "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ userCode: codes[1].user_code }),
  }));
  expect(form.status).toBe(400);
  expect(await form.json()).toEqual({ error: "invalid_user_code" });
  expect(state()).toEqual(before);
});

it("rejects repeated verify query keys without processing the second browser's code", async () => {
  const { browsers, codes } = await claims();
  const before = state();
  for (const [query, status] of [["user_code=" + codes[0].user_code + "&user_code=" + codes[1].user_code, 400],
    ["user_code=" + codes[1].user_code + "&user_code=" + codes[0].user_code, 403]] as const) {
    const response = await f!.request("/api/auth/device?" + query, undefined, browsers[0]);
    expect(response.status).toBe(status);
  }
  expect(state()).toEqual(before);
});

it.each(["approve", "deny"])("uses the same JSON userCode in the gate and %s handler despite query/body conflicts", async operation => {
  const { browsers, codes } = await claims();
  const before = state();
  const duplicate = await f!.app(new Request(f!.config.origin + "/api/auth/device/" + operation, {
    method: "POST", headers: { ...browsers[0], "content-type": "application/json; charset=UTF-8" },
    body: '{"userCode":' + JSON.stringify(codes[0].user_code) + ',"userCode":' + JSON.stringify(codes[1].user_code) + '}',
  }));
  // Both JSON readers select the final duplicate key, whose original browser
  // claim prevents this same-owner session from deciding it.
  expect(duplicate.status).toBe(403);
  expect(await duplicate.json()).toEqual({ error: "code_not_claimed_by_this_session" });
  expect(state()).toEqual(before);
  const raw = codes[0].user_code.replace(/[^A-Z0-9]/gi, "").toLowerCase();
  const normalizedInput = raw.slice(0, 4) + " - " + raw.slice(4);
  const decision = await f!.request("/api/auth/device/" + operation + "?userCode=" + codes[1].user_code +
    "&user_code=" + codes[1].user_code, { userCode: normalizedInput, padding: "&userCode=" + codes[1].user_code }, browsers[0]);
  expect(decision.status).toBe(200);
  expect(await decision.json()).toEqual({ success: true });
  const status = (code: string) => (f!.db.prepare("SELECT status FROM deviceCode WHERE userCode=?")
    .get(code.replace(/[^A-Z0-9]/gi, "").toUpperCase()) as { status: string }).status;
  expect(status(codes[0].user_code)).toBe(operation === "approve" ? "approved" : "denied");
  expect(status(codes[1].user_code)).toBe("pending");
});
