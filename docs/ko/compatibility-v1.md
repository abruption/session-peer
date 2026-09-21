# v1 호환성 계약

이 문서는 session-peer가 1.0.0부터 유지하려는 인터페이스를 정의합니다. 패키지 동작에
대한 계약이며 호스팅 릴레이의 가용성 계약은 아닙니다. `tests/fixtures/compatibility-v1.json`의
기계 판독 fixture가 이 정책의 실행 가능한 근거입니다.

## 호환성 등급

| 등급 | 의미 |
| --- | --- |
| Stable | v1 동안 기존의 유효한 입력과 필수 출력 의미를 유지합니다. 명시된 곳에는 필드를 추가할 수 있습니다. |
| Versioned | 호환되지 않는 변경은 새 명시 버전이 필요합니다. 이전 버전은 문서화된 마이그레이션 기간 동안 읽을 수 있습니다. |
| Migrated | 영속 데이터는 명시적인 버전 마이그레이션으로만 변경합니다. 일반 시작 과정은 이전 스키마를 다시 쓰지 않습니다. |
| Operator internal | 형식을 검증하고 복구할 수 있지만 제공된 도구만 편집합니다. 사용자가 작성하는 API가 아닙니다. |
| Experimental | 릴리스 노트와 이전 지침을 제공한 뒤 변경하거나 제거할 수 있습니다. |

“지원”은 CI와 문서화된 운영 경로를 유지한다는 뜻입니다. “시험됨”은 릴리스 근거에서
실행한 환경을 뜻합니다. “최선 지원”은 제한된 진단만 제공하며 릴리스 gate가 아닙니다.
“실험적”은 여기서 승격하기 전까지 v1 호환성을 약속하지 않습니다.

## CLI와 기계 판독 결과

명령, 문서화된 옵션, 옵션 우선순위와 종료 의미는 안정적입니다. 종료 `0`은 문서화된
제출 의미에 따라 명령이 완료됐음을, `1`은 명령 또는 전송 실패를, `2`는 argparse 사용
오류 또는 문서에 명시된 대상 없음 상태를 뜻합니다. 사람용 문구, 간격, 순서와 터미널
장식은 고정하지 않습니다.

JSON 스키마 버전 1은 안정적이며 필드를 추가할 수 있습니다. 각 명령 결과는 현재 타입의
`schemaVersion`, `ok`, `host`, `command`를 유지합니다. 단일 목적지는 객체 하나, 반복
목적지는 객체 배열을 유지합니다. 소비자는 알 수 없는 필드를 무시해야 합니다. v1 안에서
필수 필드를 제거하거나 타입을 바꿀 수 없습니다. 제출 필드는 명시적 ACK 필드가 없는 한
에이전트 소비나 응답을 뜻하지 않습니다. [CLI 레퍼런스](cli-reference.md)를 참고하세요.

## 회신 주소, MCP와 정책

`session-peer://v1/reply`는 버전이 있는 형식입니다. 필드는 제품 URI parser가 비활성
데이터로 읽으며, 알 수 없거나 중복되거나 안전하지 않은 필드는 닫힌 상태로 거부합니다.
호환되지 않는 주소 변경에는 새로운 URI authority 버전이 필요합니다.

MCP 도구 결과는 CLI JSON 결과를 `structuredContent`로 재사용하므로 CLI의 추가 필드는
MCP에서도 추가 필드입니다. MCP 정책 `schemaVersion: 1`과 릴레이 수신기 정책은 안정적인
엄격 allowlist입니다. 알 수 없는 정책 키는 거부합니다. 정책 capability를 추가하려면
문서화해야 하며 운영자가 선택하기 전까지 거부됩니다. [MCP](mcp.md)와
[페어링 기기](paired-devices.md)를 참고하세요.

## 기기 상태, 백업과 작업 영수증

