# session-peer 문서

영어 문서가 정본입니다. 한국어, 일본어, 중국어 간체 문서는 같은 목차와 규범적
동작을 유지합니다. 목표에 맞는 가장 짧은 가이드부터 시작하세요. 프로토콜과 검증
기록은 검토 자료이며 별도의 설치 경로가 아닙니다.

## 사용자

- [CLI 레퍼런스](cli-reference.md)는 로컬·SSH 검색, 전송, JSON, 업데이트와 제한을 설명합니다.
- [진단과 회신](diagnostics.md)은 정확한 제출 상태와 안전한 문제 해결 방법을 설명합니다.
- [여러 Codex 홈](multi-home-list.md), [명시적 wake](wake.md), [Antigravity](antigravity.md)는 선택형 에이전트 흐름을 다룹니다.

## AI 지원 설정과 통합

- [AI 지원 가이드](ai-assistant-guide.md)는 에이전트에게 설정이나 검증을 맡길 때 사용하는 제한된 인계 문서입니다.
- [MCP](mcp.md)와 [에이전트 어댑터](agent-adapters.md)는 선택형 통합과 정책 경계를 설명합니다.

## 페어링 기기와 운영자

- [페어링 기기](paired-devices.md)는 직접 또는 호스팅된 종단 간 암호화 릴레이를 사용하는 사용자 경로입니다.
- [릴레이 인증](relay-auth.md), [수명주기와 복구](relay-lifecycle.md), [와치독](relay-watchdog.md), [엣지 정책](relay-edge-policy.md)은 운영자 참고 문서입니다.
- [배포 자료](../../deploy/README.md)는 재사용 예제와 Abruption KR 운영 참조를 구분합니다.

## 개발과 이력

- [v1 호환성 계약](compatibility-v1.md)은 안정적, 버전형, 마이그레이션형, 내부형, 실험적 표면을 분류합니다.
- [에이전트 전송 아키텍처](architecture/agent-transports.md)와 [릴레이 개발 계획](relay-development-plan.md)은 구현 경계를 설명합니다.
- [릴리스 노트](releases/v1.0.0-rc.2.md)는 현재 후보를 설명하고, [검증 기록](validation/69-rc.md)은 범위가 명시된 증거와 한계를 보존합니다.
- 완료된 relay69 프로토타입 소스는 고유 회귀 검사를 제품 릴레이 테스트로 옮긴 뒤 제거했습니다. 폐기된 프로토타입 코드는 Git 이력에 남아 있습니다.
