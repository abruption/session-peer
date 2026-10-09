"""Byte budgets checked before application or native-worker effects."""
import json

MAX_TEXT_BYTES = 32 * 1024
MAX_APPLICATION_BYTES = 64 * 1024
# Includes binding, operation and JSON escaping, not just the raw message.
MAX_WORKER_BYTES = 256 * 1024


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


def worker_frame(binding, operation, text, peer_fingerprint=None):
    value = {'binding': binding, 'operation': operation, 'text': text}
    if peer_fingerprint is not None:
        value['peerFingerprint'] = peer_fingerprint
    return encoded_frame(value,
                         MAX_WORKER_BYTES, 'native_worker_frame_too_large')


def valid_text(text):
    try:
        return (isinstance(text, str) and bool(text.strip()) and '\0' not in text
                and len(text.encode('utf-8')) <= MAX_TEXT_BYTES)
    except UnicodeError:
        return False
