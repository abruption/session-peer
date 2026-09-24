# 페어링된 기기 및 비공개 릴레이 (v1.0)

이 선택형 Unix/Python 3.11+ 트랜스포트는 운영자가 정의한 Claude, Codex 또는 등록된 Antigravity 엔드포인트로 요청을 전달합니다. 일반적인 로컬/SSH 명령은 의존성 없는 상태로 유지됩니다. 이는 명시적인 CLI 워크플로이며, 모바일 애플리케이션, NAT 통과, WireGuard 터널 또는 자동 공용 서비스는 설치되지 않습니다.

## 연결 실패 진단과 안전한 연결 재시도

`no_authenticated_route`는 `retryAllowed:false`, `consumptionConfirmed:false`를 유지합니다. `routeFailures`는 경로별 마지막 `stage`, 허용 목록의 `reason`, `attempts`를 표시합니다. 제한된 `attemptHistory`는 각 시도의 단계·사유·`elapsedMs`를 보존하며 HTTP 거부에는 `httpStatus`, WebSocket 종료에는 `closeCode`가 포함될 수 있습니다. 제어, 입장, 업그레이드, attach, 피어 TLS 및 probe 실패를 구분하되 URL·자격증명·원문 예외·메시지 본문은 기록하지 않습니다. 두 번째 연결이 성공하면 `setupDegraded:true`, `setupAttempts:2`, `setupFailureHistory`가 표시되며 깨끗한 안정성 통과로 계산하지 않습니다.

**WebSocket 업그레이드 전 제어·입장 시간 초과**에만 0.5초 후 한 번 더 Relay에 연결합니다. attach, 피어 TLS 및 probe 시간 초과는 재시도하지 않습니다. WebSocket 업그레이드 시간 초과도 원본에서 이미 수신자 방을 페어링했을 수 있어 재시도하지 않습니다. 새 입장 티켓과 채널을 사용하며 소비된 티켓이나 에이전트 메시지를 재전송하지 않습니다. HTTP 거부, 인증/인증서 오류, 알 수 없는 실패도 재시도하지 않습니다. 직접 연결이 선택되면 Relay 시도는 취소될 수 있습니다. 제출 후 응답 손실은 여전히 `unknown`이며 재전송이나 경로 전환을 하지 않습니다. 이 제한된 완화 조치가 공개 경로 장애 해결을 입증하지는 않습니다. 배포 후 실제 ACK와 장시간 검증을 다시 통과해야 합니다.

수신자는 정제된 `relay_connection_failed` 경고를 stderr에 분당 최대 한 번 출력합니다. 정상 유휴 만료로 보이는 종료는 실패 경고와 분리합니다. `device serve --diagnostic-events`와 `relay serve --diagnostic-events`를 명시적으로 사용하면 방·attach·종료 단계, 소요 시간, 허용 목록의 사유·종료 코드만 stderr에 기록합니다. 기본값은 꺼짐이며 기기 신원, 방 이름, URL, 헤더, 자격증명, 본문은 기록하지 않습니다. Relay 지표에는 방 열림·페어링, 각 레그의 attach 전송 및 만료 카운터가 추가됩니다. attach 전송은 클라이언트 수신의 증명이 아닙니다. 수신자 관점의 `idle_expiry_like`는 서버 원인의 확증이 아닙니다.

WebSocket 종료의 `closeSource`는 코드가 수신됐는지 송신됐는지 구분합니다. Relay 지표는 수신자 선착·클라이언트 선착 방을 구분합니다. `receiverWsAgeMs`는 수신자 대기 시간이지 연결 생존의 증거가 아닙니다. 방 페어링과 수신자의 `attach_received`·피어 TLS 이벤트 시각을 대조해야 합니다.

`stream_close.closeCode`는 원격에서 수신한 종료 코드입니다. `1006`은 종료 프레임을 받지 못했다는 뜻이며 레그 정체 가능성을 시사합니다. `peer_closed`는 상대 레그가 끝나 Relay가 이 레그를 닫은 경우, `remote_going_away`는 Relay의 닫기 요청 없이 원격 엔드포인트가 1001을 보낸 경우입니다. `receiverRoleBusy`·`clientRoleBusy`는 같은 방에서 거절된 중복 레그 수이며, 수신자 값이 늘면 수신자가 재연결하는 동안 Relay가 이전 레그를 아직 붙잡고 있을 수 있습니다.

