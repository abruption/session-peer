# Cloudflare 뒤의 네이티브 클라이언트 (RC 검증)

릴레이의 브라우저 UI와 네이티브 API는 서로 다른 클라이언트를 가집니다. 브라우저 OAuth 콜백이나 공개 헬스체크 GET이 성공했다고 해서 기기 코드(device-code) POST나 인증된 WebSocket 연결이 작동한다고 단정할 수 없습니다.

KR 파일럿에서 네이티브 기기 코드 요청이 HTTP 403 / Cloudflare 1010(`browser_signature_banned`)을 반환했습니다. 해당 Cloudflare 보안 이벤트는 `source=bic`, `ruleId=bic`, `action=block`으로 확인되었습니다. 이는 해당 요청에 대해 Browser Integrity Check가 원인임을 식별한 것이며, Bot Fight Mode가 원인으로 식별된 것은 아닙니다.

## 네이티브 POST 예외 기준선

소유자는 먼저 기기 코드/토큰 경로를 승인한 다음, 세 가지 등록/허가(admission) POST 경로를 명시적으로 승인했습니다. 이는 `http_config_settings` 내의 단일 Configuration Rule로 유지되며, `action=set_config` 및 `action_parameters={"bic":false}`로 설정됩니다. 해당 표현식은 다음과 같습니다:

```text
(http.host eq "relay.abruption.dev" and ssl and http.request.method eq "POST" and http.request.uri.path in {"/api/auth/device/code" "/api/auth/device/token" "/api/relay/challenge" "/api/relay/devices" "/api/relay/admission"} and http.request.uri.query eq "")
```

이는 쿼리가 없는 5개의 HTTPS POST 엔드포인트에 대해서만 BIC를 비활성화합니다. 영역(zone) 전체 BIC 설정, 관리형 WAF, Bot Fight Mode, DDoS 보호, 보안 수준, 기존 속도 제한 규칙(rate rules) 및 원본 서버 인그레스 제한은 변경되지 않은 상태로 유지됩니다. 기존 Cloudflare 속도 제한 규칙은 다른 서비스를 보호하므로 릴레이 전용 속도 보호로 기술해서는 안 됩니다. Control 자체의 요청 제한, 고정 클라이언트 ID, 코드 만료/폴링 제한, 명시적 공개 가입 스위치 또는 계정 허용 목록(allowlist), 그리고 명시적 브라우저 승인은 계속 적용됩니다. 이 규칙과 일치하더라도 어떤 인증도 부여되지 않습니다.

해당 구성은 명시적 승인 후에 적용되었습니다. v2 규칙의 Cloudflare Trace는 의도된 5개 경로 모두와 일치했으며, 다른 메서드/호스트, 쿼리, 후행 슬래시, 일반 텍스트 HTTP, 브라우저 승인/취소, 작업 조회(operation lookup) 및 릴레이 세션/WebSocket 엔드포인트를 포함한 10개의 다른 사례를 제외했습니다. 1단계는 실제 네이티브 코드 발급, 브라우저 승인 및 토큰 폴링도 통과했습니다. Trace는 구성 검증일 뿐이며, 다운스트림 네이티브 전달 성공에 대한 증거는 아닙니다.

## 변경 및 롤백

다른 배포에 이러한 규칙을 적용하기 전에 기존 구성 단계를 확인하고 다른 규칙들을 보존하십시오. 기존 규칙 세트를 위의 예시로 교체하거나 전체 영역에 대해 BIC를 비활성화하지 마십시오. 새 규칙 ID/버전을 기록하고, 저장된 표현식을 다시 읽은 뒤 의도된 사례와 제외된 사례를 점검하십시오.

동시 구성 변경 사항을 보존하면서 추가된 규칙만 되돌리십시오(해당 ID로 비활성화/삭제). 에지 규칙 되돌리기의 일환으로 애플리케이션 데이터베이스, 키, 영수증(receipts) 또는 재생(replay) 상태를 복원하지 마십시오.

POST 전용 기준선은 작업 조회 또는 릴레이 세션/WebSocket GET 라우트를 포함하지 않습니다. 후속 승인된 작업 조회 범위는 아래에 설명되어 있습니다. 릴레이 세션/WebSocket GET에는 여전히 BIC 예외가 없습니다. 브라우저 사용자 에이전트를 모방하거나, 브라우저 쿠키를 CLI로 전달하거나, 명시적인 재시도 불가 차단에 대해 계속 재시도하지 마십시오. 기기 코드, 토큰 및 비밀값(secrets)이 로그나 보고서에 노출되지 않도록 유지하십시오.

## 승인된 작업 영수증 조회

소유자는 이후 네이티브 영수증 조회 403 오류 해결을 승인했습니다. 새로운 네이티브 조회가 오류 1010을 반환했습니다. GraphQL 진단 API의 예산이 소진되었기 때문에 정확한 과거 보안 이벤트를 읽을 수 없었습니다. BIC 전용 변경을 통해 등록을 반복하지 않고 먼저 단일 수신자 영수증 URL을 복원했습니다. 이 제한적인 성공적 실험은 다른 ID들을 해결하지 못했습니다.

동일 규칙의 버전 4는 이제 릴레이 호스트에서 **쿼리가 없는 HTTPS GET**에 추가로 일치하며, `/api/relay/operations/` 뒤에 표준 소문자 UUIDv4가 오는 경로를 포함합니다. 58바이트 경로, 16진수 문자, 하이픈 위치, 버전 및 변형은 본 배포에서 지원하는 `starts_with`, `len`, `substring` 및 문자별 비교를 사용하여 검사됩니다. 유료 정규식 기능이나 요금제 업그레이드는 사용되지 않았습니다. 지원되지 않는 대체 표현식은 활성 구성을 변경하지 않고 거부되었습니다. 이는 운영 레시피가 아닙니다.

Trace는 기존 작업 ID와 잘못된 형식의 ID, 대문자, 잘못된 버전/변형, 후행 슬래시, 쿼리, 메서드/호스트/프로토콜 및 관련 없는 API 제외를 포함한 21개 사례를 통과했습니다. 그 후 원래 등록된 두 기기 모두 새로운 등록 없이 CLI exit 0으로 커밋된 영수증을 조정(reconcile)했습니다. 인증된 다른 소유자와 존재하지 않는 표준 작업 ID는 애플리케이션으로부터 404를 수신했습니다. 이 예외는 BIC만 우회하며, 소유권을 부여하거나 API 인증을 우회하지 않습니다.

이 구성을 재사용하기 전에 대상 영역/단계에서 정확한 표현식을 검증하고 다른 규칙들을 보존하십시오. 파일럿의 마스킹된 표현식, API 결과 및 롤백 diff는 [RC validation](validation/69-rc.md)에서 인용한 운영 증거 디렉터리의 `DYNAMIC-RECEIPT-BIC-RESULT.md`에 보관되어 있습니다.

참고 자료: [Cloudflare error 1010](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/) 및 [Browser Integrity Check](https://developers.cloudflare.com/waf/tools/browser-integrity-check/).
