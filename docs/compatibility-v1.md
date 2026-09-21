# v1 compatibility contract

This document defines the interfaces that session-peer intends to keep compatible
from 1.0.0 onward. It describes package behavior, not the availability of the
hosted relay. The machine-readable fixtures in `tests/fixtures/compatibility-v1.json`
are the executable companion to this policy.

## Compatibility tiers

| Tier | Meaning |
| --- | --- |
| Stable | Existing valid input and required output meaning remain compatible throughout v1. Fields may be added where stated. |
| Versioned | Incompatible changes require a new explicit version. Old versions remain readable for the documented migration window. |
| Migrated | Persistent data changes only through an explicit, versioned migration. Normal startup never rewrites an old schema. |
| Operator internal | The format is validated and recoverable, but only the shipped tools may edit it. It is not a user-authored API. |
| Experimental | A release may change or remove the surface after release notes and migration guidance. |

“Supported” means CI and documented production paths are maintained. “Tested”
names an environment exercised by release evidence. “Best effort” has bounded
diagnostics but no release gate. “Experimental” carries no v1 compatibility
promise until promoted here.

## CLI and machine-readable results

Commands, documented options, option precedence and exit meanings are stable.
Exit `0` means the requested command completed according to its documented
submission semantics, `1` is a command or transport failure, and `2` is either
argparse usage failure or no matching target where documented. Human prose,
spacing, ordering and terminal decoration are not frozen.

JSON schema version 1 is stable and additive. Each command result keeps
`schemaVersion`, `ok`, `host` and `command` with their current types. A single
destination remains one object; repeated destinations remain an array of those
objects. Consumers must ignore unknown fields. Required fields cannot disappear
or change type inside v1. Submission fields never imply agent consumption or a
reply unless an explicit acknowledgement field says so. See the [CLI reference](cli-reference.md).

## Reply addresses, MCP and policy

`session-peer://v1/reply` is versioned. Its fields are inert data parsed by the
production URI parser; unknown, duplicate or unsafe fields fail closed. An
incompatible address requires a new URI authority version.

MCP tool results reuse the CLI JSON result as `structuredContent`; additive CLI
fields are therefore additive MCP fields. MCP policy `schemaVersion: 1` and relay
receiver policy are stable, strict allowlists. Unknown policy keys are rejected.
Adding a policy capability requires documentation and remains denied until an
operator opts in. See [MCP](mcp.md) and [paired devices](paired-devices.md).

## Device state, backup and operation receipts

Device state and backup manifests are versioned operator-managed data. Users may
move them only through shipped backup, restore and rotation commands. Backup
manifest schema 1, stable device principals, key generations, revocation
tombstones and durable operation receipts cannot be silently renumbered,
reinterpreted or discarded. An incompatible change requires a new manifest or
database schema plus an explicit migration and recovery fence.

Control and replay databases, public-state snapshots, spent-ticket files and
revision high-water records are operator internal. Their invariants are stable;
their table and JSON layout is not a user-editable public API. Use the shipped
migration and recovery procedures described in [relay lifecycle](relay-lifecycle.md).

## Relay and endpoint protocol

Endpoint TLS framing, pairing messages and relay/control HTTP shapes are
version-negotiated. The current endpoint application protocol is
`session-peer-device-v1`; control public state and replay state use
`schemaVersion: 1`. Unknown versions fail closed. The blind relay must not gain
plaintext access, and OAuth or relay admission must not replace endpoint pinning
or receiver policy.

Hosted limits, service availability, OAuth-provider policy, edge rules and the
operator dashboard are deployment behavior. They are not part of the PyPI v1
availability promise. Security boundaries and persisted rollback protection
remain release gates even when their operator configuration changes.

## Support matrix

| Surface | Supported boundary for v1 | Level |
| --- | --- | --- |
| Core CLI | Python 3.9+, macOS, Linux and native Windows | Supported |
| MCP adapter | Python 3.10+, macOS and Linux; Windows where the MCP runtime supports stdio | Supported |
| Paired receiver and relay | Python 3.11+, Unix; Windows endpoints use the documented WSL boundary | Supported after the WSL beta gate |
| Control service | Node 22 and 24 on Linux arm64/x64 | Supported |
| Claude Code | Native inbox contract exercised by CI and release validation | Tested; upstream private schemas are not promised |
| Codex | Saved-thread discovery and `codex queue` contract exercised by CI | Tested; undocumented database variants are best effort |
| Antigravity | Explicit bridge protocol | Experimental until promoted in a later contract revision |

A one-time successful run on another operating system or agent version is
evidence, not an indefinite support promise. Release notes must state newly
tested versions and any reduced coverage.

## Change and deprecation rules

Stable surfaces change additively during v1. A removal, type change, semantic
reuse or stricter rejection of formerly valid public input requires either a new
versioned surface or the next major release. Deprecations are documented in
release notes for at least one minor release before removal unless continuing
the behavior would be unsafe.

Persistent formats use explicit migrations with preflight, backup and
post-migration verification. Experimental surfaces may change in a prerelease,
but the release notes must name the change and its replacement. The source
modularization tracked by [#112](https://github.com/abruption/session-peer/issues/112)
must preserve these fixtures and the generated standalone CLI behavior.

## Release checklist

Every release identifies contract additions, deprecations and migrations. CI
validates required JSON fields and types, exit meanings, URI and policy parsing,
backup invariants and relay protocol version markers. A passing fixture allows
documented additive fields; it does not turn internal storage into a public API.
