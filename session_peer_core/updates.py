def remote_installed_version(host: str, ssh_opts: list[str],
                             ssh_info: dict | None = None) -> str | None:
    """Version of the copy *installed* on that machine.

    Not the same thing as asking the remote command to report itself:
    run_remote() ships our own source and runs that, so it would always echo
    our version back. The installed file is what a session over there will
    actually use, and it is what can fall behind.
    """
    check_ssh_argument(host, "--host")
    for opt in ssh_opts:
        check_ssh_argument(opt, "--ssh-opt")
    ssh_info = ssh_user_metadata(host, ssh_opts) if ssh_info is None else ssh_info
    probe = 'python3 "$HOME/.local/share/session-peer/session_peer.py" --version 2>/dev/null'
    try:
        done = subprocess.run(
            ["ssh", *ssh_opts, host, probe],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except FileNotFoundError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", "ssh not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ssh_failure_error(host, ssh_info, "timeout") from exc
    except OSError as exc:
        raise ssh_failure_error(host, ssh_info, "transport_failed", str(exc)) from exc
    out = done.stdout.strip()
    detail = done.stderr.strip() or f"ssh exited {done.returncode}"
    failure = classify_ssh_failure(detail, done.returncode) if done.returncode != 0 else None
    if failure:
        raise ssh_failure_error(host, ssh_info, failure, detail)
    return out.split()[-1] if out.startswith("session-peer") else None


def parse_version(text: str) -> tuple[int, ...]:
    """(1, 2, 3) from "v1.2.3". Unparseable parts sort lowest."""
    parts = text.strip().lstrip("vV").split(".")
    return tuple(int(p) if p.isdigit() else 0 for p in parts[:3])


def stable_version(text: object) -> tuple[int, int, int] | None:
    """Strict stable release version; prereleases and partial tags are ignored."""
    if not isinstance(text, str):
        return None
    match = re.fullmatch(r"[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", text.strip())
    if match is None:
        return None
    values = tuple(int(part) for part in match.groups())
    return values if all(value <= sys.maxsize for value in values) else None


def release_version(text: object) -> tuple[int, int, int, int, int] | None:
    """Strict comparable stable/alpha/beta/rc version without a packaging dependency."""
    if not isinstance(text, str):
        return None
    match = re.fullmatch(
        r"[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:(?:-)?(a|alpha|b|beta|rc|pre|preview)[.-]?(0|[1-9]\d*))?",
        text.strip(),
        re.IGNORECASE,
    )
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups()[:3])
    if any(value > sys.maxsize for value in (major, minor, patch)):
        return None
    label, serial = match.groups()[3:]
    if label is None:
        return major, minor, patch, 3, 0
    stage = {
        "a": 0,
        "alpha": 0,
        "b": 1,
        "beta": 1,
        "rc": 2,
        "pre": 2,
        "preview": 2,
    }[label.lower()]
    return major, minor, patch, stage, int(serial)


def normalized_version(version: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in version)


def update_cache_path() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME")
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return base / "session-peer" / "update.json"


def skill_update_cache_path() -> Path:
    return update_cache_path().with_name("skill-update.json")


def installed_skill_metadata(path: Path) -> dict:
    """Read only the small, published frontmatter fields; never execute a skill."""
    try:
        if path.stat().st_size > 16384:
            return {"version": None, "runtimeMinVersion": None}
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {"version": None, "runtimeMinVersion": None}
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", content, re.DOTALL)
    if match is None:
        return {"version": None, "runtimeMinVersion": None}
    block = re.search(r"(?m)^metadata:\s*\n((?:[ \t]+[^\n]*\n?)*)", match.group(1))
    if block is None:
        return {"version": None, "runtimeMinVersion": None}
    fields = dict(re.findall(r"(?m)^  ([a-z-]+):\s*[\"']?([0-9]+\.[0-9]+\.[0-9]+)[\"']?\s*$", block.group(1)))
    version = fields.get("version")
    minimum = fields.get("runtime-min-version")
    return {"version": version if stable_version(version) else None,
            "runtimeMinVersion": minimum if stable_version(minimum) else None}


