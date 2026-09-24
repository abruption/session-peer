#!/bin/sh
# session-peer installer.
#
#   ./install.sh                      install here
#   ./install.sh --host web-01        install on a remote machine over SSH
#   ./install.sh --host a --host b    ...on several
#   ./install.sh --uninstall          remove it
#
# Installs the program into ~/.local/share/session-peer, compatibility skills
# into separate Claude and Codex directories, and links ~/.local/bin/session-peer.
# Skills installed by another manager are left untouched.
#
# Remote installs push the files over the SSH connection itself, so the remote
# machine needs no internet access — which matters, since air-gapped hosts are
# one of the reasons this tool exists.

set -eu

RAW="https://raw.githubusercontent.com/abruption/session-peer/main"
CLAUDE_ROOT="${CLAUDE_CONFIG_DIR:-${ANTHROPIC_CONFIG_DIR:-$HOME/.claude}}"
CLAUDE_SKILL_DIR="$CLAUDE_ROOT/skills/session-peer"
CODEX_SKILL_DIR="$HOME/.agents/skills/session-peer"
PROGRAM_DIR="$HOME/.local/share/session-peer"
BIN_DIR="$HOME/.local/bin"
HOSTS=""
UNINSTALL=0

die() { echo "install.sh: $*" >&2; exit 1; }

usage() {
    cat <<'USAGE'
session-peer installer.

  ./install.sh                      install here
  ./install.sh --host web-01        install on a remote machine over SSH
  ./install.sh --host a --host b    ...on several
  ./install.sh --uninstall          remove it

Installs the program into ~/.local/share/session-peer, compatibility skills into
~/.claude/skills/session-peer and ~/.agents/skills/session-peer, and links
~/.local/bin/session-peer. Existing skills managed elsewhere are preserved.

Remote installs push the files over the SSH connection itself, so the remote
machine needs no internet access.
USAGE
    exit "${1:-0}"
}

validate_host() {
    case "$1" in
        -*) die "--host must not start with '-' (ssh would read it as an option)" ;;
    esac
    _lower=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -d ' =')
    case "$_lower" in
        *proxycommand*|*permitlocalcommand*|*localcommand*)
            die "--host must not carry proxy/local command options" ;;
    esac
}

while [ $# -gt 0 ]; do
    case "$1" in
        --host) [ $# -ge 2 ] || die "--host needs a value"; HOSTS="$HOSTS $2"; shift 2 ;;
        --host=*) HOSTS="$HOSTS ${1#--host=}"; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) usage 0 ;;
        *) die "unknown argument: $1 (try --help)" ;;
    esac
done

# --------------------------------------------------------------------------
# Local install
# --------------------------------------------------------------------------

fetch() {
    # fetch <url> <dest>
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$2" "$1"
    else
        die "need curl or wget to download $1"
    fi
}

# Resolve the directory containing this script, if it is a real file.
# When run via curl|sh, $0 is "sh" or a pipe — not a file we can dirname.
if [ -f "$0" ]; then
    src_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd 2>/dev/null) || src_dir=""
else
    src_dir=""
fi

install_skill_at() {
    skill_dir=$1
    skill_source=$2
    if [ -L "$skill_dir" ] || { [ -e "$skill_dir" ] && [ ! -f "$skill_dir/.session-peer-installer" ]; }; then
        echo "  skill preserved (managed elsewhere): $skill_dir"
        return
    fi
    if [ -L "$skill_dir/SKILL.md" ]; then
        echo "  skill preserved (linked file): $skill_dir/SKILL.md"
        return
    fi
    mkdir -p "$skill_dir"
    cp "$skill_source" "$skill_dir/SKILL.md"
    printf '%s\n' 'session-peer install.sh v1' > "$skill_dir/.session-peer-installer"
    echo "  skill installed: $skill_dir/SKILL.md"
}

remove_skill_at() {
    skill_dir=$1
    if [ -L "$skill_dir" ] || [ ! -f "$skill_dir/.session-peer-installer" ]; then
        echo "  skill preserved (not installer-owned): $skill_dir"
        return
    fi
    rm -f "$skill_dir/SKILL.md" "$skill_dir/.session-peer-installer"
    rmdir "$skill_dir" 2>/dev/null || true
}

install_here() {
    command -v python3 >/dev/null 2>&1 || die "python3 not found"

    mkdir -p "$PROGRAM_DIR" "$BIN_DIR"

    # Always copy or fetch — re-running upgrades rather than skipping.
    if [ -n "$src_dir" ] && [ -f "$src_dir/session_peer.py" ]; then
        cp "$src_dir/session_peer.py" "$PROGRAM_DIR/session_peer.py"
        if [ -f "$src_dir/skills/session-peer/SKILL.md" ]; then
            skill_source="$src_dir/skills/session-peer/SKILL.md"
        elif [ -f "$src_dir/SKILL.md" ]; then
            skill_source="$src_dir/SKILL.md"
        else
            tmp_dir=$(mktemp -d)
            trap 'rm -f "$tmp_dir/SKILL.md"; rmdir "$tmp_dir"' EXIT
            fetch "$RAW/skills/session-peer/SKILL.md" "$tmp_dir/SKILL.md"
            skill_source="$tmp_dir/SKILL.md"
        fi
    else
        fetch "$RAW/session_peer.py" "$PROGRAM_DIR/session_peer.py"
        tmp_dir=$(mktemp -d)
        trap 'rm -f "$tmp_dir/SKILL.md"; rmdir "$tmp_dir"' EXIT
        fetch "$RAW/skills/session-peer/SKILL.md" "$tmp_dir/SKILL.md"
        skill_source="$tmp_dir/SKILL.md"
    fi

    install_skill_at "$CLAUDE_SKILL_DIR" "$skill_source"
    install_skill_at "$CODEX_SKILL_DIR" "$skill_source"

    chmod +x "$PROGRAM_DIR/session_peer.py"
    ln -sf "$PROGRAM_DIR/session_peer.py" "$BIN_DIR/session-peer"

    version=$(python3 "$PROGRAM_DIR/session_peer.py" --version 2>/dev/null || echo "unknown")
    echo "installed $version on $(hostname)"
    echo "  command: $BIN_DIR/session-peer"

    case ":${PATH}:" in
        *":$BIN_DIR:"*) ;;
        *) echo "  note: $BIN_DIR is not on PATH; add it or call the script directly" ;;
    esac
}

