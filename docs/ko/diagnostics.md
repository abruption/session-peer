# 진단 및 회신 주소 계약

`session-peer doctor`는 대상 세션을 소유한 머신을 검사합니다. `--host`를 사용하면 동일한 표준 라이브러리 스크립트가 SSH를 통해 해당 호스트에서 실행되므로 경로, 사용자, 프로세스, 소켓 및 데이터베이스가 올바른 보안 경계 내에서 평가됩니다.

이 명령어는 읽기 전용입니다. Claude 인박스에 연결하거나, Codex 큐 항목을 제출하거나, 임의의 파일 시스템 루트를 스캔하거나, 권한을 변경하거나, SSH 호스트 키를 등록하거나, 에이전트 설정을 변경하지 않습니다.

## JSON 모델

Doctor는 공통 응답 엔벨로프를 사용합니다. `ok`는 진단 명령어가 실행되었는지 여부를 나타내며, 모든 선택적 에이전트가 설치되었거나 사용 가능하다는 의미는 아닙니다. 이를 확인하려면 중첩된 상태를 사용하세요:

```json
{
  "schemaVersion": 1,
  "ok": true,
  "host": "worker.example.ts.net",
  "command": "doctor",
  "status": "partial",
  "claude": {
    "status": "inbox_unavailable",
    "sessionsDir": "/home/alice/.claude/sessions",
    "records": 1,
    "invalidRecords": 0,
    "aliveSessions": 1,
    "availableInboxes": 0,
    "checks": [
      {"status": "warning", "code": "inbox_unavailable", "message": "..."}
    ]
  },
  "codex": {
    "status": "available",
    "selectedHome": "/home/alice/.codex",
    "homeSource": "default",
    "executable": "/home/alice/.local/bin/codex",
    "homes": [
      {
        "codexHome": "/home/alice/.codex",
        "stateDb": "/home/alice/.codex/state_5.sqlite",
        "status": "available",
        "code": "state_db_readable",
        "sessionCount": 12
      }
    ],
    "checks": []
  },
  "capabilities": {
    "replyObservation": {
      "status": "unsupported",
      "reason": "no_cross_agent_acknowledgement_api",
      "claudeLocalIdleNotice": "native_claude_only",
      "automatedWait": false
    }
  }
}
```

최상위 `status`는 두 에이전트 트랜스포트를 모두 사용할 수 있을 때 `healthy`, 하나만 사용할 수 있을 때 `partial`, 둘 다 사용할 수 없을 때 `issues_found`입니다. 에이전트 상태는 다음과 같습니다:

| Status | Meaning |
| --- | --- |
| `available` | 필요한 로컬 증거를 읽을 수 있고 존재합니다. Claude 인박스 확인은 실제 전송 전까지 파일 시스템 수준에서만 수행됩니다. |
| `unavailable` | 실행 중인 사용 가능한 세션을 찾을 수 없습니다. |
| `inbox_unavailable` | 실행 중인 Claude 프로세스가 기록되어 있지만 사용 가능한 인박스가 없습니다. |
| `missing_tool` | 대상 시스템에서 Codex 실행 파일을 사용할 수 없습니다. |
| `missing_home` | 구성된 세션 디렉터리 또는 Codex 상태 DB가 없습니다. |
| `wrong_home` | 구성된 경로의 파일 유형이 잘못되었습니다. |
| `permission_denied` | 대상 OS 사용자가 필요한 경로나 기록을 검사할 수 없습니다. |
| `unsupported` | 알려진 파일이 존재하지만 해당 스키마가 지원되지 않습니다. |
| `unknown` | 검사 결과 더 구체적인 상태를 확인할 수 없습니다. |

코드 값은 안정적인 기계 판독 가능 사유입니다. 메시지는 사람을 위한 것이며 스키마 변경 없이 더 구체화될 수 있습니다.

## 반환 경로 확인

`doctor --host worker --check-return-route`는 `worker`에게 감지된 출발지로 돌아가는 SSH 명령어를 테스트하도록 요청합니다. `--reply-to USER@HOST`는 감지된 해당 주소를 재정의합니다. 이 확인은 배치 모드, 비밀번호 및 키보드 대화형 인증 비활성화, 엄격한 호스트 키 확인, 호스트 키 업데이트 비활성화 상태에서 고정된 `true` 명령어를 사용합니다. 자격 증명이나 완화된 정책으로 재시도하지 않습니다.

```json
{
  "returnRoute": {
    "status": "failed",
    "transport": "ssh",
    "host": "alice@origin.example.ts.net",
    "reason": "authentication_failed",
    "sshUser": "alice",
    "sshUserSource": "explicit"
  }
}
```

반환 상태는 `verified` 또는 `failed`입니다. 실패 사유에는 `return_host_unavailable`, `ssh_executable_missing`, `authentication_failed`, `host_key_failed`, `timeout`, `transport_failed`, `remote_command_failed`가 포함됩니다. 현재 머신의 현재 사용자에 대한 반환 주소는 검증된 로컬 경로로 정규화되며 SSH를 절대 시작하지 않습니다.

## 구조화된 Reply-To

메시지에는 이제 비활성 버전 관리 URI가 포함되고 그 뒤에 기존 명령어가 따릅니다:

