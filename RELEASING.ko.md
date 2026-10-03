# session-peer 릴리스

GitHub 릴리스 게시가 `.github/workflows/publish.yml`을 실행해 잠긴 자산을 검증하고 wheel과 sdist를 PyPI Trusted Publishing으로 업로드합니다. 드래프트는 게시되지 않습니다. 준비·최종 승인·게시·검증을 분리하십시오. 보호된 `main`에는 최신 PR과 전체 Python 플랫폼 매트릭스, 문서·셸·패키지 설치·MCP·Relay·control·통합 테스트 및 의존성 감사가 포함된 `release gate`가 필요합니다. 라이브 OAuth, 에이전트 ACK, 운영 Relay 상태는 별도의 운영 증거입니다.

## 변경 불가능한 릴리스 준비 (다음 승인된 릴리스)

2026-10-03 소유자가 GitHub Immutable Releases와 `refs/tags/v*` 대상 활성 태그 규칙
24408525를 설정했습니다. 우회 없이 태그 수정·삭제가 차단되며 생성은 허용됩니다.
기존 `v1.0.2`는 자산 없이 `immutable: false` 상태이며 검증된 독립형 릴리스가 아닙니다.
매 릴리스 전 저장소 설정을 다시 확인하십시오. 이 변경은 향후 게시를 준비하며 게시를 승인하지 않습니다.

소유자가 보호된 `main`의 정확한 태그 커밋에서 `prepare-release.yml`을 수동 실행합니다.
소스·참조·버전·조상 관계, 재현 빌드와 패키지 설치를 확인한 뒤 빈 안정판 드래프트에
wheel, sdist, `session_peer.py`, `install.sh`, `SKILL.md`, `SHA256SUMS`,
`release-provenance.json`의 일곱 자산을 증명하고 첨부합니다. 매니페스트는 다섯 페이로드를
포함하며 서명된 증명은 매니페스트와 근거도 포함합니다. 첨부는 게시하지 않습니다.
게시하면 파일이 잠기며 `publish.yml`은 재빌드나 자산 추가 없이 잠긴 패키지를 검증하고
PyPI에 업로드합니다. PyPI 워크플로·환경 연결을 유지하십시오.

```bash
# Set the next approved version; no tag/version is changed by this document.
release_tag=vX.Y.Z
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
git tag "$release_tag" "$release_commit"
git push origin "$release_tag"
gh release create "$release_tag" --repo abruption/session-peer \\
  --target "$release_commit" --title "session-peer $release_tag" \\
  --notes-file "docs/releases/$release_tag.md" --draft --latest
gh workflow run prepare-release.yml --repo abruption/session-peer \\
  --ref main -f tag="$release_tag"
# Review successful preparation, the seven draft assets, and their attestations.
# Obtain final approval before the separate publication command:
gh release edit "$release_tag" --repo abruption/session-peer \\
  --draft=false --prerelease=false --latest
```

검증된 독립형 설치·업데이트에는 서명 워크플로, 소스 참조·다이제스트 및 호스팅 러너
정책을 지원하는 최신 GitHub CLI의 `gh attestation verify`가 필요합니다.
설치기는 기본적으로 검증된 최신 불변 릴리스를 설치합니다. `--local-source`는 인접 소스를
명시적으로 신뢰하고 `--main`은 미검증 개발 코드에 명시적으로 동의합니다.
이전 릴리스나 증명 누락 시 자동 대체는 없습니다. 검증 릴리스 게시 전에는 pipx/uv/pip를
사용하십시오. 설치기를 실행하기 전에 인증하려면 다음을 사용하십시오(경량 버전 태그 필요).

```bash
set -eu
repo=abruption/session-peer
tag=$(gh api "repos/$repo/releases/latest" --jq \\
  'if .immutable == true and .draft == false and .prerelease == false then .tag_name else error("no immutable stable release") end')
commit=$(gh api "repos/$repo/git/ref/tags/$tag" --jq '.object | select(.type == "commit") | .sha')
case "$commit" in ????????* ) ;; * ) echo "expected a lightweight release tag" >&2; exit 1 ;; esac
staging=$(mktemp -d)
trap 'rm -f "$staging/install.sh"; rmdir "$staging"' EXIT
curl --fail --location --proto '=https' --proto-redir '=https' \\
  --max-filesize 262144 --max-time 30 \\
  "https://github.com/$repo/releases/download/$tag/install.sh" -o "$staging/install.sh"
gh attestation verify "$staging/install.sh" --repo "$repo" \\
  --signer-workflow "$repo/.github/workflows/prepare-release.yml" \\
  --source-ref refs/heads/main --source-digest "$commit" \\
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  --deny-self-hosted-runners --format json
sh "$staging/install.sh"
```

다운로드 제한은 독립형 8 MiB, 지원 파일 256 KiB, 메타데이터 1 MiB입니다.
교체 전에 인증된 매니페스트·증명, 정확한 태그·버전, 준비 파일의 성공적인 `--version`이
필요합니다. SSH 배포 전에 송신 측에서 검증하므로 오프라인 대상에는 Python만 필요합니다.
검증 실패 시 기존 파일은 유지됩니다. 아래 v1.0.2 절차는 역사적 기록이며
향후 릴리스에는 위 준비 워크플로를 사용하십시오.


## v1.0.0 근거와 v1.0.2 유지보수 조건

