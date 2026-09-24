#!/usr/bin/env python3
"""session-peer — message Claude Code and Codex sessions locally or over SSH.

Claude uses its native inbox socket/pipe; Codex uses its queue CLI. SSH runs the
same standard-library-only script on the destination, without a remote install.
Successful submission is not evidence of consumption or acknowledgement.
"""

# Generated into session_peer.py by tools/generate_session_peer.py. Edit the
# canonical segments in session_peer_core/, then regenerate the standalone file.

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
from datetime import datetime, timezone
import errno
import getpass
from importlib import metadata
import json
import os
import re
import selectors
import signal
import shlex
import socket
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NamedTuple, TypedDict

try:
    import fcntl
except ImportError:  # Native Windows uses its own read-only writer inspection.
    fcntl = None

__version__ = "1.0.0"
GITHUB_REPO = "abruption/session-peer"

# Claude Code refuses a same-machine message once its serialized form passes
# about a million characters, so fail here rather than at the far end.
MAX_MESSAGE_CHARS = 1_000_000

# Over SSH the message travels as a command-line argument, so it meets Linux's
# MAX_ARG_STRLEN (128 KB per argument) long before the cap above. base64 costs
# 4/3, and the rest of the command needs room, so keep well under it.
MAX_REMOTE_MESSAGE_CHARS = 90_000
CONNECT_TIMEOUT = 10.0
DRAIN_TIMEOUT = 2.0
DETECT_TIMEOUT = 3.0
CODEX_QUEUE_TIMEOUT = 30.0
MAX_CODEX_MESSAGE_BYTES = 32 * 1024
CODEX_HOME_STABILITY_SECONDS = 0.25
UPDATE_CACHE_SCHEMA_VERSION = 1
UPDATE_CACHE_TTL_SECONDS = 24 * 60 * 60
UPDATE_REFRESH_LOCK_SECONDS = 5 * 60
UPDATE_CACHE_MAX_BYTES = 4096
UPDATE_NOTICE_ENV = "SESSION_PEER_NO_UPDATE_NOTICE"
UPDATE_REFRESH_ARG = "--_refresh-update-cache"
REPLY_ADDRESS_SCHEME = "session-peer"
REPLY_ADDRESS_VERSION = "v1"
MAX_REPLY_ADDRESS_CHARS = 4096

# Tailscale hands out addresses from the CGNAT range, 100.64.0.0/10. Matching on
# "100." alone would also catch ordinary public addresses like 100.200.x.x.
TAILNET_SECOND_OCTET = range(64, 128)

EXIT_ERROR = 1
EXIT_NO_TARGET = 2

_CLIENT_UPDATE_NOTICE: dict | None = None
_IDENTITY_UNSET = object()


class CcPeerError(Exception):
    """Anything the user should see as a one-line failure."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


class NoTargetError(CcPeerError):
    """A requested saved session cannot be resolved."""
