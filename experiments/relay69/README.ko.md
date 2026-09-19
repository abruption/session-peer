# #69 페어링된 기기 릴레이 실험실

로컬 #47 커밋 `993d04d`에 기반한 실험용 픽스처 전용 코드입니다. **프로덕션 수신기, 플러그인 또는 설치된 CLI 명령어가 아닙니다.** 일반 패키지, 로컬/SSH 동작 및 설치된 버전은 변경되지 않습니다. 네이티브 Claude/Codex 세션, 인박스, 큐, 모델 자격 증명 또는 쿼터는 사용되지 않습니다.

## 로컬에서 재현

Python 3.11+ 및 TLS 1.3을 지원하는 OpenSSL이 필요합니다. 테스트된 환경은 macOS Python 3.14/3.13 및 Ubuntu arm64 Python 3.12였습니다.

```sh
python3 -m venv /tmp/session-peer-relay-lab
/tmp/session-peer-relay-lab/bin/pip install -r experiments/relay69/requirements.txt
/tmp/session-peer-relay-lab/bin/python -m unittest tests.test_relay69 -v
```

테스트는 루프백 TCP, 실제 TLS, 로컬 WebSocket 릴레이 및 일회용 상태를 사용합니다. 선택적 의존성이 없으면 일반적인 unittest 검색은 이 모듈을 건너뜁니다. 이 실험은 wheel이나 sdist에 포함되지 않습니다. 어떤 import도 리스너를 시작하지 않습니다.

## 컴포넌트 및 경계

- `identity.py`: 로컬에서 생성된 P-256 개인 키 및 수명이 짧은 자체 서명 인증서입니다. 키/상태는 0600/0700 권한이며 초대장에 포함되거나 릴레이로 복사되지 않습니다. 이는 파일 시스템 보호이며 프로덕션 OS 키체인이 아닙니다.
- `wire.py`: Python/OpenSSL MemoryBIO를 사용하는 TCP 또는 바이너리 WebSocket 프레임 기반의 TLS 1.3/ALPN입니다. 클라이언트는 초대된 인증서를 명시적으로 신뢰하고 고정(pin)합니다. 페어링된 수신기는 list/send 전에 인식된 클라이언트 인증서를 요구합니다. 인증되지 않은 알 수 없는 클라이언트는 연결당 한 번의 초대 예약만 시도할 수 있습니다. 공용 릴레이 URL에는 WSS가 필요하며 일반 텍스트 WS는 루프백 테스트로 제한됩니다. HTTP 및 WS 리디렉션은 거부됩니다.
- `store.py`: 10분 일회용 초대 예약, 보류/페어링/철회된 기기 상태, 에이전트 데이터베이스와 독립적인 실행 저널입니다. 페어링은 상호 TLS가 제안된 키를 증명한 후에만 커밋됩니다. 보류 중인 개시자는 동일한 키로 유실된 커밋 응답을 조정할 수 있습니다. 철회는 활성 채널을 닫으며, 로테이션은 매끄러운 갱신이 아닌 철회 후 새 페어링입니다.
- `relay.py`: 역할/룸 범위의 입장 자격 증명으로 120초 HttpOnly 세션 쿠키를 발급합니다. 인증은 업그레이드 전에 발생합니다. 릴레이는 암호문만 전달하고 엔드포인트 키를 보유하지 않습니다. 릴레이는 라우팅/역할, IP, 시간, 길이 및 암호문을 봅니다. Cloudflare/Caddy는 외부 TLS 메타데이터 **및 입장 자격 증명/쿠키**를 볼 수 있지만 내부 TLS 일반 텍스트나 키는 볼 수 없습니다. 외부 인증은 종단 간 신원이 아니며 피어 TLS 검증을 대체하지 않습니다.
- `app.py`: 수신된 모든 작업은 #47 `LocalTransport` 및 명시적으로 인스턴스화된 결정론적 픽스처 어댑터 하나를 거칩니다. 와이어 작업은 probe/list/send/status이며 임의의 명령어, 경로, 네이티브 어댑터 또는 wake는 사용할 수 없습니다. 요청은 버전, 양측 신원, UUID, 만료 시간, 작업 및 본문을 바인딩하며 TLS 채널은 레코드 무결성 및 재생 보호를 제공합니다.

저널은 픽스처 어댑터를 호출하기 전에 보류 중인 의도를 커밋합니다. 동일한 본문을 가진 동일한 피어+메시지 ID는 저장된 결과를 반환하며, 다른 본문은 거부됩니다. 어댑터 호출과 결과 커밋 사이의 충돌은 알 수 없는 상태로 유지되며 절대 자동으로 재실행되지 않습니다. 이는 활성성보다 최대 한 번 시도를 우선시합니다. 이것은 네이티브의 정확히 한 번 전달이 **아닙니다**. `submitted`는 계속 false로 유지되는 `consumptionConfirmed`와 별개입니다. `relayAttached`는 통신망 연결을 설명하며, 인증된 엔드포인트 프로브만이 수신기의 준비 상태를 확인합니다.

