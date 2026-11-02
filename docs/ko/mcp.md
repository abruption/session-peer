# 선택형 Codex MCP 연동

Python 3.10 이상에서 설치하십시오: `pipx install 'session-peer[mcp]'`(또는 격리된 venv에 extra 설치). 의존성이 없는 Python 3.9 CLI 및 `install.sh`는 계속 지원됩니다. 셸 설치기는 MCP 의존성을 설치하지 않습니다. Python 3.9에서 MCP 엔트리 포인트는 Python 3.10+이 필요하다고 보고합니다.

선택형 extra는 MCP SDK `mcp>=1.30,<2`를 요구합니다. 업스트림 1.x 보안 수정이 포함된 버전으로 의존성 하한을 올리는 것으로, stdio만 사용하는 이 서버에서 악용 가능한 결함이 확인됐다는 뜻은 아닙니다. 이번 변경으로 HTTP 전송, OAuth 서버 경로, MCP 클라이언트 경로가 활성화되지는 않습니다. 기존 환경에는 명시적인 패키지 업그레이드가 필요하며, 선언 변경만으로 설치된 SDK가 업데이트되지는 않습니다.

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

## 미출시 v1.4.0 후보: 목적지 조회 (#356)

`list_destinations()`는 인자를 받지 않으며 운영자 정책의 메타데이터만 반환합니다. `schemaVersion`은 1이고 각 항목은 `destination`, `transport`, `agents`, `capabilities`를 포함합니다. 자식 프로세스를 시작하거나 네트워크 요청을 보내지 않습니다. SSH 호스트 값과 Codex 홈 경로는 생략됩니다. 목적지 이름은 신뢰할 수 없는 데이터입니다. 구성된 기능은 정책상 권한을 나타내며 네이티브 에이전트와의 호환성을 나타내지는 않습니다.

응답은 한계를 명시합니다: `callerIdentity="unavailable"`, `readiness="not_checked"`, `submission="not_attempted"`, `consumption="not_checked"`, `ack="not_checked"`. 이 도구는 목적지가 64개를 넘거나 ID에 출력할 수 없는 문자가 있거나 UTF-8 기준 128바이트를 넘으면 조회를 거부합니다. 텍스트와 구조화된 내용을 합친 MCP 도구 결과는 64 KiB 이내이며, 바깥 JSON-RPC 봉투는 이 한도에 포함되지 않습니다. 이는 조회 도구의 제한으로, 정책 읽기와 기존 도구의 동작은 바뀌지 않습니다. 출력 가능한 문자 판정에는 실행 중인 Python의 유니코드 데이터베이스를 사용합니다. 기본 로컬 목록 조회 전용 정책은 그대로 유지됩니다.

## 미출시 v1.4.0 후보: 전송 사전 검증 (#357)

`preflight_send(destination, target, message, wake=false, wake_timeout=30)`는 기존 CLI dry-run 검사로 일반 메시지를 검증합니다. 운영자 정책은 `schemaVersion` 2를 사용하고 해당 목적지와 에이전트에 `preflight`를 명시적으로 허용해야 합니다. 버전 1의 기존 기능 집합에는 새 권한이 추가되지 않으며, 기본값은 로컬 목록 조회 전용으로 유지됩니다. 사전 검증에는 `send`가 필요하지 않으며 전송 권한을 부여하지 않습니다. wake 적격성을 검사하려면 별도로 `wake`가 필요하지만, 모델을 활성화하거나 wake 예산을 예약하지는 않습니다.

버전이 지정된 설명은 SSH 어댑터가 결과를 가공하기 전의 네이티브 응답에서 허용된 사실만 추출하고, 정해진 거부·불확실 사유와 운영자 조치를 제공합니다. 메시지 내용, 원시 오류, 자격 증명, 호스트·홈 경로와 네이티브 기록은 제외됩니다. 결과가 불확실하거나 예상치 못한 제출 증거가 있으면 `retryAllowed=false`로 검증에 실패합니다. 자동으로 재전송하지 마십시오. 사전 검증은 메시지를 제출하거나 handoff 권한을 만들지 않습니다. 기기 및 handoff 모드는 지원하지 않습니다.