명시적으로 켠 Relay·수신자 수명주기 이벤트에는 `eventTimeUtcMs`(UTC Unix 밀리초)가 포함됩니다. 클라이언트는 Relay 연결 시도마다 임의 UUIDv4 `attemptId`를 새로 만들고 성공 결과 또는 시도별 실패 메타데이터에 기록합니다. 새 Relay는 이 ID를 페어링된 방 이벤트에 기록하고 새 수신자에게 attach 알림으로 전달합니다. 수신자의 `attach_received`·peer-TLS 이벤트에도 같은 ID가 남습니다. 이 ID는 신원·방 이름·요청 ID·메시지 내용에서 파생되지 않으며 인가나 재전송 안전성을 바꾸지 않습니다. 실패를 귀속하려면 정확한 `attemptId`가 Relay 방 하나와 수신자 레그 하나에만 대응하는지 확인하고 시계 오차를 고려해 UTC 시각을 대조하십시오. 이벤트가 없거나 중복되거나 구버전 레그라면 시각·집계값만으로 추정하지 말고 `unattributed`로 기록하십시오.

공개 경로 정체가 재발하면 명시적으로 켠 Relay의 `stream_close` 이벤트에서 각 레그의 `ingressFrames`/`ingressBytes`, `egressCompletedFrames`/`egressCompletedBytes` 및 첫·마지막 UTC 프레임 시각을 비교할 수 있습니다. 이는 암호화된 WebSocket 프레임 수이지 메시지 수가 아닙니다. 송신 완료는 Relay의 소켓 send가 반환됐다는 뜻일 뿐 Cloudflare·수신자·TLS·애플리케이션이 바이트를 소비했다는 증거가 아닙니다. 같은 방·`attemptId` 아래 두 역할을 비교한 뒤 수신자 이벤트와 대조하십시오. 이벤트가 없거나 매칭이 모호하면 `unattributed`로 유지합니다. 카운터만으로 Cloudflare·OCI·중간 홉의 귀책을 정할 수 없습니다. 메타데이터 시각과 프레임 크기만으로도 활동이 드러날 수 있으므로 opt-in 로그를 비공개·한정 보존하십시오.

1초 이상 열려 있던 대기 방이 Relay에 의해 정상 종료되면 수신자는 백오프를 늘리지 않고 0.5초 뒤 다시 연결합니다. 그 밖의 실패와 1초 안에 닫힌 방은 계속 최대 5초까지 지수 백오프합니다. Relay 레그는 양쪽 모두 10초 WebSocket ping 간격·제한을 사용하므로 정체된 레그를 약 40초가 아닌 약 20초 안에 감지합니다. 이는 재연결 공백을 줄일 뿐 정체된 네트워크 경로를 고치지는 않습니다.

## 설치

양쪽 기기 모두 격리된 환경에서 PyPI의 session-peer v0.9.0 이상을 설치합니다:

```sh
python3 -m venv ~/.local/share/session-peer-relay/venv
~/.local/share/session-peer-relay/venv/bin/pip install 'session-peer[relay]'
```

릴레이 extra는 v0.9.0부터 PyPI에서 제공됩니다. 패키지 발행은 호스팅 Relay의 가용성을 보장하지 않습니다. 아래에 표시된 설치된 `session-peer` 실행 파일을 사용하십시오. 관리 명령(`device`/`relay`)은 JSON을 출력합니다. 패키지 버전이 서로 다른 Python 환경을 혼용하지 마십시오.

## 신원, 정책 및 페어링

각 엔드포인트에서:

```sh
session-peer device init --state /private/device-state
```

반환된 `device`는 해당 기기의 공개 인증서 지문입니다. 각 기기는 자체 개인 키를 유지합니다. 해당 키를 릴레이나 다른 엔드포인트로 절대 복사하지 마십시오. 새로운 비공개 상태 디렉터리(0700)를 사용하십시오. 사용자 데이터를 조용히 chmod하는 대신 기존의 안전하지 않은 파일/디렉터리를 거부합니다. 이 데이터베이스는 session-peer 자체의 기기 저널이며, Codex 대화 DB나 온톨로지 볼트 DB가 아닙니다.

