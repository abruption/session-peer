# Releasing session-peer

Publishing a GitHub release triggers `.github/workflows/publish.yml`, which verifies
the locked assets and uploads wheel and sdist to PyPI through Trusted Publishing.
A draft does not publish. Keep preparation, final approval, publication, and
verification separate. Protected `main` requires an up-to-date PR and the
aggregate `release gate`: Linux, macOS and Windows Python matrices; documentation,
shell, wheel, sdist, standalone, MCP, Relay and control tests; integration tests;
and Python/Node dependency audits. Live OAuth, agent ACKs and production Relay
health are separate operator evidence.

## Immutable release preparation (next approved release)

On 2026-10-03 the owner enabled GitHub Immutable Releases and active tag ruleset
24408525 for `refs/tags/v*`: tag update/deletion are blocked with no bypass;
creation is allowed. Historical `v1.0.2` remains `immutable: false` with no assets.
It is not a verified standalone release. Recheck repository settings before every
release; this change prepares future publication and does not authorize one.

Manually dispatch `prepare-release.yml` as the owner on protected `main` at the
exact tag commit. It checks source/ref/version/ancestry, reproducibility and package
installation, then attests and attaches all seven assets to an empty stable draft:
wheel, sdist, `session_peer.py`, `install.sh`, `SKILL.md`, `SHA256SUMS` and
`release-provenance.json`. The manifest covers five payloads; signed provenance
covers the manifest and evidence too. Draft attachment never publishes. Publishing
locks those files; `publish.yml` verifies and uploads the exact locked packages to
PyPI, without rebuilding or adding assets. Keep PyPI's workflow/environment mapping.

```bash
# Set the next approved version; no tag/version is changed by this document.
release_tag=vX.Y.Z
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
git tag "$release_tag" "$release_commit"
git push origin "$release_tag"
gh release create "$release_tag" --repo abruption/session-peer \
  --target "$release_commit" --title "session-peer $release_tag" \
  --notes-file "docs/releases/$release_tag.md" --draft --latest
gh workflow run prepare-release.yml --repo abruption/session-peer \
  --ref main -f tag="$release_tag"
# Review successful preparation, the seven draft assets, and their attestations.
# Obtain final approval before the separate publication command:
gh release edit "$release_tag" --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

Verified standalone installation/update requires a recent GitHub CLI supporting
`gh attestation verify`, including signer workflow, source ref/digest and hosted
runner policy. The installer defaults to the verified latest immutable release;
`--local-source` explicitly trusts adjacent source and `--main` explicitly opts in
to unverified development code. There is no automatic fallback for old releases or
missing attestations. Use pipx/uv/pip until a verified release exists. To authenticate
the installer before executing it (requires a lightweight version tag):

```bash
set -eu
repo=abruption/session-peer
tag=$(gh api "repos/$repo/releases/latest" --jq \
  'if .immutable == true and .draft == false and .prerelease == false then .tag_name else error("no immutable stable release") end')
commit=$(gh api "repos/$repo/git/ref/tags/$tag" --jq '.object | select(.type == "commit") | .sha')
case "$commit" in ????????* ) ;; * ) echo "expected a lightweight release tag" >&2; exit 1 ;; esac
staging=$(mktemp -d)
trap 'rm -f "$staging/install.sh"; rmdir "$staging"' EXIT
curl --fail --location --proto '=https' --proto-redir '=https' \
  --max-filesize 262144 --max-time 30 \
  "https://github.com/$repo/releases/download/$tag/install.sh" -o "$staging/install.sh"
