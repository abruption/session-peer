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
SOURCE_MODE=release

die() { echo "install.sh: $*" >&2; exit 1; }

usage() {
    cat <<'USAGE'
session-peer installer.

  ./install.sh                      install here
  ./install.sh --host web-01        install on a remote machine over SSH
  ./install.sh --host a --host b    ...on several
  ./install.sh --uninstall          remove it
  ./install.sh --local-source       install trusted files beside this script
  ./install.sh --main               opt in to unverified development main

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
        --local-source) SOURCE_MODE=local; shift ;;
        --main) SOURCE_MODE=main; shift ;;
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

verify_release() {
    # Generated trusted verifier; never import or run a downloaded verifier.
    python3 - "$1" <<'SESSION_PEER_RELEASE_VERIFIER'
"""Verify release bytes before compiling, running, or installing downloaded code."""

import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request


RELEASE_REPOSITORY = "abruption/session-peer"
RELEASE_BUILDER = RELEASE_REPOSITORY + "/.github/workflows/prepare-release.yml"
RELEASE_SOURCE_LIMIT = 8 * 1024 * 1024
RELEASE_METADATA_LIMIT = 1024 * 1024
RELEASE_SUPPORT_LIMIT = 256 * 1024


class ReleaseVerificationError(RuntimeError):
    pass


def release_read(url, limit):
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                 "User-Agent": "session-peer-release-verifier"})
    with urllib.request.urlopen(request, timeout=30) as response:
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isdigit() or int(length) > limit):
            raise ReleaseVerificationError("release download exceeds its size limit")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ReleaseVerificationError("release download exceeds its size limit")
    return data


def release_json(path):
    value = json.loads(release_read("https://api.github.com/repos/" + RELEASE_REPOSITORY + path,
                                    RELEASE_METADATA_LIMIT))
    if not isinstance(value, dict):
        raise ReleaseVerificationError("invalid GitHub release metadata")
    return value


def release_commit(tag):
    obj = release_json("/git/ref/tags/" + tag).get("object", {})
    for _ in range(4):
        if not isinstance(obj, dict) or not re.fullmatch(r"[0-9a-f]{40}", obj.get("sha", "")):
            break
        if obj.get("type") == "commit":
            return obj["sha"]
        if obj.get("type") != "tag":
            break
        obj = release_json("/git/tags/" + obj["sha"]).get("object", {})
    raise ReleaseVerificationError("release tag does not resolve to a full commit SHA")


def release_attest(path, commit):
    if shutil.which("gh") is None:
        raise ReleaseVerificationError("verified standalone installation needs GitHub CLI (gh) with "
                                       "attestation verify support; install/upgrade gh or use pip/uv/pipx")
    command = ["gh", "attestation", "verify", str(path), "--repo", RELEASE_REPOSITORY,
               "--signer-workflow", RELEASE_BUILDER, "--source-ref", "refs/heads/main",
               "--source-digest", commit, "--cert-oidc-issuer", "https://token.actions.githubusercontent.com",
               "--deny-self-hosted-runners", "--format", "json"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=120)
        result = json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        raise ReleaseVerificationError("could not verify release build attestation; install/upgrade gh") from error
    if done.returncode or not isinstance(result, list) or not result:
        raise ReleaseVerificationError("release build attestation did not verify against protected main: "
                                       + done.stderr.strip()[:1000])


