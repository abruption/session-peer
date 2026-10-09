# Source in Bash or zsh: source /reviewed/path/sp.sh
# Remove only our alias: source /reviewed/path/sp-remove.sh
# No profile/PATH edits, command execution, argument reconstruction or eval.
if [ -n "${BASH_VERSION-}" ]; then
    if [ "${BASH_SOURCE[0]}" = "$0" ]; then
        printf '%s\n' 'Source sp.sh in Bash or zsh; executing it cannot change your shell.' >&2
        exit 1
    fi
elif [ -n "${ZSH_VERSION-}" ]; then
    case "$ZSH_EVAL_CONTEXT" in
        *:file) ;;
        *) printf '%s\n' 'Source sp.sh in Bash or zsh; executing it cannot change your shell.' >&2; exit 1 ;;
    esac
else
    printf '%s\n' 'sp.sh supports Bash and zsh only.' >&2
    # The exit fallback is needed when an unsupported shell executes the file.
    # shellcheck disable=SC2317
    return 1 2>/dev/null || exit 1
fi

# Do not inspect positional arguments: source without arguments inherits its
# caller's positional parameters in Bash. Activation always means activation.
if [ "${_SESSION_PEER_SP_OWNED-}" = 1 ]; then
    case "$(alias sp 2>/dev/null)" in
        "alias sp='session-peer'"|"sp=session-peer")
            return 0
            ;;
    esac
fi

if command -v sp >/dev/null 2>&1; then
    printf '%s\n' 'sp already exists; inspect type -a sp. Nothing was changed.' >&2
    return 1
fi
if ! command -v session-peer >/dev/null 2>&1; then
    printf '%s\n' 'session-peer is unavailable; select its existing installation on PATH first.' >&2
    return 1
fi
alias sp='session-peer'
_SESSION_PEER_SP_OWNED=1
