# 프라이빗 릴레이 제어 및 인증 (RC 후보)

상태: #69에 대한 구현 후보이며, 배포된 프로덕션 서비스가 아닙니다.
아래의 control-to-relay 계약은 Python 소유자의 최종
인터페이스 지침을 반영하고 있으며, 실제 서비스 간 통합은 별도의 관문으로 남아 있습니다. 이 프로젝트는 일반적인 Python 설치 환경에 리스너,
OAuth 계정 또는 Node 의존성을 추가하지 않습니다.

## 신뢰 경계

`control/`는 독립적인 Node 22/24 React/Vite + BetterAuth **1.7.5** 서비스입니다.
GitHub와 Google만이 구성된 유일한 로그인 제공자입니다. 제공자 자격 증명이
누락되어도 가짜 로그인이 노출되지 않습니다. 비밀번호 로그인/가입은 비활성화되어 있습니다. 이메일 주소가 아닌
OAuth 계정 ID가 권한 부여 신원입니다. 모든 제어
API 호출은 네이티브 BetterAuth 세션, 명시적 허용 목록 또는 커밋된
공개 가입 기록, 그리고 내부 사용자 ID 소유권을 다시 검사합니다. 가입을 일시 중지해도
이미 커밋된 공개 신원이 제거되지는 않습니다.
이메일 기반의 자동 계정 연동은 허용되지 않습니다. 동일한 이메일을 사용하는 다른 제공자를 활성화하더라도
기존 사용자의 기기가 암묵적으로 부여되지 않습니다.

허용 목록 전용 운영은 페일클로즈 기본값으로 유지됩니다. 운영자는 검증된 무제한
공개 가입을 명시적으로 활성화할 수 있습니다. 검증된 제공자 콜백은
BetterAuth가 사용자를 생성하기 전에 신원을 예약합니다. 운영자가 나중에 새로운 가입을
닫더라도 커밋된 신원은 계속 사용할 수 있습니다. 계정 및 세션 생성
역시 BetterAuth DB 훅에 의해 검사됩니다. 거부된 콜백은 영구적인
공개 슬롯을 차지하거나 제어 접근 권한을 부여할 수 없습니다.

웹 `/login`, `/device`, `/devices`는 프로덕션 환경에서 HTTP-only 보안 쿠키를 사용합니다.
기기 페이지에는 코드, 클라이언트 및 스코프가 표시되며, 코드 일치
확인과 명시적인 승인/거부가 요구되고, 예기치 않은 요청에 대한 경고가 표시됩니다.
추가 제어 클레임 테이블은 검증된 코드를 단순한 사용자가 아닌 **정확한 브라우저
세션**에 바인딩합니다. BetterAuth 자체의 자사 클레임은 사용자 바인딩 방식이지만,
이 래퍼는 더 좁은 세션 제한을 제공합니다.

CLI 로그인은 BetterAuth `deviceAuthorization()` 및 `bearer()`를 사용합니다:

- `POST /api/auth/device/code`, `client_id=session-peer-cli`.
- 제공된 검증 URI를 열고, 인증한 후 코드를 확인/승인합니다.
- 안내된 간격(5초)으로 `POST /api/auth/device/token`을 폴링합니다.
  그랜트는 `urn:ietf:params:oauth:grant-type:device_code`입니다.
- `access_token`은 OAuth 제공자 액세스 토큰, OAuth 보호 리소스 토큰 또는 릴레이 JWT가 아닌 **자사 BetterAuth 세션 토큰**입니다.
- 이를 구성된 제어 오리진에만 `Authorization: Bearer …`로 전송하십시오.
  토큰은 BetterAuth 세션(24시간)과 함께 만료되며, 리프레시 토큰이나
  영구적인 백그라운드 로그인 보장은 여기에 추가되지 않습니다. OS 자격 증명 저장소 및
  CLI UX는 Python/클라이언트 소유자의 통합 책임입니다.
