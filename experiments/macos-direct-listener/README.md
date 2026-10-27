# macOS Direct listener observations — 2026-10-27

This record accompanies [#341](https://github.com/abruption/session-peer/issues/341). It separates an unresolved inbound-listener problem from the receiver's startup and diagnostic presentation. The tested public runtime was Python session-peer v1.3.1, source `5391365c4896cd7eefa1ba2bbe20b9bed2075d8c`. It is a dated experiment, not a general platform certification or an automatic test.

## Environment and controls

Both Macs ran macOS 27.0.1 on arm64. The Mac mini used Tailscale 1.104.1's Network Extension; the MacBook used the open-source `tailscaled` 1.104.2. The baseline private environments used Homebrew Python 3.14.9, OpenSSL 4.1.0, cryptography 50.0.2, websockets 17.3 and session-peer 1.3.1. The MacBook's separate python.org Python 3.13.7 control used OpenSSL 3.0.16 with the same session-peer/cryptography/websockets versions. The distributions were not all tested on the same machine, so the comparison is confounded by machine and Tailscale differences. Each pairing case used new private identities, a separate policy with no native send permission, a private invitation transferred over SSH, and a receiver that stopped after 20 seconds. The fixture also rejected any native invocation. Existing device state, launchAgents, firewall, access policy, SSH configuration and Tailscale installation were not modified.

The operator explicitly authorized the 20-second wildcard-listener comparisons. Those were controlled experiments, not a recommendation to widen an existing listener.

## Independently observed results

| Build / experiment | Result |
| --- | --- |
| Plain asyncio, no session-peer: Homebrew Python 3.14.9, loopback, both Macs, Kqueue and Select | Accepted callback, received bytes and echo succeeded. |
| Same plain probe, each machine's own tailnet IPv4, self-connect, both selectors | TCP connected; no accepted callback during the bounded observation; echo timed out. |
| Cross-Mac plain probe, mini receiver, tailnet bind | TCP connected; echo timed out; no accepted callback observed. |
| Cross-Mac plain probe, mini receiver, loopback bind | Connection refused; no accepted callback observed. |
| Cross-Mac plain probe, mini receiver, private LAN bind | Connection refused; no accepted callback observed. |
| Cross-Mac plain probe, MacBook receiver, tailnet bind | TCP connected; echo timed out; no accepted callback observed. |
| Cross-Mac plain probe, MacBook receiver, loopback bind | Connect timed out; no accepted callback observed. |
| Cross-Mac plain probe, MacBook receiver, private LAN bind | Connect timed out; no accepted callback observed. |
| Mini raw threaded socket echo, no session-peer or asyncio | Homebrew Python 3.14.9 timed out in accept/read; the system Python passed. |
| Additional plain-probe interpreter controls | The MacBook's python.org Python 3.13.7 passed self-tailnet echo. The mini's uv Python 3.13.7 and Homebrew Python 3.15.1 failed it. This does not support a simple Python-minor-version attribution. |
| Released CLI v1.3.1 at the source above, test identities, Homebrew receivers, own tailnet bind | Both directions returned `peer_tls/timeout`, exit 1, `retryAllowed:false`; the client retained `pending`, while the receiver had no paired peer. |
| Released CLI v1.3.1, test identities, Homebrew receivers, explicit wildcard bind | Both directions still returned the same timeout. No wildcard workaround was established. |
| Released CLI v1.3.1, mini Homebrew client to MacBook python.org Python 3.13.7 receiver on its tailnet address | Pairing succeeded, both test peers became paired, and an authenticated probe succeeded. |
| Released CLI v1.3.1, MacBook python.org client to mini Homebrew TLS receiver through a private-address system-Python byte forwarder | Pairing and authenticated probe succeeded; the forwarder accepted three connections, did not terminate TLS, and exited normally. This is an explicitly forwarded topology, not a fix for the failing native listener. |

The diagnostic candidate was separately tested with `app.py` SHA-256 `71bb4ad28b30d478f33fe6cfbc0d4d4ebb4dbb6e153564e5af226669d94da6f5` and `cli.py` SHA-256 `21b7ea3e0187b6b27d7a6ec6a907a243e9f953c1f4facdb6a9158c0d0fb71de8`. These are candidate verification results, not additional evidence about the released binary or a repair of its failing topology:

| Final candidate configuration | Result and normal-shutdown summary |
| --- | --- |
| Mini Homebrew receiver, native tailnet bind; MacBook client | Pairing again timed out at peer TLS; the receiver's observed counters were accepted 0, TLS completed 0, TLS failed 0. The client retained pending state. The emitted summary positively records the zero callback observation for this fixture. |
| MacBook python.org receiver, tailnet bind; mini client | Pairing and authenticated probe passed; accepted 3, TLS completed 3, TLS failed 0. |
| Mini Homebrew loopback TLS receiver behind the private byte forwarder; MacBook client | Pairing and authenticated probe passed; accepted 3, TLS completed 3, TLS failed 0; the forwarder also accepted 3. |

All three final candidate receivers stopped normally after 20 seconds with zero native invocations. The successful receivers emitted two rate-limited phase records plus one shutdown summary; the zero-accept receiver emitted only its summary. These summaries describe the receiver instance's observation at normal close, not a guarantee about kernel state or later callbacks from an incorrectly retained external listener.

The four failed released-CLI pairing cases used separate new states and were not retried. The final candidate's failed case and each successful control also used new states; they did not retry a previous uncertain state. The result collection recorded zero native invocations. The system Python served only as a plain-TCP control/forwarder, not as a session-peer Relay runtime; the supported runtime floor is unchanged. The first pairing harness did not instrument the accept callback: its lack of Direct lifecycle logs is not itself proof that no accept occurred. Plain-TCP callback counts were measured separately.

Both machines reported the tested interpreter path as permitted by the application firewall. The actual running Homebrew Python.app image was also checked on the mini and reported permitted. This metadata does not establish effective inbound behavior or rule out all policy/filter interactions. Code-signing identity, interpreter distribution, routing and platform behavior remain investigation variables.

Read-only signature verification failed for both installed Homebrew Python.app images, while the MacBook's python.org image passed. On a newly copied mini-only test bundle, regenerating its ad-hoc signature made strict signature verification pass but the same raw TCP accept test still failed. No installed interpreter or firewall entry was changed. Invalid signature metadata alone therefore was not established as the cause, and re-signing was not established as a repair.

## Reproduction scaffold

`tcp_probe.py` is the plain-TCP probe used for the control comparisons, with command-line bounds and Python 3.9-compatible loop setup. It creates no session-peer state or credentials. Its historical framework setup was changed from Runner to explicit loop construction for the system-Python comparison; the echo payload and observation points are unchanged. It is not executed by repository CI.

Select the intended interpreter explicitly. Run self-connect comparisons with loopback and then the machine's own tailnet address, followed by separately authorized server/client comparisons on the other Mac. Record connect, accepted callback, bytes, echo and closure separately. The scaffold reports its own ready/connect/callback/byte-count/echo/close observations; do not publish personal endpoint addresses or raw private logs. No TLS secret, invitation or native message is part of this scaffold.

## Interpretation and remaining work

The observations establish that the original pairing timeout is reproducible, that the pairing protocol can work between these Macs in the stated controls, and that TCP connection establishment or listener creation is not sufficient readiness evidence. They do not identify a universal macOS/Tailscale/Python root cause or certify a production forwarding deployment.

The accompanying code change adds explicit startup uncertainty and bounded opt-in Direct accept/TLS diagnostics. It does not modify binds, firewall policy, runtime selection, authentication, TLS deadlines or retries. The original issue remains open for the unresolved listener behavior and a separately reviewed upstream report if further evidence isolates its owner.

Relevant primary references are [Tailscale's macOS variants](https://tailscale.com/docs/concepts/macos-variants), [Apple TN3179](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy), [CPython's framework launcher](https://github.com/python/cpython/blob/v3.14.9/Mac/Tools/pythonw.c), and [Apple's code-signing/firewall discussion](https://developer.apple.com/library/archive/documentation/Security/Conceptual/CodeSigningGuide/AboutCS/AboutCS.html). In particular, TN3179 does not make incoming TCP accept depend on Local Network permission, so these results are not a verified TCC diagnosis.
