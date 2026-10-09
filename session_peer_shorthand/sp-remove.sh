# Source in the same Bash/zsh scope to remove only our unchanged owned alias.
# A separate file avoids interpreting inherited caller positional arguments.
if [ -n "${BASH_VERSION-}" ]; then
    if [ "${BASH_SOURCE[0]}" = "$0" ]; then
        printf '%s\n' 'Source sp-remove.sh in Bash or zsh.' >&2
        exit 1
    fi
elif [ -n "${ZSH_VERSION-}" ]; then
    case "$ZSH_EVAL_CONTEXT" in
        *:file) ;;
        *) printf '%s\n' 'Source sp-remove.sh in Bash or zsh.' >&2; exit 1 ;;
    esac
else
    printf '%s\n' 'sp-remove.sh supports Bash and zsh only.' >&2
    # The exit fallback is needed when an unsupported shell executes the file.
    # shellcheck disable=SC2317
    return 1 2>/dev/null || exit 1
fi
if [ "${_SESSION_PEER_SP_OWNED-}" = 1 ]; then
    case "$(alias sp 2>/dev/null)" in
        "alias sp='session-peer'"|"sp=session-peer")
            unalias sp
            unset _SESSION_PEER_SP_OWNED
            return 0
            ;;
    esac
fi
if command -v sp >/dev/null 2>&1; then
    printf '%s\n' 'sp was not created by this activation or has changed. Nothing was removed.' >&2
    return 1
fi
unset _SESSION_PEER_SP_OWNED
