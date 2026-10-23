"""Bounded, offline codec for receiver-bound pairing links.

The fragment contains a bearer secret. Never include input in errors or logs.
"""
import base64
import hashlib
import json
import math
import re
import uuid

from .identity import fingerprint
from .wire import direct_address, validate_relay_url


PREFIX = 'session-peer://pair/v1#'
MAX_LINK_BYTES = 16 * 1024
MAX_DECODED_BYTES = 12 * 1024
_ERROR = 'invalid_pairing_link'
_KEY = re.compile(r'[0-9a-f]{64}\Z')
_BASE64 = re.compile(r'[A-Za-z0-9_-]+\Z')
_FIELDS = {'v', 'id', 'secret', 'expires', 'device', 'certificate', 'routes'}


def _reject():
    raise ValueError(_ERROR)


def _key(value):
    if not isinstance(value, str) or _KEY.fullmatch(value) is None:
        _reject()


def _unbase64(value):
    if not isinstance(value, str) or _BASE64.fullmatch(value) is None:
        _reject()
    data = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    if base64.urlsafe_b64encode(data).decode('ascii').rstrip('=') != value:
        _reject()
    return data


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _validate(invitation, expected_key):
    _key(expected_key)
    if not isinstance(invitation, dict) or type(invitation.get('v')) is not int:
        _reject()
    version = invitation['v']
    fields = _FIELDS if version == 1 else _FIELDS | {'keyFingerprint', 'keyGeneration'}
    if version not in (1, 2) or set(invitation) != fields:
        _reject()
    ident = invitation['id']
    if (not isinstance(ident, str) or len(ident) != 36
            or str(uuid.UUID(ident)) != ident or uuid.UUID(ident).version != 4):
        _reject()
    _key(invitation['device'])
    if len(_unbase64(invitation['secret'])) != 32:
        _reject()
    expires = invitation['expires']
    if type(expires) not in (int, float) or not math.isfinite(expires):
        _reject()
    certificate = invitation['certificate']
    if not isinstance(certificate, str):
        _reject()
    receiver_key = invitation['device']
    if version == 2:
        receiver_key = invitation['keyFingerprint']
        _key(receiver_key)
        generation = invitation['keyGeneration']
        if type(generation) is not int or generation <= 0:
            _reject()
    if fingerprint(certificate) != receiver_key:
        _reject()
    routes = invitation['routes']
    if not isinstance(routes, dict) or not routes or set(routes) - {'direct', 'relay'}:
        _reject()
    for kind, route in routes.items():
        if (not isinstance(route, str) or not route or not route.isascii()
                or any(ord(char) <= 32 or ord(char) == 127 for char in route)):
            _reject()
        (direct_address if kind == 'direct' else validate_relay_url)(route)


def encode_link(invitation, expected_key):
    """Encode an existing invitation and the intended client's certificate key."""
    try:
        _validate(invitation, expected_key)
        raw = json.dumps({'v': 1, 'invitation': invitation,
                          'clientKeyFingerprint': expected_key},
                         sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(raw) > MAX_DECODED_BYTES:
            _reject()
        link = PREFIX + base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
        if len(link) > MAX_LINK_BYTES:
            _reject()
        return link
    except Exception:
        raise ValueError(_ERROR) from None


def decode_link(link):
    """Return (invitation, intended key), without treating expiry as a parse error."""
    try:
        if (not isinstance(link, str) or len(link) > MAX_LINK_BYTES
                or not link.isascii() or not link.startswith(PREFIX)):
            _reject()
        raw = _unbase64(link[len(PREFIX):])
        if len(raw) > MAX_DECODED_BYTES:
            _reject()
        envelope = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                              parse_constant=lambda _: _reject())
        if (not isinstance(envelope, dict)
                or set(envelope) != {'v', 'invitation', 'clientKeyFingerprint'}
                or type(envelope['v']) is not int or envelope['v'] != 1):
            _reject()
        invitation, expected_key = envelope['invitation'], envelope['clientKeyFingerprint']
        _validate(invitation, expected_key)
        return invitation, expected_key
    except Exception:
        raise ValueError(_ERROR) from None


def link_digest(link):
    """Hash the validated original envelope, preserving its exact byte identity."""
    decode_link(link)
    return hashlib.sha256(link.encode('ascii')).hexdigest()
