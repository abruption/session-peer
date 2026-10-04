# session-peer 릴리스

1.0.3은 1.0.2 이후의 안정판 보안·안정성 유지보수 릴리스입니다. 준비, 변경 불가능한 GitHub 공개, 사람이 수행하는 PyPI 환경 검토, 공개 후 검증을 구분합니다. 보호된 main은 검토·최신화된 PR과 Python 플랫폼 매트릭스, 문서, 셸, 패키지/단독 파일/MCP/Relay/Control, 통합 테스트 및 Python/Node 의존성 감사를 포함한 릴리스 게이트를 요구합니다.

## 과거 증거와 현재 경계

다섯 호스트의 v1.0.0 RC4 rc4-rerun-02 캠페인은 14,436.65초 실행됐습니다. complete 기록, 공개 상태 241/241, 프로브 147/147, 제출 21/21, Relay 재시작 복구 3.182초였습니다. 독립 ACK는 20/21입니다. T120 Windows 네이티브 Claude의 원래 ACK는 TUI 종료로 미확인이며 별도의 단발 확인에서 정확한 ACK를 받았습니다. 소유자가 #164에서 예외를 수락했습니다. 20/21을 유지하세요. 과거 증거는 v1.0.3을 검증하지 않습니다. #161의 외부 지연 근본 원인은 미확인입니다.

Python/PyPI 버전은 1.0.3, 태그와 GitHub 릴리스는 v1.0.3입니다. 안정판·Latest로 설정합니다. 플러그인 버전은 독립적입니다. 코어는 Python 3.9+, MCP는 3.10+, Relay 수신기/서버는 Unix 또는 WSL과 Python 3.11+가 필요합니다. 서비스 수신기는 서비스 PATH의 Codex나 운영자 소유 codexBin 바인딩이 필요합니다. 패키지 공개는 호스팅 대응 배포, 기기군 설치, 운영 재시작, 실시간 OAuth 상태 또는 ACK를 증명하지 않습니다. 불확실한 결과는 자동 재전송을 허용하지 않습니다.

## 소스와 설정 게이트

1. v1.0.3 변경을 1.0.2 및 네 언어 릴리스 노트와 대조합니다. 다섯 보안 수정 통합 후에 내용을 공개합니다. CVE 배정은 공개 선행 조건이 아닙니다. 패키지/생성 버전, README 네 개의 버전과 아카이브 노트를 확인합니다. cc_peer.py는 동결 상태로 배포에서 제외하고 자격정보, 키, DB, 재생 상태, 브라우저 프로필, 로컬 증거와 채팅을 제외합니다.
2. 전체 로컬 테스트와 PR 릴리스 게이트를 실행합니다. 비공개 보안 포크에서는 CI가 실행되지 않으므로 병합 후 통합된 공개 main의 정확한 커밋에서 CI 성공을 요구합니다. 깨끗한 wheel/sdist 설치, 격리된 설치 import, 정확한 CLI 버전, 초기화된 홈의 JSON list, extras와 pip check를 검증합니다. 명시적 빈 Codex 홈은 state_db_missing으로 안전하게 실패해야 합니다. 실시간 메시지를 보내지 않습니다.
3. PyPI에 1.0.3 파일이 없는지 확인합니다. GitHub Immutable Releases와 v* 태그 규칙에서 생성만 허용하고 우회 없는 수정/삭제 차단을 확인합니다. 소유자가 2026-10-03에 활성화했습니다 (규칙 24408525). 과거 v1.0.2는 비불변·자산 없음 상태로 검증된 단독 파일 릴리스가 아닙니다. 현재 설정을 다시 확인합니다.
4. Trusted Publisher가 session-peer를 abruption/session-peer, publish.yml, pypi로 연결하는지 확인합니다. 소유자의 2026-09-29 확인은 새로운 PyPI UI 확인이 아닙니다. 2026-10-03에는 pypi가 검토자 abruption, 자기 검토 허용, v* 태그를 요구했고 관리자 우회는 활성화돼 있었습니다. 설정을 재확인하고 정상적인 사람의 검토를 거치며 조용히 우회하지 않습니다.

