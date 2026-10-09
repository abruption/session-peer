# Opt-in Handoff v1. The frozen design fixture remains a design artifact; this
# module implements a deliberately narrower, same-user POSIX receipt channel.
HANDOFF_LEDGER_BYTES = 33554432
HANDOFF_RECORD_BYTES = 32768  # reserve all 64 waits, a receipt and native facts
HANDOFF_FRAME_BYTES = 4096
HANDOFF_COLLECTOR_ARG = "--_handoff-receipt-collector"
HANDOFF_PRODUCER_ARG = "--_handoff-receipt-producer"
_HANDOFF_MACH_CLOCK = None
HANDOFF_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")


def handoff_error(reason):
    # Private frames, tokens, digests, paths and exception text never escape.
    return CcPeerError("Handoff operation refused", {"reason": reason, "retryAllowed": False})


def handoff_now_ns():
    """Shared native monotonic domain, including CPython 3.9 on Darwin.

    CPython 3.9's Darwin monotonic clock subtracts a process-local t0. Never
    compare that clock across the sender and independent receipt collector.
    mach_absolute_time has a shared boot-relative tick domain; timebase_info
    converts it to integer nanoseconds without float/UTC or invented offsets.
    """
    global _HANDOFF_MACH_CLOCK
    if sys.platform != "darwin":
        value = time.monotonic_ns()
    else:
        try:
            import ctypes
            if _HANDOFF_MACH_CLOCK is None:
                class Timebase(ctypes.Structure):
                    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]
                library = ctypes.CDLL(None)
                absolute = library.mach_absolute_time
                absolute.argtypes, absolute.restype = [], ctypes.c_uint64
                timebase = library.mach_timebase_info
                timebase.argtypes, timebase.restype = [ctypes.POINTER(Timebase)], ctypes.c_int
                info = Timebase()
                if timebase(ctypes.byref(info)) != 0 or not info.numer or not info.denom:
                    raise handoff_error("handoff_clock_unavailable")
                _HANDOFF_MACH_CLOCK = (absolute, int(info.numer), int(info.denom))
            absolute, numer, denom = _HANDOFF_MACH_CLOCK
            value = int(absolute()) * numer // denom
        except (OSError, AttributeError, ValueError, TypeError) as exc:
            raise handoff_error("handoff_clock_unavailable") from exc
    if type(value) is not int or not 0 <= value <= 9223372036854775807:
        raise handoff_error("handoff_clock_unavailable")
    return value


def handoff_now():
    return handoff_now_ns() / 1000000000


def handoff_uuid(value):
    if type(value) is not str or HANDOFF_UUID.fullmatch(value) is None:
        raise handoff_error("invalid_correlation_id")
    return value


def handoff_cli_uuid(value):
    try:
        return handoff_uuid(value)
    except CcPeerError as exc:
        raise argparse.ArgumentTypeError("expected a canonical UUIDv4") from exc


def handoff_identifier(value, limit=256):
    if (type(value) is not str or not value or
            any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xd800 <= ord(c) <= 0xdfff for c in value)):
        raise handoff_error("invalid_receipt")
    if len(value.encode("utf-8")) > limit:
        raise handoff_error("invalid_receipt")
    return value


def handoff_timeout(value):
    if (type(value) is not str or re.fullmatch(r"[1-9][0-9]?", value, flags=re.ASCII) is None
            or not 1 <= int(value) <= 60):
        raise argparse.ArgumentTypeError("expected an ASCII integer from 1 to 60")
    return int(value)


def handoff_validate_public(value):
    """Closed public shape; not proof of native ownership or receipt authority."""
    def require(condition):
        if not condition:
            raise handoff_error("invalid_handoff")
    def closed(obj, required, optional=()):
        require(type(obj) is dict and set(required) <= set(obj) <= set(required) | set(optional))
    def integer(number):
        require(type(number) is int and 0 <= number <= 9007199254740991)
    def enum(item, choices):
        require(type(item) is str and item in choices)
    try:
        require(len(HandoffLedger.encode(value)) <= 8192)
        closed(value, ("schemaVersion", "correlationId", "ledgerEpoch", "state", "submission", "observation", "ack", "wait", "targetGeneration", "decisionOwner", "retry", "nextActions"))
        integer(value["schemaVersion"])
        require(value["schemaVersion"] == 1)
        handoff_uuid(value["ledgerEpoch"])
        handoff_uuid(value["correlationId"])
        closed(value["submission"], ("status",))
        state_submissions = {"validated": {"not_attempted"}, "refused": {"refused"}, "submitted": {"submitted"}, "delivered": {"submitted"}, "acknowledged": {"submitted"}, "unknown": {"unknown"}, "timed_out_unknown": {"submitted", "unknown"}}
        require(value["state"] in state_submissions and value["submission"]["status"] in state_submissions[value["state"]])
        generation = value["targetGeneration"]
        if generation is not None:
            handoff_identifier(generation)
        observed = value["observation"]
        closed(observed, ("status", "injectionObserved"), ("clientUserMessageId", "turn"))
        enum(observed["status"], ("not_requested", "pending", "observed", "unsupported", "failed"))
        require(type(observed["injectionObserved"]) is bool)
        if "clientUserMessageId" in observed:
            handoff_identifier(observed["clientUserMessageId"], 128)
        if observed["injectionObserved"]:
            require(value["submission"]["status"] == "submitted" and observed["status"] == "observed" and "clientUserMessageId" in observed and generation is not None)
        if "turn" in observed:
            require(observed["injectionObserved"])
            closed(observed["turn"], ("id", "status"))
            handoff_identifier(observed["turn"]["id"], 128)
            enum(observed["turn"]["status"], ("running", "completed", "failed", "interrupted", "unknown"))
        require(value["state"] != "delivered" or observed["injectionObserved"])
        ack = value["ack"]
        closed(ack, ("status",), ("assurance", "receivedAtUtcMs", "late"))
        enum(ack["status"], ("not_requested", "pending", "acknowledged", "unsupported"))
        if ack["status"] == "acknowledged":
            require(value["state"] == "acknowledged" and generation is not None and value["submission"]["status"] == "submitted")
            require(set(ack) == {"status", "assurance", "receivedAtUtcMs", "late"})
            enum(ack["assurance"], ("token_possession", "operator_confirmed"))
            integer(ack["receivedAtUtcMs"])
            require(type(ack["late"]) is bool)
        else:
            require(set(ack) == {"status"})
            require(ack["status"] != "pending" or generation is not None)
        require(value["state"] != "acknowledged" or ack["status"] == "acknowledged")
        wait = value["wait"]
        closed(wait, ("for", "status"), ("operationId", "deadlineAtUtcMs", "reason"))
        enum(wait["for"], ("none", "delivered", "acknowledged"))
        enum(wait["status"], ("not_requested", "pending", "satisfied", "timed_out_unknown", "stopped", "unsupported", "failed"))
        if "operationId" in wait:
            handoff_uuid(wait["operationId"])
        if "deadlineAtUtcMs" in wait:
            integer(wait["deadlineAtUtcMs"])
        if "reason" in wait:
            enum(wait["reason"], ("insufficient_budget", "deadline_before_effect", "evidence_unsupported", "evidence_failed", "history_unavailable", "stopped_by_operator", "invalid_handoff"))
        if wait["for"] == "none":
            require(wait["status"] == "not_requested" and "operationId" not in wait and "deadlineAtUtcMs" not in wait)
        else:
            require("operationId" in wait and "deadlineAtUtcMs" in wait and wait["status"] != "not_requested")
        if wait["status"] == "satisfied":
            require(observed["injectionObserved"] if wait["for"] == "delivered" else ack["status"] == "acknowledged")
        require(wait["status"] != "stopped" or wait.get("reason") == "stopped_by_operator")
        require(value["decisionOwner"] == "sender_operator")
        require(value["retry"] == {"allowed": False, "reason": "receiver_dedup_unavailable"} and value["retry"]["allowed"] is False)
        actions = value["nextActions"]
        require(type(actions) is list and all(type(action) is str and action in ("keep_waiting", "reconcile", "stop_waiting") for action in actions) and len(actions) == len(set(actions)))
        require(not (wait["status"] == "unsupported" or wait.get("reason") == "history_unavailable") or "keep_waiting" not in actions)
    except (KeyError, TypeError, UnicodeError, ValueError, RecursionError) as exc:
        raise handoff_error("invalid_handoff") from exc
    return value


