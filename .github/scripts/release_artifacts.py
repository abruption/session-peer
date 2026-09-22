#!/usr/bin/env python3
"""Fail-closed release source and artifact verification for GitHub Actions."""

from __future__ import annotations

import argparse
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "session-peer"
VERSION_PATTERN = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class VerificationError(RuntimeError):
    pass


def project_version(root: Path = ROOT) -> str:
    match = VERSION_PATTERN.search((root / "session_peer.py").read_text(encoding="utf-8"))
    if not match:
        raise VerificationError("session_peer.py has no literal __version__ assignment")
    return match.group(1)


def git(*args: str, root: Path = ROOT) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


MAINTENANCE_BRANCH = "release/0.9.x"
MAINTENANCE_BASE = "d68aab73ad5be806da03281e30b73e74ed63db78"  # reviewed v0.9.1
REPOSITORY = "abruption/session-peer"


def verify_source(tag: str, target: str, expected_sha: str, root: Path = ROOT) -> str:
    version = project_version(root)
    if not re.fullmatch(r"0\.9\.(?:[2-9]|[1-9][0-9]+)", version) or tag != "v" + version:
        raise VerificationError("maintenance publication requires canonical v0.9.N, N >= 2; no RC/dev/local versions")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise VerificationError("event commit must be a full lowercase Git SHA")
    head = git("rev-parse", "HEAD", root=root)
    if head != expected_sha:
        raise VerificationError("checked-out commit does not match event commit")
    if git("rev-parse", f"refs/tags/{tag}^{{commit}}", root=root) != head:
        raise VerificationError("tag does not resolve to the checked-out commit")
    branch_head = git("rev-parse", f"refs/remotes/origin/{MAINTENANCE_BRANCH}", root=root)
    if branch_head != head:
        raise VerificationError("release commit is not the current maintenance branch tip")
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", MAINTENANCE_BASE, head],
            cwd=root, check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as error:
        raise VerificationError("release commit does not descend from the pinned v0.9.1 baseline") from error
    if target not in {MAINTENANCE_BRANCH, "refs/heads/" + MAINTENANCE_BRANCH, head}:
        raise VerificationError("release target must be release/0.9.x or the exact full release SHA")
    if git("status", "--porcelain", root=root):
        raise VerificationError("release checkout is not clean")
    return version