- 브라우저 쿠키 세션만이 확인/승인/거부를 수행할 수 있으며, bearer 승인은
  거부됩니다. 기기 코드 유효 기간은 5분이며, 거부, 만료, 폴링 제한
  및 일회성 교환은 고정된 BetterAuth 구현을 사용합니다.

OAuth 콜백 (운영자 앱 구성 필요):

```
https://relay.abruption.dev/api/auth/callback/github
https://relay.abruption.dev/api/auth/callback/google
```

## 최종 control API (미출시 후보)

JSON 본문만 허용되며 최대 16 KiB입니다. 알 수 없는 프로토콜 필드는 거부됩니다.
인증된 API 요청은 사용자당 분당 60회로 제한됩니다. 제한 사항은 소유자당 활성
챌린지 16개, 툼스톤을 포함한 총 32개의 기기 신원, 그리고 4096개의 영속
작업입니다. 공간을 확보하기 위해 작업 기록이 암묵적으로 삭제되는 일은 결코 없으며,
대기 중인 작업을 포함하여 제한 초과 시 페일클로즈됩니다.

| Endpoint | Result / checks |
| --- | --- |
| `GET /api/relay/devices` | Only caller-owned devices; no certificates/secrets |
| `POST /api/relay/challenge` | `{operation: "register" | "admission", payload}`; owner/operation/full-payload bound nonce, 60-second window |
| `POST /api/relay/devices` | Initial registration or key renewal; payload + `challengeId`, new-key `proof`, old-key `previousKeyProof` for renewal |
| `GET /api/relay/operations/:id` | Owner-only pending/committed result, for lost-response reconciliation |
| `POST /api/relay/admission` | Admission payload + `challengeId`, `proof`; short-lived ES256 relay JWT |
| `POST /api/relay/devices/:principal/revoke` | Owner session; no lost-device key requirement; permanent tombstone |

### 등록 및 인증서 갱신

```text
{ principal, certificatePEM, keyGeneration, name, operationId, expectedGeneration }
```

`principal`은 인증서와 별개인 고정된 무작위 64자 소문자 16진수 기기 신원입니다. `operationId`는 결과를
알 수 있을 때까지 유지되는 UUID v4입니다. 초기 등록 시에는 초기 인증서 DER
SHA256과 동일한 principal, 존재하지 않는 기기, `keyGeneration=0`
및 `expectedGeneration`의 생략이 필요합니다. 갱신 시에는 기존에 활성화된 동일 소유자의 principal,
`expectedGeneration=current generation` 및 `keyGeneration=expectedGeneration+1`이 필요합니다.
서버가 증가분을 계산/검사하므로, 클라이언트는 건너뛰기나 롤백을 선택할 수 없습니다.
최대 세대는 2147483647입니다. 갱신 시 소유자, principal 및 기존 이름은 보존되며,
`name`은 초기 등록 시 사용됩니다(갱신 시에는 기존 이름을
전송하십시오). 이름은 제어 문자가 없는 1–80자입니다.

인증서 입력은 정확히 하나의 공개 PEM 인증서여야 하며, 크기는 <=8192 바이트,
P-256 키를 사용하고 현재 유효 기간이 60초 이상 남아 있어야 합니다. 새 인증서는
저장된 인증서와 달라야 합니다. 동일 키에 대한 인증서 갱신은 허용됩니다.
소유권은 공개 CA 검증이 아닌 서명에 의해 입증됩니다; 등록이
엔드포인트 E2EE 페어링/PIN 인증을 대체하지는 않습니다. 개인 키는 절대 제출하지 마십시오.

초기 등록과 갱신 모두 챌린지 작업 **register**를 사용한 후
`POST /api/relay/devices`를 호출합니다. 새 키의 `proof`는 반환된 정확한 `proofMessage`에 서명합니다.
갱신 시에는 **동일한 메시지**에 대한 기존 키의 `previousKeyProof`가 추가로 필요합니다.
로그인만으로 교체하는 것은 허용되지 않습니다. 오직 저장된 기존 키의 소유만이
이전 인증서의 유효 기간을 무시하여 만료된 인증서의 갱신을 허용합니다;
새 인증서의 유효 기간과 일반 진입 유효 기간은 계속 강제됩니다. 기존
키를 분실한 경우 소유자에 의한 폐기 및 새 principal이 필요합니다. 폐기된 신원은
등록, 갱신 또는 재시도를 통해 결코 되살아나지 않습니다.

