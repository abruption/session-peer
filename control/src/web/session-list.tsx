export interface AccountSession {
  id: string;
  createdAt: string;
  expiresAt: string;
  userAgent: string;
  current: boolean;
}

/** Receives metadata only: never pass bearer tokens to the browser UI. */
export function SessionList({ sessions, busy, revoke }: {
  sessions: AccountSession[];
  busy: boolean;
  revoke: (id: string) => void;
}) {
  return (
    <ul className="devices sessions">
      {sessions.map((session) => (
        <li key={session.id}>
          <div>
            <strong>{session.current ? "This browser" : "Other login"}</strong>
            <p>{session.userAgent || "Client details unavailable"}</p>
            <p>Signed in: <time dateTime={session.createdAt}>{new Date(session.createdAt).toLocaleString()}</time></p>
            <p>Expires: <time dateTime={session.expiresAt}>{new Date(session.expiresAt).toLocaleString()}</time></p>
          </div>
          {!session.current && <button disabled={busy} onClick={() => revoke(session.id)}>Revoke</button>}
        </li>
      ))}
    </ul>
  );
}
