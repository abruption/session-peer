# Antigravity is opt-in: only runtime-registered sessions are discoverable.
AGY_MAX_BYTES = 32768
AGY_FRAME_BYTES = 262144


def agy_error(code: str) -> AdapterError:
    return AdapterError('antigravity', code, 'Antigravity: ' + code)


def agy_uuid(value: str) -> str:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise agy_error('invalid_uuid')


def agy_private(path: Path, directory: bool = False) -> None:
    st = path.lstat()
    if (st.st_uid != os.getuid() or st.st_mode & 0o077 or
            (not stat.S_ISDIR(st.st_mode) if directory else stat.S_ISLNK(st.st_mode))):
        raise agy_error('unsafe_runtime_path')


def agy_root(create: bool = False) -> Path:
    if os.name != 'posix':
        raise agy_error('unsupported_platform')
    root = Path('/tmp') / ('session-peer-agy-' + str(os.getuid()))
    if create:
        root.mkdir(mode=0o700, exist_ok=True)
    if root.exists() or root.is_symlink():
        agy_private(root, True)
    return root


def agy_process(pid: int) -> dict:
    """No process environment or full argument collection."""
    if sys.platform.startswith('linux'):
        proc = Path('/proc') / str(pid)
        fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            raise agy_error('owner_not_live')
        return {'pid': pid, 'ppid': int(fields[1]), 'start': fields[19],
                'uid': proc.stat().st_uid, 'comm': (proc / 'comm').read_text().strip()}
    if sys.platform == 'darwin':
        p = subprocess.run(['ps', '-p', str(pid), '-o', 'ppid=', '-o', 'uid=', '-o', 'comm='],
                           capture_output=True, text=True, timeout=3)
        row = p.stdout.strip().split(None, 2)
        born = _process_start_time(pid)
        if len(row) != 3 or not born:
            raise agy_error('owner_not_live')
        return {'pid': pid, 'ppid': int(row[0]), 'uid': int(row[1]),
                'comm': Path(row[2]).name, 'start': born}
    raise agy_error('unsupported_platform')


def agy_has_presence(pid: int, home: Path, thread: str) -> bool:
    expected = (home / 'presence' / (thread + '.lock')).resolve()
    if sys.platform.startswith('linux'):
        for fd in (Path('/proc') / str(pid) / 'fd').iterdir():
            try:
                if fd.resolve(strict=True) == expected:
                    return True
            except OSError:
                pass
        return False
    executable = _lsof_executable()
    if not executable:
        raise agy_error('lsof_unavailable')
    p = subprocess.run([executable, '-a', '-p', str(pid), '-Fn'],
                       capture_output=True, text=True, timeout=3)
    if p.returncode:
        raise agy_error('presence_unverifiable')
    return any(line.startswith('n') and Path(line[1:]).resolve() == expected
               for line in p.stdout.splitlines())


def agy_owner(home: Path, thread: str) -> dict:
    pid = os.getppid()
    for _ in range(24):
        proc = agy_process(pid)
        if (proc['uid'] == os.getuid() and proc['comm'] == 'agy'
                and agy_has_presence(pid, home, thread)):
            return proc
        pid = proc['ppid']
        if pid <= 1:
            break
    raise agy_error('run_bridge_inside_target_tui')


def agy_owner_live(info: dict) -> bool:
    try:
        proc = agy_process(info['ownerPid'])
        return (proc['uid'] == os.getuid() and proc['comm'] == 'agy'
                and proc['start'] == info['ownerStart']
                and agy_has_presence(proc['pid'], Path(info['antigravityHome']), info['id']))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, CcPeerError):
        return False