뮤테이션, 챌린지 소비 및 커밋된 영수증은 하나의 SQLite 트랜잭션입니다.
갱신은 미처리된 소유자 챌린지를 무효화하고, 상태를 즉시 재발행하며,
세대 변경에 걸쳐 있는 진입 서명을 거부합니다.

### 작업 결과 / 재시도 경계

등록 챌린지는 반환하기 전에 소유자/operationId/페이로드 다이제스트를 영속적으로
예약합니다. 뮤테이션 전 소유자 조회 시 반환:

```json
{ "operationId": "<fixed UUID v4>", "committed": false }
```

완료된 등록 및 `GET /api/relay/operations/:id`는 다음을 반환합니다:

```json
{
  "operationId": "<fixed UUID v4>",
  "committed": true,
  "principal": "<unchanged ID>",
  "keyFingerprint": "<SHA256 certificate DER>",
  "keyGeneration": 1
}
```

알 수 없는 ID와 다른 소유자의 ID는 모두 404를 반환합니다. 대기 중인 예약은
챌린지가 만료된 후에도 지속됩니다. 소유자/페이로드/operationId가 동일한 완료된 재시도는
챌린지가 만료되었거나 기기가 나중에 폐기되었더라도 추가 뮤테이션이나 증명 실행 없이
저장된 과거 영수증을 반환합니다. 변경된 페이로드
또는 다른 소유자의 operationId 재사용은 거부됩니다. 영수증은 **현재 기기
상태가 아닙니다**; 현재 세대/폐기 상태는 기기 목록을 사용하십시오. 폐기된 영수증
재시도로 기기를 부활시킬 수 없습니다. 발행 실패 시 뮤테이션이 롤백되고
해당 작업은 커밋되지 않은 상태로 남으며, 헬스는 발행이 복구될 때까지
진입을 차단합니다. 응답이 유실된 경우 ID를 보존하고 상태를 쿼리하십시오; 새 작업을
생성하거나 잠재적으로 수락되었을 수 있는 네이티브 에이전트 제출을 자동으로 재시도하지 마십시오.

### 챌린지 증명 및 시간 단위

응답: `{challengeId, nonce, issuedAt, expiresAt, proofMessage}`. 모든 control
API 및 공개 상태 `issuedAt`/`expiresAt` 값은 UNIX **초** 단위 숫자입니다.
BetterAuth의 네이티브 인증 API는 설치된 SDK 형태를 유지합니다; `expires_in` 및
`interval`은 상대적 초 단위입니다. 클라이언트는 반환된 정확한 UTF-8 메시지에
P-256 ECDSA/SHA256으로 서명하며, DER 서명은 패딩 없는 base64url로 인코딩됩니다:

```text
session-peer-control-v1:
<origin>
<operation>
<challengeId>
<nonce>
<SHA256 of server-canonical payload JSON>
```

클라이언트는 `session-peer-control-v1:` 접두사를 요구하며, 나머지 부분을
파싱/재구성하지 않고 반환된 정확한 문자열에 서명합니다. 마지막 개행은 없습니다. 서버 정규화는 operationId/expectedGeneration을
포함한 모든 등록 필드를 바인딩하므로 클라이언트는 JSON 정규화가 필요하지 않습니다.
진입 증명은 등록된 인증서의 현재 키를 사용합니다. 등록 증명은
제출된 인증서를 사용하며, 갱신의 previousKeyProof는 저장된 이전 키를 사용합니다.

