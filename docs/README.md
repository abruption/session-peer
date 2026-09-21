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

- [v1 compatibility contract](compatibility-v1.md) classifies stable, versioned, migrated, internal and experimental surfaces.
- [Agent transport architecture](architecture/agent-transports.md) and the [relay development plan](relay-development-plan.md) explain implementation boundaries.
- [Release notes](releases/v1.0.0-alpha.1.md) describe published behavior; [validation records](validation/69-rc.md) preserve scoped evidence and limitations.
- The completed relay69 prototype source was removed after its unique regressions moved to the product relay suite. Git history remains the source for obsolete prototype code.