def handoff_json(raw, limit, *, integers=True):
    if type(raw) is not bytes or len(raw) > limit:
        raise handoff_error("invalid_receipt")
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise handoff_error("invalid_receipt")
            out[key] = value
        return out
    def number(token):
        raise handoff_error("invalid_receipt")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs,
                           parse_float=number if integers else float, parse_constant=number)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise handoff_error("invalid_receipt") from exc
    if type(value) is not dict:
        raise handoff_error("invalid_receipt")
    return value


def handoff_private_wire(raw, confirmation=False):
    value = handoff_json(raw, HANDOFF_FRAME_BYTES)
    required = {"schemaVersion", "ledgerEpoch", "correlationId", "targetGeneration"}
    required |= {"confirmed"} if confirmation else {"kind", "receiptId", "capability"}
    if set(value) != required or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise handoff_error("invalid_receipt")
    for key in ("ledgerEpoch", "correlationId"):
        handoff_uuid(value[key])
    handoff_identifier(value["targetGeneration"])
    if confirmation:
        if value["confirmed"] is not True:
            raise handoff_error("invalid_receipt")
    else:
        handoff_uuid(value["receiptId"])
        cap = value["capability"]
        if value["kind"] != "receipt" or type(cap) is not str or re.fullmatch(r"[A-Za-z0-9_-]{43}", cap) is None:
            raise handoff_error("invalid_receipt")
        decoded = base64.urlsafe_b64decode(cap + "=")
        if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != cap:
            raise handoff_error("invalid_receipt")
    return value


def handoff_root():
    return Path.home() / ".local" / "share" / "session-peer" / "handoff"


def handoff_boot_clock():
    """Read native boot identity; UTC is never retention/timeout authority."""
    import hashlib
    try:
        if sys.platform == "linux":
            raw = Path("/proc/sys/kernel/random/boot_id").read_bytes()
            if len(raw) > 64:
                return None
        elif sys.platform == "darwin":
            import ctypes
            class Timeval(ctypes.Structure):
                _fields_ = [("sec", ctypes.c_long), ("usec", ctypes.c_int32)]
            function = ctypes.CDLL(None).sysctlbyname
            function.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
            function.restype = ctypes.c_int
            value, size = Timeval(), ctypes.c_size_t(ctypes.sizeof(Timeval))
            if function(b"kern.boottime", ctypes.byref(value), ctypes.byref(size), None, 0) != 0 or not value.sec:
                return None
            raw = (str(value.sec) + ":" + str(value.usec)).encode("ascii")
        else:
            return None
        # Namespace continuity proof by the shared clock provider. Earlier
        # candidate process-relative metadata is not silently treated as this
        # boot-relative domain after upgrade.
        return hashlib.sha256(b"handoff-shared-native-clock-v1:" + sys.platform.encode("ascii") + b":" + raw).hexdigest()
    except (OSError, AttributeError, ValueError):
        return None