`keyFingerprint`는 소문자 **SHA256(인증서 DER)**이며, 기존의
Python fingerprint/keyId 의미와 일치합니다. `cnf.jwk`는 해당 인증서의
공개 키에서 추출됩니다. 이는 **SHA256(SPKI DER)가 아닙니다**. JWK만으로는 인증서
DER을 재구성할 수 없습니다; 릴레이는 서명된 인증서 핑거프린트를 현재 상태와 비교하고
인증된 제어 발급자의 cnf에 대한 서명된 바인딩을 신뢰한 다음, cnf를
사용하여 소유권을 검증합니다. JWK/SPKI 해시를 계산하여 이 필드와 비교하지 마십시오.
서명용 `kid`는 별도의 제어 서명 키(현재 SPKI 해시)를 식별합니다;
이는 기기 인증서 핑거프린트가 아닙니다.

### 진입 토큰 및 릴레이 교환

진입 페이로드:

```text
{ role: "client" | "receiver", devicePrincipal, receiverPrincipal }
```

두 principal 모두 활성 상태여야 하고 동일한 내부 사용자 ID가 소유해야 합니다; 수신자
역할은 자신을 식별해야 합니다. Room = SHA256(UTF8(userId + NUL + receiverPrincipal)),
도메인 접두사는 없습니다. 호출자는 room/user/issuer/audience/TTL을 설정할 수 없습니다.

JWT는 **ES256**, 인식된 서명 `kid`, `typ=JWT`를 사용합니다. 클레임은 `iss`/`aud` =
구성된 릴레이 오리진, `sub` = 내부 불투명 사용자 ID, `devicePrincipal`,
`receiverPrincipal`, `keyFingerprint`, `keyGeneration`, `role`, `room`, `iat`,
`exp` (iat+60초), `jti`, `cnf.jwk` (공개 EC P-256 전용, 개인 키 자료 없음)입니다.
응답 `{token, expiresAt, room}`은 UNIX 초 단위 만료를 사용합니다. 제공자
액세스 토큰과 자사 세션 토큰 모두 Python 릴레이로 전송되지 않습니다.

릴레이 교환:

```http
Authorization: Bearer <JWT>
X-Session-Peer-Proof: <unpadded base64url DER ECDSA signature>
```

기기는 P-256 ECDSA/SHA256 및 마지막 개행 없이 정확한 UTF-8 `session-peer-admission-v1:` + **전체 JWT**에
서명합니다. 이는 제어 nonce 증명과는 별개입니다.
Python은 원자적 1회용 jti 소비 및 쿠키 발급 전에 서명/발급자/대상/시간/수명<=60/인식된 kid,
공개 P256 cnf, 현재 상태/소유자/세대/핑거프린트/역할/수신자/room 및
소유권을 검증해야 합니다. 실패한 증명이 다른 기기의 jti를 소진시켜서는 안 됩니다. 재생 저장소는
JWT 만료 시까지 재시작/다중 워커 전반에 걸쳐 검증되어야 합니다. 이는 Python 통합 관문입니다;
control 형식 테스트가 Python 수신자의 구현 완료를 입증하지는 않습니다.
OAuth 로그인/등록은 엔드포인트 E2EE 페어링/PIN 정책을 대체하지 않습니다.

## 운영자 메트릭

`GET /api/admin/metrics`는 브라우저 세션 전용 운영자 엔드포인트입니다. 운영자는
`SESSION_PEER_ALLOWED_ACCOUNTS`에 명시적으로 나열된 제공자 신원을 적어도
하나 보유한 인증된 사용자이며, 공개 가입으로는 이 역할을 절대 부여받을 수 없습니다.
응답에는 집계된 서비스 헬스, 가입 상태 및 카운트, 기기 수,
작업 수, 그리고 현재 공개 상태 리비전이 포함됩니다. 이메일,
제공자 계정 ID, 내부 사용자 ID, 기기 principal, 인증서, 토큰 또는
비밀 정보는 절대 반환하지 않습니다. React 경로는 `/admin/metrics`이며 30초마다
집계 뷰를 새로고침합니다.

