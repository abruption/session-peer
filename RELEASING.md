# Releasing session-peer

Version 1.1.0 is an unpublished candidate prepared on 2026-10-09; the current published stable release remains 1.0.4. Preparation-only authorization stops before tags, drafts, workflow dispatch or publication; an explicit instruction to complete this release authorizes those publication steps, not the required human PyPI environment review or operational deployment. Keep preparation, immutable GitHub publication, the human PyPI environment review and post-publication verification distinct. Protected main requires reviewed, up-to-date PRs and the aggregate release gate, including Python platform matrices, documentation, shell, package/standalone/MCP/Relay/Control tests, integrations and Python/Node dependency audits.

## Historical evidence and current boundaries

The five-host v1.0.0 RC4 rc4-rerun-02 campaign ran for 14,436.65 seconds: complete record, public health 241/241, probes 147/147, submissions 21/21 and Relay restart recovery in 3.182 seconds. Independent ACKs were 20/21. T120 Windows native Claude had no confirmed original ACK because its TUI closed; a distinct one-shot check later received an exact ACK. The owner accepted this exception in #164. Keep 20/21 unchanged; this historical evidence does not validate v1.0.4 or v1.1.0. #161 remains open with the external stall root cause unconfirmed.

The Python/PyPI candidate version is 1.1.0; the planned tag and GitHub release are v1.1.0, neither created by preparation. Make it stable and Latest only after authorized publication. The plugin version remains independent. Core requires Python 3.9+, MCP 3.10+, Relay receiver/server Unix or WSL and Python 3.11+. Service receivers need Codex on their service PATH or an operator-owned codexBin binding. Package publication does not establish hosted remediation, fleet installation, production restarts, live OAuth health or agent ACKs. Unknown outcomes never authorize automatic resend.

## Source and configuration gates

1. Review the v1.1.0 candidate against published 1.0.4 and all four release notes. PR #261 and feature PRs #283–#290 must merge through normal protections before the preparation PR. Rebase preparation onto that integrated main, preserve both parser protections and frozen contract bytes, and reassess #180/#181/#268 unsupported gates and companion skill PR #30. Preserve published v1.0.3 security history and skill 0.3.2/minimum 0.9.1/full 1.0.1. Check package/generated versions, four README published/candidate distinctions and archives; keep legacy cc_peer.py frozen and excluded. Exclude credentials, keys, databases, replay state, browser profiles, local evidence and chats.
2. Run the complete local suite and PR release gate. Require successful CI on exact integrated public main after merge; private advisory fork checks are not a substitute for that public release gate. Validate clean wheel/sdist installs, isolated installed imports, exact CLI version, initialized-home JSON list, extras and pip check. An explicit empty Codex home must fail closed with state_db_missing. Do not submit live messages for this gate.
3. Verify PyPI has no 1.1.0 files. The 2026-10-07 preparation check returned HTTP 404 for the historical 1.0.4 version JSON. Verify GitHub Immutable Releases and the v* tag ruleset: creation allowed, tag update/deletion blocked with no bypass. The owner enabled these on 2026-10-03 (ruleset 24408525); the 2026-10-05 check confirmed the strict main release gate. The 2026-10-07 GitHub API check reconfirmed Immutable Releases enabled and ruleset 24408525 active, covering refs/tags/v* with update/deletion blocked and no bypass. Historical v1.0.2 was nonimmutable with no assets and is not a verified standalone release; recheck current settings before publication.
4. Verify the Trusted Publisher maps session-peer to abruption/session-peer, publish.yml and pypi. A signed-in PyPI browser inspection on 2026-10-05 verified that mapping; it is historical evidence, not a new PyPI browser verification. The 2026-10-07 GitHub API check reconfirmed required reviewer `abruption`, self-review allowed (`prevent_self_review: false`) and `v*` tags accepted. Administrator bypass was enabled at the 2026-10-05 check (`can_admins_bypass: true`); do not treat that historical observation as a new bypass-policy check. The owner's earlier [2026-09-29 mapping check](https://github.com/abruption/session-peer/issues/235#issuecomment-5882178667) is historical evidence too. Recheck settings, use normal human review and never silently bypass it.

## Prepare the immutable draft

After the preparation PR is merged, record the exact main commit and create a lightweight tag at it. Never move an existing tag. Run preparation as the repository owner on protected main at that exact commit; a main advance between dispatch and verification fails closed.

