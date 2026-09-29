# session-peer

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![PyPI 주간 다운로드](https://api.pepy.tech/badge/session-peer/week)](https://pepy.tech/projects/session-peer)
[![PyPI 월간 다운로드](https://api.pepy.tech/badge/session-peer/month)](https://pepy.tech/projects/session-peer)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abruption/session-peer/blob/main/LICENSE)

[English](https://github.com/abruption/session-peer/blob/main/README.md) · **한국어** · [日本語](https://github.com/abruption/session-peer/blob/main/README.ja.md) · [简体中文](https://github.com/abruption/session-peer/blob/main/README.zh-CN.md)

**하나의 CLI로 로컬 또는 SSH 원격의 Claude Code·Codex 세션을 찾고 메시지를 보내세요.**

다른 세션에 변경 검토, 진행 상황 보고, 작업 인계를 요청할 수 있어요.
각 에이전트의 기본 수신함과 큐를 사용하며, 응답 방식은 수신 에이전트가 결정해요.

<a id="see-it-in-action"></a>

## 데모

![Codex가 Claude Code에 요청을 보내고 명시적인 ACK를 받는 데모](https://raw.githubusercontent.com/abruption/session-peer/main/docs/assets/session-peer-live-codex-claude.gif)

session-peer 1.0.2로 실제 로컬 요청과 회신을 주고받았어요. Codex가 Claude Code에
요청을 보내고 `ACK DEMO-READY`를 받아요. CLI 출력과 메시지 발췌를 익명화해 다시 그린
약 22초 애니메이션이며 화면 녹화는 아니에요. 전송 성공만으로 ACK를 뜻하지는 않아요.

## 빠른 시작

<a id="installation-options"></a>

### 설치

Python 3.9 이상이 필요해요. 기본 로컬·SSH CLI는 외부 Python 패키지에 의존하지 않아요.
현재 안정판: **1.0.2**.

```bash
pipx install session-peer
session-peer --version
session-peer list
```

uv를 선호하면 `uv tool install session-peer`를 사용하세요. 네이티브 Windows,
가상 환경의 pip, 독립 스크립트·SSH 설치 방법은
[설치 가이드](https://github.com/abruption/session-peer/blob/main/docs/ko/cli-reference.md#install)에 있어요.

SSH 조회의 예시 호스트 `worker`를 실제 호스트 또는 별칭으로 바꿔주세요.
그런 다음 가상 세션 이름과 전체 UUID를 조회한 목적지로 바꿔주세요.

```bash
session-peer list --host worker
session-peer send --to api-worker --message "진행 상황을 알려주세요"
session-peer send --host worker --to 'codex:00000000-0000-4000-8000-000000000001' --message "변경 사항을 검토해주세요"
```

SSH 목적지에는 Python과 대상 에이전트의 기본 수신함·큐가 필요하지만,
session-peer CLI를 설치할 필요는 없어요. 사용자 지정 Codex 홈은 조회 결과의
`codexHome`을 `--codex-home`으로 지정하고, `--dry-run`으로 전송 없이 검증하세요.
세션을 소유한 목적지 계정을 사용하세요(`--host USER@HOST`).
SSH 접근 권한과 수신 세션의 권한이 적용돼요.

**`posted` / `queued`는 제출 확인이며 소비·ACK·작업 완료를 뜻하지 않아요.**
필요하면 명시적으로 회신을 요청하세요. 일반 전송은 비활성 Codex 목적지를 기본적으로 거부하고,
해당 세션을 시작하지 않아요. 결과가 불확실한 전송은 자동 재시도하지 마세요.

선택형 [에이전트 스킬](https://github.com/abruption/session-peer-skill)은 실행 프로그램과
별도로 설치해요. Skills CLI 명령은 설치 가이드를 참고하세요.

### 업데이트

실행 프로그램을 설치했던 관리자를 그대로 사용하세요.

```bash
pipx upgrade session-peer
# 또는: uv tool upgrade session-peer
# 또는, 해당 가상 환경에서: python -m pip install --upgrade session-peer
```

로컬 설치에서 `session-peer update`는 독립 스크립트 실행 파일을 교체하며,
패키지 설치본에는 업그레이드 안내를 제공해요. 이 명령은 스킬을 갱신하지 않아요.
스킬에는 원래 설치 도구(Skills CLI 또는 동봉 사본의 `install.sh`)를 사용하세요.
[업데이트 상세와 원격 제약](https://github.com/abruption/session-peer/blob/main/docs/ko/cli-reference.md#updating)을 참고하세요.

<a id="documentation"></a>

## 문서

- [문서 지도](https://github.com/abruption/session-peer/blob/main/docs/ko/README.md): 사용자·통합·운영·개발 가이드
- [CLI 참조](https://github.com/abruption/session-peer/blob/main/docs/ko/cli-reference.md): 옵션·JSON·설치 변형·마이그레이션
- [진단과 회신](https://github.com/abruption/session-peer/blob/main/docs/ko/diagnostics.md) · [여러 Codex 홈](https://github.com/abruption/session-peer/blob/main/docs/ko/multi-home-list.md)
- [AI 지원 설치](https://github.com/abruption/session-peer/blob/main/docs/ko/ai-assistant-guide.md) · [프로젝트 사이트](https://abruption.dev/projects/session-peer/) · [릴리스 노트](https://github.com/abruption/session-peer/releases)
- [릴리스 절차](https://github.com/abruption/session-peer/blob/main/RELEASING.ko.md)

[기기 페어링·암호화 Relay](https://github.com/abruption/session-peer/blob/main/docs/ko/paired-devices.md)는
Unix·Python 3.11 이상·`session-peer[relay]`와 고정된 기기 신원·명시적 수신 정책이 필요해요.
패키지 발행이 호스팅 서비스 가용성을 보장하지는 않아요.
블라인드 Relay는 애플리케이션 메시지 내용을 복호화할 수 없어요.
[MCP·Codex 플러그인](https://github.com/abruption/session-peer/blob/main/docs/ko/mcp.md)은 Python 3.10 이상과
`session-peer[mcp]`가 필요하며, MCP wake에는 `send`와 `wake` 권한이 모두 필요해요.
[Wake](https://github.com/abruption/session-peer/blob/main/docs/ko/wake.md)는 명시적으로 요청할 때만 실행되며,
턴을 시작하고 사용량을 소비하거나 프로젝트 파일을 바꿀 수 있어요.
[Antigravity 브리지](https://github.com/abruption/session-peer/blob/main/docs/ko/antigravity.md)는 실험 상태예요.

영어가 정본이며 한국어·일본어·중국어 간체 가이드의 정합성을 유지해요.
번역은 CLI의 출력 언어를 바꾸지 않아요.

## 라이선스

[MIT](https://github.com/abruption/session-peer/blob/main/LICENSE).

## 지원 및 보안

버그·기능 제안은 [GitHub Issues](https://github.com/abruption/session-peer/issues/new/choose)를 사용하세요.
보안 취약점은 공개 이슈가 아닌 [비공개 보고](https://github.com/abruption/session-peer/security/advisories/new)로 제출하고,
[보안 정책](https://github.com/abruption/session-peer/blob/main/SECURITY.ko.md)을 따라주세요.
공유할 진단 결과에서 비밀정보·대화·세션 ID·개인 경로를 가려주세요.

비공개 문의나 대체 보안 연락처는 제목에 `[session-peer]`를 넣어
[support@abruption.dev](mailto:support@abruption.dev)로 이메일을 보내주세요.
지원은 최선을 다하되 응답 시한을 보장하지 않아요. 이메일은 수동 검토하며 공개 이슈로 자동 게시하지 않아요.
영어·한국어 보고를 환영해요.
