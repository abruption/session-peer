# session-peer CLI 레퍼런스

[개요로 돌아가기](../../README.ko.md)

명령어의 상세 동작, 설치 옵션, 전송 한계 및 과거 검증 내역은 아래와 같습니다.

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

<a id="install"></a>
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

명령어와 스킬을 한 단계로 모두 설치합니다. 에어갭 호스트나 SSH를 통한 원격 배포에
사용하세요:

```bash
git clone https://github.com/abruption/session-peer && cd session-peer

./install.sh                          # this machine
./install.sh --host build-server      # a remote machine, over SSH
./install.sh --host web-01 --host db  # several at once
```

이렇게 하면 `session_peer.py`가 `~/.local/share/session-peer/`에 배치되고,
`~/.claude/skills/session-peer/`에 [session-peer 스킬](https://github.com/abruption/session-peer-skill/blob/main/session-peer/SKILL.md)의 호환 사본이
설치되며, `~/.local/bin/session-peer`가 링크됩니다. 기존 cc-peer 파일은 유지됩니다.
`./install.sh --uninstall [--host ...]`로 제거할 수 있습니다.

`session-peer update`는 최신 GitHub 릴리스에서 독립 실행형 프로그램을 갱신합니다.
`./install.sh --host <host>`는 이 체크아웃의 프로그램과 스킬을 SSH를 통해 푸시합니다.
`session-peer update --host <host>`는 설치된 버전이 다르거나 없을 때 프로그램만
푸시합니다. 아무것도 변경하지 않고 보고만 받으려면 `--check`를 추가하세요.
패키지 관리자 설치 및 원격 제한 사항에 대해서는 [업데이트](#updating)를 참조하세요.

**원격 설치는 파일들을 SSH 연결 자체를 통해 푸시하므로**, 대상 시스템에 인터넷 액세스가
필요하지 않습니다. 독립 실행형 파일을 설치하려면 `python3` 및 SSH 접근 권한이
필요합니다. 메시징을 수행하려면 대상 시스템에 선택한 에이전트의 기본 인박스 또는 큐도
있어야 합니다.

또는 설치 프로그램을 완전히 건너뛰고 단일 파일만 복사할 수도 있습니다:

```bash
curl -O https://raw.githubusercontent.com/abruption/session-peer/main/session_peer.py
chmod +x session_peer.py
```

<a id="the-skill"></a>
### 스킬

공개 스킬 정본은 [session-peer-skill 저장소](https://github.com/abruption/session-peer-skill)에서 관리합니다.
독립 실행형 설치 프로그램은 에어갭과 SSH 설치를 위해 호환 사본을 유지하며
`~/.claude/skills/session-peer/SKILL.md`에 배치합니다. 배치 경로는 기본값 이전에
`CLAUDE_CONFIG_DIR`, 그 다음 `ANTHROPIC_CONFIG_DIR`을 따릅니다. Claude Code, Codex,
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

<a id="updating"></a>
### 업데이트

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
원격 버전이 더 최신이더라도 푸시하므로, 배포하기 전에 먼저 확인하고 로컬 프로그램을
업데이트하세요. 원격 복사본은 GitHub에서 가져오지 않습니다. 원격 버전 검사는
pip/pipx/uv 설치가 아니라 `~/.local/share/session-peer/session_peer.py`만 검사합니다.
원격 업데이트는 해당 독립 실행형 경로와 CLI 링크를 설치합니다. 패키지 관리자로
설치된 원격 CLI의 경우 해당 호스트에서 자체 관리자로 업그레이드하세요.

로컬 또는 원격 `update` 모두 Claude 스킬을 갱신하지 않습니다. 독립 실행형 프로그램과
스킬을 모두 갱신하려면 원하는 릴리스 체크아웃에서 `install.sh`를 다시 실행하세요.
로컬 `session-peer update --check` 및 `session-peer update`는 자동 알림에 사용되는
동일한 캐시도 채웁니다.

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
- **`--host` 및 `--ssh-opt`는 사용자의 ssh 구성만큼만 신뢰할 수 있습니다.** 이들은 `ssh`에
  전달되므로, 이를 제어하는 사람이 사용자가 연결할 대상을 제어하게 됩니다. ssh가 로컬
  명령어를 실행하게 만드는 값(`ProxyCommand` 및 관련 항목)은 거부되며, `-`로 시작하는
  `--host`는 즉시 거부됩니다. 그러나 에이전트에 대해 `session-peer`를 허용 목록에
  추가하는 경우, 이는 단순한 메시징뿐만 아니라 SSH 권한을 부여하는 것으로 취급하세요.
  메시지 본문과 세션 이름에는 그러한 위험이 없습니다. 셸에 도달하기 전에 따옴표로
  처리되기 때문입니다.
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