`admin.abruption.dev`는 기존 Authelia 관리 포털로 유지합니다. 루트와
`/api/*` 경로는 이미 인증 콘솔이 소유합니다. 정확한 `/session-peer`
포털 페이지와 `/session-peer/api/metrics`를 모두 Authelia로 보호하십시오.
집계 API는 별도의 `127.0.0.1:3771` 리스너에서 제공하며 공개 릴레이
호스트로 라우팅해서는 안 됩니다. 이 방식은 Authelia를 유일한 브라우저
로그인으로 사용하면서 공개 릴레이가 전달된 신원 헤더를 신뢰하지 않게
합니다. 릴레이에 직접 접근하는 경우를 위해 기존 `/admin/metrics`와
`/api/admin/metrics`의 공급자 운영자 권한 검사는 유지합니다. Authelia
포털에서는 사용자, 공개 가입, 기기 및 작업의 제한된 상세 목록을 조회할 수
있습니다. 목록에는 이름, 이메일, 공급자, 작업 ID, 상태, 세대 및 축약된
principal이 포함될 수 있습니다. 공급자 계정 ID, 내부 사용자 ID, 전체
principal, 토큰, 쿠키, proof, 요청 hash, 인증서와 키는 절대 포함하지 않으며
각 응답은 최대 100행으로 제한합니다.

### 원자적 공개 상태 및 계약 전환

```text
{ schemaVersion: 1, revision, issuer, audience, issuedAt, expiresAt,
  jwks: { keys: [public signing JWK with kid/alg/use] },
  devices: { principal: { userId, keyFingerprint, generation, revoked } } }
```

이름, 이메일, 인증서, 세션/OAuth 토큰 또는 개인 키는 없습니다. 사용자 ID는
가명화된 소유권 메타데이터입니다. 공개 디렉터리를 서비스하는 공용 HTTP 경로는 없습니다.
단일 파일 바인드가 아닌 읽기 전용 **디렉터리 바인드**는 비공개 DB/서명 키/온톨로지/기타 서비스 파일에 대한
접근 권한을 부여하지 않고 원자적 교체를 노출합니다.
비공개 형제 항목을 노출하도록 DynamicUser 상위 디렉터리를 확장하지 마십시오.

모든 발행은 기기 뮤테이션 트랜잭션 또는 파일 교체 전에 control
SQLite 데이터베이스에서 안전한 정수형 `revision`을 영속적으로 새로 예약합니다.
예약은 뮤테이션 롤백 후에도 유지됩니다; 간격은 허용되나 재사용은 허용되지 않습니다. SQLite는
synchronous FULL과 함께 WAL을 사용합니다. 시작 시 기존 공개 파일보다
오래된 카운터는 거부됩니다. Python은 추가로 가장 높은 리비전과 콘텐츠 해시를 영속화합니다.
완전한 호스트 롤백에는 여전히 외부 복구 펜싱이 필요합니다; 복원된
카운터가 따라잡기를 기다리는 방식을 폐기된 기기를 되살리는 데 사용해서는 절대 안 됩니다.

공개 디렉터리는 umask 0077 하에서도 명시적으로 0755입니다. 각 새 상태
파일은 fsync/rename/디렉터리 fsync 전에 fchmod 0644로 설정됩니다; 비공개 상위 항목과
비공개 데이터베이스/서명 자료는 계속 보호됩니다. 디렉터리 바인드 마운트는
디렉터리 교체 없이 원자적 파일 교체를 인식합니다.

상태는 매 **60초**마다 재발행되고, **issuedAt+180초**에 만료되며,
뮤테이션 시 즉시 발행됩니다. Python은 상태가 누락/기형/만료되었거나
issuedAt>now+5초인 경우 페일클로즈합니다. 모든 진입 시마다 다시 읽고
기존 연결을 매초 재검사하여, 폐기/로테이션된 세션을 닫습니다. JWT TTL
만으로는 활성 세션 폐기가 되지 않습니다. 실제 연결/시계/재시작 동작은
Python/스테이징 검증이 필요합니다. 발행 실패는 DB 뮤테이션을 롤백하고
헬스 실패로 표시합니다; SQLite와 파일은 분산 원자적 트랜잭션이 아닙니다.
발행 후 DB 커밋 실패가 발생하면 일시적으로 접근이 거부될 수 있습니다; 실패한
해당 작업을 성공으로 보고하거나 오래된 상태 검사를 우회하지 마십시오.