## 변경 불가능한 초안 준비

준비 PR 병합 후 정확한 main 커밋을 기록하고 해당 커밋에 lightweight 태그를 만듭니다. 기존 태그를 옮기지 않습니다. 저장소 소유자가 보호된 main의 해당 커밋에서 준비를 실행합니다. 실행 요청과 검증 사이에 main이 바뀌면 안전하게 실패합니다.

```bash
git fetch origin main --tags
release_tag=v1.0.3
release_commit=$(git rev-parse origin/main)
git tag "$release_tag" "$release_commit"
git push origin "$release_tag"
gh release create "$release_tag" --repo abruption/session-peer \
  --target "$release_commit" --title "session-peer $release_tag" \
  --notes-file "docs/releases/$release_tag.md" --draft --latest
gh workflow run prepare-release.yml --repo abruption/session-peer \
  --ref main -f tag="$release_tag"
```

prepare-release.yml이 소스/ref/버전/계보를 확인하고 두 번의 재현 빌드, 아카이브 검사, 격리 설치 테스트와 감사를 수행합니다. 빈 초안에 wheel, sdist, session_peer.py, install.sh, SKILL.md, SHA256SUMS, release-provenance.json의 정확히 일곱 자산을 증명·첨부합니다. manifest는 다섯 payload를, 서명 출처 증명은 manifest와 증거도 포함합니다. 기존 자산은 덮어쓰지 않습니다. 공개 전에 성공한 준비 실행, 커밋, 일곱 파일, 해시와 증명을 검토합니다. 초안 첨부는 공개가 아닙니다.

## 고정된 GitHub 릴리스 공개

해당 버전에 대한 소유자의 명시적 승인으로 공개합니다. 이미 릴리스 완료를 지시했다면 이 절차의 승인 요건을 충족하므로 문서만을 이유로 두 번째 확인을 요구하지 않습니다. 필수적인 사람의 pypi 환경 검토는 대체하지 않습니다. 공개는 태그와 자산을 고정하고 publish.yml을 시작합니다.

