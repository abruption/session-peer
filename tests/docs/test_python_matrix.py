"""Keep interpreter/profile coverage and installed-artifact probes release-gated."""

from itertools import product
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import venv

from tests.docs.test_dependency_audit_workflow import run_script


ROOT = Path(__file__).resolve().parents[2]
CI = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')


def job(name):
    start = re.search(r'^  ' + re.escape(name) + r':\n', CI, re.M)
    if start is None:
        raise AssertionError('Missing CI job: ' + name)
    remainder = CI[start.end():]
    next_job = re.search(r'^  [a-z][a-z0-9-]*:\n', remainder, re.M)
    return remainder[:next_job.start()] if next_job else remainder


def cells(name):
    # This is the small matrix subset used by this workflow, not a YAML parser.
    # Accept only simple literal scalar data, never evaluate YAML expressions.
    text = job(name).split('    steps:\n', 1)[0]
    axes = []
    for key, values in re.findall(r'^        ([a-z]+): (\[[^\n]+\])$', text, re.M):
        scalars = []
        for value in values[1:-1].split(','):
            value = value.strip()
            if not re.fullmatch(r"(?:'[A-Za-z0-9_.-]+'|\"[A-Za-z0-9_.-]+\"|[A-Za-z0-9_.-]+)", value):
                raise AssertionError('Unsupported matrix literal')
            scalars.append(value.strip("'\""))
        axes.append((key, scalars))
    result = {tuple(zip((key for key, _ in axes), values))
              for values in product(*(values for _, values in axes))} if axes else set()
    includes = re.findall(r'^          - os: ([^\n]+)\n            python: \'([^\']+)\'$', text, re.M)
    result.update((('os', os_name), ('python', python)) for os_name, python in includes)
    return [dict(cell) for cell in result]


class PythonMatrix(unittest.TestCase):
    def test_core_floors_new_posix_interpreter_and_windows_are_retained(self):
        actual = {(x['os'], x['python']) for x in cells('test')}
        expected = set(product(('ubuntu-latest', 'macos-latest'), ('3.9', '3.13', '3.14')))
        expected.add(('windows-latest', '3.13'))
        self.assertEqual(expected, actual)
        for suite in ('core', 'adapters', 'codex', 'distribution'):
            self.assertIn('unittest discover -s tests/' + suite, job('test'))
        self.assertIn('tools/generate_session_peer.py --check', job('test'))

    def test_optional_profiles_keep_their_minimums_and_all_release_gates(self):
        mcp = {(x['os'], x['python'], x['profile']) for x in cells('mcp')}
        self.assertEqual(set(product(('ubuntu-latest', 'macos-latest'),
                                     ('3.10', '3.13', '3.14'), ('minimum', 'latest'))), mcp)
        relay = {(x['os'], x['python']) for x in cells('relay')}
        self.assertEqual(set(product(('ubuntu-latest', 'macos-latest'), ('3.11', '3.13', '3.14'))), relay)
        self.assertIn('--constraint .github/requirements/mcp-minimum.txt', job('mcp'))
        self.assertIn('Audit resolved MCP runtime graph', job('mcp'))
        self.assertIn('unittest discover -s tests/mcp_integration', job('mcp'))
        self.assertIn('unittest discover -s tests/relay', job('relay'))
        gate = job('release-gate')
        for name in ('test', 'package', 'mcp', 'relay'):
            self.assertRegex(gate, r'needs: \[[^\]]*\b' + name + r'\b')
            self.assertIn('needs.' + name + '.result', gate)
        for name in ('test', 'package', 'mcp', 'relay'):
            self.assertIn('fail-fast: false', job(name))
            self.assertNotIn('continue-on-error', job(name))

    def test_package_cells_build_and_install_both_artifacts_on_314(self):
        self.assertEqual({('ubuntu-latest', '3.13'), ('ubuntu-latest', '3.14'), ('macos-latest', '3.14')},
                         {(x['os'], x['python']) for x in cells('package')})
        package = job('package')
        self.assertIn('python-version: ${{ matrix.python }}', package)
        self.assertIn('tools/generate_session_peer.py --check', package)
        self.assertIn('python -m build', package)
        self.assertIn('SESSION_PEER_DIST_DIR: dist', package)
        script = run_script(package, 'Install wheel and sdist independently')
        self.assertIn('for kind in wheel sdist', script)
        self.assertIn('"$RUNNER_TEMP/session-peer-package-$kind"', script)
        for marker in ('pip install dist/*.whl', 'pip install dist/*.tar.gz', '--help', 'pip check'):
            self.assertIn(marker, script)

    @unittest.skipIf(os.name == 'nt', 'package cells use POSIX shell')
    def test_actual_package_version_probe_rejects_checkout_shadowing(self):
        script = run_script(job('package'), 'Install wheel and sdist independently')
        probe = next(line for line in script.splitlines() if '-I -c ' in line)
        expected = re.search(r'^__version__ = "([^"]+)"$',
                             (ROOT / 'session_peer.py').read_text(), re.M).group(1)
        with tempfile.TemporaryDirectory(prefix='codex-python-package-') as directory:
            env_dir = Path(directory) / 'venv'
            venv.EnvBuilder(with_pip=False, symlinks=True).create(env_dir)
            python = str(env_dir / 'bin/python')
            purelib = Path(subprocess.check_output(
                [python, '-I', '-c', 'import sysconfig; print(sysconfig.get_path("purelib"))'],
                text=True).strip())
            installed = purelib / 'session_peer.py'
            for index, mode in enumerate(('wrong-version', 'installed-version', 'outside-purelib')):
                with self.subTest(mode=mode):
                    version = expected if mode != 'wrong-version' else '0.0.0'
                    installed.write_text('__version__ = ' + repr(version) + '\n' +
                                         ('__file__ = ' + repr(str(ROOT / 'session_peer.py')) + '\n'
                                          if mode == 'outside-purelib' else ''))
                    # Equal-sized fixture versions written within one second
                    # must not reuse the preceding subprocess's timestamp pyc.
                    stamp = 1690000000 + index * 2
                    os.utime(installed, (stamp, stamp))
                    result = subprocess.run(
                        ['bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', probe],
                        cwd=ROOT, env=dict(os.environ, venv=str(env_dir), expected=expected,
                                          PYTHONPATH=str(ROOT)), capture_output=True, text=True)
                    self.assertEqual(mode == 'installed-version', result.returncode == 0,
                                     'Package import/version boundary mismatch')


if __name__ == '__main__':
    unittest.main()
