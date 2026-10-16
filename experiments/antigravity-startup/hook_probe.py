"""Opt-in test-only SessionStart probe; never persist the raw hook payload/env."""
import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--runtime', required=True)
    args = parser.parse_args()
    output = Path(args.output_dir)
    # Operator-created private scratch only, not a shared log or repository.
    if output.stat().st_uid != os.getuid() or output.stat().st_mode & 0o077:
        raise ValueError('private output directory required')
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ValueError('hook input too large')
    data = json.loads(raw)
    thread = str(uuid.UUID(data['conversationId']))
    record = {
        'observedMonotonic': time.monotonic(),
        'conversationId': thread,
        'hookPid': os.getpid(),
        'hookParentPid': os.getppid(),
        'contextPresent': {
            name: bool(os.environ.get(name)) for name in (
                'ANTIGRAVITY_LS_ADDRESS', 'ANTIGRAVITY_CSRF_TOKEN',
                'ANTIGRAVITY_CONVERSATION_ID', 'ANTIGRAVITY_TRAJECTORY_ID',
            )
        },
    }
    # Inherit the legitimate hook environment; never read or copy token values.
    # Unchanged runtime must prove ancestor/presence itself; no replacement owner.
    proc = subprocess.Popen(
        [sys.executable, args.runtime, 'antigravity-bridge', 'serve',
         '--thread', thread, '--ttl', '120', '--max-requests', '2'],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    record['bridgePid'] = proc.pid
    if select.select([proc.stdout], [], [], 5)[0]:
        line = proc.stdout.readline(16385)
        try:
            response = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            response = {}
        record['bridgeReady'] = response.get('ready') is True
        record['bridgeReason'] = response.get('error', {}).get('reason')
    else:
        record['bridgeReady'] = False
        record['bridgeReason'] = 'probe_readiness_timeout'
    record['bridgeExit'] = proc.poll()
    if not record['bridgeReady'] and proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=5)
    proc.stdout.close()
    fd = os.open(output / 'hook-result.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(record, handle)
    print('{}')


if __name__ == '__main__':
    main()