검토된 RC4 런타임은 5개 호스트의 `rc4-rerun-02`에서 14,436.65초 `complete`, 공개 health 241/241, probe 147/147, 제출 21/21, Relay 재시작 복구 3.182초를 기록했습니다. 독립 ACK는 20/21입니다. 원래 T120 Windows native Claude ACK는 TUI 종료로 미확인이며, 같은 경로의 별도 단발 시험에서는 정확한 ACK를 받았습니다. 사용자는 #164에서 이 운영 예외를 명시적으로 수락했습니다. 원래 결과를 21/21로 바꾸지 마십시오. #161의 외부 정체 위치는 미확정이며 완화가 근본 원인 해결을 뜻하지 않습니다. 이는 v1.0.0의 역사적 근거이며 v1.0.2 변경의 검증 결과는 아닙니다.

Python/PyPI 버전은 `1.0.2`, Git 태그와 GitHub 릴리스는 `v1.0.2`입니다. 시험판으로 표시하지 말고 Latest로 표시하십시오. 일반 업그레이드와 독립형 업데이트 알림은 v1.0.1 대신 v1.0.2을 선택할 수 있습니다. 플러그인 버전은 독립적으로 유지합니다. 코어는 Python 3.9+에서 의존성이 없고 MCP는 3.10+, Relay 수신기/서버는 Unix 또는 WSL의 3.11+가 필요합니다. 패키지 발행은 호스팅 Relay/OAuth 가용성을 보장하지 않습니다. 서비스로 실행하는 macOS·Linux 수신기의 PATH에 대상 TUI의 `codex` 실행 파일 디렉터리를 넣거나 운영자가 관리하는 절대 `codexBin` 경로를 설정하십시오. Relay 로그인은 만료되며 재승인이 필요할 수 있습니다. #161은 근본 원인이 미확정인 채 열어 둡니다.

레거시 URL용 루트 `cc_peer.py`는 보존하되 wheel과 sdist에서 제외합니다. 네 언어 README, 보안 정책, 안정판 노트, Relay 문서와 선택형 런타임은 포함합니다. 자격증명, 기기 키, 인증 DB, replay 상태, 브라우저 프로필, 로컬 증거와 대화는 제외합니다.

## Trusted Publisher

PyPI 프로젝트 `session-peer`는 GitHub `abruption/session-peer`의 `publish.yml`, 환경 `pypi`에 연결됩니다. 장기 PyPI 비밀은 저장소에 두지 않습니다. 이전 성공만으로 현재 소유자 측 설정을 확정하지 말고 게시 전 확인하십시오.

## 준비 및 검증

1. v1.0.2 마일스톤의 완료된 수정들을 확인하고 #161은 근본 원인 미확정인 모니터링으로 열어 둡니다. v1.0.1 대비 런타임 차이와 v1.0.2 노트를 검토합니다. `release/0.9.x`를 `main`에 병합하지 마십시오.
2. `session_peer.__version__ == "1.0.2"`, 생성된 `session_peer.py` 일치, README 네 언어의 설치 명령과 sdist의 안정판 노트 네 언어를 확인합니다. 전체 로컬 테스트와 PR `release gate`, 병합 후 정확한 `main` CI를 통과해야 합니다.
3. 정확한 후보에서 `python3 -m build`로 wheel과 sdist를 만들고 내용을 검사합니다. 둘을 깨끗한 환경에 각각 설치하여 `session-peer --version`, 초기화된 에이전트 홈의 JSON `list`, `pip check`, Relay/MCP 확장과 help를 검사합니다. 명시적으로 빈 Codex 홈은 `state_db_missing`으로 실패해야 하며 설치 실패가 아닙니다. 라이브 모델 메시지는 이 게이트에 포함하지 않습니다.
4. CI 통과 후에만 병합하고 `main`의 정확한 커밋·버전·노트를 재확인합니다. PyPI에 `1.0.2` 파일이 아직 없는지 확인합니다.

## 드래프트와 게시

준비 PR 병합 후 아래 드래프트를 만듭니다. squash/merge 커밋은 릴리스 커밋을 바꿉니다. 게시된 태그를 이동하지 마십시오.

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v1.0.2 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.2" \
  --notes-file docs/releases/v1.0.2.md \
  --draft --latest
```

태그·대상·제목·노트·드래프트·안정판·Latest 의도를 확인합니다. 드래프트는 게시 승인이 아닙니다.

## 게시

**게시 직전에 사용자 최종 승인을 받아야 합니다.** 게시 명령:

```bash
gh release edit v1.0.2 \
  --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

워크플로는 태그/버전/보호된 main 일치, 재현 가능한 wheel·sdist, 아카이브·설치·감사, SHA256SUMS와 provenance를 확인한 뒤 OIDC로 업로드해야 합니다. 기존 PyPI 파일은 건너뛰지 않고 오류로 처리합니다. 실패 뒤 아티팩트를 바꿔 재업로드하지 마십시오. `1.0.2` 부분 게시나 해시 불일치가 생기면 승격을 중단하고 실패 증거를 보존한 뒤 새 버전(일반적으로 `1.0.3`)으로 검토된 수정 발행을 합니다. yank도 버전 재사용을 허용하지 않습니다.

## 게시 검증

1. 정확한 태그·커밋의 `publish.yml` 성공을 확인합니다. PyPI의 wheel·sdist를 받아 워크플로 후보와 해시 및 provenance를 비교하고 각각 새 환경에 설치합니다.
2. 버전, 초기화된 에이전트 홈의 JSON `list`, Relay/MCP 확장, `pip check`, GitHub 안정판/Latest, 일반 업그레이드·업데이트 선택을 확인합니다. 호스팅 Relay는 별도로 검사하며 queued는 ACK가 아닙니다.
3. 발행 증거를 기록한 뒤 v1.0.2 마일스톤을 닫습니다. #161은 기존 모니터링 마일스톤에서 열어 두며 근본 원인이 해결됐다고 주장하지 않습니다. 전체 기기 설치나 운영 서비스 재시작은 별도 운영 결정입니다.
