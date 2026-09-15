# Releasing session-peer

Publishing a GitHub release triggers `.github/workflows/publish.yml`, which builds
the tag and uploads it to PyPI through Trusted Publishing. A draft release does
not publish. Keep release preparation, approval, publication, and verification as
separate steps so the tag and uploaded artifacts always point at reviewed code.

## Current candidate: v0.6.2

The v0.6.2 candidate contains #63 and #64. It does not include the unfinished
v0.7 roadmap in #45. The version source is `session_peer.py`; Hatch reads it for
both wheel and sdist metadata. Reviewed notes live in
`docs/releases/v0.6.2.md`.

The repository must continue to contain the frozen root `cc_peer.py` for legacy
self-update URLs. It must remain outside the session-peer wheel and sdist.

## Trusted Publisher configuration

The GitHub environment is `pypi`, and the active workflow is `publish.yml`.
The PyPI project owner should retain this Trusted Publisher mapping:

| Field | Value |
| --- | --- |
| PyPI project | `session-peer` |
| GitHub owner | `abruption` |
| GitHub repository | `session-peer` |
| Workflow filename | `publish.yml` |
| GitHub environment | `pypi` |

The v0.6.1 release used this path successfully. GitHub cannot inspect the PyPI
owner-side mapping, so a previous success is evidence rather than a guarantee
that it has not changed.

## Prepare and verify

1. Create a release issue and branch from current `origin/main`.
2. Update `session_peer.__version__`, durable README wording, this runbook, and
   `docs/releases/<version>.md` in one release-preparation PR.
3. Run the checks used by CI:

   ```bash
   python3 -m compileall -q cc_peer.py session_peer.py tests
   python3 -m unittest discover -s tests -v
   python3 -m unittest discover -v
   python3 -m build
   ```

4. Inspect both archives. `session_peer.py`, license, metadata, and README belong
   in the sdist; the wheel contains the session-peer module and metadata. Neither
   archive may contain `cc_peer.py`, credentials, session databases, or local
   notes.
5. Install the wheel and sdist independently in fresh environments. Confirm
   `session-peer --version`, `session-peer list --json`, and import metadata.
6. Merge the release-preparation PR only after every required check passes. Fetch
   `main`, record its exact commit, and confirm it still contains the intended
   changes and version.

## Prepare the draft

Create the draft only after the release-preparation PR is merged, because a
squash or merge commit changes the release commit:

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v0.6.2 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v0.6.2" \
  --notes-file docs/releases/v0.6.2.md \
  --draft --latest
```

Verify the draft's tag, target commit, title, notes, draft status, and prerelease
status. If GitHub created the tag while saving the draft, confirm it resolves to
the recorded release commit. Do not move an existing published tag.

## Publish

Obtain final approval immediately before publication. Publishing is the action
that makes the GitHub release public and starts the PyPI upload:

```bash
gh release edit v0.6.2 --repo abruption/session-peer --draft=false --latest
```

Do not create a second release or retry with modified artifacts if the workflow
fails. Preserve the failed run and diagnose the failing stage. A version already
accepted by PyPI cannot be replaced.

## Verify publication

1. Confirm the release-triggered `publish.yml` run completed successfully and
   used the expected tag and commit.
2. Confirm PyPI exposes exactly `session-peer==0.6.2`. Download the wheel and
   sdist, compare their filenames and SHA-256 hashes with the workflow artifacts,
   and inspect their contents again.
3. Install 0.6.2 from PyPI into a fresh environment. Confirm the version and a
   local read-only listing. A no-submit dry-run may use an explicit temporary
   Codex home and executable; expected target failure is acceptable if it proves
   no queue command ran.
4. Confirm GitHub marks v0.6.2 as latest and `session-peer update --check` reports
   it to an older standalone installation.
5. Close the release issue only after GitHub, PyPI, fresh-install, and updater
   verification are recorded.

Package-managed installations upgrade with their own manager. Standalone
installations use `session-peer update`; `install.sh` is required to refresh the
bundled Claude skill. Submission is never proof of consumption or acknowledgement.
