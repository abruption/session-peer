def relay_install_guidance():
    requirement = shlex.quote('session-peer[relay]==' + __version__)
    if not installed_as_distribution():
        return {'installation': 'standalone_or_unknown',
                'nextAction': 'Keep the existing CLI. Choose a separate Python 3.11+ venv, pipx, or uv installation for the Relay extra; a skill/plugin does not install it.',
                'example': 'python3 -m venv .venv-session-peer && .venv-session-peer/bin/python -m pip install ' + requirement}
    prefix = tuple(part.lower() for part in Path(sys.prefix).parts)
    if 'pipx' in prefix and 'venvs' in prefix:
        manager, command = 'pipx', 'pipx install --force ' + requirement
    elif 'uv' in prefix and 'tools' in prefix:
        manager, command = 'uv', 'uv tool install --force ' + requirement
    elif sys.prefix != sys.base_prefix:
        manager, command = 'venv', 'python -m pip install ' + requirement
    else:
        return {'installation': 'pip_or_unknown',
                'nextAction': 'Use the original package manager with the Relay extra and Python 3.11+. Do not overwrite an externally managed Python installation.'}
    return {'installation': manager, 'command': command,
            'nextAction': 'Run explicitly in the original Python 3.11+ installation; no package or credentials have been changed.'}


def optional_relay():
    if sys.version_info < (3, 11) or os.name != 'posix':
        raise CcPeerError('Paired devices require Python 3.11+ on macOS/Linux; use a compatible environment (WSL on Windows)',
                          {'reason': 'relay_runtime_unsupported', 'guidance': relay_install_guidance()})
    try:
        from session_peer_relay import cli
        return cli
    except ImportError as exc:
        guidance = relay_install_guidance()
        raise CcPeerError('Install session-peer[relay] to use paired devices. ' +
                          guidance.get('command', guidance['nextAction']),
                          {'reason': 'relay_dependencies_missing', 'guidance': guidance}) from exc


def cmd_optional_relay(args):
    return optional_relay().main(args.command, ["--help"] if args.relay_help else args.relay_args)


def cmd_setup(args):
    if args.interactive and not args.mode:
        args.mode = input("Connection mode [local/ssh/relay]: ").strip()
        if args.mode not in ('local', 'ssh', 'relay'):
            raise CcPeerError('Choose local, ssh, or relay', {'reason': 'invalid_setup_mode'})
    if args.mode in ('local', 'ssh') or not args.mode:
        if args.action != 'plan' or args.apply:
            raise CcPeerError('Local/SSH setup only inspects capabilities; use the existing CLI',
                              {'reason': 'setup_action_unsupported'})
        if args.mode == 'ssh' and not args.host:
            result = {'ok': True, 'mode': 'ssh', 'nextAction': 'Choose --host, then use list and send --dry-run. The destination needs Python 3 and a POSIX-compatible shell; no Relay extra is needed.'}
        elif args.mode:
            # Existing list keeps its SSH option/response validation and partial
            # discovery semantics. This path never imports optional Relay code.
            return cmd_list(args)
        else:
            result = {'ok': True, 'choices': ['local', 'ssh', 'relay'],
                      'nextAction': 'Choose --mode local/ssh for the standard-library CLI, or --mode relay for explicit paired-device setup.',
                      'installation': relay_install_guidance(), 'changed': False}
        emit(args.json, result, json.dumps(human_text(result), ensure_ascii=False, indent=2), command='setup')
        return 0
    optional_relay()
    from session_peer_relay.setup import run
    result = run(args)
    exit_code = result.pop('_exit', 0 if result.get('ok') else 1)
    emit(args.json, result, json.dumps(human_text(result), ensure_ascii=False, indent=2), command='setup')
    return exit_code