기존 dry-run 검사는 로컬·버전 확인 프로세스와 SSH 연결을 시작할 수 있으며, SSH 설정 자체도 명령을 실행할 수 있습니다. 따라서 이 도구는 `readOnlyHint=false`와 `openWorldHint=true`를 사용합니다. 호스트 승인은 정책 권한과 별개입니다. 통과는 검사 시점의 결과이며, 경로 예약, 유효 저장소의 증명, 승인, 이후 전송의 보장, 소비 또는 ACK를 뜻하지 않습니다.

## 미출시 v1.4.0 후보: 제한된 진단 (#358)

`diagnose_destination(destination="local", agent=null, active_probe=false)`는 `schemaVersion` 2 정책의 명시적인 `diagnostics` 권한이 필요합니다. 기본 모드는 정책 메타데이터와 선언된 에이전트 기능만 반환하며, CLI나 검색 프로세스를 시작하거나 네트워크를 요청하지 않습니다. 목적지 ID에는 목적지 조회와 같은 출력 가능 문자 및 UTF-8 128바이트 제한이 적용됩니다. 버전 1과 기본 정책은 진단 권한을 부여하지 않습니다. 기본 모드의 `declaredCapabilities`는 어댑터 선언에서 가져온 불리언 값이며, 실제 전달이나 준비 상태를 입증하지 않습니다.

`active_probe=true`를 지정하면 `diagnostics_probe`도 필요합니다. 메타데이터 모드는 모든 플랫폼에서 지원합니다. 능동 모드는 현재 macOS와 Linux만 지원하며, Windows에서는 CLI 프로세스나 네트워크 요청 없이 고정 사유 `diagnostics_platform_unsupported`를 반환합니다. 검사는 설정된 목적지, 고정된 Codex 홈과 허용된 에이전트만 사용합니다. 에이전트별 doctor 호출은 최대 세 에이전트를 검사하며, 20초의 실행 예산을 공유한 뒤 프로세스를 정리합니다. 이는 엄격한 실제 경과 시간 제한이나 원격 프로세스 정리의 보장이 아닙니다. 자식 프로세스의 stdout과 stderr는 각각 64 KiB로 제한됩니다. Codex 검사는 선택한 홈만 확인합니다. 역방향 경로 검사, 메시지 제출, 네이티브 모델 활성화 또는 자동 재시도는 수행하지 않습니다. 능동 검사는 CLI 프로세스와 SSH 연결을 시작할 수 있으며 운영자의 SSH 설정이 명령을 실행할 수도 있습니다. 호스트 승인은 정책 권한과 별개입니다. 선택적 능동 검사가 운영자 SSH 설정을 실행할 수 있으므로 통합 도구는 `readOnlyHint=false`와 `idempotentHint=false`를 사용합니다.

응답은 허용 목록의 상태와 진단 코드만 노출하고 원시 오류, 호스트 이름, 홈 경로, 인증정보, 세션 내용과 알 수 없는 응답 필드를 제외합니다. 메타데이터 모드는 준비 상태를 검증하지 않으며, 능동 결과도 검사 시점의 상태일 뿐 소비나 ACK의 증거 또는 전송 권한이 아닙니다. 텍스트와 구조화된 도구 결과를 합친 크기는 64 KiB로 제한됩니다.

상태·검사 필드가 없거나 잘못되었거나, 일부 검사가 누락되거나 검사 목록이 잘린 경우에는 정상으로 표시하지 않고 알 수 없음·불완전(`diagnostic_incomplete`)으로 보고합니다. 전송 단계 `tcpAccept`, `tls`, `peerAuthentication`은 모두 `not_checked`로 남으며 진단에서 별도로 검증하지 않습니다.

후보 MCP 래퍼가 지원하는 검사와 실행 효과는 다음으로 제한됩니다.