def agy_read_frame(stream: socket.socket, timeout: float = 3) -> dict:
    data = bytearray()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise agy_error("frame_timeout")
        stream.settimeout(remaining)
        chunk = stream.recv(min(4096, AGY_FRAME_BYTES + 1 - len(data)))
        if not chunk:
            raise agy_error('incomplete_frame')
        data.extend(chunk)
        if len(data) > AGY_FRAME_BYTES:
            raise agy_error('frame_too_large')
        if b'\n' in data:
            line, rest = data.split(b'\n', 1)
            if rest:
                raise agy_error('invalid_frame')
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                raise agy_error('invalid_frame')
            if not isinstance(value, dict):
                raise agy_error('invalid_frame')
            return value


def agy_write_frame(stream: socket.socket, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode() + b'\n'
    if len(data) > AGY_FRAME_BYTES:
        raise agy_error('frame_too_large')
    stream.sendall(data)


def agy_peer_uid(stream: socket.socket) -> int:
    if sys.platform.startswith('linux'):
        import struct
        return struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    if sys.platform == 'darwin':
        import ctypes
        uid, gid = ctypes.c_uint(), ctypes.c_uint()
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.getpeereid(stream.fileno(), ctypes.byref(uid), ctypes.byref(gid)):
            raise agy_error('peer_identity_unavailable')
        return uid.value
    raise agy_error('unsupported_platform')


def agy_rpc(info: dict, request: dict) -> dict:
    path = agy_root() / (info['_key'] + '.sock')
    agy_private(path)
    if not stat.S_ISSOCK(path.lstat().st_mode):
        raise agy_error('unsafe_runtime_path')
    with socket.socket(socket.AF_UNIX) as stream:
        stream.settimeout(20)
        stream.connect(str(path))
        if agy_peer_uid(stream) != os.getuid():
            raise agy_error('wrong_uid')
        agy_write_frame(stream, request)
        return agy_read_frame(stream, 20)


def agy_registrations(args: argparse.Namespace) -> list[dict]:
    if os.name != 'posix':
        return []
    root = agy_root()
    selected = getattr(args, 'antigravity_home', None)
    selected = str(Path(selected).expanduser().resolve()) if selected else None
    rows = []
    for path in sorted(root.glob('*.json')):
        try:
            agy_private(path)
            if not path.is_file() or path.stat().st_size > 8192:
                continue
            info = json.loads(path.read_text())
            agy_uuid(info['id']); agy_uuid(info['generation'])
            if not re.fullmatch(r'[a-f0-9]{32}', path.stem):
                continue
            if info.get('schemaVersion') != 1 or (selected and info['antigravityHome'] != selected):
                continue
            info['_key'] = path.stem
            if not agy_owner_live(info):
                continue
            response = agy_rpc(info, {'op': 'status', 'generation': info['generation']})
            if response.get('ready') is True and response.get('generation') == info['generation']:
                rows.append(info)
        except (OSError, ValueError, TypeError, KeyError, CcPeerError):
            continue
    return rows


class AgyBridge:
    """One owner and generation; in-memory duplicate suppression, no retries."""
    def __init__(self, info: dict, api: Path, limit: int):
        self.info, self.api, self.limit = info, api, limit
        self.seen: dict[str, tuple[str, dict]] = {}

    def handle(self, req: dict) -> dict:
        import hashlib
        if req.get('generation') != self.info['generation']:
            raise agy_error('stale_generation')
        if not agy_owner_live(self.info):
            raise agy_error('owner_not_live')
        if req == {'op': 'status', 'generation': self.info['generation']}:
            return {'ready': True, 'generation': self.info['generation']}
        if set(req) != {'op', 'generation', 'target', 'requestId', 'text'} or req['op'] != 'send':
            raise agy_error('invalid_request')
        if req['target'] != self.info['id']:
            raise agy_error('wrong_target')
        ident = agy_uuid(req['requestId'])
        text = req['text']
        if not isinstance(text, str) or not text.strip() or '\0' in text or len(text.encode()) > AGY_MAX_BYTES:
            raise agy_error('invalid_message')
        signature = hashlib.sha256(text.encode()).hexdigest()
        if ident in self.seen:
            prior_sig, result = self.seen[ident]
            if prior_sig != signature:
                raise agy_error('request_id_conflict')
            return {**result, 'duplicateSuppressed': True}
        if len(self.seen) >= self.limit:
            raise agy_error('request_limit')
        result = {'ok': False, 'agent': 'antigravity', 'status': 'unknown',
                  'submitted': False, 'consumptionConfirmed': False, 'retryAllowed': False,
                  'requestId': ident, 'generation': self.info['generation'],
                  'antigravityHome': self.info['antigravityHome'],
                  'target': {'agent': 'antigravity', 'id': self.info['id']}}
        self.seen[ident] = signature, result
        try:
            # No shell; native stdout/stderr may contain credentials and are discarded.
            done = subprocess.run([str(self.api), 'send-message', '--title=session-peer',
                                   self.info['id'], text], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=15)
            result = {**result, 'nativeExitCode': done.returncode}
            if done.returncode == 0:
                result.update(ok=True, status='submitted', submitted=True)
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.seen[ident] = signature, result
        return result


def cmd_agy_bridge(args: argparse.Namespace) -> int:
    import hashlib
    if fcntl is None:
        raise agy_error('unsupported_platform')
    thread = agy_uuid(args.thread)
    home = Path(args.antigravity_home or '~/.gemini/antigravity-cli').expanduser().resolve()
    root = agy_root(True)
    key = hashlib.sha256((str(home) + '\0' + thread).encode()).hexdigest()[:32]
    sockpath, registration = root / (key + '.sock'), root / (key + '.json')
    if args.action == 'stop':
        # Take the lock: never delete another live bridge's files.
        for info in agy_registrations(args):
            if info['_key'] == key:
                response = agy_rpc(info, {'op': 'stop', 'generation': info['generation']})
                print(json.dumps(response)); return 0
        raise agy_error('not_registered')
    owner = agy_owner(home, thread)
    api = home / 'bin/agentapi'
    if not api.is_file() or not os.access(api, os.X_OK):
        raise agy_error('agentapi_unavailable')
    lockpath = root / (key + '.lock')
    fd = os.open(lockpath, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        agy_private(lockpath)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise agy_error('already_registered')
        sockpath.unlink(missing_ok=True)
        registration.unlink(missing_ok=True)
        info = {'schemaVersion': 1, 'agent': 'antigravity', 'id': thread,
                'name': thread, 'cwd': os.getcwd(), 'antigravityHome': str(home),
                'ownerPid': owner['pid'], 'ownerStart': owner['start'],
                'generation': str(uuid.uuid4()), 'bridgePid': os.getpid()}
        bridge = AgyBridge(info, api, args.max_requests)
        stopped = False
        def stop(signum, frame):
            nonlocal stopped
            stopped = True
        signals = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
        prior = {sig: signal.signal(sig, stop) for sig in signals}
        try:
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(sockpath)); sockpath.chmod(0o600)
                server.listen(4); server.settimeout(1)
                fd = os.open(registration, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'w') as out:
                    json.dump(info, out)
                print(json.dumps({'ready': True, 'generation': info['generation'],
                                  'expiresInSeconds': args.ttl}), flush=True)
                deadline = time.monotonic() + args.ttl
                while not stopped and time.monotonic() < deadline and agy_owner_live(info):
                    try:
                        client, _ = server.accept()
                    except socket.timeout:
                        continue
                    with client:
                        client.settimeout(3)
                        try:
                            if agy_peer_uid(client) != os.getuid():
                                continue
                            request = agy_read_frame(client)
                            if request == {'op': 'stop', 'generation': info['generation']}:
                                stopped = True
                                response = {'stopped': True}
                            else:
                                response = bridge.handle(request)
                            agy_write_frame(client, response)
                        except CcPeerError as exc:
                            with contextlib.suppress(OSError):
                                agy_write_frame(client, {'ok': False, 'status': 'refused', 'submitted': False,
                                                        'consumptionConfirmed': False, 'error': str(exc),
                                                        **exc.details, 'retryAllowed': False})
                        except (OSError, ValueError, TypeError):
                            pass
        finally:
            sockpath.unlink(missing_ok=True)
            registration.unlink(missing_ok=True)
            for sig, handler in prior.items():
                signal.signal(sig, handler)
    # Lock inode intentionally remains to prevent split-lock races.
    return 0


def agy_sender() -> dict | None:
    try:
        rows = agy_registrations(argparse.Namespace())
        if not rows:
            return None
        pid = os.getppid()
        for _ in range(24):
            matches = [row for row in rows if row['ownerPid'] == pid]
            if len(matches) == 1:
                thread = matches[0]['id']
                return {'agent': 'antigravity', 'id': thread, 'target': 'antigravity:' + thread}
            if matches:
                return None
            pid = agy_process(pid)['ppid']
            if pid <= 1:
                break
    except (OSError, ValueError, subprocess.SubprocessError, CcPeerError):
        pass
    return None


class AntigravityAdapter(AgentAdapter):
    name = 'antigravity'

    def identity(self, target: str, context: ExecutionContext) -> SessionIdentity:
        result = super().identity(target, context)
        agy_uuid(result.identifier)
        return result

    def remote_options(self, args: argparse.Namespace) -> list[str]:
        return [part for name in ('antigravity_home', 'antigravity_generation', 'request_id')
                if getattr(args, name, None) for part in ('--' + name.replace('_', '-'), getattr(args, name))]

    def list(self, context: ExecutionContext) -> DiscoveryResult:
        rows = agy_registrations(context.options)
        return {'sessions': [{k: v for k, v in {**row, 'status': 'registered',
                             'target': self.target(row['id'])}.items() if k != '_key'} for row in rows],
                'discovery': {'status': 'ok' if rows else 'not_installed',
                              'scope': 'registered_bridges', 'reason': None if rows else 'no_live_registration'}}

    def diagnose(self, context: ExecutionContext) -> dict:
        return {'status': 'available' if os.name == 'posix' and agy_registrations(context.options) else 'disabled',
                'scope': 'registered_bridges', 'checks': []}

    def validate_send(self, args: argparse.Namespace, text: str | None = None) -> None:
        super().validate_send(args, text)
        if getattr(args, 'request_id', None):
            agy_uuid(args.request_id)
            if not getattr(args, 'antigravity_generation', None):
                raise agy_error('request_id_requires_generation')
        if text is not None and ('\0' in text or len(text.encode()) > AGY_MAX_BYTES):
            raise agy_error('invalid_message')

    def submit(self, context: ExecutionContext, text: str) -> SubmissionResult:
        args = context.options
        thread = self.identity(args.to, context).identifier
        rows = [row for row in agy_registrations(args) if row['id'] == thread]
        if len(rows) != 1:
            raise agy_error('ambiguous_home' if rows else 'not_registered')
        info = rows[0]
        if getattr(args, 'antigravity_generation', None) not in (None, info['generation']):
            raise agy_error('stale_generation')
        if args.dry_run:
            return {'ok': True, 'status': 'dry_run', 'submitted': False,
                    'consumptionConfirmed': False, 'generation': info['generation'],
                    'antigravityHome': info['antigravityHome']}
        req = {'op': 'send', 'generation': info['generation'], 'target': thread,
               'requestId': getattr(args, 'request_id', None) or str(uuid.uuid4()), 'text': text}
        try:
            return agy_rpc(info, req)
        except (OSError, CcPeerError):
            return {'ok': False, 'agent': 'antigravity', 'status': 'unknown', 'submitted': False,
                    'consumptionConfirmed': False, 'retryAllowed': False,
                    'requestId': req['requestId'], 'generation': info['generation']}
