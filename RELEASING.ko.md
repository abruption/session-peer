# session-peer 릴리스하기

GitHub 릴리스를 발행하면 `.github/workflows/publish.yml`이 트리거되어 태그를 빌드하고 Trusted Publishing을 통해 PyPI에 업로드합니다. 드래프트 릴리스는 발행되지 않습니다. 태그와 업로드된 아티팩트가 항상 검토된 코드를 가리키도록 릴리스 준비, 승인, 발행 및 검증을 별도의 단계로 유지하세요.

## 현재 후보: v0.9.0

v0.9.0 후보는 승인된 #47 어댑터/트랜스포트 리팩터링, #69 릴레이 실험실, #85 Antigravity 어댑터와 네이티브 어댑터를 통해 페어링된 요청을 라우팅하는 선택적 제품 릴레이 패키지를 통합합니다. 이전의 #87/#88 PR은 의존성 브랜치에 병합되었으며, 승인된 변경 사항은 메인 타깃 릴리스 PR로 명시적으로 전달됩니다. 후보 릴리스 노트: `docs/releases/v0.9.0.md`. #89에서 발행을 추적하며 아티팩트 검증이 완료될 때까지 열어 둡니다.
플러그인 매니페스트는 독립적인 버전(0.1.0)을 유지합니다.

### #90, #91, #92 이후의 최종 통합