gh attestation verify "$staging/install.sh" --repo "$repo" \
  --signer-workflow "$repo/.github/workflows/prepare-release.yml" \
  --source-ref refs/heads/main --source-digest "$commit" \
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  --deny-self-hosted-runners --format json
sh "$staging/install.sh"
```

The tested GitHub CLI baseline is 2.102.0; the earliest version supporting every
policy flag has not been established. Online attestation lookup requires authenticated
gh (`gh auth login` or `GH_TOKEN`); the installer needs repository/attestation read
access, not publication permission. See the [GitHub CLI verifier source](https://github.com/cli/cli/blob/v2.102.0/pkg/cmd/attestation/verify/verify.go).
These local fixtures establish policy/order/error behavior, not live signature acceptance.

GitHub and PyPI publication are separate irreversible steps. Dependency audits remain
mandatory both during preparation and again before PyPI upload. A newly disclosed CVE
between those checks can leave a locked public GitHub release without its PyPI version.
Preparation-time audit success is not current audit evidence. Treat publication as
incomplete until the publication workflow and PyPI verification succeed; retain both
run records and exact assets, diagnose the failed gate, and fix forward with a reviewed
new version when necessary. No audit bypass is authorized by this procedure; changing
the audit policy requires a separate owner decision.

Downloads are capped (standalone 8 MiB; support 256 KiB; metadata 1 MiB).
Authenticated manifest/provenance, exact tag/version and a successful staged
`--version` are required before replacement. The installer verifies on the sender
before SSH deployment; offline destinations need Python only. Existing files remain
untouched on verification failure. The following v1.0.2 procedure is historical;
use the preparation workflow above for future releases.


## v1.0.0 evidence and v1.0.2 maintenance gate

The reviewed RC4 runtime was validated in the five-host `rc4-rerun-02` campaign:
14,436.65 seconds with a `complete` record, public health 241/241, probes
147/147, submissions 21/21, and Relay restart recovery in 3.182 seconds.
Independent ACKs were 20/21. The original T120 Windows native Claude ACK is
unconfirmed because its TUI closed; a distinct one-shot check of the same path
subsequently received an exact ACK. The user explicitly accepted this operational
exception in #164. Do not rewrite the original result as 21/21. #161's external
stall origin remains unproven; mitigation is not root-cause repair. This is
historical v1.0.0 evidence, not a validation claim for the v1.0.2 changes.

The Python/PyPI version is `1.0.2`; the Git tag and GitHub release are `v1.0.2`.
This is a stable release: do not mark it prerelease, and make it GitHub Latest.
Normal package upgrades and standalone update notices may select v1.0.2 instead
of v1.0.1. The plugin manifest keeps its independent version. The default core
remains dependency-free on Python 3.9+; MCP needs Python 3.10+, and Relay
receiver/server use requires Unix or WSL and Python 3.11+. Package publication
does not guarantee hosted Relay/OAuth availability. A service-managed macOS or
Linux receiver needs the target TUI's `codex` executable directory on its PATH
or an operator-owned absolute `codexBin` binding. Relay login expires and can
require reauthorization. #161 remains open with root cause unconfirmed.

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

1. Confirm the v1.0.2 milestone's completed fixes and keep #161 open as
   monitoring with root cause unconfirmed. Review the runtime diff against
   v1.0.1 and the v1.0.2 notes; do not merge `release/0.9.x` into `main`.
2. Confirm `session_peer.__version__ == "1.0.2"`, generated `session_peer.py`
   matches its source, four README install commands agree, and four stable
   release notes are included in sdist. Run the complete local suite and the
   PR `release gate`; after merge, require a successful CI run on exact `main`.
3. Build wheel and sdist from the exact candidate with `python3 -m build`.
   Inspect contents and install each archive independently in clean environments.
   Check `session-peer --version`, JSON `list` against an initialized agent home,
   `pip check`, Relay/MCP extras and help smoke tests. An explicit empty Codex
   home must fail closed with `state_db_missing`; this is not an install failure.
   Do not submit live model messages for this gate.
4. Merge only after checks pass. Fetch `main`, record its exact commit, recheck
   version and release notes, and confirm PyPI has no `1.0.2` files yet.

## Prepare the draft

Create the draft only after the preparation PR is merged; a squash or merge
commit changes the release commit. Never move an existing published tag.

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v1.0.2 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.2" \
  --notes-file docs/releases/v1.0.2.md \
  --draft --latest
```

Verify tag, target, title, notes, draft status, stable status and Latest intent.
Draft creation does not authorize publication.

## Publish

Obtain final user approval immediately before publication. Publishing makes the
GitHub release public and starts the immutable PyPI upload:

```bash
gh release edit v1.0.2 \
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
and filenames are immutable. A partial `1.0.2` publication or hash mismatch stops
promotion; fix forward through reviewed changes and a new version (normally
`1.0.3`), not a moved tag or reused version. Yanking does not make reuse safe.

## Verify publication

1. Verify `publish.yml` succeeded for the exact tag and commit. Download both
   PyPI files, compare hashes with preserved workflow candidates and provenance,
   and install each independently from PyPI in fresh environments.
2. Repeat version, JSON `list` on an initialized agent home, Relay/MCP extras and `pip check`.
   Confirm GitHub says stable and Latest, and normal upgrade/update checks select
   v1.0.2. Verify hosted Relay separately; a queued message is not an ACK.
3. Record publication evidence before closing the v1.0.2 milestone. Keep #161
   open in its existing monitoring milestone; do not imply a root-cause fix. Fleet deployment
   or production service restarts require a separate operational decision.
