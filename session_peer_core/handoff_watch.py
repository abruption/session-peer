# Read-only sampled handoff projection. Included in the standalone namespace.
HANDOFF_WATCH_FRAME_BYTES = 16 * 1024
HANDOFF_WATCH_OUTPUT_BYTES = 256 * 1024
HANDOFF_WATCH_END_RESERVE = 2048
HANDOFF_WATCH_FINISH_SECONDS = 0.1
HANDOFF_WATCH_REAP_SECONDS = 0.025
HANDOFF_WATCH_SLEEP_SLICE_SECONDS = 0.05
HANDOFF_WATCH_WRITER_SCRIPT = r'''
import os
import select
import signal
import sys
import threading
import time
try:
    signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})
    parent = int(sys.argv[1])
    cutoff = float(sys.argv[2])
    if sys.platform == "darwin":
        import ctypes
        class Timebase(ctypes.Structure):
            _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]
        library = ctypes.CDLL(None)
        absolute = library.mach_absolute_time
        absolute.argtypes, absolute.restype = [], ctypes.c_uint64
        timebase = library.mach_timebase_info
        timebase.argtypes, timebase.restype = [ctypes.POINTER(Timebase)], ctypes.c_int
        info = Timebase()
        if timebase(ctypes.byref(info)) != 0 or not info.numer or not info.denom:
            os._exit(1)
        def now():
            return (int(absolute()) * int(info.numer) // int(info.denom)) / 1000000000
    else:
        def now():
            return time.monotonic_ns() / 1000000000
    def supervise():
        try:
            while True:
                remaining = cutoff - now()
                if os.getppid() != parent or remaining <= 0:
                    os._exit(1)
                time.sleep(min(0.01, remaining))
        except BaseException:
            os._exit(1)
    if os.getppid() != parent or now() >= cutoff:
        os._exit(1)
    threading.Thread(target=supervise, daemon=True).start()
except BaseException:
    os._exit(1)
def exact(size):
    result = bytearray()
    while len(result) < size:
        chunk = os.read(0, size - len(result))
        if not chunk:
            os._exit(0)
        result.extend(chunk)
    return bytes(result)
try:
    while True:
        size = int.from_bytes(exact(4), "big")
        if not 1 <= size <= 16384:
            os._exit(1)
        frame = exact(size)
        offset = 0
        while offset < size:
            try:
                count = os.write(1, frame[offset:])
            except BlockingIOError:
                remaining = cutoff - now()
                if remaining <= 0:
                    os._exit(1)
                select.select([], [1], [], remaining)
                continue
            if count <= 0:
                os._exit(1)
            offset += count
        os.write(0, b"1")
except BaseException:
    os._exit(1)
'''


def handoff_watch_timeout(value):
    return handoff_timeout(value)


def handoff_watch_interval(value):
    if (type(value) is not str or re.fullmatch(r"[1-9][0-9]{3}", value, flags=re.ASCII) is None
            or not 1000 <= int(value) <= 5000):
        raise argparse.ArgumentTypeError("expected an ASCII integer from 1000 to 5000")
    return int(value)


class HandoffWatchOutputError(Exception):
    pass


@contextlib.contextmanager
def handoff_watch_defer_interrupt():
    previous_handler = signal.getsignal(signal.SIGINT)
    pending = [None]
    def defer(signum, frame):
        if previous_handler != signal.SIG_IGN:
            pending[0] = (signum, frame)
    # Masking this thread alone cannot defer CPython handlers when another
    # unmasked thread receives a process-directed signal. Record it as well.
    signal.signal(signal.SIGINT, defer)
    try:
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
        try:
            yield
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        if pending[0] is not None:
            if callable(previous_handler):
                previous_handler(*pending[0])
            elif previous_handler == signal.SIG_DFL:
                os.kill(os.getpid(), signal.SIGINT)


