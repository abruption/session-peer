# session-peer 릴리스

GitHub 릴리스 게시가 `.github/workflows/publish.yml`을 실행해 해당 태그의 wheel과 sdist를 빌드하고 PyPI Trusted Publishing으로 업로드합니다. 드래프트는 게시되지 않습니다. 준비·최종 승인·게시·검증을 분리하십시오. 보호된 `main`에는 최신 PR과 전체 Python 플랫폼 매트릭스, 문서·셸·패키지 설치·MCP·Relay·control·통합 테스트 및 의존성 감사가 포함된 `release gate`가 필요합니다. 라이브 OAuth, 에이전트 ACK, 운영 Relay 상태는 별도의 운영 증거입니다.

## v1.0.0 근거와 v1.0.1 유지보수 조건

검토된 RC4 런타임은 5개 호스트의 `rc4-rerun-02`에서 14,436.65초 `complete`, 공개 health 241/241, probe 147/147, 제출 21/21, Relay 재시작 복구 3.182초를 기록했습니다. 독립 ACK는 20/21입니다. 원래 T120 Windows native Claude ACK는 TUI 종료로 미확인이며, 같은 경로의 별도 단발 시험에서는 정확한 ACK를 받았습니다. 사용자는 #164에서 이 운영 예외를 명시적으로 수락했습니다. 원래 결과를 21/21로 바꾸지 마십시오. #161의 외부 정체 위치는 미확정이며 완화가 근본 원인 해결을 뜻하지 않습니다. 이는 v1.0.0의 역사적 근거이며 v1.0.1 변경의 검증 결과는 아닙니다.

Python/PyPI 버전은 `1.0.1`, Git 태그와 GitHub 릴리스는 `v1.0.1`입니다. 시험판으로 표시하지 말고 Latest로 표시하십시오. 일반 업그레이드와 독립형 업데이트 알림은 v1.0.0 대신 v1.0.1을 선택할 수 있습니다. 플러그인 버전은 독립적으로 유지합니다. 코어는 Python 3.9+에서 의존성이 없고 MCP는 3.10+, Relay 수신기/서버는 Unix 또는 WSL의 3.11+가 필요합니다. 패키지 발행은 호스팅 Relay/OAuth 가용성을 보장하지 않습니다. 서비스로 실행하는 macOS·Linux 수신기의 PATH에 대상 TUI의 `codex` 실행 파일 디렉터리를 넣거나 운영자가 관리하는 절대 `codexBin` 경로를 설정하십시오. Relay 로그인은 만료되며 재승인이 필요할 수 있습니다. #161은 근본 원인이 미확정인 채 열어 둡니다.

레거시 URL용 루트 `cc_peer.py`는 보존하되 wheel과 sdist에서 제외합니다. 네 언어 README, 보안 정책, 안정판 노트, Relay 문서와 선택형 런타임은 포함합니다. 자격증명, 기기 키, 인증 DB, replay 상태, 브라우저 프로필, 로컬 증거와 대화는 제외합니다.

## Trusted Publisher

PyPI 프로젝트 `session-peer`는 GitHub `abruption/session-peer`의 `publish.yml`, 환경 `pypi`에 연결됩니다. 장기 PyPI 비밀은 저장소에 두지 않습니다. 이전 성공만으로 현재 소유자 측 설정을 확정하지 말고 게시 전 확인하십시오.

## 준비 및 검증

1. v1.0.1 마일스톤의 완료된 수정들을 확인하고 #161은 근본 원인 미확정인 모니터링으로 열어 둡니다. v1.0.0 대비 런타임 차이와 v1.0.1 노트를 검토합니다. `release/0.9.x`를 `main`에 병합하지 마십시오.
2. `session_peer.__version__ == "1.0.1"`, 생성된 `session_peer.py` 일치, README 네 언어의 설치 명령과 sdist의 안정판 노트 네 언어를 확인합니다. 전체 로컬 테스트와 PR `release gate`, 병합 후 정확한 `main` CI를 통과해야 합니다.
3. 정확한 후보에서 `python3 -m build`로 wheel과 sdist를 만들고 내용을 검사합니다. 둘을 깨끗한 환경에 각각 설치하여 `session-peer --version`, 초기화된 에이전트 홈의 JSON `list`, `pip check`, Relay/MCP 확장과 help를 검사합니다. 명시적으로 빈 Codex 홈은 `state_db_missing`으로 실패해야 하며 설치 실패가 아닙니다. 라이브 모델 메시지는 이 게이트에 포함하지 않습니다.
4. CI 통과 후에만 병합하고 `main`의 정확한 커밋·버전·노트를 재확인합니다. PyPI에 `1.0.1` 파일이 아직 없는지 확인합니다.

## 드래프트와 게시

준비 PR 병합 후 아래 드래프트를 만듭니다. squash/merge 커밋은 릴리스 커밋을 바꿉니다. 게시된 태그를 이동하지 마십시오.

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v1.0.1 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.1" \
  --notes-file docs/releases/v1.0.1.md \
  --draft --latest
```

태그·대상·제목·노트·드래프트·안정판·Latest 의도를 확인합니다. 드래프트는 게시 승인이 아닙니다.

## 게시

**게시 직전에 사용자 최종 승인을 받아야 합니다.** 게시 명령:

```bash
gh release edit v1.0.1 \
  --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

워크플로는 태그/버전/보호된 main 일치, 재현 가능한 wheel·sdist, 아카이브·설치·감사, SHA256SUMS와 provenance를 확인한 뒤 OIDC로 업로드해야 합니다. 기존 PyPI 파일은 건너뛰지 않고 오류로 처리합니다. 실패 뒤 아티팩트를 바꿔 재업로드하지 마십시오. `1.0.1` 부분 게시나 해시 불일치가 생기면 승격을 중단하고 실패 증거를 보존한 뒤 새 버전(일반적으로 `1.0.2`)으로 검토된 수정 발행을 합니다. yank도 버전 재사용을 허용하지 않습니다.

## 게시 검증

1. 정확한 태그·커밋의 `publish.yml` 성공을 확인합니다. PyPI의 wheel·sdist를 받아 워크플로 후보와 해시 및 provenance를 비교하고 각각 새 환경에 설치합니다.
2. 버전, 초기화된 에이전트 홈의 JSON `list`, Relay/MCP 확장, `pip check`, GitHub 안정판/Latest, 일반 업그레이드·업데이트 선택을 확인합니다. 호스팅 Relay는 별도로 검사하며 queued는 ACK가 아닙니다.
3. 증거 기록 뒤 #161을 명시적으로 이월하거나 해결한 경우에만 v1.0.1 마일스톤을 닫습니다. 전체 기기 설치나 운영 서비스 재시작은 별도 운영 결정입니다.
