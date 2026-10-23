# session-peer CLI 레퍼런스

[개요로 돌아가기](../../README.ko.md)

## 수신 세션 세대 고정 조건 (개발 중)

`list --with-target-generation --json`은 각 행에 `targetGeneration`과
`generationStatus`를 추가합니다. 운영체제의 프로세스 생성 정보를 확인할 수 있는
Claude 세션은 `tg1:` 토큰을 `send --target-generation TOKEN`에 전달할 수 있습니다.
`--dry-run`과 SSH에서도 원래 대상의 토큰을 사용합니다. 토큰은 전송 조건이며 비밀정보,
권한, ACK 또는 재전송·중복 방지 키가 아닙니다. 사용하지 않으면 기존 출력과 동작을 유지합니다.

전송 직전에 세션 기록, 프로세스 생성 정보, 수신 경로를 재확인하고 실제 연결된 소켓·파이프의
서버 PID를 확인한 뒤 메시지와 Windows 인증 줄을 씁니다. 이름·PID 재사용이나 경로 변경은
`stale_target`으로 거부하며, 확인 불가능한 신원은 추정하지 않습니다. 같은 프로세스의 상태나
이름 변경만으로 토큰이 바뀌지는 않습니다. 모델의 신원을 인증하거나 같은 OS 계정의 악성
프로세스를 막는 기능은 아니며, 필요한 운영체제 API가 없으면 사용할 수 없습니다.
생성 정보의 정밀도는 운영체제마다 다릅니다(Linux는 부팅 ID와 시작 시각의 clock tick 사용).
전역적으로 고유하거나 복제를 방지하는 신원, 암호학적 SSH 호스트 키 연속성을 보장하지 않습니다.

`stale_target` 거부에는 원래 요청한 Claude 세대를 담은 `lastSeenTarget`이 포함됩니다.
새 수신 프로세스를 다시 조회한 결과가 아닙니다. 이 제한된 메타데이터에는 프로세스 생성값,
경로, 사용자 이름이나 호스트 이름을 넣지 않습니다.

`{"status":"refused","reason":"stale_target","submitted":false,"retryAllowed":false,"lastSeenTarget":{"agent":"claude","targetGeneration":"tg1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}`

`target_generation_unavailable`은 운영체제의 신원을 확인할 수 없다는 뜻이고,
`unsupported_target_generation`은 대상이 이 전송 조건을 지원하지 않는다는 뜻입니다.
두 결과에는 `lastSeenTarget`을 넣지 않으며 재전송 권한도 주지 않습니다.
소스 전송·재시작 회귀 테스트는 전용 프로토콜 수신함과 로컬 SSH 대역을 사용합니다.
실제 원격 장비나 실제 에이전트의 검증 근거는 아닙니다.

Codex 큐, Antigravity와 페어링 기기는 이 수신 프로세스 세대 보장을 제공하지 않습니다.
일반 세대 고정 요청은 큐 삽입·wake 전에 거부하고 각각의 기존 계약을 유지합니다.
Codex의 작성자 재확인만으로 나중에 큐를 소비하는 작성자를 원자적으로 제한할 수는 없습니다.
#180의 전체 작업은 아직 열려 있습니다. v1.0.4에 발행된 기능이 아니며 자동 대체 전송·재전송도 없습니다.