def installed_skills() -> list[dict]:
    """Detect Claude and Codex skill paths without changing either manager."""
    agents_root = Path.home() / ".agents"
    claude_root = Path(os.environ.get("CLAUDE_CONFIG_DIR") or
                       os.environ.get("ANTHROPIC_CONFIG_DIR") or Path.home() / ".claude")
    agents_skill = agents_root / "skills/session-peer/SKILL.md"
    candidates = [(agents_skill, "agents"),
                  (claude_root / "skills/session-peer/SKILL.md", "claude")]
    locked = False
    try:
        lock = agents_root / ".skill-lock.json"
        if lock.stat().st_size <= 65536:
            value = json.loads(lock.read_text(encoding="utf-8"))
            locked = value.get("skills", {}).get("session-peer", {}).get("source") == "abruption/session-peer-skill"
    except (OSError, UnicodeError, ValueError, AttributeError):
        pass
    seen = set()
    result = []
    for path, location in candidates:
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_file() or resolved in seen:
                continue
        except (OSError, RuntimeError):
            continue
        seen.add(resolved)
        manager = "skills_cli" if resolved == agents_skill.resolve() and locked else (
            "runtime_installer" if location == "claude" else "manual")
        result.append({"location": location, "manager": manager,
                       **installed_skill_metadata(path)})
    return result


def update_notices_disabled(args: argparse.Namespace | None = None) -> bool:
    if args is not None and getattr(args, "no_update_notice", False):
        return True
    return os.environ.get(UPDATE_NOTICE_ENV, "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def read_update_cache(path: Path | None = None, now: float | None = None) -> dict:
    """Return an explicit internal cache state; never raise into a CLI command."""
    path = update_cache_path() if path is None else path
    now = time.time() if now is None else now
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            return {"status": "invalid", "reason": "not_regular"}
        if info.st_size > UPDATE_CACHE_MAX_BYTES:
            return {"status": "invalid", "reason": "too_large"}
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "missing"}
    except (OSError, UnicodeError, ValueError):
        return {"status": "invalid", "reason": "unreadable_or_malformed"}

    if not isinstance(value, dict) or value.get("schemaVersion") != UPDATE_CACHE_SCHEMA_VERSION:
        return {"status": "invalid", "reason": "schema"}
    latest = stable_version(value.get("latest"))
    checked_at = value.get("checkedAt")
    if (
        latest is None
        or isinstance(checked_at, bool)
        or not isinstance(checked_at, (int, float))
        or checked_at != checked_at
        or checked_at > now + 300
    ):
        return {"status": "invalid", "reason": "fields"}

    state = {
        "status": "fresh",
        "latest": normalized_version(latest),
        "checkedAt": float(checked_at),
    }
    if now - checked_at >= UPDATE_CACHE_TTL_SECONDS:
        state["status"] = "expired"
    return state


def write_update_cache(tag: str, path: Path | None = None,
                       checked_at: float | None = None) -> Path:
    """Atomically store only public release metadata with user-only permissions."""
    parsed = stable_version(tag)
    if parsed is None:
        raise ValueError("latest release is not a stable semantic version")
    path = update_cache_path() if path is None else path
    checked_at = time.time() if checked_at is None else checked_at
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    encoded = json.dumps({
        "schemaVersion": UPDATE_CACHE_SCHEMA_VERSION,
        "latest": normalized_version(parsed),
        "checkedAt": int(checked_at),
    }, separators=(",", ":")).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    descriptor = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return path


def update_refresh_lock_path(path: Path | None = None) -> Path:
    cache = update_cache_path() if path is None else path
    return cache.with_name("update.lock")


def schedule_update_refresh(path: Path | None = None, now: float | None = None,
                            popen=None) -> bool:
    """Start one detached refresh and return immediately; all failures are isolated."""
    path = update_cache_path() if path is None else path
    now = time.time() if now is None else now
    source = Path(__file__).resolve()
    if not source.is_file():  # `python3 -` on an SSH destination has no reusable source file.
        return False
    lock = update_refresh_lock_path(path)
    descriptor = None
    owns_lock = False
    try:
        lock.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            lock.parent.chmod(0o700)
        except OSError:
            pass
        try:
            descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            owns_lock = True
        except FileExistsError:
            try:
                if now - lock.stat().st_mtime < UPDATE_REFRESH_LOCK_SECONDS:
                    return False
                lock.unlink()
            except (FileNotFoundError, OSError):
                return False
            try:
                descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                owns_lock = True
            except FileExistsError:
                # Another invocation won the stale-lock replacement race.
                return False
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
        descriptor = None

        launch = subprocess.Popen if popen is None else popen
        options = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            options["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        else:
            options["start_new_session"] = True
        launch([sys.executable, str(source), UPDATE_REFRESH_ARG], **options)
        return True
    except Exception:
        if owns_lock:
            try:
                lock.unlink(missing_ok=True)
            except OSError:
                pass
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)