```text
Reply-To: session-peer://v1/reply?agent=claude&session=api-worker&transport=ssh&host=alice%40origin
Reply: python3 /path/to/session_peer.py send --host alice@origin --to api-worker --no-reply-to
```

이 URI는 `send --to URI`로 전달할 수 있습니다. 버전, 필드 이름, 중복 필드, 에이전트, 트랜스포트, UUID, 호스트, 제어 문자 및 충돌하는 CLI 라우팅 플래그는 검색 또는 디스패치 전에 유효성이 검사됩니다. 그 내용은 절대 셸 구문으로 파싱되지 않습니다. 필드는 다음과 같습니다:

| Field | Requirement |
| --- | --- |
| `agent` | 필수: `claude` 또는 `codex`. |
| `session` | 필수 세션 이름/PID, 또는 전체 Codex UUID. |
| `transport` | 필수: `local` 또는 `ssh`. |
| `host` | `ssh`인 경우에만 필수이며, 알려진 경우 SSH 사용자를 포함합니다. |
| `codexHome` | 발신자가 활성화된 구성 홈을 식별할 수 있는 경우 Codex에 대해 선택 사항입니다. |

전송 JSON에는 나가는 메시지에 배치된 경로에 대한 `replyRoute`가 포함됩니다. 로컬 경로는 `verified`이며, SSH 경로는 옵트인 doctor 프로브가 성공할 때까지 사유가 `reverse_ssh_not_checked`인 `unverified` 상태입니다. `--to`가 구조화된 주소를 사용하는 경우 `addressResolution`은 선택된 트랜스포트 및 모든 `ssh_self` 정규화를 기록합니다.

## 일반적인 대기 기능이 없는 이유

Claude Code는 다른 로컬 Claude 세션을 관찰하는 메인 Claude 대화를 위한 네이티브 단발성 `notify_when_idle` 구독을 문서화하고 있습니다. 동일한 문서에서 이를 해당 머신의 세션으로 제한하며 서브에이전트, 에이전트 팀 팀원 및 해당 머신 외부의 세션은 제외합니다. Codex 큐 제출 또한 session-peer를 통한 에이전트 간 확인을 노출하지 않습니다.

결과적으로 이식 가능한 `--wait`는 변경 가능한 트랜스크립트로부터 완료 여부를 추론해야 합니다. 새로운 트랜스크립트 이벤트는 다른 요청에 속할 수 있으며, 누락된 이벤트는 보류된 입력, 오프라인 세션, 변경된 스토리지 형식 또는 완료되지 않은 턴을 의미할 수 있습니다. session-peer는 잘못된 확인을 반환하는 대신 해당 기능을 `unsupported`로 보고합니다. 완료 워크플로의 경우 메시지에 요구사항과 상관관계 토큰을 넣고 대상에게 해당 `Reply-To` URI로 새 메시지를 보내도록 요청하세요.

참고자료: [Claude Code 메시지 전달](https://code.claude.com/docs/en/cross-session-messaging#message-delivery), [유휴 알림](https://code.claude.com/docs/en/cross-session-messaging#get-a-notice-when-another-session-goes-idle) 및 [세션 인박스 소켓](https://code.claude.com/docs/en/cross-session-messaging#the-sessions-inbox-socket).

## List 검색 결과

`list`는 기본적으로 두 에이전트 모두를 대상으로 하며, `--agent claude|codex`로 하나를 선택합니다. `discovery` 객체는 요청된 각 에이전트를 보고합니다. Claude는 `ok`/`error`를 유지하고, Codex는 `ok`, `not_installed` 또는 `error`와 홈별 진단 정보를 보고합니다. 실패 시 성공한 행은 보존되지만 `ok=false`, 최상위 오류 요약 및 종료 코드 1이 설정됩니다. Codex가 자동 설치되지 않은 경우 `not_installed`이며, 종료 코드 0의 빈 결과가 반환됩니다. 명시적으로 구성된 홈이 누락된 경우는 오류로 유지됩니다. 누락된 Claude 세션 디렉터리는 빈 결과이며, 읽을 수 없는 디렉터리는 오류입니다. SSH는 부분 결과와 반복된 호스트 엔벨로프를 보존합니다. 모든 행에는 `agent` 식별자가 있습니다. 후보 검색, 메타데이터 및 권한 경계에 대해서는 [멀티 홈 목록](multi-home-list.md)을 참조하세요.

## CLI 입력 및 출력 선택

결과 엔벨로프를 보려면 list/send/doctor/update에서 `--output-format json`을 사용하세요. `--json`은 계속 별칭으로 유지됩니다. `--output-format text`는 기본 사용자 출력입니다. 이러한 옵션은 전송 본문을 JSON으로 해석하지 않습니다. `send --message TEXT`(또는 `-m TEXT`), 기존 위치 지정 메시지 또는 표준 입력(`--message -`)을 사용하세요. 모순되는 출력 플래그는 사용법 오류(stderr, 종료 코드 2)이며, 충돌하는 본문 소스는 표준 입력을 읽거나 디스패치하기 전에 선택한 결과 형식 및 종료 코드 1로 실패합니다. 기존 CLI, SSH 및 MCP 제출/수신 시맨틱은 변경되지 않습니다.