uninstall_here() {
    [ -L "$BIN_DIR/session-peer" ] && [ "$(readlink "$BIN_DIR/session-peer")" = "$PROGRAM_DIR/session_peer.py" ] && rm -f "$BIN_DIR/session-peer"
    rm -f "$PROGRAM_DIR/session_peer.py"
    remove_skill_at "$CLAUDE_SKILL_DIR"
    remove_skill_at "$CODEX_SKILL_DIR"
    rmdir "$PROGRAM_DIR" 2>/dev/null || true
    echo "removed session-peer from $(hostname)"
}

# --------------------------------------------------------------------------
# Remote install — ship the files over the SSH connection, no internet needed
# --------------------------------------------------------------------------

remote_run() {
    host=$1
    validate_host "$host"

    if [ "$UNINSTALL" -eq 1 ]; then
        ssh "$host" 'R="${CLAUDE_CONFIG_DIR:-${ANTHROPIC_CONFIG_DIR:-$HOME/.claude}}"; P="$HOME/.local/share/session-peer"; B="$HOME/.local/bin/session-peer"; [ ! -L "$B" ] || [ "$(readlink "$B")" != "$P/session_peer.py" ] || rm -f "$B"; rm -f "$P/session_peer.py"; for D in "$R/skills/session-peer" "$HOME/.agents/skills/session-peer"; do if [ ! -L "$D" ] && [ -f "$D/.session-peer-installer" ]; then rm -f "$D/SKILL.md" "$D/.session-peer-installer"; rmdir "$D" 2>/dev/null || true; fi; done; rmdir "$P" 2>/dev/null || true; echo "removed session-peer from $(hostname)"'
        return
    fi

    # Locate source files: next to this script, or fetch to a temp dir.
    if [ -n "$src_dir" ] && [ -f "$src_dir/session_peer.py" ]; then
        py="$src_dir/session_peer.py"
        if [ -f "$src_dir/skills/session-peer/SKILL.md" ]; then
            skill="$src_dir/skills/session-peer/SKILL.md"
        elif [ -f "$src_dir/SKILL.md" ]; then
            skill="$src_dir/SKILL.md"
        else
            die "SKILL.md not found next to this script"
        fi
    else
        tmp_dir=$(mktemp -d)
        trap 'rm -rf "$tmp_dir"' EXIT
        fetch "$RAW/session_peer.py" "$tmp_dir/session_peer.py"
        fetch "$RAW/skills/session-peer/SKILL.md" "$tmp_dir/SKILL.md"
        py="$tmp_dir/session_peer.py"
        skill="$tmp_dir/SKILL.md"
    fi

    {
        echo 'set -eu'
        echo 'command -v python3 >/dev/null 2>&1 || { echo "python3 not found on $(hostname)" >&2; exit 1; }'
        echo 'R="${CLAUDE_CONFIG_DIR:-${ANTHROPIC_CONFIG_DIR:-$HOME/.claude}}"'
        echo 'mkdir -p "$HOME/.local/share/session-peer" "$HOME/.local/bin"'
        echo 'base64 -d > "$HOME/.local/share/session-peer/session_peer.py" <<'"'"'CC_PEER_PY'"'"''
        base64 < "$py"
        echo 'CC_PEER_PY'
        echo 'T=$(mktemp -d)'
        echo 'base64 -d > "$T/SKILL.md" <<'"'"'CC_PEER_SKILL'"'"''
        base64 < "$skill"
        echo 'CC_PEER_SKILL'
        echo 'for D in "$R/skills/session-peer" "$HOME/.agents/skills/session-peer"; do'
        echo '  if [ -L "$D" ] || { [ -e "$D" ] && [ ! -f "$D/.session-peer-installer" ]; } || [ -L "$D/SKILL.md" ]; then echo "skill preserved (managed elsewhere): $D"; continue; fi'
        echo '  mkdir -p "$D"; cp "$T/SKILL.md" "$D/SKILL.md"; printf "%s\n" "session-peer install.sh v1" > "$D/.session-peer-installer"; echo "skill installed: $D/SKILL.md"'
        echo 'done'
        echo 'rm "$T/SKILL.md"; rmdir "$T"'
        echo 'chmod +x "$HOME/.local/share/session-peer/session_peer.py"'
        echo 'ln -sf "$HOME/.local/share/session-peer/session_peer.py" "$HOME/.local/bin/session-peer"'
        echo 'echo "installed $(python3 "$HOME/.local/share/session-peer/session_peer.py" --version) on $(hostname)"'
    } | ssh "$host" sh
}

# --------------------------------------------------------------------------

if [ -n "$HOSTS" ]; then
    status=0
    set -f            # no globbing: --host '*' must not expand
    # shellcheck disable=SC2086 # deliberate split: HOSTS is a list we built
    for host in $HOSTS; do
        remote_run "$host" || { echo "install.sh: failed on $host" >&2; status=1; }
    done
    set +f
    exit "$status"
fi

if [ "$UNINSTALL" -eq 1 ]; then
    uninstall_here
else
    install_here
fi
