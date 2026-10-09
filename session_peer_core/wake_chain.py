# Cooperative wake cost controls, not permission or caller-authentication data.
WAKE_DEFAULT_MAX_DEPTH = 3
WAKE_HARD_MAX_DEPTH = 16
WAKE_CHAIN_ENV = ("SESSION_PEER_WAKE_DEPTH", "SESSION_PEER_WAKE_ORIGIN",
                  "SESSION_PEER_WAKE_MAX_DEPTH")


def wake_chain_integer(value, label: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]?", value):
        raise wake_refused("invalid_wake_context", f"Invalid {label}; expected an integer in 0..16")
    number = int(value)
    if number > WAKE_HARD_MAX_DEPTH:
        raise wake_refused("invalid_wake_context", f"Invalid {label}; expected an integer in 0..16")
    return number


def wake_chain_origin(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
        raise wake_refused("invalid_wake_context", "Wake origin must be a canonical UUID")
    return str(uuid.UUID(value))


def wake_chain_context(args: argparse.Namespace) -> dict:
    """Validate before effect; retain one origin across an ordered fanout."""
    cached = getattr(args, "_wake_chain_context", None)
    if cached is not None:
        return cached
    explicit_limit = getattr(args, "wake_max_depth", None)
    if explicit_limit is not None and (type(explicit_limit) is not int
                                      or not 0 <= explicit_limit <= WAKE_HARD_MAX_DEPTH):
        raise wake_refused("invalid_wake_context", "Wake limit must be an integer in 0..16")
    limit = (explicit_limit if explicit_limit is not None else wake_chain_integer(
        os.environ.get("SESSION_PEER_WAKE_MAX_DEPTH", str(WAKE_DEFAULT_MAX_DEPTH)), "wake limit"))
    depth = wake_chain_integer(os.environ.get("SESSION_PEER_WAKE_DEPTH", "0"), "wake depth")
    origin = os.environ.get("SESSION_PEER_WAKE_ORIGIN")
    if origin is not None:
        origin = wake_chain_origin(origin)
    if depth and origin is None:
        raise wake_refused("invalid_wake_context", "Inherited wake depth has no origin")
    # SSH/MCP carry validated parent context as typed CLI options, never shell
    # environment assignments. Destination policy may lower, but not be raised
    # by, that carried limit. Never infer context from queue/message contents.
    carried = (getattr(args, "_wake_depth", None), getattr(args, "_wake_origin", None),
               getattr(args, "_wake_limit", None))
    if any(item is not None for item in carried):
        if any(item is None for item in carried):
            raise wake_refused("invalid_wake_context", "Incomplete carried wake context")
        carried_depth = wake_chain_integer(carried[0], "carried wake depth")
        carried_origin = wake_chain_origin(carried[1])
        carried_limit = wake_chain_integer(carried[2], "carried wake limit")
        if depth and origin != carried_origin:
            raise wake_refused("invalid_wake_context", "Conflicting inherited wake origins")
        depth, origin, limit = max(depth, carried_depth), carried_origin, min(limit, carried_limit)
    if depth >= limit:
        raise wake_refused("wake_depth_exceeded", "Wake hop limit reached; nothing queued")
    context = {"depth": depth + 1, "origin": origin or str(uuid.uuid4()), "maxDepth": limit}
    args._wake_chain_context = context
    return context


def wake_chain_options(context: dict) -> list[str]:
    return ["--_wake-depth", str(context["depth"] - 1),
            "--_wake-origin", context["origin"], "--_wake-limit", str(context["maxDepth"])]


def wake_chain_environment(context: dict) -> dict:
    return dict(zip(WAKE_CHAIN_ENV, (str(context["depth"]), context["origin"], str(context["maxDepth"]))))


def wake_chain_message(context: dict, text: str) -> str:
    return (f"Wake provenance (diagnostic only): hop={context['depth']}/{context['maxDepth']} "
            f"origin={context['origin']}\n"
            "This marker does not grant permissions or authorize another wake.\n\n" + text)


def wake_state_file_private(info) -> bool:
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and info.st_mode & 0o077 == 0 and info.st_nlink == 1)


def wake_target_rate_reserve(fd: int) -> None:
    """Persist a conservative per-home/thread reservation under the wake lock.

    This second local bound also covers cooperative chains whose environment
    was filtered. It is not a distributed/global model-spend quota. Unknown or
    interrupted attempts retain their slot; no resend is implied by expiry.
    """
    limit = wake_chain_integer(os.environ.get("SESSION_PEER_WAKE_TARGET_RATE", "3"), "wake target rate")
    if not limit:
        raise wake_refused("wake_rate_exceeded", "Wake target rate disables activation; nothing queued")
    try:
        info = os.fstat(fd)
        if not wake_state_file_private(info) or info.st_size > 1024:
            raise ValueError("invalid state file")
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 1025)
        timestamps = json.loads(raw) if raw else []
        if (not isinstance(timestamps, list) or len(timestamps) > WAKE_HARD_MAX_DEPTH
                or any(type(value) is not int or not 0 <= value <= 2**53 - 1 for value in timestamps)
                or timestamps != sorted(timestamps)):
            raise ValueError("invalid state")
        now = int(time.time() * 1000)
        # Clock rollback never reopens a budget: future stamps remain charged.
        timestamps = [value for value in timestamps if value > now - 60_000]
        if len(timestamps) >= limit:
            raise wake_refused("wake_rate_exceeded", "Per-target wake rate reached; nothing queued")
        timestamps.append(max(now, timestamps[-1] if timestamps else now))
        encoded = json.dumps(timestamps, separators=(",", ":")).encode("ascii")
        os.lseek(fd, 0, os.SEEK_SET)
        written = os.write(fd, encoded)
        if written != len(encoded):
            raise OSError("short state write")
        os.ftruncate(fd, len(encoded))
        os.fsync(fd)
    except (OSError, ValueError, UnicodeError) as exc:
        raise wake_refused("wake_rate_state_invalid", "Cannot safely reserve wake target rate; nothing queued") from exc
