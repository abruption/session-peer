# v0.9.0 integration work (active)

Goal: integrate real-agent paired direct/E2EE relay delivery, validate installation
and operation, prepare v0.9.0 release PR, then after merge publish tag/PyPI and
perform operational validation before v1.0.0-rc.

Authoritative starting state: main 39fedf8 contains #86 only. #87/#88 merged into
refactor/47-agent-transports, not main. Integration branch feat/69-native-relay
cherry-picks those approved changes with provenance onto main. Main CI run
35185418394 passed. This branch is not a release until all gates below pass.

Design decisions:
- Keep core standalone/SSH dependency-free. Optional session_peer_relay package
  and [relay] extra (Python 3.11+) only load for explicit device/relay commands.
- Native endpoints are operator-defined aliases, never peer-controlled executable,
  home or arbitrary CLI args. Receiver policy binds paired device fingerprints to
  capabilities and target aliases; pairing alone grants no agent access.
- Route list/send via existing AgentRegistry and LocalTransport, using bounded
  worker subprocesses so native I/O cannot block TLS admission or revocation.
- Journal submission intent before native effect. Include destination binding and
  message in request digest. Unknown outcomes never automatically retransmit.
- Device-specific keys, pinned TLS1.3 inside WebSocket, separate relay admission,
  explicit pairing/revocation. Operator installs relay behind existing HTTPS edge;
  no secret/private-key propagation or automatic public exposure.
- Keep lab immutable as historical evidence. Product package has its own regression
  tests and explicit real-session testing; never count fixture results as native.

Gates (pending unless evidence recorded below):
1. Integrated baseline tests and wheel/sdist.
2. Product direct/relay tests: native allowlist, pairing, revoke, duplicates,
   subprocess timeout/crash, blocked transport fallback, metadata redaction,
   malformed/large input, private permissions and service restart.
3. Isolated installation from built artifacts; Linux service hardening/runbook.
4. Real available agent session delivery over direct and relay with independent
   transcript/ACK evidence, stopped/cleaned pilot resources.
5. Main integration PR green; release PR/version/changelog/publish audit.
6. Release merge verified; immutable tag, GitHub publication, PyPI install checks.
7. Actual operation/soak and remaining defects resolved before v1.0.0-rc.

Progress evidence (2026-09-17, in progress):
- Both approved branches integrated locally with provenance; pre-product combined
  baseline: 352 tests passed. Product native/CLI/adversarial tests are being added.
- Real KR agy TUI resumed by user. Two distinct SP090 integration markers were
  delivered over direct and relay paths and ACKed; duplicate IDs were suppressed.
  Paths used loopback listeners and explicitly owned SSH tunnels, not public WSS.
- Artifacts built and isolated wheel/sdist environments installed with relay extra.
- Linux DynamicUser service test caught root-owned read-only systemd credential
  incompatibility. Restricted credential-mount support added; retest started
  successfully with ProtectHome/ProtectSystem/NoNewPrivileges, 256MiB/64 tasks;
  unauthenticated admission401 and authenticated admission200 observed.
- User-approved public WSS pilot completed: authenticated list, real Antigravity
  send and independently observed ACK, duplicate receipt reuse, admission401.
  SSH forwarding was stopped. See relay-public-pilot-2026-09-17.md for boundaries.
- Temporary Caddy route/service/receiver/bridge removed; original Caddy hash and
  HTTP301 restored, port3769 closed, user TUI preserved. No permanent deployment.
- Latest full local suite including route-update regression: 370 tests passed.
  Main-target PR, release metadata, CI and publication remain pending.
