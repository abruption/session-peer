"""Allowlisted connection diagnostics. Never serialize an exception's message."""
import ssl
import urllib.error

from websockets.exceptions import ConnectionClosed

from .store import Rejected


class TransportFailure(Rejected):
    def __init__(self, stage, reason, *, transient=False, http_status=None,
                 close_code=None, close_source=None, retry_after=None):
        super().__init__(reason)
        self.stage = stage
        self.transient = transient
        self.http_status = http_status
        # Polling metadata only. Do not include untrusted response headers in diagnostics.
        self.retry_after = retry_after if type(retry_after) in (int, float) and retry_after >= 0 else None
        self.close_code = (int(close_code) if isinstance(close_code, int)
                           and not isinstance(close_code, bool) and 1000 <= close_code <= 4999 else None)
        self.close_source = close_source if self.close_code is not None and close_source in {'received', 'sent'} else None

    def diagnostic(self):
        value = {'stage': self.stage, 'reason': str(self)}
        if self.http_status is not None:
            value['httpStatus'] = self.http_status
        if self.close_code is not None:
            value['closeCode'] = self.close_code
            if self.close_source is not None:
                value['closeSource'] = self.close_source
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
    if isinstance(cause, ConnectionClosed):
        close = cause.rcvd or cause.sent
        code = close.code if close else None
        source = 'received' if cause.rcvd is not None else 'sent' if cause.sent is not None else None
        return TransportFailure(stage, 'connection_closed', close_code=code, close_source=source)
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