릴리스 최종화 브랜치는 main `27b28dd`에서 시작되며, 여기에는 v0.9 기능 준비(#90), 지원/보안 파일럿(#91), 4개 국어 README(#92)가 포함되어 있습니다. 후자에는 조정된 v0.9 기능 설명 및 sdist 내용이 포함됩니다. 패키지 버전은 이미 `0.9.0`이므로 이번 문서 최종화를 위해 다시 올리지 마세요. 이 베이스는 최종 릴리스 커밋이 아닙니다. 최종화 PR이 병합된 후 정확한 main 커밋을 기록하세요.

- #89를 열어 두세요: 준비 PR 병합이 발행 또는 아티팩트 검증을 의미하는 것은 아닙니다.
- 세 개의 번역된 README, `docs/cli-reference.md`, 보안 정책 및 v0.9 릴리스 노트를 선택적 릴레이 파일과 함께 sdist에 포함합니다.
- 독립적인 플러그인 버전, 동결된 기존 업데이터, 선택적 extra 및 실험 제외를 유지합니다. CI에서 wheel과 sdist 설치를 모두 검증합니다.
- 이 최종화가 준비될 당시 가장 최근에 발행된 릴리스는 v0.8.0이었습니다. 후보 문구를 성공적인 PyPI 업로드로 해석해서는 안 됩니다.
- 병합 후에만 드래프트를 생성하세요. 릴리스 발행에는 아래에 설명된 별도의 최종 승인이 여전히 필요합니다. 이 PR에서 #89를 자동으로 닫지 마세요.

릴레이 extra에는 Unix 및 Python 3.11+가 필요합니다. `docs/relay-public-pilot-2026-09-17.md`의 공개 파일럿 증거를 포함하여 의존성이 없는 코어 외에도 `.[relay,mcp]`를 검증하세요. 제한된 실시간 테스트는 소크(soak) 테스트가 아닙니다. 실제 운영 검증은 v1.0.0-rc의 관문으로 남아 있습니다.

저장소는 레거시 자체 업데이트 URL을 위해 동결된 루트 `cc_peer.py`를 계속 포함해야 합니다. 이는 session-peer wheel 및 sdist 외부에 남아 있어야 합니다.

## Trusted Publisher 구성

GitHub 환경은 `pypi`이고 활성 워크플로는 `publish.yml`입니다. PyPI 프로젝트 소유자는 다음 Trusted Publisher 매핑을 유지해야 합니다:

| Field | Value |
| --- | --- |
| PyPI project | `session-peer` |
| GitHub owner | `abruption` |
| GitHub repository | `session-peer` |
| Workflow filename | `publish.yml` |
| GitHub environment | `pypi` |

v0.6.1 릴리스는 이 경로를 성공적으로 사용했습니다. GitHub는 PyPI 소유자 측 매핑을 검사할 수 없으므로 이전의 성공은 변경되지 않았음을 보장하는 것이 아니라 증거일 뿐입니다.

## 준비 및 검증

1. 릴리스 이슈를 생성하고 현재 `origin/main`에서 브랜치를 생성합니다.
2. 하나의 릴리스 준비 PR에서 `session_peer.__version__`, 지속적인 README 문구, 이 런북 및 `docs/releases/<version>.md`를 업데이트합니다.
3. CI에서 사용되는 검사를 실행합니다:

   ```bash
   python3 -m compileall -q cc_peer.py session_peer.py session_peer_mcp.py tests
   python3 -m unittest discover -s tests -v
   python3 -m unittest discover -v
   python3 -m build
   ```

   `.[mcp]` extra가 설치된 별도의 Python 3.10+ 환경에서 테스트 스위트를 반복합니다. 독립형 환경에서는 선택적 SDK 테스트만 건너뛰어야 합니다. 릴리스 검사 시 실시간 wake/모델 테스트를 활성화하지 마세요.

4. 두 아카이브를 모두 검사합니다. `session_peer.py`, 라이선스, 메타데이터 및 README는 sdist에 속하며, wheel에는 `session_peer.py`, `session_peer_mcp.py`, 선택적 `session_peer_relay/` 패키지 및 메타데이터가 포함됩니다. sdist에는 MCP/wake/멀티 홈 문서와 플러그인 파일도 포함됩니다. 어떤 아카이브도 `cc_peer.py`, 자격 증명, 세션 데이터베이스 또는 로컬 메모를 포함해서는 안 됩니다.
5. 새로운 환경에서 wheel과 sdist를 각각 독립적으로 설치합니다. `session-peer --version`, `session-peer list --output-format json` 및 import 메타데이터를 확인합니다. 세션이 없는 스모크 테스트에는 격리된 임시 HOME을 사용하세요. extra가 설치된 상태에서 `session-peer-mcp --help`를 확인합니다. 기본 정책은 로컬 읽기 전용으로 유지되어야 합니다.
6. 필요한 모든 검사를 통과한 후에만 릴리스 준비 PR을 병합합니다. `main`을 가져와 정확한 커밋을 기록하고 원하는 변경 사항과 버전이 여전히 포함되어 있는지 확인합니다.

## 드래프트 준비

스쿼시 또는 병합 커밋은 릴리스 커밋을 변경하므로 릴리스 준비 PR이 병합된 후에만 드래프트를 생성하세요:

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v0.9.0 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v0.9.0" \
  --notes-file docs/releases/v0.9.0.md \
  --draft --latest
```

드래프트의 태그, 타깃 커밋, 제목, 노트, 드래프트 상태 및 사전 릴리스(prerelease) 상태를 확인합니다. 드래프트를 저장하는 동안 GitHub가 태그를 생성한 경우 기록된 릴리스 커밋으로 확인되는지 확인하세요. 기존에 발행된 태그를 이동하지 마세요.

## 발행

발행 직전에 최종 승인을 받습니다. 발행은 GitHub 릴리스를 공개하고 PyPI 업로드를 시작하는 작업입니다:

```bash
gh release edit v0.9.0 --repo abruption/session-peer --draft=false --latest
```

워크플로가 실패하더라도 두 번째 릴리스를 생성하거나 수정된 아티팩트로 재시도하지 마세요. 실패한 실행을 보존하고 실패한 단계를 진단하세요. PyPI에서 이미 수락된 버전은 대체할 수 없습니다.

## 발행 검증

1. 릴리스로 트리거된 `publish.yml` 실행이 성공적으로 완료되었고 예상된 태그 및 커밋을 사용했는지 확인합니다.
2. PyPI에 정확히 `session-peer==0.9.0`이 노출되는지 확인합니다. wheel과 sdist를 다운로드하여 해당 파일 이름과 SHA-256 해시를 워크플로 아티팩트와 비교하고 내용을 다시 검사합니다.
3. 새로운 환경에 PyPI에서 0.9.0을 설치합니다. 버전과 로컬 읽기 전용 목록 조회를 확인합니다. 제출 없는 dry-run은 명시적인 임시 Codex 홈 및 실행 파일을 사용할 수 있으며, 큐 명령어가 실행되지 않았음을 증명한다면 예상된 대상 실패는 허용됩니다.
4. GitHub가 v0.9.0을 latest로 표시하고 이전 독립형 설치에 대해 `session-peer update --check`가 이를 보고하는지 확인합니다.
5. GitHub, PyPI, 신규 설치 및 업데이터 검증이 기록된 후에만 릴리스 이슈를 닫습니다.

패키지 관리자로 설치한 경우 자체 관리자로 업그레이드합니다. 독립형 설치는 `session-peer update`를 사용하며 번들된 Claude 스킬을 새로고침하려면 `install.sh`가 필요합니다. 제출이 소비나 확인의 증거는 절대 아닙니다.
