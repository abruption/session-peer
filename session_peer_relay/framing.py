"""Byte budgets checked before application or native-worker effects."""
import json
import re
from pathlib import PurePosixPath, PureWindowsPath

MAX_TEXT_BYTES = 32 * 1024
MAX_APPLICATION_BYTES = 64 * 1024
# Includes binding, operation and JSON escaping, not just the raw message.
MAX_WORKER_BYTES = 256 * 1024
MAX_DELIVERY_CONTEXT_BYTES = 8 * 1024


def valid_delivery_context(value):
    """Accept only bounded receiver facts; malformed context never spoils a result."""
    if (type(value) is not dict
            or set(value) != {'schemaVersion', 'agent', 'target', 'home', 'capabilities'}
            or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
            or value['agent'] not in ('claude', 'codex', 'antigravity')):
        return False
    for key in ('target', 'home'):
        item = value[key]
        if item is not None:
            if not isinstance(item, str) or not item or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in item):
                return False
            try:
                if len(item.encode('utf-8')) > 4096:
                    return False
            except UnicodeError:
                return False
    if value['target'] is not None and not value['target'].startswith(value['agent'] + ':'):
        return False
    if value['target'] is not None:
        identifier = value['target'].split(':', 1)[1]
        pattern = r'[1-9][0-9]*' if value['agent'] == 'claude' else r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
        if re.fullmatch(pattern, identifier) is None:
            return False
    if value['home'] is not None and not (
            PurePosixPath(value['home']).is_absolute() or PureWindowsPath(value['home']).is_absolute()):
        return False
    capabilities = value['capabilities']
    if (type(capabilities) is not dict or set(capabilities) != {'send', 'wake', 'wait', 'ack'}
            or any(type(item) is not bool for item in capabilities.values())):
        return False
    try:
        encoded_frame(value, MAX_DELIVERY_CONTEXT_BYTES, 'delivery_context_too_large')
    except FrameRejected:
        return False
    return True


class FrameRejected(ValueError):
    """A positively known rejection before any bytes are submitted."""


def encoded_frame(value, limit, reason):
    try:
        data = json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError):
        raise FrameRejected('invalid_frame') from None
    if len(data) > limit:
        raise FrameRejected(reason)
    return data


def application_frame(value):
    return encoded_frame(value, MAX_APPLICATION_BYTES, 'application_frame_too_large')


def worker_frame(binding, operation, text, peer_fingerprint=None, *, explain=False):
    value = {'binding': binding, 'operation': operation, 'text': text}
    if peer_fingerprint is not None:
        value['peerFingerprint'] = peer_fingerprint
    if explain:
        if operation != 'resolve' or explain is not True:
            raise FrameRejected('invalid_explain')
        value['explain'] = True
    return encoded_frame(value,
                         MAX_WORKER_BYTES, 'native_worker_frame_too_large')


def valid_text(text):
    try:
        return (isinstance(text, str) and bool(text.strip()) and '\0' not in text
                and len(text.encode('utf-8')) <= MAX_TEXT_BYTES)
    except UnicodeError:
        return False
