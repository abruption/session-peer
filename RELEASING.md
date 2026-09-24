# Releasing session-peer

Publishing a GitHub release triggers `.github/workflows/publish.yml`, which builds
the selected tag and uploads wheel and sdist to PyPI through Trusted Publishing.
A draft does not publish. Keep preparation, final approval, publication, and
verification separate. Protected `main` requires an up-to-date PR and the
aggregate `release gate`: Linux, macOS and Windows Python matrices; documentation,
shell, wheel, sdist, standalone, MCP, Relay and control tests; integration tests;
and Python/Node dependency audits. Live OAuth, agent ACKs and production Relay
health are separate operator evidence.

## Stable v1.0.0 gate

The reviewed RC4 runtime was validated in the five-host `rc4-rerun-02` campaign:
14,436.65 seconds with a `complete` record, public health 241/241, probes
147/147, submissions 21/21, and Relay restart recovery in 3.182 seconds.
Independent ACKs were 20/21. The original T120 Windows native Claude ACK is
unconfirmed because its TUI closed; a distinct one-shot check of the same path
subsequently received an exact ACK. The user explicitly accepted this operational
exception in #164. Do not rewrite the original result as 21/21. #161's external
stall origin remains unproven; mitigation is not root-cause repair. Stable
promotion requires no runtime behavior change from RC4 and a fresh `main` CI run.

The Python/PyPI version is `1.0.0`; the Git tag and GitHub release are `v1.0.0`.
This is a stable release: do not mark it prerelease, and make it GitHub Latest.
Normal package upgrades and standalone update notices may select v1.0.0 instead
of v0.9.2. The plugin manifest keeps its independent version. The default core
remains dependency-free on Python 3.9+; MCP needs Python 3.10+, and Relay
receiver/server use requires Unix or WSL and Python 3.11+. Package publication
does not guarantee hosted Relay/OAuth availability. A service-managed macOS or
Linux receiver needs the target TUI's `codex` executable directory on its PATH;
`codexBin` is WSL-only. Relay login expires and can require reauthorization.

The root `cc_peer.py` is frozen for legacy self-update URLs and must be excluded
from wheel and sdist. Include four READMEs, security policy, stable release notes,
Relay documentation and optional runtime sources. Exclude credentials, device
keys, auth databases, replay state, browser profiles, local evidence and chats.

## Trusted Publisher configuration

The PyPI project `session-peer` maps to GitHub repository
`abruption/session-peer`, workflow `publish.yml`, environment `pypi`. No long-lived PyPI
credential is stored in the repository. Prior success is not proof the mapping
has remained unchanged; verify it before publication.

## Prepare and verify

1. Resolve the v1.0.0 milestone and #152 docs gate. Record #164's operational
   exception and keep #161 as v1.0.1 monitoring with root cause unconfirmed.
   Confirm the final diff against RC4 changes only version, generated artifact,
   documentation and tests; do not merge `release/0.9.x` into `main`.
2. Confirm `session_peer.__version__ == "1.0.0"`, generated `session_peer.py`
   matches its source, four README install commands agree, and four stable
   release notes are included in sdist. Run the complete local suite and the
   PR `release gate`; after merge, require a successful CI run on exact `main`.
3. Build wheel and sdist from the exact candidate with `python3 -m build`.
   Inspect contents and install each archive independently in clean environments.
   Check `session-peer --version`, clean-home JSON `list`, `pip check`, Relay/MCP
   extras and help smoke tests. Do not submit live model messages for this gate.
4. Merge only after checks pass. Fetch `main`, record its exact commit, recheck
   version and release notes, and confirm PyPI has no `1.0.0` files yet.

## Prepare the draft

Create the draft only after the preparation PR is merged; a squash or merge
commit changes the release commit. Never move an existing published tag.

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v1.0.0 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.0" \
  --notes-file docs/releases/v1.0.0.md \
  --draft --latest
```

Verify tag, target, title, notes, draft status, stable status and Latest intent.
Draft creation does not authorize publication.

## Publish

Obtain final user approval immediately before publication. Publishing makes the
GitHub release public and starts the immutable PyPI upload:

```bash
gh release edit v1.0.0 \
  --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

The workflow must fail closed unless tag and package version agree, the tag is
the event commit on protected main, and the clean source reproducibly builds
identical wheel and sdist twice. It installs both candidates, checks archives,
audits dependencies, records SHA256SUMS and release-provenance.json, requests
GitHub/PyPI attestations, and uploads via OIDC. Existing PyPI files are a hard
error; do not skip them.

Do not rerun an upload with modified artifacts after failure. Preserve the failed
run and any accepted files, then diagnose the first failed gate. PyPI versions
and filenames are immutable. A partial `1.0.0` publication or hash mismatch stops
promotion; fix forward through reviewed changes and a new version (normally
`1.0.1`), not a moved tag or reused version. Yanking does not make reuse safe.

## Verify publication

1. Verify `publish.yml` succeeded for the exact tag and commit. Download both
   PyPI files, compare hashes with preserved workflow candidates and provenance,
   and install each independently from PyPI in fresh environments.
2. Repeat version, clean-home JSON `list`, Relay/MCP extras and `pip check`.
   Confirm GitHub says stable and Latest, and normal upgrade/update checks select
   v1.0.0. Verify hosted Relay separately; a queued message is not an ACK.
3. Record evidence and only then close the v1.0.0 milestone. Fleet deployment
   or production service restarts require a separate operational decision.