수신 머신에서 0600 정책 파일을 생성합니다. 클라이언트 지문, 에이전트 대상 및 홈을 독립적으로 조회한 값으로 바꿉니다. 예를 들어:

```json
{
  "targets": {
    "review": {
      "agent": "codex",
      "target": "codex:FULL-THREAD-UUID",
      "codexHome": "/home/alice/.codex",
      "codexBin": "/home/alice/.local/bin/codex"
    }
  },
  "peers": {
    "CLIENT-64-HEX-FINGERPRINT": {
      "capabilities": ["list", "send"],
      "targets": ["review"]
    }
  }
}
```

Claude 바인딩은 `agent: claude`와 홈 없는 정확한 세션 이름/PID를 사용합니다. Antigravity 바인딩은 `agent: antigravity`, `target: antigravity:UUID` 및 `antigravityHome`을 사용합니다. 먼저 [해당 브리지 절차](antigravity.md)를 사용하여 TUI를 등록하십시오. 수신자는 이러한 에이전트 세션을 소유한 계정으로 실행됩니다. 단지 다른 사용자의 세션에 접근하기 위해 수신자를 루트로 실행하지 마십시오.

페어링은 기기 키 소유를 증명합니다. **이는 네이티브 에이전트 접근 권한을 부여하지 않습니다**: 수신 정책이 지문, 작업 및 대상 별칭을 별도로 허용해야 합니다. 피어는 실행 파일, 홈, wake 플래그, SSH 목적지 또는 임의의 네이티브 명령 인자를 제공할 수 없습니다. 정책 변경은 수신자를 재시작한 후에 적용됩니다. 제한: 구성된 대상 8개 및 정책 기기 128개.

launchd나 systemd로 시작한 수신자는 로그인 셸이 아닌 서비스 관리자의 최소 `PATH`를 물려받습니다. macOS/Linux Codex 대상은 대상 TUI가 쓰는 `codex` 디렉터리를 수신기 서비스의 `PATH`에 넣거나(예: launchd `EnvironmentVariables.PATH`, systemd `Environment=PATH=...`), 운영자 소유 바인딩의 `codexBin`을 `/opt/homebrew/bin/codex`처럼 `codex`로 끝나는 절대 경로로 지정할 수 있습니다. 수신자는 기동 시 실행 가능한 일반 파일을 검증하고 심볼릭 링크를 실제 대상으로 해석합니다. Unix Codex에는 `codexPython`을 사용하지 않습니다. 기존의 활성 writer 및 홈 검사는 그대로 적용됩니다. 실제 전송 전에 같은 수신기 환경에서 `send --dry-run`으로 확인하십시오. 실행 파일이 없으면 제출 전에 `codex_executable_not_found`로 거부합니다. 결과가 unknown인 전송은 자동 재시도하지 마십시오.

## 네이티브 Windows Codex용 WSL 수신자

같은 Windows 워크스테이션에서 Codex 세션과 CLI가 네이티브로 실행될 때 수신자는 WSL2에서 실행합니다. 페어링된 피어가 아니라 운영자 정책이 마운트된 상태 홈과 실행 파일을 모두 고정합니다:

```json
{
  "targets": {
    "windows-review": {
      "agent": "codex",
      "target": "codex:FULL-THREAD-UUID",
      "codexHome": "/mnt/c/Users/alice/.codex",
      "codexBin": "/mnt/c/Users/alice/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe",
      "codexPython": "/mnt/c/Python313/python.exe"
    }
  },
  "peers": {
    "CLIENT-64-HEX-FINGERPRINT": {
      "capabilities": ["list", "send"],
      "targets": ["windows-review"]
    }
  }
}
```