def refresh_update_cache_background() -> int:
    lock = update_refresh_lock_path()
    try:
        try:
            tag, _ = latest_release()
            write_update_cache(tag)
        except (CcPeerError, OSError, ValueError):
            pass
        try:
            write_update_cache(latest_skill_release(), skill_update_cache_path())
        except (CcPeerError, OSError, ValueError):
            pass
    finally:
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


def update_command() -> str:
    if not installed_as_distribution():
        return "session-peer update"
    prefix = tuple(part.lower() for part in Path(sys.prefix).parts)
    if "pipx" in prefix and "venvs" in prefix:
        return "pipx upgrade session-peer"
    if "uv" in prefix and "tools" in prefix:
        return "uv tool upgrade session-peer"
    return "python -m pip install --upgrade session-peer"


def prepare_client_update(args: argparse.Namespace, now: float | None = None,
                          launcher=None) -> dict | None:
    """Read only local cached state; an expired/missing cache refreshes later."""
    if update_notices_disabled(args):
        return None
    if getattr(args, "command", None) == "update" and not getattr(args, "host", []):
        return None
    state = read_update_cache(now=now)
    if state["status"] != "fresh":
        try:
            (schedule_update_refresh if launcher is None else launcher)()
        except Exception:
            pass
        return None
    current = release_version(__version__)
    latest = release_version(state["latest"])
    if current is None or latest is None or latest <= current:
        return None
    checked_at = datetime.fromtimestamp(state["checkedAt"], timezone.utc)
    return {
        "schemaVersion": UPDATE_CACHE_SCHEMA_VERSION,
        "status": "available",
        "current": __version__.lstrip("vV"),
        "latest": state["latest"],
        "checkedAt": checked_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "github_release_cache",
        "command": update_command(),
    }


def prepare_skill_updates(args: argparse.Namespace, now: float | None = None,
                          launcher=None) -> list[dict]:
    """Use only the local skill cache; notice without modifying installations."""
    if update_notices_disabled(args) or (
            getattr(args, "command", None) == "update" and not getattr(args, "host", [])):
        return []
    installs = installed_skills()
    if not installs:
        return []
    state = read_update_cache(skill_update_cache_path(), now=now)
    if state["status"] != "fresh":
        try:
            (schedule_update_refresh if launcher is None else launcher)()
        except Exception:
            pass
        return []
    latest = stable_version(state["latest"])
    checked_at = datetime.fromtimestamp(state["checkedAt"], timezone.utc)
    commands = {"skills_cli": "npx skills update session-peer",
                "runtime_installer": "./install.sh"}
    return [{"schemaVersion": 1, "status": "available", "current": item["version"],
             "latest": state["latest"], "location": item["location"],
             "manager": item["manager"], "command": commands.get(item["manager"]),
             "checkedAt": checked_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
             "source": "github_release_cache"}
            for item in installs if item["version"] is not None
            and stable_version(item["version"]) < latest]


