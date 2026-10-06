# Handoff v1 계약 — 설계 제안 v0.2

## 상태와 출처

이 문서는 Python #181과 TypeScript 0.4.0 설계 검토를 위한 미구현 설계입니다. 확정된 프로토콜이나 출시 약속이 아니며, 실제 ACK 지원의 증거도 아닙니다. 이 문서의 병합은 런타임 구현, 게시, 네이티브 제출 또는 운영 변경을 승인하지 않습니다. 픽스처에는 기록된 전달이 아닌 합성 예제가 들어 있습니다.

게시된 Python 참조 버전은 [v1.0.3](https://github.com/abruption/session-peer/tree/0d252550ab40c26d1ac4a19193df6ca2f84d830b)입니다. 일반 출력의 소스는 [adapters](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/adapters.py), [Codex](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/codex.py), [SSH](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/ssh.py), [output](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/output.py)입니다. [공유 픽스처](https://github.com/abruption/session-peer/blob/main/tests/fixtures/handoff-v1.json)는 정규화된 레거시 예제와 제안된 옵트인 예제를 구분합니다. 런타임 참조와 설계 픽스처의 고정 버전은 별개입니다. TypeScript의 게시된 과거 참조를 출시되지 않은 Python 버전으로 암묵적으로 바꾸지 않습니다.

## 증거와 호환성

제출은 네이티브 전송 계층의 수락을 뜻하며, 전달은 정확한 원래 사용자 메시지 ID가 정확한 원래 대상 세대에 주입되었다는 증거를 뜻합니다. 확인 응답은 명시적으로 상관관계가 연결된 수신 확인이며, 완료나 책임 수락 또는 모델이 모든 바이트를 읽었다는 증거가 아닙니다. 큐 삭제, 프로세스 종료, 턴 완료, 답변 없음, 성공한 상태 조회는 ACK가 아닙니다. 알 수 없는 네이티브 턴 상태는 절대로 completed가 되지 않습니다.

일반 send 출력은 런타임별 형식을 유지합니다. Python Claude 성공은 status, submitted, consumptionConfirmed를 생략합니다. Codex의 queued 성공에는 submitted true와 consumptionConfirmed false가 포함됩니다. submitted false인 레거시 unknown은 아무 효과도 없었다는 보편적인 증거가 아닙니다. 빠진 false/null 필드를 추가하거나, 선택적 필드의 부재를 재해석하거나, consumptionConfirmed를 덮어쓰거나, 일반 종료 코드를 바꾸지 마세요. 정규화된 픽스처 값은 식별 정보만 숨깁니다. 각 예제는 출처를 기록하며 완전한 출력 스키마는 아닙니다.

옵트인은 기존 외부 schemaVersion 1 아래에서 각 대상 결과에 handoff 객체 하나를 추가합니다. fanout 수준의 handoff는 없습니다. 명시적인 대기는 외부 ok와 종료 코드만 바꿀 수 있습니다. 네이티브 status, target, queueId, submitted, consumptionConfirmed와 독립적으로 유효한 모든 제출 증거를 보존합니다. 최선 노력 관찰 실패는 네이티브 제출 성공을 바꿀 수 없습니다. 잘못된 handoff 데이터는 유효한 네이티브 증거를 지우거나 ACK로 승격할 수 없습니다. 명시적 대기 요청은 재제출 없이 검증에 실패합니다.

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
| 주입 확인, ACK 기한 만료 | timed_out_unknown | submitted | timed_out_unknown | 네이티브 / 네이티브 또는 부재 | false / 1 |
| 효과 발생 가능, 수신 확인 없음 | unknown | unknown | not_requested | 네이티브 / 네이티브 또는 부재 | false / 1 |
| 유효한 수신 확인으로 명시적 대기 충족 | acknowledged | submitted | satisfied | 네이티브 / 네이티브 또는 부재 | true / 0 |
| 이전 시간 초과의 상태 조회 성공 | timed_out_unknown | submitted | timed_out_unknown | 부재 / 부재 | true / 0 |

잘못된 플래그, 잘못된 시간 초과 표기, 누락된 대상, 잘못된 ID는 사용법/대상 없음 종료 코드 2를 유지하며 JSON/handoff가 전혀 없을 수도 있습니다. 이러한 실패에 합성 상관관계 ID나 레거시 false/null을 만들어 넣지 않습니다. 인터럽트는 취소/재전송 없이 종료 코드 130을 사용합니다. 성공한 상태 조회는 조회 성공을 보고하며 확인 응답을 뜻하지 않습니다.

## 기능과 부트스트랩

모든 기능은 현재 제품 지원이 아닌 향후 수락 관문입니다. 경로는 ACK 지원을 표시하기 전에 수신 확인 소비자, 생산자, 대상 세대를 독립적으로 검증해야 합니다. 부트스트랩 실패는 unsupported이며 일반 메시지 전달을 시도할 권한이 아닙니다.

| 경로 / 관찰자 | 주입 관찰 | 수신 확인 ACK |
| --- | --- | --- |
| 동일 기기의 비공개 수집기와 호환 생산자 | 버전/home/writer/ID 검증 후 Codex만 | 비공개 부트스트랩 후 지원 |
| 설치된 호환 수신 확인 핸들러로 향하는 명시적으로 신뢰된 역방향 SSH | 별도로 검증된 Codex 경로 | 핸들러/설정 검증 후 지원 |
| 호환 핸들러 설치 없이 소스를 스트리밍하는 SSH | 별도로 검증된 Codex 경로 | 지원되지 않음 |
| Claude 네이티브 관찰자 | 기본적으로 지원되지 않음 | 호환되는 명시적 수신 확인 생산자만 |
| 페어링 기기, Relay, Side Session, wake | 초기 경로 범위 밖 | 지원되지 않음 |

필수 delivered 또는 acknowledged 대기는 해당 채널이 지원되지 않으면 효과 발생 전에 거절합니다. 최선 노력의 상관관계 연결 send는 사용되지 않을 비밀 권한을 발급하지 않고 observation/ack unsupported로 제출할 수 있습니다. 수집기는 전달, wake, 모델 프롬프트 또는 승인을 호출하지 않습니다. 네이티브 app-server에서 큐로의 폴백은 원래 네이티브 제출이 시작되었을 가능성이 생기기 전에만 허용됩니다. 시도 후의 불확실성과 관찰자 실패는 절대로 또 다른 제출을 유발하지 않습니다. 버전, 플랫폼, home, 원래 writer 식별 정보 검사는 필수입니다. 트랜스크립트나 임의 답변 본문을 스캔하지 않습니다.

## 수신 확인의 전송 형식과 수명 주기

Receipt v1은 Reply-To v1과 별개이며, Reply-To v1의 파서와 권한은 변경되지 않습니다. 수신 확인 핸들은 비밀이 아닌 로컬 선택자이며 URI나 권한이 아닙니다. 실제 bearer 권한은 승인된 비공개 효과 입력과 비공개 핸들러 stdin을 통해서만 전달되며 argv, URI, 일반 JSON, 환경, 로그 또는 원시 원장 영속 저장에는 절대 나타나지 않습니다.

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

권한은 암호학적으로 무작위인 32바이트를 패딩 없는 base64url 문자 43개로 인코딩한 값입니다. 예제의 자리표시자는 유효한 전송 입력이 아닙니다. 보호된 수집기는 epoch, 상관관계, 원래 세대에 결합된 권한의 SHA-256 해시만 저장합니다. 상수 시간 검증과 원자적인 첫 수신 확인 커밋이 필요합니다. 해당 결합에 대한 중복 수신 확인 ID는 멱등적입니다. 잘못된 ID, 오래된 세대, 충돌하는 수신 확인, 만료된 권한, 잘못된 프레임은 상태를 전진시킬 수 없습니다. ACK 도착 시각은 수집기가 지정하며 호출자 타임스탬프는 권한 있는 근거가 아닙니다.

수집기는 송신자 대화와 독립적인 사용자 소유 프로세스입니다. 파일/디렉터리는 비공개 0600/0700입니다. 엔드포인트는 로컬 소유자 검사를 수행하는 비공개 IPC 또는 명시적으로 설정된 신뢰할 수 있는 역방향 SSH 핸들러입니다. 공개 리스너, 자동 SSH 키 설치, 프로필 변경, 트랜스크립트 읽기, 비밀 내보내기, 범용 CLI exec는 허용되지 않습니다. 재시작은 커밋된 수신 확인 해시와 수신 확인을 복구합니다. 시도된 의도에 대해 잃어버린 원시 권한을 다시 생성하지 않습니다. 권한 수명은 의도 커밋부터 24시간이며 상세 정보 만료, 철회, 격리 또는 첫 유효 수신 확인과 함께 끝납니다. 수락된 수신 확인의 중복은 권한 만료 후에도 저장된 결과를 반환하지만 수신 확인 상세 정보가 존재하는 동안에만 가능합니다.

수동 생산자는 제안된 무제출 handoff confirm 작업입니다. 정확한 epoch/ID/세대와, 관찰된 명시적 상관관계 연결 답변에 대한 로컬 송신자 운영자의 진술이 필요합니다. stdin은 메타데이터만 받으며 트랜스크립트/본문은 받지 않습니다. operator_confirmed를 기록하고 token_possession은 절대 기록하지 않습니다. 기록은 운영자의 증언이며 독립적으로 검증된 모델 식별 정보가 아닙니다. 토큰 소유 생산자는 비공개 입력을 읽는 설치된 호환 수신 확인 전용 핸들러여야 하며 임의 명령을 실행할 수 없습니다. 두 생산자는 모두 구현 수락 관문으로 남아 있습니다. 생산자가 검증되기 전에는 어떠한 assurance도 표시하지 않습니다.

## 송신자 원장, 신규성 및 보존

단일 비공개 직렬화 영속 원장이 무작위 epoch를 소유합니다. 대상에 결합된 준비된 의도는 효과 발생 전에 커밋하고 동기화합니다. 효과 의도 펜스가 커밋되면 온전한 해당 epoch 안에서 네이티브 시도는 단 한 번만 승인됩니다. 해당 커밋 이후 충돌은 실제 효과 시작 전의 충돌도 포함하여 unknown으로 복구되며 절대로 다시 제출하지 않습니다. 결합에는 에이전트, 대상, home/writer 식별 정보, 세대, 보호된 내부 페이로드 다이제스트가 포함됩니다. 다이제스트는 공개 출력이 아닙니다. 충돌이나 대상 재시작은 의도의 결합을 암묵적으로 바꾸지 않습니다.

새 ID는 자동 준비 또는 새로운 무효과 handoff prepare 작업이 생성하고 예약합니다. 호출자가 제공한 알 수 없는 UUID는 신규성을 증명할 수 없으므로 효과 발생 전에 거절합니다. 제공된 알려진 준비 ID는 정확한 결합과 일치하고 시도되지 않은 상태여야 합니다. 제공된 시도 완료 ID는 조회/조정 전용이며 또 다른 send에는 사용할 수 없습니다. 순서가 있는 fanout은 대상마다 의도 하나를 한 번 생성하고 영속적으로 연결합니다. 호출자는 ID 하나를 여러 대상에 재사용할 수 없습니다. 조정은 ID나 권한을 다시 생성하지 않습니다.

epoch당 한도는 보존된 의도/펜스 기록 10,000개와 32 MiB 저널 중 먼저 차는 쪽입니다. 수용 시 제출 후 용량을 채우는 대신 효과 발생 전에 종결 기록과 수신 확인 하나를 위한 제한된 저장 공간을 예약합니다. 펜스 축출/LRU는 허용되지 않습니다. 상세 정보 보존 기간은 준비부터 30일, 권한 수명은 24시간, 의도당 최대 대기는 64회입니다. 만료된 상세 정보는 대상에 결합된 간결한 펜스 tombstone으로 바뀌어 epoch 전체 기간 동안 보존됩니다. tombstone도 할당량에 포함됩니다. 대기 할당량 소진은 네이티브 효과 사실을 바꾸지 않고 새 대기를 거절합니다. 상세 정보 정리는 제출 권한을 복구하지 않습니다. 할당량 소진 시 자동 초기화가 아닌 명시적 운영자 보관 처리 전까지 준비/효과를 거절합니다.

누락, 손상, 상세 정보 만료 또는 알려진 복원 이력은 status/reconcile에서 unknown을 반환하며 재시도는 금지됩니다. 기존 원장은 절대로 자동 재생성하지 않습니다. 첫 사용에는 명시적 로컬 초기화와 새 epoch가 필요합니다. 알려진 복원은 모든 이전 의도를 격리하여 보존된 증거 조정 전까지 효과와 수신 확인 수락을 비활성화합니다. 새 epoch에는 명시적 운영자 초기화와 생성된 새 ID가 필요하며 이전 요청에 대해서는 어떤 주장도 하지 않습니다. 로컬 전용 설계로는 표시되지 않은 롤백이나 기기 간 원장 복제를 신뢰성 있게 감지할 수 없습니다. 펜싱 보장은 온전하고 보존되어 있으며 롤백되지 않았음이 입증된 이력으로 한정됩니다. 외부 단조 앵커/복제 방지 저장소는 v1 범위 밖입니다. 이 제한은 보편적인 exactly-once 주장 뒤에 숨기지 않고 계속 드러나야 합니다.

## 대기 이력과 늦은 수신 확인

각 대기에는 별개의 작업 ID, 목표, 단조 시계 기한, 불변의 종결 결과가 있습니다. status는 해당 의도에 대해 가장 최근에 시작한 대기(직렬화된 순서)를 반환하며 대기가 없으면 not_requested를 반환합니다. 향후 별도의 대기 이력 API를 암시하지 않습니다. 현재 수신 확인/상태는 독립적으로 전진할 수 있습니다. 따라서 늦은 ACK는 현재 상태를 acknowledged로 바꿀 수 있지만 반환되는 원래 대기는 timed_out_unknown으로 남습니다. 그 대기를 satisfied로 다시 쓰지 않습니다.

수신 확인이 원래 send 대기의 관찰 기한 이후에 수락되면 늦은 것으로 판단합니다. send 대기가 없으면 가장 이른 명시적 대기와 비교합니다. 대기가 없으면 late는 false입니다. 이후 대기는 이미 수락된 늦은 수신 확인으로 충족될 수 있으며 ack late 플래그는 true를 유지합니다. 활성 상태에서는 수신 확인 수락과 기한 전이를 같은 단조 시계 기준으로 직렬화합니다. 복구 시 순서를 입증할 수 없는 수신 확인 타이밍에는 합성 late 플래그나 acknowledged 상태를 지정하지 않습니다. 운영자 확인으로 새 증언이 성립할 때까지 분류되지 않은 보류 증거로 유지합니다. UTC 타임스탬프는 진단 전용입니다. 반복 대기는 새 네이티브 제출을 만들지 않습니다.

## 예산과 한계

기본 예산은 대상당 30초입니다. CLI는 선행 0, 부호, 공백, 소수점, 지수 없이 ASCII 십진 정수 1부터 60까지만 허용합니다. 새 플래그는 레거시 파싱을 변경하지 않습니다. 전체 단조 시계 예산은 설정, 사전 검사, 준비, 효과, 관찰보다 먼저 시작합니다. 그 안에서 정리를 위해 정확히 5초를 예약합니다. 예산이 5초 이하이면 insufficient_budget으로 효과 발생 전에 거절합니다. 관찰/효과 마감은 시작 시각에 예산을 더하고 5초를 뺀 값입니다. 정리가 시작 시각에 예산을 더한 한계를 연장할 수 없습니다. 대기 기한 진단은 이 마감을 설명하며 갱신된 원격 예산이 아닙니다.

SSH는 남은 기간만 전달하고 원래 호출자 기한을 유지합니다. 원격 핸들러는 예산을 초기화하거나 UTC로 효과를 승인할 수 없습니다. 남은 전체 예산이 정리 예약 시간 이하이면 효과 발생 전에 거절합니다. 마감 경계에서 now >= cutoff를 만료로 사용합니다. 마감보다 엄격히 앞서 커밋된 수신 확인은 해당 대기를 충족할 수 있으며 마감 시각 또는 이후의 확인은 늦은 확인입니다. 효과 발생 가능성이 생기면 시간 초과는 unknown입니다. 재시도/폴백 또는 새 제출은 허용되지 않습니다. 순서가 있는 fanout은 각 대상에 자체적으로 제한된 예산을 부여하며 한 호스트의 예산을 반복하지 않습니다. 제한된 정리/소유 리소스를 보장할 수 없는 구현은 해당 경로를 지원한다고 표시할 수 없습니다.

```text
safe-integer = JSON integer token, 0..9007199254740991; booleans/fractions/exponents rejected
safe-id = 1..128 UTF-8 bytes, no U+0000..001F or U+007F..009F, valid Unicode scalars
safe-generation = 1..256 UTF-8 bytes, same control/scalar rule
receipt frame = one strict UTF-8 JSON object, at most 4096 bytes
public handoff frame = at most 8192 UTF-8 bytes
duplicate JSON keys, unknown nested keys, NaN/Infinity and trailing data rejected
turn/native IDs are opaque; only correlation/epoch/wait/receipt IDs use UUID-v4 syntax
```

JSON 숫자 토큰은 손실이 있는 파싱 전에 검증해야 합니다. JavaScript Number가 1과 같더라도 어휘 형태 1.0과 1e0은 거절합니다. 안전한 정수와 정확한 불리언 규칙은 새 스키마에만 적용되며 과거 출력에는 적용되지 않습니다. 한계는 잘라낸 후가 아닌 영속 저장 전에 검사합니다. 일반 stdout/로그에는 권한, 메시지 본문, 트랜스크립트 내용, 페이로드 다이제스트가 절대 포함되지 않습니다. 제한된 메타데이터 관찰이 출력 필터링 뒤에 본문 반환 API를 숨겨서는 안 됩니다.

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

재시작한 수집기가 권한 수명의 단조 시계 연속성을 증명할 수 없으면 TTL을 연장하거나 권한을 재생성하지 않고 보수적으로 만료시킵니다. 유효하게 커밋된 수신 확인은 복구할 수 있습니다. 이미 시도한 의도에 대한 새 대기의 예산이 부족하면 해당 대기만 실패하며 제출/주입 사실은 보존합니다. 원래 의도를 refused로 다시 분류하지 않습니다. reconcile 동작은 상태/증거 대조이며 새 제출이나 암묵적 복구 명령이 아닙니다.

## 확정과 구현 관문

이 제안은 확정 전에 정확한 커밋과 픽스처에 대한 TypeScript 검토가 필요합니다. 새 prepare/confirm 표기, ledgerEpoch와 대기 operationId 필드, 5초 정리 예약, 숫자 토큰 검증, 복원 제한은 명시적인 v0.2 개정 사항이며 이미 수락되거나 출시된 기능이 아닙니다.

픽스처는 런타임별 선택적 부재, queued true인 명시적 대기 시간 초과, 잘못된/중복/늦은 ACK, 대기 이력, 재시작, 누락/복원/만료/가득 찬 원장, 사용자 지정 알 수 없는 ID, 기한 경계, 잘못된 스키마, SSH 보존을 다뤄야 합니다. 엄격한 SSH 옵트인 검증은 handoff를 거절하더라도 유효한 네이티브 스냅샷을 보존해야 합니다. 레거시 Claude 재구성이나 일반 실패 경로는 이를 버릴 수 없습니다. 완전한 응답은 같은 엄격한 파서를 통해서만 전송 시간 초과/0이 아닌 종료 코드 이후에도 보존됩니다. 부분 프레임은 unknown으로 남습니다.

구현 수락 전에는 생산자 부트스트랩과 수집기 소유권/재시작, 영속 의도와 용량 예약, 지원되는 각 플랫폼/버전/home에서의 정리, 메타데이터 전용 Codex 관찰, 엄격한 로컬/SSH 튜플, 무제출 status/wait/ack/confirm 작업을 검증해야 합니다. 이 설계 PR은 네이티브/실제 실행 증거를 제공하지 않습니다. Side Session과 wake 실험은 선행 조건이 아닌 별도의 향후 작업입니다. 페어링 기기/Relay 중복 제거와 운영자 모니터링을 암묵적으로 추가하지 않습니다.
