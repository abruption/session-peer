# session-peer documentation

English is the canonical source. Korean, Japanese and Simplified Chinese editions
mirror the same navigation and normative behavior. Start with the shortest guide
for your goal; protocol and validation records are review material, not parallel
installation paths.

## Users

- [CLI reference](cli-reference.md) covers local and SSH discovery, sending, JSON, updates and limits.
- [Diagnostics and replies](diagnostics.md) explains truthful submission states and safe troubleshooting.
- [Multiple Codex homes](multi-home-list.md), [explicit wake](wake.md) and [Antigravity](antigravity.md) cover optional agent workflows.

## AI-assisted setup and integrations

- [AI assistant guide](ai-assistant-guide.md) is the bounded handoff for an agent performing setup or verification.
- [MCP](mcp.md) and [agent adapters](agent-adapters.md) describe optional integrations and policy boundaries.

## Paired devices and operators

- [Paired devices](paired-devices.md) is the user path for direct or hosted end-to-end encrypted relay use.
- [Relay authentication](relay-auth.md), [lifecycle and recovery](relay-lifecycle.md), [watchdog](relay-watchdog.md), and [edge policy](relay-edge-policy.md) are operator references.
- [Deployment material](../deploy/README.md) separates reusable examples from the Abruption KR operational reference.

## Development and history

- [v1.3.0 release notes](releases/v1.3.0.md) describe the six merged features, supported combinations and release verification.

- [v1.2.1 preparation notes](releases/v1.2.1.md) record the 2026-10-19 patch candidate for Orca Claude discovery, skill metadata reading and the compatibility skill copy; publication remains separate.

- [v1.2.0 published record and historical preparation](releases/v1.2.0.md) record the 2026-10-16 publication separately from preparation started on 2026-10-15 and updated on 2026-10-16, the merged six-PR scope and remaining acceptance gates.

- [v1.1.2 historical preparation notes](releases/v1.1.2.md) describe #298 and the 2026-10-13 preparation; v1.1.2 was subsequently published. Do not reuse its version or commands.

- [v1.1.1 maintenance notes](releases/v1.1.1.md) cover the documentation/test maintenance target prepared on 2026-10-12; runtime behavior is unchanged from 1.1.0. Verify package publication separately.

- [Experimental handoff runtime](handoff-runtime.md) describes the limited private-receipt support shipped in 1.1.0, supported routes and remaining acceptance gates.
- [v1 compatibility contract](compatibility-v1.md) classifies stable, versioned, migrated, internal and experimental surfaces.
- [Agent transport architecture](architecture/agent-transports.md) and the [relay development plan](relay-development-plan.md) explain implementation boundaries.
- [v1.1.0 release notes](releases/v1.1.0.md) preserve the published 1.1.0 evidence, changes and partial support boundaries.
- [v1.0.4 notes](releases/v1.0.4.md) describe the prior maintenance release dated 2026-10-07; [v1.0.3 notes](releases/v1.0.3.md) preserve the prior security release history; [validation records](validation/69-rc.md) preserve scoped evidence and limitations.
- The completed relay69 prototype source was removed after its unique regressions moved to the product relay suite. Git history remains the source for obsolete prototype code.
