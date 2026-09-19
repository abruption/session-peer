import { afterEach, expect, it, vi } from "vitest";
import { createWatchdog, notifySystemd } from "../src/server/watchdog.js";
import { execFile } from "node:child_process";

vi.mock("node:child_process", () => ({ execFile: vi.fn() }));
afterEach(() => { vi.useRealTimers(); vi.clearAllMocks(); });
const env = { NOTIFY_SOCKET: "/run/systemd/notify", WATCHDOG_USEC: "30000000", WATCHDOG_PID: "123" };

it("is inert without systemd, and rejects invalid watchdog or a wrapper PID", async () => {
  const notify = vi.fn();
  await createWatchdog(() => true, {}, notify).start();
  expect(notify).not.toHaveBeenCalled();
  for (const bad of [
    { ...env, WATCHDOG_PID: "124" }, { ...env, WATCHDOG_USEC: "NaN" },
    { ...env, WATCHDOG_USEC: "1000" }, { ...env, NOTIFY_SOCKET: "" },
  ]) expect(() => createWatchdog(() => true, bad, notify, 123)).toThrow("invalid_systemd_watchdog_configuration");
});

it("notifies ready only when healthy, stops heartbeats on health loss and shutdown", async () => {
  vi.useFakeTimers();
  let healthy = true;
  const notify = vi.fn(async () => {});
  const w = createWatchdog(() => healthy, env, notify, 123);
  await w.start();
  expect(notify).toHaveBeenLastCalledWith(env.NOTIFY_SOCKET, ["READY=1", "WATCHDOG=1"]);
  await vi.advanceTimersByTimeAsync(5000);
  expect(notify).toHaveBeenLastCalledWith(env.NOTIFY_SOCKET, ["WATCHDOG=1"]);
  healthy = false;
  await vi.advanceTimersByTimeAsync(30000);
  expect(notify).toHaveBeenCalledTimes(2);
  healthy = true;
  w.stop();
  await vi.advanceTimersByTimeAsync(30000);
  expect(notify).toHaveBeenCalledTimes(2);
});

it("never announces ready for an unhealthy state or a failed notification", async () => {
  const notify = vi.fn(async () => { throw new Error("fixture_failure"); });
  await expect(createWatchdog(() => false, env, notify, 123).start()).rejects.toThrow("control_unhealthy");
  expect(notify).not.toHaveBeenCalled();
  await expect(createWatchdog(() => true, env, notify, 123).start()).rejects.toThrow("fixture_failure");
});

it("bounds concurrent notifiers even when a notification stalls", async () => {
  vi.useFakeTimers();
  let finish!: () => void;
  const notify = vi.fn(async () => {});
  const w = createWatchdog(() => true, env, notify, 123);
  await w.start();
  notify.mockImplementationOnce(() => new Promise<void>(r => { finish = r; }));
  await vi.advanceTimersByTimeAsync(30000);
  expect(notify).toHaveBeenCalledTimes(2);
  w.stop(); finish();
  await vi.advanceTimersByTimeAsync(30000);
  expect(notify).toHaveBeenCalledTimes(2);
});

it("passes no secrets to a bounded shell-free notifier, with no PID reassignment", async () => {
  vi.mocked(execFile).mockImplementation(((file: string, fields: string[], options: any, callback: any) => {
    expect(file).toBe("/usr/bin/systemd-notify");
    expect(fields).toEqual(["WATCHDOG=1"]);
    expect(options.env).toEqual({ NOTIFY_SOCKET: env.NOTIFY_SOCKET });
    expect(options.timeout).toBe(2000);
    expect(options.killSignal).toBe("SIGKILL");
    expect(options.shell).toBeUndefined();
    callback(null);
  }) as typeof execFile);
  await notifySystemd(env.NOTIFY_SOCKET, ["WATCHDOG=1"]);
});

it("reports notifier failure without child diagnostics or environment", async () => {
  vi.mocked(execFile).mockImplementation(((file: any, args: any, options: any, callback: any) => {
    callback(new Error("fixture-sensitive-output"));
  }) as typeof execFile);
  await expect(notifySystemd(env.NOTIFY_SOCKET, ["WATCHDOG=1"]))
    .rejects.toThrow("systemd_notification_failed");
});
