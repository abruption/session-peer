# session-peer 릴리스

GitHub 릴리스를 게시하면 `.github/workflows/publish.yml`이 트리거되어 선택한 태그를 빌드하고 Trusted Publishing을 통해 PyPI에 업로드합니다. 드래프트는 게시되지 않습니다. 공개 아티팩트가 항상 검토된 코드를 가리키도록 준비, 승인, 게시 및 검증 단계를 분리하여 유지하십시오.

RC3 배포와 정식 버전 승격은 별도 조건입니다. 게시된 정확한 RC3를 5개 호스트에서 독립적인 ACK 증거와 중단 없는 4시간 관찰로 검증할 때까지 #161, #163, #164와 RC3 마일스톤을 유지하십시오. [RC3 검증 계획](docs/ko/releases/v1.0.0-rc.3.md)을 따르며 RC2 증거와 오프라인 재현으로 대체하지 않습니다.

## 현재 후보: v1.0.0-rc.3

세 번째 1.0 릴리스 후보는 #158의 Windows 수정을 포함한 RC2 계약을 유지하면서, #161에서 추적 중인 공개 릴레이 경로 실패에 대응해 제출 전 설정 재시도가 제한된 경로 진단(#162)과 수신자 재연결 공백 단축 및 role_busy 지표(#168)를 추가합니다. RC2의 Claude와 SSH 수정은 안정 버전 v0.9.2에도 배포됐습니다. 표준 Python/PyPI 버전은 `1.0.0rc3`이며, 사용자용 Git 태그 및 GitHub 릴리스는 `v1.0.0-rc.3`입니다. `packaging.version.Version`은 이 값들을 동일하게 취급합니다. RC 제로로 정규화되는 단순 `v1.0.0-rc`는 사용하지 마십시오.

이번 릴리스는 명시적인 시험판(prerelease)입니다:

- GitHub 릴리스를 **Pre-release**로 표시하고 Latest로 표시하지 마십시오.
- 일반 안정 버전 패키지 업그레이드는 v0.9.2을 계속 선택해야 합니다.
- 테스터는 `pipx install 'session-peer[relay]==1.0.0rc3'` 또는 이에 상응하는 `uv` 명령어로 정확한 버전을 설치합니다.
- GitHub, PyPI 및 클린 설치 검증이 완료될 때까지 v1.0.0-rc.3 마일스톤을 열린 상태로 유지하십시오.
- 플러그인 매니페스트는 독자적인 버전(0.1.0)을 유지합니다.

후보 버전에는 로컬/SSH 작동, 선택적 MCP 및 Antigravity 어댑터, 페어링된 직접/릴레이 전송, 관리형 허가(managed admission), 공개 OAuth 가입, 능동적 해지(active revocation)와 복구, 운영자 메트릭 및 검토된 KR 배포 아티팩트가 포함됩니다. 릴레이 엑스트라는 Unix 및 Python 3.11+를 필요로 합니다. 기본 코어는 Python 3.9+에서 의존성 없이 유지됩니다. 호스팅된 릴레이는 운영 서비스이며 패키지 가용성에 대한 약속이 아닙니다.

저장소는 레거시 자체 업데이트 URL을 위해 루트의 동결된 `cc_peer.py`를 유지해야 하지만 wheel 및 sdist에서는 제외해야 합니다. 4개의 README, 보안 정책, 릴리스 후보 노트, 릴레이 수명주기/인증 문서 및 선택적 런타임 소스를 모두 포함하십시오. OAuth 자격 증명, 기기 키, 인증 데이터베이스, 재생 상태(replay state), 브라우저 프로필, 로컬 증거 또는 대화 내용을 절대로 포함하지 마십시오.

## Trusted Publisher 설정

GitHub 환경은 `pypi`이고 활성 워크플로는 `publish.yml`입니다. PyPI 프로젝트 소유자는 다음 Trusted Publisher 매핑을 유지해야 합니다:

| 필드 | 값 |
| --- | --- |
| PyPI project | `session-peer` |
| GitHub owner | `abruption` |
| GitHub repository | `session-peer` |
| Workflow filename | `publish.yml` |
| GitHub environment | `pypi` |

이전의 성공적인 릴리스는 참고 증거일 뿐이며, 소유자 측 매핑이 변경되지 않았음을 보장하지 않습니다.

## 준비 및 검증