def release_validate_runtime(path, version):
    source = path.read_bytes()
    if len(source) > RELEASE_SOURCE_LIMIT:
        raise ReleaseVerificationError("standalone artifact exceeds its size limit")
    try:
        tree = ast.parse(source, filename=str(path))
        versions = [node.value.value for node in tree.body
                    if isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "__version__"
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
        if versions != [version]:
            raise ReleaseVerificationError("standalone literal __version__ does not match release tag")
        compile(tree, str(path), "exec")
        done = subprocess.run([sys.executable, "-I", str(path), "--version"],
                              capture_output=True, text=True, timeout=15)
    except (SyntaxError, UnicodeError, OSError, subprocess.TimeoutExpired) as error:
        raise ReleaseVerificationError("standalone artifact does not compile/run") from error
    if done.returncode or done.stdout.strip() != "session-peer " + version:
        raise ReleaseVerificationError("staged standalone --version does not match release tag")


def release_tag_version(tag, allow_prerelease=False):
    if not isinstance(tag, str):
        raise ReleaseVerificationError("release has no canonical version tag")
    match = re.fullmatch(r"v((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))"
                         r"(?:(a|b|rc)(0|[1-9]\d*)|-(alpha|beta|rc)\.(0|[1-9]\d*))?", tag)
    if match is None or (not allow_prerelease and any(match.groups()[1:])):
        raise ReleaseVerificationError("release has no canonical version tag allowed for this operation")
    version, label, serial, long_label, long_serial = match.groups()
    if long_label:
        label, serial = {"alpha": "a", "beta": "b", "rc": "rc"}[long_label], long_serial
    return version + (label + serial if label else "")


def verified_release_download(directory, tag=None, include_support=False, event_release=False,
                              expected_commit=None):
    """Return the verified version; directory must be private and initially empty."""
    directory = Path(directory)
    try:
        if event_release:
            release_tag_version(tag, allow_prerelease=True)
        release = release_json("/releases/tags/" + tag if event_release else "/releases/latest")
        found = release.get("tag_name", "")
        version = release_tag_version(found, allow_prerelease=event_release)
        if tag is not None and found != tag:
            raise ReleaseVerificationError("latest release changed while preparing the update; retry")
        prerelease = release.get("prerelease")
        if (release.get("immutable") is not True or release.get("draft") is not False
                or type(prerelease) is not bool or (prerelease and not event_release)):
            raise ReleaseVerificationError("release is not immutable or allowed for this operation; use package-manager installation "
                                           "until a verified release is published")
        commit = release_commit(found)
        if expected_commit is not None and commit != expected_commit:
            raise ReleaseVerificationError("release tag differs from event commit")
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise ReleaseVerificationError("release assets are missing")
        by_name = {}
        prefix = "https://github.com/" + RELEASE_REPOSITORY + "/releases/download/" + found + "/"
        for asset in assets:
            if not isinstance(asset, dict) or not isinstance(asset.get("name"), str) or asset["name"] in by_name:
                raise ReleaseVerificationError("invalid or duplicate release asset")
            by_name[asset["name"]] = asset
        names = ["SHA256SUMS", "release-provenance.json", "session_peer.py"]
        if include_support:
            names += ["install.sh", "SKILL.md"]
        for name in names:
            asset = by_name.get(name, {})
            limit = RELEASE_SOURCE_LIMIT if name == "session_peer.py" else RELEASE_SUPPORT_LIMIT
            size = asset.get("size")
            if (type(size) is not int or not 0 < size <= limit
                    or asset.get("browser_download_url") != prefix + name):
                raise ReleaseVerificationError("missing, oversized, or invalid release asset: " + name)
            data = release_read(prefix + name, limit)
            if len(data) != size:
                raise ReleaseVerificationError("release asset size does not match metadata: " + name)
            (directory / name).write_bytes(data)
        # Authenticate the manifest before trusting any digest or running code.
        release_attest(directory / "SHA256SUMS", commit)
        entries = {}
        for line in (directory / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
            if not match or match[2] in entries:
                raise ReleaseVerificationError("invalid or duplicate release manifest entry")
            entries[match[2]] = match[1]
        expected = {"session_peer-" + version + "-py3-none-any.whl", "session_peer-" + version + ".tar.gz",
                    "session_peer.py", "install.sh", "SKILL.md"}
        if set(entries) != expected or set(by_name) != expected | {"SHA256SUMS", "release-provenance.json"}:
            raise ReleaseVerificationError("release asset/manifest file set does not match the release contract")
        release_attest(directory / "release-provenance.json", commit)
        provenance = json.loads((directory / "release-provenance.json").read_bytes())
        if (not isinstance(provenance, dict) or provenance.get("repository") != RELEASE_REPOSITORY
                or provenance.get("commit") != commit or provenance.get("tag") != found
                or provenance.get("version") != version
                or provenance.get("workflow_ref") != RELEASE_BUILDER + "@refs/heads/main"
                or provenance.get("artifacts") != [{"filename": name, "sha256": digest}
                                                   for name, digest in sorted(entries.items())]):
            raise ReleaseVerificationError("release provenance does not match the tag/source/manifest")
        for name in names[2:]:
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != entries.get(name):
                raise ReleaseVerificationError("release checksum mismatch: " + name)
            release_attest(directory / name, commit)
        release_validate_runtime(directory / "session_peer.py", version)
        return version
    except ReleaseVerificationError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ReleaseVerificationError("could not download/verify the release: " + str(error)) from error

try:
    print(verified_release_download(Path(sys.argv[1]), include_support=True))
except ReleaseVerificationError as error:
    print("install.sh: " + str(error), file=sys.stderr)
    raise SystemExit(1)
SESSION_PEER_RELEASE_VERIFIER
}

prepare_source() {
    destination=$1
    if [ "$SOURCE_MODE" = release ]; then
        verify_release "$destination" || die "release verification failed; no files installed"
    elif [ "$SOURCE_MODE" = local ]; then
        [ -n "$src_dir" ] && [ -f "$src_dir/session_peer.py" ] || die "--local-source needs trusted local source files"
        cp "$src_dir/session_peer.py" "$destination/session_peer.py"
        if [ -f "$src_dir/skills/session-peer/SKILL.md" ]; then
            cp "$src_dir/skills/session-peer/SKILL.md" "$destination/SKILL.md"
        else
            cp "$src_dir/SKILL.md" "$destination/SKILL.md"
        fi
    else
        echo 'install.sh: explicit --main installs unverified development code' >&2
        fetch "$RAW/session_peer.py" "$destination/session_peer.py"
        fetch "$RAW/skills/session-peer/SKILL.md" "$destination/SKILL.md"
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

    # Same-filesystem staging protects an existing installation from partial
    # downloads and invalid artifacts. Only this invocation's files are removed.
    tmp_dir=$(mktemp -d "$PROGRAM_DIR/.install.XXXXXX")
    trap 'rm -f "$tmp_dir/session_peer.py" "$tmp_dir/SKILL.md" "$tmp_dir/install.sh" "$tmp_dir/SHA256SUMS" "$tmp_dir/release-provenance.json"; rmdir "$tmp_dir"' EXIT
    trap 'exit 1' HUP INT TERM
    prepare_source "$tmp_dir"
    version=$(python3 -I "$tmp_dir/session_peer.py" --version) || die "invalid standalone artifact"
    case "$version" in "session-peer "[0-9]*) ;; *) die "invalid standalone version" ;; esac
    chmod +x "$tmp_dir/session_peer.py"
    mv -f "$tmp_dir/session_peer.py" "$PROGRAM_DIR/session_peer.py"
    skill_source="$tmp_dir/SKILL.md"

    install_skill_at "$CLAUDE_SKILL_DIR" "$skill_source"
    install_skill_at "$CODEX_SKILL_DIR" "$skill_source"

    chmod +x "$PROGRAM_DIR/session_peer.py"
    ln -sf "$PROGRAM_DIR/session_peer.py" "$BIN_DIR/session-peer"

    version=$(python3 -I "$PROGRAM_DIR/session_peer.py" --version 2>/dev/null || echo "unknown")
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

    command -v python3 >/dev/null 2>&1 || die "python3 not found"
    tmp_dir=$(mktemp -d)
    trap 'rm -f "$tmp_dir/session_peer.py" "$tmp_dir/SKILL.md" "$tmp_dir/install.sh" "$tmp_dir/SHA256SUMS" "$tmp_dir/release-provenance.json"; rmdir "$tmp_dir"' EXIT
    prepare_source "$tmp_dir" || return 1
    py="$tmp_dir/session_peer.py"
    skill="$tmp_dir/SKILL.md"

    {
        echo 'set -eu'
        echo 'command -v python3 >/dev/null 2>&1 || { echo "python3 not found on $(hostname)" >&2; exit 1; }'
        echo 'R="${CLAUDE_CONFIG_DIR:-${ANTHROPIC_CONFIG_DIR:-$HOME/.claude}}"'
        echo 'mkdir -p "$HOME/.local/share/session-peer" "$HOME/.local/bin"'
        echo 'T=$(mktemp -d "$HOME/.local/share/session-peer/.install.XXXXXX")'
        printf '%s\n' 'trap '\''rm -f "$T/session_peer.py" "$T/SKILL.md"; rmdir "$T"'\'' EXIT' 'trap '\''exit 1'\'' HUP INT TERM'
        echo 'base64 -d > "$T/session_peer.py" <<'"'"'CC_PEER_PY'"'"''
        base64 < "$py"
        echo 'CC_PEER_PY'
        echo 'base64 -d > "$T/SKILL.md" <<'"'"'CC_PEER_SKILL'"'"''
        base64 < "$skill"
        echo 'CC_PEER_SKILL'
        echo 'V=$(python3 -I "$T/session_peer.py" --version)'
        echo 'case "$V" in "session-peer "[0-9]*) ;; *) echo "invalid standalone artifact" >&2; exit 1 ;; esac'
        echo 'chmod +x "$T/session_peer.py"; mv -f "$T/session_peer.py" "$HOME/.local/share/session-peer/session_peer.py"'
        echo 'for D in "$R/skills/session-peer" "$HOME/.agents/skills/session-peer"; do'
        echo '  if [ -L "$D" ] || { [ -e "$D" ] && [ ! -f "$D/.session-peer-installer" ]; } || [ -L "$D/SKILL.md" ]; then echo "skill preserved (managed elsewhere): $D"; continue; fi'
        printf '%s\n' '  mkdir -p "$D"; cp "$T/SKILL.md" "$D/SKILL.md"; printf "%s\n" "session-peer install.sh v1" > "$D/.session-peer-installer"; echo "skill installed: $D/SKILL.md"'
        echo 'done'
        echo 'chmod +x "$HOME/.local/share/session-peer/session_peer.py"'
        echo 'ln -sf "$HOME/.local/share/session-peer/session_peer.py" "$HOME/.local/bin/session-peer"'
        echo 'echo "installed $(python3 "$HOME/.local/share/session-peer/session_peer.py" --version) on $(hostname)"'
    } | ssh "$host" sh
    remote_status=$?
    rm -f "$tmp_dir/session_peer.py" "$tmp_dir/SKILL.md" "$tmp_dir/install.sh" "$tmp_dir/SHA256SUMS" "$tmp_dir/release-provenance.json"
    rmdir "$tmp_dir"
    trap - EXIT
    return "$remote_status"
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