최종 계약은 미공개 후보 55ff3bb/6815e1e/fae9029(SPKI 기기 해시,
밀리초 단위 챌린지, 개별 도메인 rotate 엔드포인트, 2초/10초
상태)를 대체합니다. 이전 아티팩트/클라이언트를 이 검증기와 혼용하지 마십시오. 시작 시 저장된
SPKI 기기 행은 `contract_migration_required`와 함께 거부됩니다; 이전
기기 핑거프린트나 작업 이력을 절대 암묵적으로 재해석하지 않습니다. 등록 스키마 마커 또한
세대를 다시 매기거나 영수증을 폐기하지 않고 이전의 데이터가 채워진 후보 데이터베이스를
거부합니다. 새로운 격리된 후보 상태를 사용하거나
이전 상태를 보존하는 명시적인 운영자 검토 마이그레이션을 계획하십시오. 여기서는 자동
자격 증명/기기 상태 삭제가 수행되지 않습니다.

## 빌드, 시크릿 및 운영

`control/`에서:

```
npm ci
npm run typecheck
npm test
npm run build
```

프로덕션 환경에서는 하나의 HTTPS 오리진(와일드카드 신뢰 오리진 불가),
32자 이상의 무작위 BetterAuth 시크릿, 선택적인 비상용 제공자
계정 ID 허용 목록, 명시적인 공개 가입 스위치 및 활성화된
운영자 소유 OAuth 앱을 명시적으로 구성해야 합니다. 예시 **비-비밀** 값:

```
NODE_ENV=production
SESSION_PEER_CONTROL_ORIGIN=https://relay.abruption.dev
SESSION_PEER_ALLOWED_ACCOUNTS=[{"provider":"github","accountId":"REPLACE_WITH_NUMERIC_PROVIDER_ID"}]
SESSION_PEER_PUBLIC_SIGNUP=true
SESSION_PEER_CONTROL_DATA=/var/lib/session-peer-control/private
SESSION_PEER_RELAY_PUBLIC=/var/lib/session-peer-control/relay-public
GITHUB_CLIENT_ID=REPLACE_WITH_OPERATOR_APP_ID
GOOGLE_CLIENT_ID=REPLACE_WITH_OPERATOR_APP_ID
```

허용 목록이 누락된 경우 운영자가 명시적으로 `SESSION_PEER_PUBLIC_SIGNUP=true`를
설정하지 않는 한 기본적으로 모두 거부됩니다. 공개 가입에는 초대 목록이나 사용자
수 상한이 없습니다. 이를 다시 `false`로 설정하면 새 등록이 마감되지만 이전에
커밋된 공개 신원 및 명시적 허용 목록 항목은 계속 사용할 수 있습니다.
제공자 검증은 최대 10분 동안 보류 중인 신원 예약을 생성하며,
SQLite `IMMEDIATE` 트랜잭션을 통해 동시 콜백이 동일한 신원에 대해
경쟁하는 것을 방지합니다. OAuth 시크릿과 BetterAuth 시크릿은
`*_SECRET_FILE`/`BETTER_AUTH_SECRET_FILE` 및 systemd LoadCredential에서 가져옵니다;
이를 커밋하거나 브라우저 자격 증명을 복사하지 마십시오. 운영자가 제어하는
로컬/테스트 환경을 위해 원시 환경 변수 값도 지원됩니다; 환경 덤프를 절대 출력하지 마십시오.
활성화된 GitHub/Google 제공자의 경우 배포 오버라이드에 LoadCredential 항목과 해당
`GITHUB_CLIENT_SECRET_FILE`/`GOOGLE_CLIENT_SECRET_FILE` 경로를 추가하십시오.
절반만 구성된 자격 증명이 누락된 경우 시작이 거부됩니다. 비활성화된 제공자는
클라이언트 ID와 시크릿 파일이 모두 구성되지 않아야 합니다.

