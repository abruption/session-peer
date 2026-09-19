import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import githubMark from "./assets/github-invertocat-white.svg";
import googleSignIn from "./assets/google-signin-dark@2x.png";
import "./style.css";
async function api<T>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const res = await fetch(path, {
    credentials: "same-origin",
    method: method ?? (body ? "POST" : "GET"),
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok)
    throw new Error(
      res.status === 401
        ? "Sign in to continue."
        : res.status === 403
          ? "This account or request is not permitted."
          : "Request failed or expired. Please try again.",
    );
  return res.json() as Promise<T>;
}
function safeReturn(value: string | null) {
  return value && /^\/(device|devices|admin\/metrics)(?:\?[^#]*)?$/.test(value)
    ? value
    : "/devices";
}
interface Session {
  user: { name: string };
}
interface Device {
  principal: string;
  name: string;
  keyGeneration: number;
  revoked: boolean;
}
interface AdminMetrics {
  generatedAt: number;
  serviceHealthy: boolean;
  signup: {
    mode: "closed" | "open";
    registeredUsers: number;
    publicUsers: number;
    pendingReservations: number;
  };
  devices: { total: number; active: number; revoked: number };
  operations: { total: number; committed: number; pending: number };
  stateRevision: number;
}
function OAuthButton({
  provider,
  onClick,
}: {
  provider: string;
  onClick: () => void;
}) {
  if (provider === "google") {
    return (
      <button
        type="button"
        className="oauth-button google-sign-in"
        aria-label="Sign in with Google"
        onClick={onClick}
      >
        <img src={googleSignIn} alt="" aria-hidden="true" />
      </button>
    );
  }
  return (
    <button
      type="button"
      className="oauth-button github-sign-in"
      onClick={onClick}
    >
      <img src={githubMark} alt="" aria-hidden="true" />
      <span>Sign in with GitHub</span>
    </button>
  );
}
function App() {
  const path = location.pathname;
  const [session, setSession] = useState<Session | null | undefined>();
  const [error, setError] = useState("");
  const [providers, setProviders] = useState<string[]>([]);
  const [admin, setAdmin] = useState(false);
  useEffect(() => {
    api<Session | null>("/api/auth/get-session")
      .then(setSession)
      .catch(() => setSession(null));
    api<{ providers: string[] }>("/api/control/config")
      .then((x) => setProviders(x.providers))
      .catch(() => setError("Service unavailable."));
    api<{ admin: boolean }>("/api/control/me")
      .then((x) => setAdmin(x.admin))
      .catch(() => setAdmin(false));
  }, []);
  async function login(provider: string) {
    try {
      const r = await api<{ url?: string }>("/api/auth/sign-in/social", {
        provider,
        callbackURL:
          location.origin +
          safeReturn(
            new URLSearchParams(location.search).get("returnTo") ??
              location.pathname + location.search,
          ),
      });
      if (r.url) location.assign(r.url);
      else setError("Sign in unavailable.");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  const signingIn = path === "/login" || !session;
  return (
    <>
      <header>
        <a href="/devices" className="brand">
          session-peer <span>relay</span>
        </a>
        <nav>
          {session && (
            <>
              <a href="/devices">Devices</a>
              <a href="/device">Authorize</a>
              {admin && <a href="/admin/metrics">Metrics</a>}
              <button
                onClick={() =>
                  api("/api/auth/sign-out", {})
                    .then(() => location.assign("/login"))
                    .catch(() => setError("Sign out failed."))
                }
              >
                Sign out
              </button>
            </>
          )}
        </nav>
      </header>
      <main className={signingIn ? "login-main" : undefined}>
        <p className="eyebrow">PRIVATE DEVICE NETWORK</p>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {signingIn ? (
          <>
            <h1>
              Your devices,
              <br />
              connected privately.
            </h1>
            <p className="muted">
              Sign in with GitHub or Google to manage your relay devices.
            </p>
            {session === undefined ? (
              <p>Checking session…</p>
            ) : (
              <section className="card">
                <h2>Sign in</h2>
                {providers.length ? (
                  <div className="oauth-buttons">
                    {providers.map((provider) => (
                      <OAuthButton
                        key={provider}
                        provider={provider}
                        onClick={() => login(provider)}
                      />
                    ))}
                  </div>
                ) : (
                  <p>Sign in is not configured. Contact the relay operator.</p>
                )}
                <p className="muted">
                  Accounts are not linked automatically by email.
                </p>
              </section>
            )}
            <p>
              <a
                href={
                  "/login?returnTo=" +
                  encodeURIComponent(location.pathname + location.search)
                }
              >
                Return to sign in
              </a>
            </p>
          </>
        ) : path === "/device" ? (
          <Authorize />
        ) : path === "/admin/metrics" ? (
          <Metrics />
        ) : (
          <Devices />
        )}
      </main>
      <footer>
        End-to-end encrypted relay · Only approve devices you recognize.
      </footer>
    </>
  );
}
function MetricCard({ label, value, note }: { label: string; value: React.ReactNode; note: string }) {
  return (
    <section className="metric-card">
      <p className="metric-label">{label}</p>
      <strong className="metric-value">{value}</strong>
      <p className="muted">{note}</p>
    </section>
  );
}
function Metrics() {
  const [metrics, setMetrics] = useState<AdminMetrics>();
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const refresh = async () => {
    setRefreshing(true);
    try {
      setMetrics(await api<AdminMetrics>("/api/admin/metrics"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  };
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <>
      <div className="title-row">
        <div>
          <p className="eyebrow">OPERATOR ONLY</p>
          <h1>Relay metrics</h1>
          <p className="muted">Aggregate service and RC signup counters. No account or device identifiers are shown.</p>
        </div>
        <button disabled={refreshing} onClick={() => void refresh()}>{refreshing ? "Refreshing…" : "Refresh"}</button>
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      {!metrics ? (
        !error && <p>Loading metrics…</p>
      ) : (
        <>
          <section className="status-line">
            <span className={metrics.serviceHealthy ? "status-ok" : "status-bad"}>
              {metrics.serviceHealthy ? "Healthy" : "Unhealthy"}
            </span>
            <span>Signup: {metrics.signup.mode.replaceAll("_", " ")}</span>
            <span>State revision: {metrics.stateRevision}</span>
          </section>
          <div className="metric-grid">
            <MetricCard label="Registered users" value={metrics.signup.registeredUsers} note={`${metrics.signup.publicUsers} public OAuth user${metrics.signup.publicUsers === 1 ? "" : "s"}`} />
            <MetricCard label="Pending signups" value={metrics.signup.pendingReservations} note={metrics.signup.mode === "open" ? "Public signup is open" : "New public signup is closed"} />
            <MetricCard label="Active devices" value={metrics.devices.active} note={`${metrics.devices.revoked} revoked · ${metrics.devices.total} total`} />
            <MetricCard label="Committed operations" value={metrics.operations.committed} note={`${metrics.operations.pending} pending · ${metrics.operations.total} total`} />
          </div>
          <p className="updated">Updated {new Date(metrics.generatedAt).toLocaleString()}</p>
        </>
      )}
    </>
  );
}
function Authorize() {
  const [code, setCode] = useState(
    new URLSearchParams(location.search).get("user_code") ?? "",
  );
  const [request, setRequest] = useState<{
    client_id?: string;
    scope?: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  async function inspect(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setResult("");
    setRequest(null);
    setConfirmed(false);
    try {
      setRequest(
        await api("/api/auth/device?user_code=" + encodeURIComponent(code)),
      );
    } catch (e) {
      setResult((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function decide(approve: boolean) {
    setBusy(true);
    try {
      await api("/api/auth/device/" + (approve ? "approve" : "deny"), {
        userCode: code,
      });
      setRequest(null);
      setResult(
        approve
          ? "Device authorization approved. Return to your device."
          : "Device authorization denied.",
      );
    } catch (e) {
      setResult((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <h1>Authorize a device</h1>
      <p className="muted">Enter the code shown on the device you are using.</p>
      <section className="card">
        <form onSubmit={inspect}>
          <label>
            Device code
            <input
              value={code}
              maxLength={32}
              onChange={(e) => {
                setCode(e.target.value);
                setRequest(null);
                setConfirmed(false);
              }}
              autoComplete="off"
              required
            />
          </label>
          <button disabled={busy}>Check code</button>
        </form>
        {request && (
          <>
            <hr />
            <h2>Confirm this request</h2>
            <p>
              This signs the CLI into your relay account. It can register
              devices, revoke access, and request relay connections.
            </p>
            <dl>
              <dt>Code</dt>
              <dd>{code}</dd>
              <dt>Application</dt>
              <dd>{request.client_id}</dd>
              <dt>Scope</dt>
              <dd>{request.scope || "First-party relay control session"}</dd>
            </dl>
            <p className="warning">
              Approve only if you started this request on a device in your
              possession. Never approve a code sent by someone else.
            </p>
            <label className="check">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              This code matches my device.
            </label>
            <div className="actions">
              <button
                className="primary"
                disabled={busy || !confirmed}
                onClick={() => decide(true)}
              >
                Approve device
              </button>
              <button disabled={busy} onClick={() => decide(false)}>
                Deny
              </button>
            </div>
          </>
        )}
        {result && <p role="status">{result}</p>}
      </section>
    </>
  );
}
function Devices() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const refresh = () =>
    api<{ devices: Device[] }>("/api/relay/devices")
      .then((x) => {
        setDevices(x.devices);
        setLoaded(true);
      })
      .catch((e) => setError((e as Error).message));
  useEffect(() => {
    void refresh();
  }, []);
  async function revoke(d: Device) {
    if (!confirm(`Revoke ${d.name}? It will lose relay access.`)) return;
    setBusy(d.principal);
    try {
      await api("/api/relay/devices/" + d.principal + "/revoke", {});
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <h1>Your devices</h1>
      <p className="muted">
        Devices registered to your account. Register new devices from the
        session-peer CLI.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <section className="card">
        {!loaded ? (
          <p>Loading devices…</p>
        ) : !devices.length ? (
          <p>No devices registered yet.</p>
        ) : (
          <ul className="devices">
            {devices.map((d) => (
              <li key={d.principal}>
                <div>
                  <strong>{d.name}</strong>
                  <p className="muted">
                    {d.principal.slice(0, 12)}… · Key {d.keyGeneration} ·{" "}
                    {d.revoked ? "Revoked" : "Active"}
                  </p>
                </div>
                <button
                  disabled={d.revoked || !!busy}
                  onClick={() => revoke(d)}
                >
                  {d.revoked ? "Revoked" : "Revoke access"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
