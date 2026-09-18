import { execFile } from "node:child_process";

// No shell, inherited OAuth environment, detached helper, or PID reassignment.
export function notifySystemd(socket: string, fields: string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    execFile("/usr/bin/systemd-notify", fields, {
      env: { NOTIFY_SOCKET: socket }, timeout: 2000, killSignal: "SIGKILL",
      maxBuffer: 1024,
    }, error => error ? reject(new Error("systemd_notification_failed")) : resolve());
  });
}

export function createWatchdog(
  healthy: () => boolean,
  env: NodeJS.ProcessEnv = process.env,
  notify: typeof notifySystemd = notifySystemd,
  pid = process.pid,
) {
  const socket = env.NOTIFY_SOCKET;
  const usec = Number(env.WATCHDOG_USEC);
  if (!socket && !env.WATCHDOG_USEC) return { start: async () => {}, stop: () => {} };
  if (!socket || !/^[0-9]+$/.test(env.WATCHDOG_USEC ?? "")
      || !Number.isSafeInteger(usec) || usec < 3000000
      || (env.WATCHDOG_PID !== undefined && env.WATCHDOG_PID !== String(pid)))
    throw new Error("invalid_systemd_watchdog_configuration");
  let stopped = false;
  let started = false;
  let busy = false;
  let timer: ReturnType<typeof setInterval> | undefined;
  async function pulse(ready: boolean) {
    if (stopped || busy) return;
    busy = true;
    try {
      if (!healthy()) throw new Error("control_unhealthy");
      await notify(socket!, ready ? ["READY=1", "WATCHDOG=1"] : ["WATCHDOG=1"]);
    } finally { busy = false; }
  }
  return {
    async start() {
      if (started || stopped) throw new Error("watchdog_already_started_or_stopped");
      started = true;
      await pulse(true);
      if (stopped) return;
      timer = setInterval(() => {
        // No synthetic heartbeat after failure: let systemd's deadline expire.
        void pulse(false).catch(() => {});
      }, Math.min(5000, Math.floor(usec / 3000)));
      timer.unref();
    },
    stop() { stopped = true; if (timer) clearInterval(timer); },
  };
}
