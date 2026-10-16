"""Owned-session-only native diagnostic; raw native output never leaves memory."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--scratch', required=True)
    p.add_argument('--runtime', required=True)
    p.add_argument('--thread')
    p.add_argument('--phase', choices=['hook', 'tool'], default='hook')
    a = p.parse_args()
    scratch = Path(a.scratch)
    if scratch.stat().st_uid != os.getuid() or scratch.stat().st_mode & 0o077:
        raise ValueError('private scratch required')
    if a.phase == 'tool' and not a.thread:
        thread = str(uuid.UUID(os.environ['ANTIGRAVITY_CONVERSATION_ID']))
    elif a.thread:
        thread = str(uuid.UUID(a.thread))
    else:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError('hook input too large')
        thread = str(uuid.UUID(json.loads(raw)['conversationId']))
    spec = importlib.util.spec_from_file_location('tested_runtime', a.runtime)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    # Production ancestor, UID, presence, and start-time checks are not weakened.
    owner = runtime.agy_owner(Path('~/.gemini/antigravity-cli').expanduser(), thread)
    result = {'phase': a.phase, 'conversationId': thread, 'ownerPid': owner['pid'],
              'ownerValidated': True, 'observedMonotonic': time.monotonic(),
              'contextPresent': {name: name in os.environ for name in (
                  'ANTIGRAVITY_LS_ADDRESS', 'ANTIGRAVITY_CSRF_TOKEN',
                  'ANTIGRAVITY_CONVERSATION_ID', 'ANTIGRAVITY_TRAJECTORY_ID')}}
    token = 'ACK AGY307-PINNED-' + a.phase.upper()
    argv = [str(scratch / 'agy'), 'agentapi', 'send-message',
            '--title=session-peer-isolated-probe', '--', thread,
            'User-authorized isolated native delivery test. Reply exactly ' + token
            + '. Do not use tools or edit files.']
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=15)
        result['nativeExit'] = done.returncode
        result['timedOut'] = False
        combined = done.stdout + b'\n' + done.stderr
        # Persist fixed classes only, never diagnostics or credential values.
        result['knownDiagnostic'] = next((label for literal, label in (
            (b'ANTIGRAVITY_LS_ADDRESS is not set', 'ls_address_not_set'),
            (b'a tool context is required to send a message', 'tool_context_required'),
            (b'invalid agentapi principal', 'invalid_agentapi_principal'),
            (b'ANTIGRAVITY_LS_ADDRESS', 'ls_address_diagnostic'),
            (b'ANTIGRAVITY_CSRF_TOKEN', 'csrf_diagnostic'),
            (b'connection refused', 'connection_refused'),
        ) if literal in combined), 'none_matched')
    except subprocess.TimeoutExpired:
        result['nativeExit'] = None
        result['timedOut'] = True
        result['knownDiagnostic'] = 'not_classified'
    fd = os.open(scratch / (a.phase + '-result.json'),
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(result, handle)
    print('{}' if a.phase == 'hook' else 'Owned native probe completed; diagnostics retained privately.')

if __name__ == '__main__':
    main()