def latest_skill_release() -> str:
    request = urllib.request.Request(
        "https://api.github.com/repos/abruption/session-peer-skill/releases/latest",
        headers={"Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=DETECT_TIMEOUT * 4) as response:
            value = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CcPeerError("could not check the session-peer skill release") from exc
    tag = value.get("tag_name") if isinstance(value, dict) else None
    if stable_version(tag) is None:
        raise CcPeerError("invalid session-peer skill release tag")
    return tag


def latest_release() -> tuple[str, str]:
    """(tag, download URL) of the newest release on GitHub."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=DETECT_TIMEOUT * 4) as response:
            release = json.load(response)
            if not isinstance(release, dict):
                raise ValueError("unexpected release response")
            tag = release.get("tag_name", "")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CcPeerError(
            f"could not reach GitHub to check for updates: {exc}. "
            f"On a host with no route out, update it from a machine that has one: "
            f"session-peer update --host <this host>"
        ) from exc
    if not tag:
        raise CcPeerError("GitHub returned no release tag")
    if stable_version(tag) is None:
        raise CcPeerError(f"GitHub returned a non-stable release tag: {tag!r}")
    return tag, f"https://raw.githubusercontent.com/{GITHUB_REPO}/{tag}/session_peer.py"


def installed_as_distribution() -> bool:
    """Do not overwrite a file owned by pip/pipx/uv with the script updater."""
    try:
        dist = metadata.distribution("session-peer")
    except metadata.PackageNotFoundError:
        return False
    target = Path(__file__).resolve()
    return any(Path(dist.locate_file(f)).resolve() == target for f in (dist.files or []))


def cmd_update(args: argparse.Namespace) -> int:
    if not args.host and installed_as_distribution():
        command = update_command()
        if args.check:
            tag, _ = latest_release()
            try:
                write_update_cache(tag)
            except (OSError, ValueError):
                pass
            latest, current = release_version(tag), release_version(__version__)
            outdated = latest is not None and current is not None and current < latest
            state = f"{tag} available" if outdated else "up to date"
            emit(
                args.json,
                {"current": __version__, "latest": tag, "outdated": outdated,
                 "managedBy": "package-manager", "updateCommand": command},
                f"session-peer {__version__} — {state}. Upgrade with: {command}",
                command="update",
            )
            return 0
        emit(
            args.json,
            {"current": __version__, "updated": False,
             "managedBy": "package-manager", "updateCommand": command},
            f"This installation is package-managed. Upgrade with: {command}",
            command="update",
        )
        return 0
    if args.host:
        exit_code = 0
        all_results = []
        tailnet_status = tailscale_status() or {}
        for requested_host in args.host:
            host = requested_host
            try:
                host = resolve_ssh_destination(requested_host, tailnet_status)
                ssh_opts = tailscale_ssh_options(requested_host, host) + args.ssh_opt
                shown_host = display_host(requested_host, host)
                ssh_info = ssh_user_metadata(requested_host, ssh_opts)
                there = remote_installed_version(requested_host, ssh_opts, ssh_info)

                if args.check:
                    if there is None:
                        state = "not installed"
                    elif there == __version__:
                        state = "up to date"
                    else:
                        state = f"{there} → {__version__} available"
                    all_results.append(json_result("update", {
                        **host_metadata(requested_host, host), **ssh_info,
                        "remoteVersion": there, "current": __version__,
                        "outdated": there != __version__,
                    }))
                    if not args.json:
                        print(f"{shown_host}: session-peer {there or '(none)'} — {state}")
                    continue

                if there == __version__:
                    all_results.append(json_result("update", {
                        **host_metadata(requested_host, host), **ssh_info,
                        "remoteVersion": there, "current": __version__,
                        "updated": False,
                    }))
                    if not args.json:
                        print(f"{shown_host} runs session-peer {there} — already current.")
                    continue

                new_version = push_to_remote(requested_host, ssh_opts, ssh_info)
                all_results.append(json_result("update", {
                    **host_metadata(requested_host, host), **ssh_info,
                    "previous": there, "current": __version__, "updated": True,
                }))
                if not args.json:
                    prev = there or "(none)"
                    print(f"{shown_host}: session-peer {prev} → {new_version}")

            except CcPeerError as exc:
                exit_code = EXIT_ERROR
                all_results.append(json_result(
                    "update",
                    {**host_metadata(requested_host, host), "error": str(exc), **exc.details},
                    ok=False,
                ))
                if not args.json:
                    print(f"session-peer: {requested_host}: {exc}", file=sys.stderr)
        if args.json:
            emit_json_results(all_results)
        return exit_code

    tag, url = latest_release()
    try:
        write_update_cache(tag)
    except (OSError, ValueError):
        pass
    latest, current = release_version(tag), release_version(__version__)
    if latest is None or current is None:
        raise CcPeerError("could not compare the installed and latest release versions")

    if args.check:
        state = "up to date" if current >= latest else f"{tag} available"
        emit(
            args.json,
            {"current": __version__, "latest": tag, "outdated": current < latest},
            f"session-peer {__version__} — {state}",
            command="update",
        )
        return 0

    if current >= latest:
        emit(
            args.json,
            {"current": __version__, "latest": tag, "updated": False},
            f"session-peer {__version__} is already current ({tag}).",
            command="update",
        )
        return 0

    target = Path(__file__).resolve()
    try:
        with urllib.request.urlopen(url, timeout=DETECT_TIMEOUT * 4) as response:
            source = response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise CcPeerError(f"could not download {tag}: {exc}") from exc
    if b"__version__" not in source:
        raise CcPeerError(f"what came back from {url} does not look like session_peer.py")

    # We are running from the file being replaced. Write beside it and rename,
    # so a failed download can't leave a half-written script behind.
    staged = target.with_suffix(".py.new")
    try:
        staged.write_bytes(source)
        staged.chmod(target.stat().st_mode & 0o777)
        staged.replace(target)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        raise CcPeerError(f"could not replace {target}: {exc}") from exc

    emit(
        args.json,
        {"current": __version__, "latest": tag, "updated": True, "path": str(target)},
        f"session-peer {__version__} → {tag}  ({target})",
        command="update",
    )
    return 0