자동 경로는 인증된 직접 프로브와 릴레이 프로브를 경쟁시키며, 동일한 선택 주기에서 둘 다 완료되면 직접 연결을 우선합니다. 메시지는 한 승자에게만 전달됩니다. 제출 후 실패하더라도 경로를 바꾸거나 재전송하지 않습니다. 알 수 없는 결과를 확인할 때는 원래 메시지 ID로 status를 사용하세요.

## 명시적 명령어

실험 venv를 사용하여 작업 트리 루트에서 실행합니다:

```sh
python -m experiments.relay69 init --state /private/test/receiver
python -m experiments.relay69 invite --state /private/test/receiver \
  --out /private/test/invitation.json --direct 127.0.0.1:3769
python -m experiments.relay69 serve --state /private/test/receiver \
  --bind 127.0.0.1 --port 3769 --seconds 1800
python -m experiments.relay69 pair --state /private/test/client \
  --invite /private/test/invitation.json --route direct
python -m experiments.relay69 request --state /private/test/client \
  --peer RECEIVER_FINGERPRINT --route direct --op send --message fixture-only
```

페어링 전에 별도로 신뢰할 수 있는 관리 경로를 통해 초대장의 인증서 핑거프린트를 수신기의 `init` 출력과 비교하세요. 본 실험실에서는 공개 초대 자료에 기존 SSH를 사용하고 일회용 비밀에는 비공개 파일을 사용했습니다. 초대장, 입장 비밀 또는 쿠키를 로그나 URL에 절대 붙여넣지 마세요. `request --op status --message ORIGINAL_MESSAGE_ID`는 불확실한 결과를 조정합니다. `revoke --state RECEIVER_STATE --peer CLIENT_FINGERPRINT`는 해당 테스트 클라이언트를 철회합니다.

릴레이 모드의 경우 git 외부에서 역할당 하나씩 무작위 256비트 입장 자격 증명 두 개를 프로비저닝하세요. 릴레이 `--accounts` 파일은 `{hash: SHA256(credential), room: test-room, role: receiver|client}` 형식의 JSON 배열입니다. 엔드포인트는 0600 권한의 `--admission-file`로 자신의 자격 증명만 받으며 상대방의 비공개 TLS 키는 절대 받지 않습니다. invite 및 serve 둘 다에 `--relay wss://HOST/v1/connect`를 추가하고 `pair --route relay`를 사용하세요. 수신기와 클라이언트 모두 아웃바운드로 연결합니다. relay 명령어는 `--bind`, `--port`, `--accounts` 및 `--seconds`를 허용합니다.

공개 시험에서는 전용 호스트 이름, 기존 CF/KR TLS 종단 및 KR-to-US 테일넷 업스트림을 사용했습니다. 공개 구성은 인프라에 따라 다르며 이 저장소에 의해 자동으로 프로비저닝되지 않습니다. 현재 배포된 시험 환경은 남아 있지 않습니다.

## 운영 한도

릴레이는 10개의 연결, 초당 20개의 HTTP 입장/업그레이드 요청, 100개의 활성 쿠키, 256 KiB 프레임, 4프레임 수신 워터마크, 32 KiB 트랜스포트 쓰기 워터마크, 2초 전달 마감 시간 및 총 32 MiB 전달 바이트를 허용합니다. TLS JSON 메시지는 64 KiB로, 메시지 본문은 32 KiB로 제한됩니다. 수신기는 연결을 8개로, 연결당 요청을 100개로 제한하며, 저널은 중복 제거 이력을 조용히 축출하는 대신 10,000개의 레코드에서 멈춥니다. 이러한 한도는 테스트 예산이며 조정된 제품 보증이 아닙니다.

서비스 수명은 최대 30분입니다. 공용 백엔드는 독립적인 systemd 런타임 한도, DynamicUser, 기능(capability) 없음, 읽기 전용 코드, ProtectHome, 명시적 금지 디렉터리, 비공개 tmp/장치, 256 MiB 메모리, 50% CPU 및 64개 작업을 사용했습니다. Cgroup IP 규칙은 US 백엔드에 대해 KR만 허용했습니다. 샌드박스 사전 점검을 통해 다른 홈과 제품 디렉터리를 읽을 수 없음을 확인했습니다. 새로운 방화벽 규칙, DNS 레코드, 영구 계정 또는 전역 Python 패키지는 설치되지 않았습니다. Mac 픽스처 클라이언트는 별도의 상태/venv를 사용했으며 Linux 샌드박스의 OS 격리를 갖추었다고 주장하지 않았습니다.

실제 애플리케이션에는 더 강력한 기기 수명 주기/UX, 출발지 바인딩 입장 구성, 기기별 쿼터, 오프라인 복구, 의존성 및 프로토콜 검토, 플랫폼 서비스/키 스토리지 설계가 필요합니다. 영수증 계약은 릴레이 연결, 엔드포인트 수락 및 네이티브 제출을 계속 구분해야 합니다. [측정 보고서](REPORT.ko.md)를 참조하세요.