| 모드 / 에이전트 | 확인하는 사실 | 프로세스 / 연결 효과 |
| --- | --- | --- |
| 메타데이터 | 정책과 어댑터 선언 | 없음 |
| 능동 Claude | 등록 기록, 프로세스 식별 메타데이터와 파일시스템의 수신함 존재 여부 | 수신함에 연결하지 않음 |
| 능동 Codex | 실행 파일 존재 여부, 선택한 홈의 읽기 전용 SQLite 조회와 제한된 writer 검색 | 네이티브 Codex 실행이나 버전 조회 없음 |
| 능동 Antigravity | 등록된 브리지 메타데이터 | 브리지 또는 네이티브 RPC 없음 |
| 능동 SSH | 명시적인 검사 권한을 받은 뒤 설정된 정방향 경로만 확인 | SSH 설정이 명령을 실행할 수 있음. 역방향 검사나 회신 호스트로의 자동 연결 없음 |

허용된 코드의 예로는 `sessions_dir_missing`, `inbox_present`, `codex_executable_missing`, `state_db_readable`, `unsaved_writer_check_unavailable`, `adapter_failed`가 있습니다. 결과는 허용된 에이전트와 에이전트별 최대 32개 검사로 제한되며, 이 코드는 위의 제한된 범위만 설명합니다.

`ok`는 가용성이 아니라 수집과 형식의 완전성을 나타냅니다. 완전한 `missing_home` 결과도 `ok=true`일 수 있으므로 에이전트별 상태를 따로 확인하십시오. `diagnosticEvidence`는 능동 결과에서 `point_in_time_only`, 메타데이터 모드에서 `not_collected`입니다. 특정 대상의 준비 상태를 검사하지 않으므로 `readiness`는 `not_checked`로 유지됩니다. `state_db_readable` 검사의 통과는 읽기 전용 DB 조회가 성공했다는 뜻일 뿐, 유효 저장소의 증명이나 회신 경로의 보장이 아닙니다.

`tcpAccept`, `tls`, `peerAuthentication` 단계는 `not_checked`로 유지됩니다. 여기서 `peerAuthentication`은 페어링된 기기의 인증을 뜻하며 정방향 SSH 인증과 별개입니다. `sshFailure`는 `authentication_failed` 또는 `host_key_failed`처럼 정제된 정방향 SSH 실패 범주만 보고합니다. TCP, TLS, 페어링된 기기 또는 회신 호스트 검사는 추가하지 않습니다.

## 도구 및 권한

- `list_sessions(destination="local", agent=null, include_inactive=false)`는 CLI의 구조화된 목록을 반환합니다. Agent는 `claude` 또는 `codex`일 수 있으며, 생략 시 허용된 에이전트를 나열합니다.
- `send_message(destination, target, message, dry_run=false, wake=false, wake_timeout=30)`는 `send`가 명시적으로 허용된 곳에만 1회 제출합니다. Target은 Claude 이름/PID, `codex:<UUID>`, 또는 구성된 호스트 및 홈과 정확히 일치하는 Reply-To URI입니다.

MCP 도구 어노테이션은 목록 조회를 읽기 전용으로, 전송을 멱등하지 않음으로 표시합니다. 필요에 따라 호스트 클라이언트의 도구 승인을 구성하십시오. 서버 정책은 목적지를 독립적으로 제한하며 샌드박스/호스트 승인을 우회하지 않습니다. 다른 호스트 이름이 동일한 머신으로 확인되더라도 Reply-To URI의 SSH 별칭은 정책과 정확히 일치해야 합니다. 그렇지 않은 경우 직접 대상 및 구성된 목적지 ID를 사용하십시오.

응답은 MCP structuredContent 및 텍스트 모두에서 CLI JSON 필드를 보존합니다. 부분적인 목록 조회 실패는 검색된 세션을 유지하고 isError를 설정합니다. 큐 제출은 소비가 아닙니다. 알 수 없는 결과의 전송을 절대 자동으로 재시도하지 마십시오. 원격 제출 후 취소 또는 트랜스포트 유실이 발생할 수 있습니다. 수신 확인/상태 확인/대기 도구는 없습니다. [명시적 wake](wake.md)는 `send` 외에 별도의 `wake` 기능이 필요합니다. wake를 활성화할 때 클라이언트 도구 타임아웃을 150초로 구성하십시오.

공유 MCP 프로세스는 호출 스레드를 안정적으로 식별할 수 없습니다. 메시지는 서버를 시작한 세션에 귀속시키는 대신 `session-peer MCP (caller session unavailable)`을 식별하고 Reply-To를 생략합니다. 인증을 위해 이 헤더에 의존하지 마십시오. 메시지 본문은 셸 명령 문자열이 아닌 stdin을 통해 전달되며, 일반적인 CLI 제한이 계속 적용됩니다.

