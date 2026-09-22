# Releasing session-peer 0.9.x maintenance updates

This runbook applies only to the stable maintenance line. Main and RC releases
retain their separate runbook and publisher. Do not merge RC features or relabel
RC source as 0.9.2 to work around release policy.

## Release source and approval

- Base: protected release/0.9.x, descending from the reviewed v0.9.1 commit
  d68aab73ad5be806da03281e30b73e74ed63db78.
- Accept only canonical v0.9.N tags (N >= 2) matching the literal package version.
  RC, dev, local versions, other release lines and shortened SHA targets fail.
- The tag, release-event SHA, checked-out SHA and current maintenance branch tip
  must identify the same clean commit. Target the maintenance branch or full SHA.
- The exact commit must be a merged PR result targeting this repository's
  release/0.9.x, not an unmerged head or a direct push.
- Require the latest push CI run for that exact commit, branch and ci.yml to
  complete successfully. PR CI alone does not prove the resulting merge commit.
- Branch protection requires PRs, up-to-date GitHub Actions release gate,
  linear history, resolved conversations, no force pushes or deletion, and
  enforcement for administrators. A second approver is not required for this
  solo-maintainer repository; final publication still requires explicit approval.
- API errors, missing evidence, changed branch tip, or removed branch protection
  stop publication. No fallback to main, another branch or the old publisher.

The governance verifier uses read-only GitHub API calls and checks the live
protected flag, merged PR and exact-commit push CI both before building and
immediately before upload. Branch-protection configuration itself is managed
separately; do not weaken or bypass it to satisfy a release.

## Prepare and merge

1. Update version, minimal fixes and release notes through a maintenance PR.
2. Wait for all PR CI jobs and release gate. CI includes Windows/macOS/Linux,
   core/MCP/Relay tests, pinned-action policy checks, isolated dependency audit,
   exact distribution contents, reproducible builds and independent installs.
3. Review the diff and merge into release/0.9.x. Do not merge this maintenance
   branch into main: the RC forward-fix is a separate PR.
4. Wait for push CI on the new merge/squash commit. Fetch and check out that
   exact commit in a clean checkout.
5. Confirm the branch protections and read-only governance result:

   ```bash
   git fetch origin release/0.9.x --tags
   release_commit=$(git rev-parse origin/release/0.9.x)
   python .github/scripts/release_artifacts.py verify-governance --commit "$release_commit"
   ```

The verifier prints only evidence identifiers, never credentials. GitHub Actions
provides GH_TOKEN in the environment; local gh authentication may be used for
preflight. Do not paste tokens into arguments, files, issue comments or logs.

## Draft, publication and verification

After the merged commit and push CI are verified, record the full SHA. Create a
draft with the exact version and commit, not a moving PR branch. Drafting or tag
creation is a separate approved operation; never move an existing tag.

For the initial maintenance update, the release version is 0.9.2 and the notes
are docs/releases/v0.9.2.md. Publishing the GitHub release starts publish.yml.
The workflow accepts release.published only, has serialized non-cancelling
maintenance concurrency, and has no manual skip-check path.

The hardened pipeline:

1. Check out the event's immutable commit; verify tag/version/baseline/branch tip
   and clean source, plus live protection/PR/push-CI evidence.
2. Build wheel and sdist twice using pinned tooling and require equal hashes.
   Check exact archive contents; exclude cc_peer.py, credentials and session DBs.
3. Write SHA256SUMS and release-provenance.json; retain immutable workflow
   artifacts and GitHub provenance attestation.
4. Install the wheel and sdist independently and audit runtime extras.
5. Recheck live governance, reverify the manifest, and pass only the unchanged
   wheel/sdist to the existing PyPI Trusted Publisher with PEP 740 attestations.
6. Download the exact PyPI file set, compare metadata and downloaded SHA-256
   values, then independently install both downloaded formats.

The existing Trusted Publisher identity remains repository abruption/session-peer,
workflow publish.yml, environment pypi. No PyPI account/token/permission change is
needed for this code path. Publishing is not complete until GitHub/PyPI artifacts,
fresh installs and the standalone updater's stable-release selection are verified.

Do not auto-retry an upload failure, use skip-existing, replace a published
version, or rebuild different files under the same version. Preserve evidence and
diagnose. If the maintenance branch advances before upload, the verifier denies
the older tip; prepare/review the new exact commit rather than bypassing the guard.

## 0.9.2 rollout order

Complete #159, its merged-commit push CI, v0.9.2 publication and artifact checks
first. Then merge the independent #158 forward-fix into main and prepare RC2.
The native Windows Claude candidate's actual reception and exact ACK have been
confirmed. Posted/queued still does not generally imply consumption.

This PR prepares the publication path; it does not create a release tag, publish
a GitHub release, upload to PyPI, or merge either PR.
