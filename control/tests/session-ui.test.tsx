import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { SessionList } from "../src/web/session-list.js";

it("renders account session metadata safely with revocation only for other logins", () => {
  const sessions = [
    { id: "opaque-current", current: true, userAgent: "Browser", createdAt: "2026-10-03T00:00:00.000Z", expiresAt: "2026-10-04T00:00:00.000Z" },
    { id: "opaque-cli", current: false, userAgent: '<script>alert("untrusted")</script>', createdAt: "2026-10-03T01:00:00.000Z", expiresAt: "2026-10-04T01:00:00.000Z" },
  ];
  const html = renderToStaticMarkup(<SessionList sessions={sessions} busy={false} revoke={() => {}} />);
  expect(html).toContain("This browser");
  expect(html).toContain("Other login");
  expect(html.match(/<button/g)).toHaveLength(1);
  expect(html).toContain("&lt;script&gt;");
  expect(html).not.toContain("<script>");
  expect(html).not.toContain("opaque-current");
  expect(html).not.toContain("opaque-cli");
  expect(html).toContain('dateTime="2026-10-04T01:00:00.000Z"');
  expect(renderToStaticMarkup(<SessionList sessions={sessions} busy={true} revoke={() => {}} />)).toContain('disabled=""');
});
