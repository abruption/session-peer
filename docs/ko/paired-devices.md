# 페어링된 기기 및 비공개 릴레이 (v0.9 베타)

이 선택형 Unix/Python 3.11+ 트랜스포트는 운영자가 정의한 Claude, Codex 또는 등록된 Antigravity 엔드포인트로 요청을 전달합니다. 일반적인 로컬/SSH 명령은 의존성 없는 상태로 유지됩니다. 이는 명시적인 CLI 워크플로이며, 모바일 애플리케이션, NAT 통과, WireGuard 터널 또는 자동 공용 서비스는 설치되지 않습니다.

## 설치

양쪽 기기 모두 격리된 환경에서 PyPI의 session-peer v0.9.0 이상을 설치합니다:

```sh
python3 -m venv ~/.local/share/session-peer-relay/venv
~/.local/share/session-peer-relay/venv/bin/pip install 'session-peer[relay]'
```

릴레이 extra는 v0.9.0부터 PyPI에서 제공되며 베타 상태로 유지됩니다. 배포 자체가 장기적인 운영 안정성을 보장하지는 않습니다. 아래에 표시된 설치된 `session-peer` 실행 파일을 사용하십시오. 관리 명령(`device`/`relay`)은 JSON을 출력합니다. 패키지 버전이 서로 다른 Python 환경을 혼용하지 마십시오.

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
      "codexHome": "/home/alice/.codex"
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

## 네이티브 Windows Codex용 WSL 수신자

같은 Windows 워크스테이션에서 Codex 세션과 CLI가 네이티브로 실행될 때 수신자는 WSL2에서 실행합니다. 페어링된 피어가 아니라 운영자 정책이 마운트된 상태 홈과 실행 파일을 모두 고정합니다:

```json
{
  "targets": {
    "windows-review": {
      "agent": "codex",
      "target": "codex:FULL-THREAD-UUID",
      "codexHome": "/mnt/c/Users/alice/.codex",
      "codexBin": "/mnt/c/Users/alice/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe"
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

`codexHome`은 로컬 Windows 드라이브에 마운트된 절대 WSL 경로여야 하고, `codexBin`은 이름이 `codex.exe`인 절대 경로의 실행 가능한 일반 파일이어야 합니다. 수신자는 POSIX 경로로 데이터베이스를 읽고, 고정 인자로 `/usr/bin/wslpath`를 호출한 뒤 드라이브가 명시된 Windows 경로를 네이티브 자식의 `CODEX_HOME`으로만 전달합니다. 셸 명령은 만들지 않습니다. WSL이 아닌 호스트, 누락된 실행 파일 또는 안전하지 않은 변환은 정책 로드 중 `wsl_codex_requires_wsl`, `invalid_codex_executable` 또는 `wsl_home_conversion_failed`로 실패합니다. Linux/macOS Codex 대상은 `codexBin`을 생략하며 기존 동작을 유지합니다. 네이티브 Windows 클라이언트는 계속 일반 로컬 CLI를 사용합니다. 이 어댑터는 Windows Codex를 대상으로 하는 WSL 수신자 전용입니다. Windows writer 잠금은 POSIX advisory lock이 아니므로 이 명시적 바인딩은 네이티브 세션이 비활성일 때도 고정 홈에 큐를 넣을 수 있습니다. 성공한 제출도 그 세션이 소비하기 전까지 `consumptionConfirmed: false`를 보고합니다.

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

`unknown`(수신자/워커 충돌 포함)은 결코 자동 재실행을 허용하지 않습니다. 이는 최대 한 번 실행 시도이며, 정확히 한 번 소비가 아닙니다. 저널은 10,000개의 요청으로 제한되며 가득 차면 더 이상의 새로운 제출을 거부합니다. 알 수 없는 항목을 재시도하기 위해 보류 중인 항목을 삭제하거나 저널을 비우지 마십시오. 보존/순환 및 장기 실행 플릿 관리는 RC 강화 작업으로 남아 있습니다.

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
