# First Google account discovery (development)

This opt-in operator procedure obtains a verified Google account ID before adding
that ID to the relay allowlist. It does not enable public signup, grant a session,
or connect Google and GitHub accounts by matching email addresses. Actual provider
validation remains an RC gate; mocked provider tests are separate evidence.

Use the dedicated Google Web OAuth client and its exact configured callback:
`https://relay.example.com/api/auth/callback/google`. Keep the application in
Testing and restrict its Google test users while preparing the private relay.
Supply its secret through the existing protected file/systemd credential path.

Before the first Google login, set these two **temporary** control settings:

```text
SESSION_PEER_GOOGLE_DISCOVERY_EMAIL=the-explicitly-approved-account@example.com
SESSION_PEER_GOOGLE_DISCOVERY_UNTIL=REPLACE_WITH_UNIX_SECONDS_WITHIN_30_MINUTES
```

Both settings, an enabled Google provider and a future deadline of at most 30
minutes are required. This mode prevents every new Google login while it is
enabled, including after the deadline; remove both settings to resume normal
Google authentication. Existing account allowlists are not relaxed.

1. Start the reviewed control candidate with these settings and its normal
   protected state. Open its Google sign-in flow in the approved user's browser.
2. Better Auth performs its normal authorization-code, state and PKCE exchange.
   The wrapper verifies the returned Google ID token through Better Auth's pinned
   verifier: signature, issuer, client audience, expiry and maximum token age. If
   the library supplies an expected nonce, that nonce is checked too. It does not
   claim a nonce was issued when the provider flow did not supply one.
3. Only the real Google callback with the exact expected email and
   `email_verified=true` may create
   `<SESSION_PEER_CONTROL_DATA>/google-account-discovery.json`. The private file
   contains the verified subject, expected email, verification time, issuer and
   public client ID. It contains no authorization code or provider/session token.
4. The callback intentionally refuses login before account linking or provisioning.
   Confirm the discovery record through the trusted operator path, add its exact
   `accountId` as a `google` entry in `SESSION_PEER_ALLOWED_ACCOUNTS`, and remove
   both discovery settings. Preserve the other approved account entries.
5. Restart through the reviewed service procedure and perform a separate normal
   Google login and CLI device approval test. The discovery callback itself was
   not a successful login.

The discovery file is created once with mode 0600 in a private 0700 directory.
Retries, different subjects, an expired window or a failed write cannot replace
it or grant access. If the operator must repeat discovery, inspect and explicitly
archive the prior result first; do not automatically delete it during restart.

`accountLinking=false` remains in effect. A Google account whose email already
belongs to a GitHub-created user may be refused with `account-not-linked`.
Discovery still works before that check. It does not authorize automatic linking;
validate separate providers with distinct approved owners or isolated test state
unless an explicit account-linking policy is added in a separate change.
