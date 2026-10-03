#!/usr/bin/env python3
"""Synthetic Codex executable for real session-peer --wake cleanup fixtures."""
import json
import os
from pathlib import Path
import signal
import sys
import time


if sys.argv[1:] == ['--version']:
    print('codex-cli 0.154.0')
elif sys.argv[1] == 'queue':
    root = Path(os.environ['CODEX_HOME'])
    with (root / 'queue-submissions').open('a') as stream:
        stream.write('queued\n')
    thread = sys.argv[sys.argv.index('--thread') + 1]
    print(f'Queued message fixture-queue for thread {thread}.')
elif sys.argv[1:] == ['app-server']:
    root = Path(os.environ['CODEX_HOME'])
    mode = os.environ['WAKE_TEST_MODE']
    if mode == 'resistant':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    for line in sys.stdin:
        value = json.loads(line)
        if value.get('method') == 'initialize':
            print(json.dumps({'id': 1, 'result': {}}), flush=True)
        elif value.get('method') == 'thread/resume':
            thread = value['params']['threadId']
            print(json.dumps({'id': 2, 'result': {'thread': {'id': thread}}}), flush=True)
            ready = root / 'app-server-ready'
            pending = root / 'app-server-ready.tmp'
            pending.write_text(str(os.getpid()))
            pending.replace(ready)
            if mode == 'complete':
                print(json.dumps({'method': 'turn/completed', 'params': {
                    'threadId': thread, 'turn': {'status': 'completed'}}}), flush=True)
            else:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and not (root / 'fixture-stop').exists():
                    time.sleep(.01)
else:
    raise SystemExit('unexpected fixture arguments')
