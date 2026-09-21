import { expect, it } from "vitest";
import { BoundedRateLimiter } from "../src/server/app.js";

it("bounds user buckets, prunes expiry, and resets with a new process instance", () => {
  let now = 1_000;
  const limiter = new BoundedRateLimiter(2, 100, 2, () => now);
  expect(limiter.check("one")).toBe(true);
  expect(limiter.check("one")).toBe(true);
  expect(limiter.check("one")).toBe(false);
  expect(limiter.check("two")).toBe(true);
  expect(limiter.size).toBe(2);
  expect(limiter.check("three")).toBe(false);
  expect(limiter.size).toBe(2);
  now += 100;
  expect(limiter.check("three")).toBe(true);
  expect(limiter.size).toBe(1);
  const restarted = new BoundedRateLimiter(2, 100, 2, () => now);
  expect(restarted.check("one")).toBe(true);
  expect(restarted.size).toBe(1);
});
