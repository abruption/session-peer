import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import session_peer as peer


@unittest.skipUnless(sys.platform in ('darwin', 'linux'), 'POSIX process groups')
class Descendants(unittest.TestCase):
    def test_term_resistant_descendant_dies_before_leader_is_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory)/'ready'
            script = '''import os,signal,sys,time
child = os.fork()
if child == 0:
 signal.signal(signal.SIGTERM, signal.SIG_IGN)
 open(sys.argv[1], 'w').write(str(os.getpid()))
 time.sleep(30)
else:
 time.sleep(30)
'''
            process = subprocess.Popen([sys.executable, '-c', script, str(ready)], start_new_session=True)
            try:
                deadline = time.monotonic()+5
                while not ready.exists() and time.monotonic()<deadline: time.sleep(.01)
                self.assertTrue(ready.exists())
                child = int(ready.read_text())
                start = time.monotonic()
                peer.stop_codex_wake(process)
                self.assertLess(time.monotonic()-start, 4)
                for _ in range(100):
                    status = subprocess.run(['ps', '-o', 'stat=', '-p', str(child)], capture_output=True, text=True).stdout.strip()
                    if not status or status.startswith('Z'): break
                    time.sleep(.01)
                self.assertTrue(not status or status.startswith('Z'), status)
                with patch.object(peer.os, 'killpg') as kill:
                    peer.stop_codex_wake(process)
                    kill.assert_not_called()
            finally:
                if process.returncode is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