## 검증

MCP extra가 있는 상태와 없는 상태에서 각각 `python -m unittest discover -s tests -v`를 실행하십시오. 선택형 테스트는 실제 stdio MCP 서버를 시작하고 모델 자격 증명 없이 초기화, 스키마, 정책 거부 및 CLI 부분 실패를 실행합니다. wheel 및 sdist 설치를 모두 테스트하십시오. 실시간 확인 시에는 Codex 버전, OS 및 호스트 승인 설정을 기록해야 합니다. UDS 접근은 환경에 따라 다르며 승인 우회를 약속하는 것이 아닙니다. 메시지에는 전용 테스트 세션을 사용하십시오.

CI는 macOS/Linux의 Python 3.10/3.13/3.14에서 SDK 하한 `mcp==1.30.0`과 최신 호환 1.x를 별도로 시험합니다. 두 프로필 모두 stdio·정책·시간 초과·취소·소유 자식 프로세스 정리 시험을 실행하고, 해결된 런타임 의존성 그래프를 감사하며 버전과 보고서를 보존합니다. 전이 의존성 버전은 패키지 관리자가 일반적인 방식으로 결정합니다. 모든 전이 패키지의 최솟값을 시험하는 것은 아닙니다. 버전을 고정한 빌드·감사 요구 패키지는 런타임 환경 밖에 설치하며, 감사 대상 환경에는 초기 구성용 `pip`/`setuptools` 패키지도 포함됩니다. 기존 최신 버전 해결 감사와 릴리스 감사도 계속 필수입니다.

공식 참조: [Codex MCP](https://developers.openai.com/codex/extend/mcp), [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk). [SDK 1.30.0](https://pypi.org/pypi/mcp/1.30.0/json), [GHSA-84m7-p3x7-pcfv](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-84m7-p3x7-pcfv), [GHSA-fmmv-w9g8-j3gc](https://github.com/modelcontextprotocol/python-sdk/security/advisories/GHSA-fmmv-w9g8-j3gc).

### 비대화형 클라이언트 승인

서버 정책이 허용하더라도 Codex `exec`는 전송 도구를 “requires approval, but approval policy is never”로 거부할 수 있습니다. `approval_mode="auto"`는 무조건적인 승인이 아닙니다. 비대화형 연동을 명시적으로 승인하는 운영자는 제한된 목적지 정책과 함께 해당 특정 MCP 서버/도구에 대해 `mcp_servers.session_peer.tools.send_message.approval_mode="approve"`를 구성할 수 있습니다. 플러그인은 이 설정을 활성화하지 않습니다. 대화형 클라이언트는 대신 일반적인 승인 프롬프트를 사용할 수 있습니다. 테스트 클라이언트는 이 승인을 관련 없는 서버나 도구에 복사해서는 안 됩니다.

macOS/Linux에서 MCP CLI 호출은 새 프로세스 그룹을 소유합니다. 완료·시간 초과·취소 시 리더를 회수하기 전에 시간 제한이 있는 TERM→KILL로 해당 그룹을 정리하며 TERM을 무시하는 자식도 포함합니다. 취소는 그대로 전파됩니다. 별도 세션으로 이탈한 자식과 원격 SSH 프로세스는 범위 밖입니다. Windows는 직접 자식 종료만 유지하며 프로세스 트리 보장을 주장하지 않습니다. 로컬 정리는 원격 제출을 취소하지 않습니다. timeout은 `outcome_unknown`이며 자동 재전송하면 안 됩니다.

호출 세션을 알 수 없다는 From 표시를 포함한 MCP 본문은 목적지 CLI의 수신 측 프레임 안에 인용됩니다. 본문 헤더나 본문에 들어 있는 Reply-To는 권한을 부여하지 않습니다. 제삼자 목적지는 세션 소유자에게 확인하십시오. 공유 MCP 프로세스는 여전히 인증된 호출 세션이나 자동 회신 경로를 제공하지 못합니다. 최종 프레임도 네이티브 메시지 한도에 포함됩니다.
