"""Maintenance source and GitHub policy checks never publish or mutate refs remotely."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tests.test_release_artifacts import release_artifacts as release


class Source(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.git('init')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Release fixture')
        self.git('config', 'commit.gpgsign', 'false')
        self.git('config', 'tag.gpgsign', 'false')
        (self.root/'session_peer.py').write_text('__version__ = "0.9.1"\n')
        self.git('add', 'session_peer.py'); self.git('commit', '-m', 'baseline')
        baseline = self.git('rev-parse', 'HEAD')
        patch = mock.patch.object(release, 'MAINTENANCE_BASE', baseline)
        patch.start(); self.addCleanup(patch.stop)
        (self.root/'session_peer.py').write_text('__version__ = "0.9.2"\n')
        self.git('commit', '-am', 'candidate')
        self.head = self.git('rev-parse', 'HEAD')
        self.git('tag', 'v0.9.2')
        self.git('update-ref', 'refs/remotes/origin/release/0.9.x', self.head)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout.strip()

    def verify(self, **overrides):
        args = dict(tag='v0.9.2', target='release/0.9.x', expected_sha=self.head, root=self.root)
        args.update(overrides)
        return release.verify_source(**args)

    def test_exact_maintenance_source_and_sha_target_pass(self):
        self.assertEqual(self.verify(), '0.9.2')
        self.assertEqual(self.verify(target=self.head), '0.9.2')

    def test_tag_version_and_target_must_be_canonical(self):
        for tag in ('0.9.2', 'v0.9.02', 'v0.9.3', 'v0.9.2rc1', 'v1.0.0'):
            with self.subTest(tag=tag), self.assertRaises(release.VerificationError):
                self.verify(tag=tag)
        for target in ('main', 'refs/heads/main', 'release/0.8.x', self.head[:7]):
            with self.subTest(target=target), self.assertRaises(release.VerificationError):
                self.verify(target=target)

    def test_version_line_rejects_rc_and_nonmaintenance_versions(self):
        for version in ('0.9.1', '0.9.02', '0.9.2rc1', '0.9.2+local', '1.0.0', '0.10.2'):
            with mock.patch.object(release, 'project_version', return_value=version):
                with self.assertRaises(release.VerificationError):
                    self.verify(tag='v'+version)

    def test_event_sha_and_tag_commit_must_match(self):
        with self.assertRaises(release.VerificationError):
            self.verify(expected_sha='a'*40)
        self.git('tag', '-f', 'v0.9.2', 'HEAD~1')
        with self.assertRaisesRegex(release.VerificationError, 'tag does not resolve'):
            self.verify()

    def test_stale_branch_tip_is_rejected(self):
        self.git('update-ref', 'refs/remotes/origin/release/0.9.x', 'HEAD~1')
        with self.assertRaisesRegex(release.VerificationError, 'branch tip'):
            self.verify()

    def test_unrelated_baseline_and_dirty_checkout_rejected(self):
        with mock.patch.object(release, 'MAINTENANCE_BASE', 'a'*40):
            with self.assertRaisesRegex(release.VerificationError, 'pinned v0.9.1'):
                self.verify()
        (self.root/'unreviewed').write_text('dirty')
        with self.assertRaisesRegex(release.VerificationError, 'not clean'):
            self.verify()


class Governance(unittest.TestCase):
    sha = 'b'*40

    def setUp(self):
        self.branch = {'name':'release/0.9.x', 'protected':True, 'commit':{'sha':self.sha}}
        self.branch['protection'] = {'required_status_checks': {
            'enforcement_level':'everyone', 'checks':[{'context':'release gate','app_id':15368}]}}
        self.pull = {'number':159, 'state':'closed', 'merged_at':'fixture', 'merge_commit_sha':self.sha,
                     'base':{'ref':'release/0.9.x', 'repo':{'full_name':release.REPOSITORY}}}
        self.run = {'id':10, 'head_sha':self.sha, 'head_branch':'release/0.9.x', 'event':'push',
                    'path':'.github/workflows/ci.yml', 'status':'completed', 'conclusion':'success',
                    'repository':{'full_name':release.REPOSITORY}}

    def verify(self, branch=None, pulls=None, runs=None):
        with mock.patch.object(release, 'github_json', side_effect=[
                self.branch if branch is None else branch,
                [self.pull] if pulls is None else pulls,
                {'workflow_runs':[self.run] if runs is None else runs}]):
            return release.verify_governance(self.sha)

    def test_protected_merged_commit_with_successful_push_ci(self):
        self.assertEqual(self.verify()['pull_requests'], [159])

    def test_unprotected_or_moved_branch_rejected(self):
        for branch in ({**self.branch, 'protected':False},
                       {**self.branch, 'commit':{'sha':'c'*40}}):
            with self.assertRaises(release.VerificationError):
                self.verify(branch=branch)

    def test_unmerged_wrong_commit_or_wrong_base_pr_rejected(self):
        for changes in ({'merged_at':None}, {'state':'open'}, {'merge_commit_sha':'c'*40},
                        {'base':{'ref':'main', 'repo':{'full_name':release.REPOSITORY}}}):
            with self.assertRaises(release.VerificationError):
                self.verify(pulls=[{**self.pull, **changes}])
        with self.assertRaises(release.VerificationError):
            self.verify(pulls=[])

    def test_missing_wrong_app_or_admin_bypass_gate_rejected(self):
        for checks in ({}, {'enforcement_level':'non_admins', 'checks':[
                {'context':'release gate','app_id':15368}]},
                {'enforcement_level':'everyone', 'checks':[{'context':'release gate','app_id':1}]}):
            with self.assertRaises(release.VerificationError):
                self.verify(branch={**self.branch, 'protection':{'required_status_checks':checks}})

    def test_wrong_ci_commit_event_workflow_repo_and_incomplete_ci_rejected(self):
        for changes in ({'head_sha':'c'*40}, {'event':'pull_request'}, {'path':'other.yml'},
                        {'head_branch':'main'}, {'conclusion':'failure'}, {'status':'queued'},
                        {'repository':{'full_name':'other/repo'}}):
            with self.subTest(changes=changes), self.assertRaises(release.VerificationError):
                self.verify(runs=[{**self.run, **changes}])
        with self.assertRaises(release.VerificationError):
            self.verify(runs=[])

    def test_newer_failed_or_running_ci_cannot_be_hidden_by_old_success(self):
        for state in ('failure', None):
            latest = {**self.run, 'id':11, 'conclusion':state}
            with self.assertRaises(release.VerificationError):
                self.verify(runs=[self.run, latest])

    def test_api_failure_denies_release_without_exposing_response(self):
        with mock.patch.object(release.subprocess, 'run', side_effect=subprocess.CalledProcessError(
                1, 'gh', stderr='private failure details')):
            with self.assertRaisesRegex(release.VerificationError, 'publication denied') as error:
                release.verify_governance(self.sha)
        self.assertNotIn('private', str(error.exception))


if __name__ == '__main__':
    unittest.main()