```bash
gh release edit v1.0.3 --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

publish.yml이 소유자, 정확한 태그/소스/main 계보를 확인하고 고정된 불변 자산을 내려받아 인증된 출처 증명과 manifest를 검증합니다. 재빌드·자산 추가는 하지 않습니다. PyPI 작업 전 설치 검사와 최신 의존성 감사가 다시 통과해야 합니다. 준비 시점 감사 성공은 현재 감사 증거가 아닙니다.

## 대기 중인 PyPI 배포의 사람 검토

1. 업로드 전에 정확한 Actions 실행이 pypi 검토 대기인지 관찰합니다. 실행 URL/ID와 시도 번호, 태그, 커밋, SHA256SUMS, release-provenance.json, 대기 시각을 기록합니다. 소스 테스트와 설정은 대기를 증명하지 못합니다. 다음 릴리스에서 관찰하는 것이 #235 수락 검사입니다.
2. 필수 사람 검토자가 후보 증거와 현재 Trusted Publisher/환경 설정을 확인합니다. Review deployments에서 pypi를 선택하고 승인된 경우에만 Approve and deploy를 명시적으로 선택합니다. GitHub 공개 승인은 이 검토를 대체하지 않습니다. 환경 게이트를 유지합니다.
3. 거부하려면 pypi를 선택하고 이유와 함께 Reject를 선택합니다. 예상된 대기나 제어가 없으면 업로드 전에 중단·취소합니다. 거부/취소 실행을 보존하고 원인을 해결합니다. 거부를 피하려고 태그를 이동하거나 버전을 재사용하지 않습니다.
4. 검토자, 결정, 의견, 시각과 결과를 기록하고 업로드·검증 증거를 보존합니다. 거부는 공개 성공이나 승인 대기 검증 성공이 아닙니다. 관리자 우회는 예외로 별도의 명시적 소유자 승인이 필요하며 이유, 수행자, 시각, 실행, 태그, 커밋을 기록해야 합니다.

## 공개 검증 또는 복구

정확한 태그/커밋에서 publish.yml과 PyPI 검증이 성공했는지 확인합니다. PyPI 파일 두 개를 내려받아 정확한 파일 목록과 해시를 고정 후보/출처 증명과 대조하고 깨끗한 환경에서 각각 설치합니다. 격리 버전, 초기화된 홈 JSON list, extras와 pip check를 재확인합니다. 안정판/Latest와 v1.0.3 업데이트 선택을 확인합니다. 마일스톤 종료 전 증거를 기록하고 #161은 모니터링으로 유지합니다.

GitHub와 PyPI 공개는 별개의 되돌릴 수 없는 단계입니다. GitHub 공개 후 감사 실패로 PyPI 파일 없는 고정 릴리스가 남을 수 있습니다. 두 실행과 정확한 자산을 보존합니다. 감사 우회, 수정 자산 업로드 재실행, 기존 파일 건너뛰기, 버전 재사용은 하지 않습니다. 일부 1.0.3 업로드나 불일치는 승격을 중단합니다. 첫 실패 게이트를 진단하고 검토된 수정과 새 버전 (통상 1.0.4)으로 전진합니다. yank도 재사용을 허용하지 않습니다.

## 검증된 단독 파일 설치

최신 인증된 GitHub CLI가 gh attestation verify와 서명 워크플로, 소스 ref/digest, OIDC issuer, 호스팅 러너 정책을 지원해야 합니다. 테스트 기준은 2.102.0이며 모든 플래그를 지원하는 최초 버전은 미확인입니다. 저장소/증명 읽기 권한이면 충분하고 공개 권한은 필요하지 않습니다. [GitHub CLI 검증 소스](https://github.com/cli/cli/blob/v2.102.0/pkg/cmd/attestation/verify/verify.go)에 정책 플래그가 있습니다. 로컬 fixture는 정책/순서/오류 동작을 확인하며 실제 서명 수락을 증명하지 않습니다.

설치기는 검증된 Latest 불변 자산을 기본으로 사용합니다. --local-source는 인접 소스를 명시적으로 신뢰하며 --main은 미검증 개발 소스를 선택합니다. 증명이 없거나 과거 미서명 릴리스이면 실패합니다. 검증이 불가능하면 pipx/uv/pip을 사용합니다. 실행 전에 install.sh를 인증합니다:

```bash
set -eu
repo=abruption/session-peer
tag=$(gh api "repos/$repo/releases/latest" --jq \
  'if .immutable == true and .draft == false and .prerelease == false then .tag_name else error("no immutable stable release") end')
commit=$(gh api "repos/$repo/git/ref/tags/$tag" --jq '.object | select(.type == "commit") | .sha')
case "$commit" in ????????* ) ;; * ) echo "expected a lightweight release tag" >&2; exit 1 ;; esac
staging=$(mktemp -d)
trap 'rm -f "$staging/install.sh"; rmdir "$staging"' EXIT
curl --fail --location --proto '=https' --proto-redir '=https' \
  --max-filesize 262144 --max-time 30 \
  "https://github.com/$repo/releases/download/$tag/install.sh" -o "$staging/install.sh"
gh attestation verify "$staging/install.sh" --repo "$repo" \
  --signer-workflow "$repo/.github/workflows/prepare-release.yml" \
  --source-ref refs/heads/main --source-digest "$commit" \
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  --deny-self-hosted-runners --format json
sh "$staging/install.sh"
```

다운로드 상한은 단독 파일 8 MiB, 지원 파일 256 KiB, 메타데이터 1 MiB입니다. 인증된 manifest/출처 증명, 정확한 태그/버전, 임시 --version 검사 후에 교체합니다. SSH 배포 전에 송신자가 검증하므로 오프라인 대상에는 Python만 필요합니다. 검증 실패 시 기존 파일을 유지합니다. SSH 허용 목록, 기존 페어링 바인딩 검토, Control 로그인 세션 이전은 릴리스 노트를 확인하세요.