class HandoffWatchOutput:
    """Owned writer isolates blocking stdout without changing inherited flags.

    A completion ACK proves only an OS write, never consumer processing. Unknown
    completion suppresses subsequent frames. The final 100ms of the original
    budget covers the end frame and child cleanup, including 25ms for reaping.
    A helper watchdog also exits on parent death or the original shared-clock
    deadline, including when the parent is stopped. OS process creation and
    uninterruptible I/O remain scheduling limitations.
    """
    def __init__(self, stream, deadline):
        import io
        self.stream, self.deadline = stream, deadline
        self.work_deadline = deadline - HANDOFF_WATCH_FINISH_SECONDS
        self.channel, self.process = None, None
        self.used, self.damaged = 0, False
        if isinstance(stream, io.StringIO):
            return
        child = None
        try:
            fd = stream.fileno()
            self.channel, child = socket.socketpair()
            # Register the handle before delivering a pending terminal SIGINT.
            with handoff_watch_defer_interrupt():
                self.process = subprocess.Popen(
                    [sys.executable, "-I", "-S", "-c", HANDOFF_WATCH_WRITER_SCRIPT,
                     str(os.getpid()), repr(deadline)],
                    stdin=child, stdout=fd, stderr=subprocess.DEVNULL, env={},
                    close_fds=True, start_new_session=True)
        except Exception:
            self.close()
            raise HandoffWatchOutputError()
        except BaseException:
            self.close()
            raise
        finally:
            if child is not None:
                try:
                    child.close()
                except BaseException:
                    self.close()
                    raise

    def close(self):
        # A pending SIGINT is delivered only after kill/reap has finished.
        with handoff_watch_defer_interrupt():
            return self._close()

    def _close(self):
        if self.channel is not None:
            channel = self.channel
            self.channel = None
            try:
                channel.close()
            except OSError:
                pass
        if self.process is not None:
            try:
                if self.process.poll() is None:
                    self.process.kill()
                self.process.wait(timeout=max(0, self.deadline - handoff_now()))
            except (OSError, subprocess.TimeoutExpired):
                return False
        return True

    def write(self, text, *, end=False):
        raw = (text + "\n").encode("utf-8")
        limit = HANDOFF_WATCH_OUTPUT_BYTES - (0 if end else HANDOFF_WATCH_END_RESERVE)
        if len(raw) > HANDOFF_WATCH_FRAME_BYTES or self.used + len(raw) > limit:
            return "output_limit"
        if self.damaged:
            return "output_unavailable"
        io_deadline = self.deadline - HANDOFF_WATCH_REAP_SECONDS if end else self.work_deadline
        if handoff_now() >= io_deadline:
            return "output_unavailable" if end else "duration_elapsed"
        try:
            if self.channel is None:
                self.stream.write(raw.decode("utf-8"))
            else:
                self.channel.settimeout(max(0, io_deadline - handoff_now()))
                self.channel.sendall(len(raw).to_bytes(4, "big") + raw)
                remaining = io_deadline - handoff_now()
                if remaining <= 0:
                    raise HandoffWatchOutputError()
                self.channel.settimeout(remaining)
                if self.channel.recv(1) != b"1":
                    raise HandoffWatchOutputError()
            self.used += len(raw)
            return None
        except Exception:
            self.damaged = True
            return "output_unavailable"
        except BaseException:
            self.damaged = True
            raise


def handoff_watch_frame(args, payload, *, ok):
    if args.json:
        return json.dumps(json_result("handoff", payload, ok=ok), ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False)
    if payload["event"] == "snapshot":
        return ("Watch snapshot " + str(payload["sequence"]) + " (sampled changes)\n" +
                handoff_status_text(payload["handoff"], payload["historyPhase"]))
    return ("Handoff watch ended: " + payload["reason"] + "; snapshots: " +
            str(payload["snapshotsEmitted"]) + "; samples: " + str(payload["samples"]) + ".")


def handoff_watch_pause(until):
    # Some schedulers coalesce a long relative sleep by a proportion of its
    # duration. Recheck the same absolute deadline after short sleeps rather
    # than consuming the final-output reserve in one long sleep. This changes
    # neither the sampling interval nor the original total watch budget.
    while True:
        remaining = until - handoff_now()
        if remaining <= 0:
            return
        time.sleep(min(HANDOFF_WATCH_SLEEP_SLICE_SECONDS, remaining))