컴파일된 `node dist/server/migrate.js`를 실행할 때 동일한 보호된 구성과 배타적 writer lock을 사용한 다음 `npm start`를 실행하십시오. 이 명령은 설치된 버전을 보고하기 전에 Better Auth 및 버전이 지정된 session-peer 자체 스키마를 마이그레이션합니다. 마이그레이션은 명시적입니다. 프로덕션 시작은 해당 스키마를 검증하고 테이블을 암묵적으로 생성하거나 다시 작성하는 대신 `migration_required`로 실패합니다. 업그레이드 전에 일관된 보호 스냅샷을 만들고 마이그레이션을 `ExecStartPre` 또는 자동 재시작 경로에 넣지 마십시오. 로컬 개발 환경은 localhost
또는 127.0.0.1에서만 HTTP를 허용하며 프로덕션 시크릿을 사용해서는 안 됩니다. 상태는 소스 외부 및
iCloud 외부에 있어야 합니다. 비공개 서명 키는 0600 모드로 한 번 생성되며
재시작 후에도 유지됩니다. 모든 비공개 DB/상태 상위 디렉터리는 소유자 전용입니다; 백업에는
control SQLite 일관된 스냅샷, 서명 키 및 OAuth 정책이 별도의
보호된 리소스로 포함되어야 합니다. 이는 중앙 온톨로지 SQLite가 **아닙니다**.

`deploy/examples/authenticated-control/session-peer-control.service`는 활성화된 유닛이 아닌 설치 템플릿입니다:
루프백 3770, DynamicUser, 배타적 flock 작성자 락, 비공개 영속
상태, 보호된 homes/system/kernel, 읽기 전용 control 트리만 노출하는 격리된
`/opt` 마운트, 접근 불가능한 타 서비스 data/config/log 경로, capability
없음, 256MiB/50% CPU/64 태스크.
배포 시에는 `/usr/bin/node`에 지원되는 Node를 제공하고, 빌드된
control 트리를 설치하며, 서비스의 비공개 상태에서 인증 스키마를 마이그레이션하고 제공자
자격 증명/정책을 설정해야 합니다. 실행 락은 동시 systemd control 작성자를 방지합니다;
수동 실행 시에도 동일한 락을 사용해야 합니다. 설치 중에 락 소유권/상태 경로를 확인하십시오.
Node 메모리/런타임 동작은 여전히 스테이징 관찰이 필요합니다.

Caddy 통합은 `/api/control/*`, `/api/auth/*`, `/api/relay/*` 및
웹 페이지/에셋을 기존 Python 릴레이 웹소켓/진입 경로로부터 3770으로 분리해야 합니다.
통합된 아티팩트와 리소스 격리가 스테이징 소유자와 함께 검토되기 전까지는 Caddy를
다시 로드하거나 호스트 이름을 열지 마십시오. 알 수 없는 경로는 404를 반환합니다;
`.env` 및 소스/상태 파일은 정적 에셋이 아닙니다. 보안 헤더에는
no-store, 엄격한 CSP, 안티 프레이밍 및 no-referrer가 포함됩니다. HTTP 서버는
X-Forwarded-Host나 임의의 Host 값을 신뢰하지 않습니다. 프록시는 구성된
오리진 Host를 보존해야 합니다. 서버는 루프백 소켓으로부터 인증 IP 헤더를 덮어씁니다; 신뢰할 수 없는
X-Forwarded-For는 인증 제한기를 우회할 수 없습니다. 이 보수적인 후보는
로컬 프록시 전체에서 인증 엔드포인트 제한을 공유하므로 다중 사용자 용량은 여전히
스테이징 측정이 필요합니다. 여러 Set-Cookie 헤더는 개별적으로 보존됩니다.
요청 URL/헤더/본문/토큰 로깅은 활성화되어 있지 않으며, 진단
메시지에는 고정된 운영 오류 코드만 포함됩니다.

## 검증 경계

