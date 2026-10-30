"""Check the SDK floor and execute CI's real profile/audit shell boundaries."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests.docs.test_dependency_audit_workflow import named_step, run_script


ROOT = Path(__file__).resolve().parents[2]
CI = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
MCP = CI.split('\n  mcp:\n', 1)[1].split('\n  relay:\n', 1)[0]


class McpDependencyProfiles(unittest.TestCase):
    def test_floor_matrix_and_release_gate_preserve_supported_contract(self):
        manifest = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
        self.assertIn('requires-python = ">=3.9"', manifest)
        self.assertIn('mcp>=1.30,<2; python_version >= \'3.10\'', manifest)
        constraint = (ROOT / '.github/requirements/mcp-minimum.txt').read_text()
        self.assertEqual(['mcp==1.30.0'], [x for x in constraint.splitlines() if x and not x.startswith('#')])
        for text in ("os: [ubuntu-latest, macos-latest]", "python: ['3.10', '3.13', '3.14']",
                     'profile: [minimum, latest]', 'fail-fast: false'):
            self.assertIn(text, MCP)
        install = run_script(MCP, 'Install MCP runtime profile')
        self.assertIn('--constraint .github/requirements/mcp-minimum.txt', install)
        self.assertIn('--upgrade \'.[mcp]\'', install)
        self.assertNotIn('requirements/audit.txt', install)
        self.assertNotIn('requirements/build.txt', install)
        self.assertIn('tests/mcp_integration', named_step(MCP, 'MCP stdio, policy, timeout and owned-child cleanup'))
        upload = named_step(MCP, 'Retain MCP dependency and audit reports')
        self.assertIn('if: ${{ always() }}', upload)
        self.assertIn('matrix.profile', upload)
        self.assertIn('retention-days: 30', upload)
        self.assertNotIn('continue-on-error', MCP)
        gate = CI.split('\n  release-gate:\n', 1)[1]
        self.assertRegex(gate, r'needs: \[[^\]]*\bmcp\b')
        self.assertIn('needs.mcp.result', gate)
        # Keep existing latest full-extra audits, including release-time audits.
        for workflow in ('ci.yml', 'dependency-audit.yml', 'prepare-release.yml', 'publish.yml'):
            self.assertIn("install '.[relay,mcp]'", (ROOT / '.github/workflows' / workflow).read_text())

    @unittest.skipIf(os.name == 'nt', 'CI profile shell runs on POSIX')
    def test_install_branches_pin_only_minimum_and_propagate_failure(self):
        for profile in ('minimum', 'latest'):
            for failure in (0, 17):
                with self.subTest(profile=profile, failure=failure), tempfile.TemporaryDirectory(prefix='codex-mcp-install-') as folder:
                    root = Path(folder)
                    runtime = root / 'session-peer-mcp-runtime/bin'
                    runtime.mkdir(parents=True)
                    recorder = root / 'record.py'
                    recorder.write_text('import json, os, sys\n'
                                        'with open(os.environ["CALLS"], "a") as f: f.write(json.dumps(sys.argv[1:]) + "\\n")\n'
                                        'sys.exit(int(os.environ["INSTALL_FAILURE"]) if ".[mcp]" in sys.argv else 0)\n')
                    (runtime / 'python').write_text('#!/bin/sh\nexec "$FIXTURE_PYTHON" "$FIXTURE_RECORDER" "$@"\n')
                    (runtime / 'python').chmod(0o700)
                    result = subprocess.run(
                        ['bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c',
                         'python() { test "$1" = -m && test "$2" = venv; }\n' +
                         run_script(MCP, 'Install MCP runtime profile')],
                        cwd=root, env=dict(os.environ, RUNNER_TEMP=str(root), MCP_PROFILE=profile,
                                          FIXTURE_PYTHON=sys.executable, FIXTURE_RECORDER=str(recorder),
                                          CALLS=str(root / 'calls.jsonl'), INSTALL_FAILURE=str(failure)),
                        capture_output=True, text=True)
                    self.assertEqual(failure, result.returncode)
                    calls = [json.loads(x) for x in (root / 'calls.jsonl').read_text().splitlines()]
                    install = next(x for x in calls if '.[mcp]' in x)
                    self.assertEqual(profile == 'minimum', '--constraint' in install)
                    if profile == 'minimum':
                        self.assertEqual('.github/requirements/mcp-minimum.txt', install[install.index('--constraint') + 1])
                    else:
                        self.assertIn('--upgrade', install)
                    self.assertEqual(failure == 0, ['-m', 'pip', 'check'] in calls)

    @unittest.skipIf(os.name == 'nt', 'CI profile shell runs on POSIX')
    def test_record_step_rejects_wrong_minimum_missing_sdk_and_wrong_major(self):
        # Run the workflow's actual shell/code with only fixture distribution
        # metadata, not an installed SDK or a package/advisory network request.
        cases = [('minimum', '1.30.0', True), ('latest', '1.31.0', True),
                 ('minimum', '1.31.0', False), ('latest', '2.0.0', False),
                 ('minimum', None, False)]
        for profile, version, success in cases:
            with self.subTest(profile=profile, version=version), tempfile.TemporaryDirectory(prefix='codex-mcp-profile-') as folder:
                root = Path(folder)
                runtime = root / 'session-peer-mcp-runtime/bin'
                runtime.mkdir(parents=True)
                (root / 'mcp-reports').mkdir()
                constraints = root / '.github/requirements'
                constraints.mkdir(parents=True)
                (constraints / 'mcp-minimum.txt').write_text((ROOT / '.github/requirements/mcp-minimum.txt').read_text())
                (root / 'mcp.py').write_text('# metadata fixture only\n')
                if version:
                    info = root / ('mcp-' + version + '.dist-info')
                    info.mkdir()
                    (info / 'METADATA').write_text('Metadata-Version: 2.1\nName: mcp\nVersion: ' + version + '\n')
                # -S prevents a real installed SDK in the test interpreter's
                # site-packages from satisfying the missing-metadata control.
                (runtime / 'python').write_text(
                    '#!/bin/sh\nif test "$1" = -m; then printf "[]\\n"; exit 0; fi\n'
                    'exec "$FIXTURE_PYTHON" -S "$@"\n')
                (runtime / 'python').chmod(0o700)
                result = subprocess.run(
                    ['bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c',
                     run_script(MCP, 'Record and verify resolved MCP profile')],
                    cwd=root, env=dict(os.environ, RUNNER_TEMP=str(root),
                                      PYTHONPATH=str(root), MCP_PROFILE=profile,
                                      FIXTURE_PYTHON=sys.executable, PYTHONOPTIMIZE='1'),
                    capture_output=True, text=True)
                self.assertEqual(success, result.returncode == 0, 'Profile acceptance mismatch')
                if success:
                    record = json.loads((root / 'mcp-reports/profile.json').read_text())
                    self.assertEqual((profile, version), (record['profile'], record['mcp']))

    @unittest.skipIf(os.name == 'nt', 'CI audit shell runs on POSIX')
    def test_audit_findings_and_service_errors_keep_exit_and_reports(self):
        audit = named_step(MCP, 'Audit resolved MCP runtime graph')
        self.assertIn("steps.mcp_runtime.outcome == 'success'", audit)
        self.assertIn("steps.mcp_profile.outcome == 'success'", audit)
        self.assertIn('!cancelled()', audit)
        for status in (0, 1, 2):
            with self.subTest(status=status), tempfile.TemporaryDirectory(prefix='codex-mcp-audit-') as folder:
                root = Path(folder)
                runtime = root / 'session-peer-mcp-runtime/bin'
                runtime.mkdir(parents=True)
                (runtime / 'python').symlink_to(sys.executable)
                (root / 'mcp-reports').mkdir()
                stub = '''python() {
                  test "$1" = -m && test "$2" = pip_audit || return 99
                  while test "$#" -gt 0; do
                    if test "$1" = --output; then shift; printf '{}\\n' > "$1"; break; fi
                    shift
                  done
                  printf 'audit fixture diagnostic\\n' >&2
                  return "$AUDIT_STATUS"
                }
                '''
                result = subprocess.run(
                    ['bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c',
                     stub + run_script(MCP, 'Audit resolved MCP runtime graph')],
                    cwd=root, env=dict(os.environ, RUNNER_TEMP=str(root), AUDIT_STATUS=str(status)),
                    capture_output=True, text=True)
                self.assertEqual(status, result.returncode)
                reports = root / 'mcp-reports'
                self.assertEqual(str(status), (reports / 'audit-exit-status.txt').read_text().strip())
                self.assertEqual({}, json.loads((reports / 'audit.json').read_text()))
                self.assertIn('audit fixture diagnostic', (reports / 'audit.log').read_text())


if __name__ == '__main__':
    unittest.main()
