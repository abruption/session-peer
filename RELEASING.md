# Releasing session-peer

Publishing a GitHub release triggers `.github/workflows/publish.yml`, which builds
the selected tag and uploads it to PyPI through Trusted Publishing. A draft does
not publish. Keep preparation, approval, publication and verification separate so
the public artifacts always point at reviewed code.

## Current candidate: v1.0.0-alpha.1

The first 1.0 alpha depends on the authenticated relay RC in #99. Its canonical
Python/PyPI version is `1.0.0a1`; the human-facing Git tag and GitHub release are
`v1.0.0-alpha.1`. `packaging.version.Version` treats those values as equal. Do
not use a bare `v1.0.0-alpha`, which normalizes to alpha zero.

This release is an explicit prerelease:

- mark the GitHub release **Pre-release** and do not mark it Latest;
- normal stable package upgrades must continue to select v0.9.0;
- testers install the exact version with
  `pipx install 'session-peer[relay]==1.0.0a1'` or the equivalent `uv` command;
- keep #101 open until GitHub, PyPI and fresh-install verification finish;
- the plugin manifest retains its independent version (0.1.0).

The candidate includes local/SSH operation, optional MCP and Antigravity adapters,
paired direct/relay transport, managed admission, public OAuth signup, active
revocation, operator metrics and the reviewed KR deployment artifacts. The relay
extra requires Unix and Python 3.11+. The default core remains dependency-free on
Python 3.9+. A hosted relay is an operational service and not a package-availability
promise.

The repository must retain the frozen root `cc_peer.py` for legacy self-update
URLs while excluding it from wheel and sdist. Include all four READMEs, security
policy, alpha release notes, relay lifecycle/auth documentation and optional
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
mapping has not changed.

## Prepare and verify

1. Merge #99 first. Retarget the release-preparation PR to `main`, update it, and
   require a clean merge. Do not recreate release changes manually on another
   branch.
2. Confirm `session_peer.__version__ == "1.0.0a1"`, the alpha notes are included
   in the sdist, and the four README install commands agree.
3. Run the complete CI matrix. Locally repeat the core suite, control Node 22/24
   suite, Node/Python integration, build and archive inspection appropriate to
   the final diff. Live model submissions are not part of release preparation.
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
   `session-peer --version` reports `1.0.0a1`, `session-peer list --output-format
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
gh release create v1.0.0-alpha.1 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.0-alpha.1" \
  --notes-file docs/releases/v1.0.0-alpha.1.md \
  --draft --prerelease --latest=false
```

Verify tag, target, title, notes, draft status and prerelease status. Do not move
an existing published tag. Draft creation does not authorize publication.

## Publish

Obtain final user approval immediately before publication. Publishing makes the
GitHub release public and triggers the PyPI upload:

```bash
gh release edit v1.0.0-alpha.1 \
  --repo abruption/session-peer \
  --draft=false --prerelease --latest=false
```

Do not create a second release or retry with modified artifacts if the workflow
fails. Preserve the failed run and diagnose it. PyPI versions are immutable.

## Verify publication

1. Confirm `publish.yml` succeeded for the expected tag and commit.
2. Confirm PyPI exposes exactly `session-peer==1.0.0a1`. Download wheel and sdist,
   compare their hashes with the workflow artifacts, and inspect contents again.
3. Install the exact PyPI prerelease in fresh environments and repeat version,
   clean-home list, relay-extra and MCP smoke checks.
4. Confirm GitHub marks the release as prerelease and not latest. The stable
   `releases/latest` endpoint and ordinary update notices must continue to point
   to v0.9.0.
5. Verify the hosted relay separately; package publication does not prove service
   health, OAuth policy or agent acknowledgement.
6. Close #101 only after GitHub, PyPI and fresh-install evidence is recorded.

Package-managed installations upgrade with their own manager. Standalone stable
installations keep using `session-peer update`; alpha testers use the exact package
version. Submission is never proof of consumption or acknowledgement.