로컬 테스트는 실제 BetterAuth/SQLite/device-code 엔드포인트, 생성된 픽스처
P-256 인증서 및 암호화 연산, 그리고 루프백 상의 컴파일된 HTTP 서버를 사용합니다. 인증
픽스처는 비공개 임시 제어 DB에 테스트 사용자/계정/세션을 시드합니다.
별도의 콜백 테스트는 아웃바운드 GitHub/Google 전송만을 모의 처리하며, 픽스처
자격 증명과 서명된 픽스처 Google 토큰을 사용합니다; 이들은 고정된 네이티브 OAuth
state/PKCE/callback/allowlist/account-linking 경로를 실행합니다. 제공자 요청은 전송되지 않습니다.
**프로덕션 가짜 OAuth 엔드포인트나 인증 우회는 존재하지 않습니다**. OpenSSL은 테스트 전용입니다.
테스트는 소유자 격리, 정책 폐기, CSRF, 정확한 브라우저 세션 클레임,
코드 승인/거부/만료/교환, 챌린지 만료/재생/변조, 키
교체 거부, 듀얼 키 로테이션, 세대 경쟁 상태, 동일 메시지 previousKeyProof, 소유자 전용 영속 작업
조회/대기/커밋/재오픈된 DB 재시도,
만료된 인증서 갱신, 폐기된 툼스톤, 원자적 상태 발행 실패
및 비-시크릿 상태,
루프백/정적/Host/본문 제한 동작, 거부된 위조 Google ID 토큰 및
허용 목록에 없는/동일 이메일의 상이한 제공자 신원을 다룹니다. 이들은 실제 자격 증명 기반 제공자
OAuth, Mac 사용자 브라우저, Python JWT 통합, 24시간 운영 또는 실제 Claude
할당량 복구 테스트가 아닙니다. RC PR 전에 이들 각각을 별도로 기록하십시오. 본 구현에 의해
어떠한 머지, 릴리스 태그, 발행 또는 원격 푸시도 승인되지 않습니다.

공식 참고 자료 (설치된 1.7.5 소스를 기준으로 구현 검증됨):
- https://better-auth.com/docs/plugins/device-authorization
- https://better-auth.com/docs/plugins/bearer
- https://better-auth.com/docs/concepts/users-accounts

## 등록 예시

이러한 축약된 형태는 예시용입니다. 새로운 챌린지를 받아 반환된
정확한 `proofMessage`에 서명하십시오; 인증서, 서명 및 챌린지 플레이스홀더는
실행 가능한 자격 증명이 아닙니다.

초기 챌린지 페이로드 (`operation: "register"`):

```json
{
  "principal": "<initial certificate DER SHA256>",
  "certificatePEM": "<device certificate>",
  "keyGeneration": 0,
  "name": "laptop",
  "operationId": "11111111-1111-4111-8111-111111111111"
}
```

해당 페이로드와 함께 `challengeId` 및 새 키 `proof`를
`POST /api/relay/devices`로 전송하십시오. 처음으로 로테이션할 때는 동일한 principal을 유지하고,
`expectedGeneration: 0` 및 `keyGeneration: 1`을 설정하며, 대체
인증서와 안정적인 새 로테이션 작업 UUID를 제공하십시오. 동일한 챌린지 메시지에 대해
이전 키의 `previousKeyProof`를 추가하십시오. 불확실한 응답 속에서도 해당 작업 ID를
보존하고 `GET /api/relay/operations/<operationId>`로 소유자 전용 과거 영수증을
조회하십시오.

초기 등록 시에는 `expectedGeneration`을 반드시 생략해야 하며, 로테이션 시에는 필수입니다.
이전 후보에서 사용된 세대를 추론하거나 암묵적으로 변환하지 마십시오.
`tests/control_integration/test_control_integration.py`에 있는 실행 가능한 Node/Python 픽스처는
등록, 진입, 폐기된 자격 증명, 소유자 간 거부 및 응답 유실이
동반된 로테이션을 다룹니다. 시드된 픽스처 세션은 실제 OAuth의 증거가 아닙니다.
