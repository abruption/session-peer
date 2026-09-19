# Antigravity CLI 어댑터 (실험적 기능)

이 실험적인 선택형 어댑터는 session-peer v0.9.0에서 사용할 수 있습니다.
`pipx install session-peer` 또는 `uv tool install session-peer`로 설치하십시오.
릴리스 제공 여부가 장기적인 운영 안정성을 보장하지는 않습니다.
내부 어댑터/트랜스포트 리팩터링(#47)을 사용하며, 페어링된 기기 전달을 위한 대상(#69)으로 승인될 수 있습니다. Antigravity 자체는 절대 자동으로 설치되지 않습니다. 필터링되지 않은 목록 조회에는 실행 중인 브리지 등록이 포함됩니다.

이는 사용자가 시작한 로컬 브리지와 [공식 agentapi 인터페이스](https://antigravity.google/docs/sidecars/)를 사용하여 **기존 TUI**로 전달합니다.
Mac 및 Linux CLI 1.2.4 실험을 통해 유휴 상태 전달이 입증되었습니다. 이후 macOS CLI 1.2.7 RC 시험에서는 문서화된 `agentapi send-message` 위치 인자를 맞춘 뒤 직접 전달과 공개 릴레이 전달이 모두 통과했습니다. CLI 사이드카 자동 시작 메커니즘은 확립되지 **않았습니다**. `agy -p` 및 `--conversation`으로 다른 작성기를 시작하는 것은 전달 대체 수단이 아닙니다. Windows 브리지 작업은 지원되지 않으며, 다른 어댑터는 해당 환경에서 계속 사용 가능합니다.

## 수신 TUI에서 등록

수신하는 agy TUI에 일반 도구 실행기를 통해 이 명령을 실행하도록 요청합니다:

```sh
session-peer antigravity-bridge serve --thread FULL-CONVERSATION-UUID
```

TUI를 소유한 계정으로 실행하십시오. 다른 사용자가 소유한 작업 공간 디렉터리는 CLI의 홈을 식별하지 않습니다. 기본 홈은 `~/.gemini/antigravity-cli`입니다. 사용자 지정 홈의 경우 `--antigravity-home /absolute/path`를 사용하십시오. 등록 시 조상 `agy` 프로세스, UID, 시작 시간 및 해당 정확한 홈과 대화에 대한 열린 현재 상태 파일을 확인합니다. Linux는 `/proc`을 사용하고, macOS는 `ps` 및 `lsof`를 사용합니다. macOS에서는 고정된 C 로캘로 프로세스 시작 시간을 읽으므로, 현지화된 TUI에서 시작한 브리지를 다른 로캘을 사용하는 릴레이 작업자도 검색할 수 있습니다.
열려 있는 presence FD는 신원의 증거이며, **보유된 커널 잠금의 증거가 아닙니다**.
일치하는 여러 조상 등록을 사용하여 발신자를 유추하지 않습니다.

브리지는 인증된 도구 환경을 상속하고 `<home>/bin/agentapi send-message`를 호출합니다. 프로세스 환경을 추출하거나 토큰을 복사하지 않습니다. 관련 없는 SSH 셸에서 실행하거나, 자격 증명을 조작하거나, 도구 권한 거부를 우회하지 마십시오. 일반 SSH 프로세스는 TUI를 대신하여 이 등록을 생성할 수 없습니다. 장기 실행 명령으로 시작하십시오. 준비 완료 JSON은 로컬 엔드포인트가 수신 대기 중임을 의미하며 모델이 무언가를 소비했음을 의미하지 않습니다.

기본값: 수명 3,600초(최대 86,400초), 최대 1,000개의 고유 요청(최대 10,000개). `--ttl` 및 `--max-requests`로 이러한 명시적 한도를 낮추거나 높일 수 있습니다. 데몬, 전역 사이드카 구성 또는 자동 재시작은 설치되지 않습니다.

## 검색 및 전송

```sh
session-peer list --agent antigravity --host ubuntu@worker --json
session-peer send --host ubuntu@worker --to antigravity:FULL-CONVERSATION-UUID \
  --antigravity-home /home/ubuntu/.gemini/antigravity-cli \
  --antigravity-generation GENERATION-FROM-LIST \
  --message 'Please review the proposed change' --json
```

로컬 전달의 경우 `--host`를 생략합니다. 일반 SSH 트랜스포트는 독립형 소스를 목적지로 스트리밍하므로 전송을 위해 원격 패키지 설치가 필요하지 않습니다. 수신 브리지가 이미 실행 중이어야 합니다. 등록된 세션은 필터링되지 않은 `list`에도 `agent: antigravity`, `antigravityHome`, `ownerPid`, `ownerStart`, `generation`, `status: registered`와 함께 나타납니다. 이 상태가 유휴 상태를 의미하지는 않습니다. 검색 범위는 `registered_bridges`입니다. `--all`을 지정하더라도 과거 세션이나 등록되지 않은 TUI 세션은 열거되지 않습니다. 이유가 `no_live_registration`인 `not_installed`는 agy가 설치되지 않았다는 증거가 아니라 실행 중인 브리지가 없음을 의미합니다.

`--antigravity-home`은 목적지에서 알려진 등록을 필터링합니다. 동일한 UUID에 대해 실행 중인 두 개의 홈은 필터링되지 않는 한 `ambiguous_home`으로 실패합니다. 세대 고정은 교체된 등록을 통한 전달을 방지합니다. `--dry-run`은 agentapi를 호출하지 않고 등록을 검증합니다. 본문은 32 KiB UTF-8로 제한됩니다. 네이티브 발신자 신원은 수신 TUI의 agentapi 신원이며, `From:` 헤더는 설명용일 뿐 원격 에이전트에 대한 암호화 인증이 아닙니다.

## 결과 계약

- `status: submitted`, `ok: true`, `submitted: true`는 agentapi가 종료 코드 0으로 종료되었음을 의미합니다.
- `consumptionConfirmed: false`는 계속 false로 유지됩니다. 자동화된 ACK/대기 기능은 제공되지 않습니다. `--wake`는 지원되지 않습니다. 필요한 경우 회신을 별도로 확인하십시오.
- 타임아웃, 시작 실패, 0이 아닌 네이티브 종료 코드 또는 유실된 브리지 응답은 `status: unknown`, `ok: false`, `retryAllowed: false`를 반환합니다. 자동으로 재전송하지 마십시오.
- 요청 유효성 검사 오류는 네이티브 호출 전에 거부됩니다. `reason` 및 `error`를 확인하십시오. 구조화된 응답 전의 원격 트랜스포트 실패 또한 결과를 알 수 없는 상태로 남겨둘 수 있습니다.
- `requestId`와 `generation`은 이번 시도를 식별합니다. 선택형 `--request-id UUID`에는 `--antigravity-generation UUID`가 필요합니다. **동일한 브리지 세대** 내에서 동일한 ID/본문은 `duplicateSuppressed: true`와 함께 캐시된 결과를 반환합니다. 해당 ID로 변경된 내용은 거부됩니다. 영구적인 보관함, 재시작 간 재생, 또는 정확히 한 번 보장은 없습니다. 알 수 없는 상태를 재시도하기 위해 ID를 변경하지 마십시오.

브리지에는 동일 UID 검사와 비공개 `/tmp/session-peer-agy-UID` 디렉터리(0700), 등록 및 소켓(0600), 제한된 프레임 JSON 읽기, 15초 네이티브 호출 타임아웃이 있습니다. 네이티브 stdout/stderr는 폐기되며, 오류에 시크릿은 포함되지 않습니다. agentapi에 전달된 메시지 본문은 네이티브 프로세스 인자이며 충분한 권한을 가진 프로세스 검사에 표시될 수 있습니다. 동일한 OS 사용자로 실행되는 다른 프로그램은 동일한 신뢰 경계 내에 있습니다.

## 중지 및 재등록

```sh
session-peer antigravity-bridge stop --thread FULL-CONVERSATION-UUID
```

사용자 지정된 경우 동일한 홈 옵션을 사용하여 수신 머신/계정에서 실행합니다. 중지, TTL, 소유자 사망, SIGINT/SIGTERM/SIGHUP은 소켓 및 등록을 제거합니다. 활성 네이티브 요청은 15초 마감 시간만큼 정리를 지연시킬 수 있습니다. SIGKILL 또는 머신 장애는 정리를 실행할 수 없습니다. 다음 serve는 오래된 파일을 제거하기 전에 배타적 잠금을 유지하고 새 세대를 사용합니다. 스플릿 락 경쟁을 방지하기 위해 작은 잠금 파일이 의도적으로 남아 있습니다. 활성 잠금 파일의 링크를 해제하지 마십시오.

TUI 재시작 후 해당 TUI에서 다시 명시적으로 등록하십시오. 검색 시 소유자를 다시 확인하므로 오래된 경로나 재사용된 PID만으로는 충분하지 않습니다. 권한 또는 검사 실패로 인해 세션을 전송 가능한 상태로 만들 수는 없습니다. `doctor`는 실행 중인 브리지가 없을 때 Antigravity를 `disabled`로 보고합니다. 이 선택형 기능은 정상적인 Claude/Codex 설정을 저하시키지 않습니다.

MCP에는 명시적인 대상 `agents: ["antigravity"]` 및 `send` 권한이 필요합니다. 소스 등록은 전송 권한을 부여하지 않습니다. MCP는 현재 사용자 지정 Antigravity 홈/세대를 고정할 수 없습니다. 해당 제어에는 CLI를 사용하십시오. 여러 홈은 모호한 상태로 유지되며 안전하게 실패합니다. Reply-To URI는 홈 핀이 아닌 agent/UUID를 전달합니다.

## 검증

`python3 -m unittest tests.test_antigravity -v`는 조각화되거나/잘못되거나/크기가 초과된 프레임, 정확한 대상/세대 검사, PID 재사용, 권한, 요청 충돌, 타임아웃, dry-run, SSH 구조화 결과, 발신자 신원 및 MCP 허용 목록을 다룹니다. 실제 Unix 소켓 + 자식 프로세스 픽스처는 모델 자격 증명 없이 SIGTERM 정리 및 오래된 상태에서의 재시작을 테스트합니다. 실시간 테스트 경계 및 남은 작업에 대해서는 [개발 검증](validation/85-antigravity.md)을 참조하십시오.
