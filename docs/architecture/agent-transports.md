# ADR: internal agent and execution transport contracts

Status: accepted for the post-v0.8 refactor (#47). This is an internal source
contract, not a public external-plugin ABI. The package version remains 0.8.0
until a separately prepared release.

## Decision

Keep the dependency-free `session_peer.py` standalone artifact and define the
contracts in that file. SSH streams its source to destination-side `python3 -`;
ordinary remote operations still require no installed session-peer service or
package. Splitting the runtime into importable files now would require a bundle
builder, remote module installation, or a second distribution mechanism. None is
needed to validate the agent/transport boundary.

An agent owns native identity, discovery, validation, submission, diagnosis,
agent-specific command options, and presentation. A transport owns where those
operations execute. `LocalTransport` invokes the registered adapter;
`SshTransport` resolves the destination and invokes the existing safely quoted,
single-source SSH protocol. The receiver parses the same CLI and invokes its
local adapter. SSH is not an agent.

The initial registry explicitly contains Claude followed by Codex. CLI choices,
listing, sends, doctor, Reply-To validation and MCP agent policy use that registry.
MCP remains a policy-enforcing subprocess client of the CLI; registration never
grants send/wake permission. Update deployment is still distinct from agent
submission.

## Evidence and compatibility

- Claude discovery produces PID/name/inbox evidence and posts to a native socket.
  A completed write is not proof of consumption.
- Codex uses native queue and app-server interfaces. One UUID can occur in
  multiple homes, so identity preserves host and home rather than collapsing by
  UUID. Multi-home inventory, ambiguity checks and active-writer validation remain
  within the Codex implementation. Caller-side defaults are not evidence about a
  remote receiver's active home.
- Native queue acceptance may precede a failed wake. Preserve the native payload,
  including queue ID, submission and wake status; never automatically retry.
- Wake is optional and remains constrained to the previously verified runtime
  and lifecycle. Wait and acknowledgement are unsupported by both adapters.
- Host identity, sender envelopes and return-route normalization are independent
  of the agent. Construct the message envelope once at the sender and transmit
  its existing base64 representation over SSH.

Existing options, wire fields, response envelope schema version, ordering and
exit codes remain unchanged. The additive exception is
`doctor.capabilities.agents`, mapping registered names to boolean `list`, `send`,
`wake`, `wait`, and `ack` support. These describe implemented mechanisms, not
current credentials, inbox availability, model readiness or destination
permission. `doctor.capabilities.replyObservation` retains its prior meaning.

Remote list partial failures also accept `not_installed` discovery status;
otherwise a missing optional Codex install could discard another agent's
failure diagnostics. A failed remote submission with `submitted: true` likewise
retains its native result instead of discarding its ID. A Reply-To cannot claim one agent while targeting a
registered prefix for another.

## Contract and trust boundary

`ADAPTER_CONTRACT_VERSION = 1` is independent of JSON response schemaVersion.
The registry validates names, exact contract version, capabilities and methods
before registration; duplicates are rejected. `SessionIdentity` records agent,
host, identifier and optional Codex home. `ExecutionContext` provides destination
identity and parsed options. These are process-local values, not a new wire
protocol. Discovery and submission retain typed dictionary contracts so native
result fields are not flattened away.

`AdapterError` derives from the existing CLI error and adds agent/reason fields.
Contract errors use `invalid_adapter_contract`, `duplicate_agent`, `unknown_agent`,
`unsupported_capability`, or `invalid_target`. Malformed discovery and diagnosis
use `invalid_adapter_result`. Unexpected operation exceptions are contained as
`adapter_failed`, without echoing exception text. Unexpected submission errors
or malformed submission results become `outcome_unknown` with no retry, because
native submission might already have happened. Existing intentional CLI/native
errors and their structured details remain intact.

Discovery validates each adapter's result before aggregation. One adapter's
failure must not discard successful rows or diagnostics from another. No adapter
is allowed to claim consumption merely because its transport returned.

There is no entry-point discovery, import-by-name, plugin directory scan, or
message-driven loading. A name in a message, CLI argument, URI or MCP policy
cannot cause code installation or execution. Unknown explicit agents fail;
unregistered prefixes in ordinary target strings remain literal Claude names
for compatibility. The `claude:` prefix is likewise still part of a literal
Claude name; Codex and newly registered adapters use their registered prefixes.

Future external plugins require a separate design: explicit operator installation
and allowlisting, package ownership and dependency isolation, version negotiation,
error containment and documentation of the fact that in-process Python plugins
execute trusted code. This change supplies no sandbox or external loading flag.

## Validation

`tests/test_adapters.py` exercises a common Claude/Codex/fixture contract, third
agent CLI and Reply-To routing, capabilities, incompatible registrations,
malformed results, exception containment, MCP policy and native submission counts.
A source-registered fixture is inserted only into a test copy of the streamed
program and executed in a fresh Python subprocess through the existing SSH
serializer. No production dispatch edits, external plugin loader, live model
account, SSH connection or message delivery are needed for that test.

Existing transport, native socket, queue, multi-home, reply, MCP and wake suites
remain the compatibility baseline. Package and standalone installation tests
ensure the single-file and optional-extra distribution boundaries remain intact.
