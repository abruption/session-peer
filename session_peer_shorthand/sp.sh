# Source in Bash or zsh: source /reviewed/path/sp.sh
# Remove only our alias: source /reviewed/path/sp.sh --remove
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
    return 1 2>/dev/null || exit 1
fi

case "$#:${1-}" in
    0:|1:--remove) ;;
    *) printf '%s\n' 'Usage: source sp.sh [--remove]' >&2; return 2 ;;
esac

# A marker alone is insufficient: never remove an alias changed by its owner.
if [ "${_SESSION_PEER_SP_OWNED-}" = 1 ]; then
    case "$(alias sp 2>/dev/null)" in
        "alias sp='session-peer'"|"sp=session-peer")
            if [ "${1-}" = --remove ]; then
                unalias sp
                unset _SESSION_PEER_SP_OWNED
            fi
            return 0
            ;;
    esac
fi

if command -v sp >/dev/null 2>&1; then
    printf '%s\n' 'sp already exists; inspect type -a sp. Nothing was changed.' >&2
    return 1
fi
if [ "${1-}" = --remove ]; then
    unset _SESSION_PEER_SP_OWNED
    return 0
fi
if ! command -v session-peer >/dev/null 2>&1; then
    printf '%s\n' 'session-peer is unavailable; select its existing installation on PATH first.' >&2
    return 1
fi
alias sp='session-peer'
_SESSION_PEER_SP_OWNED=1