def github_json(endpoint: str):
    # gh receives GH_TOKEN from the workflow environment, never argv/output.
    try:
        done = subprocess.run(["gh", "api", "--method", "GET", endpoint],
                              check=True, capture_output=True, text=True, timeout=30)
        return json.loads(done.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise VerificationError("GitHub release-policy evidence unavailable; publication denied") from error


def verify_governance(commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise VerificationError("governance commit must be a full lowercase Git SHA")
    prefix = "repos/" + REPOSITORY
    branch = github_json(prefix + "/branches/release%2F0.9.x")
    if (branch.get("name") != MAINTENANCE_BRANCH or branch.get("protected") is not True
            or branch.get("commit", {}).get("sha") != commit):
        raise VerificationError("maintenance branch must be protected and still point to the release commit")
    checks = branch.get("protection", {}).get("required_status_checks", {})
    if (checks.get("enforcement_level") != "everyone"
            or {"context": "release gate", "app_id": 15368} not in checks.get("checks", [])):
        raise VerificationError("maintenance release gate must be enforced for everyone by GitHub Actions")
    pulls = github_json(prefix + "/commits/" + commit + "/pulls?per_page=100")
    merged = [pr for pr in pulls if pr.get("merged_at") and pr.get("state") == "closed"
              and pr.get("merge_commit_sha") == commit
              and pr.get("base", {}).get("ref") == MAINTENANCE_BRANCH
              and pr.get("base", {}).get("repo", {}).get("full_name") == REPOSITORY]
    if not merged:
        raise VerificationError("release commit must be the result of a merged maintenance PR")
    runs = github_json(prefix + "/actions/workflows/ci.yml/runs?head_sha=" + commit
                       + "&event=push&branch=release%2F0.9.x&per_page=100")
    matching = [run for run in runs.get("workflow_runs", [])
                if run.get("head_sha") == commit and run.get("head_branch") == MAINTENANCE_BRANCH
                and run.get("event") == "push" and run.get("path") == ".github/workflows/ci.yml"
                and run.get("repository", {}).get("full_name") == REPOSITORY]
    latest = max(matching, key=lambda run: run["id"]) if matching else None
    if not latest or latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise VerificationError("latest push CI for the exact merged maintenance commit must succeed")
    return {"commit": commit, "branch": MAINTENANCE_BRANCH,
            "pull_requests": sorted(pr["number"] for pr in merged), "ci_run": latest["id"]}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_artifacts(directory: Path) -> tuple[Path, Path]:
    wheels = sorted(directory.glob("*.whl"))
    sdists = sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise VerificationError(
            f"expected exactly one wheel and one sdist in {directory}; "
            f"found {len(wheels)} wheel(s) and {len(sdists)} sdist(s)"
        )
    return wheels[0], sdists[0]


def _metadata_value(text: str, key: str) -> str:
    value = Parser().parsestr(text).get(key)
    if not value:
        raise VerificationError(f"archive metadata has no {key}")
    return value


def verify_artifacts(directory: Path, version: str) -> dict[str, str]:
    wheel, sdist = package_artifacts(directory)
    expected_wheel = f"session_peer-{version}-py3-none-any.whl"
    expected_sdist = f"session_peer-{version}.tar.gz"
    if wheel.name != expected_wheel or sdist.name != expected_sdist:
        raise VerificationError(
            "artifact filenames do not match the package/version contract: "
            f"expected {expected_wheel!r} and {expected_sdist!r}"
        )
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise VerificationError("wheel must contain exactly one METADATA file")
        wheel_metadata = archive.read(metadata_names[0]).decode("utf-8")
    with tarfile.open(sdist) as archive:
        metadata_members = [item for item in archive.getmembers() if item.isfile() and item.name.endswith("/PKG-INFO")]
        if len(metadata_members) != 1:
            raise VerificationError("sdist must contain exactly one PKG-INFO file")
        extracted = archive.extractfile(metadata_members[0])
        if extracted is None:
            raise VerificationError("sdist PKG-INFO could not be read")
        sdist_metadata = extracted.read().decode("utf-8")

    for kind, metadata in (("wheel", wheel_metadata), ("sdist", sdist_metadata)):
        if _metadata_value(metadata, "Name") != PACKAGE:
            raise VerificationError(f"{kind} package name does not match {PACKAGE}")
        if _metadata_value(metadata, "Version") != version:
            raise VerificationError(f"{kind} version does not match {version}")
    return {path.name: sha256(path) for path in (wheel, sdist)}


def write_manifest(directory: Path, version: str) -> Path:
    hashes = verify_artifacts(directory, version)
    manifest = directory / "SHA256SUMS"
    manifest.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())),
        encoding="utf-8",
    )
    return manifest


def read_manifest(directory: Path, version: str) -> dict[str, str]:
    expected_files = set(verify_artifacts(directory, version))
    manifest = directory / "SHA256SUMS"
    if not manifest.is_file():
        raise VerificationError("SHA256SUMS is missing")
    entries: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^/\\]+)", line)
        if not match:
            raise VerificationError(f"invalid SHA256SUMS line: {line!r}")
        digest, name = match.groups()
        if name in entries:
            raise VerificationError(f"duplicate SHA256SUMS entry: {name}")
        entries[name] = digest
    if set(entries) != expected_files:
        raise VerificationError("SHA256SUMS does not name exactly the wheel and sdist")
    for name, expected in entries.items():
        actual = sha256(directory / name)
        if actual != expected:
            raise VerificationError(f"checksum mismatch for {name}: expected {expected}, got {actual}")
    return entries


def compare_builds(first: Path, second: Path, version: str) -> None:
    first_hashes = verify_artifacts(first, version)
    second_hashes = verify_artifacts(second, version)
    if first_hashes != second_hashes:
        raise VerificationError(
            "independent builds are not byte-for-byte reproducible: "
            f"{first_hashes!r} != {second_hashes!r}"
        )


def write_provenance(
    directory: Path,
    version: str,
    repository: str,
    commit: str,
    tag: str,
    run_id: str,
    run_attempt: str,
    workflow_ref: str,
) -> Path:
    hashes = read_manifest(directory, version)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise VerificationError("provenance commit must be a full lowercase Git SHA")
    document = {
        "artifacts": [
            {"filename": name, "sha256": digest}
            for name, digest in sorted(hashes.items())
        ],
        "commit": commit,
        "package": PACKAGE,
        "repository": repository,
        "run_attempt": run_attempt,
        "run_id": run_id,
        "tag": tag,
        "version": version,
        "workflow_ref": workflow_ref,
    }
    output = directory / "release-provenance.json"
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def _pypi_json(version: str, attempts: int, delay: float) -> dict:
    url = f"https://pypi.org/pypi/{PACKAGE}/{version}/json"
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, headers={"User-Agent": "session-peer-release-verifier/1"})
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < attempts:
                time.sleep(delay)
    raise VerificationError(f"PyPI did not expose {PACKAGE} {version} after {attempts} attempts") from last_error


