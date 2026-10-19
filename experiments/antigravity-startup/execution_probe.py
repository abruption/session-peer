"""Body-free owned-native execution observations and receiver-side bridge setup."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
import uuid

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--scratch', required=True)
    p.add_argument('--runtime', required=True)
    p.add_argument('--event', choices=['SessionStart', 'PreInvocation', 'PostInvocation', 'Stop'])
    p.add_argument('--start-bridge', action='store_true')
    a = p.parse_args()
    scratch = Path(a.scratch)
    if scratch.stat().st_uid != os.getuid() or scratch.stat().st_mode & 0o077:
        raise ValueError('private scratch required')
    spec = importlib.util.spec_from_file_location('tested_runtime', a.runtime)
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)
    if a.start_bridge:
        thread = str(uuid.UUID(os.environ['ANTIGRAVITY_CONVERSATION_ID']))
    else:
        payload = sys.stdin.buffer.read(65537)
        if len(payload) > 65536:
            raise ValueError('hook payload too large')
        thread = str(uuid.UUID(json.loads(payload)['conversationId']))
    home = Path('~/.gemini/antigravity-cli').expanduser().resolve()
    # Do not weaken production ownership/presence checks or import credentials.
    try:
        owner = rt.agy_owner(home, thread)
        owner_verified = True
    except Exception:
        if a.start_bridge:
            raise
        # Observation must survive a cross-conversation owner mismatch. Only
        # the bridge setup requires successful native owner validation.
        owner = {'pid': None, 'start': None}
        owner_verified = False
    record = {'event': a.event or 'BridgeSetup', 'pid': os.getpid(),
              'ppid': os.getppid(), 'ownerPid': owner['pid'],
              'ownerStart': owner['start'], 'ownerVerified': owner_verified,
              'conversationId': thread,
              'monotonic': time.monotonic(), 'utcSeconds': time.time()}
    fd = os.open(scratch / 'execution-events.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a') as out:
        out.write(json.dumps(record) + '\n')
    if a.start_bridge:
        bridge = subprocess.Popen([sys.executable, a.runtime, 'antigravity-bridge',
            'serve', '--thread', thread, '--ttl', '600', '--max-requests', '2'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True)
        ready = {}
        if select.select([bridge.stdout], [], [], 8)[0]:
            line = bridge.stdout.readline(16385)
            try:
                ready = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                pass
        bridge.stdout.close()
        if ready.get('ready') is not True:
            if bridge.poll() is None:
                bridge.terminate()
                bridge.wait(timeout=5)
            raise RuntimeError('bridge readiness not established')
        record.update({'ready': True, 'bridgePid': bridge.pid,
            'generation': ready['generation'], 'antigravityHome': str(home),
            'eventsPath': str(scratch / 'execution-events.jsonl')})
        fd = os.open(scratch / 'bridge-manifest.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(record, out)
        print('Receiver bridge ready. No message has been sent by this setup.')
    else:
        print('{}')

if __name__ == '__main__':
    main()
