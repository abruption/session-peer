"""Run inside the same transient unit before opening a public listener."""
import json
import os

assert os.geteuid() != 0
checked = []
for path in ('/home/ubuntu', '/root', '/opt', '/srv', '/var/lib', '/etc/ssh'):
    try:
        os.listdir(path)
    except (PermissionError, FileNotFoundError):
        checked.append(path)
    else:
        raise RuntimeError('Sandbox permitted a forbidden directory')
print(json.dumps({'sandbox': 'passed', 'forbiddenDirectories': checked}), flush=True)
