# session-peer 릴리스

1.1.0은 2026-10-09에 준비한 미발행 후보이며 현재 공개 안정판은 1.0.4입니다. 준비만 승인된 경우에는 태그 생성, 초안 작성, 워크플로 실행 또는 공개 단계로 넘어가지 않습니다. 이 릴리스를 완료하라는 명시적 지시는 해당 공개 단계를 승인하지만, 사람이 수행해야 하는 필수 PyPI 환경 검토나 운영 배포까지 승인하는 것은 아닙니다. 릴리스 준비, 불변 GitHub 릴리스 공개, 사람이 수행하는 필수 PyPI 환경 검토, 공개 후 검증은 각각 별도 단계입니다. 보호된 main에 반영하려면 검토를 마치고 최신 main을 반영한 PR과, Python 플랫폼 매트릭스·문서·셸·패키지/독립 실행 파일/MCP/Relay/Control 테스트·통합 테스트·Python/Node 의존성 감사를 포함한 릴리스 게이트가 필요합니다.

## 과거 증거와 현재 경계

다섯 호스트에서 진행한 v1.0.0 RC4 rc4-rerun-02 캠페인은 14,436.65초 동안 실행됐습니다. 상태는 complete(완료)였고, 공개 health(서비스 상태) 점검 241/241, 프로브(연결 점검) 147/147, 제출 21/21, Relay 재시작 후 복구 시간 3.182초를 기록했습니다. 독립적으로 확인한 ACK(수신 확인)는 20/21입니다. T120 Windows 네이티브 Claude의 원래 ACK는 TUI가 종료되어 확인되지 않았지만, 별도의 단발 확인에서 정확한 ACK를 받았습니다. 소유자는 #164에서 이 예외를 수락했습니다. 집계는 20/21로 유지하십시오. 이 과거 증거는 v1.0.4 또는 v1.1.0을 검증하지 않습니다. #161은 계속 열려 있으며 외부 경로 정체의 근본 원인은 확인되지 않았습니다.

Python/PyPI 후보 버전은 1.1.0이며 예정된 태그와 GitHub 릴리스는 v1.1.0입니다. 준비 작업에서는 둘 다 생성하지 않습니다. 공개 승인이 끝난 뒤에만 안정판·Latest(최신 릴리스)로 설정합니다. 플러그인 버전은 별도로 관리합니다. 코어에는 Python 3.9 이상, MCP에는 Python 3.10 이상이 필요합니다. Relay 수신기와 서버에는 Unix 또는 WSL 환경 및 Python 3.11 이상이 필요합니다. 서비스로 실행되는 수신기는 서비스 PATH에서 Codex를 찾을 수 있거나 운영자가 관리하는 codexBin 바인딩이 있어야 합니다. 패키지를 공개해도 호스팅 서비스에 대응 조치가 적용되거나, 전체 기기에 설치되거나, 운영 환경이 재시작되거나, 실시간 OAuth 상태가 확인되거나, 에이전트 ACK가 수신됐다는 뜻은 아닙니다. 결과가 불확실하면 자동으로 재전송하지 않습니다.

## 소스와 설정 게이트

