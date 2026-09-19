# 여러 홈에 걸친 Codex 세션

`session-peer list --json`에는 알려진 홈 전반의 Claude 및 저장된 Codex 세션이 포함됩니다. `--agent codex`는 Codex로 필터링하고, `--agent claude`는 Codex 조사를 건너뜁니다. `--codex-home`이 없으면 대상 시스템의 후보는 다음과 같습니다:

1. 기본 `~/.codex`.
2. 비어 있지 않은 경우 `CODEX_HOME`.
3. macOS `~/Library/Application Support/orca/codex-accounts/*/home` 아래의 직접적인 계정 홈.
4. 절대(또는 `~/`) 홈 경로의 JSON 배열인 `SESSION_PEER_CODEX_HOMES`.

재귀적인 파일 시스템 스캔이나 프로세스/자격 증명 검사는 없습니다. 명시적인 `--codex-home PATH`는 자동 조사 및 무관한 구성 오류를 우회합니다. DB는 읽기 전용으로 열립니다. Send/wake는 기존의 더 엄격한 홈 확인을 유지하며, 목록 조회가 활성 작성기를 선택하지는 않습니다.

## 행 및 검색

각 Codex 행에는 정규 `codexHome` 및 절대 `stateDb` 경로가 포함됩니다. 신원은 호스트 + 정규 홈 + UUID입니다. 즉, 서로 다른 홈의 동일한 UUID는 별도로 유지됩니다. 동일한 홈의 심볼릭 링크 별칭은 중복 제거되고 해당 `sources`가 병합됩니다. Codex 행은 `updatedAt` 내림차순으로 정렬된 후 홈 및 UUID 순으로 정렬됩니다. `--all`은 모든 홈에서 독립적으로 보관된 레코드를 포함합니다. 사용자 출력에는 각 행 옆에 홈이 표시됩니다.

예시(기존 schemaVersion 1 엔벨로프 내):

```json
{
  "sessions": [
    {"agent": "codex", "id": "same-uuid", "codexHome": "/home/me/.codex", "stateDb": "/home/me/.codex/state_5.sqlite"},
    {"agent": "codex", "id": "same-uuid", "codexHome": "/home/me/custom", "stateDb": "/home/me/custom/state_5.sqlite"}
  ],
  "discovery": {
    "codex": {
      "status": "ok",
      "homes": [
        {"codexHome": "/home/me/.codex", "stateDb": "/home/me/.codex/state_5.sqlite", "sources": ["default"], "status": "ok", "sessionCount": 1},
        {"codexHome": "/home/me/custom", "stateDb": "/home/me/custom/state_5.sqlite", "sources": ["configured"], "status": "ok", "sessionCount": 1}
      ]
    }
  }
}
```

기존의 최상위 `codexHome`은 조사에서 조사 오류 없이 정확히 하나의 후보 홈을 식별한 경우에만 유지되며, 여러 홈의 경우 생략됩니다. 소비자는 스레드 UUID에서 홈을 추론하지 말고 해당 행의 홈을 사용해야 합니다.

홈 진단은 `status: ok | absent | error`를 사용합니다. 선택적인 기본 또는 Orca DB가 없는 것은 오류가 아닙니다. `--codex-home`, `CODEX_HOME` 또는 `SESSION_PEER_CODEX_HOMES`에 의해 명시적으로 지정된 홈이 누락된 경우는 선택적 후보의 별칭이더라도 오류입니다. 성공적으로 읽은 빈 DB는 세션 수가 0인 `ok`입니다.

오류에는 안정적인 코드가 포함됩니다: `state_db_missing`, `state_db_not_regular`, `permission_denied` 또는 `state_db_read_failed`(손상되었거나 호환되지 않는 DB 포함). 조사 실패는 `discovery.codex.errors`에 `source`, `error`, 선택적 `path` 및 코드 `home_resolution_failed`, `candidate_enumeration_failed` 또는 `invalid_home_configuration`과 함께 나타납니다. 유효하지 않은 추가 홈 구성은 전체가 거부되며, 기본/환경/Orca 결과는 유지됩니다.

어떠한 실패라도 발생하면 Codex 집계는 `error`로 설정되고 명령어는 `ok: false`, 종료 코드 1이 되지만 다른 홈 및 Claude 행은 유지됩니다. 읽을 수 있는 DB가 없고 오류도 없으면 자동 검색은 `not_installed`, 빈 세션 및 종료 코드 0을 보고합니다. 이는 이전의 기본 DB 누락 오류에서 변경된 사항입니다. 성공적인 검색이 활동, 수신 또는 큐 소비의 증거는 아닙니다.

## SSH, 전송 및 MCP

SSH를 통해 스트리밍된 소스는 해당 호스트의 자체 사용자/환경을 사용하여 해당 호스트의 홈을 열거합니다. 반복된 `--host`는 기존의 순서화된 응답 배열을 유지하며, 하나의 실패는 다른 호스트의 결과를 버리지 않고 전체 종료 코드 1을 생성합니다.

선택한 행의 홈을 명시적으로 사용하세요:

```sh
session-peer list --host user@worker --agent codex --json
session-peer send --host user@worker --codex-home '/path/from/selected/row' --to codex:<uuid> 'message'
```

MCP는 구성된 홈을 계속 명시적으로 전달합니다. 이 CLI 기본값은 MCP에 다른 홈에 대한 액세스 권한을 부여하지 않습니다. 추가 홈의 경우 승인된 다른 대상을 만드세요. Python 3.9 독립형 의존성은 변경되지 않습니다.