```bash
git fetch origin main --tags
release_tag=v1.1.0
release_commit=$(git rev-parse origin/main)
git tag "$release_tag" "$release_commit"
git push origin "$release_tag"
gh release create "$release_tag" --repo abruption/session-peer \
  --target "$release_commit" --title "session-peer $release_tag" \
  --notes-file "docs/releases/$release_tag.md" --draft --latest
gh workflow run prepare-release.yml --repo abruption/session-peer \
  --ref main -f tag="$release_tag"
```

prepare-release.yml verifies source/ref/version/ancestry, builds twice reproducibly, inspects archives, tests isolated installations and audits dependencies. It attests and attaches exactly seven assets to an empty draft: wheel, sdist, session_peer.py, install.sh, SKILL.md, SHA256SUMS and release-provenance.json. The manifest covers five payloads; signed provenance covers the manifest and evidence too. No existing asset is overwritten. Review the successful preparation run, exact commit, seven files, hashes and attestations before publication. Draft attachment does not publish.

## Publish the locked GitHub release

Publish only with the owner's explicit authorization for this version. An existing instruction to complete this release satisfies the procedural approval requirement; do not demand a second confirmation solely because of this runbook. It does not replace the required human pypi environment review. Publishing locks the tag and assets and starts publish.yml.

```bash
gh release edit v1.1.0 --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

publish.yml requires the repository owner, verifies exact tag/source/main ancestry, downloads the locked immutable assets and verifies their authenticated provenance and manifest. It never rebuilds or adds assets. Package installation checks and current dependency audits must pass again before the PyPI job. Preparation-time audit success is not current audit evidence.

## Human review of the pending PyPI deployment

1. Observe the exact Actions run waiting on pypi before any upload. Record run URL/ID and attempt, tag, commit, SHA256SUMS, release-provenance.json and pending time. Source tests and repository settings cannot prove this pause; observing the next release remains the #235 acceptance check.
2. The required human reviewer checks the candidate evidence and current Trusted Publisher/environment settings. In **Review deployments**, select **pypi** and explicitly choose **Approve and deploy** only when authorized. GitHub publication approval does not replace this review. When the deployment is pending, request the required human review and keep the environment gate intact.
3. To refuse upload, select **pypi**, explain the reason and choose **Reject**. If the expected pause or controls are absent, stop and cancel before upload. Preserve the rejected/cancelled run and resolve the cause; do not move the tag or reuse the version to evade rejection.
4. Record reviewer, decision, comment, timestamp and result. Retain upload and verification evidence. Rejection is neither successful publication nor successful approval-pause validation. Administrator bypass is exceptional and requires separate explicit owner authorization with recorded reason, actor, time, run, tag and commit.

## Verify publication or recover

Verify publish.yml and its PyPI verification succeeded for the exact tag/commit. Download both PyPI files, compare the exact file set and hashes with locked candidates/provenance, and install each independently in fresh environments. Recheck isolated version, JSON list on an initialized home, extras and pip check. Confirm stable/Latest and normal update selection of v1.1.0. Record evidence before closing the milestone; retain #161 as monitoring.

GitHub and PyPI publication are separate irreversible steps. An audit failure after GitHub publication can leave a locked release without PyPI files; preserve both runs and exact assets. Do not bypass audits, rerun uploads with modified artifacts, skip existing files or reuse versions. A partial 1.1.0 upload or mismatch stops promotion. Diagnose the first failed gate and fix forward through reviewed changes and a new version, normally 1.1.1. Yanking does not permit reuse.

## Verified standalone installation

A recent authenticated GitHub CLI must support gh attestation verify and signer workflow, source ref/digest, OIDC issuer and hosted-runner policy. The tested baseline is 2.102.0; the earliest version supporting all flags is unestablished. Repository/attestation read access suffices; publication permission is unnecessary. [GitHub CLI verifier source](https://github.com/cli/cli/blob/v2.102.0/pkg/cmd/attestation/verify/verify.go) documents the policy flags. Local fixtures prove policy/order/error behavior, not live signature acceptance.

The installer defaults to verified Latest immutable assets. --local-source explicitly trusts adjacent source; --main opts into unverified development source. Missing attestations or old unsigned releases fail closed; use pipx/uv/pip when verification is unavailable. Authenticate install.sh before execution:

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

Downloads are capped at 8 MiB for standalone, 256 KiB for support files and 1 MiB for metadata. Authenticated manifest/provenance, exact tag/version and a staged --version check precede replacement. The sender verifies before SSH deployment; offline destinations need Python only. Verification failure leaves existing files untouched. Review the release notes for the SSH option allowlist, legacy pairing-binding review and Control login-session migration.
