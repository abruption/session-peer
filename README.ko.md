<div align="center">

# session-peer

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![PyPI 주간 다운로드](https://api.pepy.tech/badge/session-peer/week)](https://pepy.tech/projects/session-peer)
[![PyPI 월간 다운로드](https://api.pepy.tech/badge/session-peer/month)](https://pepy.tech/projects/session-peer)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abruption/session-peer/blob/main/LICENSE)

[English](https://github.com/abruption/session-peer/blob/main/README.md) · **한국어** · [日本語](https://github.com/abruption/session-peer/blob/main/README.ja.md) · [简体中文](https://github.com/abruption/session-peer/blob/main/README.zh-CN.md)

**하나의 CLI로 로컬 또는 SSH 원격 환경에서 Claude Code·Codex 세션을 찾고 메시지를 보낼 수 있습니다.**

</div>

다른 세션에 변경 사항 검토, 진행 상황 공유, 작업을 이어받아 달라고 요청할 수 있습니다.
session-peer는 각 에이전트가 기본 제공하는 수신함과 큐를 사용하며, 응답 방식은 수신 에이전트가 결정합니다.

<a id="see-it-in-action"></a>

## 데모

![Codex가 Claude Code에 요청을 보내고 명시적인 ACK(수신 확인)를 받는 데모](https://raw.githubusercontent.com/abruption/session-peer/main/docs/assets/session-peer-live-codex-claude.gif)

session-peer 1.0.2를 사용해 실제 로컬 요청과 회신을 주고받았습니다. Codex가 Claude Code에
요청을 보내고 `ACK DEMO-READY`를 받습니다. CLI 출력과 메시지 발췌를 익명화해 다시 그린
약 22초 애니메이션이며, 화면 녹화본은 아닙니다. 전송 성공만으로 ACK가 확인되는 것은 아닙니다.

## 빠른 시작

<a id="installation-options"></a>

### 설치

Python 3.9 이상이 필요합니다. 기본 로컬·SSH CLI는 외부 Python 패키지에 의존하지 않습니다.
현재 안정판: **1.0.4**.

2026-10-07 유지보수 릴리스의 [릴리스 노트](docs/ko/releases/v1.0.4.md)를 참고하십시오. 패키지 공개와 운영 배포는 별개입니다.

릴리스 후보 **1.1.0**을 준비하고 있으며 아직 발행하지 않았습니다. 예정된 변경과 남은 검증 조건은 [후보 릴리스 노트](docs/ko/releases/v1.1.0.md)를 참고하십시오.

```bash
pipx install session-peer
session-peer --version
session-peer list
```

uv를 선호하면 `uv tool install session-peer`를 사용하십시오. 네이티브 Windows,
가상 환경에서 pip를 사용하는 방법, 독립형(standalone) 설치 및 SSH 배포 방법은
[설치 가이드](https://github.com/abruption/session-peer/blob/main/docs/ko/cli-reference.md#install)를 참고하십시오.

SSH 조회 예시의 호스트 `worker`를 실제 호스트 또는 별칭으로 바꾸십시오.
그런 다음 예시 세션 이름과 전체 UUID를 list 결과에 표시된 대상으로 바꾸십시오.

```bash
session-peer list --host worker
session-peer send --to api-worker --message "진행 상황을 알려주세요"
session-peer send --host worker --to 'codex:00000000-0000-4000-8000-000000000001' --message "변경 사항을 검토해주세요"
```

SSH 대상에는 Python과 대상 에이전트가 기본 제공하는 수신함·큐가 필요하지만,
대상에 session-peer CLI를 설치할 필요는 없습니다. 사용자 지정 Codex 홈을 사용한다면 조회 결과의
`codexHome`을 `--codex-home`으로 지정하고, 실제 전송 없이 `--dry-run`으로 검증하십시오.
세션을 소유한 대상 계정을 지정하십시오(`--host USER@HOST`).
SSH 접근 제어와 수신 세션의 권한은 그대로 적용됩니다.

**`posted` / `queued`는 제출 확인일 뿐, 메시지 소비·ACK·작업 완료를 뜻하지 않습니다.**
필요하면 명시적으로 회신을 요청하십시오. 일반 전송은 비활성 Codex 대상을 기본적으로 거부하며,
해당 세션을 시작하지 않습니다. 결과가 불확실한 전송은 자동으로 다시 시도하지 마십시오.

선택 사항인 [에이전트 스킬](https://github.com/abruption/session-peer-skill)은 실행 프로그램과
별도로 설치합니다. Skills CLI 설치 명령은 설치 가이드를 참고하십시오.

### 업데이트

실행 프로그램 설치에 사용한 패키지 관리자를 그대로 사용하십시오.

```bash
pipx upgrade session-peer
# 또는: uv tool upgrade session-peer
# 또는, 해당 가상 환경에서: python -m pip install --upgrade session-peer
```

로컬 설치에서 `session-peer update`는 독립형 런타임 파일을 교체하며,
패키지 설치본에는 업그레이드 방법을 안내합니다. 이 명령은 에이전트 스킬을 갱신하지 않습니다.
스킬을 업데이트할 때는 원래 설치 도구(Skills CLI 또는 동봉 사본의 `install.sh`)를 사용하십시오.
[업데이트 상세와 원격 제약](https://github.com/abruption/session-peer/blob/main/docs/ko/cli-reference.md#updating)을 참고하십시오.

<a id="documentation"></a>

## 문서

- [문서 지도](https://github.com/abruption/session-peer/blob/main/docs/ko/README.md): 사용자·통합·운영·개발 가이드
- [CLI 참조](https://github.com/abruption/session-peer/blob/main/docs/ko/cli-reference.md): 옵션·JSON·설치 변형·마이그레이션
- [진단과 회신](https://github.com/abruption/session-peer/blob/main/docs/ko/diagnostics.md) · [여러 Codex 홈](https://github.com/abruption/session-peer/blob/main/docs/ko/multi-home-list.md)
- [AI 도구를 활용한 설치](https://github.com/abruption/session-peer/blob/main/docs/ko/ai-assistant-guide.md) · [프로젝트 사이트](https://abruption.dev/projects/session-peer/) · [릴리스 노트](https://github.com/abruption/session-peer/releases)
- [릴리스 절차](https://github.com/abruption/session-peer/blob/main/RELEASING.ko.md)

[기기 페어링·암호화 Relay](https://github.com/abruption/session-peer/blob/main/docs/ko/paired-devices.md)는
Unix·Python 3.11 이상·`session-peer[relay]`, 고정된 기기 신원, 명시적 수신 정책이 필요합니다.
패키지를 공개해도 호스팅 서비스의 가용성이 보장되지는 않습니다.
블라인드 Relay는 애플리케이션 메시지 내용을 복호화할 수 없습니다.
[MCP(Model Context Protocol)·Codex 플러그인](https://github.com/abruption/session-peer/blob/main/docs/ko/mcp.md)은 Python 3.10 이상과
`session-peer[mcp]`가 필요하며, MCP wake 기능에는 `send`와 `wake` 권한이 모두 필요합니다.
[Wake](https://github.com/abruption/session-peer/blob/main/docs/ko/wake.md)는 명시적으로 요청한 경우에만 실행됩니다.
턴을 시작하고 사용량을 소비하거나 프로젝트 파일을 변경할 수 있습니다.
[Antigravity 브리지](https://github.com/abruption/session-peer/blob/main/docs/ko/antigravity.md)는 실험 단계입니다.

영어 문서가 정본이며, 한국어·일본어·중국어 간체 가이드는 영어 문서에 맞춰 관리합니다.
번역은 CLI의 출력 언어를 바꾸지 않습니다.

## 라이선스

[MIT](https://github.com/abruption/session-peer/blob/main/LICENSE).

## 지원 및 보안

버그 보고와 기능 제안에는 [GitHub Issues](https://github.com/abruption/session-peer/issues/new/choose)를 사용하십시오.
보안 취약점은 공개 이슈가 아닌 [비공개 보고](https://github.com/abruption/session-peer/security/advisories/new)로 제출하고,
[보안 정책](https://github.com/abruption/session-peer/blob/main/SECURITY.ko.md)을 따르십시오.
진단 결과를 공유할 때는 비밀정보·대화·세션 ID·개인 경로를 가리십시오.

비공개 문의나 대체 보안 연락은 제목에 `[session-peer]`를 넣어
[support@abruption.dev](mailto:support@abruption.dev)로 이메일을 보내십시오.
최선을 다해 지원하지만 응답 시한은 보장하지 않습니다. 이메일은 수동으로 검토하며 공개 이슈로 자동 게시하지 않습니다.
영어와 한국어로 제보할 수 있습니다.