`codexHome`은 로컬 Windows 드라이브에 마운트된 절대 WSL 경로입니다. `codexBin`과 필수 항목 `codexPython`은 각각 `codex.exe`, `python.exe`라는 이름의 절대 경로이며 운영자가 관리하는 실행 가능한 일반 파일이어야 합니다(심볼릭 링크 금지). 인터프리터에는 Microsoft Store 실행 별칭이 아닌 설치된 네이티브 Windows Python 3.9+를 지정합니다.

고정 인자의 `/usr/bin/wslpath`로 경로를 변환하고 자체 standalone 코드를 네이티브 Python으로 스트리밍합니다. 셸 명령은 만들지 않습니다. Windows SQLite/WAL과 writer 잠금은 네이티브 Python이 확인하며 유일한 소유자·동일 사용자 SID·프로세스 생성 시각·Codex 실행 파일 신원을 검증합니다. Linux SQLite로 Windows DB를 열거나 writer 검사를 우회하지 않습니다. 비활성·모호·검사 불가능한 writer는 거부합니다. 기존 WSL 정책에도 `codexPython`을 추가해야 하며 누락·잘못된 인터프리터는 `native_windows_python_required` 또는 `invalid_codex_python`으로 거부합니다.

Linux/macOS 대상은 `codexPython`을 생략하고 위와 같이 `codexBin`을 선택적으로 설정할 수 있습니다. Windows 클라이언트는 일반 로컬 CLI를 계속 사용합니다. 성공한 제출도 `consumptionConfirmed: false`이며 소비는 별도의 실제 응답으로 확인해야 합니다. 정책이나 수신자를 갱신해도 기존 unknown 전송을 자동 재시도하지 마십시오.

네이티브 로컬 CLI 지원이 모든 Windows SSH 셸 지원을 뜻하지는 않습니다. 소스 스트리밍 SSH에는 동작하는 python3와 POSIX 호환 원격 셸이 필요하며 Windows Store 실행 별칭만으로는 부족합니다. 네이티브 CLI를 로컬에서 사용하거나 Python이 설치된 WSL SSH 엔드포인트를 사용하십시오.

직접 수신자를 시작합니다(기본값은 루프백이며, 다른 머신을 위해 연결 가능한 사설 인터페이스를 선택하십시오):

```sh
session-peer device serve --state /private/device-state \
  --policy /private/receiver-policy.json --bind PRIVATE-IP --port 3770 --seconds 3600
session-peer device invite --state /private/device-state \
  --direct PRIVATE-IP:3770 --out /private/invitation.json
```

신뢰할 수 있는 채널을 통해 초대장을 클라이언트의 비공개 파일로 전송한 후, 10분 이내에 실행합니다:

```sh
session-peer device pair --state /private/client-state \
  --invite /private/invitation.json --route direct
```

초대장에는 일회용 시크릿과 고정된 수신자 인증서가 있습니다. 보류 중인 페어링은 동일한 기기 키를 증명하여 유실된 커밋 응답을 조정할 수 있습니다. 인증서 대체는 실패합니다. 페어링 후에는 초대장 파일을 삭제하십시오. 시크릿이 포함되어 있습니다. IPv6 직접 주소는 `[address]:port` 형식을 사용합니다. 직접 접근에는 TCP 연결 가능성이 필요합니다. 자동 라우터, 방화벽, VPN 또는 NAT 구성은 제공되지 않습니다.

## 비공개 릴레이 프로비저닝

신뢰할 수 있는 관리 머신에서:

```sh
session-peer relay provision --out /private/new-room --room personal
```

이렇게 하면 `accounts.json`(입장 해시), `receiver.token`, `client.token`이 생성됩니다. 각 토큰은 0600 파일로 보관하십시오. 릴레이 서버에는 해시만 설치됩니다. 수신자/클라이언트 입장 토큰은 비공개 기기 신원 키와 별도로 배포하십시오. 토큰은 릴레이 입장을 제어하며, 내부의 고정된 TLS가 페어링 및 네이티브 접근을 독립적으로 제어합니다. 릴레이는 엔드포인트 개인 키를 절대 가져가지 않습니다.

```sh
session-peer relay serve --accounts /private/accounts.json \
  --bind 127.0.0.1 --port 3769 --seconds 3600
```