2026-10-15 native Codex [0.162.1](https://github.com/openai/codex/tree/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs)의 큐 입력 경로를 검토했지만, 원래 쓰기 프로세스의 세대를 원자적으로 검사하는 지원 가능한 전제조건은 찾지 못했습니다. 확인한 소스에서 잠금 획득 경로는 세대 토큰을 기록하지 않고, 스레드의 `sessionId`는 재개 후에도 유지되며, `thread/queue/add`는 세대 전제조건 대신 스레드·입력·클라이언트 메시지 ID를 받습니다. 확인한 `turn/steer` 경로는 활성 턴 잠금 안에서 `expectedTurnId`를 검사하지만, session-peer는 이 턴 전용 검사를 쓰기 프로세스의 세대로 사용하지 않습니다. 이는 고정된 경로에 한정된 조사이며 모든 native API나 향후 버전의 기능 부재를 증명하지 않습니다. PID·시작 시각·잠금 재검사, 큐 ID, `canAcceptDirectInput`, `sessionId`로는 필요한 원본 세대 보장을 확립할 수 없으므로 Codex `targetGeneration`은 계속 `unsupported`로 보고합니다. #180은 별도로 검증된 native 계약을 위해 열린 상태로 유지합니다.

명령어의 상세 동작, 설치 옵션, 전송 한계 및 과거 검증 내역은 아래와 같습니다.
기계 소비자는 [v1 호환성 계약](compatibility-v1.md)도 따라야 합니다.

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/pypi/pyversions/session-peer)](https://pypi.org/project/session-peer/)

단일 CLI에서 로컬 또는 SSH를 통해 **Claude Code 및 Codex 세션**에 메시지를 전송합니다.
Claude 대상은 기본 인박스 소켓/파이프를 사용하고, Codex 대상은 `codex queue`를 사용합니다.
SSH는 대상 시스템에서 동일한 Python 스크립트를 실행하므로, 전송 또는 목록 요청을 수신하기 위해
session-peer를 대상 시스템에 설치할 필요가 없습니다.

이 프로젝트는 Git 이력과 이슈 번호를 보존하면서 cc-peer를 이어갑니다.
session-peer 릴리스는 [PyPI](https://pypi.org/project/session-peer/) 및
[GitHub](https://github.com/abruption/session-peer/releases)에 게시되며, 기존 PyPI
cc-peer 프로젝트는 최종 0.5.1 릴리스 이후 보관 처리되었습니다.
구체적인 마이그레이션 단계는 [cc-peer에서 이전하기](#moving-from-cc-peer)를 참조하세요.

## 지원 및 보안

- **버그 및 기능 요청:** [이슈 템플릿](https://github.com/abruption/session-peer/issues/new/choose)을 사용하세요. 먼저 기존 이슈를 검색해 보세요.
- **보안 취약점:** [비공개로 보고](https://github.com/abruption/session-peer/security/advisories/new)해 주세요. [SECURITY.md](../../SECURITY.ko.md)를 참조하세요.
- **비공개 문의:** 제목에 `[session-peer]`를 포함하여 [support@abruption.dev](mailto:support@abruption.dev?subject=%5Bsession-peer%5D%20Support)로 이메일을 보내주세요. 비공개 취약점 보고를 사용할 수 없는 경우에도 이메일이 대안이 될 수 있습니다.

공개 이슈는 모든 사람에게 표시됩니다. 민감한 정보가 수정된 최소한의 재현 방법을 공유하고,
대화 이력, 세션 데이터베이스, 인증 파일, 토큰 또는 개인 키를 첨부하지 마세요. 이메일은 수동으로
검토되며 이슈로 자동 게시되지 않습니다. 지원은 최선의 노력으로 제공되며 보장된 응답 시간이
없습니다. 영어 및 한국어 보고 모두 환영합니다.

## 빠른 시작

`pipx install session-peer` 또는 `uv tool install session-peer`로 CLI를 설치합니다.
독립 실행형 CLI 및 Claude 스킬에 대해서는 [설치](#install)를 참조하세요.

```bash
session-peer list                              # Claude, Codex + registered Antigravity
session-peer list --agent claude                # Claude-only filter
session-peer list --agent codex                 # saved Codex threads
session-peer list --agent codex --host worker   # saved threads on an SSH host

session-peer send --to api-worker --message "message"     # Claude name or PID
session-peer send --to 'codex:<full-thread-uuid>' --message "message" --output-format json
session-peer send --host worker --to 'codex:<full-thread-uuid>' --dry-run -m "message"
```

`<full-thread-uuid>`를 대상 시스템의 Codex 목록에 있는 전체 ID로 바꿉니다.
`list`는 기본적으로 등록된 모든 어댑터를 포함합니다. Antigravity는 활성 상태이며
명시적으로 등록된 브리지만 나열합니다. **필터링할 때는 `--codex`가 아니라
`--agent codex`를 사용하세요**: `--codex`는 지원되는 플래그가 아니며 `--codex-home` 및
`--codex-bin`과 모호합니다. `send`는 `--agent` 플래그가 아니라 대상에서 에이전트를
선택합니다.

**게시됨/큐에 추가됨이 확인을 의미하지는 않습니다.** 저장된 Codex 스레드가 반드시
실행 중인 것은 아닙니다. 일반 send는 세션을 활성화하지 않으며, [명시적 `--wake`](wake.md)는
옵트인 방식이며 소비나 응답을 확인해주지 않습니다.

<a id="delivery-explanation"></a>

### 전달 설명 (개발 중)

#323의 개발 기능으로 v1.3 후보이며, 공개 v1.2.1에는 없습니다. `send --dry-run`에 `--explain`을 추가하면 선택한 로컬·SSH·페어링 기기 대상, 기존 검증 결과, 전달 방식과 관찰 한계를 사람이 읽기 쉬운 형태로 표시합니다. `doctor --explain`은 기존 진단 스냅샷과 선언된 지원 기능을 설명하며, 특정 대상의 전송 준비 상태를 확인하지는 않습니다. `handoff status --explain`은 기존 intent에 저장된 증거를 설명합니다. 처리한 SSH 대상마다 개별 설명을 표시하지만, 예상치 못한 오류가 나면 기존 호스트 반복 처리가 중단되어 이후 대상은 처리하지 않을 수 있습니다.

```bash
session-peer send --host worker --to 'codex:<full-thread-uuid>' --message "Review the patch" --dry-run --explain
session-peer send --device RECEIVER_FINGERPRINT --to review --message "Review the patch" --dry-run --explain
session-peer doctor --explain
session-peer handoff status --correlation-id PREPARED_UUID --explain
```

설명은 선택한 명령의 기존 결과를 재사용하며 진단·native 버전·SSH 조회, 대상 활성화나 별도의 `list` 작업을 추가하지 않습니다. 기존 dry-run 자체에는 버전 검사가 포함될 수 있습니다. 실제 전송 시에는 다시 검증하며, 미리보기 성공이 대상을 예약하거나 제출·소비·완료를 보장하지는 않습니다. 선언된 지원 기능, 실제 검사 결과와 확인할 수 없는 사실을 구분해 표시합니다. `--wake`를 지정하지 않으면 깨우기 가능 여부를 검사하지 않습니다. 지정한 경우에도 기존 사전 검사 결과만 설명합니다.

페어링 dry-run은 기존 수신 기기 정책에 따른 `resolve` 작업을 유지합니다. 기존 연결 확인 과정에서 지원을 알리는 수신 기기와만 선택적 설명 context를 협상합니다. 이 내부 context에는 버전과 허용 필드 검증을 적용하며 크기를 8 KiB로 제한합니다. 일반 JSON 출력이나 handoff 스키마는 추가하지 않습니다. 선택한 수신 측 에이전트·대상·home은 보고되고 검증된 경우에만 표시하며 송신 측 프로필에서 추측하지 않습니다. 구형 수신 기기의 독립적으로 확인된 native 결과는 유지하고, 보고되지 않은 context는 알 수 없음으로 표시합니다. 대체 경로 시도, 추가 조회나 재전송은 하지 않습니다.

Handoff status는 읽기 전용 스냅샷을 재사용하며 intent·receipt capability·wait·collector를 만들거나 ledger에 기록하지 않습니다. 제출, 입력 주입 관찰, 명시적 receipt와 최근 저장된 wait는 구분합니다. Receipt가 acknowledged여도 작업 완료를 증명하지는 않습니다. 저장된 관찰은 오래된 정보일 수 있습니다. 보고된 receipt 관찰 시각만 관찰 시각으로 설명하며, 설명 생성 시각이나 진단 스냅샷 시각을 전달 관찰 시각으로 해석하지 않습니다. 일반 전송에 receipt ACK 지원이 추가되지는 않습니다.

이 범위는 텍스트 출력 전용이므로 `--explain`을 `--json` 또는 `--output-format json`과 함께 지정하면 사용법 오류가 발생합니다. `--dry-run`은 `send --explain`에만 필수이며 `doctor --explain`과 `handoff status --explain`에는 필요하지 않습니다. Send에서는 실험적 handoff 옵션인 `--correlation-id`, `--request-ack`, `--observe-delivery`, `--wait-for`와 `--explain`의 조합을 메시지 입력이나 대상·ledger 작업 전에 계속 거부합니다. 새 옵션을 사용하지 않은 기존 명령의 출력·JSON·종료 계약은 유지됩니다. 설명은 성공한 상태 조회를 ACK 증거로 바꾸거나 원래 명령의 종료 의미를 바꾸지 않습니다.

Send의 메시지 입력 요구사항과 한도는 동일합니다. 평소처럼 `--message`, `--message-file` 또는 stdin을 사용하며 임시 본문을 자동 생성하지 않습니다. 설명 필드에는 본문이나 receipt 비밀값을 넣지 않습니다. 일반 설명은 stdout에, 실패 결과나 예상 밖 제출 증거의 설명은 stderr에 표시하며 기존 요약·오류 출력의 위치는 바꾸지 않습니다. 확인할 수 없는 증거는 그대로 알 수 없음으로 표시하고, 실제 전송 결과가 불확실하면 자동 재전송하지 않습니다.

### 페어링된 기기 옵션 및 Antigravity (v0.9)

이 기능들은 PyPI v0.9.0부터 제공됩니다. Antigravity는 여전히 실험적이며 페어링된 전송은
베타 상태로 유지되므로 운영상 검증이 여전히 필요합니다. `pipx install 'session-peer[relay]'`를
사용하여 추가 패키지를 설치합니다. `[relay]` 추가 패키지(Unix, Python 3.11+)는 직접 또는
자체 호스팅 WSS 릴레이를 통한 인증된 페어링 기기 전달을 활성화합니다. 페어링은 기기
식별자를 고정하며, 별도의 운영자 정책을 통해 개별 에이전트 대상 및 작업을 허용합니다.
블라인드 릴레이는 애플리케이션 메시지를 복호화할 수 없습니다. 엔드포인트를 노출하기 전에
[페어링 기기 설정 및 운영 가이드](paired-devices.md)를 따르세요. 베타 버전은
NAT 통과나 호스팅된 퍼블릭 서비스를 제공하지 않습니다.

Antigravity는 기존 TUI 내에서 명시적으로 시작된 브리지를 필요로 합니다.
[Antigravity 설정](antigravity.md)을 참조하세요. 이는 옵트인 방식이며 Claude/Codex
검색을 변경하지 않습니다. 활성 Antigravity 등록도 필터링되지 않은 목록에 표시됩니다.
일반 로컬 및 SSH 명령어는 표준 라이브러리 전용 설치 경로를 유지합니다.
[v0.9 릴리스 노트](releases/v0.9.0.md)를 참조하세요.

### 메시지 입력 및 결과 출력

`--message TEXT`(단축형 `-m`)는 대상에 전송할 텍스트를 지정합니다.
`--output-format text|json`은 메시지 형식이 아니라 명령어 결과 형식을 선택합니다.
`list`, `send`, `doctor`, `update`에서 사용할 수 있으며, 기본값은 `text`입니다.
기존의 `--json`은 `--output-format json`의 별칭으로 유지됩니다.

```bash
session-peer send --to worker --message "Report progress" --output-format json
session-peer send --to worker -m - --output-format json < message.txt
session-peer list --output-format json
```

기존의 위치 기반 메시지와 메시지가 생략된 stdin 입력은 계속 작동합니다.
위치 기반 메시지 또는 `--message` 중 하나만 사용해야 하며, 둘 다 사용할 수는 없습니다.
`--message -`는 stdin에서 읽으며, 명시적인 빈 메시지는 여전히 거부됩니다. 대시로 시작하는
텍스트를 보내려면 `--message='--literal text'` 또는 stdin을 사용하세요. 내부 SSH `--b64`
입력은 공개 메시지 형식 중 어느 것과도 결합할 수 없습니다.

`--json --output-format json`은 유효하며, `--json`과 `--output-format text`를
어떤 순서로든 결합하면 오류가 발생합니다. 유효하지 않거나 모순되는 출력 옵션은 argparse
사용법 오류(stderr, 종료 코드 2)입니다. 메시지 소스 충돌은 일반 명령어 오류(요청 시 JSON,
종료 코드 1)입니다. 두 경우 모두 메시지가 제출되지 않습니다. JSON 결과는 수신이 아니라
여전히 제출만을 설명합니다. 이 플래그들은 구조화된 JSON 메시지 입력 프로토콜을 도입하지
않습니다.

<a id="route-presets"></a>

## 로컬 경로 프리셋 (개발 중)

#324의 개발 기능이며 공개 v1.2.1에는 없습니다. 선택적으로 사용하는 `preset` 명령은 수신자가 아니라 접속 경로를 저장합니다. Mac/Linux에서 `--preset`으로 로컬 또는 SSH 경로 하나를 골라 일반 Claude Code·Codex 목록 조회나 전송에 사용합니다. Windows의 프리셋 작업은 거부하며 기존 Windows 명령은 바꾸지 않습니다.

```bash
session-peer preset add work-mac --host user@work-mac --agent codex --codex-home /Users/user/.codex
session-peer preset list
session-peer preset show work-mac --json
session-peer list --preset work-mac
session-peer send --preset work-mac --to 'codex:<full-thread-uuid>' --message "Review the patch" --dry-run
session-peer send --preset work-mac --preset-revision 'dp1:<HASH>' --to 'codex:<full-thread-uuid>' --message "Review the patch"
session-peer preset replace work-mac --expect-revision 'dp1:<HASH>' --host user@new-mac --agent codex --codex-home /Users/user/.codex
session-peer preset remove work-mac --expect-revision 'dp1:<CURRENT-HASH>'
```

UUID는 현재 목록에서 확인한 값으로, 해시는 선택한 프리셋에 표시된 정확한 revision으로 바꿉니다. 실제 전송에는 `--preset-revision`이 필요하고 dry-run에서는 생략할 수 있습니다. `dp1:` 해시는 프리셋 이름과 검증된 경로의 정확한 값만 포함하며 DNS·SSH 설정·호스트 키·native 소유권·권한·세대·ACK를 증명하지 않습니다. 경로 값이 바뀌면 다시 확인해야 하고, 동일한 값을 복원하면 해시도 같습니다. 수정·삭제에는 `--expect-revision`이 필요하며 같은 이름의 추가는 거부합니다.

수신자의 이름·PID·UUID·세대 토큰은 저장하지 않습니다. `--to`는 계속 필수이며 이름은 기존 규칙으로 현재 대상을 새로 찾는 값이지 이전 세션에 고정된 주소가 아닙니다. 명시적인 기존 `--target-generation`, writer·저장소 검사, 결과가 불확실할 때 자동 재전송하지 않는 원칙은 유지합니다. 프리셋 이름은 사람의 신원이나 전달 사실을 증명하지 않습니다.

저장 위치는 `$XDG_CONFIG_HOME/session-peer/destinations.json`이며 변수가 없으면 `~/.config/session-peer/destinations.json`입니다. 지정한 기본 경로는 절대 경로여야 합니다. 앱 디렉터리는 소유자 전용 0700, 파일은 소유자 전용 0600 또는 더 제한적인 권한을 사용합니다. 심볼릭 링크, 안전하지 않은 소유권·권한, 중복·알 수 없는 JSON 키, 잘못된 UTF-8, 128개 초과 항목, 64 KiB 초과 파일은 다른 경로로 우회하지 않고 거부합니다. 이름은 `[a-z][a-z0-9_-]{0,63}` 형식입니다. 스키마에는 전송 방식·에이전트, 필요한 경우 SSH 호스트 하나, Codex 경로의 절대 home만 저장합니다:

```json
{"schemaVersion":1,"presets":{"work-mac":{"transport":"ssh","agent":"codex","host":"user@work-mac","codexHome":"/Users/user/.codex"}}}
```

프리셋과 명시적인 `--host`, `--codex-home`, `--agent`, `--ssh-opt`, `--codex-bin`은 값이 같아도 함께 사용할 수 없습니다. Reply-To URI, 페어링 기기, Antigravity, wake, 실험적 handoff 조합도 제외합니다. 자격증명·실행 파일 경로·SSH 명령이나 옵션·승인 설정·receipt 비밀값은 저장하지 않습니다. 기존 운영자 소유 SSH 설정은 그대로 적용됩니다.

`preset list`와 `preset show`는 설정만 읽으며 native 목록 조회·SSH·업데이트 알림·백그라운드 갱신을 실행하지 않습니다. 읽기 작업은 없는 저장소를 초기화하지 않습니다. 반면 `list --preset`은 기존 원격 조회와 부분 실패 처리를 포함해 선택한 경로 하나의 일반 목록 조회를 명시적으로 실행합니다. 다른 프리셋에 접속하거나 그룹에 일괄 전송하지 않습니다.

텍스트 목록 조회·전송은 기존 작업 전에 선택한 경로와 revision을 stderr에 표시합니다. 기존 native 결과 JSON·stdout·종료 계약은 유지하며 프리셋 플래그·revision·로컬 파일 경로를 SSH로 전달하지 않습니다. 호출마다 읽은 스냅샷 하나를 사용합니다. 나중에 프리셋을 수정·삭제해도 이미 확장한 호출은 취소되지 않으며 실제 제출은 native 대상을 다시 검증합니다. 이는 저장소·소유권의 원자적 증명, 수신측 중복 억제, 소비, ACK, 작업 완료를 보장하지 않습니다.

`preset_commit_unconfirmed` 오류는 원자적 교체가 이미 보일 수 있지만 디스크에 안전하게 기록됐는지 확인하지 못했다는 뜻입니다. 재시도 전에 현재 설정을 확인하세요. 자동으로 되돌리지는 않습니다.

검사하는 상위 경로는 root 또는 현재 사용자 소유이며 다른 사용자가 쓸 수 없어야 합니다. root 소유의 sticky 임시 디렉터리는 예외이고, 설정의 직계 부모는 현재 사용자 소유여야 합니다. 모든 경로 구성 요소는 심볼릭 링크를 따라가지 않고 엽니다. 전용 저장소의 확장 ACL 항목은 보수적으로 거부합니다. Mac 상위 경로의 deny-only ACL은 허용하지만 allow 항목이나 확인할 수 없는 ACL은 거부하며 Linux POSIX ACL도 검사합니다. 비어 있거나 상대 경로인 `XDG_CONFIG_HOME`은 다른 위치로 조용히 우회하지 않고 거부합니다. 기존 권한을 자동으로 고치지 않으므로 안전한 사용자 전용 절대 경로를 선택하세요. 잘못된 설정은 비공개 백업을 보관한 뒤 오프라인에서 확인·수정하고, 내용은 공개하지 마세요.

Mac에서 소유권을 무시하는 마운트는 `preset_ownership_unenforced`로, 마운트 조회를 수행하거나 검증할 수 없으면 `preset_mount_unverifiable`로 거부합니다. 파일 모드만으로 소유권 강제를 증명했다고 취급하지 않습니다. Linux에서는 상위 경로의 ACL도 거부하며 ACL 상태를 검증할 수 없는 파일시스템도 거부합니다. 관리 명령을 중단했을 때는 변경이 이미 보일 수 있으므로 현재 설정을 확인하세요. 디렉터리 동기화 실패를 조용히 성공으로 처리하지 않습니다.

### 수신 대상 주소록 (개발 중)

이 추가 #324 범위는 v1.3 후보이며 공개 v1.2.1에는 없습니다. 경로 프리셋은 계속 경로만 저장합니다. 별도로 선택해 사용하는 주소록은 사용자 지정 표시 이름을 로컬 또는 SSH Mac/Linux 경로에서 명시적으로 선택한 Claude Code·Codex 수신 대상에 연결합니다. 표시 이름은 사람의 신원을 인증하지 않습니다. 페어링 기기, Antigravity와 Windows는 거부합니다. 명시적인 주소록 작업이나 `--address`가 없는 명령은 주소록 설정을 읽지 않으며, 자동 이전이나 대체 경로 시도를 추가하지 않습니다.

```bash
session-peer address resolve --preset work-mac --to 'codex:<full-thread-uuid>' --json
session-peer address add review --label Review --preset work-mac --to 'codex:<full-thread-uuid>' --expect-selection 'as1:<HASH>'
session-peer address discover --address review --json
session-peer send --address review --dry-run --message 'Review the patch'
session-peer send --address review --address-revision 'ab1:<HASH>' --confirm-target 'codex:<full-thread-uuid>' --message 'Review the patch'
session-peer address reselect review --expect-revision 'ab1:<OLD_HASH>' --to 'codex:<new-full-thread-uuid>' --expect-selection 'as1:<NEW_HASH>'
session-peer address remove review --expect-revision 'ab1:<HASH>'
```

자리표시자를 실제로 보고된 정확한 값으로 바꿉니다. `add` 전에 `address resolve` 결과를 검토하고 해당 `as1:` 관찰 revision을 사용합니다. `reselect` 전에는 같은 프리셋으로 원하는 새 대상을 다시 resolve하고 새 `as1:` 값을 검토합니다. `as1:`은 관찰된 선택 메타데이터의 revision이며 권한, native epoch나 소비 증거가 아닙니다. 추가 또는 재선택에 성공할 때마다 새 `bindingId`를 만들고 이를 `ab1:` 주소 revision에 포함합니다. 따라서 동일한 주소를 삭제 후 다시 만들어도 이전 revision을 재사용할 수 없습니다. 경로의 `dp1:`은 계속 값의 해시이며, 동일한 프리셋 값을 복원하면 새 epoch가 아니라 같은 해시를 얻습니다.

`address list`와 `address show`는 설정만 읽습니다. `address resolve`와 `address discover`는 임시 메시지, native CLI·버전 조회나 모델·세션 활성화 없이 선택한 수신 대상의 메타데이터를 명시적으로 확인합니다. 기존 OS 프로세스 메타데이터 확인은 수행될 수 있습니다. Discover는 서로 다른 `--address` 이름을 최대 16개까지 받으며, 경로·home과 고정된 SSH 키 context가 모두 같은 경우에만 묶어 그룹당 한 번 확인합니다. 주소별 부분 실패를 유지하고, 하나라도 확인에 실패하거나 저장된 선택과 달라지면 종료 코드 1을 반환합니다. 네트워크 검색이나 그룹 일괄 전송은 하지 않습니다. 참조 프리셋이 없거나 경로·revision이 달라지면 거부하며, 저장된 이전 경로로 대체하지 않습니다.

Claude 주소는 선택한 `tg1:` 세대를 저장하고 제출 전에 기존 연결 상대 확인 조건을 적용합니다. Codex 주소는 전체 스레드 UUID, 정확한 home과 `aw1:` writer 관찰을 저장하며 효과가 발생하기 전에 기존 검사를 반복합니다. Codex 세대는 계속 **미지원**입니다. Writer 관찰과 재검증은 원래 native 인스턴스 세대를 원자적으로 검증하는 보장이 아닙니다. Writer가 달라지거나 확인할 수 없으면 명시적으로 다시 선택해야 하며, 자동 대상 변경이나 재실행은 하지 않습니다. SSH 선택은 실제 연결에서 검증한 호스트 키를 요구하며 실제 전송에도 같은 키를 고정합니다. 이것으로 사람을 인증하거나 SSH 설정·SQLite 저장소의 동일성을 증명하지는 않습니다.

실제 전송에는 현재 `--address-revision`과 정확한 `--confirm-target`이 모두 필요하며 dry-run에서는 생략할 수 있습니다. `--address`는 `--to`, `--preset`, 명시적 호스트·native·SSH 재정의, 페어링 기기, wake, handoff나 Reply-To URI 경로와 함께 사용할 수 없습니다. 일반 메시지 입력과 한도는 그대로 유지됩니다. 결과가 불확실해도 자동 재전송은 허용되지 않습니다. 이 명령들은 별도의 #323 전달 설명 후보 기능과의 조합을 보장하지 않습니다.

저장소는 `destinations.json` 옆의 별도 `addresses.json`이며 `schemaVersion: 1`, 64 KiB 한도와 최대 128개 항목을 사용합니다. 프리셋과 같은 소유자·권한·ACL·마운트 검사 및 심볼릭 링크를 따르지 않는 경로 검사를 적용하고 파일을 자동 복구하거나 이전하지 않습니다. 주소 이름은 프리셋 이름 문법을 따릅니다. 표시 이름은 NFC로 정규화하고 128자로 제한하며 제어 문자·양방향 제어 문자·서식 문자를 거부합니다. 관리 작업의 commit을 확인하지 못했어도 변경이 이미 보일 수 있으므로 재시도 전에 현재 설정을 확인하세요. 수신자 바인딩 revision은 수신 측 중복 방지, ACK나 작업 완료 증거를 추가하지 않습니다.

<a id="install"></a>
## 선택적 대화형 단축 명령

이 파일이 포함된 릴리스에서는 Bash/zsh와 PowerShell에서 현재 셸에만 적용되는 `sp` 별칭을 선택적으로 사용할 수 있습니다. 현재 선택된 `session-peer` 명령에 인자와 표준 입력을 그대로 전달하며 출력, 종료 코드, 권한도 동일합니다. 별도의 인자 해석기나 Python/TypeScript 선택기가 아닙니다. 스크립트, SSH 요청, 자동 생성 회신 안내에는 정식 명령을 사용하세요. 두 구현을 동시에 설치하지 마세요. 기존 설치 관리자로 구현을 교체하고 셸에서 어떤 명령이 먼저 선택되는지 확인하세요.

wheel과 소스 배포 파일의 `session_peer_shorthand`에 활성화 파일이 포함됩니다. 설치만으로 활성화되거나 프로필과 PATH가 바뀌지는 않습니다. 선택한 설치본의 Python 인터프리터로 파일 경로를 확인하세요. 활성화한 pip 가상 환경의 인터프리터 또는 `pipx environment --value PIPX_LOCAL_VENVS`나 `uv tool dir`에서 확인한 도구 환경의 인터프리터를 사용합니다. 일반적으로 Unix 도구 환경에는 `session-peer/bin/python`, Windows에는 `session-peer/Scripts/python.exe`가 있습니다. 경로를 추측하지 말고 실제 환경을 확인하세요. 모듈은 파일 경로만 출력합니다. 셸에서 읽어 실행하기 전에 파일을 검토하세요.

```bash
asset=$("/path/to/tool/python" -I -m session_peer_shorthand bash)
source "$asset"
sp --version
source "${asset%/*}/sp-remove.sh"
```

```powershell
$asset = & 'C:\path\to\tool\Scripts\python.exe' -I -m session_peer_shorthand powershell
. $asset
sp --version
. $asset -Remove
```

이미 `sp` 실행 파일, 별칭 또는 함수가 있으면 덮어쓰지 않고 활성화를 거부합니다. PowerShell은 보통 `sp`를 `Set-ItemProperty`의 별칭으로 정의하므로 기본적으로 활성화가 거부됩니다. 충돌을 직접 관리하기로 결정하지 않았다면 정식 명령을 계속 사용하세요. Bash/zsh에서는 source로, PowerShell에서는 dot-source로 파일을 읽어야 합니다. cmd.exe는 지원하지 않습니다. 별칭은 셸의 일반적인 별칭 확장 규칙을 따릅니다. Bash의 비대화형 스크립트는 기본적으로 별칭 확장을 끄므로 정식 명령을 사용해야 합니다.

이 방식으로 만든 별칭이 변경되지 않았다면 반복 활성화해도 추가 변경 없이 성공합니다. 제거는 같은 셸에서 생성한 별칭에만 적용되며, 다른 별칭이나 명령으로 바꾸었다면 거부합니다. 셸을 닫으면 별칭도 사라집니다. 기존 설치 관리자로 업데이트하면 별칭은 복사된 실행본이 아니라 정식 명령을 계속 가리킵니다. 제거하거나 구현을 교체하기 전에 별칭을 먼저 제거하세요. 패키지 제거는 실행 중인 셸을 바꾸지 않습니다. 영구 설정과 제거를 직접 관리할 의사가 없다면 프로필에 이 파일을 추가하지 마세요.

standalone 설치 방식은 바뀌지 않으며 이 파일들을 자동 설치하지 않습니다. standalone과 함께 쓰려면 검토한 체크아웃에서 파일을 가져오거나 해당 릴리스의 검증된 소스 배포 파일에서 `session_peer_shorthand`를 추출하세요. 검증되지 않은 다운로드를 바로 실행하지 말고 [릴리스 검증](../../RELEASING.ko.md) 절차를 따르세요. PATH에서 정식 명령을 찾을 수 있게 한 뒤 검토한 로컬 파일을 직접 읽으세요. 직접 선택한 파일의 업데이트와 제거는 사용자의 책임이며 standalone, pipx, uv, pip의 관리 주체는 바뀌지 않습니다. 충돌 검사는 현재 셸과 PATH에 보이는 명령만 확인하며 다른 셸이나 향후 PATH 변경까지 확인하지 않습니다.

## 설치

Python 3.9+, 표준 라이브러리 전용 — 외부 의존성 없음.

### pip

활성화된 가상 환경에서:

```bash
python -m pip install session-peer
```

또는 격리된 설치를 위해 [pipx](https://pipx.pypa.io/)를 사용하는 경우:

```bash
pipx install session-peer
```

또는 `uv tool install session-peer`를 사용할 수도 있습니다.
패키지 관리자는 `session-peer` 명령어를 설치하지만 [에이전트 스킬](#the-skill)은 설치하지 않습니다.
Claude Code, Codex, Antigravity용 스킬은 전용 저장소에서 설치합니다.

```bash
npx -y skills@latest add abruption/session-peer-skill \
  --skill session-peer --global \
  --agent claude-code --agent codex --agent antigravity \
  --copy --yes
```

<a id="installsh"></a>
### install.sh

검증된 독립형 설치에는 증명 검증을 지원하는 최신 GitHub CLI가 필요합니다. 검증된 불변 릴리스 게시 전에는 pipx/uv/pip를 사용하십시오. 기존 v1.0.2에는 검증된 독립형 자산이 없습니다. 내려받은 코드를 실행하기 전에 [부트스트랩 절차](../../RELEASING.ko.md)로 설치기를 인증하십시오. 아래 명령은 이미 신뢰한 설치기 체크아웃을 전제로 하며 기본값은 검증된 최신 릴리스를 내려받습니다. 로컬 파일에는 명시적 `--local-source`, 미검증 개발 main에는 명시적 `--main`이 필요합니다.

명령어와 스킬을 한 단계로 모두 설치합니다. 에어갭 호스트나 SSH를 통한 원격 배포에
사용하세요:

```bash
git clone https://github.com/abruption/session-peer && cd session-peer

./install.sh                          # this machine
./install.sh --host build-server      # a remote machine, over SSH
./install.sh --host web-01 --host db  # several at once
```

이렇게 하면 `session_peer.py`가 `~/.local/share/session-peer/`에 배치되고,
`~/.claude/skills/session-peer/`와 `~/.agents/skills/session-peer/`에 [session-peer 스킬](https://github.com/abruption/session-peer-skill/blob/main/session-peer/SKILL.md)의 호환 사본이
설치되며, `~/.local/bin/session-peer`가 링크됩니다. 다른 관리자로 설치한 스킬과 심볼릭 링크,
기존 cc-peer 파일은 유지됩니다. `./install.sh --uninstall [--host ...]`은 설치기가 소유한
파일만 제거하며, 소유권 표시가 없는 기존 스킬은 보존합니다.

`session-peer update`는 최신 GitHub 릴리스에서 독립 실행형 프로그램을 갱신합니다.
`./install.sh --host <host>`는 최신 릴리스를 검증하고 그 프로그램과 스킬을 SSH로 전송합니다.
`session-peer update --host <host>`는 설치된 버전이 다르거나 없을 때 프로그램만
푸시합니다. 아무것도 변경하지 않고 보고만 받으려면 `--check`를 추가하세요.
패키지 관리자 설치 및 원격 제한 사항에 대해서는 [업데이트](#updating)를 참조하세요.

**원격 설치는 파일들을 SSH 연결 자체를 통해 푸시하므로**, 대상 시스템에 인터넷 액세스가
필요하지 않습니다. 독립 실행형 파일을 설치하려면 `python3` 및 SSH 접근 권한이
필요합니다. 메시징을 수행하려면 대상 시스템에 선택한 에이전트의 기본 인박스 또는 큐도
있어야 합니다.

명시적으로 신뢰한 로컬 개발 소스의 경우:

```bash
# Explicitly trust reviewed local source for development only.
./install.sh --local-source
```

<a id="the-skill"></a>
### 스킬

공개 스킬 정본은 [session-peer-skill 저장소](https://github.com/abruption/session-peer-skill)에서 관리합니다.
독립 실행형 설치 프로그램은 에어갭과 SSH 설치를 위해 호환 사본을 유지하며 Claude Code용
`~/.claude/skills/session-peer/SKILL.md`와 Codex용 `~/.agents/skills/session-peer/SKILL.md`에
배치합니다. Claude 경로는 기본값 이전에 `CLAUDE_CONFIG_DIR`, 그 다음 `ANTHROPIC_CONFIG_DIR`을
따릅니다. 별도 관리 스킬을 덮어쓰거나 제거하지 않습니다. Claude Code, Codex,
Antigravity 전체에 전역 설치하려면 위 Skills CLI 명령을 사용하세요. 스킬은 대상과 메시지
선택을 안내하고 Python 프로그램은 검색과 전송을 수행합니다. 설치해도 에이전트의 권한이나
인바운드 설정은 변경되지 않습니다.

## 사용법

```bash
session-peer list                                  # Claude + Codex on this machine
session-peer list --host web-01                    # Claude + Codex over there
session-peer list --host web-01 --all              # Claude stale records / no inbox
session-peer list --agent codex --all              # include archived Codex threads
session-peer doctor                                # local inbox/tool/home diagnostics
session-peer doctor --host web-01                  # run the same checks there
session-peer doctor --host web-01 --check-return-route  # also test SSH back here

session-peer send --to api-worker "message"        # local session
session-peer send --host web-01 --to api-worker "message"
session-peer send --host deploy@web-01 --to api-worker "message"  # explicit SSH user
session-peer send --host web-01 --to 4011 "message"          # address by pid
git log --oneline -5 | session-peer send --host web-01 --to api-worker -   # stdin

session-peer send --host web-01 --to api-worker --dry-run "x"   # resolve only
session-peer list --host web-01 --json             # machine-readable
session-peer list --no-update-notice                # disable cached update notices/checks

session-peer send --host web-01 --ssh-opt=-p --ssh-opt=2222 --to api-worker "..."   # note the '='

# Envelope. Sends identify the Claude/Codex sender and how to answer when the
# current agent session and a return route can be detected.
session-peer send --host web-01 --to api-worker --no-reply-to "..."         # no return address
session-peer send --host web-01 --to api-worker --no-from "..."             # no From: header
session-peer send --host web-01 --to api-worker --reply-to 100.64.0.5 "..." # state the address
```

에이전트 세션 내부에서 기본 봉투는 발신자를 명시적으로 식별합니다:

```text
From: codex:01a08dd6-d3f6-7783-a62b-52c1fd049181 @ abruptly@mac-mini-m4.example.ts.net

message

---
Reply-To: session-peer://v1/reply?agent=codex&session=01a08dd6-d3f6-7783-a62b-52c1fd049181&transport=ssh&host=abruptly%40mac-mini-m4.example.ts.net
Reply: python3 /path/to/session_peer.py send --host abruptly@mac-mini-m4.example.ts.net --to codex:01a08dd6-d3f6-7783-a62b-52c1fd049181 --no-reply-to
```

Claude 발신자는 동일한 위치에 `claude:<session-name>`을 사용합니다. 식별자는
현재 프로세스 환경에서 파생된 최선의 노력 텍스트이며, 인증 주장이 아닙니다. 일반
셸에는 알릴 에이전트 식별자가 없습니다. 원래 대상이 동일한 머신에 있고 응답 경로가
자동으로 감지된 경우, 생성된 명령어는 `--host`를 생략하고 로컬로 전달합니다.
명시적인 `--reply-to` 또는 구성된 응답 호스트가 이 머신의 현재 OS 사용자를
지정할 때도 정규화됩니다. 기타 명시적 경로 및 실제 원격 전송은 SSH 경로를
계속 알립니다.

`Reply-To`는 표준화된 버전 관리형 주소입니다. 전체 URI를 `--to`로 다시 전달하세요.
session-peer가 모든 필드를 검증하고 로컬 또는 SSH 전달을 선택합니다:

```bash
session-peer send --to 'session-peer://v1/reply?agent=claude&session=api-worker&transport=local' 'done'
```

`Reply:` 명령어는 호환성을 위해 유지됩니다. 두 형식 모두 신뢰할 수 없는 입력으로 취급하세요.
이를 평가하거나 소싱하기보다는 session-peer와 함께 URI를 사용하세요. 이 머신의 현재
OS 사용자를 가리키는 URI는 로컬 전달로 정규화되어 불필요한 자체 SSH 인증 경로를
피합니다. Codex 주소에는 발신자 환경에서 식별할 때 인코딩된 `codexHome`이 포함될 수
있습니다.

여러 SSH 대상에서 작업하려면 `--host`를 반복 지정하세요. `--json`은 `list`, `send`,
`doctor`, `update`에서 사용할 수 있습니다.

### JSON 응답 규약

모든 JSON 결과 객체는 동일한 스키마 버전 관리형 봉투로 시작합니다:

```json
{
  "schemaVersion": 1,
  "ok": true,
  "host": "mac-mini.example.ts.net",
  "command": "list",
  "sessions": [],
  "version": "0.8.0"
}
```

- `schemaVersion`은 공통 봉투의 버전을 지정합니다. `clientUpdate` 및 `codexHomeResolution`과
  같은 명령어별 중첩 스키마는 자체 버전을 전달합니다.
- `ok`는 모든 성공과 실패 시 존재합니다. 0이 아닌 프로세스 종료 코드라도 다른 호스트에
  대한 성공적인 결과를 포함할 수 있습니다.
- `host`는 해당 결과가 적용되는 대상을 식별합니다. 로컬 결과는 OS 호스트 이름을
  사용합니다. Tailscale로 확인된 대상은 검증된 MagicDNS 식별자를 사용하며, `sshHost`는
  호출자가 제공한 다른 SSH 별칭을 보존합니다.
- `command`는 `list`, `send`, `doctor`, `update` 중 하나입니다. 나머지 필드는 해당
  명령어의 페이로드이며, 실패 시 `error`와 구조화된 진단 필드가 추가됩니다.

로컬 또는 단일 호스트 호출은 하나의 객체를 출력합니다. `--host`를 반복하면 요청
순서대로 독립적으로 귀속 가능한 동일한 객체들의 배열이 출력됩니다. 잘못된 메시지
입력과 같이 연결 전에 발생하는 실패도 요청된 대상마다 한 번씩 출력됩니다. 이러한
카디널리티는 네 가지 명령어가 모두 공유하므로, 소비자는 객체 대 배열 여부만으로 분기한
후 동일한 봉투 필드를 사용할 수 있습니다.

일반적인 명령어는 전용 24시간 업데이트 캐시를 읽습니다. 캐시가 없거나 만료되었거나
유효하지 않은 경우 분리된 최선의 노력 GitHub 갱신이 시작되며, 요청된 명령어를 지연시키거나
변경하지 않습니다. 최신 캐시를 통해 호출 중인 CLI가 안정 릴리스보다 뒤처져 있음이
확인되면, JSON 결과에 `clientUpdate`가 추가됩니다:

```json
{
  "clientUpdate": {
    "schemaVersion": 1,
    "status": "available",
    "current": "0.7.0",
    "latest": "0.7.1",
    "checkedAt": "2026-09-16T10:00:00Z",
    "source": "github_release_cache",
    "command": "session-peer update"
  }
}
```

사람이 읽는 출력에서는 stderr를 통해 동일한 짧은 안내가 제공됩니다. 클라이언트가 최신
상태이거나, 캐시를 사용할 수 없거나 오래되었거나, 호스트가 오프라인이거나, 알림이
비활성화된 경우 이 필드는 생략되므로 필드의 부재만으로 클라이언트가 최신 상태임을
증명하지는 못합니다. 다중 호스트 명령어의 경우 이 사실은 호출하는 단일 CLI 범위에
국한되며 각 결과 객체에 복사됩니다. 대상의 `remoteVersion` 필드는 별도의 의미를
유지합니다. 원격 하위 프로세스는 자체적인 갱신을 수행하지 않습니다.

로컬의 `tailscale status --json`이 디바이스 호스트 이름, 짧은 MagicDNS 이름,
전체 MagicDNS 이름 또는 Tailscale IP로 `--host`를 식별하는 경우, session-peer는
현재의 MagicDNS FQDN을 검증하고 `host`로 보고합니다. SSH는 제공된 값을 대상 별칭으로
그대로 수신하며(다를 경우 `sshHost`로 별도 보고됨), `HostName` 재정의는 연결을 해당
FQDN으로 라우팅하고 `HostKeyAlias`는 기존 호스트 키 조회를 유지합니다. 이를 통해
일치하는 `Host`, `User`, `Port`, `IdentityFile` 설정이 유지됩니다. 오프라인으로 보고된
알려진 피어는 SSH 연결 전에 실패합니다. 테일넷 맵에 없는 호스트는 일반적인 SSH 대상으로
유지됩니다.

호스트 식별자는 로그인 계정을 제공하지 않습니다. `known_hosts`, Tailscale 피어 및
MagicDNS 이름은 OS 사용자가 아니라 머신을 식별합니다. 계정을 `--host USER@HOST`로
지정하거나 원래 별칭에 대해 구성하세요:

```sshconfig
Host web-01
    User deploy
```

명시적인 `USER@HOST`가 우선합니다. 그렇지 않은 경우 session-peer는 유효한 OpenSSH
구성 또는 로컬 사용자 기본값을 보고하기 위해 동일한 별칭과 옵션으로 `ssh -G`를
실행합니다. 다른 머신에서 추측하거나 다른 사용자 이름으로 실패한 로그인을 재시도하지
않습니다.

성공적인 원격 결과 및 SSH 연결 실패 시 `sshUser` 및 `sshUserSource`가 추가됩니다.
소스는 `explicit`, `ssh_config_or_local_default`이거나, `ssh -G`가 이를 확인할 수 없는 경우
`unknown`입니다. 연결 실패 시 `authentication_failed`, `host_key_failed`, `timeout`,
`transport_failed`로 분류되는 `sshFailure`도 추가됩니다. 인증 오류는 호출자에게
`--host USER@HOST` 또는 원래 별칭의 SSH `User` 설정을 안내하며 절대 재시도되지
않습니다.

종료 코드: `0` 명령어 성공(목록 조회 또는 dry-run 포함), `1` 운영 오류, `2` CLI 사용법
오류 또는 대상 없음으로 보고된 미해결 대상, `130` 중단됨(Ctrl-C). 롤아웃 부재를
포함한 Codex 큐 거부는 운영 오류(`1`)입니다. dry-run 중 저장된 스레드가 누락된 경우 `2`를
반환합니다. 전송 시의 종료 코드 `0`은 소비나 응답을 확인해주지 않습니다.

### 시간 제한 handoff 감시(v1.3 후보)

```sh
session-peer handoff status --correlation-id PREPARED_UUID --json
session-peer handoff watch --correlation-id PREPARED_UUID --watch-timeout 30 --interval-ms 1000 --json
```

로컬 소유자의 POSIX 기록에 있는 기존 준비 UUID를 사용합니다. 상태 조회는 단일 스냅샷을 유지하며 감시는 1..60초(기본 30) 동안 1000..5000밀리초 간격(기본 1000)으로 최대 61번 조회합니다. 두 값은 ASCII 정수만 허용합니다. 감시는 예산 안에 유효한 공개 결과를 구성할 수 있을 때만 최초 스냅샷을 출력하고 이후 공개 메타데이터/historyPhase가 바뀐 경우만 출력하므로 스냅샷이 없을 수도 있습니다. JSON 감시는 operation watch와 event snapshot 또는 end인 공통 schemaVersion 1 NDJSON 봉투를 사용하고 스냅샷에 기존 handoff 객체를 포함하며 status JSON은 유지합니다. 기한 종료의 코드 0은 감시 완료만 뜻하고 ACK나 대기 성공은 아닙니다. SIGINT는 130, 기록·출력 실패는 1, 잘못된 인자는 2입니다. 기록 부재·손상이나 ledgerEpoch 변경 시 감시를 중단합니다. historyPhase는 prepared, attempted, terminal, tombstone 또는 quarantined이며 attempted는 영속적인 시도 방지 기록을 뜻하고 실행 중이라는 의미는 아닙니다.

감시는 읽기 전용이며 의도·대기·수신 확인 생성, 기록 쓰기, 제출·깨우기를 수행하지 않습니다. 호스트·기기·Windows 경로나 Codex ACK를 추가하지 않습니다. 프레임은 16 KiB, 전체는 256 KiB로 제한하고 종료용 2 KiB를 남깁니다. 실제 파일 디스크립터 표준 출력에는 전용 격리 Python 출력 보조 프로세스 하나를 사용합니다. 크기가 제한된 직렬화된 공개 바이트만 받고 공유 디스크립터 플래그를 바꾸거나 기록·네이티브 데이터를 읽지 않습니다. 부모는 IPC까지 원래 총예산으로 제한하고 새 기록 읽기·검증 단계 전에도 기한을 확인합니다. 총 시간 안에서 최종 출력·정리에 100 ms를 남기므로 조회는 더 일찍 끝날 수 있습니다. 시간 초과·SIGINT·오류 시 보조 프로세스를 종료·회수합니다. 다만 중단할 수 없는 OS 작업이 있어 엄격한 실시간 보장을 제공하지는 못합니다. 부분 쓰기나 완료 응답 부재 시 종료를 포함한 후속 프레임을 금지하며 소비자는 잘린 마지막 NDJSON 줄을 거부해야 합니다. 보조 프로세스 완료는 OS 쓰기 완료이며 수신자 소비의 증거가 아닙니다. 스냅샷은 모든 이벤트를 빠짐없이 전달하는 스트림이 아니며 로컬 UTC 관측은 ACK 도착 순서의 증거가 아닙니다. 개인정보, 유지되는 제출·ACK·대기의 의미, 읽기 전용 수집기 조회와 기존 격리 조건은 [handoff 런타임 가이드](handoff-runtime.md)를 참고하세요. 감시는 네이티브 메시지 프로세스나 수집기를 시작하지 않습니다. 이 후보는 배포된 릴리스가 아닙니다. 페이로드·권한 다이제스트를 노출하지 않으며 공개 targetGeneration의 기존 계약은 유지합니다. 읽기 전용 기록은 불변 스냅샷 바이트를 읽은 뒤 파싱·검증 전에 공유 잠금을 해제합니다. 중단 시 최종 출력·정리는 남은 총예산 안에서 최대 100 ms로 제한합니다. 전체 성공에는 완전한 성공 종료 프레임과 종료 코드 0이 모두 필요합니다. 해당 프레임 뒤에도 정리가 실패할 수 있습니다. 0이 아닌 종료는 전체 실패이며 ACK를 상향 해석하거나 독립적으로 유효한 제출 사실을 버리거나 재시도해도 된다는 뜻은 아닙니다.

### 신뢰하는 로컬 SSH 설정 (v1.3 후보, 미출시)

Linux와 macOS에서는 `--host`를 지정한 로컬 CLI의 `list`, `send`, `doctor`, `update` 호출에서 `--ssh-config ABSOLUTE_PATH`와 `--trust-ssh-config`를 함께 사용해 기존 OpenSSH 설정을 선택할 수 있습니다. 두 플래그가 모두 필요합니다. 다음은 예시 경로이며, 따옴표로 감싼 공백도 지원합니다.

```bash
session-peer list --host worker --ssh-config '/home/alice/SSH Profiles/work.conf' --trust-ssh-config
session-peer doctor --host worker --ssh-config '/home/alice/SSH Profiles/work.conf' --trust-ssh-config --check-return-route
```

이 선택은 해당 설정에 로컬 코드 실행 권한을 부여합니다. `Match exec`는 `ssh -G` 사용자 확인이나 `send --dry-run` 중에도 실행될 수 있습니다. 운영자는 `Include` 파일, `ProxyCommand`, 기타 외부 의존성도 신뢰해야 합니다. 검증은 설정 샌드박스가 아니며 의존성을 재귀적으로 검증하지 않습니다. 기존 프로필이나 설정 파일을 수정하지 않습니다.

경로는 절대 경로여야 하며 `..` 구성 요소, 제어 문자, 경로 내 심볼릭 링크를 허용하지 않습니다. 선택한 파일은 현재 유효 사용자가 소유한 일반 파일이어야 하고, 하드 링크 수가 정확히 1개이며, 최대 64 KiB여야 합니다. 그룹·다른 사용자 쓰기 권한과 setuid/setgid/sticky 비트도 거부합니다. 상위 디렉터리는 root 또는 현재 유효 사용자 소유여야 하며 그룹·다른 사용자 쓰기가 금지되어야 합니다. 단, root 소유의 sticky 디렉터리는 예외입니다. Linux에서는 확장 접근 ACL과 디렉터리 기본 ACL을 거부하고, macOS에서는 allow ACL 항목과 소유권이 비활성화된 볼륨을 거부합니다. ACL이나 소유권을 확인할 수 없어도 거부합니다. 이는 보수적 검사이며 전체 유효 권한 해석기는 아닙니다.

하나의 CLI 호출에서 같은 선택을 로컬 `ssh -G` 조회, doctor, 원격 목록·버전 확인, 업데이트 탐색·설치·검증, send/handoff SSH 호출에 재사용합니다. 매 SSH 실행 전에 파일 식별 정보·메타데이터·내용 해시와 저장 경로 안전성을 다시 확인합니다. 변경을 발견하면 기본 설정으로 대체하지 않고 거부합니다. OpenSSH는 원래 경로를 열기 때문에 불변 바이트 스냅샷이 아니며, 검증과 OpenSSH 읽기 사이에 같은 사용자가 변경하는 경쟁 조건은 남습니다.

이 모드는 `StrictHostKeyChecking=yes`, `UpdateHostKeys=no`, `ForwardAgent=no`, `PermitLocalCommand=no`, `BatchMode=yes`를 강제하고 연결 다중화를 비활성화합니다. 기존 명시적 호스트 키 고정이 우선합니다. `--ssh-opt` 허용 목록은 그대로이며, 여기서 `-F`와 `ProxyCommand`는 계속 금지됩니다. 선택한 로컬 경로는 원격 명령·응답 경로·공개 JSON으로 전달되지 않습니다. 역방향 doctor 검사는 원격 장비 자체 설정을 사용하고 이 경로를 상속하지 않습니다. 정방향 성공은 역방향 인증, 메시지 소비, ACK를 입증하지 않습니다.

환경 변수, MCP 요청, ReplyTo 주소, 저장된 프리셋에서는 이 모드를 선택할 수 없습니다. Windows, `setup`, 페어링된 기기 경로, 프리셋 조합, 응답 URI 대상, `--host` 없는 호출은 설정을 읽거나 SSH를 시작하기 전에 거부됩니다. 두 플래그를 생략하면 기존 기본 SSH 동작을 유지합니다.

### 일회용 페어링 링크(v1.3 후보)

양쪽 기기에 `pairing-offer-v1`과 기존 Unix Python 3.11+ relay 추가 의존성이 필요합니다. 다음은 후보 명령이며 공개된 v1.3 지원이 아닙니다.

```sh
session-peer device rotation-status --state /private/client-state
session-peer device offer --state /private/device-state --peer-key CLIENT-CURRENT-64-HEX-KEY --direct PRIVATE-IP:3770 --show-link
session-peer device pair --state /private/client-state --link --route direct
session-peer device offer-status --state /private/device-state --offer-id OFFER-UUID
session-peer device offer-cancel --state /private/device-state --offer-id OFFER-UUID
```

생성 시 양쪽 신원을 확인하고 소유자의 터미널에만 링크를 표시합니다. `--link`에는 값을 붙이지 않습니다. 크기가 제한되고 표시되지 않는 입력을 사용하며, 클라이언트가 별도로 확인한 수신 기기의 현재 키 지문을 입력한 뒤 신뢰를 등록하고 접속합니다. 터미널이 없으면 입력 노출이나 자동 승인 대신 거부합니다. 링크를 명령 인자, 브라우저 기록, 로그나 이슈에 남기지 마십시오. 설정 안내는 링크·비공개 파일을 선택할 수 있으며 기존 파일 명령도 유지합니다. 취소는 해당 초대의 보류 신뢰만 제거합니다. 완료된 페어링은 별도의 명시적 철회가 필요합니다. 기록 없는 만료 링크는 거부하고, 정확히 일치하는 저장 기록이 있어야 이미 완료된 인증 결과만 확인할 수 있습니다. 페어링은 수신 대상 정책이나 네이티브 CLI의 승인을 대신하지 않습니다. 키 교체 제한, 만료·횟수 제한, 중단과 위협 모델은 [기기 페어링 안내](paired-devices.md)를 참조하십시오.

<a id="updating"></a>
### 업데이트

macOS/Linux에서는 지정한 안정 버전 하나의 자동 런타임 알림만 숨기거나 그 설정을
해제할 수 있습니다.

```bash
session-peer update --dismiss-runtime-notice 1.3.1
session-peer update --clear-runtime-notice-dismissal
```

위 버전은 사용 예시이며 릴리스 발표가 아닙니다. 두 명령은 로컬 설정만 오프라인으로
변경하며 릴리스를 확인·설치·승인하지 않습니다. 원격/SSH 옵션이나 확인 옵션과 함께
사용할 수 없습니다. 정규화한 버전이 정확히 일치하는 알림만 숨기므로 이후 버전의
알림은 표시될 수 있고, 설정을 해제하면 기존 동작으로 돌아갑니다. 명시적인 로컬
확인은 실제 최신 버전과 구버전 여부를 그대로 보고하며 알림 설정은 별도 정보로
표시합니다. 원격 확인, 스킬 알림, 기존의 전체 알림 비활성화 설정은 바뀌지 않습니다.
원격 명령에서도 호출한 CLI 자체의 캐시 알림은 표시될 수 있습니다. 이때 로컬 설정은
대상별이 아닌 한 번만 읽으며, 원격 버전이나 결과는 해당 설정으로 숨기지 않습니다.

설정은 업데이트 캐시와 분리하여
`$XDG_CONFIG_HOME/session-peer/update-notices.json`에 저장합니다. 환경변수가 없거나
비어 있으면 `~/.config/session-peer/update-notices.json`을 사용합니다.
디렉터리와 파일은 안전한 소유권과 비공개 권한이 필요합니다. 안전하지 않은 경로는
수정하거나 다른 경로로 우회하지 않고 거부합니다. 손상되었거나 향후 스키마를 사용하는
파일은 알림을 숨기지 않으며 두 명령 모두 덮어쓰지 않으므로 전용 설정 파일을 먼저
확인하세요. Windows는 아직 버전별 설정을 지원하지 않지만 일반 업데이트·확인과
전체 알림 비활성화는 계속 사용할 수 있습니다.

안전 검사는 POSIX 소유권과 권한 비트를 확인합니다. ACL(접근 제어 목록)의 전체 검사나
물리 저장 매체의 내구성 인증은 수행하지 않습니다. 상위 경로의 심볼릭 링크와
상대 경로로 지정한 설정 위치는 다른 경로로 대체하지 않고 거부합니다. 파일시스템은
디렉터리 기준 입출력, 파일 잠금, 디렉터리 fsync(동기화)를 지원해야 합니다.
손상된 설정을 확인하고 백업한 뒤에는 운영자가 해당 전용 JSON 파일만 직접 제거하고
설정 명령을 다시 실행할 수 있습니다. 쓰기 작업이 실행 중일 수 있다면 잠금 파일을
제거하지 마세요. 자동 복구는 수행하지 않습니다.

패키지 관리자로 설치한 경우 명령어를 설치한 것과 동일한 관리자를 사용하세요:

```bash
pipx upgrade session-peer
# or: uv tool upgrade session-peer
# or, in its virtual environment: python -m pip install --upgrade session-peer
```

이러한 설치의 경우, 로컬 `session-peer update`는 패키지가 소유한 파일을 교체하지
않고 패키지 관리자 안내를 출력합니다. `session-peer update --check`는 최신 안정 GitHub
릴리스를 확인하고, 공유 캐시를 갱신하며, 정확한 업그레이드 명령어를 보고하지만 해당
파일들을 교체하지는 않습니다.

독립 실행형 프로그램의 경우:

```bash
session-peer update --check                       # check the latest GitHub release
session-peer update                               # update the local program
session-peer update --host web-01 --check         # inspect the remote standalone copy
session-peer update --host web-01                 # push this program if versions differ
```

원격 업데이트는 최신 GitHub 릴리스가 아니라 **로컬 프로그램의 버전**과 비교합니다.
원격 복사본이 없거나 더 오래된 경우에만 푸시하고, 원격이 더 최신이면 그대로 둡니다.
배포하기 전에 먼저 확인하고 로컬 프로그램을 업데이트하세요.
원격 복사본은 GitHub에서 가져오지 않습니다. 원격 버전 검사는
pip/pipx/uv 설치가 아니라 `~/.local/share/session-peer/session_peer.py`만 검사합니다.
원격 업데이트는 해당 독립 실행형 경로와 CLI 링크를 설치합니다. 패키지 관리자로
설치된 원격 CLI의 경우 해당 호스트에서 자체 관리자로 업그레이드하세요.

로컬 또는 원격 `update` 모두 Claude 스킬을 갱신하지 않습니다. 독립 실행형 프로그램과
스킬을 모두 갱신하려면 원하는 릴리스 체크아웃에서 `install.sh`를 다시 실행하세요.
로컬 `session-peer update --check` 및 `session-peer update`는 자동 알림에 사용되는
동일한 캐시도 채웁니다.

### Orca에서 관리하는 Claude 프로필

macOS에서 `CLAUDE_CONFIG_DIR`과 `ANTHROPIC_CONFIG_DIR`을 지정하지 않으면
`~/.claude/sessions`와 같은 사용자 소유의 알려진 Orca 경로
`~/Library/Application Support/orca/claude-profiles/*/home/sessions`를 검색합니다.
환경변수로 지정하면 기존 우선순위와 범위를 유지하며 다른 프로필로 검색을 넓히지 않습니다.
한 프로필만 확인하려면
`CLAUDE_CONFIG_DIR="/path/to/profile/home" session-peer list --agent claude --json`을
사용하세요. 설치 경로는 바뀌지 않습니다.

모든 플랫폼의 기본·명시적 등록 디렉터리 검색에는 전체 항목 4,096개, 등록 파일당
1 MiB 제한이 적용됩니다. 추가 Orca 프로필 검색만 macOS 전용이며 바로 아래 항목 128개로
제한합니다. 자동 검색하는 프로필 디렉터리의 심볼릭 링크·재분석 지점·다른 사용자 소유권은
거부합니다. 검색과 doctor는 인증정보·수신함 키·대화 기록을 읽지 않습니다.
같은 실제 등록 디렉터리의 별칭은 한 번만 검색합니다. 별도 기록이 같은 살아 있는 PID나
수신함을 주장하면 공개 메타데이터가 같아도 충돌입니다.

일부 오류가 있어도 정상 목록은 보존하지만, **살아 있는 세션 충돌을 포함한 검색 오류가
하나라도 있으면 관련 없는 정상 PID도 포함하여 모든 대상 선택을 거부**합니다.
이는 dry-run·전송·handoff에 모두 적용됩니다. 명시적 디렉터리는 다른 프로필의 오류를
분리할 수 있지만 선택한 디렉터리 내부 충돌이나 검색 한도를 해결하지는 못합니다.
기존 단일 디렉터리의 잘못된 기록 처리 방식은 유지합니다.
선택한 기록·수신함을 다른 프로필로 재검색하지 않고 확인합니다. 일반 Unix 소켓 별칭은
유지하지만 기존의 선택적 세대 확인 제한도 유지합니다. 세대 토큰은 전송 권한이나 ACK가 아닙니다.
모델 인증·모든 파일시스템 경쟁 제거·수신 증명을 제공하지 않으며, 다른 Orca 구조나 임의 설정
경로를 자동 검색하지 않습니다.

### 환경 변수

| Variable | Effect |
| :-- | :-- |
| `SESSION_PEER_REPLY_HOST` | 공지되는 응답 호스트를 재정의합니다: `--reply-to` → `SESSION_PEER_REPLY_HOST` → `CC_PEER_REPLY_HOST` → 자동 감지된 Tailscale MagicDNS 이름 또는 IP. 응답 라인을 생성하려면 감지 가능한 Claude 또는 Codex 발신자 세션이 여전히 필요합니다. |
| `CC_PEER_REPLY_HOST` | 레거시 대체 수단이며, 새로운 구성에는 `SESSION_PEER_REPLY_HOST`를 권장합니다. |
| `CLAUDE_CONFIG_DIR` | Claude Code가 구성을 보관하는 위치(기본값 `~/.claude`)입니다. 세션 검색을 위한 `session-peer list` 및 스킬 배치를 위한 `install.sh`에서 이를 따릅니다. |
| `ANTHROPIC_CONFIG_DIR` | `CLAUDE_CONFIG_DIR`이 설정되지 않은 경우 대체 수단입니다. |
| `CODEX_HOME` | Codex 검색/큐 홈(기본값 `~/.codex`)입니다. `--codex-home`에 의해 재정의됩니다. |
| `SESSION_PEER_CODEX_HOMES` | 암시적 전송/dry-run 전에 중복 스레드 UUID 및 안정적인 활성 작성기를 확인할 추가 대상 홈입니다. 셸 명령어나 경로 구분 목록이 아닌 절대 경로(또는 `~/…`)의 JSON 배열입니다. 목록을 병합하지는 않으며, 모호하지 않은 활성 작성기가 암시적 전송 홈을 변경할 수 있습니다. |
| `SESSION_PEER_NO_UPDATE_NOTICE` | `1`, `true`, `yes`, `on`으로 설정하여 자동 캐시 업데이트 알림 및 백그라운드 갱신을 비활성화합니다. 명령어별 해당 옵션은 `--no-update-notice`입니다. 명시적인 `session-peer update --check`는 여전히 확인을 수행합니다. |
| `XDG_CACHE_HOME` | 업데이트 캐시의 기본 디렉터리입니다. 설정되지 않은 경우 `~/.cache/session-peer/update.json`이 사용됩니다. |

`--host`를 사용하면 대상의 환경을 사용하여 검색하며, 로컬 환경 변수는 자동으로 전달되지
않습니다. `--codex-home` 및 `--codex-bin`은 해당 대상의 경로를 명시적으로 선택합니다.

## Codex 세션

Codex 검색은 읽기 전용 SQLite 연결을 사용하여 `state_5.sqlite`를 읽습니다.
이 내부 스키마는 실험적이며 macOS의 Codex CLI 0.154.0에서 테스트되었습니다.
크로스 플랫폼 픽스처 테스트가 모든 OS에서의 실제 Codex 검증을 주장하는 것은 아닙니다.
저장된 세션이 반드시 활성 상태인 것은 아닙니다. `--all`은 보관된 스레드를 포함합니다.

`--codex-home`은 대상의 `CODEX_HOME`(기본값 `~/.codex`)을 재정의합니다.
`--codex-bin`은 전송을 위한 `codex`의 PATH 조회를 재정의합니다. SSH에서 이는
원격 경로입니다. 전송하려면 `queue` 명령어가 있는 Codex 실행 파일과 해당 홈에
적절한 저장된 스레드/롤아웃이 필요합니다. 목록 조회만으로는 큐가 이를 수락할 수
있음을 증명하지 못합니다.

### SQLite 저장소 경계

독립적인 `list`는 메타데이터만 조회합니다. Codex를 실행하거나 버전을 조회하지 않으며, `--codex-bin`을 지정해도 목록 조회에 사용할 버전이 확인되는 것은 아닙니다. 따라서 macOS에서는 후보 SQLite DB를 열기 전에 일반 설정과 강제 설정을 모두 보수적으로 검사합니다. 구버전 로더에서 기본 홈의 오래된 DB를 잘못 조회하는 것을 막지만, 일반 설정을 무시하는 최신 로더의 정상 환경도 거부할 수 있습니다. 거부는 오류로 반환하며, 성공한 빈 목록이나 다른 DB로의 우회로 바꾸지 않습니다. 다른 에이전트의 정상 결과는 조회 불완전 오류와 함께 유지합니다. 진단은 저장소 설정의 모호함을 알리고, 운영자가 알려진 설정 계층과 유효한 `com.openai.codex` 설정·요건과 의도한 홈·저장소 구성을 확인하도록 안내합니다. `--codex-home`만 바꿔서는 전역 설정의 모호함이 해소되지 않습니다. 오류를 없애려고 설정, 관리 프로필이나 DB를 자동 삭제하지 마세요. native 로더가 실제로 해당 값을 무시하더라도 이 구성의 목록 조회는 보수적으로 미지원이며, 정확한 버전별 조회 지원은 별도 개선으로 다룹니다. send dry-run 내부의 목록 확인은 이미 선택한 전송 정책을 재사용하며 추가 버전 조회를 하지 않습니다.

전송과 그 내부 dry-run 검사에서는 선택한 native 실행 파일에 따라 macOS 설정 검사 정책이 달라집니다. 소스를 확인한 Codex 0.162.1은 강제 설정만 읽지만, Codex [0.154.0](https://github.com/openai/codex/blob/6b9826e3aa83b1a5947db50f4332cb9c65f1b340/codex-rs/config/src/loader/macos.rs)은 `CFPreferencesCopyAppValue`로 일반 설정도 읽습니다. macOS의 일반 큐 전송과 dry-run은 선택한 홈과 작업 디렉터리에서 `--version` 자식 프로세스를 한 번 실행합니다. 조회 3초와 정리 2초로 제한하고 표준 출력은 1 MiB, 진단 출력은 64 KiB까지 받습니다. 출력 내용은 반사하지 않으며, 형식이 잘못됐거나 확인할 수 없거나 소스를 검토하지 않은 버전은 버전만으로 거부하지 않고 일반 설정도 보수적으로 검사합니다. 프로세스 정리가 불확실하면 큐 제출 전에 거부하고, 중단 요청은 제한된 정리를 시도한 뒤 전달합니다. 정확히 `codex-cli 0.162.1`일 때만 강제 설정 전용 검사를 선택하며 이후 버전을 같다고 추정하지 않습니다. handoff는 기존 버전 조회와 원래 기한을 재사용하고 제출까지 선택한 정책을 유지합니다. 지원하는 0.154.0 wake 경로는 활성 writer에게 큐만 제출할 때도 일반 설정을 검사합니다. 예산 예약 및 자식 프로세스 실행 경계에서 저장소와 사용자 지정 마커를 다시 검사합니다. macOS 이외에는 새 버전 조회를 추가하지 않고 결과를 캐시하지 않으며 wake 지원 범위도 늘리지 않습니다. 확인된 큐 제출 이후 거부되더라도 제출 사실을 유지하고 다시 보내지 않습니다. 소스 기반 검사와 모의 회귀 테스트일 뿐 새로운 native 설정이나 MDM 실측은 아닙니다.

직접 시작하는 큐 및 wake 자식 프로세스는 상위 경로의 별칭까지 해석한, 실제로 존재하는 물리적 작업 디렉터리를 사용합니다. 프로젝트 검색, 자식 `cwd`, POSIX `PWD`, wake의 `thread/resume.cwd`가 같은 디렉터리를 사용합니다. 저장된 consumer 디렉터리가 존재하면 물리적 경로와 서로 다른 논리적 경로를 같은 마커 경계 및 사용자 지정 마커 대체 규칙으로 모두 검사하므로 별칭 설정을 보수적으로 거부할 수 있습니다. 사라진 consumer 디렉터리는 검사할 계층이 없다는 기존 처리를 유지합니다. 실행 중인 writer의 시작 설정이 확인되는 것은 아니며, 검사 후 별칭이나 설정이 바뀔 가능성도 남습니다. 결과의 `wake.cwd`도 이 물리적 경로를 사용하므로 저장된 별칭 표기와 다를 수 있습니다.

native 로더의 계층 목록 주석에는 `<cwd>/config.toml`이 있지만, 고정된 [프로젝트 계층 구성 코드](https://github.com/openai/codex/blob/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs/config/src/loader/mod.rs#L1652)는 `.codex/config.toml`을 불러옵니다. 이 검사는 오래된 주석이 아니라 실제 구현을 따릅니다. Windows Known Folder 조회가 성공했는데 반환 경로가 잘못됐거나 크기 제한을 넘으면 다른 디렉터리로 조용히 대체하지 않고 거부합니다.

wake는 예산 예약 전에 알려진 저장소 설정을 검사하지만, 예약 후 설정이나 쓰기 프로세스 증거가 바뀌면 후속 재검사에서 거부될 수 있습니다. 변환된 native 홈 경로는 상속된 cwd를 유지하며 Windows 소비자 디렉터리는 검사하지 않습니다.

2026-10-09 소스 조사에서는 native Codex [0.154.0](https://github.com/openai/codex/blob/6b9826e3aa83b1a5947db50f4332cb9c65f1b340/codex-rs/core/src/config/mod.rs)과 [0.159.0](https://github.com/openai/codex/blob/687a119f0fcaace47e1f1abcc77cec6c813fd6da/codex-rs/core/src/config/mod.rs)을 확인했습니다. 두 버전 모두 설정된 `sqlite_home`, 비어 있지 않은 `CODEX_SQLITE_HOME`, `CODEX_HOME` 순으로 SQLite 저장소를 선택합니다. 상대 환경 변수 경로의 기준은 native에서 결정한 작업 디렉터리입니다. [관리자 요구사항](https://github.com/openai/codex/blob/687a119f0fcaace47e1f1abcc77cec6c813fd6da/codex-rs/core/src/config/requirements.rs)은 명령행 재정의를 포함한 저장소 설정을 바꿀 수 있습니다. [native 큐 경로](https://github.com/openai/codex/blob/687a119f0fcaace47e1f1abcc77cec6c813fd6da/codex-rs/tui/src/session_queue_commands.rs)는 이미 실행 중인 공유 서버를 재사용할 수 있으므로 새 클라이언트의 환경만으로 서버의 저장소를 확인할 수 없습니다. 이는 소스 조사 결과이며 새로운 실제 전송이나 플랫폼 검증이 아닙니다.

2026-10-15 native Codex [0.162.1](https://github.com/openai/codex/tree/092d3acd6bec3e3a14bdc7e7a2810ab628ab759d/codex-rs) 조사 결과, 저장소 우선순위는 관리자 요구사항, 병합된 설정 계층, `CODEX_SQLITE_HOME`, `CODEX_HOME` 순입니다. `sqlite_home`을 설정할 수 있는 계층은 시스템 파일, macOS 관리 프로필, 사용자의 `config.toml`, `--profile`로 선택한 프로필 파일, native 프로세스 작업 디렉터리의 프로젝트 계층(작업 디렉터리부터 가장 가까운 기본 `.git` 루트까지의 `.codex/config.toml`, 루트가 없으면 작업 디렉터리만 해당하며 신뢰한 프로젝트에서만 활성화)입니다. 기존 `[profiles.*]` 테이블에는 저장소 키가 없습니다. `codex queue`는 홈의 `app-server-control/app-server-control.sock`에서 연결을 받는 app-server 데몬이 실행 중이면 그 데몬을 통해, 그렇지 않으면 내장 서버를 통해 제출합니다. native TUI는 `--no-daemon` 등으로 제외하지 않으면 기본적으로 이런 데몬을 자동으로 시작합니다. 데몬의 QueueStore는 시작할 때 선택한 데이터베이스를 유지하지만 `config/read`는 현재 디스크의 계층을 다시 읽습니다. `initialize`는 홈과 플랫폼을 알려주지만, 검토한 `initialize`, `config/read`, 큐 API에는 시작 시점 SQLite 정체를 증명하는 안정적인 계약이 없습니다. 스레드 UUID가 일치하거나 같은 서버에 연결되었다고 해서 저장소가 같다는 뜻은 아니며(복사한 데이터베이스에도 같은 UUID가 있을 수 있음), 큐 API에는 기대 저장소나 프로세스 세대 전제조건이 없습니다. 큐에 쌓인 메시지를 소비하는 프로세스는 자기 저장소의 큐를 폴링합니다. 이는 소스 조사 결과이며 실제 전송이나 플랫폼 검증이 아닙니다.

session-peer는 상속된 `CODEX_SQLITE_HOME`이 비어 있지 않거나 검사하는 홈의 설정에 루트 `sqlite_home`이 있으면 발견, 사전 검증, 큐 제출 전에 거부합니다. 설정 경로가 선택한 홈과 같아도 거부하며, 따옴표·이스케이프가 있는 루트 키와 루트의 점 구분 키·테이블도 포함합니다. 선택되지 않은 하위 키는 루트 저장소 설정으로 취급하지 않습니다. 빈 환경 변수 재정의는 native 자식 프로세스의 환경에서 제거합니다. 환경 변수 이름은 POSIX에서 대소문자를 구분하고 Windows에서는 구분하지 않습니다. 기존에 지원하는 native 홈 경로 변환은 유지하며 저장소 위치 변경 지원을 추가하지 않습니다. 또한 시스템 설정·요구사항 파일(`/etc/codex/config.toml`, `/etc/codex/managed_config.toml`, `/etc/codex/requirements.toml`, Windows에서는 Known Folder API의 ProgramData 디렉터리 아래 `OpenAI\Codex\config.toml`과 `requirements.toml`)과 macOS 관리 프로필 값에 루트 `sqlite_home`이 있으면 프로젝트 신뢰 여부와 관계없이 거부합니다. 큐 제출은 검사한 홈에서 native 프로세스를 시작하므로 호출한 위치의 디렉터리가 프로젝트 계층을 추가하지 않습니다. 사전 검증은 큐·app-server 자식 프로세스를 시작하지 않고(wake 및 macOS 일반 큐 사전 검증은 native 버전 확인 프로세스를 실행할 수 있음) 같은 실행 계획(홈, 자식 프로세스 작업 디렉터리, 환경, 알려진 계층, 소비 디렉터리)을 검사하고, 실제 전송은 효과 직전에 다시 검사합니다. 어느 쪽도 native Codex가 설정을 읽기 전의 시간차를 없애지 못하므로 사전 검증 통과가 다음 전송의 저장소 일치를 보장하지 않습니다. 사용자 정책에 따라 데몬 제어 소켓은 활성 여부와 관계없이 거부 사유가 아니며 session-peer가 연결을 시도하지도 않습니다. 데몬과 내장 서버 선택은 기존처럼 native Codex가 하며 저장소 권한을 주장하지 않습니다. 변환된 native 홈 경로를 제외하고, 사전 검증, 큐 제출, wake는 소비하는 쓰기 프로세스나 wake 서버가 보통 시작하는 저장된 스레드 디렉터리의 프로젝트 계층도 검사하며, 스레드 메타데이터를 읽을 수 없거나 형식이 잘못되었으면 거부합니다. wake는 대상별 예산을 예약하기 전에 이 저장소 검사를 수행합니다. 거부 사유는 `sqlite_environment_override`, `sqlite_home_configuration`, `sqlite_home_system_configuration`, `sqlite_home_managed_configuration`, `sqlite_home_project_configuration`, `consumer_directory_unverifiable`, `storage_config_unreadable`, `storage_config_unverifiable`입니다.

검사하는 TOML 파일은 최대 1 MiB의 UTF-8 일반 파일이어야 하며 심볼릭 링크는 허용하지 않습니다. Windows 시스템 디렉터리는 `SHGetKnownFolderPath(FOLDERID_ProgramData)`로 확인하며 API 실패 시 native Codex와 같이 고정된 `C:\ProgramData`를 사용합니다. `ProgramData` 환경 변수는 사용하지 않습니다. macOS에서는 CoreFoundation으로 Codex 설정 도메인을 동기화하고 소유한 값을 해제합니다. 강제 설정 전용 정책은 복사 후 강제 여부를 다시 확인하고 일반 사용자 설정은 무시합니다. 버전에 따라 선택한 보수적 정책은 위 설명대로 일반 설정도 읽습니다. 선택한 base64 문자열은 최대 2 MiB이며 최대 1 MiB의 UTF-8 TOML로 디코딩합니다. 동기화·형식·디코딩·크기 오류는 거부합니다. TOML 파일이나 설정값이 없어도 됩니다. 기본 프로젝트 탐색은 디렉터리가 아닌 가장 가까운 `.git` 항목(metadata만 확인) 또는 `HEAD`가 있는 .git 디렉터리에서 멈춥니다. 심볼릭 링크 marker는 보수적으로 거부하며, 루트가 없으면 작업 디렉터리만 검사합니다. `<cwd>/config.toml`은 프로젝트 계층이 아닙니다. 알려진 설정에 루트 `project_root_markers` 재정의가 있으면 사용자 지정 표식을 정확히 해석한다고 주장하지 않고 모든 상위 디렉터리를 보수적으로 검사합니다. API는 모의 테스트로 검증했으며 실제로 재배치한 Windows Known Folder와 강제 MDM 프로필은 시험하지 않았습니다. 읽을 수 없거나 변경·크기 초과·키 구문 판별 불가 상태인 파일은 내용을 출력하지 않고 거부합니다. 외부 의존성이 없는 키 판별기는 Python 3.9를 지원하지만 완전한 TOML·스키마 검증기는 아닙니다. 다른 값은 native Codex가 계속 검증합니다. 큐 제출과 wake는 자식 프로세스를 시작하기 전에 이 경계를 다시 확인합니다. 거부 결과는 `status=refused`, `submitted=false`, `retryAllowed=false`이며 정상적인 기존 출력과 쓰기 프로세스 소유권 검사는 바뀌지 않습니다. SSH에서는 발신자의 환경이 아니라 대상 기기에서 검사합니다.

변환된 native 홈(WSL relay 수신자가 native Windows Codex에 큐 제출)은 기존 제출 계약을 유지하지만 저장소 검증은 지원하지 않습니다. 이 POSIX 프로세스는 Windows 쪽 홈 표기, 대소문자 규칙, 환경, 시스템·관리·프로젝트 계층을 검사할 수 없습니다. 이런 경로를 효과 전에 거부하는 엄격 모드는 향후 가능하지만 구현하지 않았습니다.

이 변경은 한정된 방어 강화이며 모든 설정에서 native 저장소가 일치함을 증명하지 않습니다. 검사하지 않는 대상은 패키지 기본 설정, 엔터프라이즈 클라우드 설정 번들, 실행 중인 공유 데몬의 시작 시점 저장소, 이미 실행 중인 쓰기 프로세스의 `--profile` 선택·`-c` 재정의·환경 변수, 저장된 스레드 디렉터리가 아닌 곳에서 시작했거나 디렉터리가 사라진 쓰기 프로세스, 그리고 변환된 native 홈의 Windows 측 시스템·관리·프로젝트 계층입니다. 마지막 검사 후 설정이 바뀔 수도 있습니다. 검사 성공만으로 저장소 일치를 추론하지 마세요. [#268](https://github.com/abruption/session-peer/issues/268)은 이 계약의 native 플랫폼 검증을 위해 열린 상태로 유지합니다. 가짜 자식 프로세스 테스트는 거부와 환경 처리만 보여주며 실제 오대상 전송, 보안 악용, 새로운 native 호환성을 입증하지 않습니다. wake의 버전 지원 범위는 바뀌지 않습니다.

### Orca 및 여러 Codex 홈

Orca에서 실행된 세션은 계정별 홈을 사용할 수 있는 반면, 별도의 터미널이나 SSH 명령어는
`~/.codex`를 사용할 수 있습니다. 동일한 UUID가 양쪽 모두에 존재할 수 있습니다. 한 복사본에
대한 성공적인 큐 제출이 의도한 세션이 해당 홈을 사용하고 있음을 입증하지는 않습니다.

명시적인 대상 홈 지정은 여전히 가장 확실한 선택 방법입니다. 예를 들어, `<account-id>` 및
`<full-thread-uuid>`를 대상 계정 및 스레드로 바꿉니다:

```bash
session-peer list --host mac --agent codex \
  --codex-home '~/Library/Application Support/orca/codex-accounts/<account-id>/home' --json
session-peer send --host mac --to 'codex:<full-thread-uuid>' \
  --codex-home '~/Library/Application Support/orca/codex-accounts/<account-id>/home' \
  --dry-run --json "message"
```

로컬에서 사용할 때는 `--host mac`을 생략합니다. 제출할 준비가 되었을 때만 `--dry-run`을
제거하세요. `~`를 따옴표로 감싸면 대상 시스템에서 확장이 유지되며, 절대 원격 경로를
사용해도 됩니다. 현재 릴리스는 `--codex-home`을 대상 제약으로 처리하면서도 일치하는
모든 알려진 홈의 작성기 증거를 검증합니다. 이전 릴리스도 명시적 홈 문법은 받아들이지만
이 안전 보장은 제공하지 않습니다.

중복 홈 거부 기준은 v0.6.1에 도입되었습니다. 아래에 설명된 활성 작성기 선택, 재검증
및 상세한 `codexHomeResolution` 증거는 v0.6.2에 도입되었습니다. v0.6.1에서는 동일한
스레드 UUID가 둘 이상의 알려진 홈에 존재할 경우 명시적인 `--codex-home`이 필요합니다.

`--codex-home`이 없으면 선택 시 대상의 `CODEX_HOME`을 사용하고, 그 다음 `~/.codex`를
사용합니다. send 또는 dry-run 전에 모호성 방지 기능이 제한된 인벤토리를 확인합니다:

- 선택된 홈, 그리고 상태 DB가 존재하는 경우 기본 `~/.codex`.
- macOS 전용으로, `~/Library/Application Support/orca/codex-accounts/*/home` 바로 아래에
  존재하는 상태 DB.
- 대상의 `SESSION_PEER_CODEX_HOMES`에 지정된 추가 홈 (예시):

```bash
export SESSION_PEER_CODEX_HOMES='["/srv/codex/account-a", "/srv/codex/account-b"]'
```

이를 대상 명령어의 환경에 구성하세요. 로컬 export는 `--host`에 의해 전달되지
않습니다. Windows에서는 JSON의 요구 사항에 따라 백슬래시가 이스케이프된 절대
Windows 경로를 사용하세요. 빈 구성 배열은 허용되며, 형식이 잘못된 구성은 암시적
전송 시 오류가 됩니다.

모든 전송과 dry-run에서 session-peer는 UUID를 저장한 모든 알려진 홈을 찾고 각 홈의
정확한 `thread-writer-locks/<uuid>.lock`을 검사합니다. 단일 후보와 명시적
`--codex-home`도 포함됩니다. 커널 권고 잠금을 독립적으로 조사하고 두 번의 안정적인
`lsof` 관찰을 통해 연 프로세스를 상호 연관시킵니다. 암시적 전송은 안정적인 동일 사용자
Codex 작성기가 정확히 하나인 홈을 선택합니다. 명시한 홈은 그 작성기와 일치해야 하며,
다른 홈이 유일한 활성 작성기를 소유하면 명령은 구조화된 충돌을 반환하고 홈을 몰래
바꾸지 않습니다. 선택된 PID, 프로세스 시작 시각, 유지 중인 잠금은 큐 제출 직전에 다시
확인됩니다. 잠금이 비어 있거나 오래된 경우 단지 파일이 존재한다는 이유만으로 선택되지
않습니다.

알 수 없는 증거, 여러 활성 작성기, `lsof` 누락, 권한 실패, PID/시작 시각/inode 변경 및
상충되는 증거는 큐에 넣기 전에 안전하게 차단됩니다. 보관된 저장 복사본도 계산에
포함됩니다. 읽을 수 없거나 호환되지 않는 알려진 데이터베이스 및 누락된 구성 데이터베이스도
제출을 방지합니다. 모든 저장 복사본이 비활성이면 미래 resume용 큐를 의도적으로 넣을 때
명시적 `--codex-home`과 `--allow-inactive-codex-home`을 함께 사용해야 합니다. `--wake`는
이미 명시적인 활성화 opt-in으로 작동합니다. 명시 home 없이 inactive 플래그만 사용하면
거부됩니다. 확인된 심볼릭 링크 별칭 및 반복된 경로는 하나의 홈으로 계산됩니다.

`list`는 `--codex-home`이 정확히 하나를 선택하지 않는 한 알려진 홈들을 집계합니다.
일반적인 파일 시스템 검색이나 프로세스 환경 검사는 없으며 프로세스 인수는 노출되지
않습니다. 활동 검사는 SSH를 포함하여 대상 머신에서 실행됩니다. POSIX `flock` 또는
`lsof`가 없는 플랫폼은 live-writer 소유권을 확립할 수 없으며 그 증거가 필요할 때
안전하게 차단됩니다. 구성되지 않은/사용자 정의 레이아웃 및 검사 후 생성된 복사본은
여전히 누락될 수 있습니다. 제출하지 않고 선택한 홈, 제한된 후보, 실행 파일 및 지원되는
상태 DB 스키마를 검사하려면 `session-peer doctor`를 사용하세요.

### 제출 및 JSON 결과

제출은 데이터베이스 직접 쓰기가 아닌 `codex queue`를 사용합니다. `queued`는 CLI가
제출을 수락했음을 의미할 뿐, 턴에서 이를 소비했거나 확인했음을 의미하지 않습니다.
session-peer는 세션을 깨우거나 재개하지 않습니다. 큐 DB 쓰기 및 Claude 소켓 연결은
호출자의 실행 환경에서 승인이 필요할 수 있습니다. 이 도구는 샌드박스나 인바운드
정책을 변경하지 않습니다. 큐 시간 초과(30초)는 제출 결과를 알 수 없음을 의미하므로,
재시도하기 전에 대상을 검사하세요. 이는 응답을 기다리기 위한 시간 초과가 아니며,
session-peer는 자동으로 재시도하지 않습니다.

Codex 메시지는 측정된 Codex 서버 제한이 아닌 session-peer의 이식성 정책으로서
발신자/응답 헤더를 포함하여 32 KiB의 UTF-8로 제한됩니다. NUL 문자는 CLI 인수로
전달할 수 없습니다. `--dry-run`은 큐에 넣지 않고 실행 파일 및 저장된 대상을 확인하지만,
이후의 제출이 성공할 것이라고 보장할 수는 없습니다.

로컬 Codex 목록 JSON은 공통 응답 봉투를 사용하며 `sessions`, `version` 및
`discovery.codex.homes`의 홈별 진단 정보를 포함합니다. 각 세션 항목에는 `agent`,
`id`, `name`(첫 번째 줄, 최대 120자), `cwd`, `updatedAt`(유닉스 초), `archived`,
표준 `codexHome`, `stateDb`가 있습니다. 최상위 `codexHome`은 인벤토리 오류가 없는
단일 후보 홈에 대해서만 유지됩니다. 성공적인 각 원격 결과에는 동일한 필드와 설치된
독립 실행형 복사본에 대한 선택적 `remoteVersion`이 포함됩니다. 단일 원격 호스트는
객체를 반환하고, 반복된 호스트는 배열을 반환합니다.

설치 버전 조회는 보조 정보입니다. 조회가 실패해도 검색 결과와 주 작업의 종료 상태를
유지합니다. 이 경우 `remoteVersion`을 생략하고 원본 조회 진단 없이 제한된 이유
(`timeout`, `transport_failed`, `authentication_failed`, `host_key_failed`,
`invalid_response`, `probe_failed`)를 담은
`remoteVersionProbe: {status: "unknown", reason: ...}`를 포함합니다. 사람용 출력에는
버전을 알 수 없다는 안내가 표시됩니다. 미설치가 확인된 원격 대상은 기존처럼 두 버전
필드를 모두 생략합니다. 원격 업데이트의 버전 검증은 계속 필수입니다.

공통 봉투 내에서 Codex 전송 JSON은 `target: {agent, id}`, `status: queued`(또는
dry-run 시 `validated`), `chars`, `dryRun` 및 선택적 `queueId`를 포함합니다. 또한
다음 항목들도 포함됩니다:

- `codexHome`: 발신자 측의 추측이 아닌 확인된 절대 대상 홈.
- `codexHomeResolution`: 스키마 버전 관리형 `status`, `selected`, `reason` 및
  제한된 후보 증거. 상태는 `explicit`, `selected`, `ambiguous`, `unknown` 중
  하나입니다. 후보는 프로세스 인수나 환경 값 없이 저장된 스레드, 작성기 잠금,
  안정적인 소유자 PID 및 프로세스 시작 시각 팩트를 노출합니다.
- `submitted`: 큐 CLI가 성공적으로 완료된 후에만 `true`, dry-run의 경우 `false`.
- `consumptionConfirmed`: 항상 `false`. 큐에 추가됨이나 유효성 검증됨 모두 소비를
  증명하지는 않습니다.

오류 발생 시 공통 봉투의 `ok`를 `false`로 설정하고, `error`를 추가하며, 홈 증거로
인해 실패한 경우 `codexHomeResolution`을 포함합니다. 시간 초과는 제출 결과를
알 수 없음을 의미하며, 오류 발생 시 `submitted`가 누락되었다고 해서 아무것도 큐에
들어가지 않았다는 증거로 해석해서는 안 됩니다. 목록 조회 결과는 제출을 설명하지
않으므로 제출/소비 필드가 없습니다.

로컬 Codex 큐 시간 초과 또는 신뢰할 수 있는 완전한 응답이 없는 SSH 전송은
`status: unknown`, `reason: outcome_unknown`, `retryAllowed: false`를 노출합니다.
SSH 종료 코드 255 또는 137, 누락되거나 잘못된 stdout, 인증·호스트 키·인터프리터
진단만으로는 아무것도 제출되지 않았음을 증명할 수 없습니다. 완전한 버전 명시 응답은 이후
SSH 실패나 시간 초과가 발생해도 성공·거부 및 네이티브 제출 사실을 보존하며,
진단 stderr의 잘못된 UTF-8은 유효한 프로토콜 stdout을 무효화하지 않습니다.
실행 전 실패와 완료된 거부는 기존 필드를 유지합니다. 자동 재시도나 대체 경로를
시도하지 않으며, 결과를 알 수 없을 때 `submitted: false`를 추가하지 않습니다.
재시도 메타데이터가 없다고 해서 재전송이 허용되는 것은 아닙니다.

스키마 없는 기존 전송 객체는 `ok`가 불리언이고 `command` 필드가 있다면 `send`인 경우
일반 종료 코드 0/1/2에서 계속 허용됩니다. 비정상 종료나 종료 단계의 시간 초과가 발생하면
이 객체만으로 완료를 증명할 수 없습니다.

모든 명령어에서 단일 원격 호스트는 플랫 객체를 반환하고 여러 호스트는 배열을
반환합니다. `CODEX_THREAD_ID`(또는 호환성 대체 수단인 `CODEX_SESSION_ID`)가
존재하면 메시지 봉투와 응답 명령어가 발신 Codex 스레드를 식별합니다.

### 진단 및 응답 관찰

`doctor`는 세션을 소유한 머신에서 읽기 전용 검사를 수행합니다. Claude의 구성된
세션 디렉터리 및 인박스 가용성, Codex의 실행 파일 및 제한된 홈/상태 DB 후보, 지원되지
않는 DB 스키마, 권한 또는 알 수 없는 실패를 고유 코드로 보고합니다. 인박스에
연결하거나, 큐에 쓰거나, 임의의 디렉터리를 검색하거나, 에이전트/SSH 설정을 변경하지
않습니다.

역방향 SSH는 `--check-return-route`를 지정한 경우에만 검사됩니다. 대상 시스템은
프롬프트, 비밀번호 인증, 호스트 키 등록 및 구성 변조가 비활성화된 고정 `ssh ... true`
프로브를 실행합니다. 정방향 SSH의 성공이 역방향 경로가 작동한다는 증거로 절대
재사용되지 않습니다. 자동 Tailscale 감지로 출발지를 식별할 수 없는 경우
`--reply-to USER@HOST`를 사용하세요. JSON 세부 정보 및 상태 값은
[docs/diagnostics.md](diagnostics.md)에 문서화되어 있습니다.

일반적인 `--wait`는 의도적으로 제공되지 않습니다. Claude Code에는 동일 머신을 위한
기본 `notify_when_idle` 기능이 있지만, 원격 세션, 서브에이전트 또는 Codex에는 적용되지
않으며 성공적인 소켓/큐 제출이 확인을 의미하지도 않습니다. 따라서 session-peer는
변경 가능한 트랜스크립트를 추적하다가 잘못 일치시킬 위험을 감수하는 대신
`capabilities.replyObservation.status: unsupported`를 보고합니다. 완료 여부가
중요한 경우 대상에게 제공된 `Reply-To` 주소로 명시적 응답을 보내도록 요청하세요.
선택적 wake 기능은 [#46](https://github.com/abruption/session-peer/issues/46)에서
계속 추적 중입니다.

<a id="moving-from-cc-peer"></a>
## cc-peer에서 이전하기

저장소 이름 변경 및 패키지 전환이 완료되었습니다:
[session-peer 0.6.0](https://pypi.org/project/session-peer/0.6.0/)이 게시되었으며
[cc-peer 0.5.1](https://pypi.org/project/cc-peer/0.5.1/)은 Claude 전용 최종 호환성
릴리스입니다. **기존 PyPI cc-peer 프로젝트는 보관 처리되었으며, GitHub session-peer
저장소는 활성 상태로 유지됩니다.** 기존 레거시 배포판은 계속 다운로드할 수 있으며
마이그레이션을 위해 취소(yank)되지 않았습니다. 완료된 [전환 이슈 #48](https://github.com/abruption/session-peer/issues/48)을
참조하세요.

새 제품은 `pipx install session-peer`, `uv tool install session-peer` 또는
[독립 실행형 설치 프로그램](#installsh)을 통해 명시적으로 설치하세요.
`cc-peer` 명령어 별칭은 설치되지 않습니다. 두 제품은 공존할 수 있습니다.
워크플로를 확인한 후 패키지를 설치했던 동일한 관리자로 이전 패키지를 제거하세요(예:
`pipx uninstall cc-peer`). 스크립트 설치의 경우 고정된 cc-peer v0.5.1 태그의
`install.sh --uninstall`을 사용하세요. 실행하기 전에 경로를 확인하고 로컬 사용자 지정을
백업하세요. 새로운 uninstall은 session-peer 파일만 제거합니다.

스크립트 및 에이전트 지침을 업데이트하여 `session-peer`를 호출하고, 이전의
`~/.claude/skills/cc-peer/cc_peer.py`가 아닌 새로운 독립 실행형 프로그램 경로
`~/.local/share/session-peer/session_peer.py`를 사용하도록 하세요. 새로운 Claude 스킬은
`~/.claude/skills/session-peer/`에 별도로 위치합니다. Claude/Codex 구성, 세션 데이터 및
이전 설치본은 자동으로 마이그레이션되거나 제거되지 않습니다. 여유가 될 때
`CC_PEER_REPLY_HOST`를 `SESSION_PEER_REPLY_HOST`로 교체하세요. 이전 변수는 대체
수단으로 유지됩니다.

최종 cc-peer 릴리스는 지속적인 기능 또는 보안 유지 관리를 약속하지 않습니다. 동결된
루트의 `cc_peer.py`는 이전 자체 업데이트 URL을 위해 태그에 유지되지만, 새 휠 및
sdist에서는 제외됩니다. 해당 로컬 업데이트 명령어는 다른 제품을 설치하는 대신 사용자를
이곳으로 안내합니다.

## Claude Code 세션

### 공식 기능을 먼저 사용하세요

Claude 간의 워크플로의 경우 Claude Code의 내장
[세션 간 메시징](https://code.claude.com/docs/en/cross-session-messaging) 및
[Remote Control](https://code.claude.com/docs/en/remote-control)을 먼저 고려하세요.
session-peer는 해당 워크플로를 사용할 수 없거나 적합하지 않을 때 셸 기반의 로컬/SSH
경로를 제공하며, Claude 및 Codex 대상을 위한 공통 CLI를 제공합니다. 이 섹션의
Claude 전용 안내는 Codex 큐의 전제 조건이 아닙니다.

### 인박스 전송의 작동 방식

Claude Code의 [세션 인박스 소켓](https://code.claude.com/docs/en/cross-session-messaging#the-sessions-inbox-socket)은
한 줄의 JSON을 수락합니다:

```json
{"type":"user","message":{"role":"user","content":"your message"}}
```

session-peer는 해당 인박스를 소유한 머신에서 연결합니다. SSH 전송의 경우 Unix 소켓을
포워딩하는 대신 소스를 원격 `python3 -`에 파이프로 연결하여 그곳에서 연결을 설정합니다.
네이티브 Windows 대상은 명명된 파이프와 세션의 `.key` 파일에 있는 인증 라인을 대신
사용합니다.

세션 레코드는 일반적으로 `~/.claude/sessions/<pid>.json`에 있으며 `messagingSocketPath`에
소켓 경로를 보관합니다. `/tmp/cc-socks/`로 절대 추측하지 마세요. 이전 테스트에서는
해당 레이아웃과 `/run/user/1001/cc-socks/`가 모두 발견되었습니다. 바인딩된 인박스가 없는
활성 PID는 도달할 수 없는 것으로 처리됩니다. 레코드 스키마는 내부 인터페이스이며
변경될 수 있습니다. 오래되었거나 인박스가 없는 레코드를 검사하려면 `session-peer list --all`을
사용하세요. 레코드나 소켓의 존재가 호출자에게 쓰기 권한이 있음을 보장하지는 않습니다.

### 수신 측이 다음에 일어날 일을 결정합니다

**"게시됨"이 "전달됨"은 아닙니다.** 소켓에 쓰는 것은 성공하지만, Claude가 메시지를 읽을지 여부는 해당 세션의 [인바운드 제어](https://code.claude.com/docs/en/cross-session-messaging#control-inbound-messages)에 달려 있습니다.

메시지는 승인을 위해 보류되거나 거부될 수 있습니다. 이전 검증에서 우회 모드 수신자는
승인될 때까지 스크립트에서 시작된 메시지를 보류했습니다. 소켓 쓰기 성공으로 수신을
추론하거나 테스트를 통과시키기 위해 권한 모드를 변경하지 마세요.

워커가 무인 상태에서 수신 메시지를 수락하도록 의도적으로 구성하려면 해당 수신자를
명시적으로 구성하세요:

```json
{ "crossSessionInbound": "accept" }
```

단일 워커를 위한 것이라면 프로젝트 설정이나 `--settings`를 사용하여 범위를 지정하세요.
사용자 설정은 해당 OS 사용자의 다른 세션에도 영향을 줍니다. 메시지를 수락하면 수신
턴이 시작되어 사용량이 소모될 수 있습니다. session-peer는 사용자를 대신해 이 설정을
적용하지 않으며, 수신자 자체의 도구 권한이 계속 적용됩니다.

### 왜 `tmux send-keys`가 아닌가요?

터미널 키 입력은 의도한 대화 입력이 아니라 실행 중인 하위 프로세스나 권한 프롬프트로
들어갈 수 있습니다. session-peer는 대신 에이전트의 인박스/큐 경계를 사용합니다. Claude는
인박스 메시지를 사용자가 입력한 승인이 아니라 [수신 세션 규칙](https://code.claude.com/docs/en/cross-session-messaging#how-a-session-treats-an-incoming-message)의
적용을 받는 피어 텍스트로 처리합니다.

## 한계 및 제약 사항

- **발신자 식별은 최선의 노력입니다.** 감지 가능한 Claude 또는 Codex 세션 내부에서
  실행 중일 때, session-peer는 에이전트 자격이 부여된 텍스트 형식의 `From:` 헤더를
  추가합니다. 해당 컨텍스트 외부에서는 이를 생략할 수 있습니다. 이는 인증된 식별
  프로토콜이 아니며, 환경 변수와 세션 레지스트리는 로컬 힌트일 뿐입니다.
- **공지된 응답에는 작동하는 회신 경로가 필요합니다.** 에이전트 발신자 및 응답 호스트를
  확인할 수 있는 경우, `Reply-To` 및 호환성을 위한 `Reply:` 라인이 회신 경로를
  설명합니다. 정방향 SSH의 성공이 역방향 SSH 접근을 증명하지는 않으므로, 옵트인 방식의
  doctor 검사를 사용하세요. 해당 주소는 어떠한 접근 권한도 부여하지 않으며, session-peer는
  응답을 상호 연관시키거나 기다리지 않습니다.
- **Tailscale 상태는 로컬 라우팅 힌트입니다.** 알려진 온라인 피어는 현재의 MagicDNS
  이름으로 주소가 지정되고, 알려진 오프라인 피어는 SSH 전에 거부됩니다. 알 수 없는 대상은
  일반 SSH로 유지되며, session-peer는 모든 SSH 호스트가 테일넷에 속한다고 주장하지 않습니다.
- **베스천을 통과하는 검색은 지원되지 않습니다.** `--host`는 단일 SSH 홉입니다. SSH 구성의
  `ProxyJump`를 사용하여 직접 연결하세요.
- **대상 사용자와 실행 권한이 중요합니다.** Claude 인박스와 Codex 상태/큐는 대상 계정에
  속합니다. 올바른 계정과 홈을 사용하세요. `known_hosts` 항목은 해당 계정을 저장하지
  않습니다. 호출자의 샌드박스가 여전히 접근을 거부할 수 있으며, session-peer는 어느
  에이전트의 권한이나 할당량도 우회하지 않습니다.
- **`--host`와 `--ssh-opt`는 메시징뿐 아니라 SSH 접근 권한을 부여합니다.** 대상은 공백이나 셸 구문이 없는 단일 호스트 별칭 또는 주소여야 합니다. 설정 조회를 포함한 모든 `ssh` 실행 전에 옵션 허용 목록을 검사합니다. 허용 플래그는 `-4`, `-6`, `-p`, `-l`, `-i`, `-J`(값 분리 또는 결합), 그리고 `-oKEY=value` 또는 `-o` 다음의 `KEY=value`입니다. 허용 키는 Port, User, IdentityFile, HostName, HostKeyAlias, ConnectTimeout, BatchMode, ServerAliveInterval, ServerAliveCountMax, StrictHostKeyChecking, ProxyJump, IdentitiesOnly입니다. 대체 설정 파일, 제어 소켓, provider, 명령 hook을 포함한 나머지 옵션은 거부합니다. 기존 사용자·시스템 SSH 설정은 신뢰된 것으로 취급하며 그 자체로 명령을 실행할 수 있습니다. 이 필터는 해당 설정의 샌드박스가 아닙니다. 메시지 본문과 세션 이름은 셸 인용 처리됩니다. 명시적 `StrictHostKeyChecking`은 `yes`, `ask`, `accept-new`만 허용하고 `no`, `off`는 거부합니다. `UserKnownHostsFile` 경로 변경도 허용하지 않습니다. 강화된 문법은 SSH URI 형식의 점프 대상, 더하기 기호가 포함된 사용자명, 공백으로 구분한 옵션 대입을 거부합니다. 호스트 형식의 점프 대상과 등호 대입을 사용하십시오.
- **Windows 지원.** Claude의 명명된 파이프 전송이 지원됩니다. `install.sh` 및
  독립 실행형 원격 설치 프로그램/업데이터는 POSIX 셸을 사용하므로, 네이티브 Windows에서는
  Python 패키지 관리자를 사용하세요. 실제 Codex 검증은 macOS 전용으로 유지되며,
  Codex 홈, Reply-To, doctor 및 JSON 픽스처는 Windows CI에서 실행됩니다.

## 테스트

```bash
python3 -m unittest discover -s tests -v
```

기본 테스트 스위트는 실제 에이전트, SSH 서버 또는 네트워크를 필요로 하지 않습니다. 레거시
호환성 테스트, 공유 CLI 헬퍼, 픽스처 기반 Codex 검색 및 큐 하위 프로세스 테스트,
격리된 독립 실행형 설치/공존 검사가 포함됩니다. Codex 커버리지에는 argv/페이로드
처리, 대상 홈 선택, 실제 권고 잠금 조사, 안정적인 소유자 증거, 디스패치 없는 dry-run,
실패/시간 초과 시맨틱 및 원격 옵션 전달이 포함됩니다. 다중 홈 픽스처는 기본 및
Orca/구성된 홈 간의 중복 UUID, 고유/다중/변경되는 작성기 증거, 안전하게 차단되는
인벤토리 오류, 명시적 선택, 별칭 중복 제거, 단일 홈 호환성 및 구조화된 홈/제출
메타데이터를 재현합니다. 저장된 행에서 활성 작성기를 추론하거나 실제 세션에 메시지를
제출하지 않습니다. 업데이트 알림 커버리지는 최신 상태 및 만료, 엄격한 안정 버전,
원자적 프라이빗 쓰기, 단일 플라이트 백그라운드 갱신, 옵트아웃 동작, 패키지 관리자 안내,
다중 호스트 범위 및 실패 격리를 검사합니다.

CI는 Ubuntu 및 macOS(Python 3.9 및 3.13)와 Windows(Python 3.13, 여기서는 POSIX 설치
프로그램 테스트 생략)에서 테스트를 실행합니다. 별도의 작업에서 `shellcheck`를 통한 셸
구문, 독립 실행형 설치/재설치/제거, 휠/sdist 내용 및 설치를 확인합니다. 이것이 완전한
전송 커버리지는 아닙니다. Claude 검색 픽스처, 실제 UDS 페이로드 검사 및 더 광범위한
종료 코드/원격 명령어 회귀 테스트는 [#28](https://github.com/abruption/session-peer/issues/28)에서
계속 추적 중입니다.

## 검증 내역

### session-peer v0.8.0 릴리스 후보 (2026-09-16)

- #76, #77, #78, #80 및 #82에서 통합된 Claude/Codex 목록 조회, 선택적 MCP 도구 및
  Codex 플러그인, 명시적인 제한된 Codex wake, 다중 홈 Codex 목록 조회, 이름 지정된
  메시지 및 출력 서식 옵션을 통합했습니다.
- JSON 호환성, 선택적 종속성, Codex 0.154.0 wake 경계 및 유효성 검증 한계는
  [v0.8.0 릴리스 노트](releases/v0.8.0.md)를 참조하세요.
- MCP SDK를 사용하여 301개의 로컬 테스트를 통과했습니다. 독립 실행형 실행에서는 두 개의
  선택적 SDK 테스트를 건너뜁니다. 휠 및 sdist가 독립적으로 설치되었으며 v0.8.0을
  보고합니다.
- 릴리스 준비 작업은 GitHub 릴리스를 게시하거나 PyPI에 업로드하지 않습니다.

### session-peer v0.7.0 (2026-09-16)

- 캐시된 업데이트 알림, 공유 JSON 봉투, 읽기 전용 진단, 구조화된 Reply-To 파싱/라우팅,
  동일 머신 정규화 및 옵트인 역방향 경로 분류에 대해 240개의 로컬 테스트를
  통과했습니다.
- CI는 Ubuntu 및 macOS(Python 3.9/3.13), Windows(Python 3.13), 패키지 빌드 및 격리된
  설치, 독립 실행형 설치 스모크 테스트, shellcheck 및 시크릿 스캐닝을 포함합니다.
- 휠과 sdist 내용을 검사하고 독립적으로 설치했습니다. 두 아티팩트 모두 v0.7.0을 보고하며
  동결된 레거시 `cc_peer.py`를 제외합니다.
- 실제 SSH doctor 실행으로 Claude 인박스와 제한된 기본/Orca Codex 홈을 찾았습니다.
  옵트인 역방향 프로브는 성공적인 정방향 연결과 무관하게 인증 실패를 보고했습니다. 실제
  메시지는 제출되지 않았습니다.

### session-peer v0.6.2 (2026-09-15)

- UUID별 Codex 작성기 유효성 검증, 동일 머신 응답 로컬화, SSH 대상 사용자 해결 및
  구조화된 연결 실패 진단에 대해 198개의 로컬 테스트와 릴리스 빌드 검사를 통과했습니다.
- 휠과 sdist 내용을 검사하고 독립적으로 설치했습니다. 두 아티팩트 모두 v0.6.2를 보고하며
  동결된 레거시 `cc_peer.py`를 제외합니다.
- 릴리스 준비 과정에서 실제 메시지는 제출되지 않았습니다. 큐 수락, 소비, 확인 및
  역방향 SSH 연결 가능성은 여전히 별개의 결과입니다.

### session-peer v0.6.1 (2026-09-15)

- 중복 홈 보호, 발신자 에이전트 봉투 및 MagicDNS SSH 라우팅을 갖춘 v0.6.0 Codex
  어댑터를 통합한 후 174개의 로컬 테스트와 릴리스 CI 검사를 통과했습니다. 휠/sdist
  빌드 및 격리된 설치가 확인되었습니다.
- 로컬 Codex 목록 조회 및 명시적 홈 dry-run이 제출 없이 성공했습니다. Tailscale IP로
  제공된 읽기 전용 SSH 목록 조회는 현재 MagicDNS `HostName`을 통해 연결되었으며 원래
  값을 `sshHost`/`HostKeyAlias`로 유지했습니다.
- 릴리스 준비 과정의 일환으로 실제 메시지는 제출되지 않았습니다. 큐 수락, 메시지
  소비, 확인 및 역방향 SSH 연결 가능성은 여전히 별개의 결과입니다.

### session-peer v0.6.0 전환 (2026-09-10)

- 134개의 로컬 테스트와 릴리스 CI 검사를 통과했습니다. 휠/sdist 빌드 및 격리된 설치,
  실제 PyPI 설치, 패키지 관리자 업데이트 보호, 레거시 CLI의 공존/제거가 확인되었습니다.
- **두 대의 macOS 머신에서 Codex CLI 0.154.0**을 사용하여 로컬/SSH 저장 세션 검색,
  dry-run 및 실제 큐 제출이 작동했습니다. 제출된 본문은 큐 레코드와 일치했습니다. 이러한
  검사는 소비되거나 확인된 것이 아니라 **큐에 추가됨**을 확인했으며, 신뢰할 수 있는
  활성 세션 표시기를 설정하지는 못했습니다.
- 새 CLI를 통한 Claude 로컬/SSH 인박스 쓰기가 성공했습니다. 주간 사용량 한도로 인해
  새로운 수신 턴/응답 검증은 방지되었으므로, 해당 쓰기 작업이 완료된 왕복으로 주장되지는
  않습니다.
- 두 대의 macOS 호스트와 두 대의 Ubuntu 호스트에서 독립 실행형 CLI/Claude 스킬
  마이그레이션이 확인되었습니다. 설치 및 읽기 전용 검색 검사는 에이전트 턴을 시작하거나
  인바운드 설정을 변경하지 않았습니다.

릴리스 순서 및 검증 한계는 [RELEASING.md](../../RELEASING.ko.md) 및 [#48](https://github.com/abruption/session-peer/issues/48)을
참조하세요.

### 과거 cc-peer Claude 전송 검증

이름 변경 전, Claude Code **v2.1.263**을 Tailscale 네트워크 상의 SSH를 통해 5대의 머신에서
실행했습니다: macOS 26(Apple 실리콘) 2대, Ubuntu 24.04(arm64, 서로 다른 리전의
Oracle Ampere A1) 2대, Windows 10 22H2 1대. 이러한 과거 관찰 내역이 session-peer v0.6.0에서
모든 테스트가 반복되었음을 주장하는 것은 아닙니다:

- macOS에서 두 리전의 Linux 세션으로 전송했으며, 각각 수신 트랜스크립트에
  `type: user` 및 `origin.kind: "peer"`로 기록되었습니다.
- 페이로드 무결성 — 따옴표, 백틱, `$HOME` 및 이모지가 바이트 단위로 정확히 도착했습니다.
- 보류 경로: bypass-mode 세션에서 승인 대화 상자가 표시되었고, 승인 후
  `Released 1 held cross-session message`를 기록했습니다.
- 실제 환경에서의 두 가지 소켓 레이아웃: 한 Ubuntu 호스트에서는 `/tmp/cc-socks/`,
  동일한 빌드를 실행하는 다른 호스트에서는 `/run/user/1001/cc-socks/`.
- 세션의 `.key` 파일에서 읽어온 필수 인증 라인을 사용하는 Windows 명명된 파이프 전송(`\\.\pipe\LOCAL\cc-msg-<hash>`).
  Windows 머신에서 `list`, `send`, `--host`가 모두 검증되었습니다.

두 에이전트의 검색 형식은 업스트림 릴리스 간에 변경될 수 있습니다. 이전의 성공적인
전송 테스트가 최신 에이전트 빌드에서의 검색이나 전달을 보장하지는 않습니다.

## 라이선스

MIT

### 통합 세션 검색

기본 `list` 및 `list --json`은 Claude와 Codex를 함께 쿼리합니다. 이전의
Claude 전용 기본값을 유지하려면 `--agent claude`를 사용하고, Codex 전용으로 조회하려면
`--agent codex`를 사용하세요. 모든 세션 행에는 `agent: "claude" | "codex"`가 포함되며,
PID 및 스레드 UUID와 같은 에이전트별 필드는 변경되지 않습니다. 통합된 사람이 읽는
출력에는 AGENT 열이 포함됩니다. Claude 행이 Codex 행 앞에 위치하여 Claude 검색 순서를
보존하며, Codex 행은 업데이트 시간 내림차순, 그 다음 홈 및 UUID 순으로 정렬됩니다.

목록 응답에는 요청된 각 에이전트를 키로 하는 `discovery`가 포함되며,
`status: "ok" | "not_installed" | "error"`(중간 상태는 Codex 전용) 및 실패한
소스에 대한 `error` 설명이 포함됩니다. 검색 실패 시 성공적으로 검색된 세션을
유지하면서 `ok: false`, 최상위 오류 요약 및 종료 코드 1을 반환합니다. 자동으로
검색된 Codex 설치가 없는 것은 정상적인 빈 결과(`not_installed`, 종료 코드 0)입니다.
명시적으로 구성된 홈이 누락된 것은 오류입니다. Claude 세션 디렉터리가 누락된 것은
빈 결과입니다. 둘 다 실행 중인 Codex 프로세스의 증거는 아닙니다. 형식이 잘못된 개별
Claude 레코드는 이전과 마찬가지로 계속 건너뜁니다.

이러한 시맨틱은 로컬 및 SSH 모두에 적용됩니다. 반복된 호스트는 기존의 정렬된
배열에서 독립적인 결과를 유지하며, 실패가 하나라도 발생하면 전체 종료 코드는 1이
됩니다. Codex 목록 조회에는 기본, 환경 선택, Orca 및 구성된 홈이 포함됩니다. 해당
홈만 검사하려면 `--codex-home PATH`를 사용하세요. `--all`은 Claude의 오래된/인박스
없는 레코드를 유지하고 보관된 Codex 스레드를 포함합니다.

### 선택적 MCP / Codex 플러그인

구조화되고 대상이 제한된 `list_sessions` 및 `send_message` 도구를 사용하려면
Python 3.10+ 환경에서 `session-peer[mcp]`를 설치하고 [MCP 설정](mcp.md)을 따르세요.
기본 정책은 로컬 목록 조회만 허용합니다. 독립 실행형 CLI 및 셸 설치 프로그램은 기존
종속성 요구 사항을 유지합니다.

큐에 들어간 Codex 세션의 옵트인 활성화에 대해서는 [명시적 wake](wake.md)를 참조하세요.

후보 소스, 홈별 오류, 중복 UUID 및 전송을 위한 정확한 홈 선택에 대해서는
[다중 홈 Codex 목록 조회](multi-home-list.md)를 참조하세요.

### 내부 확장 아키텍처

에이전트 어댑터와 로컬/SSH 실행은 단일 파일 CLI를 유지하면서 내부 버전 관리형 규약을
공유합니다. [어댑터 개발](agent-adapters.md) 및 [아키텍처 결정](architecture/agent-transports.md)을
참조하세요. 외부 플러그인 로딩은 제공되지 않습니다. `doctor.capabilities.agents`는
구현된 list/send/wake/wait/ack 지원을 설명하지만 권한을 부여하거나 준비 상태를 증명하지는
않습니다.

`install.sh`는 로컬·SSH 갱신을 대상 파일시스템에서 준비하고 런타임·스킬을 모두 받은 후 임시 CLI 버전을 검증하여 런타임을 원자적으로 교체합니다. 다운로드·검증 실패 시 기존 런타임·실행기·스킬을 유지합니다. 전체 설치 파일의 트랜잭션, 서명 검증 또는 이후 스킬 관리자 실패의 롤백을 의미하지 않습니다. 기존 설치 관리자 소유권은 유지됩니다.

SSH는 하위 프로세스 시작 전에 최종 셸 인용 명령의 UTF-8 바이트 수를 검사합니다. 보수적 상한 131071바이트에는 base64 메시지·봉투·옵션·인용이 포함됩니다. 초과 시 로컬에서 `ssh_command_too_large`, `submitted: false`로 거부합니다. Unicode에는 글자 수만으로 충분하지 않습니다. 로컬 전송 제한은 그대로이며 이 검사만으로 모든 OS의 전체 인자·환경 공간을 보장하지는 않습니다.

네이티브 전달 시 session-peer는 상대 메시지의 모든 줄을 인용하고 발신 세션과 회신 경로를 검증되지 않은 주장으로 표시합니다. Codex와 Antigravity에는 상대 메시지가 사용자의 권한 부여가 아니라는 경고도 붙습니다. Claude Code는 이미 이 경고를 제공하므로 반복하지 않습니다. `--no-from`과 `--no-reply-to`는 발신 메타데이터만 생략하며 수신 측의 이 표시는 제거하지 않습니다. Reply-To는 실행 권한이 없는 경로 정보입니다. 주변 표시를 확인하고 제삼자에게 회신하기 전 세션 소유자에게 목적지를 확인하십시오. 이 표시는 혼동을 줄일 뿐 모든 프롬프트 주입을 막지는 않습니다. 표시와 이스케이프된 제어 문자도 메시지 한도에 포함되며, `chars`는 실제 전달할 인용된 텍스트의 길이입니다. 제출과 소비·ACK의 의미는 바뀌지 않습니다.

## 실제 SSH 연결의 호스트 키 확인 (개발 중)

`list`, `send`, `doctor --host`에 `--ssh-identity`를 추가하면
`sshIdentity`를 반환합니다. 지문과 키 종류는 실제 OpenSSH 호스트 키 확인과
완전한 원격 응답으로 확인합니다. 목적지·포트·키 조회 이름은 연결 전 설정
조회 결과이며, 최종 네트워크 목적지의 별도 증명이 아닙니다. 원격 응답이
완료되지 않은 키는 `observed`이며 `verified`로 표시하지 않습니다.

```sh
session-peer list --host workstation --ssh-identity --json
session-peer send --host workstation --to reviewer --message="Review this change" \
  --require-ssh-host-key 'SHA256:<previously-verified-fingerprint>' --json
```

위 자리표시자를 발견 결과의 확인된 지문으로 바꾸세요. 지문은 별도 시험
연결이 아니라 실제 전송 연결에서 인증·원격 실행 전에 확인합니다. 키가
바뀌면 거부하며, 키 교체 시 직접 확인한 새 지문을 지정해야 합니다. 이
모드는 연결 재사용을 끄고 엄격한 호스트 키 확인을 유지합니다. 조회 모드는
기존 known-hosts 신뢰를 사용하고, 고정 모드는 지정한 공개 키만 신뢰하며
known-hosts 파일에 기록하지 않습니다. 여러 기기가 같은 키를 쓸 수 있으므로
기기·계정·세션 세대·메시지 소비를 증명하는 값은 아닙니다.

개발 구현은 POSIX의 일반 Ed25519·RSA·ECDSA 키만 지원하며 호스트 인증서와
보안 키 방식은 지원하지 않습니다. 사용자 설정의 `KnownHostsCommand`는
덮어쓰지 않고 거부합니다. SSH 설정과 중간 경유 호스트의 신뢰는 운영자가
관리합니다. 별도 연결인 설치 버전 보충 조회는 이 모드에서 생략합니다.
완전한 응답 뒤 확인 기록이 없으면 기존 제출 증거를 유지하지만 필수 지문
조건은 만족하지 않으며 자동 재전송을 허용하지 않습니다.

옵션을 쓰지 않으면 기존 동작·출력이 유지됩니다. 공개 v1.0.4에는 포함되지
않았습니다. 로컬 검증은 확인 도우미·읽기 전용 SSH 설정·가짜 전송 경로와
전용 루프백 서버에 대한 실제 OpenSSH 연결을 포함합니다. 잘못된 지문에서는
인증·원격 실행 요청이 0회였으며 시험용 비밀 키는 메모리에만 두었습니다.
실제 원격 호스트나 실행 중인 에이전트의 검증은 아니며 플랫폼 CI도 필요합니다.