def download_from_pypi(expected_dir: Path, output_dir: Path, version: str, attempts: int, delay: float) -> None:
    expected = read_manifest(expected_dir, version)
    payload = _pypi_json(version, attempts, delay)
    release_version = payload.get("info", {}).get("version")
    if release_version != version:
        raise VerificationError(f"PyPI returned version {release_version!r}, expected {version!r}")
    files = {entry.get("filename"): entry for entry in payload.get("urls", [])}
    if set(files) != set(expected):
        raise VerificationError(
            f"PyPI file set {sorted(files)} does not match workflow artifacts {sorted(expected)}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise VerificationError(f"download directory {output_dir} is not empty")

    for name, expected_digest in sorted(expected.items()):
        entry = files[name]
        if entry.get("digests", {}).get("sha256") != expected_digest:
            raise VerificationError(f"PyPI metadata checksum mismatch for {name}")
        url = entry.get("url", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or not (parsed.hostname == "files.pythonhosted.org"):
            raise VerificationError(f"unexpected PyPI artifact URL for {name}: {url!r}")
        request = Request(url, headers={"User-Agent": "session-peer-release-verifier/1"})
        with urlopen(request, timeout=60) as response:
            data = response.read()
        destination = output_dir / name
        destination.write_bytes(data)
        if sha256(destination) != expected_digest:
            raise VerificationError(f"downloaded PyPI artifact checksum mismatch for {name}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subparsers = result.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version")

    source = subparsers.add_parser("verify-source")
    source.add_argument("--tag", required=True)
    source.add_argument("--target", required=True)
    source.add_argument("--expected-sha", required=True)

    governance = subparsers.add_parser("verify-governance")
    governance.add_argument("--commit", required=True)

    artifacts = subparsers.add_parser("verify-artifacts")
    artifacts.add_argument("--dist", type=Path, required=True)
    artifacts.add_argument("--version", required=True)
    artifacts.add_argument("--write-manifest", action="store_true")

    manifest = subparsers.add_parser("verify-manifest")
    manifest.add_argument("--dist", type=Path, required=True)
    manifest.add_argument("--version", required=True)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--first", type=Path, required=True)
    compare.add_argument("--second", type=Path, required=True)
    compare.add_argument("--version", required=True)

    provenance = subparsers.add_parser("write-provenance")
    provenance.add_argument("--dist", type=Path, required=True)
    provenance.add_argument("--version", required=True)
    provenance.add_argument("--repository", required=True)
    provenance.add_argument("--commit", required=True)
    provenance.add_argument("--tag", required=True)
    provenance.add_argument("--run-id", required=True)
    provenance.add_argument("--run-attempt", required=True)
    provenance.add_argument("--workflow-ref", required=True)

    download = subparsers.add_parser("download-pypi")
    download.add_argument("--expected", type=Path, required=True)
    download.add_argument("--output", type=Path, required=True)
    download.add_argument("--version", required=True)
    download.add_argument("--attempts", type=int, default=30)
    download.add_argument("--delay", type=float, default=10)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "version":
            print(project_version())
        elif args.command == "verify-source":
            print(verify_source(args.tag, args.target, args.expected_sha))
        elif args.command == "verify-governance":
            print(json.dumps(verify_governance(args.commit), sort_keys=True))
        elif args.command == "verify-artifacts":
            if args.write_manifest:
                print(write_manifest(args.dist, args.version))
            else:
                print(json.dumps(verify_artifacts(args.dist, args.version), sort_keys=True))
        elif args.command == "verify-manifest":
            print(json.dumps(read_manifest(args.dist, args.version), sort_keys=True))
        elif args.command == "compare":
            compare_builds(args.first, args.second, args.version)
        elif args.command == "write-provenance":
            print(
                write_provenance(
                    args.dist,
                    args.version,
                    args.repository,
                    args.commit,
                    args.tag,
                    args.run_id,
                    args.run_attempt,
                    args.workflow_ref,
                )
            )
        elif args.command == "download-pypi":
            download_from_pypi(args.expected, args.output, args.version, args.attempts, args.delay)
    except (OSError, subprocess.CalledProcessError, VerificationError, zipfile.BadZipFile, tarfile.TarError) as error:
        print(f"release verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