영구적인 Linux 호스팅의 경우, wheel을 `/opt/session-peer-relay/venv`에 설치하고, 해시를 `/etc/session-peer-relay/accounts.json`에 저장하며, 검토된 [systemd 템플릿](../../deploy/examples/static-account/session-peer-relay.service)을 맞게 수정하십시오. 활성화하기 전에 `systemd-analyze verify`로 검증하십시오. 이 템플릿은 동적 사용자, 권한 없음, 접근 불가능한 홈 디렉터리, 읽기 전용 시스템, 비공개 임시 디렉터리 및 명시적 리소스 제한으로 실행됩니다. 이는 네이티브 수신자가 아닌 **블라인드 릴레이**를 위한 것입니다. 후자는 에이전트 소유의 런타임 경로와 소켓이 필요합니다.

루프백 릴레이를 전용 호스트 이름의 HTTPS/WSS 역방향 프록시 뒤에 둡니다:

```caddyfile
relay.example.com {
    reverse_proxy 127.0.0.1:3769
}
```

이 예제는 기존 프로덕션 Caddyfile을 다시 로드하라는 지침이 아닙니다. 배포 환경의 기존 인증서/DNS 정책을 사용하고, 정확한 diff를 검증하며, 기존 WebSocket 사용자를 확인하고, 롤백을 계획하십시오. 다시 로드/엣지 업데이트로 인해 연결이 끊어질 수 있습니다. URL/쿼리에는 어떤 토큰도 들어가서는 안 됩니다. 헤더/본문 디버그 로그를 피하십시오. 프록시는 IP, 호스트 이름 및 입장 메타데이터를 볼 수 있지만, 애플리케이션 메시지와 페어링 시크릿은 엔드포인트 TLS1.3 내에 유지됩니다. 외부 TLS 검증을 비활성화하지 마십시오.

`--relay wss://relay.example.com/v1/connect` 및 `--admission-file /private/receiver.token`으로 수신자를 시작한 다음, 해당 `--relay` URL(및 선택적으로 `--direct`)을 사용하여 초대장을 생성합니다. 클라이언트는 `--route relay` 및 `--admission-file /private/client.token`을 사용하여 페어링할 수 있습니다. 일반 텍스트 `ws://`는 격리된 테스트를 위해 루프백으로 제한됩니다. 수신자 준비 완료 출력은 로컬 리스너를 확인하는 것이며, `relayReadyConfirmed: false`는 의도적으로 엔드투엔드 릴레이 준비 완료를 주장하지 않습니다.

## 목록 조회, 전송 및 조정

```sh
session-peer list --device RECEIVER-FINGERPRINT --device-state /private/client-state \
  --relay-admission-file /private/client.token --json
session-peer send --device RECEIVER-FINGERPRINT --device-state /private/client-state \
  --relay-admission-file /private/client.token --device-route auto \
  --to review --message 'Please inspect the proposed change' --json
```

`--to`는 수신 정책에서 허용된 대상 별칭이며, 임의의 네이티브 UUID나 셸 명령이 아닙니다. `--agent`는 허용된 목록 결과를 필터링합니다. 기기 라우팅은 `--host`와 상호 배타적입니다. 네이티브 홈/바이너리/SSH 옵션은 수신 정책에 속하며 페어링된 요청에서는 거부됩니다. 여기서는 `--wake` 및 명시적 SSH Reply-To가 지원되지 않습니다. 설명용 From 헤더는 유지되지만, 자동 페어링 Reply-To 경로는 공지되지 않습니다. 이 베타에서는 MCP 기기 목적지가 구현되지 않았으며, 기존 로컬/SSH 정책은 변경되지 않고 유지됩니다.

자동 라우팅은 인증된 준비 상태 프로브를 경합시켜 둘 다 동시에 완료되면 직접 연결을 선호합니다. 선택된 **하나의** 연결로 애플리케이션 요청을 전송합니다. 불확실한 제출 후 페일오버하여 재전송하지 않습니다. 경로를 강제하려면 `--device-route direct` 또는 `relay`를 설정하십시오. 메시지는 봉투를 제외하고 32 KiB UTF-8로 제한됩니다. `--dry-run`은 네이티브 제출 없이 구성된 네이티브 대상을 확인합니다.

