"""Bounded opt-in POSIX message input; ordinary CLI input is unchanged."""

import codecs
import os
import selectors
import sys


class HandoffStdinError(Exception):
    """Fixed metadata-only pre-effect failure; never reflects message bytes."""

    def __init__(self, reason, exit_code=1):
        super().__init__("Handoff message input refused before submission")
        self.reason = reason
        self.exit_code = exit_code
        self.details = {"reason": reason, "retryAllowed": False}


def read_handoff_stdin(stream, cutoff, clock, max_bytes=4_000_000,
                       max_chars=1_000_000):
    """Read raw stdin until EOF within the caller's original effect cutoff.

    ``clock`` and ``cutoff`` share the caller's handoff clock domain. The
    remaining duration is recomputed after every chunk; input never renews it.
    Raw LF, Unicode and whitespace are preserved. This function does not
    initialize a ledger, reserve an ID, infer native evidence or log a body.
    POSIX readiness/nonblocking I/O bounds a stalled pipe/socket producer.
    As with other local I/O, kernel calls on a faulty filesystem are not a
    universal hard-real-time guarantee. Windows descriptors are unsupported.
    """
    if os.name != "posix":
        raise HandoffStdinError("handoff_stdin_platform_unsupported")
    fd = None
    was_blocking = None
    selector = None
    try:
        if clock() >= cutoff:
            raise HandoffStdinError("handoff_stdin_deadline")
        if stream.isatty():
            raise HandoffStdinError("handoff_stdin_terminal")
        fd = getattr(stream, "buffer", stream).fileno()
        was_blocking = os.get_blocking(fd)
        os.set_blocking(fd, False)
        # SelectSelector also supports redirected regular files on POSIX;
        # epoll/kqueue default selectors do not consistently accept them.
        selector = selectors.SelectSelector()
        selector.register(fd, selectors.EVENT_READ)
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        raw = bytearray()
        byte_count = char_count = 0
        while True:
            remaining = cutoff - clock()
            if remaining <= 0:
                raise HandoffStdinError("handoff_stdin_deadline")
            if not selector.select(remaining):
                continue
            if clock() >= cutoff:
                raise HandoffStdinError("handoff_stdin_deadline")
            try:
                chunk = os.read(fd, min(65536, max_bytes - byte_count + 1))
            except BlockingIOError:
                continue
            if clock() >= cutoff:
                raise HandoffStdinError("handoff_stdin_deadline")
            byte_count += len(chunk)
            if byte_count > max_bytes:
                raise HandoffStdinError("handoff_stdin_too_large")
            text = decoder.decode(chunk, final=not chunk)
            char_count += len(text)
            if char_count > max_chars:
                raise HandoffStdinError("handoff_stdin_too_large")
            raw.extend(chunk)
            if not chunk:
                # Retain one bounded raw buffer instead of one Python string
                # per chunk (a hostile one-byte producer must not multiply
                # container overhead). Incremental decoding above still rejects
                # invalid scalars and excess codepoints before full EOF.
                return raw.decode("utf-8", errors="strict")
    except KeyboardInterrupt:
        raise HandoffStdinError("handoff_stdin_interrupted", 130) from None
    except UnicodeError:
        raise HandoffStdinError("handoff_stdin_invalid_utf8") from None
    except (OSError, ValueError, TypeError, AttributeError):
        raise HandoffStdinError("handoff_stdin_unavailable") from None
    finally:
        active_error = sys.exc_info()[0] is not None
        cleanup_failed = False
        if selector is not None:
            try:
                selector.close()
            except (OSError, ValueError):
                cleanup_failed = True
        if fd is not None and was_blocking is not None:
            try:
                os.set_blocking(fd, was_blocking)
            except OSError:
                cleanup_failed = True
        if cleanup_failed and not active_error:
            raise HandoffStdinError("handoff_stdin_unavailable") from None
