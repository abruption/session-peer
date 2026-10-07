"""Execute documented release examples against synthetic shell commands only."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
COMMIT = "a" * 40


class ReleaseCommands(unittest.TestCase):
    def shell_calls(self, block):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "calls.jsonl"
            staging = str(Path(temporary) / "staging with spaces")
            # Functions intercept every external command in all three examples.
            # A minimal environment supplies neither credentials nor user shell startup files.
            harness = r'''
set -eu
capture() {
  "$FIXTURE_PYTHON" -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FIXTURE_LOG"
}
git() {
  capture git "$@"
  if [ "$1" = rev-parse ]; then printf '%s\n' "$FIXTURE_COMMIT"; fi
}
gh() {
  capture gh "$@"
  if [ "$1" = api ]; then
    case "$2" in
      */releases/latest) printf '%s\n' v1.2.3 ;;
      */git/ref/tags/v1.2.3) printf '%s\n' "$FIXTURE_COMMIT" ;;
      *) return 1 ;;
    esac
  fi
}
curl() { capture curl "$@"; }
mktemp() { capture mktemp "$@"; printf '%s\n' "$FIXTURE_STAGING"; }
sh() { capture sh "$@"; }
rm() { capture rm "$@"; }
rmdir() { capture rmdir "$@"; }
'''
            env = {"PATH": os.defpath, "FIXTURE_PYTHON": sys.executable,
                   "FIXTURE_LOG": str(log), "FIXTURE_STAGING": staging,
                   "FIXTURE_COMMIT": COMMIT}
            done = subprocess.run(["/bin/bash", "--noprofile", "--norc"],
                                  input=harness + block, cwd=temporary, env=env,
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            return calls, staging

    def test_release_preparation_commands_preserve_argument_boundaries(self):
        for name in ("RELEASING.md", "RELEASING.ko.md", "RELEASING.ja.md", "RELEASING.zh-CN.md"):
            with self.subTest(document=name):
                blocks = re.findall(r"```bash\n(.*?)```", (ROOT / name).read_text(), re.DOTALL)
                self.assertEqual(len(blocks), 3, "preparation, owner publication and installer authentication remain distinct")
                calls, _ = self.shell_calls(blocks[0])
                self.assertEqual(calls, [
                    ["git", "fetch", "origin", "main", "--tags"],
                    ["git", "rev-parse", "origin/main"],
                    ["git", "tag", "v1.0.4", COMMIT],
                    ["git", "push", "origin", "v1.0.4"],
                    ["gh", "release", "create", "v1.0.4", "--repo", "abruption/session-peer",
                     "--target", COMMIT, "--title", "session-peer v1.0.4",
                     "--notes-file", "docs/releases/v1.0.4.md", "--draft", "--latest"],
                    ["gh", "workflow", "run", "prepare-release.yml", "--repo", "abruption/session-peer",
                     "--ref", "main", "-f", "tag=v1.0.4"],
                ])
                publication_calls, _ = self.shell_calls(blocks[1])
                self.assertEqual(publication_calls, [
                    ["gh", "release", "edit", "v1.0.4", "--repo", "abruption/session-peer",
                     "--draft=false", "--prerelease=false", "--latest"],
                ])

    def test_installer_authentication_commands_preserve_argument_boundaries(self):
        query = ('if .immutable == true and .draft == false and .prerelease == false '
                 'then .tag_name else error("no immutable stable release") end')
        for name in ("RELEASING.md", "RELEASING.ko.md", "RELEASING.ja.md", "RELEASING.zh-CN.md"):
            with self.subTest(document=name):
                block = re.findall(r"```bash\n(.*?)```", (ROOT / name).read_text(), re.DOTALL)[2]
                calls, staging = self.shell_calls(block)
                installer = staging + "/install.sh"
                self.assertEqual(calls, [
                    ["gh", "api", "repos/abruption/session-peer/releases/latest", "--jq", query],
                    ["gh", "api", "repos/abruption/session-peer/git/ref/tags/v1.2.3", "--jq",
                     '.object | select(.type == "commit") | .sha'],
                    ["mktemp", "-d"],
                    ["curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
                     "--max-filesize", "262144", "--max-time", "30",
                     "https://github.com/abruption/session-peer/releases/download/v1.2.3/install.sh",
                     "-o", installer],
                    ["gh", "attestation", "verify", installer, "--repo", "abruption/session-peer",
                     "--signer-workflow", "abruption/session-peer/.github/workflows/prepare-release.yml",
                     "--source-ref", "refs/heads/main", "--source-digest", COMMIT,
                     "--cert-oidc-issuer", "https://token.actions.githubusercontent.com",
                     "--deny-self-hosted-runners", "--format", "json"],
                    ["sh", installer], ["rm", "-f", installer], ["rmdir", staging],
                ])


if __name__ == "__main__":
    unittest.main()