`submitted`/`queued`는 소비와 명확히 구분됩니다. `consumptionConfirmed`는 항상 false입니다. 모델 ACK는 독립적으로 관찰되어야 합니다. 네이티브 작업은 제한된 하위 프로세스에서 실행되므로 입장/철회를 차단할 수 없습니다. 영구적인 요청 의도는 네이티브 효과가 발생하기 전에 커밋됩니다. 동일한 요청 ID 및 정규 대상 바인딩/본문은 기록된 결과를 반환하며, 대상/본문을 변경하면 충돌이 발생합니다.

시도 식별자를 유지하려면 `--request-id UUID`를 사용하십시오. 응답이 유실된 경우 새 ID를 생성하는 대신 원본 ID를 쿼리하십시오:

```sh
session-peer device status --state /private/client-state --peer RECEIVER-FINGERPRINT \
  --request-id ORIGINAL-UUID --admission-file /private/client.token
```

`unknown`(수신자/워커 충돌 포함)은 결코 자동 재실행을 허용하지 않습니다. 이는 최대 한 번 실행 시도이며, 정확히 한 번 소비가 아닙니다. 저널은 10,000개의 요청으로 제한되며 가득 차면 더 이상의 새로운 제출을 거부합니다. 알 수 없는 항목을 재시도하기 위해 보류 중인 항목을 삭제하거나 저널을 비우지 마십시오. v1.0 CLI는 저널을 자동 순환하거나 장기 운영 플릿을 관리하지 않습니다. 운영자는 미확정 결과를 폐기하지 않는 범위에서 용량과 보존을 계획해야 합니다.

## 철회, 재시작 및 복구

```sh
session-peer device peers --state /private/device-state
session-peer device revoke --state /private/device-state --peer CLIENT-FINGERPRINT
```

철회는 새로운 승인 작업을 방지하고 추적된 채널을 닫습니다. 이미 수락된 네이티브 호출은 완료될 수 있으며, 해당 ID를 조정하십시오. 수신자 재시작 시 신원, 페어링 및 저널이 보존됩니다. 릴레이 재시작 시 연결이 끊어지며, 엔드포인트가 다시 연결되어 새로운 입장을 획득합니다. 새 제출 전에 준비 상태 프로브가 성공해야 합니다. 릴레이 티켓은 수명이 짧고 일회용이며, 연결 및 프레임은 제한되어 있습니다. 릴레이에는 일반 텍스트/오프라인 네이티브 요청 큐가 없습니다.

기본 포그라운드 서비스 수명은 1시간입니다. `--seconds 0`은 서비스 관리자를 위한 영구 작동을 명시적으로 선택합니다. SIGTERM으로 중지하고 정리 전에 제한된 네이티브 종료를 기다리십시오. 일관된 SQLite 스냅샷과 신원 파일을 사용하여 비공개 상태를 백업하고, 해당 백업을 보호하며, 활성 DB를 WAL과 별도로 복사하지 마십시오. 신원 인증서의 유효 기간은 1년입니다. 만료 시 기기 핀을 조용히 교체하는 것이 아니라 계획된 새 신원/재페어링이 필요합니다.

격리된 실시간 검증은 루프백/SSH 터널을 사용하며, VPN이 꺼진 상태의 공용 WSS 준비 상태를 입증하지는 않습니다. 공개 파일럿, 재시작/소크 테스트 및 릴리스 게이트는 [진행 중인 개발 계획](relay-development-plan.md)에서 추적됩니다.

### 페어링된 경로 업데이트

페어링된 기기의 주소가 변경될 때 고정된 신원과 전달 저널을 유지합니다. 이는 저장된 경로를 대체하므로 유지하려는 모든 경로를 포함하십시오.

```sh
session-peer device routes --state ./client-state --peer RECEIVER_FINGERPRINT \
  --relay wss://relay.example.com/v1/connect
```

경로 변경이 새 신원을 승인하거나 철회된 기기를 되살리지는 않습니다. 제한된 실시간 Antigravity 테스트 및 남은 릴리스 게이트에 대해서는 [공개 파일럿 근거](relay-public-pilot-2026-09-17.md)를 참조하십시오.
