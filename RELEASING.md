# Releasing session-peer

Publishing a GitHub release triggers `.github/workflows/publish.yml`, which builds
the selected tag and uploads it to PyPI through Trusted Publishing. A draft does
not publish. Keep preparation, approval, publication and verification separate so
the public artifacts always point at reviewed code.

Protected main requires one stable release gate and an up-to-date pull request.
The aggregate runs even after a dependency fails and succeeds only when every
release-critical job succeeds: all Linux, macOS and Windows Python combinations;
documentation and shell checks; wheel, sdist and standalone installation; the
MCP and relay matrices; Node control and Node/Python integration; and Python and
Node runtime dependency audits. Matrix expansion remains covered by its job
result, while a structural test requires the aggregate to depend on every other
CI job so renaming or adding a job cannot silently remove it from the gate.

The required gate uses deterministic fixtures. Live OAuth, model calls,
production relay traffic and production mutation remain separate operator
evidence. All third-party actions are pinned to full commit hashes. Dependabot
submits reviewable updates for Actions, Python build and audit tools, and Node
dependencies; updates pass the same gate rather than floating into a release.

RC4 publication and stable promotion are separate gates. Keep #161, #163, #164 and the RC4 milestone open until the exact published RC4 is validated on all five hosts with independent ACK evidence and an uninterrupted four-hour campaign. Follow the [RC4 validation plan](docs/releases/v1.0.0-rc.4.md); RC2 evidence and offline reproductions are not substitutes.

## Current candidate: v1.0.0-rc.4

