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