기기 상태와 백업 manifest는 버전이 있는 운영자 관리 데이터입니다. 제공된 백업, 복원,
회전 명령으로만 이동합니다. 백업 manifest 스키마 1, 안정적인 기기 principal, 키 세대,
폐기 tombstone과 영속 작업 영수증을 조용히 재번호화, 재해석 또는 삭제할 수 없습니다.
호환되지 않는 변경에는 새 manifest 또는 DB 스키마와 명시적 마이그레이션·복구 fence가
필요합니다.

control과 replay DB, 공개 상태 snapshot, spent-ticket 파일과 revision high-water 기록은
운영자 내부 형식입니다. 불변조건은 안정적이지만 테이블과 JSON 배치는 사용자가 편집하는
공개 API가 아닙니다. [릴레이 수명주기](relay-lifecycle.md)의 마이그레이션과 복구 절차를
사용하세요.

## 릴레이와 endpoint 프로토콜

Endpoint TLS framing, 페어링 메시지와 relay/control HTTP 형식은 버전 협상 대상입니다.
현재 endpoint application protocol은 `session-peer-device-v1`이고 control 공개 상태와
replay 상태는 `schemaVersion: 1`을 사용합니다. 알 수 없는 버전은 닫힌 상태로 거부합니다.
blind relay는 평문을 볼 수 없어야 하며 OAuth나 relay admission은 endpoint pinning 또는
수신기 정책을 대체할 수 없습니다.

호스팅 제한, 서비스 가용성, OAuth 제공자 정책, edge 규칙과 운영 dashboard는 배포 동작이며
PyPI v1 가용성 약속이 아닙니다. 운영 설정이 바뀌어도 보안 경계와 영속 rollback 방지는
릴리스 gate로 유지합니다.

## 지원 행렬

| 표면 | v1 지원 경계 | 수준 |
| --- | --- | --- |
| Core CLI | Python 3.9+, macOS, Linux, native Windows | 지원 |
| MCP adapter | Python 3.10+, macOS와 Linux; MCP runtime이 stdio를 지원하는 Windows | 지원 |
| 페어링 수신기와 릴레이 | Python 3.11+, Unix; Windows endpoint는 문서화된 WSL 경계 사용 | WSL beta gate 이후 지원 |
| Control service | Linux arm64/x64의 Node 22와 24 | 지원 |
| Claude Code | CI와 릴리스 검증에서 실행한 native inbox 계약 | 시험됨; upstream 비공개 스키마는 약속하지 않음 |
| Codex | CI에서 실행한 저장 thread 검색과 `codex queue` 계약 | 시험됨; 문서화되지 않은 DB 변형은 최선 지원 |
| Antigravity | 명시적 bridge protocol | 이후 계약 개정에서 승격하기 전까지 실험적 |

다른 OS나 에이전트 버전에서 한 번 성공한 실행은 근거일 뿐 영구 지원 약속이 아닙니다.
릴리스 노트에는 새로 시험한 버전과 줄어든 범위를 명시해야 합니다.

## 변경과 deprecation 규칙

안정적 표면은 v1 동안 추가 방식으로 변경합니다. 제거, 타입 변경, 의미 재사용 또는 이전에
유효한 공개 입력을 더 엄격히 거부하려면 새 버전 표면이나 다음 major 릴리스가 필요합니다.
안전하지 않은 동작을 유지해야 하는 경우가 아니라면 제거 전 최소 한 minor 릴리스 동안
릴리스 노트에 deprecation을 기록합니다.

영속 형식은 preflight, backup, 이후 검증을 포함한 명시적 마이그레이션을 사용합니다.
실험적 표면은 prerelease에서 바뀔 수 있지만 릴리스 노트에 변경과 대체 수단을 밝혀야
합니다. [#112](https://github.com/abruption/session-peer/issues/112)의 소스 모듈화는 이
fixture와 생성된 standalone CLI 동작을 보존해야 합니다.

## 릴리스 점검표

모든 릴리스는 계약 추가, deprecation과 migration을 밝힙니다. CI는 필수 JSON 필드와 타입,
종료 의미, URI·정책 parsing, backup 불변조건과 relay protocol 버전 marker를 검증합니다.
fixture 통과는 문서화된 추가 필드를 허용하지만 내부 storage를 공개 API로 만들지 않습니다.
