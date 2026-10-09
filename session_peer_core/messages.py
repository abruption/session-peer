def read_message(args: argparse.Namespace) -> str:
    named = getattr(args, "message_option", None)
    file_name = getattr(args, "message_file", None)
    if sum(value is not None for value in (args.message, named, args.b64, file_name)) > 1:
        raise CcPeerError("Choose one message source: positional message, --message/-m, or internal --b64")
    if file_name is not None:
        path = Path(file_name)
        before = handoff_private_stat(path)
        if before.st_size > 4 * MAX_MESSAGE_CHARS:
            raise CcPeerError("Private message file exceeds the message limit")
        try:
            fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
                    raise handoff_error("unsafe_message_file")
                raw = stream.read(4 * MAX_MESSAGE_CHARS + 1)
                final = os.fstat(stream.fileno())
                if (info.st_size, info.st_mtime_ns) != (final.st_size, final.st_mtime_ns) or len(raw) > 4 * MAX_MESSAGE_CHARS:
                    raise handoff_error("unsafe_message_file")
            return raw.decode("utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            raise handoff_error("invalid_private_message_file") from exc
    message = named if named is not None else args.message
    if args.b64 is not None:
        try:
            return base64.b64decode(args.b64, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise CcPeerError(f"--b64 is not valid base64-encoded UTF-8: {exc}") from exc
    if message is None or message == "-":
        if sys.stdin.isatty():
            raise CcPeerError(
                "no message given and stdin is a terminal — "
                "pass --message TEXT, a positional message, or pipe one in"
            )
        try:
            return sys.stdin.read()
        except UnicodeDecodeError as exc:
            raise CcPeerError(f"stdin is not valid UTF-8: {exc}") from exc
    return message
