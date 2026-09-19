# AI 지원 설치 및 운영

[개요로 돌아가기](../../README.ko.md)

이 문서는 코딩 에이전트나 AI 비서에게 제공할 간결한 작업 입력입니다.
AI가 가장 작은 session-peer 구성을 선택하고, 실제 작업과 검증을 마친
뒤 남은 한계를 보고하도록 안내합니다. 새로운 권한을 부여하거나 제출된
메시지를 수신 에이전트가 읽었다는 증거로 바꾸지는 않습니다.

## 이 요청문을 복사하세요

대괄호 부분을 바꾼 뒤 블록 전체를 AI에게 전달하세요. AI가 질문하기 전에
현재 장비와 저장소를 먼저 확인하도록 두는 것이 좋습니다.

```text
Read AGENTS.md if it exists, then read docs/ai-assistant-guide.md and every guide it links that is relevant to this goal.

Goal: [install session-peer / connect an SSH host / configure MCP / configure Antigravity / configure paired devices / diagnose a failure]
Environment: [operating system, local or remote, SSH alias if any]
Target agents: [Claude Code / Codex / Antigravity]

Work through the goal to a verified result. Reuse authorization already given in this conversation. Before account changes, OAuth consent, DNS or firewall changes, service deployment, reboot, payment, merge, release, or publication, confirm that the action is explicitly authorized. Never ask me to paste secrets into chat; use an existing credential manager or protected file. Start with read-only discovery, use dry-run where available, preserve unknown message outcomes, and do not retry a send merely to turn an unknown result into success.

At the end report: outcome, files or systems changed, commands and tests run, message acknowledgement evidence, remaining limitations, and any rollback instructions. Redact tokens, cookies, session IDs, private paths, conversation text, and private keys.
```

## 가장 작은 범위를 선택하세요

- 같은 장비나 SSH 호스트의 세션에는 core CLI만 설치하세요.
- 대상 에이전트에 필요한 경우에만 선택 어댑터를 설정하세요.
- MCP 클라이언트가 session-peer 도구를 사용해야 할 때만 MCP를 추가하세요.
- SSH를 사용할 수 없고 운영자가 추가 신원·복구·서비스 작업을 수용한
  경우에만 paired device 또는 암호화 릴레이를 사용하세요.

저장소에 릴레이 코드가 있다는 이유만으로 릴레이를 배포하면 안 됩니다.
일반적인 사용에는 의존성이 적고 단순한 로컬·SSH 흐름을 기본값으로
유지하세요.

## 필수 작업 흐름

1. 운영체제, Python 버전, 설치 방식, 현재 사용자, 목적지 계정, 에이전트
   home과 대상 경로가 local·SSH·MCP·paired device 중 무엇인지 확인하세요.
2. 파일을 바꾸기 전에 관련 문서와 설치된 버전을 확인하세요. 조회 결과가
   다른 agent home을 가리키면 기본 경로를 가정하면 안 됩니다.
3. 읽기 전용 조회부터 시작하세요. 실제 메시지를 보내기 전에 doctor,
   list, dry-run으로 정확한 대상과 전송 경로를 확정하세요.
4. 가장 작고 되돌릴 수 있는 변경을 수행하세요. 공용 서비스나 원격
   호스트를 바꾸기 전에 기존 설정과 rollback 방법을 보존하세요.
5. 자격정보를 명령, 로그, 소스 관리, 이슈 댓글, 채팅에 넣지 마세요.
   보호 파일, 시스템 credential 기능 또는 사용자의 credential manager를
   사용하세요.
6. 설치 경로와 실제 요청 전송 수단을 검증하세요. 로컬 unit test만으로
   SSH, OAuth, public WSS 또는 수신 모델의 동작이 입증되지는 않습니다.
7. 한계와 함께 사실을 보고하세요. submitted, posted, queued는 ACK가
   아닙니다. 완료가 중요하면 명시적 답장을 요청하고 관측하세요.

## 기본 명령

격리된 tool 설치를 우선하세요. Native Windows에서는 POSIX shell
installer 대신 Python package manager를 사용하세요.

```bash
python3 --version
pipx install session-peer
# Alternative: uv tool install session-peer

session-peer --version
session-peer doctor
session-peer list --output-format json
```

메시지를 전달하지 않고 대상을 해석하세요. 원격 목적지일 때만 SSH host
option을 추가하세요.

```bash
session-peer doctor --host SSH_ALIAS
session-peer list --host SSH_ALIAS --output-format json
session-peer send --host SSH_ALIAS --to TARGET --dry-run --message "hello" --output-format json
```

dry-run이 의도한 세션 하나를 해석한 뒤 새 메시지를 한 번 전송하세요.
README의 예시 이름이나 식별자를 그대로 사용하면 안 됩니다.

```bash
session-peer send --host SSH_ALIAS --to TARGET --message "Reply with: SESSION-PEER-ACK-UNIQUE-MARKER" --output-format json
```

## 보안과 승인 경계

- 에이전트 DB, inbox, transcript, cookie, OAuth token, device state,
  private key, replay state와 credential file은 비공개로 취급하세요.
- 장비 사이에 browser profile이나 credential을 복사하지 마세요. 대화형
  동의가 필요하면 사용자의 인증 세션을 이미 보유한 browser를 사용하세요.
- 시험 통과를 위해 host-key 확인, 인증, firewall rule, browser integrity
  보호 또는 service sandbox를 약화하지 마세요.
- 설치나 진단 요청만으로 account 변경, public exposure, 결제, 파괴적
  정리, reboot, merge, tag, release 또는 package publication이 승인되지는
  않습니다.
- 작업이 이미 명시적으로 승인됐다면 같은 권한을 반복해서 묻지 말고
  되돌릴 수 있는 준비와 검증까지 완료하세요.
- timeout이나 응답 유실 뒤에도 request와 operation identifier를 보존하세요.
  중복 작업을 만들지 말고 상태를 reconcile하세요.

## 완료 보고

AI는 다음 형태의 짧은 보고를 남겨야 합니다.

```text
Outcome:
Changes:
Validation:
Acknowledgement evidence:
Remaining limitations:
Rollback:
```

깨끗한 shell에서 의도한 명령이 실행돼야 설치 완료입니다. 전송 설정은
요청된 local·SSH·MCP·paired 경로를 실제로 시험해야 완료입니다. 릴레이
배포에는 service health, persistent state, restart, backup, restore 검증도
필요합니다. 제외했거나 중단한 시험을 통과로 표현하면 안 됩니다.

## 관련 문서

- [CLI 참고서](cli-reference.md)
- [진단과 답장](diagnostics.md)
- [MCP 설정](mcp.md)
- [에이전트 어댑터](agent-adapters.md)
- [Antigravity](antigravity.md)
- [Wake 동작](wake.md)
- [Paired device와 암호화 릴레이](paired-devices.md)
- [보안 정책](../../SECURITY.ko.md)