1. 릴리스 브랜치가 병합된 #158, #162, #168을 포함하고 `main`을 대상으로 하는지 확인하십시오. 안정 버전 유지보수 브랜치를 main에 병합하지 마십시오.
2. `session_peer.__version__ == "1.0.0rc3"`인지 확인하고, 릴리스 후보 노트가 sdist에 포함되어 있는지, 4개 README의 설치 명령어가 일치하는지 확인하십시오.
3. 전체 CI 매트릭스를 실행합니다. 로컬에서 코어 스위트, 컨트롤 Node 22/24 스위트, Node/Python 통합, 최종 diff에 적합한 빌드 및 아카이브 검사를 반복하십시오. 라이브 모델 제출은 릴리스 준비 과정에 포함되지 않습니다.
4. 정확한 후보로부터 한 번 빌드합니다:

   ```bash
   python3 -m build
   ```

5. 두 아카이브를 모두 검사합니다. wheel에는 `session_peer.py`, `session_peer_mcp.py`, `session_peer_relay/` 및 메타데이터가 포함됩니다. sdist에는 승인된 문서 및 배포 템플릿도 포함됩니다. 어떤 아카이브에도 `cc_peer.py`, 자격 증명, 데이터베이스, 재생 상태, 개인 키, 브라우저 데이터 또는 로컬 증거가 포함되어서는 안 됩니다.
6. 깨끗한 환경에 wheel과 sdist를 각각 독립적으로 설치합니다. `session-peer --version`이 `1.0.0rc3`을 보고하는지, 비어 있는 홈 디렉터리에서 `session-peer list --output-format
   json` works in an empty home, and relay/MCP extras pass `pip check` 및 help 스모크 테스트를 통과하는지 확인하십시오.
7. 필수 검사가 통과된 후에만 병합합니다. `main`을 가져와서(fetch) 정확한 커밋을 기록하고, 해당 커밋에서 버전과 의도된 변경 사항을 확인하십시오.

## 드래프트 준비

릴리스 준비 PR이 병합된 후에만 드래프트를 생성하십시오. 스쿼시 또는 머지 커밋은 릴리스 커밋을 변경합니다.

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v1.0.0-rc.3 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.0-rc.3" \
  --notes-file docs/releases/v1.0.0-rc.3.md \
  --draft --prerelease --latest=false
```

태그, 타깃, 제목, 릴리스 노트, 드래프트 상태 및 시험판(prerelease) 상태를 확인하십시오. 게시된 기존 태그를 이동하지 마십시오. 드래프트 생성이 게시를 승인하는 것은 아닙니다.

## 게시

게시 직전에 최종 사용자 승인을 받으십시오. 게시하면 GitHub 릴리스가 공개되고 PyPI 업로드가 트리거됩니다:

```bash
gh release edit v1.0.0-rc.3 \
  --repo abruption/session-peer \
  --draft=false --prerelease --latest=false
```

워크플로가 실패하더라도 두 번째 릴리스를 생성하거나 수정된 아티팩트로 재시도하지 마십시오. 실패한 실행을 보존하고 원인을 진단하십시오. PyPI 버전은 변경할 수 없습니다(immutable).

## 게시 검증

1. 예상되는 태그 및 커밋에 대해 `publish.yml`이 성공했는지 확인하십시오.
2. PyPI가 정확히 `session-peer==1.0.0rc3`을 노출하는지 확인하십시오. wheel과 sdist를 다운로드하여 워크플로 아티팩트와 해시를 비교하고 내용을 다시 검사하십시오.
3. 깨끗한 환경에 정확한 PyPI 시험판을 설치하고 버전, 클린 홈 list, 릴레이 엑스트라 및 MCP 스모크 검사를 반복하십시오.
4. GitHub가 해당 릴리스를 prerelease로 표시하고 latest로 표시하지 않았는지 확인하십시오. 안정 버전 `releases/latest` 엔드포인트 및 일반 업데이트 알림은 v0.9.2을 계속 가리켜야 합니다.
5. 호스팅된 릴레이는 별도로 검증하십시오. 패키지 게시가 서비스 정상 상태, OAuth 정책 또는 에이전트 인정을 증명하지는 않습니다.
6. GitHub, PyPI 및 클린 설치 증거가 기록된 후에만 v1.0.0-rc.3 마일스톤을 닫으십시오.

패키지 관리자로 설치한 환경은 자체 패키지 관리자로 업그레이드합니다. 독립형 안정 설치는 `session-peer update`를 계속 사용하고, 릴리스 후보 테스터는 정확한 패키지 버전을 사용합니다. 제출이 소비나 인정을 증명하는 것은 절대 아닙니다.
