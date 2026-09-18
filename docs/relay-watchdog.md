# Control watchdog and relay recovery (RC candidate)

`Upholds=` can restart a stopped relay, but cannot detect a frozen control process
that systemd still considers active. The control application therefore participates
in the systemd watchdog. This is optional outside systemd and adds no Python or
Node package dependency. It requires `/usr/bin/systemd-notify` on the service host.

Use `Type=notify`, `NotifyAccess=all`, `WatchdogSec=30`, and
`WatchdogSignal=SIGKILL`. Launch Node with `flock --no-fork --nonblock` so Node
is the main PID and matches `WATCHDOG_PID`. The existing exclusive writer lock
remains held. A different watchdog PID or incomplete watchdog configuration is
a startup error, not silent disabling. The executable must be a root-owned Node
runtime outside homes hidden by `ProtectHome`.

After the loopback listener starts, control sends `READY=1` and `WATCHDOG=1`
only when its health check passes. At most every five seconds (or one third of
the configured watchdog period), the same event loop checks:

- the publisher has not failed and the listener is running;
- the latest successful public state is within its 180-second validity period
  and is not more than five seconds in the future;
- the regular state file still exactly matches that publication;
- the control database revision equals the published revision.

The HTTP `/healthz` endpoint uses the same state checks. Failed reads, missing or
changed state, a failed publisher and unhealthy checks do not send heartbeats.
A frozen event loop cannot send them either. No successful OAuth request or
native agent delivery is implied by these checks.

Notifications use a shell-free, single-flight child process with a two-second
timeout and `SIGKILL` termination. Only `NOTIFY_SOCKET` is passed in its environment;
OAuth configuration, tokens and credential paths are not inherited. The notifier
does not set `MAINPID` or use `--no-block`: systemd-notify's acknowledgement avoids
exiting before systemd attributes the notification. `NotifyAccess=all` permits
this child inside the unit's cgroup to notify; it does not authorize other units.
Shutdown stops scheduling heartbeats; an already running notifier is bounded by
the same two-second timeout.

The operator's coordinated stack must still connect control's failure to relay
termination (`BindsTo`/ordering), and restart relay only after a fresh readiness
check (`Upholds`/ordering). A 30-second watchdog is bounded failure detection,
not immediate health detection or a replacement for Python state validation and
live revocation checks. Keep startup, restart and rate limits explicit. Migration
and replay initialization must never become automatic recovery dependencies.

Before public application, use the exact compiled candidate and actual sandbox to
verify main PID attribution, healthy operation longer than the watchdog period,
control cgroup SIGSTOP, persistent unhealthy state, SIGKILL, fresh readiness after
automatic restart, relay crash, explicit stack stop, and restart limits. Preserve
all keys, operation receipts, replay evidence and revision high-water marks.
Neither restarting nor letting a counter catch up establishes safe backup recovery.

Local unit tests cover notification gating, failure, bounded concurrency, environment
isolation and state health checks. They do not establish actual systemd notification
delivery or the SIGSTOP recovery gate; that requires the KR runtime experiment.

References: [systemd v255 notification semantics](https://github.com/systemd/systemd/blob/v255/man/systemd-notify.xml)
and [service watchdog options](https://github.com/systemd/systemd/blob/v255/man/systemd.service.xml).