The fourth 1.0 release candidate retains the RC2 contract, including the Windows
fixes from #158, and addresses the public Relay route failures tracked in #161:
sanitized route diagnostics with a bounded pre-submit setup retry (#162), and
shorter receiver reconnect gaps with role_busy metrics (#168). The Claude and SSH
fixes from RC2 are also released in stable v0.9.2.
Its canonical Python/PyPI version is `1.0.0rc4`; the human-facing Git tag
and GitHub release are `v1.0.0-rc.4`. `packaging.version.Version` treats those
values as equal. Do not use a bare `v1.0.0-rc`, which normalizes to RC zero.

RC3 was only partially published to PyPI: its wheel was accepted, but the sdist
upload failed after repeated HTTP 502 responses. It is not a promotable release.
RC4 changes only the candidate version and release documentation; the runtime
behavior remains the reviewed #162 and #168 implementation. Never retry RC3's
two-file upload or reuse its immutable version.

This release is an explicit prerelease:

- mark the GitHub release **Pre-release** and do not mark it Latest;
- normal stable package upgrades must continue to select v0.9.2;
- testers install the exact version with
  `pipx install 'session-peer[relay]==1.0.0rc4'` or the equivalent `uv` command;
- keep the v1.0.0-rc.4 milestone open until GitHub, PyPI and fresh-install verification finish;
- the plugin manifest retains its independent version (0.1.0).

The candidate includes local/SSH operation, optional MCP and Antigravity adapters,
paired direct/relay transport, managed admission, public OAuth signup, active
revocation and recovery, operator metrics and the reviewed KR deployment artifacts. The relay
extra requires Unix and Python 3.11+. The default core remains dependency-free on
Python 3.9+. A hosted relay is an operational service and not a package-availability
promise.

The repository must retain the frozen root `cc_peer.py` for legacy self-update
URLs while excluding it from wheel and sdist. Include all four READMEs, security
policy, release candidate notes, relay lifecycle/auth documentation and optional
runtime sources. Never include OAuth credentials, device keys, auth databases,
replay state, browser profiles, local evidence or conversations.

## Trusted Publisher configuration

The GitHub environment is `pypi`, and the active workflow is `publish.yml`. The
PyPI project owner should retain this Trusted Publisher mapping:

| Field | Value |
| --- | --- |
| PyPI project | `session-peer` |
| GitHub owner | `abruption` |
| GitHub repository | `session-peer` |
| Workflow filename | `publish.yml` |
| GitHub environment | `pypi` |

A previous successful release is evidence, not a guarantee that the owner-side
mapping has not changed. The repository stores no long-lived PyPI credential;
the environment and PyPI exchange GitHub's short-lived OIDC identity.

## Prepare and verify

1. Confirm the release branch contains merged #158, #162 and #168,
   and targets `main`. Do not merge the stable maintenance branch into main.
2. Confirm `session_peer.__version__ == "1.0.0rc4"`, the release candidate notes are included
   in the sdist, and the four README install commands agree.
3. Run the complete CI matrix. Locally repeat the core suite, control Node 22/24
   suite, Node/Python integration, build and archive inspection appropriate to
   the final diff. Live model submissions are not part of release preparation.
   The stable aggregate release gate and the resulting main-branch run must both
   pass before tagging.
4. Build once from the exact candidate:

   ```bash
   python3 -m build
   ```

5. Inspect both archives. The wheel contains `session_peer.py`,
   `session_peer_mcp.py`, `session_peer_relay/` and metadata. The sdist also
   contains the approved documentation and deployment templates. Neither archive
   may contain `cc_peer.py`, credentials, databases, replay state, private keys,
   browser data or local evidence.
6. Install wheel and sdist independently in fresh environments. Confirm
   `session-peer --version` reports `1.0.0rc4`, `session-peer list --output-format
   json` works in an empty home, and relay/MCP extras pass `pip check` and help
   smoke tests.
7. Merge only after required checks pass. Fetch `main`, record its exact commit,
   and verify the version and intended changes at that commit.

## Prepare the draft

Create the draft only after the release-preparation PR is merged. A squash or
merge commit changes the release commit.

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v1.0.0-rc.4 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.0-rc.4" \
  --notes-file docs/releases/v1.0.0-rc.4.md \
  --draft --prerelease --latest=false
```

Verify tag, target, title, notes, draft status and prerelease status. Do not move
an existing published tag. Draft creation does not authorize publication.

## Publish

Obtain final user approval immediately before publication. Publishing makes the
GitHub release public and triggers the PyPI upload:

```bash
gh release edit v1.0.0-rc.4 \
  --repo abruption/session-peer \
  --draft=false --prerelease --latest=false
```

Publication fails closed unless the tag and normalized package version agree,
the tag resolves to the event commit contained in protected main, and the release
target is main or that exact commit. The clean source is built twice with the
commit timestamp and both wheel and sdist must be byte-for-byte reproducible.
Exact archive contents are checked before the two artifacts are installed in
separate environments.

The workflow preserves SHA256SUMS and release-provenance.json with the repository,
commit, tag, workflow run and exact artifact hashes, and records GitHub build
provenance. Python and Node runtime audits must pass. Trusted Publishing then
uploads only those verified distributions through OIDC and requests PyPI PEP 740
attestations. Existing PyPI files remain a hard error rather than being skipped.

Do not create a second release or retry with modified artifacts if the workflow
fails. Preserve the failed run, its logs and any uploaded evidence, then diagnose
the first failed gate. PyPI filenames and versions are immutable: never overwrite
or reuse one. Fix forward through a reviewed change and a new version and tag. A
partial publication or hash mismatch stops promotion; yanking a release does not
make its version reusable. Audit findings require reviewed dependency changes,
not forced automatic fixes, destructive lockfile rewrites or unreviewed
downgrades.

## Verify publication

1. Confirm `publish.yml` succeeded for the expected tag and commit.
2. Confirm PyPI exposes exactly `session-peer==1.0.0rc4`. The workflow downloads
   the complete PyPI file set, compares its hashes with the preserved candidates,
   and installs the downloaded wheel and sdist independently. Preserve both
   workflow evidence artifacts and the run URL.
3. Install the exact PyPI prerelease in fresh environments and repeat version,
   clean-home list, relay-extra and MCP smoke checks.
4. Confirm GitHub marks the release as prerelease and not latest. The stable
   `releases/latest` endpoint and ordinary update notices must continue to point
   to v0.9.2.
5. Verify the hosted relay separately; package publication does not prove service
   health, OAuth policy or agent acknowledgement.
6. Close the v1.0.0-rc.4 milestone only after GitHub, PyPI and fresh-install evidence is recorded.

Package-managed installations upgrade with their own manager. Standalone stable
installations keep using `session-peer update`; release candidate testers use the exact package
version. Submission is never proof of consumption or acknowledgement.
