# session-peer

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![PyPI 월간 다운로드](https://api.pepy.tech/badge/session-peer/month)](https://pepy.tech/projects/session-peer)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abruption/session-peer/blob/main/LICENSE)

[English](https://github.com/abruption/session-peer/blob/main/README.md) · **한국어** · [日本語](https://github.com/abruption/session-peer/blob/main/README.ja.md) · [简体中文](https://github.com/abruption/session-peer/blob/main/README.zh-CN.md)

**하나의 CLI로 로컬 또는 SSH 원격의 Claude Code·Codex 세션을 찾고 메시지를 보내세요.**

다른 머신의 세션에 변경 검토, 진행 상황 보고, 작업 인계를 요청할 수 있어요.
예를 들어 SSH 호스트 `worker`의 `api-worker` 세션에 변경 검토를 요청해요.
각 에이전트의 기본 수신함과 큐를 사용하며, 메시지 처리 방식은 수신 에이전트가 결정해요.

## 빠른 시작

Python 3.9 이상이 필요해요. 기본 CLI는 외부 Python 패키지에 의존하지 않아요.

```bash
pipx install session-peer
# 다른 방법: uv tool install session-peer

session-peer list
session-peer list --host worker
```

## 첫 메시지 보내기

아래 이름과 UUID는 가상 예시예요. 먼저 목적지를 조회한 뒤 실제 세션으로 바꿔주세요.

```bash
session-peer send --to api-worker --message "진행 상황을 알려주세요"
session-peer send --host worker --to 'codex:00000000-0000-4000-8000-000000000001' --message "변경 사항을 검토해주세요"
```

`worker`는 SSH 호스트 또는 별칭, `api-worker`는 조회한 세션 이름으로 바꿔주세요.
예시 UUID는 목적지에서 조회한 전체 스레드 ID로 바꿔주세요.
목적지에는 Python과 대상 에이전트의 수신함·큐가 필요하지만, SSH 조회·전송을 위해
session-peer를 별도로 설치할 필요는 없어요.

**`posted` / `queued`는 제출 결과이며 읽음·작업 완료를 뜻하지 않아요.**
저장된 Codex 스레드가 실행 중이라는 보장도 없어요. 완료 확인이 필요하면 명시적으로 회신을 요청하세요.

## 자주 쓰는 기능

| 작업 | 명령 / 안내 |
|---|---|
| 에이전트별 조회 | `session-peer list --agent codex` |
| 연결·에이전트 설정 진단 | `session-peer doctor --host worker` |
| 전송 없이 대상 확인 | `session-peer send --to api-worker --dry-run -m "hello"` |
| JSON 결과 출력 | `session-peer list --output-format json` |
| 파일에서 메시지 읽기 | `session-peer send --to api-worker -m - < message.txt` |
| 선택형 MCP 도구 / Codex 플러그인 | [MCP 설정](https://github.com/abruption/session-peer/blob/main/docs/mcp.md) |
| 큐에 제출한 Codex 세션 활성화 | [명시적 wake](https://github.com/abruption/session-peer/blob/main/docs/wake.md) |

## 설치 방법

`pipx`·`uv`를 사용하거나 활성화된 가상 환경에서 `python -m pip install session-peer`를 실행하세요.
독립 실행 CLI와 에이전트 스킬을 함께 설치하려면:

```bash
git clone https://github.com/abruption/session-peer
cd session-peer
./install.sh
# 원격 설치: ./install.sh --host worker
```

셸 설치기는 POSIX 환경이 필요해요. 네이티브 Windows에서는 Python 패키지 관리자를 사용하세요.
선택형 MCP 도구는 Python 3.10 이상과 `session-peer[mcp]`가 필요해요.
[설치 상세](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#install)를 참고하세요.

## 선택형 v0.9 기능

v0.9.0에서 제공하는 실험 상태의 [Antigravity](https://github.com/abruption/session-peer/blob/main/docs/antigravity.md)는 기존 TUI 안에서 브리지를 명시적으로 시작해야 해요. 필터 없는 `list`에는 실행 중인 등록 브리지도 표시돼요.
[기기 페어링·암호화 릴레이](https://github.com/abruption/session-peer/blob/main/docs/paired-devices.md)는 Unix·Python 3.11 이상·`[relay]` 확장이 필요해요. 기기 신원을 고정하며 대상은 운영자가 명시적으로 허용해야 해요. 자체 호스팅 WSS 릴레이는 메시지를 복호화할 수 없으며 NAT 통과나 호스팅된 공용 서비스는 제공하지 않아요.
릴레이 베타는 `pipx install 'session-peer[relay]'`로 설치해요. Antigravity와 릴레이는 추가 운영 검증이 필요하며 공개가 장기 안정성을 뜻하지는 않아요. 일반 로컬·SSH 명령은 외부 의존성 없이 유지돼요.

## 전송 전 확인

- 올바른 목적지 계정과 에이전트 홈을 사용하세요. 사용자 지정 Codex 홈은 조회 결과의 `codexHome` 경로를 `--codex-home`으로 지정해요. SSH 접근 권한과 수신 세션의 권한이 적용돼요.
- 일반 전송은 비활성 세션을 깨우지 않아요. 명시적 wake는 에이전트 실행과 사용량 소비를 일으킬 수 있으며, MCP에서는 별도 wake 권한이 필요해요.
- 진단 결과를 공유하기 전에 비밀정보·대화·세션 ID·개인 경로를 가려주세요.

## 문서

- [CLI 상세](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md): 명령, JSON, 환경 변수, 업데이트, 제약, 검증 이력
- [진단·회신](https://github.com/abruption/session-peer/blob/main/docs/diagnostics.md) · [여러 Codex 홈](https://github.com/abruption/session-peer/blob/main/docs/multi-home-list.md)
- [cc-peer에서 전환](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#moving-from-cc-peer) · [릴리스](https://github.com/abruption/session-peer/releases)
- [어댑터 개발](https://github.com/abruption/session-peer/blob/main/docs/agent-adapters.md) · [릴리스 절차](https://github.com/abruption/session-peer/blob/main/RELEASING.md)

네 언어 README는 같은 빠른 시작 내용을 제공해요. 상세 문서는 현재 영어로 제공해요.
번역을 수정할 때 명령·요구 환경·동작을 영어 README와 맞춰주세요. CLI 출력 언어는 변경되지 않아요.

## 문의·보안 제보

버그·기능 요청은 [GitHub Issues](https://github.com/abruption/session-peer/issues/new/choose),
취약점은 [비공개 제보](https://github.com/abruption/session-peer/security/advisories/new)를 이용하세요.
[보안 정책](https://github.com/abruption/session-peer/blob/main/SECURITY.md)도 확인해주세요.
비공개 문의 또는 대체 보안 제보는 제목에 `[session-peer]`를 넣어
[support@abruption.dev](mailto:support@abruption.dev)로 보내주세요.
응답 기한은 보장하지 않으며 메일은 수동 검토하고 공개 Issue로 자동 전환하지 않아요. 영어·한국어 제보를 받아요.

[MIT 라이선스](https://github.com/abruption/session-peer/blob/main/LICENSE).
