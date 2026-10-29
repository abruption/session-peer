<!-- PR title should follow Conventional Commits, e.g. "fix: read the socket path from the session record" -->

## Summary
<!-- What does this change and why? -->

## Issue references
Refs #<!-- issue number; use non-closing references for partial work -->
<!-- Only for intentional completion: replace the reference with an automatic-closing
keyword and the issue reference after checking every acceptance condition.
Intentional completion example: Closes <issue-reference>.
Do not negate, qualify or quote a closing phrase to keep an issue open: GitHub
may still close it. Use Refs instead. The reference warning is only a heuristic;
it does not prove how GitHub will interpret a description or change issue state. -->
<!-- Manual sidebar links and closing keywords in commit messages are outside this
warning's scope. Automatic issue closure applies when merged into the default branch. -->

## Type
- [ ] feat
- [ ] fix
- [ ] docs
- [ ] chore / refactor / test / perf

## Checklist
- [ ] `python session_peer.py --version` / `--help` checked where relevant
- [ ] Generated standalone checked: `python tools/generate_session_peer.py --check` (or not run, with reason below)
- [ ] Commits follow Conventional Commits
- [ ] Relevant [user documentation](https://github.com/abruption/session-peer/blob/main/docs/README.md), [CLI reference](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md) and translations updated, or marked not applicable
- [ ] No secrets, tokens, or session keys in the diff

## Validation
<!-- Select checks appropriate to this change; do not imply that unrun checks pass.
Report command, result, skips and environment limits. Use "not run: reason" or
"not applicable: reason". Real-host SSH, native agent messages, model calls and
production mutations are not required for every PR and need their own scope. -->

| Area | Relevant check / evidence |
| --- | --- |
| Core | `python -m unittest discover -s tests/core -t . -v` |
| Adapters / Codex | `python -m unittest discover -s tests/adapters -t . -v`; `python -m unittest discover -s tests/codex -t . -v` |
| Distribution / docs | `python -m unittest discover -s tests/distribution -t . -v`; `python -m unittest discover -s tests/docs -t . -v` |
| Optional MCP / Relay | Install the relevant extra, then `python -m unittest discover -s tests/mcp_integration -t . -v` / `python -m unittest discover -s tests/relay -t . -v` |
| Optional Control | In `control/`: `npm ci`, `npm run typecheck`, `npm test`, `npm audit --omit=dev` |
| Control integration / built packages | Follow [test-suite prerequisites and artifact checks](https://github.com/abruption/session-peer/blob/main/tests/README.md) when relevant |

## Verified against
<!-- Record exact Python and, when relevant, Node/npm and Claude Code/Codex/
Antigravity versions; OS/architecture; extras/dependency profile; fixture versus
live acceptance. Use not run/not applicable rather than inventing evidence. -->

## Notes
<!-- Tradeoffs, follow-ups, manual test steps reviewers should know about. -->
