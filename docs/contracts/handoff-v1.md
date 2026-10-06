# Handoff v1 contract — design proposal v0.2

## Status and provenance

This is an unimplemented design for Python #181 and the TypeScript 0.4.0 design review. It is not a frozen protocol, a release promise, or evidence of live ACK support. Merge of this document does not authorize runtime implementation, publication, native submissions, or operational changes. The fixture contains synthetic examples, not recorded deliveries.

The published Python reference is [v1.0.3](https://github.com/abruption/session-peer/tree/0d252550ab40c26d1ac4a19193df6ca2f84d830b). The ordinary output source is [adapters](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/adapters.py), [Codex](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/codex.py), [SSH](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/ssh.py), and [output](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/output.py). The [shared fixture](https://github.com/abruption/session-peer/blob/main/tests/fixtures/handoff-v1.json) separates normalized legacy examples from proposed opt-in examples. Runtime reference and design fixture pins are separate: TypeScript's published historical reference is not silently changed to an unshipped Python version.

## Evidence and compatibility

Submission is acceptance by the native transport; delivery is evidence that the exact original user-message ID was injected into the exact original target generation. Acknowledgement is an explicit correlated receipt, not completion, responsibility acceptance, or proof that the model read every byte. Queue deletion, process exit, turn completion, reply silence and a successful status query are not ACKs. Unknown native turn states never become completed.

Ordinary send output stays runtime-specific. Python Claude success omits status, submitted and consumptionConfirmed; Codex queued success includes submitted true and consumptionConfirmed false. Legacy unknown with submitted false is not universal no-effect proof. Do not add missing false/null fields, reinterpret optional absence, overwrite consumptionConfirmed, or change ordinary exits. Normalized fixture values hide identities only; each example records provenance and is not an exhaustive output schema.

Opt-in adds one handoff object to each destination result under the existing outer schemaVersion 1. There is no fanout-level handoff. Explicit waiting can change outer ok and exit only: it preserves the native status, target, queueId, submitted, consumptionConfirmed and all independently valid submission evidence. Best-effort observation failure cannot change native submission success. Invalid handoff data cannot erase valid native evidence or promote an ACK; an explicit waiting request fails validation without resubmitting.

## Public schema

The following grammar is normative for this proposal. All objects are closed except the runtime-specific outer envelope. A question mark means optional and absent when unavailable; nullable fields are explicit below. Conditional rules follow the grammar.

```text
handoff.schemaVersion = 1
handoff.correlationId = UUID-v4 lowercase canonical
handoff.ledgerEpoch = UUID-v4 lowercase canonical
handoff.state = validated | refused | submitted | delivered | acknowledged | unknown | timed_out_unknown
handoff.submission.status = not_attempted | submitted | refused | unknown
handoff.observation.status = not_requested | pending | observed | unsupported | failed
handoff.observation.injectionObserved = boolean
handoff.observation.clientUserMessageId? = safe-id
handoff.observation.turn? = {id: safe-id, status: running | completed | failed | interrupted | unknown}
handoff.ack.status = not_requested | pending | acknowledged | unsupported
handoff.ack.assurance? = token_possession | operator_confirmed
handoff.ack.receivedAtUtcMs? = safe-integer
handoff.ack.late? = boolean
handoff.wait.for = none | delivered | acknowledged
handoff.wait.status = not_requested | pending | satisfied | timed_out_unknown | stopped | unsupported | failed
handoff.wait.operationId? = UUID-v4 lowercase canonical
handoff.wait.deadlineAtUtcMs? = safe-integer
handoff.wait.reason? = insufficient_budget | deadline_before_effect | evidence_unsupported | evidence_failed | history_unavailable | stopped_by_operator | invalid_handoff
handoff.targetGeneration = safe-generation | null
handoff.decisionOwner = sender_operator
handoff.retry = {allowed: false, reason: receiver_dedup_unavailable}
handoff.nextActions = unique subset of [keep_waiting, reconcile, stop_waiting]
```

Delivery requires observed injection plus an exact clientUserMessageId and non-null original targetGeneration. Turn evidence requires observed injection; a turn is separate from receipt state. Receipt acceptance does not manufacture injection evidence. An acknowledged state requires acknowledged ack with assurance, receipt time and late flag; other ACK statuses omit those fields. Submitted, delivered and acknowledged states require submitted submission. Validated requires not_attempted; refused requires refused; unknown requires unknown. Timed-out state permits submitted or unknown, never refused/not_attempted.

Each explicit wait has an operationId and deadline, even pre-effect refusal. No-wait records have neither. Satisfied delivered waits require injection evidence; satisfied acknowledged waits require valid ACK. Stopped/failed/unsupported waits preserve known effect evidence. nextActions depend on a live validated channel and retained history: unsupported or expired channels never offer keep_waiting. stop_waiting ends observation only; it does not cancel native work. All native local/SSH results forbid retry. No resend_same_id action exists in v1; correlation and user approval alone do not establish safe resend. Receiver dedup (#182) is not a prerequisite for implementing this no-resend contract.

## State and exit tuples

Absent means a legacy field remains absent. Native denotes an unchanged per-runtime snapshot. The same table applies to local and SSH, not to an unimplemented paired-device transport.

| Mode / evidence | state | submission | wait status | outer status / submitted | ok / exit |
| --- | --- | --- | --- | --- | --- |
| Ordinary send | absent | absent | absent | native / native or absent | native |
| Opt-in dry-run | validated | not_attempted | not_requested | native / native or absent | true / 0 |
| Required channel unavailable before effect | refused | refused | unsupported | native if present / no synthetic field | false / 1 |
| Budget exhausted definitely before effect | refused | refused | failed | native if present / no synthetic field | false / 1 |
| Known queued, best-effort observer fails | submitted | submitted | not_requested | queued / true | true / 0 |
| Known queued, explicit ACK deadline expires | timed_out_unknown | submitted | timed_out_unknown | queued / true | false / 1 |
| Injection known, ACK deadline expires | timed_out_unknown | submitted | timed_out_unknown | native / native or absent | false / 1 |
| Effect may have occurred, no receipt | unknown | unknown | not_requested | native / native or absent | false / 1 |
| Valid receipt satisfies explicit wait | acknowledged | submitted | satisfied | native / native or absent | true / 0 |
| Successful status query of prior timeout | timed_out_unknown | submitted | timed_out_unknown | absent / absent | true / 0 |

Invalid flags, invalid timeout lexemes, missing targets and malformed IDs retain usage/no-target exit 2 and may have no JSON/handoff at all. No synthetic correlation ID or legacy false/null is invented for such failures. Interrupt uses exit 130 without cancel/resend. A successful status query reports query success, not acknowledgement.

## Capabilities and bootstrap

Every capability is a future acceptance gate, not current product support. A route must validate the receipt consumer, producer and target generation independently before advertising ACK support. A failed bootstrap is unsupported, not permission to try generic message delivery.

| Route / observer | injection observation | receipt ACK |
| --- | --- | --- |
| Same-machine private collector plus compatible producer | Codex only after version/home/writer/ID validation | supported after private bootstrap |
| Explicitly trusted reverse SSH to installed compatible receipt handler | separately validated Codex route | supported after handler/configuration validation |
| Source-streamed SSH without compatible handler installation | separately validated Codex route | unsupported |
| Claude native observer | unsupported by default | compatible explicit receipt producer only |
| Paired device, Relay, Side Session, wake | outside initial route scope | unsupported |

Required delivered or acknowledged wait refuses before effect when its channel is unsupported. Best-effort correlated send may submit with observation/ack unsupported, without minting an unused secret capability. No collector calls delivery, wake, model prompts or approvals. Native app-server fallback to the queue is allowed only before the original native submission may have begun; post-attempt ambiguity and observer failures never trigger another submission. Version, platform, home and original writer identity checks are mandatory. No transcripts or arbitrary reply bodies are scanned.

## Receipt wire and lifecycle

Receipt v1 is separate from Reply-To v1, whose parser and permissions are unchanged. A receipt handle is a non-secret local selector, not a URI or authority. The actual bearer capability travels only through authorized private effect input and private handler stdin, never argv, URI, ordinary JSON, environment, logs or raw ledger persistence.

```json
{
  "schemaVersion": 1,
  "kind": "receipt",
  "ledgerEpoch": "11111111-1111-4111-8111-111111111111",
  "correlationId": "22222222-2222-4222-8222-222222222222",
  "targetGeneration": "fixture-generation",
  "receiptId": "33333333-3333-4333-8333-333333333333",
  "capability": "<PRIVATE_INPUT_ONLY>"
}
```

The capability is 32 cryptographically random bytes encoded as 43 unpadded base64url characters. The example placeholder is not valid wire input. The protected collector stores only a SHA-256 capability hash bound to epoch, correlation and original generation; constant-time verification and atomic first-receipt commit are required. Duplicate receipt IDs for that binding are idempotent; wrong IDs, stale generations, conflicting receipts, expired capabilities and invalid frames cannot advance state. ACK arrival time is collector-assigned; caller timestamps are not authority.

The collector is a user-owned process independent of the sender conversation. Files/directories are private 0600/0700; endpoints are local owner-checked private IPC or an explicitly configured trusted reverse SSH handler. No public listener, auto SSH key installation, profile changes, transcript reading, secret export or generic CLI exec is permitted. Restart recovers committed receipt hashes and receipts; lost raw capabilities are never regenerated for an attempted intent. Capability lifetime is 24 hours from intent commit and ends with detail expiry, revocation, quarantine or first valid receipt. Duplicates of an accepted receipt return its stored result even after capability expiry, only while receipt detail exists.

Manual producer is the proposed no-submission handoff confirm operation. It requires the exact epoch/ID/generation and a local sender-operator assertion of an observed explicit correlated reply; stdin receives metadata only, not transcript/body. It records operator_confirmed, never token_possession. The record is an operator attestation, not independently verified model identity. The token-possession producer must be an installed compatible receipt-only handler reading private input; it cannot execute arbitrary commands. Both producers remain implementation acceptance gates. No assurance is advertised until its producer is validated.

## Sender ledger, freshness and retention

A single private, serialized durable ledger owns a random epoch. Its target-bound prepared intent is committed and synced before effect; once an effect-intent fence is committed, only one native attempt is authorized in that intact epoch. Crash after that commit, including a crash before effect actually starts, recovers as unknown and never submits again. Binding includes agent, destination, home/writer identity, generation and a protected internal payload digest; the digest is not public output. Conflict or target restart never silently rebinds the intent.

Fresh IDs are generated and reserved by automatic preparation or by the new no-effect handoff prepare operation. Caller-supplied unknown UUIDs are refused before effect, because freshness cannot be proved. A supplied known prepared ID must match its exact binding and be unattempted. A supplied attempted ID is query/reconcile only, never another send. Ordered fanout generates and durably associates one intent per destination once; callers cannot reuse one ID for multiple destinations. Reconciliation never regenerates IDs or capabilities.

Limits per epoch are 10,000 retained intent/fence records and a 32 MiB journal, whichever fills first. Admission reserves bounded storage for terminal records and one receipt before effect, rather than filling capacity after submission. No fence eviction/LRU is allowed. Detail retention is 30 days from preparation, capability lifetime 24 hours, maximum 64 waits per intent; expired detail becomes a compact target-bound fence tombstone retained for the entire epoch. Tombstones count toward quota. wait quota exhaustion refuses a new wait without changing native effect facts. Pruning details never restores submission authority; quota exhaustion refuses preparation/effect until explicit operator archival, not automatic reset.

Missing, corrupt, expired-detail or known-restored history yields unknown for status/reconcile, with retry forbidden. An existing ledger is never recreated automatically; first use requires explicit local initialization and a fresh epoch. Known restoration quarantines all old intents, disabling effects and receipt acceptance until reconciliation of retained evidence. New epochs require explicit operator initialization and generated fresh IDs; they make no claim about old requests. No local-only design can reliably detect an unmarked rollback or cross-machine ledger clone: fencing guarantees are limited to proven intact, retained, non-rolled-back history. External monotonic anchors/clone-proof storage are outside v1; this limitation must remain visible, not hidden behind a universal exactly-once claim.

## Wait history and late receipts

Each wait has a distinct operation ID, goal, monotonic deadline and immutable terminal result. Status returns the most recently started wait for that intent (serialized sequence order), or not_requested if none; a future separate wait-history API is not implied. Current receipt/state can advance independently. Thus a late ACK can set current state to acknowledged while the returned originating wait remains timed_out_unknown. It never rewrites that wait to satisfied.

A receipt is late if accepted after the originating send wait's observation deadline; if there was no send wait, compare with the earliest explicit wait. With no wait, late is false. A later wait can be satisfied by an already accepted late receipt; the ack late flag remains true. Receipt acceptance and deadline transitions are serialized against the same monotonic clock while active. On recovery, receipt timing whose ordering cannot be proved is not assigned a synthetic late flag or acknowledged state; retain it as unclassified pending evidence until operator confirmation establishes a new attestation. UTC timestamps are diagnostics only. Repeated waiting makes no new native submission.

## Budgets and bounds

Default budget is 30 seconds per destination; CLI accepts only ASCII decimal integers 1 through 60 without leading zeros, signs, whitespace, decimal points or exponents. New flags do not change legacy parsing. The total monotonic budget starts before setup, preflight, preparation, effect and observation. Reserve exactly 5 seconds within it for cleanup; budgets at or below 5 seconds refuse before effect with insufficient_budget. Observation/effect cutoff is start plus budget minus 5 seconds; cleanup cannot extend start plus budget. A wait deadline diagnostic describes this cutoff, not a renewed remote budget.

SSH passes only remaining duration and keeps the original caller deadline; remote handlers cannot reset the budget or use UTC to authorize effect. If the remaining total budget is at or below cleanup reserve, refuse before effect. At the cutoff boundary use now >= cutoff as expired; a receipt committed strictly before cutoff may satisfy that wait, one at/after cutoff is late. Once effect may occur, timeout is unknown; no retry/fallback or new submission is allowed. Ordered fanout gives each destination its own bounded budget, not one host's repeated budget. Implementations that cannot guarantee bounded cleanup/owned resources cannot advertise that route.

```text
safe-integer = JSON integer token, 0..9007199254740991; booleans/fractions/exponents rejected
safe-id = 1..128 UTF-8 bytes, no U+0000..001F or U+007F..009F, valid Unicode scalars
safe-generation = 1..256 UTF-8 bytes, same control/scalar rule
receipt frame = one strict UTF-8 JSON object, at most 4096 bytes
public handoff frame = at most 8192 UTF-8 bytes
duplicate JSON keys, unknown nested keys, NaN/Infinity and trailing data rejected
turn/native IDs are opaque; only correlation/epoch/wait/receipt IDs use UUID-v4 syntax
```

JSON number tokens must be validated before lossy parsing; lexical 1.0 and 1e0 are rejected even if a JavaScript Number equals 1. Safe integer and exact boolean rules apply to the new schema only, not historical outputs. Bounds are checked before persistence, not after truncation. Ordinary stdout/logs never include capabilities, message bodies, transcript content or payload digests. Bounded metadata observation must not hide a body-returning API behind output filtering.

## Proposed CLI and zero-submit operations

These are proposed spellings, not commands available in published Python. Preparation binds the same target/message input as send without submission; confirmation accepts metadata-only private stdin. Explicit local ledger initialization is a separate opt-in setup prerequisite, never an automatic recovery action.

```text
handoff init
handoff prepare --to TARGET --message-file PRIVATE_FILE
send --to TARGET --message-file PRIVATE_FILE --correlation-id PREPARED_UUID
send --to TARGET --request-ack
send --to TARGET --observe-delivery
send --to TARGET --wait-for delivered|acknowledged --wait-timeout SECONDS
handoff status --correlation-id UUID
handoff wait --correlation-id UUID --wait-for delivered|acknowledged --wait-timeout SECONDS
handoff confirm --receipt -
ack --receipt -
```

Without correlation-id, request-ack/observe-delivery/wait-for automatically reserve a fresh intent; otherwise ordinary send stays unchanged. A correlation-only send uses best-effort evidence and no explicit wait. Status, wait, confirm, ack, init and prepare make zero native submissions. Receipt selectors do not contain secrets. Confirmation stdin contains schemaVersion, ledgerEpoch, correlationId, targetGeneration and a caller assertion confirmed=true; it rejects extra fields/body/capability and records operator_confirmed only. Flag incompatibilities and unsupported route requirements are checked before durable effect intent. Remote setup and host options must follow existing SSH trust restrictions, not arbitrary receipt routing.

ACK evidence also requires a non-null original targetGeneration and submitted submission; once a valid receipt is accepted, current state is acknowledged. Observed injection always implies submitted submission. A supplied prepared ID must not belong to a prior real send invocation, including a terminal pre-effect refusal; dry-run never consumes that first-submission authority. Dry-run is incompatible with request-ack, observe-delivery and wait-for (usage exit 2); correlation-only dry-run uses an already prepared ID.

If a restarted collector cannot prove monotonic capability lifetime continuity, it expires the capability conservatively rather than extending its TTL or regenerating it. Valid committed receipts remain recoverable. For a new wait on an already attempted intent, insufficient budget fails only that wait and preserves submission/injection facts; it does not relabel the original intent refused. The reconcile action means status/evidence comparison, not a new submission or an implicit repair command.

## Freeze and implementation gates

This proposal requires TypeScript review of its exact commit and fixture before freezing. The new prepare/confirm spellings, ledgerEpoch and wait operationId fields, 5-second cleanup reserve, numeric token validation and restoration limitations are explicit v0.2 amendments, not already accepted or shipped capabilities.

The fixture must cover per-runtime optional absence, explicit wait timeout with queued true, wrong/duplicate/late ACK, wait history, restart, missing/restored/expired/full ledger, custom unknown IDs, deadline boundaries, malformed schemas and SSH preservation. Strict SSH opt-in validation must preserve a valid native snapshot even if handoff is rejected; no legacy Claude reconstruction or generic failure path may discard it. Complete responses survive transport timeout/nonzero exits only through the same strict parser; partial frames remain unknown.

Before implementation acceptance: validate producer bootstrap and collector ownership/restart, durable intent and capacity reservation, cleanup under each supported platform/version/home, metadata-only Codex observation, strict local/SSH tuples and zero-submit status/wait/ack/confirm operations. No native/live evidence is supplied by this design PR. Side Session and wake experiments are separate future work, not prerequisites. Paired-device/Relay dedup and operator monitoring are not silently added to v1.
