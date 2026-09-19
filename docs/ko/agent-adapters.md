# 내부 에이전트 어댑터 개발하기

이 문서는 외부 플러그인 설치 인터페이스가 아닌 소스 확장 가이드입니다. 계약 버전 관리, 호환성, 결과 시맨틱 및 신뢰 경계에 대해서는 [아키텍처 결정](architecture/agent-transports.md)을 참조하세요.

어댑터는 `AgentAdapter`를 상속하고, 고유한 소문자 `name`을 선언하며, `list(context)` 및 `submit(context, text)`를 구현합니다. `main()`이 실행되기 전에 `AGENTS.register(...)`로 명시적으로 등록하세요. SSH를 통해 작동해야 하는 경우 독립형 소스에 해당 구현을 유지하세요. 기본적인 새 어댑터의 경우 CLI 라우터나 SSH 디스패처를 변경할 필요가 없습니다.

최소한의 결정론적 예시 (테스트 전용):

```python
class ExampleAdapter(AgentAdapter):
    name = "example"
    capabilities = AgentCapabilities()  # list/send; no wake/wait/ack

    def list(self, context):
        return {"sessions": [{"agent": self.name, "id": "one", "status": "idle"}],
                "discovery": {"status": "ok"}}

    def submit(self, context, text):
        target = self.identity(context.options.to, context)
        return {"ok": True, "target": {"id": target.identifier},
                "status": "validated" if context.options.dry_run else "submitted",
                "submitted": not context.options.dry_run,
                "consumptionConfirmed": False}

AGENTS.register(ExampleAdapter())
```

이 예시에는 실제 인박스가 없으므로 실제 전달 어댑터로 출시하지 마세요. 테스트 전용인 `tests/fixtures/agent_adapter.py`는 계약 테스트에 사용되는 실행 가능한 예시를 제공하며 배포되는 배포판에서 제외됩니다.

- `list`는 `sessions`와 `status`가 `ok`, `error`(`error` 텍스트 포함) 또는 `not_installed`인 `discovery` 객체를 반환합니다. 모든 행은 해당 에이전트를 식별합니다. 네이티브 신원 필드를 보존하세요. 다양한 행 레이아웃을 위해 `display_row`/`render`를 구현하세요. Codex는 기존 최상위 홈 메타데이터를 추가로 보존합니다.
- `submit`은 이미 검증되고 래핑된 메시지를 정확히 한 번 수신합니다. 네이티브 부작용이 발생하기 전에 dry-run을 준수하세요. 네이티브 제출 사실을 반환하며, 소켓/큐 수락으로부터 확인을 추론하지 마세요. 알려진 제출 이후의 네이티브 실패는 해당 ID와 부분 결과를 유지해야 합니다.
- `identity` 및 `target`은 네이티브 신원과 CLI/Reply-To 대상을 변환합니다. 기본값은 `name:identifier`이며, Claude는 접두사가 없는 이름/PID를 보존합니다.
- `diagnose`, `diagnostic_text`, `listing_notes`, `submission_text`, `remote_submission` 및 `remote_options`는 공통 라우팅을 변경하지 않고 증거 및 기존 출력 호환성을 특화합니다. 인자 옵션은 여전히 파서에서 명시적으로 선언되어야 하며, 에이전트가 셸 코드를 주입할 수는 없습니다.
- 기능 불리언은 구현 지원 여부만을 보고합니다. false인 기능은 제출 전에 실패합니다. wake를 알린다고 해서 네이티브 런타임 검사나 MCP 인증을 건너뛰지는 않으며, wait/ack는 이번 버전에서 CLI 구현이 없습니다.

MCP는 명시적으로 승인된 대상과 에이전트만 허용합니다. 소스 등록만으로는 원격/전송 권한이 부여되지 않습니다. 선택적 의존성은 코어 import 경로 외부에 있어야 합니다. 백엔드 의존성을 추가하려면 별도의 패키징 결정이 필요합니다. 공용 외부 로딩 및 설치는 구현되지 않았습니다.

선택적 MCP SDK가 없는 상태와 있는 상태 모두에서 기존 스위트 및 공유 계약 테스트를 실행하세요. 또한 wheel과 sdist를 독립적으로 빌드/설치하고 격리된 독립형 설치 프로그램 테스트를 실행하세요. 프로덕션 세션이 아닌 픽스처 트랜스포트를 새로운 계약 커버리지에 사용하세요.
