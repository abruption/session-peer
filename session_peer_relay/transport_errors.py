"""Allowlisted connection diagnostics. Never serialize an exception's message."""
import ssl
import urllib.error

from .store import Rejected


class TransportFailure(Rejected):
    def __init__(self, stage, reason, *, transient=False, http_status=None):
        super().__init__(reason)
        self.stage = stage
        self.transient = transient
        self.http_status = http_status

    def diagnostic(self):
        value = {'stage': self.stage, 'reason': str(self)}
        if self.http_status is not None:
            value['httpStatus'] = self.http_status
        return value


def failure(stage, exc):
    if isinstance(exc, TransportFailure):
        return exc
    if isinstance(exc, urllib.error.URLError):
        cause = exc.reason
    else:
        cause = exc
    if isinstance(cause, TimeoutError):
        return TransportFailure(stage, 'timeout', transient=True)
    if isinstance(cause, ssl.SSLError):
        return TransportFailure(stage, 'tls_failed')
    if isinstance(cause, (ConnectionError, OSError)):
        return TransportFailure(stage, 'connection_failed')
    if isinstance(exc, Rejected):
        known = {'login_expired', 'access_denied', 'expired_token', 'invalid_grant',
                 'control_relay_origin_mismatch', 'control_unreachable',
                 'control_request_refused', 'invalid_control_response',
                 'invalid_control_challenge', 'invalid_admission_ticket',
                 'peer_not_ready', 'rotation_unsupported'}
        if str(exc) in known:
            return TransportFailure(stage, str(exc))
    return TransportFailure(stage, 'connection_failed')


class NoAuthenticatedRoute(Rejected):
    def __init__(self, diagnostics):
        super().__init__('no_authenticated_route')
        self.route_failures = diagnostics
