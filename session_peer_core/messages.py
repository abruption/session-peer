def read_message(args: argparse.Namespace) -> str:
    named = getattr(args, "message_option", None)
    if sum(value is not None for value in (args.message, named, args.b64)) > 1:
        raise CcPeerError("Choose one message source: positional message, --message/-m, or internal --b64")
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
