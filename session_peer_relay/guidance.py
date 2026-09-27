"""Additive, fixed-vocabulary hints. Never infer delivery or retry authority."""


def with_guidance(result):
    if result.get('ok') is not False:
        return result
    reason = result.get('reason')
    diagnostic = result.get('connectionFailure', {})
    if isinstance(diagnostic, dict) and diagnostic.get('hint') in {'login_missing', 'device_not_found'}:
        reason = diagnostic['hint']
    hints = {
        'login_missing': ('login', 'Run device login explicitly for this state; no stored login was found.'),
        'device_not_found': ('enrollment', 'Control could not find a device owned by this login. Verify enrollment and account ownership; do not automatically re-enroll or replace identity.'),
        'login_expired': ('login', 'Run device login explicitly for this state and verify the browser origin and code.'),
        'expired_token': ('login', 'The device authorization expired; start a new explicit login.'),
        'unpaired_device': ('pairing', 'Pair this state with a fresh trusted invitation; login alone does not pair devices.'),
        'peer_policy_denied': ('policy', 'Ask the receiver owner to inspect the peer policy. Do not bypass it.'),
        'operation_denied': ('policy', 'Ask the receiver owner to review this operation permission.'),
        'target_denied': ('policy', 'Ask the receiver owner to review the allowed target binding.'),
        'codex_executable_not_found': ('native_target', 'Check the receiver service PATH or its operator-owned codexBin, then use a dry-run.'),
        'native_refused': ('native_target', 'Inspect the receiver target and policy with a dry-run; the exact native cause is not known.'),
        'no_authenticated_route': ('unreachable', 'Inspect route diagnostics, login, enrollment and receiver readiness; the unavailable leg or cause is not proven.'),
        'peer_not_ready': ('unreachable', 'The peer did not complete readiness; inspect the receiver without assuming it is stopped.'),
        'native_outcome_unknown': ('unknown', 'Reconcile the request ID or inspect the target; do not automatically resend.'),
    }
    hint = hints.get(reason) if isinstance(reason, str) else None
    # Route failures retain their original stage/reason. Expose actionable hints
    # only when every failed route agrees, never guess from a generic 403/404.
    routes = result.get('routeFailures', {})
    if reason == 'no_authenticated_route' and isinstance(routes, dict) and routes:
        details = list(routes.values())
        if all(isinstance(x, dict) and x.get('hint') == 'login_missing' for x in details):
            hint = hints['login_missing']
        elif all(isinstance(x, dict) and x.get('hint') == 'device_not_found' for x in details):
            hint = hints['device_not_found']
        elif all(isinstance(x, dict) and x.get('reason') == 'login_expired' for x in details):
            hint = hints['login_expired']
    if hint:
        return {**result, 'guidance': {'category': hint[0], 'nextAction': hint[1]}}
    return result