def handoff_private_stat(path, directory=False):
    if IS_WINDOWS:
        raise handoff_error("handoff_platform_unsupported")
    try:
        info = path.lstat()
    except OSError as exc:
        raise handoff_error("handoff_history_unavailable") from exc
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (not expected or stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise handoff_error("unsafe_handoff_storage")
    return info


class HandoffLedger:
    """Serialized, fsynced snapshots with retained effect fences, not dedup.

    A stable owner-only lock file survives atomic snapshot replacement. Every
    retained intent reserves its maximum record bytes before any native effect.
    No implicit initialization, eviction, repair or restored-history trust.
    """
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else handoff_root()

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")

    def initialize(self):
        if IS_WINDOWS or fcntl is None:
            raise handoff_error("handoff_platform_unsupported")
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
            for name in ("ledger.lock",):
                fd = os.open(str(self.root / name), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            state = {"schemaVersion": 1, "epoch": str(uuid.uuid4()), "records": {}}
            self._save(state)
            return state["epoch"]
        except FileExistsError as exc:
            raise handoff_error("handoff_already_initialized") from exc
        except OSError as exc:
            raise handoff_error("handoff_history_unavailable") from exc

    def _save(self, state):
        records = state["records"]
        reserved = 1024 + sum(len(self.encode(record)) + 64 if record["phase"] == "tombstone" else HANDOFF_RECORD_BYTES for record in records.values())
        if len(records) > 10000 or reserved > HANDOFF_LEDGER_BYTES:
            raise handoff_error("handoff_ledger_capacity")
        for record in records.values():
            if len(self.encode(record)) > HANDOFF_RECORD_BYTES:
                raise handoff_error("handoff_record_capacity")
        raw = self.encode(state)
        if len(raw) > HANDOFF_LEDGER_BYTES:
            raise handoff_error("handoff_ledger_capacity")
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".ledger-", dir=str(self.root))
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, str(self.root / "ledger.json"))
            temporary = None
            directory = os.open(str(self.root), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary is not None:
                os.unlink(temporary)

    @contextlib.contextmanager
    def transaction(self, deadline=None):
        if IS_WINDOWS or fcntl is None:
            raise handoff_error("handoff_platform_unsupported")
        handoff_private_stat(self.root, True)
        lock = self.root / "ledger.lock"
        before = handoff_private_stat(lock)
        fd = os.open(str(lock), os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
        try:
            after = os.fstat(fd)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise handoff_error("unsafe_handoff_storage")
            limit = deadline if deadline is not None else handoff_now() + 5
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if handoff_now() >= limit:
                        raise handoff_error("handoff_storage_busy")
                    time.sleep(min(0.01, max(0, limit - handoff_now())))
            path = self.root / "ledger.json"
            initial = handoff_private_stat(path)
            if initial.st_size > HANDOFF_LEDGER_BYTES:
                raise handoff_error("handoff_history_unavailable")
            read_fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(read_fd, "rb") as stream:
                current = os.fstat(stream.fileno())
                if (initial.st_dev, initial.st_ino) != (current.st_dev, current.st_ino):
                    raise handoff_error("unsafe_handoff_storage")
                raw = stream.read(HANDOFF_LEDGER_BYTES + 1)
            try:
                state = handoff_json(raw, HANDOFF_LEDGER_BYTES)
                if set(state) != {"schemaVersion", "epoch", "records"} or type(state["schemaVersion"]) is not int or state["schemaVersion"] != 1 or type(state["records"]) is not dict:
                    raise ValueError()
                handoff_uuid(state["epoch"])
                for key, record in state["records"].items():
                    handoff_uuid(key)
                    if type(record) is not dict or record.get("id") != key:
                        raise ValueError()
                    self._validate_record(record)
            except (CcPeerError, ValueError, KeyError, TypeError) as exc:
                raise handoff_error("handoff_ledger_corrupt") from exc
            boot, now = handoff_boot_clock(), handoff_now_ns()
            if boot is not None:
                for record in state["records"].values():
                    if (record["phase"] != "tombstone" and record["historyBoot"] == boot
                            and now >= record["createdNs"] + 30 * 86400 * 1000000000):
                        # Detail expires only under proven boot/monotonic
                        # continuity. The immutable target/payload effect fence
                        # survives and still counts toward the intent quota.
                        record.update(phase="tombstone", submission="unknown", native=None,
                                      waits=[], ack=None, capability=None, pendingReceipt=None, observe=False, ackRequested=False)
            yield state
            self._save(state)
        except OSError as exc:
            raise handoff_error("handoff_history_unavailable") from exc
        finally:
            os.close(fd)

    def prepare(self, binding, generation, correlation=None, deadline=None, native_context=None):
        import copy
        with self.transaction(deadline) as state:
            if correlation is not None:
                handoff_uuid(correlation)
                record = state["records"].get(correlation)
                if record is None:
                    raise handoff_error("handoff_id_unknown")
                if record["binding"] != binding or record["generation"] != generation:
                    raise handoff_error("handoff_binding_conflict")
                if record["phase"] != "prepared":
                    raise handoff_error("handoff_already_attempted")
                if record.get("nativeContext") != native_context:
                    raise handoff_error("handoff_native_context_changed")
                return state["epoch"], copy.deepcopy(record)
            correlation = str(uuid.uuid4())
            record = {"id": correlation, "binding": binding, "generation": generation,
                      "phase": "prepared", "submission": "not_attempted", "native": None,
                      "waits": [], "ack": None, "createdNs": handoff_now_ns(),
                      "createdUtcMs": int(time.time() * 1000), "capability": None, "pendingReceipt": None,
                      "historyBoot": handoff_boot_clock()}
            if native_context is not None:
                record["nativeContext"] = native_context
            state["records"][correlation] = record
            return state["epoch"], copy.deepcopy(record)

    def record(self, correlation, deadline=None):
        import copy
        handoff_uuid(correlation)
        with self.transaction(deadline) as state:
            record = state["records"].get(correlation)
            if record is None:
                raise handoff_error("handoff_id_unknown")
            return state["epoch"], copy.deepcopy(record)

    @staticmethod
    def _validate_record(record):
        def uint(value, maximum=9223372036854775807):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError()
        def clock(value):
            if value is not None:
                handoff_uuid(value)
        required = {"id", "binding", "generation", "phase", "submission", "native", "waits", "ack", "createdNs", "createdUtcMs", "capability", "historyBoot", "pendingReceipt"}
        if not required <= set(record) <= required | {"observe", "ackRequested", "nativeContext"}:
            raise ValueError()
        if record["phase"] not in ("prepared", "attempted", "terminal", "tombstone", "quarantined") or record["submission"] not in ("not_attempted", "submitted", "refused", "unknown"):
            raise ValueError()
        if record["phase"] == "terminal" and record["submission"] == "not_attempted":
            raise ValueError()
        for key in ("observe", "ackRequested"):
            if key in record and type(record[key]) is not bool:
                raise ValueError()
        for key in ("createdNs", "createdUtcMs"):
            uint(record[key], 9007199254740991 if key == "createdUtcMs" else 9223372036854775807)
        if record["historyBoot"] is not None and (type(record["historyBoot"]) is not str or re.fullmatch(r"[0-9a-f]{64}", record["historyBoot"]) is None):
            raise ValueError()
        if record["generation"] is not None:
            handoff_identifier(record["generation"])
        binding = record["binding"]
        if type(binding) is not dict or set(binding) != {"agent", "destination", "target", "home", "payloadDigest"}:
            raise ValueError()
        handoff_identifier(binding["agent"], 128)
        handoff_identifier(binding["target"], 4096)
        if (type(binding["destination"]) is not list or not 1 <= len(binding["destination"]) <= 32
                or any(type(host) is not str for host in binding["destination"])):
            raise ValueError()
        for host in binding["destination"]:
            handoff_identifier(host)
        if binding["home"] is not None:
            handoff_identifier(binding["home"], 4096)
        if type(binding["payloadDigest"]) is not str or re.fullmatch(r"[0-9a-f]{64}", binding["payloadDigest"]) is None:
            raise ValueError()
        if "nativeContext" in record:
            context = record["nativeContext"]
            if (binding["agent"] != "codex" or type(context) is not dict or set(context) != {"root", "resolution"}
                    or context["root"] != binding["home"] or len(HandoffLedger.encode(context)) > 4096):
                raise ValueError()
            handoff_codex_resolution(context["resolution"], binding["home"])
        if type(record["waits"]) is not list or len(record["waits"]) > 64:
            raise ValueError()
        for wait in record["waits"]:
            required_wait = {"for", "status", "operationId", "deadlineAtUtcMs", "deadlineNs", "clockEpoch"}
            if type(wait) is not dict or not required_wait <= set(wait) <= required_wait | {"reason"}:
                raise ValueError()
            handoff_uuid(wait["operationId"])
            uint(wait["deadlineNs"])
            uint(wait["deadlineAtUtcMs"], 9007199254740991)
            clock(wait["clockEpoch"])
            if wait["for"] not in ("delivered", "acknowledged") or wait["status"] not in ("pending", "satisfied", "timed_out_unknown", "stopped", "unsupported", "failed"):
                raise ValueError()
            if "reason" in wait and wait["reason"] not in ("insufficient_budget", "deadline_before_effect", "evidence_unsupported", "evidence_failed", "history_unavailable", "stopped_by_operator", "invalid_handoff"):
                raise ValueError()
            if wait["status"] == "stopped" and wait.get("reason") != "stopped_by_operator":
                raise ValueError()
        for key in ("observe", "ackRequested"):
            if key in record and type(record[key]) is not bool:
                raise ValueError()
        cap = record["capability"]
        if cap is not None:
            if type(cap) is not dict or set(cap) != {"hash", "clockEpoch", "expiresNs", "revoked"}:
                raise ValueError()
            if type(cap["hash"]) is not str or re.fullmatch(r"[0-9a-f]{64}", cap["hash"]) is None or type(cap["revoked"]) is not bool:
                raise ValueError()
            uint(cap["expiresNs"])
            handoff_uuid(cap["clockEpoch"])
        ack = record["ack"]
        if ack is not None:
            if type(ack) is not dict or set(ack) != {"status", "assurance", "receivedAtUtcMs", "late", "receiptId", "classifiedClockEpoch"}:
                raise ValueError()
            if ack["status"] != "acknowledged" or ack["assurance"] not in ("token_possession", "operator_confirmed") or type(ack["late"]) is not bool:
                raise ValueError()
            uint(ack["receivedAtUtcMs"], 9007199254740991)
            if ack["assurance"] == "token_possession":
                handoff_uuid(ack["receiptId"])
                handoff_uuid(ack["classifiedClockEpoch"])
            elif ack["receiptId"] is not None or ack["classifiedClockEpoch"] is not None:
                raise ValueError()
            if record["generation"] is None or record["submission"] != "submitted":
                raise ValueError()
        pending = record["pendingReceipt"]
        if pending is not None:
            if type(pending) is not dict or set(pending) != {"receiptId", "clockEpoch", "receivedNs", "receivedAtUtcMs"}:
                raise ValueError()
            handoff_uuid(pending["receiptId"])
            handoff_uuid(pending["clockEpoch"])
            uint(pending["receivedNs"])
            uint(pending["receivedAtUtcMs"], 9007199254740991)
            if record["generation"] is None or cap is None:
                raise ValueError()
        if record["phase"] == "prepared" and (record["submission"] != "not_attempted" or record["native"] is not None or ack is not None or pending is not None):
            raise ValueError()
        if record["phase"] == "attempted" and (record["submission"] != "unknown" or record["native"] is not None or ack is not None):
            raise ValueError()
        if record["phase"] in ("tombstone", "quarantined") and (record["submission"] != "unknown" or record["native"] is not None or ack is not None or pending is not None):
            raise ValueError()
        if record["phase"] == "tombstone" and cap is not None:
            raise ValueError()
        if record["submission"] == "submitted" and (record["phase"] != "terminal" or record["native"] is None):
            raise ValueError()
        native = record["native"]
        if native is not None:
            if type(native) is not dict or len(HandoffLedger.encode(native)) > 8192 or type(native.get("ok")) is not bool:
                raise ValueError()
            if record["submission"] == "submitted":
                handoff_validate_native(native, record)
            elif (set(native) != {"ok", "reason", "retryAllowed"} or native["ok"] is not False
                    or native["retryAllowed"] is not False
                    or native["reason"] != {"unknown": "native_outcome_unknown", "refused": "native_submission_refused"}.get(record["submission"])):
                raise ValueError()

    def quarantine_restored(self):
        """Explicit operator API for a known restored copy, never automatic."""
        with self.transaction() as state:
            for record in state["records"].values():
                record.update(phase="quarantined", submission="unknown", native=None, ack=None, pendingReceipt=None)
                if record["capability"]:
                    record["capability"]["revoked"] = True
                for wait in record["waits"]:
                    if wait["status"] == "pending":
                        wait.update(status="failed", reason="history_unavailable")


def handoff_validate_native(native, record):
    # Preserve the actual Python profiles; optional Claude facts stay absent.
    binding = record["binding"]
    target = native.get("target")
    if binding["agent"] == "codex":
        required = {"ok", "target", "chars", "dryRun", "codexHome", "submitted", "consumptionConfirmed", "status", "codexHomeResolution"}
        if (binding["destination"] != ["local"] or type(target) is not dict or set(target) != {"agent", "id"}
                or not required <= set(native) <= required | {"queueId"}
                or target["agent"] != "codex" or type(target["id"]) is not str
                or re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", target["id"]) is None
                or target["id"].lower() != binding["target"]
                or native["ok"] is not True or native["dryRun"] is not False
                or native["status"] != "queued" or native["submitted"] is not True or native["consumptionConfirmed"] is not False
                or type(native["chars"]) is not int or not 0 <= native["chars"] <= MAX_MESSAGE_CHARS
                or type(native["codexHome"]) is not str or native["codexHome"] != binding["home"]
                or type(native["codexHomeResolution"]) is not dict
                or native["codexHomeResolution"].get("selected") != binding["home"]):
            raise handoff_error("invalid_native_profile")
        if "queueId" in native:
            handoff_identifier(native["queueId"], 128)
        handoff_codex_resolution(native["codexHomeResolution"], binding["home"])
        if record.get("nativeContext") is not None and native["codexHomeResolution"] != record["nativeContext"]["resolution"]:
            raise handoff_error("invalid_native_profile")
        return
    if (binding["agent"] != "claude" or binding["destination"] != ["local"] or type(target) is not dict
            or set(native) != {"ok", "target", "chars", "dryRun"} or set(target) != {"pid", "name"}
            or type(target["pid"]) is not int or target["pid"] <= 1 or str(target["pid"]) != binding["target"]
            or native["ok"] is not True or native["dryRun"] is not False
            or type(native["chars"]) is not int or not 0 <= native["chars"] <= MAX_MESSAGE_CHARS
            or (target["name"] is not None and type(target["name"]) is not str)):
        raise handoff_error("invalid_native_profile")
    if target["name"] is not None:
        target["name"].encode("utf-8", errors="strict")


def handoff_validate_dry_run(native, record):
    """Validate no-effect evidence against the immutable prepared target.

    Dry-run facts are not positive submission facts and are never journaled as
    such.  Native discovery may race preparation, so check the returned profile
    rather than attaching an original binding to an unrelated new target.
    """
    binding = record["binding"]
    if type(native) is not dict or native.get("ok") is not True or native.get("dryRun") is not True:
        raise handoff_error("invalid_native_profile")
    target = native.get("target")
    if type(native.get("chars")) is not int or not 0 <= native["chars"] <= MAX_MESSAGE_CHARS:
        raise handoff_error("invalid_native_profile")
    if binding["agent"] == "claude":
        allowed = {"ok", "target", "chars", "dryRun"}
        if (set(native) not in (allowed, allowed | {"targetGeneration"}) or type(target) is not dict
                or set(target) != {"pid", "name"} or type(target["pid"]) is not int
                or str(target["pid"]) != binding["target"]
                or target["name"] is not None and type(target["name"]) is not str
                or native.get("targetGeneration") != record["generation"]):
            raise handoff_error("invalid_native_profile")
        if target["name"] is not None:
            target["name"].encode("utf-8", errors="strict")
    elif binding["agent"] == "codex":
        required = {"ok", "target", "chars", "dryRun", "codexHome", "submitted", "consumptionConfirmed", "status", "codexHomeResolution"}
        if (set(native) != required or type(target) is not dict or set(target) != {"agent", "id"}
                or target["agent"] != "codex" or type(target["id"]) is not str
                or target["id"].lower() != binding["target"]
                or native["status"] != "validated" or native["submitted"] is not False
                or native["consumptionConfirmed"] is not False or native["codexHome"] != binding["home"]
                or record.get("nativeContext") is None
                or native["codexHomeResolution"] != record["nativeContext"]["resolution"]):
            raise handoff_error("invalid_native_profile")
        handoff_codex_resolution(native["codexHomeResolution"], binding["home"])
    else:
        raise handoff_error("invalid_native_profile")


def handoff_codex_resolution(resolution, root):
    if (type(resolution) is not dict or set(resolution) != {"schemaVersion", "status", "selected", "reason", "candidates"}
            or type(resolution["schemaVersion"]) is not int or resolution["schemaVersion"] != 1
            or resolution["status"] not in ("explicit", "selected") or resolution["selected"] != root
            or resolution["reason"] not in ("explicit_inactive_opt_in", "explicit_live_writer", "single_stable_live_writer")
            or type(resolution["candidates"]) is not list or not 1 <= len(resolution["candidates"]) <= 32):
        raise handoff_error("invalid_native_profile")
    for candidate in resolution["candidates"]:
        required = {"codexHome", "savedThread", "writerLock", "reason"}
        optional = {"activity", "ownerPid", "ownerStartTime", "ownerStable"}
        if (type(candidate) is not dict or not required <= set(candidate) <= required | optional
                or candidate["savedThread"] is not None and type(candidate["savedThread"]) is not bool
                or candidate["writerLock"] not in ("not_checked", "absent", "free", "held", "unknown")
                or candidate.get("activity") not in (None, "inactive", "live_writer", "unknown")):
            raise handoff_error("invalid_native_profile")
        handoff_identifier(candidate["codexHome"], 4096)
        handoff_identifier(candidate["reason"])
        if "ownerStable" in candidate and type(candidate["ownerStable"]) is not bool:
            raise handoff_error("invalid_native_profile")
        for field in ("ownerPid",):
            if field in candidate and (type(candidate[field]) is not int or not 0 <= candidate[field] <= 9007199254740991):
                raise handoff_error("invalid_native_profile")
        for field in ("ownerStartTime",):
            if field in candidate:
                handoff_identifier(candidate[field], 4096)
    if sum(candidate["codexHome"] == root and candidate["savedThread"] is True for candidate in resolution["candidates"]) != 1:
        raise handoff_error("invalid_native_profile")


def handoff_cap_hash(epoch, correlation, generation, cap):
    import hashlib
    return hashlib.sha256(json.dumps([epoch, correlation, generation, cap], separators=(",", ":")).encode("utf-8")).hexdigest()


def handoff_collect(ledger, epoch_id, frame):
    """Receipt-only operations. No native command, transcript or model access."""
    import hmac
    with ledger.transaction() as state:
        if frame == {"op": "clock"}:
            return {"ok": True, "clockEpoch": epoch_id}
        if frame.get("op") == "mint":
            if set(frame) != {"op", "ledgerEpoch", "correlationId", "targetGeneration"}:
                raise handoff_error("invalid_receipt")
            handoff_uuid(frame["ledgerEpoch"])
            handoff_uuid(frame["correlationId"])
            handoff_identifier(frame["targetGeneration"])
            record = state["records"].get(frame["correlationId"])
            if (state["epoch"] != frame["ledgerEpoch"] or record is None or
                    record["generation"] != frame["targetGeneration"] or record["phase"] != "prepared"
                    or record["capability"] is not None):
                raise handoff_error("receipt_authority_unavailable")
            now = handoff_now_ns()
            if (record["historyBoot"] is None or record["historyBoot"] != handoff_boot_clock()
                    or now < record["createdNs"] or now >= record["createdNs"] + 86400 * 1000000000):
                raise handoff_error("receipt_authority_expired")
            cap = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
            record["capability"] = {"hash": handoff_cap_hash(state["epoch"], record["id"], record["generation"], cap),
                                    "clockEpoch": epoch_id, "expiresNs": record["createdNs"] + 86400 * 1000000000,
                                    "revoked": False}
            # Returned only over owner-only private IPC to authorized effect setup.
            return {"ok": True, "capability": cap, "clockEpoch": epoch_id}
        classify = frame.get("op") == "classify"
        if classify:
            if set(frame) != {"op", "schemaVersion", "ledgerEpoch", "correlationId", "targetGeneration", "capability"}:
                raise handoff_error("invalid_receipt")
            frame = {key: value for key, value in frame.items() if key != "op"}
            frame.update(kind="receipt", receiptId="00000000-0000-4000-8000-000000000000")
        receipt = handoff_private_wire(HandoffLedger.encode(frame))
        record = state["records"].get(receipt["correlationId"])
        if state["epoch"] != receipt["ledgerEpoch"] or record is None or record["generation"] != receipt["targetGeneration"]:
            raise handoff_error("receipt_authority_unavailable")
        cap = record["capability"]
        candidate = handoff_cap_hash(state["epoch"], record["id"], record["generation"], receipt["capability"])
        if cap is None or cap["revoked"] or not hmac.compare_digest(candidate, cap["hash"]):
            raise handoff_error("receipt_authority_unavailable")
        prior = record["ack"]
        if prior is not None:
            if prior["assurance"] != "token_possession" or (not classify and prior.get("receiptId") != receipt["receiptId"]):
                raise handoff_error("receipt_conflict")
            # Even after expiry duplicates require original hash proof. Read-only.
            return {"ok": True, "duplicate": True, "pending": False}
        if cap["clockEpoch"] != epoch_id or handoff_now_ns() >= cap["expiresNs"]:
            raise handoff_error("receipt_authority_expired")
        pending = record["pendingReceipt"]
        if classify and pending is None:
            # Classification cannot invent a receipt from sender-held authority.
            return {"ok": True, "duplicate": False, "pending": False}
        if not classify and pending is not None and pending["receiptId"] != receipt["receiptId"]:
            raise handoff_error("receipt_conflict")
        if record["submission"] != "submitted":
            if not classify and record["phase"] == "attempted" and pending is None:
                record["pendingReceipt"] = {"receiptId": receipt["receiptId"], "clockEpoch": epoch_id,
                        "receivedNs": handoff_now_ns(), "receivedAtUtcMs": int(time.time() * 1000)}
            if record["pendingReceipt"] is not None and record["phase"] == "attempted":
                return {"ok": True, "duplicate": pending is not None, "pending": True}
            raise handoff_error("receipt_submission_unconfirmed")
        waits = record["waits"]
        origin = waits[0] if waits else None
        if origin is not None and origin["clockEpoch"] != epoch_id:
            raise handoff_error("receipt_order_unprovable")
        if pending is not None and pending["clockEpoch"] != epoch_id:
            raise handoff_error("receipt_order_unprovable")
        # An early receipt is unclassified until this atomic acceptance. Its
        # arrival timestamp is retained privately, never backdated into ACK.
        now = handoff_now_ns()
        late = origin is not None and now >= origin["deadlineNs"]
        record["ack"] = {"status": "acknowledged", "assurance": "token_possession",
                         "receivedAtUtcMs": int(time.time() * 1000), "late": late,
                         "receiptId": pending["receiptId"] if pending is not None else receipt["receiptId"], "classifiedClockEpoch": epoch_id}
        record["pendingReceipt"] = None
        for wait in waits:
            if wait["status"] == "pending" and wait["clockEpoch"] == epoch_id:
                # Receipt arrival classifies lateness; a wait already terminal
                # before classification stays terminal. No retroactive rewrite.
                wait["status"] = "timed_out_unknown" if handoff_now_ns() >= wait["deadlineNs"] else "satisfied"
        return {"ok": True, "duplicate": False, "pending": False}


def handoff_ipc(root, frame, deadline=None):
    if deadline is not None and handoff_now() >= deadline:
        raise handoff_error("receipt_channel_unavailable")
    root = Path(root)
    handoff_private_stat(root, True)
    path = root / "receipt.sock"
    try:
        info = path.lstat()
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise handoff_error("unsafe_receipt_channel")
        remaining = min(2.0, deadline - handoff_now()) if deadline is not None else 2.0
        if remaining <= 0:
            raise handoff_error("receipt_channel_unavailable")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(remaining)
            connection.connect(str(path))
            if deadline is not None and handoff_now() >= deadline:
                raise handoff_error("receipt_channel_unavailable")
            raw = HandoffLedger.encode(frame)
            if len(raw) > HANDOFF_FRAME_BYTES:
                raise handoff_error("invalid_receipt")
            connection.sendall(raw)
            connection.shutdown(socket.SHUT_WR)
            response = bytearray()
            while True:
                if deadline is not None:
                    if handoff_now() >= deadline:
                        raise handoff_error("receipt_channel_unavailable")
                    connection.settimeout(min(2, deadline - handoff_now()))
                chunk = connection.recv(min(4097 - len(response), 1024))
                if not chunk:
                    break
                response.extend(chunk)
                if len(response) > 4096:
                    raise handoff_error("invalid_receipt")
        result = handoff_json(bytes(response), 4096)
        if result.get("ok") is not True:
            raise handoff_error("receipt_operation_refused")
        return result
    except (OSError, ValueError) as exc:
        raise handoff_error("receipt_channel_unavailable") from exc


def handoff_channel_epoch(ledger, deadline=None):
    try:
        result = handoff_ipc(ledger.root, {"op": "clock"}, deadline)
        return handoff_uuid(result.get("clockEpoch"))
    except CcPeerError:
        return None


def handoff_collector(root):
    """Independent POSIX collector; a restart expires all unused old authority."""
    ledger = HandoffLedger(root)
    epoch_id = str(uuid.uuid4())
    handoff_private_stat(ledger.root, True)
    path = ledger.root / "receipt.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    identity = None
    try:
        # Serialize binding and expiry. A losing concurrent startup must not
        # revoke authority minted by the already running collector.
        with ledger.transaction() as state:
            if path.exists():
                raise handoff_error("receipt_channel_exists")
            server.bind(str(path))
            os.chmod(path, 0o600)
            identity = path.lstat()
            server.listen(8)
            for record in state["records"].values():
                if record["capability"] and record["ack"] is None:
                    record["capability"]["revoked"] = True
        server.settimeout(1)
        end = handoff_now() + 86400
        while handoff_now() < end:
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            with connection:
                frame_deadline = handoff_now() + 1
                try:
                    raw = bytearray()
                    while True:
                        remaining = frame_deadline - handoff_now()
                        if remaining <= 0:
                            raise handoff_error("invalid_receipt")
                        connection.settimeout(remaining)
                        chunk = connection.recv(min(4097 - len(raw), 1024))
                        if not chunk:
                            break
                        raw.extend(chunk)
                        if len(raw) > 4096:
                            raise handoff_error("invalid_receipt")
                    result = handoff_collect(ledger, epoch_id, handoff_json(bytes(raw), 4096))
                except (CcPeerError, OSError, ValueError, KeyError, TypeError):
                    result = {"ok": False, "reason": "receipt_operation_refused"}
                try:
                    connection.sendall(HandoffLedger.encode(result))
                except OSError:
                    pass  # A receipt may already have committed; only duplicate proof can query it.
    finally:
        server.close()
        if identity is not None and path.exists() and path.lstat().st_ino == identity.st_ino:
            path.unlink()
    return 0


def handoff_producer_command(ledger, deadline):
    """Prove the exact installed private handler; canonical PATH is not proof."""
    script = Path(__file__).resolve()
    executable = Path(sys.executable).resolve()
    for path in (script, executable):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_uid not in (0, os.getuid()):
            raise handoff_error("receipt_handler_not_installed")
    remaining = deadline - handoff_now()
    if remaining <= 0:
        raise handoff_error("receipt_handler_not_installed")
    try:
        probe = subprocess.run([str(executable), "-I", str(script), "ack", "--help"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=min(2, remaining), check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise handoff_error("receipt_handler_not_installed") from exc
    if probe.returncode or b"--receipt" not in probe.stdout or handoff_now() >= deadline:
        raise handoff_error("receipt_handler_not_installed")
    return [str(executable), "-I", str(script), HANDOFF_PRODUCER_ARG, str(ledger.root)]


def handoff_ensure_collector(ledger, deadline):
    if handoff_now() >= deadline:
        raise handoff_error("receipt_channel_unavailable")
    path = ledger.root / "receipt.sock"
    if path.exists():
        # A stale socket is never automatically removed or rebound.
        return
    script = Path(__file__).resolve()
    if not script.is_file() or script.stat().st_mode & 0o022:
        raise handoff_error("receipt_handler_not_installed")
    # A short-lived launcher double-forks so the independent receipt-only
    # collector is not tied to this sender's exit or Popen object lifetime.
    launcher = "import os,sys; p=os.fork(); (os._exit(0) if p else None); os.setsid(); p=os.fork(); (os._exit(0) if p else None); os.execv(sys.executable,[sys.executable,*sys.argv[1:]])"
    process = subprocess.Popen([sys.executable, "-c", launcher, str(script), HANDOFF_COLLECTOR_ARG, str(ledger.root)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
    try:
        process.wait(timeout=min(2, max(0.001, deadline - handoff_now())))
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=1)
        raise handoff_error("receipt_channel_unavailable")
    until = min(deadline, handoff_now() + 2)
    while handoff_now() < until:
        if path.exists():
            return
        time.sleep(0.01)
    raise handoff_error("receipt_channel_unavailable")


def handoff_public(epoch, record, active_clock=None):
    import copy
    wait = record["waits"][-1] if record["waits"] else None
    submission = record["submission"]
    ack = record["ack"]
    state = {"not_attempted": "validated", "refused": "refused", "submitted": "submitted", "unknown": "unknown"}[submission]
    if wait and wait["status"] == "timed_out_unknown" and submission in ("submitted", "unknown"):
        state = "timed_out_unknown"
    if ack is not None and submission == "submitted":
        state = "acknowledged"
    result = {"schemaVersion": 1, "correlationId": record["id"], "ledgerEpoch": epoch,
              "state": state, "submission": {"status": submission},
              "observation": {"status": "unsupported" if record.get("observe") else "not_requested", "injectionObserved": False},
              "ack": ({key: ack[key] for key in ("status", "assurance", "receivedAtUtcMs", "late")} if ack else
                      {"status": "pending" if record.get("ackRequested") and record["capability"] and not record["capability"]["revoked"] else
                       "unsupported" if record.get("ackRequested") else "not_requested"}),
              "wait": ({key: wait[key] for key in ("for", "status", "operationId", "deadlineAtUtcMs", "reason") if key in wait}
                       if wait else {"for": "none", "status": "not_requested"}),
              "targetGeneration": record["generation"], "decisionOwner": "sender_operator",
              "retry": {"allowed": False, "reason": "receiver_dedup_unavailable"}, "nextActions": []}
    if submission in ("submitted", "unknown"):
        result["nextActions"] = ["reconcile"]
        if (record.get("ackRequested") and record["capability"] and not record["capability"]["revoked"] and not ack
                and active_clock is not None and active_clock == record["capability"]["clockEpoch"]
                and handoff_now_ns() < record["capability"]["expiresNs"] and (not wait or wait["status"] != "unsupported")):
            result["nextActions"].append("keep_waiting")
        if wait and wait["status"] == "pending":
            result["nextActions"].append("stop_waiting")
    handoff_validate_public(result)
    return copy.deepcopy(result)


def handoff_query_error(correlation, context):
    return {"schemaVersion": 1, "ok": False, "host": "local", "command": "handoff",
            "reason": "handoff_history_unavailable", "handoffQuery": {
                "schemaVersion": 1, "correlationId": correlation, "status": "unknown", "context": context,
                "retry": {"allowed": False, "reason": "history_unavailable"}}}


def handoff_start_wait(record, goal, deadline, clock_epoch, *, initial_status=None, reason=None):
    if len(record["waits"]) >= 64:
        raise handoff_error("handoff_wait_capacity")
    supported = (goal == "acknowledged" and record["generation"] is not None
                 and record["capability"] is not None and not record["capability"]["revoked"])
    wait = {"for": goal, "status": initial_status or ("pending" if supported else "unsupported"),
            "operationId": str(uuid.uuid4()),
            "deadlineAtUtcMs": int(time.time() * 1000 + max(0, deadline - handoff_now()) * 1000),
            "deadlineNs": int(deadline * 1000000000), "clockEpoch": clock_epoch}
    if reason is not None:
        wait["reason"] = reason
    elif not supported:
        wait["reason"] = "evidence_unsupported"
    record["waits"].append(wait)
    return wait["operationId"]


def handoff_wait(ledger, correlation, goal, seconds, deadline=None, clock_epoch=None, operation=None, cleanup_deadline=None):
    start = handoff_now()
    cleanup_deadline = cleanup_deadline if cleanup_deadline is not None else start + seconds
    deadline = deadline if deadline is not None else cleanup_deadline - 5
    verified_clock = handoff_channel_epoch(ledger, deadline) if seconds > 5 else None
    if operation is None:
        with ledger.transaction(cleanup_deadline) as state:
            record = state["records"].get(correlation)
            if record is None:
                raise handoff_error("handoff_id_unknown")
            clock_epoch = verified_clock
            unavailable = (record["ack"] is None and record["capability"] is not None and
                           (verified_clock is None or verified_clock != record["capability"]["clockEpoch"]))
            operation = handoff_start_wait(record, goal, deadline, clock_epoch,
                      initial_status="failed" if seconds <= 5 or unavailable else None,
                      reason="insufficient_budget" if seconds <= 5 else "history_unavailable" if unavailable else None)
    try:
        while True:
            with ledger.transaction(cleanup_deadline) as state:
                record = state["records"][correlation]
                current = next(value for value in record["waits"] if value["operationId"] == operation)
                if current["status"] != "pending":
                    break
                if record["ack"]:
                    current["status"] = "satisfied"
                elif verified_clock is None or current["clockEpoch"] != verified_clock:
                    current.update(status="failed", reason="history_unavailable")
                elif handoff_now() >= deadline:
                    current["status"] = "timed_out_unknown"
                if current["status"] != "pending":
                    break
            time.sleep(min(0.05, max(0, deadline - handoff_now())))
    except KeyboardInterrupt:
        with ledger.transaction(cleanup_deadline) as state:
            record = state["records"][correlation]
            current = next(value for value in record["waits"] if value["operationId"] == operation)
            if current["status"] == "pending":
                current.update(status="stopped", reason="stopped_by_operator")
        return 130
    return 0 if current["status"] == "satisfied" else 1


def handoff_confirm(ledger, frame):
    with ledger.transaction() as state:
        record = state["records"].get(frame["correlationId"])
        if state["epoch"] != frame["ledgerEpoch"] or record is None or record["generation"] != frame["targetGeneration"]:
            raise handoff_error("receipt_authority_unavailable")
        if record["submission"] != "submitted":
            raise handoff_error("receipt_submission_unconfirmed")
        if record["ack"]:
            return  # Never rewrite an existing valid classification.
        origin = record["waits"][0] if record["waits"] else None
        if origin and origin["status"] != "timed_out_unknown":
            raise handoff_error("receipt_order_unprovable")
        record["ack"] = {"status": "acknowledged", "assurance": "operator_confirmed",
                         "receivedAtUtcMs": int(time.time() * 1000), "late": bool(origin),
                         "receiptId": None, "classifiedClockEpoch": None}


def handoff_receipt_stdin(timeout=5):
    """Read a private POSIX frame with one total deadline, not per-read timeouts."""
    import select
    if IS_WINDOWS:
        raise handoff_error("receipt_channel_unsupported")
    deadline = handoff_now() + timeout
    try:
        fd = sys.stdin.buffer.fileno()
        raw = bytearray()
        while True:
            remaining = deadline - handoff_now()
            if remaining <= 0 or not select.select([fd], [], [], max(0, remaining))[0]:
                raise handoff_error("invalid_receipt")
            chunk = os.read(fd, 4097 - len(raw))
            if not chunk:
                return bytes(raw)
            raw.extend(chunk)
            if len(raw) > 4096:
                raise handoff_error("invalid_receipt")
    except (OSError, ValueError, AttributeError) as exc:
        raise handoff_error("invalid_receipt") from exc


def cmd_handoff(args):
    ledger = HandoffLedger()
    action = args.handoff_action
    if action == "init":
        epoch = ledger.initialize()
        emit(args.json, {"ok": True, "ledgerEpoch": epoch}, "Private handoff ledger initialized.", command="handoff")
        return 0
    if action == "prepare":
        text = read_message(args)
        binding, generation, _ = handoff_binding(args, text)
        epoch, record = ledger.prepare(binding, generation, native_context=handoff_native_context(args))
        emit(args.json, {"ok": True, "handoff": handoff_public(epoch, record)}, "Handoff intent prepared; nothing sent.", command="handoff")
        return 0
    if action == "confirm":
        frame = handoff_private_wire(handoff_receipt_stdin(), confirmation=True)
        handoff_confirm(ledger, frame)
        args.correlation_id = frame["correlationId"]
    correlation = handoff_uuid(args.correlation_id)
    try:
        epoch, record = ledger.record(correlation)
    except CcPeerError as exc:
        context = "id_unknown" if exc.details.get("reason") == "handoff_id_unknown" else "ledger_corrupt" if exc.details.get("reason") == "handoff_ledger_corrupt" else "ledger_missing"
        result = handoff_query_error(correlation, context)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print("Handoff history unavailable; do not resend.", file=sys.stderr)
        return 1
    code = handoff_wait(ledger, correlation, args.wait_for, args.wait_timeout) if action == "wait" else 0
    epoch, record = ledger.record(correlation)
    result = dict(record["native"] or {})
    result.update(ok=code == 0, handoff=handoff_public(epoch, record, handoff_channel_epoch(ledger) if record["capability"] and not record["ack"] else None))
    emit(args.json, result, "Handoff " + result["handoff"]["state"] + "; no native submission performed.", command="handoff")
    return code


def cmd_ack(args, root=None):
    frame = handoff_private_wire(handoff_receipt_stdin())
    result = handoff_ipc(handoff_root() if root is None else root, frame)
    # Deliberately no token, digest, arbitrary body or generic query information.
    emit(args.json, {"ok": True, "duplicate": result["duplicate"], "classification": "pending" if result.get("pending") else "committed"}, "Receipt recorded.", command="ack")
    return 0


def handoff_requested(args):
    return any(getattr(args, key, None) for key in ("correlation_id", "request_ack", "observe_delivery", "wait_for"))


def handoff_binding(args, text):
    import hashlib
    adapter = AGENTS.for_target(args.to)
    generation = None
    session = None
    if not getattr(args, "host", None) and not getattr(args, "device", None) and adapter.name == "claude":
        session = resolve_target(discover(include_unreachable=True), args.to)
        generation = claude_generation(session)
        requested = getattr(args, "target_generation", None)
        if requested is not None:
            require_claude_generation(session, requested)
    target = str(session["pid"]) if session else args.to
    home = str(codex_home(args)) if adapter.name == "codex" else None
    if not getattr(args, "host", None) and not getattr(args, "device", None) and adapter.name == "codex":
        target = codex_thread(args.to)
        root, resolution = resolve_codex_home(args, codex_home(args), target)
        home = str(root)
        # Internal preparation evidence only, never an invented incarnation.
        args._handoff_codex_selection = (root, resolution)
    binding = {"agent": adapter.name, "destination": list(getattr(args, "host", []) or ["local"]),
               "target": target, "home": home,
               "payloadDigest": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    return binding, generation, session


def handoff_native_context(args):
    selected = getattr(args, "_handoff_codex_selection", None)
    if selected is None:
        return None
    root, resolution = selected
    context = {"root": str(root), "resolution": resolution}
    handoff_codex_resolution(resolution, str(root))
    if len(HandoffLedger.encode(context)) > 4096:
        raise handoff_error("native_context_capacity")
    return context


def handoff_child(argv, cutoff, total, env=None):
    """Use the shared owned-process primitive; never inspect a transcript."""
    if IS_WINDOWS or handoff_now() >= cutoff:
        raise handoff_error("deadline_before_effect")
    done = handoff_stream_child(argv, b"", cutoff, total, handoff_now, env=env)
    reasons = {"process_deadline": "native_deadline",
               "stderr_capacity": "native_diagnostic_capacity",
               "process_not_started": "native_process_failed",
               "process_clock_unavailable": "native_clock_failed",
               "process_cleanup_failed": "native_cleanup_failed"}
    reason = "native_output_capacity" if done.stdout_overflow else reasons.get(done.reason, done.reason)
    return {"returncode": done.returncode, "stdout": done.stdout, "stderr": done.stderr,
            "reason": reason, "interrupted": done.interrupted,
            "spawned": done.spawned, "cleanupFailed": done.cleanup_failed}


def handoff_codex_context(args, binding, cutoff, total):
    root, resolution = args._handoff_codex_selection
    if str(root) != binding["home"]:
        raise handoff_error("native_context_changed")
    executable = codex_executable(args)
    # A bounded harmless version query proves the selected queue executable is
    # callable. It does not certify all native versions or a writer generation.
    probe = handoff_child([executable, "--version"], cutoff, total, codex_process_environment(root))
    if probe["interrupted"]:
        raise KeyboardInterrupt
    try:
        version = probe["stdout"].decode("utf-8", errors="strict").strip()
    except UnicodeError as exc:
        raise handoff_error("native_version_unavailable") from exc
    if probe["reason"] or probe["returncode"] not in (0, -signal.SIGKILL) or re.fullmatch(r"codex-cli [0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version) is None:
        raise handoff_error("native_version_unavailable")
    revalidate_codex_home(root, binding["target"], resolution)
    return root, resolution, executable


def handoff_codex_submit(args, text, binding, context, cutoff, total):
    root, resolution, executable = context
    check_codex_message(text)
    # Reuse the original selected-home evidence, not a fresh auto-selection
    # after durable intent. This remains a pre-queue guard, not atomic identity.
    try:
        revalidate_codex_home(root, binding["target"], resolution)
    except CcPeerError as exc:
        raise CcPeerError("Codex handoff refused before queue", {"status": "refused", "retryAllowed": False}) from exc
    if handoff_now() >= cutoff:
        raise CcPeerError("Codex handoff refused before queue", {"status": "refused", "retryAllowed": False})
    env = codex_process_environment(root)
    done = handoff_child(codex_queue_argv(executable, binding["target"], text), cutoff, total, env)
    # Overflow is never salvaged from an apparently valid retained prefix.
    if done["reason"] == "native_output_capacity":
        if done["interrupted"]:
            raise KeyboardInterrupt
        raise handoff_error("native_outcome_unknown")
    try:
        stdout = done["stdout"].decode("utf-8", errors="strict")
    except UnicodeError as exc:
        if done["interrupted"]:
            raise KeyboardInterrupt from exc
        raise handoff_error("native_outcome_unknown") from exc
    marker = re.fullmatch(r"Queued message ([^\s]+) for thread (?i:" + re.escape(binding["target"]) + r")\.\r?\n?", stdout)
    # A matching complete native queue receipt is retained after disconnect or
    # deadline; partial/wrong-target output never supplies submission evidence.
    if marker is None:
        if done["interrupted"]:
            raise KeyboardInterrupt
        raise handoff_error("native_outcome_unknown")
    try:
        handoff_identifier(marker.group(1), 128)
    except CcPeerError:
        if done["interrupted"]:
            raise KeyboardInterrupt
        raise
    # This supported Codex mode has no pending explicit wait. An independently
    # proven native queue submission already satisfies its goal, even when
    # SIGINT ends transport cleanup. Never invent a stopped wait or a new
    # queued/true + false/130 non-wait tuple. Missing proof above stays unknown.
    result = {"ok": True, "target": {"agent": "codex", "id": binding["target"]}, "chars": len(text),
              "dryRun": False, "codexHome": str(root), "submitted": True, "consumptionConfirmed": False,
              "status": "queued", "codexHomeResolution": resolution}
    result["queueId"] = marker.group(1)
    handoff_validate_native(result, {"binding": binding})
    return result


def handoff_refuse_send(ledger, correlation, args, reason, total, exit_code=1):
    with ledger.transaction(total) as state:
        record = state["records"][correlation]
        if record["phase"] != "prepared":
            raise handoff_error("handoff_already_attempted")
        record.update(phase="terminal", submission="refused", observe=args.observe_delivery,
                      ackRequested=args.request_ack or args.wait_for == "acknowledged")
        if args.wait_for:
            handoff_start_wait(record, args.wait_for, total - 5, None,
                       initial_status="unsupported" if reason == "evidence_unsupported" else "failed", reason=reason)
        if record["capability"]:
            record["capability"]["revoked"] = True
    epoch, record = ledger.record(correlation, total)
    emit(args.json, {"ok": False, "reason": reason, "handoff": handoff_public(epoch, record)},
         "Handoff refused before native submission.", command="send", host=args.host[0] if args.host else None)
    return exit_code


def cmd_handoff_send(args):
    """One fenced attempt; POSIX Claude receipt or Codex correlation-only.

    Remote source streaming and unproven Codex observation/cleanup are refused
    before effect, not silently converted to another transport or generic ACK.
    """
    total = handoff_now() + args.wait_timeout
    cutoff = total - 5
    if args.dry_run and (args.request_ack or args.observe_delivery or args.wait_for):
        raise NoTargetError("--dry-run cannot request observation, ACK or waiting")
    apply_reply_target(args)
    if len(args.host) > 32:
        raise NoTargetError("Handoff supports at most 32 destinations")
    if len(args.host) > 1:
        raise handoff_error("handoff_fanout_runtime_unsupported")
    message = getattr(args, "message_option", None)
    if message is None:
        message = args.message
    if args.b64 is None and getattr(args, "message_file", None) is None and (message is None or message == "-"):
        try:
            text = read_handoff_stdin(sys.stdin, cutoff, handoff_now)
        except HandoffStdinError as exc:
            # No canonical binding/epoch/ID is available at this boundary.
            emit(args.json, {"ok": False, **exc.details}, "Handoff input refused before native submission.", command="send")
            return exc.exit_code
    else:
        text = read_message(args)
    check_message(text, remote=bool(args.host))
    adapter = AGENTS.for_target(args.to)
    validate_agent_send(adapter, args, text)
    binding, generation, session = handoff_binding(args, text)
    ledger = HandoffLedger()
    epoch, prepared = ledger.prepare(binding, generation, args.correlation_id,
                                     total if args.wait_timeout <= 5 else cutoff, native_context=handoff_native_context(args))
    correlation = prepared["id"]
    if args.dry_run:
        if args.host or getattr(args, "device", None):
            raise handoff_error("handoff_route_unsupported")
        import copy
        checked_args = copy.copy(args)
        if adapter.name == "claude":
            # Resolve the original PID, not a mutable human alias.  The native
            # generation check remains the pre-effect incarnation guard.
            checked_args.to = binding["target"]
            checked_args.target_generation = generation
        try:
            if adapter.name == "codex":
                root, resolution = args._handoff_codex_selection
                revalidate_codex_home(root, binding["target"], resolution)
            result = LocalTransport().execute("send", adapter, checked_args, text)
            handoff_validate_dry_run(result, prepared)
        except (CcPeerError, OSError, UnicodeError):
            return handoff_refuse_send(ledger, correlation, args, "evidence_failed", total)
        result["handoff"] = handoff_public(epoch, prepared)
        emit(args.json, result, "Handoff validated; nothing sent.", command="send")
        return 0
    local_route = not IS_WINDOWS and not args.host and not getattr(args, "device", None) and not getattr(args, "wake", False)
    receipt_capable = local_route and session is not None and generation is not None
    effect_capable = local_route and (receipt_capable or adapter.name == "codex")
    reason = "insufficient_budget" if args.wait_timeout <= 5 else "deadline_before_effect" if handoff_now() >= cutoff else "evidence_unsupported" if not effect_capable or args.wait_for == "delivered" or (args.wait_for == "acknowledged" and not receipt_capable) else None
    wants_ack = args.request_ack or args.wait_for == "acknowledged"
    authority = None
    producer = None
    codex_context = None
    if reason is None and adapter.name == "codex":
        try:
            codex_context = handoff_codex_context(args, binding, cutoff, total)
        except KeyboardInterrupt:
            return handoff_refuse_send(ledger, correlation, args, "stopped_by_operator", total, 130)
        except CcPeerError:
            reason = "evidence_failed"
    if reason is None and wants_ack and receipt_capable:
        try:
            producer = handoff_producer_command(ledger, cutoff)
            handoff_ensure_collector(ledger, cutoff)
            authority = handoff_ipc(ledger.root, {"op": "mint", "ledgerEpoch": epoch,
                        "correlationId": correlation, "targetGeneration": generation}, cutoff)
        except CcPeerError:
            if args.wait_for == "acknowledged":
                reason = "evidence_unsupported"
            else:
                # Best effort keeps the independently supported native route;
                # no raw authority is put into its message if setup failed.
                with ledger.transaction(total) as state:
                    cap = state["records"][correlation]["capability"]
                    if cap is not None:
                        cap["revoked"] = True
    if reason is not None:
        return handoff_refuse_send(ledger, correlation, args, reason, total)
    if args.b64 is None and (not args.no_from or not args.no_reply_to):
        identity = sender_identity(args.reply_to)
        configured = configured_reply_host(args.reply_to)
        local_reply = configured is None or bool(identity and identity.get("host") and is_self_ssh_destination(str(identity["host"])))
        text = wrap_message(text, explicit_host=args.reply_to, with_from=not args.no_from,
                            with_reply=not args.no_reply_to, local_reply=local_reply, identity=identity)
    # This path performs a private bounded inbox call directly, so it must use
    # exactly the same untrusted-body boundary as LocalTransport. Native stdin,
    # --no-from/--no-reply-to and internal --b64 never bypass quoting.
    text = peer_delivery_message(text, adapter.name)
    if authority is not None:
        receipt = {"schemaVersion": 1, "kind": "receipt", "ledgerEpoch": epoch,
                   "correlationId": correlation, "targetGeneration": generation,
                   "receiptId": str(uuid.uuid4()), "capability": authority["capability"]}
        text += "\n\nReceipt-only delegated authority (not permission for other actions).\n" + \
                "An explicit correlated receipt can be submitted with the installed receipt-only handler " + shlex.join(producer) + \
                " using this private JSON on stdin (never as argv):\n" + HandoffLedger.encode(receipt).decode("utf-8")
    try:
        check_message(text, remote=False)
        if adapter.name == "codex":
            check_codex_message(text)
            root, resolution, _ = codex_context
            # Size a private prospective profile without claiming submission.
            # Reserve escaped queue-ID space before the only queue invocation.
            prospective = {"ok": True, "target": {"agent": "codex", "id": binding["target"]}, "chars": len(text),
                "dryRun": False, "codexHome": str(root), "submitted": True, "consumptionConfirmed": False,
                "status": "queued", "codexHomeResolution": resolution}
            handoff_validate_native(prospective, prepared)
            if len(HandoffLedger.encode(prospective)) > 8192 - 300:
                raise handoff_error("native_snapshot_capacity")
            native_success = None  # A profile cannot be invented before queue.
        else:
            native_success = {"ok": True, "target": {"pid": session["pid"], "name": session["name"]}, "chars": len(text), "dryRun": False}
            handoff_validate_native(native_success, prepared)
            if len(HandoffLedger.encode(native_success)) > 8192:
                raise handoff_error("native_snapshot_capacity")
    except (CcPeerError, UnicodeError):
        return handoff_refuse_send(ledger, correlation, args, "evidence_failed", total)
    if handoff_now() >= cutoff:
        return handoff_refuse_send(ledger, correlation, args, "deadline_before_effect", total)
    # Commit + fsync before the only native invocation. A crash now is unknown,
    # even if it occurred before socket creation. Recovery never re-invokes it.
    operation = None
    with ledger.transaction(cutoff) as state:
        record = state["records"][correlation]
        if record["phase"] != "prepared":
            raise handoff_error("handoff_already_attempted")
        if handoff_now() >= cutoff:
            raise handoff_error("deadline_before_effect")
        record.update(phase="attempted", submission="unknown", observe=args.observe_delivery, ackRequested=wants_ack)
        if args.wait_for:
            operation = handoff_start_wait(record, args.wait_for, cutoff, authority["clockEpoch"] if authority else None)
    interrupted = False
    try:
        if adapter.name == "codex":
            native = handoff_codex_submit(args, text, binding, codex_context, cutoff, total)
        else:
            require_claude_generation(session, generation)
            # The ordinary inbox adapter uses Python's current-process clock.
            native_now, shared_now = time.monotonic(), handoff_now()
            post_to_socket(session["socket"], text, pid=session["pid"], generation_session=session,
                           expected_generation=generation, effect_deadline=native_now + cutoff - shared_now,
                           total_deadline=native_now + total - shared_now)
            native = native_success
        submission = "submitted"
    except CcPeerError as exc:
        # Native explicit refusal is positive no-effect evidence, not a guess.
        submission = "refused" if exc.details.get("status") == "refused" else "unknown"
        native = {"ok": False, "reason": "native_submission_refused" if submission == "refused" else "native_outcome_unknown", "retryAllowed": False}
    except KeyboardInterrupt:
        interrupted = True
        native, submission = {"ok": False, "reason": "native_outcome_unknown", "retryAllowed": False}, "unknown"
    code = 130 if interrupted else 0 if submission == "submitted" else 1
    try:
        with ledger.transaction(total) as state:
            record = state["records"][correlation]
            record.update(phase="terminal", native=native, submission=submission)
            if submission != "submitted" and record["capability"]:
                record["capability"]["revoked"] = True
            if submission != "submitted" and operation is not None:
                current = next(wait for wait in record["waits"] if wait["operationId"] == operation)
                if current["status"] == "pending":
                    current.update(status="stopped" if interrupted else "failed",
                                   reason="stopped_by_operator" if interrupted else "evidence_failed")
        if submission == "submitted" and authority is not None:
            try:
                handoff_ipc(ledger.root, {"op": "classify", "schemaVersion": 1, "ledgerEpoch": epoch,
                         "correlationId": correlation, "targetGeneration": generation,
                         "capability": authority["capability"]}, total)
            except CcPeerError:
                pass  # Known native submission survives observer/classification failure.
        if args.wait_for and submission == "submitted":
            code = handoff_wait(ledger, correlation, args.wait_for, args.wait_timeout, cutoff,
                                authority["clockEpoch"] if authority else None, operation, total)
        epoch, record = ledger.record(correlation, total)
    except (CcPeerError, OSError, ValueError, KeyError, TypeError):
        # The durable effect fence already exists. A failed commit/query must
        # not erase independently validated native facts or invent handoff/ACK.
        result = dict(native)
        retained_code = 0 if submission == "submitted" and not args.wait_for else 130 if interrupted or code == 130 else 1
        result.update(ok=retained_code == 0, reason="handoff_history_unavailable", retryAllowed=False)
        emit(args.json, result, "Native outcome retained; handoff history unavailable. Do not resend.", command="send")
        return retained_code
    result = dict(native)
    result.update(ok=code == 0, handoff=handoff_public(epoch, record, authority["clockEpoch"] if authority else None))
    emit(args.json, result, "Handoff " + result["handoff"]["state"] + "; submission is not consumption.", command="send")
    return code