1. v1.1.0 후보를 공개판 1.0.4 및 네 언어 릴리스 노트와 대조합니다. PR #261과 기능 PR #283–#289은 병합됐으며 검토한 후보 PR #290은 정상 보호 절차에 따라 준비 PR보다 먼저 병합해야 합니다. 준비 브랜치를 통합 main에 맞추고 두 parser 보호와 고정 계약의 바이트를 보존하며, #180/#181/#268 미지원 조건과 별도 스킬 PR #30을 재확인합니다. 공개된 v1.0.3 보안 기록과 스킬 0.3.2/최소 0.9.1/전체 1.0.1을 유지합니다. 패키지·생성 버전, 네 언어 README의 공개판/후보 구분과 아카이브를 확인합니다. 레거시 cc_peer.py는 동결하고 배포에서 제외합니다. 자격정보·키·DB·재전송 방지 상태·브라우저 프로필·로컬 증거·채팅도 제외합니다.
2. 전체 로컬 테스트와 PR(풀 리퀘스트) 릴리스 게이트를 실행합니다. 병합 후 공개 main에 통합된 정확한 커밋에서 CI(지속적 통합)가 성공해야 합니다. 비공개 보안 포크의 검사는 공개 릴리스 게이트를 대체하지 않습니다. 깨끗한 환경에서 wheel/sdist를 설치하고, 격리 환경의 설치 패키지를 import하며, 정확한 CLI 버전, 초기화된 홈에서의 JSON list, 선택 의존성(extras)과 pip check를 검증합니다. Codex 홈을 명시적으로 비워 둔 경우에는 state_db_missing으로 차단 상태에서 실패해야 합니다. 이 게이트에서는 실제 메시지를 전송하지 않습니다.
3. PyPI에 1.1.0 파일이 없는지 확인합니다. 2026-10-07 준비 확인 당시 과거 1.0.4 버전의 JSON 응답은 HTTP 404였습니다. GitHub 불변 릴리스 기능과 v* 태그 규칙을 확인합니다. 태그 생성은 허용되고, 수정·삭제는 우회 없이 차단돼야 합니다. 소유자는 2026-10-03에 이를 활성화했고(규칙 24408525), 2026-10-05 확인에서는 엄격한 main 릴리스 게이트를 확인했습니다. 2026-10-07 GitHub API 확인에서도 불변 릴리스 기능과 규칙 24408525가 활성 상태이고, refs/tags/v*에 적용되며, 우회 없이 수정·삭제를 차단하는 것을 재확인했습니다. 과거 v1.0.2는 불변 릴리스가 아니었고 자산도 없어 검증된 독립형 설치 릴리스가 아닙니다. 공개 전에 현재 설정을 다시 확인합니다.
4. Trusted Publisher(신뢰된 게시자)가 session-peer를 abruption/session-peer, publish.yml, pypi에 연결하는지 확인합니다. 2026-10-05 로그인된 PyPI 브라우저에서 해당 연결을 확인했습니다. 이는 과거 증거이며 새 PyPI 브라우저 검증은 아닙니다. 2026-10-07 GitHub API 확인에서는 필수 검토자가 `abruption`이고, 자기 검토가 허용되며 (`prevent_self_review: false`), `v*` 태그가 허용되는 것을 재확인했습니다. 2026-10-05 확인 당시에는 관리자 우회도 활성화돼 있었습니다 (`can_admins_bypass: true`). 이 과거 관찰을 현재 우회 정책의 증거로 간주하지 않습니다. 소유자의 이전 [2026-09-29 연결 확인](https://github.com/abruption/session-peer/issues/235#issuecomment-5882178667)도 과거 증거입니다. 설정을 다시 확인하고 정해진 사람 검토 절차를 따르며, 이 절차를 숨긴 채 우회하지 않습니다.

## 변경 불가능한 초안 준비

준비 PR 병합 후 정확한 main 커밋을 기록하고 그 커밋에 lightweight(주석 없는) 태그를 만듭니다. 기존 태그를 옮기지 않습니다. 저장소 소유자가 보호된 main의 해당 커밋에서 준비 작업을 실행합니다. 실행 요청과 검증 사이에 main이 바뀌면 작업은 차단 상태에서 실패합니다.

```bash
git fetch origin main --tags
release_tag=v1.1.0
release_commit=$(git rev-parse origin/main)
git tag "$release_tag" "$release_commit"
git push origin "$release_tag"
gh release create "$release_tag" --repo abruption/session-peer \
  --target "$release_commit" --title "session-peer $release_tag" \
  --notes-file "docs/releases/$release_tag.md" --draft --latest
gh workflow run prepare-release.yml --repo abruption/session-peer \
  --ref main -f tag="$release_tag"
```

prepare-release.yml은 소스/ref/버전/커밋 계보를 확인하고, 재현 가능한 빌드 두 번과 아카이브 검사, 격리 설치 테스트 및 감사를 수행합니다. 비어 있는 초안에 wheel, sdist, session_peer.py, install.sh, SKILL.md, SHA256SUMS, release-provenance.json 등 정확히 일곱 개의 릴리스 파일을 증명과 함께 첨부합니다. manifest(릴리스 파일 목록)에는 배포 파일 다섯 개가 포함되며, 서명된 출처 증명에는 manifest와 검증 자료도 포함됩니다. 기존 파일은 덮어쓰지 않습니다. 공개 전에 준비 실행의 성공 여부, 정확한 커밋, 일곱 파일, 해시와 증명을 검토합니다. 초안에 파일을 첨부해도 공개된 것은 아닙니다.

## 불변 GitHub 릴리스 공개

해당 버전에 대해 소유자의 명시적 승인이 있을 때만 공개합니다. 이미 릴리스 완료를 지시했다면 이 런북의 승인 요건은 충족되므로, 런북에 적힌 절차만을 이유로 두 번째 확인을 요구하지 않습니다. 다만 이 지시는 필수적인 사람의 pypi 환경 검토를 승인하거나 대체하지 않습니다. 공개하면 태그와 릴리스 파일이 고정되고 publish.yml이 시작됩니다.

```bash
gh release edit v1.1.0 --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

publish.yml은 소유자, 정확한 태그/소스/main 계보를 확인한 뒤 고정된 불변 릴리스 파일을 내려받고 인증된 출처 증명과 manifest를 검증합니다. 다시 빌드하거나 파일을 추가하지 않습니다. PyPI 작업 전에 설치 검사와 최신 의존성 감사가 다시 통과해야 합니다. 준비 단계에서 감사가 성공했더라도 현재의 감사 증거로 간주하지 않습니다.

## PyPI 배포 승인 대기 중 사람의 검토

1. 업로드 전에 해당 Actions 실행이 pypi 환경의 승인 대기 상태인지 확인합니다. 실행 URL/ID와 시도 번호, 태그, 커밋, SHA256SUMS, release-provenance.json, 대기 시각을 기록합니다. 소스 테스트와 설정만으로는 승인 대기 상태를 입증할 수 없습니다. 다음 릴리스에서 실제 대기를 확인하는 것이 #235의 수락 검사입니다.
2. 필수 검토자는 후보 증거와 현재 Trusted Publisher/환경 설정을 확인합니다. **Review deployments**에서 **pypi**를 선택하고, 승인된 경우에만 **Approve and deploy**를 명시적으로 선택합니다. GitHub 릴리스 공개 승인은 이 검토를 대신하지 않습니다. 배포가 대기 상태가 되면 필수적인 사람 검토를 요청하고 환경 게이트를 유지합니다.
3. 업로드를 거부하려면 **pypi**를 선택하고 사유를 적은 뒤 **Reject**를 선택합니다. 예상한 대기 상태나 제어가 없다면 업로드 전에 중단하고 취소합니다. 거부/취소된 실행을 보존하고 원인을 해결합니다. 거부를 피하려고 태그를 옮기거나 버전을 재사용하지 않습니다.
4. 검토자, 결정, 의견, 시각과 결과를 기록하고 업로드·검증 증거를 보존합니다. 거부는 공개 성공도, 승인 대기 검증 성공도 아닙니다. 관리자 우회는 예외적인 경우에만 별도의 명시적 소유자 승인을 받아야 하며, 사유·수행자·시각·실행·태그·커밋을 기록해야 합니다.

## 공개 검증 또는 복구

정확한 태그/커밋에 대해 publish.yml과 PyPI 검증이 성공했는지 확인합니다. PyPI 파일 두 개를 내려받아 파일 목록과 해시가 고정된 후보/출처 증명과 일치하는지 확인하고, 깨끗한 환경에서 각각 설치합니다. 격리 환경에서 버전, 초기화된 홈의 JSON list, extras와 pip check를 다시 확인합니다. 안정판/Latest 설정과 일반 업데이트가 v1.1.0를 선택하는지도 확인합니다. 마일스톤을 닫기 전에 증거를 기록하고, #161은 모니터링 이슈로 계속 열어 둡니다.

GitHub와 PyPI 공개는 서로 별개이며 되돌릴 수 없습니다. GitHub 릴리스 공개 후 감사에 실패하면 PyPI 파일이 없는 고정 릴리스가 남을 수 있습니다. 두 실행 기록과 해당 릴리스 파일을 보존합니다. 감사를 우회하거나, 수정된 파일로 업로드를 다시 실행하거나, 이미 존재하는 파일을 건너뛰거나, 버전을 재사용하지 않습니다. 1.1.0 파일 일부만 업로드되거나 파일이 일치하지 않으면 승격을 중단합니다. 처음 실패한 게이트의 원인을 진단하고 검토된 수정 사항을 새 버전(일반적으로 1.1.1)에 반영해 진행합니다. PyPI에서 yank(일반 의존성 해결에서 해당 버전을 제외하는 표시)해도 버전을 재사용할 수 없습니다.

## 검증된 독립 실행 파일 설치

최신 인증된 GitHub CLI는 gh attestation verify와 서명자 워크플로, 소스 ref/digest, OIDC(OpenID Connect) 발급자, 호스팅 러너 정책을 지원해야 합니다. 테스트 기준 버전은 2.102.0이며 모든 플래그를 지원하는 최초 버전은 확인되지 않았습니다. 저장소와 증명을 읽을 권한이면 충분하며 공개 권한은 필요하지 않습니다. [GitHub CLI 검증 소스](https://github.com/cli/cli/blob/v2.102.0/pkg/cmd/attestation/verify/verify.go)에 정책 플래그가 정의되어 있습니다. 로컬 fixture(준비된 테스트 자료)는 정책·순서·오류 처리를 확인할 뿐 실제 서명 검증의 성공 여부를 입증하지 않습니다.

설치 스크립트는 검증된 Latest 불변 릴리스 파일을 기본으로 사용합니다. --local-source는 인접한 소스를 명시적으로 신뢰하며, --main은 검증되지 않은 개발 소스를 명시적으로 선택합니다. 증명이 없거나 과거의 미서명 릴리스이면 설치가 차단됩니다. 검증할 수 없다면 pipx/uv/pip을 사용하십시오. 실행 전에 install.sh를 인증하십시오:

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

다운로드 상한은 독립 실행 파일 8 MiB, 지원 파일 256 KiB, 메타데이터 1 MiB입니다. 인증된 manifest/출처 증명, 정확한 태그/버전, 스테이징된 파일의 --version 검사 후에 기존 파일을 교체합니다. SSH 배포 전에 송신자가 검증하므로 원격 대상에는 Python만 필요합니다. 검증에 실패하면 기존 파일은 그대로 유지됩니다. SSH 옵션 허용 목록, 기존 페어링 바인딩 검토, Control 로그인 세션 전환은 릴리스 노트를 확인하십시오.
