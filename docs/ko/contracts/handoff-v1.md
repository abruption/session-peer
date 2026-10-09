# Handoff v1 계약 — 설계 제안 v0.2

## 상태와 출처

이 문서는 Python #181과 TypeScript 0.4.0 설계 검토를 위한 미구현 설계입니다. 확정된 프로토콜이나 출시 약속이 아니며, 실제 ACK 지원의 증거도 아닙니다. 이 문서의 병합은 런타임 구현, 게시, 네이티브 제출 또는 운영 변경을 승인하지 않습니다. 픽스처에는 기록된 전달이 아닌 합성 예제가 들어 있습니다.

게시된 Python 참조 버전은 [v1.0.3](https://github.com/abruption/session-peer/tree/0d252550ab40c26d1ac4a19193df6ca2f84d830b)입니다. 일반 출력의 소스는 [adapters](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/adapters.py), [Codex](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/codex.py), [SSH](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/ssh.py), [output](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/output.py)입니다. [공유 픽스처](https://github.com/abruption/session-peer/blob/main/tests/fixtures/handoff-v1.json)는 정규화된 레거시 예제와 제안된 옵트인 예제를 구분합니다. 런타임 참조와 설계 픽스처의 고정 버전은 별개입니다. TypeScript의 게시된 과거 참조를 출시되지 않은 Python 버전으로 암묵적으로 바꾸지 않습니다.

## 증거와 호환성

제출은 네이티브 전송 계층의 수락을 뜻하며, 전달은 정확한 원래 사용자 메시지 ID가 정확한 원래 대상 세대에 주입되었다는 증거를 뜻합니다. 확인 응답은 명시적으로 상관관계가 연결된 수신 확인이며, 완료나 책임 수락 또는 모델이 모든 바이트를 읽었다는 증거가 아닙니다. 큐 삭제, 프로세스 종료, 턴 완료, 답변 없음, 성공한 상태 조회는 ACK가 아닙니다. 알 수 없는 네이티브 턴 상태는 절대로 completed가 되지 않습니다.

일반 send 출력은 런타임별 형식을 유지합니다. Python Claude 성공은 status, submitted, consumptionConfirmed를 생략합니다. Codex의 queued 성공에는 submitted true와 consumptionConfirmed false가 포함됩니다. submitted false인 레거시 unknown은 아무 효과도 없었다는 보편적인 증거가 아닙니다. 빠진 false/null 필드를 추가하거나, 선택적 필드의 부재를 재해석하거나, consumptionConfirmed를 덮어쓰거나, 일반 종료 코드를 바꾸지 마세요. 정규화된 픽스처 값은 식별 정보만 숨깁니다. 각 예제는 출처를 기록하며 완전한 출력 스키마는 아닙니다.

옵트인은 기존 외부 schemaVersion 1 아래에서 각 대상 결과에 handoff 객체 하나를 추가합니다. fanout 수준의 handoff는 없습니다. 명시적인 대기는 외부 ok와 종료 코드만 바꿀 수 있습니다. 네이티브 status, target, queueId, submitted, consumptionConfirmed와 독립적으로 유효한 모든 제출 증거를 보존합니다. 결과를 받는 쪽은 검증 모드와 런타임/에이전트 네이티브 프로필을 선택할 때 신뢰할 수 없는 반환 필드가 아니라 자신의 원래 요청 맥락을 사용해야 합니다. 원래 요청이 명시적 대기이고 handoff가 완전히 검증되었으며, 긍정적인 네이티브 프로필과 원래 target/home/context의 일치가 확인된 경우에만 대기 실패 예외를 허용합니다. 시간 초과, 실패, 제출 후 지원 불가는 ok false/종료 코드 1을 사용합니다. 진행 중인 대기의 인터럽트는 ok false/종료 코드 130을 사용합니다. handoff를 받았다는 사실만으로 옵트아웃 요청에서 어느 예외도 허용하지 않습니다. 최선 노력 관찰 실패는 네이티브 제출 성공을 바꿀 수 없습니다. 잘못되거나 크기 한도를 초과한 handoff는 별도로 검증되고 올바른 대상을 가리키는 네이티브 스냅샷을 지우거나 ACK로 승격할 수 없습니다. 명시적 대기는 재제출 없이 검증에 실패합니다. 잘못된 네이티브 target/home 또는 변경된 소비 사실은 독립적으로 유효한 네이티브 증거가 아닙니다. 유효한 일반 옵트아웃 성공은 요청하지 않은 handoff를 무시해도 계속 유효합니다.

긍정적인 네이티브 프로필은 공통 handoff submission 열거형과 별개입니다. 네이티브 성공이 출력하지 않는 외부 status/submitted 필드로 Python Claude의 긍정적인 제출을 추론하지 말고, 가드를 충족하려고 그 필드를 추가하지 마세요. 옵트인 어댑터는 검증된 대기 전 네이티브 성공 스냅샷을 보존해야 합니다. 소비자는 handoff.submission만 신뢰하지 않고 해당 프로필과 정확한 원래 맥락을 검증합니다.

| 원래 런타임 / 에이전트 | 긍정적인 네이티브 스냅샷 | 대상/맥락 일치 |
| --- | --- | --- |
| Python / Claude | status, submitted, consumptionConfirmed 부재; 기존의 긍정적인 소켓 쓰기 target 필드 보존 | 기존 Python 규칙에 따른 원래 해석된 대상 pid/name |
| TypeScript / Claude | status posted, submitted true, consumptionConfirmed false; queueId 부재 | 해석된 pid; 기존 TS 스키마에 따라 agent는 생략되고 name은 null일 수 있음 |
| Python / Codex | status queued, submitted true, consumptionConfirmed false; 네이티브 queueId와 codexHome 보존 | 기존 Python 규칙에 따른 원래 thread와 정규화된 home/context |
| TypeScript / Codex | status queued, submitted true, consumptionConfirmed false; 네이티브 queueId와 codexHome 보존 | UUID 비교는 대소문자를 구분하지 않음; agent는 생략될 수 있으며 정규화된 home/context가 일치해야 함 |

이 표는 합성 긍정 프로필 픽스처를 정의하며 완전한 런타임 봉투나 각 런타임의 기존 검증기를 완화할 권한이 아닙니다. posted status 또는 consumptionConfirmed true인 Codex 스냅샷은 무효입니다. 대상 비교는 원시 사전 전체의 동등 비교가 아니라 프로필을 고려합니다. 허용된 선택적 부재와 null은 계속 허용하되, 잘못된 agent, id/pid 또는 정규화된 home은 실패합니다. 정규화된 home의 일치는 현재 SSH 검증기가 아직 강제하지 않는 런타임에서 추가로 제안된 handoff 관문이며, 출시된 보호를 주장하는 것이 아닙니다. 네이티브 스냅샷 검증은 handoff의 존재나 유효성과 독립적입니다.

## 공개 스키마

다음 문법은 이 제안의 규범입니다. 런타임별 외부 봉투를 제외한 모든 객체는 닫힌 객체입니다. 물음표는 선택 사항이며 이용할 수 없으면 생략됨을 뜻합니다. null 허용 필드는 아래에 명시합니다. 조건부 규칙은 문법 뒤에 나옵니다.

```text
handoff.schemaVersion = 1
handoff.correlationId = UUID-v4 lowercase canonical
handoff.ledgerEpoch = UUID-v4 lowercase canonical
handoff.state = validated | refused | submitted | delivered | acknowledged | unknown | timed_out_unknown
handoff.submission.status = not_attempted | submitted | refused | unknown
handoff.observation.status = not_requested | pending | observed | unsupported | failed
handoff.observation.injectionObserved = boolean
handoff.observation.clientUserMessageId? = safe-id
handoff.observation.turn? = {id: safe-id, status: running | completed | failed | interrupted | unknown}
handoff.ack.status = not_requested | pending | acknowledged | unsupported
handoff.ack.assurance? = token_possession | operator_confirmed
handoff.ack.receivedAtUtcMs? = safe-integer
handoff.ack.late? = boolean
handoff.wait.for = none | delivered | acknowledged
handoff.wait.status = not_requested | pending | satisfied | timed_out_unknown | stopped | unsupported | failed
handoff.wait.operationId? = UUID-v4 lowercase canonical
handoff.wait.deadlineAtUtcMs? = safe-integer
handoff.wait.reason? = insufficient_budget | deadline_before_effect | evidence_unsupported | evidence_failed | history_unavailable | stopped_by_operator | invalid_handoff
handoff.targetGeneration = safe-generation | null
handoff.decisionOwner = sender_operator
handoff.retry = {allowed: false, reason: receiver_dedup_unavailable}
handoff.nextActions = unique subset of [keep_waiting, reconcile, stop_waiting]
```

전달에는 관찰된 주입과 정확한 clientUserMessageId, null이 아닌 원래 targetGeneration이 필요합니다. 턴 증거에는 관찰된 주입이 필요합니다. 턴은 수신 상태와 별개입니다. 수신 확인의 수락은 주입 증거를 만들어 내지 않습니다. acknowledged 상태에는 assurance, 수신 시각, late 플래그를 갖춘 acknowledged ack가 필요합니다. 다른 ACK 상태는 이 필드들을 생략합니다. submitted, delivered, acknowledged 상태에는 submitted submission이 필요합니다. validated에는 not_attempted가, refused에는 refused가, unknown에는 unknown이 필요합니다. 시간 초과 상태에는 submitted 또는 unknown만 허용되며 refused/not_attempted는 허용되지 않습니다.

각 명시적 대기에는 효과 발생 전 거절인 경우에도 operationId와 기한이 있습니다. 대기 없는 기록에는 둘 다 없습니다. satisfied인 delivered 대기에는 주입 증거가, satisfied인 acknowledged 대기에는 유효한 ACK가 필요합니다. stopped/failed/unsupported 대기는 알려진 효과 증거를 보존합니다. nextActions는 검증된 활성 채널과 보존된 이력에 따라 달라집니다. 지원되지 않거나 만료된 채널은 keep_waiting을 제공하지 않습니다. stop_waiting은 관찰만 끝내며 네이티브 작업을 취소하지 않습니다. 모든 네이티브 로컬/SSH 결과는 재시도를 금지합니다. v1에는 resend_same_id 동작이 없습니다. 상관관계와 사용자 승인만으로 안전한 재전송이 성립하지 않습니다. 수신자 중복 제거(#182)는 이 재전송 금지 계약 구현의 선행 조건이 아닙니다.

## 상태와 종료 코드 튜플

부재는 레거시 필드가 계속 생략됨을 뜻합니다. 네이티브는 변경되지 않은 런타임별 스냅샷을 뜻합니다. 같은 표가 로컬과 SSH에 적용되며 미구현 페어링 기기 전송에는 적용되지 않습니다.

| 모드 / 증거 | state | submission | wait status | 외부 status / submitted | ok / 종료 코드 |
| --- | --- | --- | --- | --- | --- |
| 일반 send | 부재 | 부재 | 부재 | 네이티브 / 네이티브 또는 부재 | 네이티브 |
| 옵트인 dry-run | validated | not_attempted | not_requested | 네이티브 / 네이티브 또는 부재 | true / 0 |
| 효과 발생 전 필수 채널 이용 불가 | refused | refused | unsupported | 있으면 네이티브 / 합성 필드 없음 | false / 1 |
| 확실히 효과 발생 전에 예산 소진 | refused | refused | failed | 있으면 네이티브 / 합성 필드 없음 | false / 1 |
| 큐 등록 확인, 최선 노력 관찰자 실패 | submitted | submitted | not_requested | queued / true | true / 0 |
| 큐 등록 확인, 명시적 ACK 기한 만료 | timed_out_unknown | submitted | timed_out_unknown | queued / true | false / 1 |
| 긍정적인 네이티브 프로필, 제출 후 채널 지원 불가 | submitted 또는 delivered | submitted | unsupported | 네이티브 / 네이티브 또는 부재 | false / 1 |
| 운영자가 진행 중인 명시적 대기를 중단 | submitted, delivered 또는 unknown | submitted 또는 unknown | stopped | 네이티브 / 네이티브 또는 부재 | false / 130 |
| 주입 확인, ACK 기한 만료 | timed_out_unknown | submitted | timed_out_unknown | 네이티브 / 네이티브 또는 부재 | false / 1 |
| 효과 발생 가능, 수신 확인 없음 | unknown | unknown | not_requested | 네이티브 / 네이티브 또는 부재 | false / 1 |
| 유효한 수신 확인으로 명시적 대기 충족 | acknowledged | submitted | satisfied | 네이티브 / 네이티브 또는 부재 | true / 0 |
| 이전 시간 초과의 상태 조회 성공 | timed_out_unknown | submitted | timed_out_unknown | 부재 / 부재 | true / 0 |
| 중단된 대기의 상태 조회 성공 | 보존된 상태 | 보존된 제출 | stopped | 부재 / 부재 | true / 0 |

잘못된 플래그, 잘못된 시간 초과 표기, 누락된 대상, 잘못된 ID는 사용법/대상 없음 종료 코드 2를 유지하며 JSON/handoff가 전혀 없을 수도 있습니다. 이러한 실패에 합성 상관관계 ID나 레거시 false/null을 만들어 넣지 않습니다. SIGINT를 포함하여 진행 중인 명시적 send/wait 작업을 중단하면 취소/재전송 없이 wait stopped와 reason stopped_by_operator를 종결 기록합니다. 완전한 구조화 출력이 있으면 해당 작업은 알려진 네이티브/제출/주입 사실을 보존하면서 ok false/종료 코드 130을 반환합니다. SSH는 원래의 명시적 대기 요청이고 target/home/결합이 일치하는 검증된 stopped 대기인 경우에만 이 예외를 수락합니다. 운영자가 의도적으로 진행 중인 대기를 멈추는 경우도 새 API 표기 없이 같은 규칙을 따릅니다. 이미 종결된 대기는 불변입니다. 인터럽트는 커밋된 시간 초과, 충족 또는 다른 종결 결과를 stopped로 다시 쓸 수 없습니다. 그 중단 기록의 성공한 상태 조회는 ok true/종료 코드 0을 사용합니다. 부분 출력이나 출력 없는 인터럽트는 독립적으로 알려진 증거를 보존하고 나머지는 불확실성으로 유지하며, 합성 false 필드, 폴백 또는 재전송을 만들지 않습니다. 성공한 상태 조회는 조회 성공을 보고하며 확인 응답을 뜻하지 않습니다.

## 기능과 부트스트랩

모든 기능은 현재 제품 지원이 아닌 향후 수락 관문입니다. 경로는 ACK 지원을 표시하기 전에 수신 확인 소비자, 생산자, 불변의 원래 대상 세대를 독립적으로 검증해야 합니다. null 세대는 수신 확인 권한을 발급하거나 필수 delivered/acknowledged 대기를 지원할 수 없습니다. 해당 요구는 효과 발생 전에 wait unsupported로 거절합니다. 부트스트랩 실패는 unsupported이며 일반 메시지 전달을 시도할 권한이 아닙니다. 새로 발견한 현재 세대는 원래 결합을 대신하지 않습니다. 대상 재시작은 새 제출/재결합을 막지만, 원래 세대에 결합된 지연 수신 확인을 그 자체로 무효화하지 않습니다. 검증된 원래 튜플과 원래 권한은 위임된 토큰 소유를 증명할 뿐 원래 에이전트/모델 신원을 증명하지 않습니다. 후속 에이전트의 새 세대 값은 거절합니다. 복사된 원래 튜플과 원래 권한을 모두 가진 후속 에이전트나 동일 사용자 독자는 token_possession 보증 아래에서 구별할 수 없습니다. 이 방식이 모델 신원을 인증하여 그러한 재생을 배제한다고 주장하지 마세요.

| 경로 / 관찰자 | 주입 관찰 | 수신 확인 ACK |
| --- | --- | --- |
| 동일 기기의 비공개 수집기와 호환 생산자 | 버전/home/writer/ID 검증 후 Codex만 | 비공개 부트스트랩 후 지원 |
| 설치된 호환 수신 확인 핸들러로 향하는 명시적으로 신뢰된 역방향 SSH | 별도로 검증된 Codex 경로 | 핸들러/설정 검증 후 지원 |
| 호환 핸들러 설치 없이 소스를 스트리밍하는 SSH | 별도로 검증된 Codex 경로 | 지원되지 않음 |
| Claude 네이티브 관찰자 | 기본적으로 지원되지 않음 | 호환되는 명시적 수신 확인 생산자만 |
| 페어링 기기, Relay, Side Session, wake | 초기 경로 범위 밖 | 지원되지 않음 |

필수 delivered 또는 acknowledged 대기는 해당 채널이 지원되지 않으면 효과 발생 전에 거절합니다. 최선 노력의 상관관계 연결 send는 사용되지 않을 비밀 권한을 발급하지 않고 observation/ack unsupported로 제출할 수 있습니다. 수집기는 전달, wake, 모델 프롬프트 또는 승인을 호출하지 않습니다. 네이티브 app-server에서 큐로의 폴백은 원래 네이티브 제출이 시작되었을 가능성이 생기기 전에만 허용됩니다. 시도 후의 불확실성과 관찰자 실패는 절대로 또 다른 제출을 유발하지 않습니다. 버전, 플랫폼, home, 원래 writer 식별 정보 검사는 필수입니다. 트랜스크립트나 임의 답변 본문을 스캔하지 않습니다.

## 수신 확인의 전송 형식과 수명 주기

Receipt v1은 Reply-To v1과 별개이며, Reply-To v1의 파서와 권한은 변경되지 않습니다. 수신 확인 핸들은 비밀이 아닌 로컬 선택자이며 URI나 권한이 아닙니다. 실제 bearer 권한은 승인된 비공개 효과 입력과 비공개 핸들러 stdin을 통해서만 전달됩니다. 비밀 비노출 보장은 송신자/수집기의 argv, URI, 환경, 일반 JSON, 진단, 오류/ACK 결과와 자체 원시 저널/영속 저장에 적용됩니다. 의도된 수신자의 네이티브 큐, 이력 또는 트랜스크립트에는 적용되지 않습니다. 네이티브 효과 입력은 CLI 통제 밖에서 그곳에 보존될 수 있으며 동일 사용자 독자는 위임된 수신 확인 전용 권한을 얻을 수 있습니다. token_possession은 독립적인 에이전트 인증이 아닙니다. 우리 관찰자는 여전히 트랜스크립트를 읽지 않습니다. 철회, 24시간 TTL, 원자적인 첫 수신 확인 수락은 새 수신 확인 권한을 제한하며 수신자의 저장 수명을 제한하지 않습니다.

```json
{
  "schemaVersion": 1,
  "kind": "receipt",
  "ledgerEpoch": "11111111-1111-4111-8111-111111111111",
  "correlationId": "22222222-2222-4222-8222-222222222222",
  "targetGeneration": "fixture-generation",
  "receiptId": "33333333-3333-4333-8333-333333333333",
  "capability": "<PRIVATE_INPUT_ONLY>"
}
```

권한은 암호학적으로 무작위인 32바이트를 패딩 없는 base64url 문자 43개로 인코딩한 값입니다. 예제의 자리표시자는 유효한 전송 입력이 아닙니다. 보호된 수집기는 epoch, 상관관계, 원래 세대에 결합된 권한의 SHA-256 해시만 저장합니다. 읽기 전용 중복을 포함한 모든 핸들러 요청에서 상수 시간 검증이 필요합니다. 원자적이고 영속적인 첫 수신 확인 커밋에는 수신 확인 ID/결합, 입증된 분류, assurance, late 플래그, 수집기 수신 시각 및 이를 뒷받침하는 대기 순서/기한 사실이 포함됩니다. 상태와 관련 대기 전이는 이후의 별도 쓰기가 아니라 이 기록과 일관되게 커밋합니다. 잘못된 ID, 잘못된 토큰, 후속 세대, 충돌하는 수신 확인, 만료된 미커밋 권한, 잘못된 프레임은 상태를 전진시킬 수 없습니다. ACK 도착 시각은 수집기가 지정하며 호출자 타임스탬프는 권한 있는 근거가 아닙니다.

수집기는 송신자 대화와 독립적인 사용자 소유 프로세스입니다. 파일/디렉터리는 비공개 0600/0700입니다. 엔드포인트는 로컬 소유자 검사를 수행하는 비공개 IPC 또는 명시적으로 설정된 신뢰할 수 있는 역방향 SSH 핸들러입니다. 공개 리스너, 자동 SSH 키 설치, 프로필 변경, 트랜스크립트 읽기, 비밀 내보내기, 범용 CLI exec는 허용되지 않습니다. 재시작은 커밋된 수신 확인 해시와 분류된 수신 확인을 복구합니다. 시도된 의도에 대해 잃어버린 원시 권한을 다시 생성하지 않습니다. 권한 수명은 의도 커밋부터 24시간이며 상세 정보 만료, 철회, 격리 또는 첫 유효 수신 확인과 함께 끝납니다. 유일한 만료 예외는 이미 커밋된 동일한 수신 확인의 읽기 전용 조회입니다. 원래 epoch, 상관관계, 세대, receiptId와 원래 권한 해시에 대한 상수 시간 증명을 모두 요구합니다. TTL 만료/첫 수신 확인으로 인한 권한 소모는 새 수신 확인의 수락이나 상태 생성/승격을 허용하지 않습니다. 철회, 격리, 상세 정보 누락/만료 또는 잘못된 토큰은 이 예외도 거절합니다. 식별자만으로 일반 상태/조회 권한이 생기지 않습니다. 승인된 송신자 운영자의 상태 조회는 별도의 소유자 검사를 수행하는 로컬 인터페이스를 사용합니다.

수동 생산자는 제안된 무제출 handoff confirm 작업입니다. 정확한 epoch/ID/원래 세대와, 관찰된 명시적 상관관계 연결 답변에 대한 로컬 송신자 운영자의 진술이 필요합니다. stdin은 메타데이터만 받으며 트랜스크립트/본문은 받지 않습니다. operator_confirmed를 기록하고 token_possession은 절대 기록하지 않습니다. 확인은 새 현재 증언/이벤트이며 과거 수신 확인의 도착 시각에 대한 소급 증거가 아닙니다. 영속적인 종결 대기 사실 등으로 원래 대기의 순서/늦음 분류를 입증할 수 있을 때만 acknowledged가 될 수 있습니다. 그렇지 않으면 ok false, 종료 코드 1, 고정 reason receipt_order_unprovable로 확인을 거절합니다. 원래 pending/unknown ACK와 원래 대기를 보존하고, 수락된 ACK를 커밋하거나 late 불리언을 만들어 넣지 않습니다. 이미 커밋된 유효한 수신 확인은 이 확인 실패로 하향 조정하거나 교체하지 않습니다. 토큰 소유 생산자는 비공개 입력을 읽는 설치된 호환 수신 확인 전용 핸들러여야 하며 임의 명령을 실행할 수 없습니다. 두 생산자는 모두 구현 수락 관문으로 남아 있습니다. 생산자가 검증되기 전에는 어떠한 assurance도 표시하지 않습니다.

## 송신자 원장, 신규성 및 보존

단일 비공개 직렬화 영속 원장이 무작위 epoch를 소유합니다. 대상에 결합된 준비된 의도는 효과 발생 전에 커밋하고 동기화합니다. 효과 의도 펜스가 커밋되면 온전한 해당 epoch 안에서 네이티브 시도는 단 한 번만 승인됩니다. 해당 커밋 이후 충돌은 실제 효과 시작 전의 충돌도 포함하여 unknown으로 복구되며 절대로 다시 제출하지 않습니다. 결합에는 에이전트, 대상, home/writer 식별 정보, 세대, 보호된 내부 페이로드 다이제스트가 포함됩니다. 다이제스트는 공개 출력이 아닙니다. 충돌이나 대상 재시작은 의도의 결합을 암묵적으로 바꾸지 않습니다.

새 ID는 자동 준비 또는 새로운 무효과 handoff prepare 작업이 생성하고 예약합니다. 호출자가 제공한 알 수 없는 UUID는 신규성을 증명할 수 없으므로 효과 발생 전에 거절합니다. 제공된 알려진 준비 ID는 정확한 결합과 일치하고 시도되지 않은 상태여야 합니다. 제공된 시도 완료 ID는 조회/조정 전용이며 또 다른 send에는 사용할 수 없습니다. 순서가 있는 fanout은 대상마다 의도 하나를 한 번 생성하고 영속적으로 연결합니다. 호출자는 ID 하나를 여러 대상에 재사용할 수 없습니다. 조정은 ID나 권한을 다시 생성하지 않습니다.

epoch당 한도는 보존된 의도/펜스 기록 10,000개와 32 MiB 저널 중 먼저 차는 쪽입니다. 수용 시 제출 후 용량을 채우는 대신 효과 발생 전에 종결 기록과 수신 확인 하나를 위한 제한된 저장 공간을 예약합니다. 펜스 축출/LRU는 허용되지 않습니다. 상세 정보 보존 기간은 준비부터 30일, 권한 수명은 24시간, 의도당 최대 대기는 64회입니다. 만료된 상세 정보는 대상에 결합된 간결한 펜스 tombstone으로 바뀌어 epoch 전체 기간 동안 보존됩니다. tombstone도 할당량에 포함됩니다. 대기 할당량 소진은 네이티브 효과 사실을 바꾸지 않고 새 대기를 거절합니다. 상세 정보 정리는 제출 권한을 복구하지 않습니다. 할당량 소진 시 자동 초기화가 아닌 명시적 운영자 보관 처리 전까지 준비/효과를 거절합니다.

누락, 손상, 상세 정보 만료 또는 알려진 복원 이력은 status/reconcile에서 unknown을 반환하며 재시도는 금지됩니다. 알려진 tombstone은 원래 epoch와 대상 결합을 보존합니다. state/submission unknown이고 ACK/주입 주장과 keep_waiting이 없는 일반 handoff를 반환할 수 있습니다. 원장 누락/손상 또는 알 수 없는 ID는 그 맥락을 복구할 수 없으므로 handoff나 만들어 낸 epoch 없이 아래의 별도 조회 오류 봉투를 반드시 반환해야 합니다. 기존 원장은 절대로 자동 재생성하지 않습니다. 첫 사용에는 명시적 로컬 초기화와 새 epoch가 필요합니다. 알려진 복원은 모든 이전 의도를 격리하여 보존된 증거 조정 전까지 효과와 수신 확인 수락을 비활성화합니다. 새 epoch에는 명시적 운영자 초기화와 생성된 새 ID가 필요하며 이전 요청에 대해서는 어떤 주장도 하지 않습니다. 로컬 전용 설계로는 표시되지 않은 롤백이나 기기 간 원장 복제를 신뢰성 있게 감지할 수 없습니다. 펜싱 보장은 온전하고 보존되어 있으며 롤백되지 않았음이 입증된 이력으로 한정됩니다. 외부 단조 앵커/복제 방지 저장소는 v1 범위 밖입니다. 이 제한은 보편적인 exactly-once 주장 뒤에 숨기지 않고 계속 드러나야 합니다.

제안된 조회 오류는 종료 코드 1을 사용합니다. handoffQuery는 표시된 필드만 갖는 닫힌 스키마이며 context는 ledger_missing, ledger_corrupt 또는 id_unknown입니다. 호출자가 제공한 문법적으로 유효한 correlationId는 그대로 반환하지만 이력의 증거로 취급하지 않습니다. ledgerEpoch, handoff, 최상위 status/submitted/consumptionConfirmed 또는 합성 네이티브 스냅샷을 추가하지 않습니다. 외부 host/command는 조회 대상과 handoff이며 reason은 handoff_history_unavailable입니다. 이는 옵트인 조회 결과이며 일반 레거시 오류를 변경하지 않습니다.

```json
{
  "schemaVersion": 1,
  "ok": false,
  "host": "fixture",
  "command": "handoff",
  "reason": "handoff_history_unavailable",
  "handoffQuery": {
    "schemaVersion": 1,
    "correlationId": "22222222-2222-4222-8222-222222222222",
    "status": "unknown",
    "context": "ledger_missing",
    "retry": {"allowed": false, "reason": "history_unavailable"}
  }
}
```

## 대기 이력과 늦은 수신 확인

각 대기에는 별개의 작업 ID, 목표, 단조 시계 기한, 불변의 종결 결과가 있습니다. status는 해당 의도에 대해 가장 최근에 시작한 대기(직렬화된 순서)를 반환하며 대기가 없으면 not_requested를 반환합니다. 향후 별도의 대기 이력 API를 암시하지 않습니다. 현재 수신 확인/상태는 독립적으로 전진할 수 있습니다. 따라서 늦은 ACK는 현재 상태를 acknowledged로 바꿀 수 있지만 반환되는 원래 대기는 timed_out_unknown으로 남습니다. 그 대기를 satisfied로 다시 쓰지 않습니다.

수신 확인이 원래 send 대기의 관찰 기한 시각 또는 이후에 수락되면 늦은 것으로 판단합니다. send 대기가 없으면 가장 이른 명시적 대기와 비교합니다. 대기가 없으면 late는 false입니다. 이후 대기는 이미 수락된 늦은 수신 확인으로 충족될 수 있으며 ack late 플래그는 true를 유지합니다. 활성 상태에서는 수신 확인 수락과 기한 전이를 같은 단조 시계 기준으로 직렬화하며, 입증된 순서/분류를 원자적으로 영속 커밋합니다. 완전히 커밋된 유효 ACK는 원래 분류, assurance, late 및 불변의 대기 사실을 복구합니다. 재시작한 시계가 달라졌다는 이유만으로 절대로 하향 조정하지 않습니다. 커밋 전 비정상 종료나 그 밖의 미커밋/미분류 타이밍 증거는 acknowledged가 되거나 합성 late 플래그를 제공할 수 없습니다. 필수 대기를 미충족으로, 기존 pending/unknown ACK를 그대로 유지한 채 미분류 증거로 보존합니다. 수동 확인은 위의 입증 또는 거절 규칙을 따르는 새 이벤트이며 소급하여 다시 쓰지 않습니다. UTC 타임스탬프는 진단 전용입니다. 반복 대기는 새 네이티브 제출을 만들지 않습니다.

## 예산과 한계

기본 예산은 대상당 30초입니다. CLI는 선행 0, 부호, 공백, 소수점, 지수 없이 ASCII 십진 정수 1부터 60까지만 허용합니다. 새 플래그는 레거시 파싱을 변경하지 않습니다. 전체 단조 시계 예산은 설정, 사전 검사, 준비, 효과, 관찰보다 먼저 시작합니다. 그 안에서 정리를 위해 정확히 5초를 예약합니다. 예산이 5초 이하이면 insufficient_budget으로 효과 발생 전에 거절합니다. 관찰/효과 마감은 시작 시각에 예산을 더하고 5초를 뺀 값입니다. 정리가 시작 시각에 예산을 더한 한계를 연장할 수 없습니다. 대기 기한 진단은 이 마감을 설명하며 갱신된 원격 예산이 아닙니다.

SSH는 남은 기간만 전달하고 원래 호출자 기한을 유지합니다. 원격 핸들러는 예산을 초기화하거나 UTC로 효과를 승인할 수 없습니다. 남은 전체 예산이 정리 예약 시간 이하이면 효과 발생 전에 거절합니다. 마감 경계에서 now >= cutoff를 만료로 사용합니다. 마감보다 엄격히 앞서 커밋된 수신 확인은 해당 대기를 충족할 수 있으며 마감 시각 또는 이후의 확인은 늦은 확인입니다. 효과 발생 가능성이 생기면 시간 초과는 unknown입니다. 재시도/폴백 또는 새 제출은 허용되지 않습니다. 순서가 있는 fanout은 각 대상에 자체적으로 제한된 예산을 부여하며 한 호스트의 예산을 반복하지 않습니다. 제한된 정리/소유 리소스를 보장할 수 없는 구현은 해당 경로를 지원한다고 표시할 수 없습니다.

```text
safe-integer = JSON integer token, 0..9007199254740991; booleans/fractions/exponents rejected
safe-id = 1..128 UTF-8 bytes, no U+0000..001F or U+007F..009F, valid Unicode scalars
safe-generation = 1..256 UTF-8 bytes, same control/scalar rule
receipt/confirmation frame = raw strict UTF-8 JSON input, at most 4096 bytes including LF/whitespace
public handoff size = compact UTF-8 encoding of the handoff subtree, at most 8192 bytes
opt-in destination stdout frame = at most 1048576 bytes including LF/whitespace
opt-in fanout = at most 32 destinations and 34603008 total stdout bytes including LF/whitespace
duplicate JSON keys, unknown nested keys, NaN/Infinity and trailing data rejected
turn/native IDs are opaque; only correlation/epoch/wait/receipt IDs use UUID-v4 syntax
```

JSON 숫자 토큰은 손실이 있는 파싱 전에 검증해야 합니다. JavaScript Number가 1과 같더라도 어휘 형태 1.0과 1e0은 거절합니다. 어휘 제한은 handoff/handoffQuery 하위 트리와 비공개 수신 확인/확인 스키마에만 적용하며 관계없는 레거시 외부 필드에는 적용하지 않습니다. 기존 레거시 파싱 및 중복 키/비유한 수 규칙을 유지합니다. handoff 요청이 있다는 이유만으로 레거시 필드가 무효가 되지 않습니다. handoff 하위 트리 크기는 정규 간결 인코딩으로 계산합니다(선택적 공백 없음, ASCII 이스케이프가 아닌 UTF-8 스칼라 문자, 쉼표/콜론 구분자). 이를 감싼 전송 형식의 하위 트리 공백은 대신 외부 프레임 한도에 포함됩니다. 비공개 수신 확인/확인의 원시 입력은 선택적 후행 JSON 공백과 LF를 포함한 모든 바이트를 포함합니다. 뒤따르는 공백 아닌 데이터는 거절합니다. 개행을 위한 추가 허용량은 없습니다. 대상/집계 한도는 새 옵트인 모드에만 적용합니다. 효과 발생 전에 과도한 대상 수를 거절하고 일반 옵트아웃 전송/출력 한도는 바꾸지 않습니다. 할당 전에 stdout을 점진적으로 제한합니다. 제한된 집계 형식은 간결한 JSON과 선택적 LF입니다. 제한된 완전한 외부 프레임 안의 선택적 하위 트리가 잘못되거나 크기 한도를 초과하면 독립적으로 검증된 네이티브 증거를 보존하고 ACK/명시적 대기를 거절하며 절대로 재제출하지 않습니다. 외부 프레임 한도를 초과하면 부분 파싱으로 성공을 만들지 않습니다. 이미 독립적으로 검증된 증거만 보존하고 그렇지 않으면 unknown을 반환합니다. 한계는 잘라낸 후가 아닌 영속 저장 전에 검사합니다. 송신자/수집기의 일반 stdout, 진단, 오류/ACK 결과와 자체 저널에는 권한이나 페이로드 다이제스트가 절대로 포함되지 않습니다. 수신자의 트랜스크립트/본문은 읽지 않습니다. 제한된 메타데이터 관찰이 출력 필터링 뒤에 본문 반환 API를 숨겨서는 안 됩니다.

## 제안된 CLI와 무제출 작업

이 표기는 제안일 뿐 게시된 Python에서 사용할 수 있는 명령이 아닙니다. 준비는 제출 없이 send와 같은 대상/메시지 입력에 결합하며 확인은 메타데이터만 담은 비공개 stdin을 받습니다. 명시적 로컬 원장 초기화는 별도의 옵트인 설정 선행 조건이며 자동 복구 동작이 아닙니다.

```text
handoff init
handoff prepare --to TARGET --message-file PRIVATE_FILE
send --to TARGET --message-file PRIVATE_FILE --correlation-id PREPARED_UUID
send --to TARGET --request-ack
send --to TARGET --observe-delivery
send --to TARGET --wait-for delivered|acknowledged --wait-timeout SECONDS
handoff status --correlation-id UUID
handoff wait --correlation-id UUID --wait-for delivered|acknowledged --wait-timeout SECONDS
handoff confirm --receipt -
ack --receipt -
```

correlation-id가 없으면 request-ack/observe-delivery/wait-for는 자동으로 새 의도를 예약합니다. 그 외의 일반 send는 변경되지 않습니다. 상관관계만 있는 send는 최선 노력 증거를 사용하고 명시적 대기를 하지 않습니다. status, wait, confirm, ack, init, prepare는 네이티브 제출을 전혀 하지 않습니다. 수신 확인 선택자에는 비밀이 포함되지 않습니다. 확인 stdin에는 schemaVersion, ledgerEpoch, correlationId, targetGeneration과 호출자의 confirmed=true 진술이 들어갑니다. 추가 필드/본문/권한은 거절하고 operator_confirmed만 기록합니다. 플래그 비호환성과 지원되지 않는 경로 요구 사항은 영속 효과 의도 전에 검사합니다. 원격 설정과 호스트 옵션은 임의 수신 확인 라우팅이 아닌 기존 SSH 신뢰 제한을 따라야 합니다.

ACK 증거에도 null이 아닌 원래 targetGeneration과 submitted submission이 필요하며, 유효한 수신 확인을 수락하면 현재 상태는 acknowledged입니다. 관찰된 주입은 항상 submitted submission을 뜻합니다. 제공된 준비 ID는 효과 발생 전 종결 거절을 포함한 이전 실제 send 호출에 속하지 않아야 합니다. dry-run은 첫 제출 권한을 소모하지 않습니다. dry-run은 request-ack, observe-delivery, wait-for와 함께 사용할 수 없으며 사용법 종료 코드 2를 반환합니다. correlation-only dry-run은 이미 준비된 ID를 사용합니다.

재시작한 수집기가 권한 수명의 단조 시계 연속성을 증명할 수 없으면 TTL을 연장하거나 권한을 재생성하지 않고 사용되지 않은 새 수신 확인 권한을 보수적으로 만료시킵니다. 유효하게 커밋된 수신 확인의 분류/assurance/late는 계속 복구할 수 있습니다. 인증된 동일 수신 확인의 읽기 전용 중복은 명시된 만료 예외를 따릅니다. 이미 시도한 의도에 대한 새 대기의 예산이 부족하면 해당 대기만 실패하며 제출/주입 사실은 보존합니다. 원래 의도를 refused로 다시 분류하지 않습니다. reconcile 동작은 상태/증거 대조이며 새 제출이나 암묵적 복구 명령이 아닙니다.

## 확정과 구현 관문

이 제안은 확정 전에 정확한 커밋과 픽스처에 대한 TypeScript 검토가 필요합니다. 새 prepare/confirm 표기, ledgerEpoch와 대기 operationId 필드, 5초 정리 예약, 숫자 토큰 검증, 복원 제한은 명시적인 v0.2 개정 사항이며 이미 수락되거나 출시된 기능이 아닙니다.

픽스처는 런타임별 선택적 부재, 요청 맥락으로 허용되는 queued true 명시적 대기 시간 초과, 위조된 옵트아웃 handoff, 잘못된 네이티브 대상, 인증된/잘못된 토큰/만료된 중복, 커밋된/커밋 전/순서 불명 수신 확인 복구, 수동 확인 거절, 원래/새/null 세대, 비밀 반사 없음, 맥락 누락 조회 오류와 알려진 tombstone의 구분, 대기 이력, 누락/복원/만료/가득 찬 원장, 사용자 지정 알 수 없는 ID, 기한/프레임 경계, 잘못된 스키마, SSH 보존을 다뤄야 합니다. 엄격한 SSH 옵트인 검증은 handoff를 거절하더라도 유효한 네이티브 스냅샷을 보존해야 합니다. 레거시 Claude 재구성이나 일반 실패 경로는 이를 버릴 수 없습니다. 완전한 응답은 원래 요청을 인식하는 동일한 엄격한 파서를 통해서만 전송 시간 초과/0이 아닌 종료 코드 이후에도 보존됩니다. 부분 프레임은 unknown으로 남습니다.

구현 수락 전에는 생산자 부트스트랩과 수집기 소유권/재시작, 영속 의도와 용량 예약, 지원되는 각 플랫폼/버전/home에서의 정리, 메타데이터 전용 Codex 관찰, 엄격한 로컬/SSH 튜플, 무제출 status/wait/ack/confirm 작업을 검증해야 합니다. 이 설계 PR은 네이티브/실제 실행 증거를 제공하지 않습니다. Side Session과 wake 실험은 선행 조건이 아닌 별도의 향후 작업입니다. 페어링 기기/Relay 중복 제거와 운영자 모니터링을 암묵적으로 추가하지 않습니다.
