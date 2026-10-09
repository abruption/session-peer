# Handoff runtime candidate

This is the unreleased implementation candidate for [#181](https://github.com/abruption/session-peer/issues/181), not a feature in published Python v1.0.4. The [frozen Handoff v1 design](contracts/handoff-v1.md) and its synthetic fixture are unchanged. This candidate does not complete every design acceptance gate.

## Supported candidate route

Same-machine POSIX Claude inbox submission can use an explicitly initialized, user-owned ledger and a separate private receipt collector. The connected inbox PID, original process birth and registry endpoint must match the selected generation. No model/session is started. Codex body-free injection observation, Windows bounded pipes, paired devices and reverse-SSH receipt bootstrap remain unsupported in this candidate. Opt-in sending over those routes refuses before native effect; ordinary opt-out local/SSH behavior is unchanged. The Codex wake version gate is unchanged.

```sh
session-peer handoff init --json
session-peer handoff prepare --to worker --message-file ./private-message.txt --json
session-peer send --to worker --message-file ./private-message.txt --correlation-id PREPARED_UUID --request-ack --wait-for acknowledged --wait-timeout 30 --json
session-peer handoff status --correlation-id PREPARED_UUID --json
session-peer handoff wait --correlation-id PREPARED_UUID --wait-for acknowledged --wait-timeout 30 --json
session-peer ack --receipt - --json
session-peer handoff confirm --receipt - --json
```

The message file must be a private, owner-only regular UTF-8 file. Use a prepared ID returned by the second command, not the literal placeholder. ACK/confirmation JSON enters only through private stdin. A cooperating recipient chooses whether to submit the delegated receipt under its normal permissions. Receipt authority is not approval to run other tools, send messages, wake a model or read a transcript. No automatic response is inferred.

## Evidence, privacy and timing

A complete inbox write is submission, not consumption or turn completion. Only an authenticated correlated receipt, or a separate explicit operator attestation with provable ordering, produces acknowledged. An early receipt during native write/drain is saved as bounded unclassified evidence. It is classified only after independently known submission and original-clock ordering; classification cannot invent a receipt or backdate an ACK. A committed ACK survives collector restart; unused authority expires conservatively on restart. Duplicates still require original token-hash proof, including after expiry. Manual confirmation never rewrites an old wait.

Ordinary Python Claude fields remain absent rather than synthesized as false/null. Known native facts survive wait failure. Pending wait interruption records stopped and returns complete structured output with exit 130; querying the stopped intent succeeds with exit 0. No status, wait, ACK or confirmation operation submits a native message. Missing/corrupt/unknown history has a separate handoffQuery error without a fabricated epoch. No automatic resend or fallback is allowed.

The per-destination budget starts before setup: 30 seconds by default, ASCII integers 1..60 only. Exactly five seconds are reserved within the total for cleanup. Observation/effect ends at total minus five seconds; timeout diagnostics describe that cutoff. Budgets at or below five seconds refuse before effect. OS filesystem/identity operations and fsync cannot be forcibly cancelled by this Python implementation; this is not a universal hard-real-time latency guarantee.

Raw receipt capabilities occur only in authorized native message input and private IPC/stdin, never sender/collector ordinary outputs, argv, URI, environment or own journal. The journal stores hashes. Native recipient queue/history may retain the delegated token, and same-user readers may acquire it: token_possession is not independent model identity. No recipient transcript is read.

## Storage and remaining gates

The owner-only POSIX directory is ~/.local/share/session-peer/handoff. Atomic fsynced snapshots and a stable exclusive lock fence the first native attempt before effect; a crash after that fence remains unknown even if no write actually began. Reservation includes each intent's bounded future receipt/wait/native detail; the 10,000-intent and 32 MiB quotas include tombstones and reservations. Capacity never evicts effect fences. There are at most 64 distinct waits per intent.

Details compact to a target-bound tombstone after 30 days only under proven native boot/monotonic continuity; unavailable continuity conservatively retains detail and may exhaust quota sooner. Cross-boot retention needs further acceptance review. A known restored ledger must be quarantined with the explicit operator HandoffLedger.quarantine_restored() API before reuse; CLI restore/reconciliation tooling remains a gate. Archive/new initialization is an explicit operator action, never automatic repair. Unmarked rollback or cloned history cannot be detected reliably. A stale collector socket is not automatically removed or rebound. Collector lifetime is at most 24 hours; receipt TTL is 24 hours from the original durable intent commit and collector restart revokes unused authority. Lifecycle/expiry boundaries still require review against the complete design before release.

Verification uses owned local Unix inboxes, actual peer-PID/process-birth checks, private collector/producer subprocesses, strict JSON, concurrent startup, crash fencing, late/duplicate/expired receipt and SIGINT fixtures. It does not prove real Claude model consumption, a native Codex observer, remote bootstrap or Windows cleanup. #181 stays open until those remaining acceptance gates are resolved; the frozen design fixture is not runtime certification.
