"""Operator-controlled native endpoint policy and bounded worker processes."""
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import session_peer as core
from .store import Rejected


_WSL_RELEASE = Path('/proc/sys/kernel/osrelease')
_WSLPATH = Path('/usr/bin/wslpath')
_WINDOWS_DRIVE_HOME = re.compile(
    r'^[A-Za-z]:\\(?:[^\x00-\x1f<>:"|?*\\/]+(?:\\|$))*$'
)


def is_wsl():
    """Use kernel evidence, not caller-controlled environment variables."""
    if sys.platform != 'linux':
        return False
    try:
        return 'microsoft' in _WSL_RELEASE.read_text(encoding='utf-8').lower()
    except OSError:
        return False


def windows_codex_home(home):
    """Convert one operator-owned mounted home without invoking a shell."""
    if not is_wsl():
        raise Rejected('wsl_codex_requires_wsl')
    if not _WSLPATH.is_file() or not os.access(_WSLPATH, os.X_OK):
        raise Rejected('wslpath_unavailable')
    try:
        done = subprocess.run(
            [str(_WSLPATH), '-w', home], capture_output=True, text=True,
            timeout=2, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Rejected('wsl_home_conversion_failed') from exc
    value = done.stdout.strip()
    if (done.returncode or not value or len(value) > 4096
            or not _WINDOWS_DRIVE_HOME.fullmatch(value)):
        raise Rejected('wsl_home_conversion_failed')
    return value


def validate_wsl_codex(binding):
    executable = binding.get('codexBin')
    if executable is None:
        return None
    if binding.get('agent') != 'codex':
        raise Rejected('unexpected_executable')
    if (not isinstance(executable, str) or '\0' in executable
            or len(executable) > 4096):
        raise Rejected('invalid_codex_executable')
    path = Path(executable)
    if (not path.is_absolute() or path.name.casefold() != 'codex.exe'
            or path.is_symlink()
            or not path.is_file() or not os.access(path, os.X_OK)):
        raise Rejected('invalid_codex_executable')
    return windows_codex_home(binding['codexHome'])


class Policy:
    def __init__(self, value):
        if not isinstance(value, dict) or set(value) != {'targets', 'peers'}:
            raise Rejected('invalid_policy')
        self.targets, self.peers = value['targets'], value['peers']
        if (not isinstance(self.targets, dict) or not 1 <= len(self.targets) <= 8
                or not isinstance(self.peers, dict) or len(self.peers) > 128):
            raise Rejected('invalid_policy')
        for alias, binding in self.targets.items():
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', alias) or not isinstance(binding, dict):
                raise Rejected('invalid_target_alias')
            if set(binding) - {'agent', 'target', 'codexHome', 'codexBin', 'antigravityHome'}:
                raise Rejected('invalid_target_binding')
            agent, target = binding.get('agent'), binding.get('target')
            if agent not in ('claude', 'codex', 'antigravity') or not isinstance(target, str) or not 0 < len(target) <= 256 or '\0' in target:
                raise Rejected('invalid_target_binding')
            if core.AGENTS.for_target(target).name != agent:
                raise Rejected('agent_target_conflict')
            home_key = {'codex': 'codexHome', 'antigravity': 'antigravityHome'}.get(agent)
            for key in ('codexHome', 'antigravityHome'):
                if key in binding and key != home_key:
                    raise Rejected('unexpected_home')
            if home_key:
                home = binding.get(home_key)
                if not isinstance(home, str) or '\0' in home or not Path(home).is_absolute():
                    raise Rejected('explicit_home_required')
            core.AGENTS.get(agent).identity(target, core.ExecutionContext('local', options(binding)))
        for fingerprint, rights in self.peers.items():
            if (not re.fullmatch(r'[a-f0-9]{64}', fingerprint) or not isinstance(rights, dict)
                    or set(rights) != {'capabilities', 'targets'}):
                raise Rejected('invalid_peer_policy')
            if (not isinstance(rights['capabilities'], list) or not rights['capabilities']
                    or any(x not in ('list', 'send') for x in rights['capabilities'])
                    or not isinstance(rights['targets'], list) or not rights['targets']
                    or any(not isinstance(x, str) or x not in self.targets for x in rights['targets'])):
                raise Rejected('invalid_peer_policy')

    def authorize(self, peer, operation, alias=None):
        rights = self.peers.get(peer)
        if not rights or operation not in rights['capabilities']:
            raise Rejected('operation_denied')
        if alias is not None and alias not in rights['targets']:
            raise Rejected('target_denied')
        return rights['targets']


def options(binding):
    args = core.build_parser().parse_args(['send', '--to', binding['target'], '--no-from', '--no-reply-to'])
    args.codex_home = binding.get('codexHome')
    args.codex_bin = binding.get('codexBin')
    args.codex_native_home = validate_wsl_codex(binding)
    # Native Windows file locks are not observable as POSIX advisory locks in
    # WSL.  The operator's explicit codexBin binding is therefore also the
    # bounded opt-in to queue for that fixed home when no WSL writer is visible.
    # Ordinary Linux/macOS relay bindings retain the live-writer requirement.
    args.allow_inactive_codex_home = args.codex_bin is not None
    args.antigravity_home = binding.get('antigravityHome')
    args.all = True
    return args


class Native:
    def __init__(self):
        self.slots = asyncio.Semaphore(2)

    async def invoke(self, binding, operation, text=None):
        async with self.slots:
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'session_peer_relay.worker',
                cwd=str(Path(core.__file__).resolve().parent),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            try:
                payload = json.dumps({'binding': binding, 'operation': operation, 'text': text}).encode()
                out, _ = await asyncio.wait_for(process.communicate(payload), 35 if operation == 'send' else 5)
                if process.returncode or len(out) > 60*1024:
                    raise ValueError('worker_failed')
                value = json.loads(out)
                if not isinstance(value, dict) or type(value.get('ok')) is not bool:
                    raise ValueError('invalid_worker_result')
                return value
            except asyncio.CancelledError:
                raise
            except Exception:
                return {'ok': False, 'status': 'unknown', 'reason': 'native_outcome_unknown',
                        'retryAllowed': False, 'consumptionConfirmed': False}
            finally:
                if process.returncode is None:
                    process.kill()
                await process.wait()
