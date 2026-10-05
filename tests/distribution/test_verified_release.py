"""Isolated hostile release fixtures; no public downloads or credentials."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import session_peer


ROOT = Path(__file__).resolve().parents[2]


class VerifiedRelease(unittest.TestCase):
    tag = "v9.8.7"
    commit = "a" * 40

    def fixture(self, root, *, runtime=None):
        version = session_peer.release_tag_version(self.tag, allow_prerelease=True)
        if runtime is None:
            runtime = (f'__version__ = "{version}"\n'
                       'print("session-peer " + __version__)\n').encode()
        payloads = {"session_peer.py": runtime, "install.sh": b"#!/bin/sh\n", "SKILL.md": b"skill\n",
                    f"session_peer-{version}-py3-none-any.whl": b"wheel", f"session_peer-{version}.tar.gz": b"sdist"}
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
        payloads["SHA256SUMS"] = "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())).encode()
        payloads["release-provenance.json"] = json.dumps({
            "repository": session_peer.RELEASE_REPOSITORY, "commit": self.commit, "tag": self.tag,
            "version": version, "workflow_ref": session_peer.RELEASE_BUILDER + "@refs/heads/main",
            "artifacts": [{"filename": name, "sha256": digest} for name, digest in sorted(hashes.items())]
        }).encode()
        prefix = "https://github.com/abruption/session-peer/releases/download/" + self.tag + "/"
        release = {"tag_name": self.tag, "immutable": True, "draft": False, "prerelease": False,
                   "assets": [{"name": name, "size": len(data), "browser_download_url": prefix + name}
                              for name, data in payloads.items()]}
        urls = {prefix + name: data for name, data in payloads.items()}
        urls["https://api.github.com/repos/abruption/session-peer/releases/latest"] = json.dumps(release).encode()
        urls["https://api.github.com/repos/abruption/session-peer/git/ref/tags/" + self.tag] = json.dumps(
            {"object": {"type": "commit", "sha": self.commit}}).encode()
        return urls, release, payloads

    def open_fixture(self, urls):
        def open_(request, **kwargs):
            stream = io.BytesIO(urls[request.full_url])
            stream.headers = {}
            return stream
        return open_

    def test_verified_success_and_exact_attestation_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            urls, _, _ = self.fixture(root)
            with mock.patch.object(session_peer.urllib.request, "urlopen", side_effect=self.open_fixture(urls)), \
                    mock.patch.object(session_peer.shutil, "which", return_value="gh"), \
                    mock.patch.object(session_peer, "release_validate_runtime") as runtime, \
                    mock.patch.object(session_peer.subprocess, "run", return_value=subprocess.CompletedProcess(
                        [], 0, stdout='[{}]', stderr='')) as run:
                self.assertEqual(session_peer.verified_release_download(root, tag=self.tag), "9.8.7")
                self.assertEqual(run.call_count, 3)
                for call, name in zip(run.call_args_list, ("SHA256SUMS", "release-provenance.json", "session_peer.py")):
                    self.assertEqual(call.args[0], [
                        "gh", "attestation", "verify", str(root / name), "--repo", "abruption/session-peer",
                        "--signer-workflow", "abruption/session-peer/.github/workflows/prepare-release.yml",
                        "--source-ref", "refs/heads/main", "--source-digest", self.commit,
                        "--cert-oidc-issuer", "https://token.actions.githubusercontent.com",
                        "--deny-self-hosted-runners", "--format", "json"])
                    self.assertEqual(call.kwargs, {"capture_output": True, "text": True, "timeout": 120})
                runtime.assert_called_once_with(root / "session_peer.py", "9.8.7")
            session_peer.release_validate_runtime(root / "session_peer.py", "9.8.7")

    def test_publication_uses_event_release_even_when_it_is_not_latest(self):
        for tag, prerelease in (("v9.8.7", False), ("v9.8.7-rc.1", True)):
            with self.subTest(tag=tag), tempfile.TemporaryDirectory() as temporary, mock.patch.object(self, "tag", tag):
                root = Path(temporary)
                urls, release, _ = self.fixture(root)
                release["prerelease"] = prerelease
                urls.pop("https://api.github.com/repos/abruption/session-peer/releases/latest")
                urls["https://api.github.com/repos/abruption/session-peer/releases/tags/" + tag] = json.dumps(release).encode()
                with mock.patch.object(session_peer.urllib.request, "urlopen", side_effect=self.open_fixture(urls)), \
                        mock.patch.object(session_peer.shutil, "which", return_value="gh"), \
                        mock.patch.object(session_peer, "release_validate_runtime") as runtime, \
                        mock.patch.object(session_peer.subprocess, "run", return_value=subprocess.CompletedProcess(
                            [], 0, stdout='[{}]', stderr='')):
                    version = session_peer.verified_release_download(root, tag=tag, event_release=True,
                                                                      expected_commit=self.commit)
                    self.assertEqual(version, "9.8.7rc1" if prerelease else "9.8.7")
                    runtime.assert_called_once_with(root / "session_peer.py", version)

    def test_event_sha_mismatch_is_rejected_before_asset_download_or_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            urls, release, _ = self.fixture(root)
            urls["https://api.github.com/repos/abruption/session-peer/releases/tags/" + self.tag] = json.dumps(release).encode()
            with mock.patch.object(session_peer.urllib.request, "urlopen", side_effect=self.open_fixture(urls)), \
                    mock.patch.object(session_peer, "release_validate_runtime") as runtime:
                with self.assertRaisesRegex(session_peer.ReleaseVerificationError, "event commit"):
                    session_peer.verified_release_download(root, tag=self.tag, event_release=True,
                                                           expected_commit="b" * 40)
                runtime.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])

    def test_hostile_metadata_manifest_and_provenance_never_execute(self):
        for mode in ("legacy", "draft", "prerelease", "oversized", "evil-url", "duplicate", "extra-asset", "digest",
                     "provenance", "manifest-duplicate", "manifest-traversal", "attestation", "missing-gh"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                urls, release, payloads = self.fixture(root)
                prefix = "https://github.com/abruption/session-peer/releases/download/" + self.tag + "/"
                if mode == "legacy": release["immutable"] = False
                if mode == "draft": release["draft"] = True
                if mode == "prerelease": release["prerelease"] = True
                if mode == "oversized": release["assets"][0]["size"] = session_peer.RELEASE_SOURCE_LIMIT + 1
                if mode == "evil-url": release["assets"][0]["browser_download_url"] = "https://evil.example/source"
                if mode == "duplicate": release["assets"].append(release["assets"][0])
                if mode == "extra-asset": release["assets"].append({"name": "unreviewed.txt"})
                if mode == "digest": urls[prefix + "session_peer.py"] = b"x" * len(payloads["session_peer.py"])
                if mode == "provenance":
                    provenance = json.loads(payloads["release-provenance.json"])
                    provenance["commit"] = "b" * 40
                    urls[prefix + "release-provenance.json"] = json.dumps(provenance).encode()
                if mode.startswith("manifest-"):
                    data = payloads["SHA256SUMS"]
                    data += data.splitlines(keepends=True)[0] if mode == "manifest-duplicate" else b"a" * 64 + b"  ../bad\n"
                    urls[prefix + "SHA256SUMS"] = data
                    next(item for item in release["assets"] if item["name"] == "SHA256SUMS")["size"] = len(data)
                urls["https://api.github.com/repos/abruption/session-peer/releases/latest"] = json.dumps(release).encode()
                with mock.patch.object(session_peer.urllib.request, "urlopen", side_effect=self.open_fixture(urls)), \
                        mock.patch.object(session_peer.shutil, "which", return_value=None if mode == "missing-gh" else "gh"), \
                        mock.patch.object(session_peer, "release_validate_runtime") as runtime, \
                        mock.patch.object(session_peer.subprocess, "run", return_value=subprocess.CompletedProcess(
                            [], 1 if mode == "attestation" else 0, stdout='[{}]', stderr='denied')):
                    with self.assertRaises(session_peer.ReleaseVerificationError):
                        session_peer.verified_release_download(root, tag=self.tag)
                    runtime.assert_not_called()

    def test_annotated_tag_resolves_to_commit_and_invalid_chain_never_runs(self):
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                urls, _, _ = self.fixture(root)
                tag_sha = "b" * 40
                urls["https://api.github.com/repos/abruption/session-peer/git/ref/tags/" + self.tag] = json.dumps(
                    {"object": {"type": "tag", "sha": tag_sha}}).encode()
                urls["https://api.github.com/repos/abruption/session-peer/git/tags/" + tag_sha] = json.dumps(
                    {"object": {"type": "commit" if valid else "tree", "sha": self.commit}}).encode()
                with mock.patch.object(session_peer.urllib.request, "urlopen", side_effect=self.open_fixture(urls)), \
                        mock.patch.object(session_peer.shutil, "which", return_value="gh"), \
                        mock.patch.object(session_peer, "release_validate_runtime") as runtime, \
                        mock.patch.object(session_peer.subprocess, "run", return_value=subprocess.CompletedProcess(
                            [], 0, stdout='[{}]', stderr='')) as run:
                    if valid:
                        self.assertEqual(session_peer.verified_release_download(root), "9.8.7")
                        self.assertIn(self.commit, run.call_args_list[0].args[0])
                        runtime.assert_called_once()
                    else:
                        with self.assertRaisesRegex(session_peer.ReleaseVerificationError, "commit SHA"):
                            session_peer.verified_release_download(root)
                        run.assert_not_called()
                        runtime.assert_not_called()

    def test_latest_release_race_rejected_before_asset_download(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            urls, _, _ = self.fixture(root)
            with mock.patch.object(session_peer.urllib.request, "urlopen", side_effect=self.open_fixture(urls)), \
                    mock.patch.object(session_peer, "release_attest") as attest, \
                    mock.patch.object(session_peer, "release_validate_runtime") as runtime:
                with self.assertRaisesRegex(session_peer.ReleaseVerificationError, "changed"):
                    session_peer.verified_release_download(root, tag="v9.8.6")
                attest.assert_not_called()
                runtime.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])

    def test_stream_cap_is_enforced_even_without_content_length(self):
        response = io.BytesIO(b"x" * 100)
        response.headers = {}
        with mock.patch.object(session_peer.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(session_peer.ReleaseVerificationError, "size limit"):
                session_peer.release_read("https://example.invalid", 10)

    def test_unsupported_gh_policy_flags_report_an_actionable_failure(self):
        with mock.patch.object(session_peer.shutil, "which", return_value="gh"), \
                mock.patch.object(session_peer.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 1, stdout="", stderr="unknown flag: --source-digest")):
            with self.assertRaisesRegex(session_peer.ReleaseVerificationError,
                                        "tested with 2.102.0.*gh auth login.*unknown flag"):
                session_peer.release_attest(Path("fixture"), self.commit)

    def test_wrong_literal_syntax_nonrunning_and_timeout_rejected(self):
        sources = [b'__version__ = "0.0.0"\nprint("session-peer 9.8.7")\n',
                   b'__version__ = "9.8.7"\nnot python!\n',
                   b'__version__ = "9.8.7"\nraise SystemExit(1)\n',
                   b'__version__ = "9.8.7"\nprint("session-peer 1.0.0")\n']
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "session_peer.py"
            for source in sources:
                path.write_bytes(source)
                with self.subTest(source=source), self.assertRaises(session_peer.ReleaseVerificationError):
                    session_peer.release_validate_runtime(path, "9.8.7")
            path.write_bytes(b'__version__ = "9.8.7"\n')
            with mock.patch.object(session_peer.subprocess, "run", side_effect=subprocess.TimeoutExpired([], 15)):
                with self.assertRaises(session_peer.ReleaseVerificationError):
                    session_peer.release_validate_runtime(path, "9.8.7")

    def test_update_failure_leaves_current_file_untouched_and_removes_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "session_peer.py"
            target.write_bytes(b"existing install")
            args = argparse.Namespace(host=[], check=False, json=True)
            with mock.patch.object(session_peer, "__file__", str(target)), \
                    mock.patch.object(session_peer, "installed_as_distribution", return_value=False), \
                    mock.patch.object(session_peer, "latest_release", return_value=(self.tag, "unused")), \
                    mock.patch.object(session_peer, "write_update_cache"), \
                    mock.patch.object(session_peer, "verified_release_download", side_effect=session_peer.ReleaseVerificationError("bad digest")):
                with self.assertRaises(session_peer.CcPeerError):
                    session_peer.cmd_update(args)
            self.assertEqual(target.read_bytes(), b"existing install")
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_update_full_download_gates_and_successful_atomic_replace(self):
        real_run = subprocess.run
        for mode in ("success", "digest", "version", "nonrunning", "oversized", "attestation"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / "session_peer.py"
                target.write_bytes(b"previous installation")
                runtime = b'__version__ = "9.8.7"\nprint("session-peer " + __version__)\n'
                if mode == "version": runtime = runtime.replace(b'"9.8.7"', b'"9.8.6"')
                if mode == "nonrunning": runtime += b'raise SystemExit(1)\n'
                urls, release, _ = self.fixture(root, runtime=runtime)
                prefix = "https://github.com/abruption/session-peer/releases/download/" + self.tag + "/"
                if mode == "digest": urls[prefix + "session_peer.py"] = b"x" * len(runtime)
                if mode == "oversized": release["assets"][0]["size"] = session_peer.RELEASE_SOURCE_LIMIT + 1
                urls["https://api.github.com/repos/abruption/session-peer/releases/latest"] = json.dumps(release).encode()
                def run(command, **options):
                    if command[0] == "gh":
                        return subprocess.CompletedProcess(command, int(mode == "attestation"), '[{}]', '')
                    return real_run(command, **options)
                args = argparse.Namespace(host=[], check=False, json=True)
                with mock.patch.object(session_peer, "__file__", str(target)), \
                        mock.patch.object(session_peer, "installed_as_distribution", return_value=False), \
                        mock.patch.object(session_peer, "latest_release", return_value=(self.tag, "unused")), \
                        mock.patch.object(session_peer, "write_update_cache"), \
                        mock.patch.object(session_peer.urllib.request, "urlopen", side_effect=self.open_fixture(urls)), \
                        mock.patch.object(session_peer.shutil, "which", return_value="gh"), \
                        mock.patch.object(session_peer.subprocess, "run", side_effect=run), \
                        mock.patch.object(session_peer, "emit"):
                    if mode == "success":
                        self.assertEqual(session_peer.cmd_update(args), 0)
                    else:
                        with self.assertRaises(session_peer.CcPeerError):
                            session_peer.cmd_update(args)
                self.assertEqual(target.read_bytes(), runtime if mode == "success" else b"previous installation")
                self.assertEqual(list(root.iterdir()), [target])

    @unittest.skipIf(os.name == "nt", "POSIX installer")
    def test_installer_default_success_and_mismatch_preserve_existing_files(self):
        for mode in ("success", "digest", "attestation", "version", "nonrunning", "oversized"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                home = root / "home"
                home.mkdir()
                marker = root / "executed"
                runtime = ('__version__ = "9.8.7"\n'
                           'from pathlib import Path\n'
                           f'Path({str(marker)!r}).write_text("executed")\n'
                           'print("session-peer " + __version__)\n').encode()
                if mode == "version": runtime = runtime.replace(b'"9.8.7"', b'"9.8.6"')
                if mode == "nonrunning": runtime += b'raise SystemExit(1)\n'
                urls, release, payloads = self.fixture(root, runtime=runtime)
                prefix = "https://github.com/abruption/session-peer/releases/download/" + self.tag + "/"
                if mode == "digest": urls[prefix + "session_peer.py"] = b"x" * len(runtime)
                if mode == "oversized": release["assets"][0]["size"] = session_peer.RELEASE_SOURCE_LIMIT + 1
                urls["https://api.github.com/repos/abruption/session-peer/releases/latest"] = json.dumps(release).encode()
                fixtures = root / "fixtures.json"
                fixtures.write_text(json.dumps({url: data.hex() for url, data in urls.items()}))
                fake_bin = root / "bin"
                fake_bin.mkdir()
                gh = fake_bin / "gh"
                gh.write_text('#!/bin/sh\n[ "$VERIFY_MODE" != attestation ] || exit 1\nprintf "[{}]\\n"\n')
                gh.chmod(0o755)
                (fake_bin / "sitecustomize.py").write_text(
                    'import io,json,os,urllib.request\n'
                    'fixtures=json.load(open(os.environ["RELEASE_FIXTURES"]))\n'
                    'def open_fixture(request,**kwargs):\n'
                    '    response=io.BytesIO(bytes.fromhex(fixtures[request.full_url]))\n'
                    '    response.headers={}\n'
                    '    return response\n'
                    'urllib.request.urlopen=open_fixture\n')
                program = home / ".local/share/session-peer/session_peer.py"
                program.parent.mkdir(parents=True)
                program.write_bytes(b"existing installation")
                skill = home / ".agents/skills/session-peer/SKILL.md"
                skill.parent.mkdir(parents=True)
                skill.write_bytes(b"existing skill")
                (skill.parent / ".session-peer-installer").write_text("owned")
                launcher = home / ".local/bin/session-peer"
                launcher.parent.mkdir(parents=True)
                launcher.symlink_to(program)
                env = {**os.environ, "HOME": str(home), "PYTHONPATH": str(fake_bin),
                       "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                       "RELEASE_FIXTURES": str(fixtures), "VERIFY_MODE": mode}
                env.pop("CLAUDE_CONFIG_DIR", None)
                env.pop("ANTHROPIC_CONFIG_DIR", None)
                done = subprocess.run(["sh", str(ROOT / "install.sh")], env=env,
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual(done.returncode == 0, mode == "success", done.stderr)
                if mode == "success":
                    self.assertEqual(program.read_bytes(), runtime)
                    self.assertEqual(skill.read_bytes(), payloads["SKILL.md"])
                else:
                    self.assertEqual(program.read_bytes(), b"existing installation")
                    self.assertEqual(skill.read_bytes(), b"existing skill")
                if mode in ("digest", "attestation", "version", "oversized"):
                    self.assertFalse(marker.exists(), "unauthenticated/invalid code executed")
                self.assertTrue(launcher.is_symlink())
                self.assertEqual(list(program.parent.glob(".install.*")), [])


if __name__ == "__main__":
    unittest.main()
