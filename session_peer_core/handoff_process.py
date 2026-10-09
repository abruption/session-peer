"""Bounded source-streamed POSIX child, with no delivery or receipt authority."""

import math
import os
import selectors
import signal
import subprocess
import sys
import time
from typing import NamedTuple, Optional


class HandoffProcessResult(NamedTuple):
    stdout: bytes
    stderr: bytes
    returncode: Optional[int]
    reason: Optional[str]
    spawned: Optional[bool]
    interrupted: bool
    stdout_overflow: bool
    stderr_overflow: bool
    cleanup_failed: bool


def handoff_group_zombies_only(pid, native_total):
    """Darwin EPERM-only diagnostic while the original leader stays reserved.

    Inspect only native stat codes, not command lines or other user data. The
    trusted local system utility has its own bounded pipes and reserved PID;
    no recursive group probe or post-reap signal is used for it.
    """
    probe = selector = None
    buffers = {"out": bytearray(), "err": bytearray()}
    valid = False
    probe_interrupted = False
    try:
        remaining = native_total - time.monotonic()
        if remaining <= 0 or sys.platform != "darwin":
            return False
        probe = subprocess.Popen(["/bin/ps", "-o", "stat=", "-g", str(pid)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        selector = selectors.DefaultSelector()
        for stream, name in ((probe.stdout, "out"), (probe.stderr, "err")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = native_total - time.monotonic()
            if remaining <= 0:
                return False
            for key, _ in selector.select(min(.05, remaining)):
                destination = buffers[key.data]
                limit = 65536 if key.data == "out" else 4096
                try:
                    chunk = os.read(key.fd, min(4096, limit - len(destination) + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if len(destination) + len(chunk) > limit:
                    return False
                destination.extend(chunk)
        statuses = [line.strip() for line in buffers["out"].splitlines() if line.strip()]
        valid = bool(statuses) and not buffers["err"] and all(line.startswith(b"Z") for line in statuses)
    except KeyboardInterrupt:
        probe_interrupted = True
    except (OSError, ValueError, TypeError):
        return False
    finally:
        if selector is not None:
            try:
                selector.close()
            except KeyboardInterrupt:
                probe_interrupted = True
        if probe is not None:
            while True:
                try:
                    # Still unreaped, known owned system utility PID; not the
                    # target group and never a post-wait signal.
                    os.kill(probe.pid, signal.SIGKILL)
                    break
                except KeyboardInterrupt:
                    probe_interrupted = True
                    if time.monotonic() >= native_total:
                        valid = False
                        break
                except ProcessLookupError:
                    break
                except OSError:
                    valid = False
                    break
            while True:
                try:
                    code = probe.wait(timeout=max(0, native_total - time.monotonic()))
                    valid = valid and code in (0, 1)
                    break
                except KeyboardInterrupt:
                    probe_interrupted = True
                except subprocess.TimeoutExpired:
                    valid = False
                    break
            for stream in (probe.stdout, probe.stderr):
                try:
                    stream.close()
                except KeyboardInterrupt:
                    probe_interrupted = True
                    try:
                        stream.close()
                    except (KeyboardInterrupt, OSError):
                        valid = False
        if probe_interrupted:
            # Propagate only after the diagnostic child is cleaned up. The
            # caller records interruption and still reaps the original leader.
            raise KeyboardInterrupt()
    return valid


def handoff_stream_child(argv, source_bytes, cutoff, total, clock, *, env=None):
    """Stream trusted source on stdin and drain both output pipes concurrently.

    ``cutoff`` and ``total`` use the caller's original clock, including its
    cleanup reserve; no renewed timeout is created here. A native-first sample
    supplies conservative remaining-duration cleanup if that clock fails.
    Only this child's still-reserved process group is signalled, before wait
    reaps the leader. Escaped/detached descendants are outside this boundary.
    The caller must not auto-reap children or concurrently waitpid this owned
    child; a foreign SIGCHLD/waitpid owner would invalidate PID reservation.
    OS spawn, signal and filesystem calls are not universally cancellable.

    This primitive returns RAW bytes and fixed metadata, never prints source,
    argv, diagnostics, native success or capabilities. A strict caller parser
    may preserve complete stdout evidence after diagnostic overflow or other
    transport trouble. STDOUT overflow always forbids adopting its valid
    prefix. Ledger/fence, target checks and SSH trust are caller responsibilities.
    ``spawned=None`` means construction was interrupted after entering Popen,
    before an owned process object was returned; effect and cleanup are unknown.
    Only ``spawned is False`` denotes a proven pre-spawn refusal/failure.
    """
    output, diagnostics = bytearray(), bytearray()
    process = selector = None
    construction_started = construction_unknown = False
    reason = None
    interrupted = stdout_overflow = stderr_overflow = cleanup_failed = False
    code = None
    source_limit, output_limit, diagnostic_limit = 4 * 1024 * 1024, 1024 * 1024, 64 * 1024

    def result(spawned):
        return HandoffProcessResult(bytes(output), bytes(diagnostics), code, reason,
                                    spawned, interrupted, stdout_overflow,
                                    stderr_overflow, cleanup_failed)

    if os.name != "posix":
        reason = "process_platform_unsupported"
        return result(False)
    if (not isinstance(argv, (list, tuple)) or not argv
            or any(type(arg) is not str or "\0" in arg for arg in argv)
            or type(source_bytes) is not bytes):
        reason = "invalid_process_request"
        return result(False)
    if len(source_bytes) > source_limit:
        reason = "source_capacity"
        return result(False)
    try:
        valid_deadline = (type(cutoff) in (int, float) and type(total) in (int, float)
                          and math.isfinite(cutoff) and math.isfinite(total)
                          and total >= cutoff)
    except (OverflowError, TypeError, ValueError):
        valid_deadline = False
    if not valid_deadline:
        reason = "invalid_process_deadline"
        return result(False)
    try:
        native_start = time.monotonic()
        shared_start = clock()
        if type(shared_start) not in (int, float) or not math.isfinite(shared_start):
            raise ValueError()
    except KeyboardInterrupt:
        reason, interrupted = "process_interrupted", True
        return result(False)
    except Exception:
        reason = "process_clock_unavailable"
        return result(False)
    if shared_start >= cutoff:
        reason = "deadline_before_spawn"
        return result(False)
    native_cutoff = native_start + (cutoff - shared_start)
    native_total = native_start + (total - shared_start)

    def remaining(deadline, native_deadline, require_shared):
        nonlocal reason, interrupted
        backup = native_deadline - time.monotonic()
        try:
            shared = clock()
            if type(shared) not in (int, float) or not math.isfinite(shared):
                raise ValueError()
            return min(backup, deadline - shared)
        except KeyboardInterrupt:
            if require_shared:
                raise
            interrupted = True
            reason = reason or "process_interrupted"
            return backup
        except Exception:
            reason = reason or "process_clock_unavailable"
            return 0 if require_shared else backup

    def close_stream(stream):
        nonlocal reason, interrupted, cleanup_failed
        if selector is not None:
            while True:
                try:
                    selector.unregister(stream)
                    break
                except KeyboardInterrupt:
                    interrupted = True
                    reason = reason or "process_interrupted"
                    if time.monotonic() >= native_total:
                        cleanup_failed = True
                        break
                except (KeyError, ValueError):
                    break
        try:
            stream.close()
        except KeyboardInterrupt:
            interrupted = True
            reason = reason or "process_interrupted"
            # close is idempotent for these privately owned pipe objects.
            try:
                stream.close()
            except (KeyboardInterrupt, OSError, ValueError):
                cleanup_failed = True
        except (OSError, ValueError):
            cleanup_failed = True
            reason = reason or "process_cleanup_failed"

    def read_stream(key):
        nonlocal reason, stdout_overflow, stderr_overflow
        kind = key.data
        destination = output if kind == "stdout" else diagnostics
        limit = output_limit if kind == "stdout" else diagnostic_limit
        try:
            chunk = os.read(key.fd, min(65536, limit - len(destination) + 1))
        except BlockingIOError:
            return
        if not chunk:
            close_stream(key.fileobj)
            return
        available = limit - len(destination)
        destination.extend(chunk[:available])
        if len(chunk) > available:
            if kind == "stdout":
                stdout_overflow = True
                reason = "stdout_capacity"
            else:
                stderr_overflow = True
                reason = reason or "stderr_capacity"
            # Keep the bounded diagnostic prefix, but avoid repeatedly waking
            # an already saturated pipe. The other pipe is drained in cleanup.
            close_stream(key.fileobj)

    try:
        if remaining(cutoff, native_cutoff, True) <= 0:
            reason = reason or "deadline_before_spawn"
            return result(False)
        construction_started = True
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=env, close_fds=True,
                                   start_new_session=True)
        selector = selectors.DefaultSelector()
        for stream, events, kind in ((process.stdin, selectors.EVENT_WRITE, "stdin"),
                                    (process.stdout, selectors.EVENT_READ, "stdout"),
                                    (process.stderr, selectors.EVENT_READ, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, events, kind)
        offset = 0
        if not source_bytes:
            close_stream(process.stdin)
        while selector.get_map():
            budget = remaining(cutoff, native_cutoff, True)
            if budget <= 0:
                reason = reason or "process_deadline"
                break
            stop_io = False
            for key, _ in selector.select(min(.05, budget)):
                # Readiness is not a renewed deadline. A scheduled-out caller
                # must not finish source feeding after its effect cutoff.
                if remaining(cutoff, native_cutoff, True) <= 0:
                    reason = reason or "process_deadline"
                    stop_io = True
                    break
                if key.data == "stdin":
                    try:
                        n = os.write(key.fd, source_bytes[offset:offset + 65536])
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        reason = reason or "source_stream_failed"
                        close_stream(key.fileobj)
                        continue
                    offset += n
                    if offset == len(source_bytes):
                        close_stream(key.fileobj)
                else:
                    read_stream(key)
            if stop_io or stdout_overflow or stderr_overflow or interrupted:
                break
    except KeyboardInterrupt:
        interrupted, reason = True, "process_interrupted"
        if construction_started and process is None:
            # The constructor may already have created an OS process. Without
            # its returned handle, do not invent no-effect or owned-cleanup
            # evidence and never signal a guessed PID/process group.
            construction_unknown = cleanup_failed = True
            reason = "process_spawn_interrupted"
    except (OSError, ValueError, TypeError):
        reason = reason or ("process_not_started" if process is None else "process_stream_failed")
    finally:
        if process is not None:
            # No poll/wait has reaped this leader. Keep PID/group ownership
            # until the only group signal has been issued, even on EOF/SIGINT.
            while True:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                    break
                except KeyboardInterrupt:
                    interrupted = True
                    reason = reason or "process_interrupted"
                    if time.monotonic() >= native_total:
                        cleanup_failed = True
                        break
                except ProcessLookupError:
                    break
                except OSError as exc:
                    # Darwin may refuse KILL for a group whose members are all
                    # zombies. Prove that condition before reaping the leader;
                    # otherwise retain conservative cleanup failure metadata.
                    try:
                        zombie_only = (isinstance(exc, PermissionError)
                                       and handoff_group_zombies_only(process.pid, native_total))
                    except KeyboardInterrupt:
                        interrupted = True
                        reason = reason or "process_interrupted"
                        zombie_only = False
                    if not zombie_only:
                        cleanup_failed = True
                        reason = reason or "process_cleanup_failed"
                    break
            close_stream(process.stdin)
            # Capture buffered complete stdout during cleanup; diagnostic
            # saturation must not discard independently valid native facts.
            if selector is not None:
                while selector.get_map():
                    try:
                        budget = remaining(total, native_total, False)
                        if budget <= 0:
                            cleanup_failed = True
                            reason = reason or "process_cleanup_failed"
                            break
                        for key, _ in selector.select(min(.05, budget)):
                            read_stream(key)
                    except KeyboardInterrupt:
                        interrupted = True
                        reason = reason or "process_interrupted"
                    except (OSError, ValueError, TypeError):
                        cleanup_failed = True
                        reason = reason or "process_cleanup_failed"
                        break
            # Repeated interruption can change result metadata, never the
            # deadline or ownership. No signal is issued after this wait.
            while True:
                try:
                    code = process.wait(timeout=max(0, remaining(total, native_total, False)))
                    break
                except KeyboardInterrupt:
                    interrupted = True
                    reason = reason or "process_interrupted"
                except subprocess.TimeoutExpired:
                    cleanup_failed = True
                    reason = reason or "process_cleanup_failed"
                    break
            for stream in (process.stdout, process.stderr):
                close_stream(stream)
        if selector is not None:
            try:
                selector.close()
            except KeyboardInterrupt:
                interrupted = True
                reason = reason or "process_interrupted"
            except (OSError, ValueError):
                cleanup_failed = True
                reason = reason or "process_cleanup_failed"
    return result(None if construction_unknown else process is not None)
