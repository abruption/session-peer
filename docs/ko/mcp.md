# 선택형 Codex MCP 연동

Python 3.10 이상에서 설치하십시오: `pipx install 'session-peer[mcp]'`(또는 격리된 venv에 extra 설치). 의존성이 없는 Python 3.9 CLI 및 `install.sh`는 계속 지원됩니다. 셸 설치기는 MCP 의존성을 설치하지 않습니다. Python 3.9에서 MCP 엔트리 포인트는 Python 3.10+이 필요하다고 보고합니다.

`session-peer-mcp --config /absolute/path/policy.json`으로 시작합니다. 정책이 없으면 서버는 실행 환경의 Codex 홈을 사용하여 로컬 목록 조회만 허용합니다. 제공된 정책은 기본값을 대체합니다. 예시:

```json
{
  "schemaVersion": 1,
  "destinations": {
    "local": {
      "agents": ["claude", "codex"],
      "capabilities": ["list"],
      "codexHome": "/Users/me/.codex"
    },
    "worker": {
      "host": "ubuntu@worker.example.ts.net",
      "agents": ["claude", "codex"],
      "capabilities": ["list", "send"],
      "codexHome": "/home/ubuntu/.codex"
    }
  }
}
```

실제 사용자 이름과 SSH 목적지, 구성된 키 및 known_hosts를 사용하십시오. 이 파일에는 비밀번호를 넣지 마십시오. 모든 Codex 목적지는 해당 목적지의 절대 경로 홈을 고정해야 합니다. 추가 홈에 대해서는 별도의 목적지 ID를 추가하십시오. 신뢰할 수 없는 프로세스에 의한 수정으로부터 정책을 보호하십시오. SSH 구성은 운영자가 제어합니다.

`codex mcp add session-peer -- /absolute/path/session-peer-mcp --config /absolute/path/policy.json`을 사용하여 등록하거나, 저장소의 `plugins/session-peer` 번들을 사용하십시오: `codex plugin marketplace add /absolute/path/to/session-peer` 실행 후 `codex plugin add session-peer@session-peer`. 플러그인은 PATH에서 `session-peer-mcp`를 실행하고 환경에 설정된 경우 `SESSION_PEER_MCP_CONFIG`를 읽습니다. 먼저 Python extra를 설치하십시오. Python 패키지를 설치해도 기존 Codex 설정은 수정되지 않습니다.

## 도구 및 권한

- `list_sessions(destination="local", agent=null, include_inactive=false)`는 CLI의 구조화된 목록을 반환합니다. Agent는 `claude` 또는 `codex`일 수 있으며, 생략 시 허용된 에이전트를 나열합니다.
- `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30)`는 `send`가 명시적으로 허용된 곳에만 1회 제출합니다. Target은 Claude 이름/PID, `codex:<UUID>`, 또는 구성된 호스트 및 홈과 정확히 일치하는 Reply-To URI입니다.

MCP 도구 어노테이션은 목록 조회를 읽기 전용으로, 전송을 멱등하지 않음으로 표시합니다. 필요에 따라 호스트 클라이언트의 도구 승인을 구성하십시오. 서버 정책은 목적지를 독립적으로 제한하며 샌드박스/호스트 승인을 우회하지 않습니다. 다른 호스트 이름이 동일한 머신으로 확인되더라도 Reply-To URI의 SSH 별칭은 정책과 정확히 일치해야 합니다. 그렇지 않은 경우 직접 대상 및 구성된 목적지 ID를 사용하십시오.

응답은 MCP structuredContent 및 텍스트 모두에서 CLI JSON 필드를 보존합니다. 부분적인 목록 조회 실패는 검색된 세션을 유지하고 isError를 설정합니다. 큐 제출은 소비가 아닙니다. 알 수 없는 결과의 전송을 절대 자동으로 재시도하지 마십시오. 원격 제출 후 취소 또는 트랜스포트 유실이 발생할 수 있습니다. 수신 확인/상태 확인/대기 도구는 없습니다. [명시적 wake](wake.md)는 `send` 외에 별도의 `wake` 기능이 필요합니다. wake를 활성화할 때 클라이언트 도구 타임아웃을 150초로 구성하십시오.

공유 MCP 프로세스는 호출 스레드를 안정적으로 식별할 수 없습니다. 메시지는 서버를 시작한 세션에 귀속시키는 대신 `session-peer MCP (caller session unavailable)`을 식별하고 Reply-To를 생략합니다. 인증을 위해 이 헤더에 의존하지 마십시오. 메시지 본문은 셸 명령 문자열이 아닌 stdin을 통해 전달되며, 일반적인 CLI 제한이 계속 적용됩니다.

## 검증

MCP extra가 있는 상태와 없는 상태에서 각각 `python -m unittest discover -s tests -v`를 실행하십시오. 선택형 테스트는 실제 stdio MCP 서버를 시작하고 모델 자격 증명 없이 초기화, 스키마, 정책 거부 및 CLI 부분 실패를 실행합니다. wheel 및 sdist 설치를 모두 테스트하십시오. 실시간 확인 시에는 Codex 버전, OS 및 호스트 승인 설정을 기록해야 합니다. UDS 접근은 환경에 따라 다르며 승인 우회를 약속하는 것이 아닙니다. 메시지에는 전용 테스트 세션을 사용하십시오.

공식 참조: [Codex MCP](https://developers.openai.com/codex/extend/mcp), [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).

### 비대화형 클라이언트 승인

서버 정책이 허용하더라도 Codex `exec`는 전송 도구를 “requires approval, but approval policy is never”로 거부할 수 있습니다. `approval_mode="auto"`는 무조건적인 승인이 아닙니다. 비대화형 연동을 명시적으로 승인하는 운영자는 제한된 목적지 정책과 함께 해당 특정 MCP 서버/도구에 대해 `mcp_servers.session_peer.tools.send_message.approval_mode="approve"`를 구성할 수 있습니다. 플러그인은 이 설정을 활성화하지 않습니다. 대화형 클라이언트는 대신 일반적인 승인 프롬프트를 사용할 수 있습니다. 테스트 클라이언트는 이 승인을 관련 없는 서버나 도구에 복사해서는 안 됩니다.
