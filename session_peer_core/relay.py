def optional_relay():
    if sys.version_info < (3, 11) or os.name != 'posix':
        raise CcPeerError('Paired devices require Python 3.11+ on macOS/Linux')
    try:
        from session_peer_relay import cli
        return cli
    except ImportError as exc:
        raise CcPeerError('Install session-peer[relay] to use paired devices') from exc


def cmd_optional_relay(args):
    return optional_relay().main(args.command, ["--help"] if args.relay_help else args.relay_args)