def cmd_handoff_watch(args):
    if IS_WINDOWS or fcntl is None:
        payload = {"operation": "watch", "event": "end", "reason": "unsupported",
                   "snapshotsEmitted": 0, "samples": 0}
        print(handoff_watch_frame(args, payload, ok=False))
        return 1
    # The same absolute deadline covers setup, locking, collector IPC and output.
    started = handoff_now()
    duration = args.watch_timeout
    interval = args.interval_ms
    if type(duration) is not int or not 1 <= duration <= 60:
        raise handoff_error("invalid_watch_timeout")
    if type(interval) is not int or not 1000 <= interval <= 5000:
        raise handoff_error("invalid_watch_interval")
    total_deadline = started + duration
    deadline = total_deadline - HANDOFF_WATCH_FINISH_SECONDS
    correlation = handoff_uuid(args.correlation_id)
    snapshots, samples = 0, 0
    writer, original_epoch, previous, context = None, None, None, None
    reason = "history_unavailable"
    try:
        writer = HandoffWatchOutput(sys.stdout, total_deadline)
        ledger = HandoffLedger()
        while handoff_now() < deadline and samples < 61:
            samples += 1
            epoch, record = ledger.record(correlation, deadline, read_only=True)
            if original_epoch is not None and epoch != original_epoch:
                reason = "history_changed"
                break
            original_epoch = epoch
            if handoff_now() >= deadline:
                raise HandoffReadDeadlineExceeded()
            phase = record["phase"]
            if phase not in ("prepared", "attempted", "terminal", "tombstone", "quarantined"):
                raise handoff_error("invalid_handoff")
            active_clock = None
            if record["capability"] and not record["capability"]["revoked"] and not record["ack"]:
                active_clock = handoff_channel_epoch(ledger, deadline, read_only=True)
            if handoff_now() >= deadline:
                raise HandoffReadDeadlineExceeded()
            public = handoff_public(epoch, record, active_clock)
            if handoff_now() >= deadline:
                raise HandoffReadDeadlineExceeded()
            projection = (phase, public)
            if projection != previous:
                payload = {"operation": "watch", "event": "snapshot", "sequence": snapshots + 1,
                           "historyPhase": phase, "handoff": public}
                try:
                    observed = int(time.time() * 1000)
                except (ValueError, OverflowError):
                    observed = None
                if observed is not None and 0 <= observed <= 9007199254740991:
                    payload["observedAtUtcMs"] = observed
                failure = writer.write(handoff_watch_frame(args, payload, ok=True))
                if failure:
                    reason = failure
                    break
                snapshots += 1
                previous = projection
            remaining = deadline - handoff_now()
            if remaining <= 0:
                raise HandoffReadDeadlineExceeded()
            handoff_watch_pause(min(deadline, handoff_now() + interval / 1000))
        else:
            reason = "duration_elapsed"
    except KeyboardInterrupt:
        reason = "interrupted"
    except HandoffWatchOutputError:
        reason = "output_unavailable"
    except HandoffReadDeadlineExceeded:
        reason = "duration_elapsed"
    except Exception:
        reason = "history_unavailable"
        # Context is a closed enum. Never emit the underlying exception or path.
        exc = sys.exc_info()[1]
        detail = exc.details.get("reason") if isinstance(exc, CcPeerError) else None
        context = ("id_unknown" if detail == "handoff_id_unknown" else
                   "ledger_corrupt" if detail == "handoff_ledger_corrupt" else
                   "ledger_missing" if isinstance(exc, FileNotFoundError) or
                   isinstance(exc.__cause__, FileNotFoundError) else None)
    finally:
        if writer is not None:
            if reason == "interrupted":
                writer.deadline = min(writer.deadline, handoff_now() + HANDOFF_WATCH_FINISH_SECONDS)
            try:
                payload = {"operation": "watch", "event": "end", "reason": reason,
                           "snapshotsEmitted": snapshots, "samples": samples}
                if context is not None:
                    payload["queryContext"] = context
                failure = writer.write(handoff_watch_frame(args, payload, ok=reason == "duration_elapsed"), end=True)
                if failure and reason != "interrupted":
                    reason = failure
            except KeyboardInterrupt:
                reason = "interrupted"
                writer.deadline = min(writer.deadline, handoff_now() + HANDOFF_WATCH_FINISH_SECONDS)
            except Exception:
                reason = "output_unavailable"
            finally:
                try:
                    if not writer.close() and reason != "interrupted":
                        reason = "output_unavailable"
                except KeyboardInterrupt:
                    reason = "interrupted"
                except Exception:
                    reason = "output_unavailable"
    return 0 if reason == "duration_elapsed" else 130 if reason == "interrupted" else 1
