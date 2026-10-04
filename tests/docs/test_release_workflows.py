"""Structural contracts for release-critical GitHub Actions workflows."""

from pathlib import Path
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest
import venv


ROOT = Path(__file__).resolve().parents[2]
ACTION_REF = re.compile(r"^\s*- uses: [^@\s]+@([^\s#]+)", re.MULTILINE)
FULL_SHA = re.compile(r"[0-9a-f]{40}")
JOB = re.compile(r"^  ([a-z][a-z0-9-]*):\s*$", re.MULTILINE)


class ReleaseWorkflows(unittest.TestCase):
    def installed_runtime_checks(self, name):
        text = (ROOT / ".github/workflows" / name).read_text()
        return re.findall(
            r'^\s*(test "\$\((/tmp/[^\s]+/bin/python) ([^\n]+)\)" = "\$RELEASE_VERSION")$',
            text, re.MULTILINE)

    def test_release_install_probes_use_isolated_virtualenv_imports_and_exact_cli_versions(self):
        probes = set()
        for name, expected in (("prepare-release.yml", 2), ("publish.yml", 4)):
            text = (ROOT / ".github/workflows" / name).read_text()
            checks = self.installed_runtime_checks(name)
            self.assertEqual(len(checks), expected, name)
            for _, python, arguments in checks:
                tokens = shlex.split(arguments)
                self.assertEqual(tokens[:2], ["-I", "-c"], name)
                probes.add(tokens[2])
                cli = python.removesuffix("python") + "session-peer"
                self.assertIn(f'test "$({cli} --version)" = "session-peer $RELEASE_VERSION"', text, name)
        self.assertEqual(len(probes), 1, "all six release checks must verify the same import contract")
        for name, expected in (("ci.yml", 1), ("prepare-release.yml", 3), ("publish.yml", 5)):
            text = (ROOT / ".github/workflows" / name).read_text()
            probes = re.findall(r"/tmp/[^\s]+/bin/python ([^\n]+)", text)
            self.assertEqual(len(probes), expected, name)
            for arguments in probes:
                self.assertTrue(arguments.startswith("-I -c "), (name, arguments))

    @unittest.skipIf(os.name == "nt", "release checks use POSIX shell")
    def test_release_install_checks_reject_real_virtualenv_shadowing_from_checkout(self):
        with tempfile.TemporaryDirectory(prefix="release-installed-import-") as temporary:
            root = Path(temporary)
            environment = root / "venv"
            # This is an import-origin fixture, not a fresh pip/artifact installation.
            venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
            python = str(environment / "bin/python")
            installed_directory = Path(subprocess.run(
                [python, "-I", "-c", 'import sysconfig; print(sysconfig.get_path("purelib"))'],
                cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip())
            installed = installed_directory / "session_peer.py"
            version = re.search(r'^__version__ = "([^"]+)"$',
                                (ROOT / "session_peer.py").read_text(), re.MULTILINE).group(1)
            installed.write_text('__version__ = "0.0.0"\n')
            env = {**os.environ, "RELEASE_VERSION": version, "PYTHONPATH": str(ROOT)}
            old = subprocess.run(
                [python, "-c", 'import session_peer; print(session_peer.__version__); print(session_peer.__file__)'],
                cwd=ROOT, env=env, check=True, capture_output=True, text=True)
            self.assertEqual(old.stdout.splitlines(), [version, str(ROOT / "session_peer.py")])
            checks = [check for name in ("prepare-release.yml", "publish.yml")
                      for check in self.installed_runtime_checks(name)]
            self.assertEqual(len(checks), 6)
            command, original_python, arguments = checks[0]
            old_command = command.replace(arguments, "-c 'import session_peer; print(session_peer.__version__)'", 1)
            old_check = subprocess.run(
                ["sh", "-c", old_command.replace(original_python, shlex.quote(python), 1)],
                cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(old_check.returncode, 0, old_check.stderr)
            for mode in ("wrong-version", "installed-version", "outside-site-packages"):
                if mode == "installed-version":
                    installed.write_text(f'__version__ = {version!r}\n# matching installed module\n')
                elif mode == "outside-site-packages":
                    installed.write_text(f'__version__ = {version!r}\n__file__ = {str(ROOT / "session_peer.py")!r}\n')
                for command, original_python, _ in checks:
                    with self.subTest(mode=mode, python=original_python):
                        done = subprocess.run(
                            ["sh", "-c", command.replace(original_python, shlex.quote(python), 1)],
                            cwd=ROOT, env=env, capture_output=True, text=True)
                        self.assertEqual(done.returncode == 0, mode == "installed-version", done.stderr)

    def test_core_matrix_installs_only_the_pinned_source_test_dependency(self):
        requirements = ROOT / ".github/requirements"
        declared = [line for line in (requirements / "test.txt").read_text().splitlines()
                    if line and not line.startswith("#")]
        build_pin = re.findall(r"^packaging==[^\s]+$", (requirements / "build.txt").read_text(), re.MULTILINE)
        self.assertEqual(len(build_pin), 1)
        self.assertEqual(declared, build_pin, "test packaging pin must track the release build verifier")
        text = (ROOT / ".github/workflows/ci.yml").read_text()
        matrix = text.split("\n  test:\n", 1)[1].split("\n  docs:\n", 1)[0]
        install = "run: python -m pip install --requirement .github/requirements/test.txt"
        self.assertIn(install, matrix)
        self.assertNotIn("--requirement .github/requirements/build.txt", matrix)
        self.assertLess(matrix.index(install), matrix.index("- name: Distribution source tests"))
        self.assertLess(matrix.index(install), matrix.index("- name: Complete default discovery contract"))

    def test_every_release_checkout_uses_the_immutable_event_commit(self):
        for name, count in (("prepare-release.yml", 4), ("publish.yml", 6)):
            text = (ROOT / ".github/workflows" / name).read_text()
            checkouts = re.findall(
                r"^      - uses: actions/checkout@[^\n]+\n"
                r"        with:\n((?:^          [^\n]+\n)+)", text, re.MULTILINE)
            self.assertEqual(len(checkouts), count, name)
            for checkout in checkouts:
                self.assertIn("          ref: ${{ github.sha }}\n", checkout, name)
            # Trusted code must still bind the named tag and main ancestry to that SHA.
            build = text.split("\n  test-wheel:", 1)[0]
            self.assertIn("RELEASE_SHA: ${{ github.sha }}", build)
            self.assertIn('--expected-sha "$RELEASE_SHA"', build)
            self.assertIn("release_artifacts.py verify-source", build)

    def test_every_third_party_action_is_commit_pinned(self):
        for relative in (".github/workflows/ci.yml", ".github/workflows/publish.yml", ".github/workflows/prepare-release.yml"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            refs = ACTION_REF.findall(text)
            self.assertTrue(refs, relative)
            for ref in refs:
                self.assertIsNotNone(
                    FULL_SHA.fullmatch(ref), f"{relative}: unpinned action ref {ref}"
                )

    def test_assets_are_attested_on_main_and_attached_before_publication(self):
        prepare = (ROOT / ".github/workflows/prepare-release.yml").read_text()
        publish = (ROOT / ".github/workflows/publish.yml").read_text()
        self.assertIn("workflow_dispatch:", prepare)
        self.assertIn('"$GITHUB_REF" != refs/heads/main', prepare)
        self.assertIn('"$GITHUB_ACTOR" != "$GITHUB_REPOSITORY_OWNER"', prepare)
        self.assertIn("group: prepare-release-${{ inputs.tag }}", prepare)
        self.assertIn("cancel-in-progress: false", prepare)
        self.assertIn("--expected-sha", prepare)
        self.assertIn("subject-path: 'dist/*'", prepare)
        self.assertIn("release.get('isDraft') is True", prepare)
        self.assertIn("release.get('assets') == []", prepare)
        self.assertIn('gh release view "$RELEASE_TAG"', prepare)
        self.assertIn("--json isDraft,isPrerelease,tagName,targetCommitish,assets", prepare)
        self.assertNotIn('gh api "repos/$GITHUB_REPOSITORY/releases/tags/$RELEASE_TAG"', prepare)
        self.assertIn('gh release upload "$RELEASE_TAG" dist/*', prepare)
        self.assertNotIn("--draft=false", prepare)
        self.assertNotIn("    if: ${{ github.repository", publish)
        self.assertIn("Require owner publication (fail rather than silently skip)", publish)
        self.assertIn("exit 1", publish.split("  test-wheel:")[0])
        self.assertIn("download_release.py", publish)
        self.assertNotIn("python -m build", publish)
        self.assertNotIn("gh release upload", publish)

    def test_both_prepare_and_publication_keep_dependency_audit_gates(self):
        for name, consumer in (("prepare-release.yml", "attach-draft"), ("publish.yml", "publish")):
            text = (ROOT / ".github/workflows" / name).read_text()
            self.assertIn("python -m pip_audit --path", text)
            self.assertIn("npm audit --omit=dev", text)
            block = re.split(r"\n  [a-z][a-z0-9-]*:\n", text.split("\n  " + consumer + ":", 1)[1], maxsplit=1)[0]
            self.assertIn("dependency-audit", block)

    def test_draft_guard_requires_view_metadata_empty_assets_and_exact_sha(self):
        text = (ROOT / ".github/workflows/prepare-release.yml").read_text()
        code = textwrap.dedent(text.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0])
        base = {"isDraft": True, "isPrerelease": False, "tagName": "v1.2.3",
                "targetCommitish": "a" * 40, "assets": []}
        cases = [({}, True), ({"isPrerelease": True}, True), ({"isDraft": False}, False),
                 ({"tagName": "v1.2.4"}, False), ({"targetCommitish": "main"}, False),
                 ({"targetCommitish": "b" * 40}, False), ({"assets": [{}]}, False), ({"assets": None}, False)]
        for change, success in cases:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                (Path(temporary) / "draft.json").write_text(json.dumps({**base, **change}))
                env = {**os.environ, "RELEASE_TAG": "v1.2.3", "GITHUB_SHA": "a" * 40}
                # Security validation must remain active even with assertions disabled.
                done = subprocess.run([sys.executable, "-O", "-c", code], cwd=temporary,
                                      env=env, capture_output=True, text=True)
                self.assertEqual(done.returncode == 0, success, done.stderr)

    def test_release_gate_needs_every_other_ci_job(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        jobs = set(JOB.findall(text.split("\njobs:\n", 1)[1]))
        match = re.search(r"^  release-gate:\n(?:^    .*\n)*?^    needs: \[([^]]+)\]$", text, re.MULTILINE)
        self.assertIsNotNone(match, "release-gate must use a reviewable inline needs list")
        dependencies = {item.strip() for item in match.group(1).split(",")}
        self.assertEqual(dependencies, jobs - {"release-gate"})
        self.assertIn("    name: release gate\n", text)
        self.assertIn("    if: ${{ always() }}\n", text)


if __name__ == "__main__":
    unittest.main()
