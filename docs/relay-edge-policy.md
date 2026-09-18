# Native clients behind Cloudflare (RC validation)

The relay's browser UI and native API have different clients. A successful
browser OAuth callback or public health GET does not establish that device-code
POSTs or authenticated WebSocket connections work.

On the KR pilot, a native device-code request returned HTTP 403 / Cloudflare
1010 (`browser_signature_banned`). The corresponding Cloudflare security event
identified `source=bic`, `ruleId=bic`, `action=block`. This identified Browser
Integrity Check for that request; it did not identify Bot Fight Mode as the cause.

## Approved native POST exception

The owner first approved device code/token paths, then explicitly approved the
three registration/admission POST paths. This remains one Configuration Rule,
in `http_config_settings`, with
`action=set_config` and `action_parameters={"bic":false}`. Its expression is:

```text
(http.host eq "relay.abruption.dev" and ssl and http.request.method eq "POST" and http.request.uri.path in {"/api/auth/device/code" "/api/auth/device/token" "/api/relay/challenge" "/api/relay/devices" "/api/relay/admission"} and http.request.uri.query eq "")
```

This disables only BIC for the five HTTPS POST endpoints without a query. The
zone-wide BIC setting, managed WAF, Bot Fight Mode, DDoS protection, security
level, existing rate rules and origin ingress restrictions stay unchanged.
The existing Cloudflare rate rule protects a different service; it must not be
described as relay-specific rate protection. Control's own request limits,
fixed client ID, code expiry/polling restrictions, account allowlist and explicit
browser approval continue to apply. Matching this rule grants no authentication.

The configuration was applied after explicit approval. The v2 rule's Cloudflare
Trace matched all five intended paths and excluded ten other cases, including
other methods/host, query, trailing slash, plaintext HTTP, browser approval/revoke,
operation lookup and relay session/WebSocket endpoints. The first stage also
passed actual native code issuance, browser approval and token polling. Trace is
configuration verification, not evidence of successful downstream native delivery.

## Changes and rollback

Before applying such a rule to another deployment, read the existing configuration
phase and preserve other rules. Do not replace an existing ruleset with the example
above or disable BIC for an entire zone. Record the new rule ID/version, reread
the stored expression and check intended and excluded cases.

Revert only the added rule (disable/delete by its ID), preserving concurrent
configuration changes. Do not restore application databases, keys, receipts or
replay state as part of reverting an edge rule.

Operation lookup and relay session/WebSocket GET routes are not included in
this exception. If they fail, stop and inspect their own status/error and security
event. Any wider exception needs separate review and authorization. Do not
impersonate a browser user-agent, transfer browser cookies to the CLI, or keep
retrying an explicit non-retryable block. Keep device codes, tokens and secrets
out of logs and reports.

References: [Cloudflare error 1010](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/)
and [Browser Integrity Check](https://developers.cloudflare.com/waf/tools/browser-integrity-check/).
