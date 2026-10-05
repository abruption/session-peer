# 发布session-peer

1.0.3是继1.0.2之后的稳定版安全与稳定性维护发布。区分准备、不可变GitHub发布、人工PyPI环境审核与发布后验证。受保护的main要求经过审核、保持最新的PR及汇总发布门禁，包括Python平台矩阵、文档、shell、包/单文件/MCP/Relay/Control、集成测试与Python/Node依赖审计。

## 历史证据与当前边界

五主机v1.0.0 RC4 rc4-rerun-02测试运行14,436.65秒：complete记录、公开健康241/241、探测147/147、提交21/21及Relay重启恢复3.182秒。独立ACK为20/21。T120 Windows原生Claude因TUI关闭未确认原始ACK，另一次单独测试收到准确ACK。所有者在#164接受此例外。保留20/21；历史证据不验证v1.0.3。#161的外部停滞根因仍未确认。

Python/PyPI版本为1.0.3，标签和GitHub发布为v1.0.3。设为稳定版及Latest。插件版本独立。核心需要Python 3.9+、MCP需要3.10+、Relay接收端/服务端需要Unix或WSL与Python 3.11+。服务接收端需要服务PATH中的Codex或运营人员拥有的codexBin绑定。包发布不能证明托管补救部署、设备群安装、生产重启、实时OAuth健康或ACK。未知结果不能授权自动重发。

## 源码与配置门禁

1. 将v1.0.3变更与1.0.2及四种语言的说明对照。整合五项公告修复后才能公开详情。CVE分配不是发布前提。确认包/生成版本、四份README版本和归档说明；冻结cc_peer.py并从发行包排除。排除凭据、密钥、数据库、重放状态、浏览器配置、本地证据及聊天。
2. 运行完整本地测试和PR门禁。合并后要求整合后的公开main准确提交通过CI；私有公告分支检查不能替代该公开发布门禁。验证干净wheel/sdist安装、隔离环境安装import、准确CLI版本、初始化home的JSON list、extras及pip check。显式空Codex home必须以state_db_missing安全失败。不要发送实时消息。
3. 确认PyPI尚无1.0.3文件。检查GitHub Immutable Releases及v*标签规则：允许创建，禁止无绕过的标签修改/删除。所有者于2026-10-03启用 (规则24408525)。2026-10-05验证确认Immutable Releases已启用、规则24408525有效，并要求严格main发布门禁。历史v1.0.2为非不可变且无资产，不是已验证单文件发布；重新检查当前配置。
4. 确认Trusted Publisher将session-peer映射到abruption/session-peer、publish.yml和pypi。2026-10-05通过已登录PyPI浏览器确认所有者/仓库abruption/session-peer、工作流publish.yml及环境pypi映射。同日GitHub配置检查确认要求审核者abruption、允许自审及v*标签；管理员绕过仍启用。重新检查配置，使用正常人工审核，不得静默绕过。

## 准备不可变草稿

准备PR合并后记录准确main提交并在其上创建轻量标签。不得移动已有标签。由仓库所有者在受保护main的准确提交上执行准备；调度与验证间main推进将安全失败。

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

prepare-release.yml验证源码/ref/版本/祖先关系，执行两次可复现构建、归档检查、隔离安装测试与依赖审计。向空草稿证明并附加恰好七项资产：wheel、sdist、session_peer.py、install.sh、SKILL.md、SHA256SUMS及release-provenance.json。manifest覆盖五项payload；签名来源证明也覆盖manifest及证据。不覆盖已有资产。发布前审核成功准备运行、准确提交、七个文件、哈希及证明。附加草稿不等于发布。

## 发布锁定的GitHub版本

只有获得所有者对该版本的明确授权才发布。已有完成此次发布的指令满足流程批准要求，不要仅因本手册再次要求确认。它不替代所需的人工pypi环境审核。发布锁定标签与资产，并启动publish.yml。

```bash
gh release edit v1.0.3 --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

publish.yml要求仓库所有者，验证准确标签/源码/main祖先关系，下载已锁定不可变资产并验证认证来源证明与manifest。不会重新构建或增加资产。PyPI任务前必须再次通过安装检查与当前依赖审计。准备时审计成功不是当前审计证据。

## 人工审核待处理的PyPI部署

1. 上传前观察准确Actions运行正等待pypi审核。记录运行URL/ID与尝试次数、标签、提交、SHA256SUMS、release-provenance.json和待处理时间。源码测试和配置不能证明暂停；下一次发布的实际观察仍是#235验收检查。
2. 必需的人工审核者检查候选证据及当前Trusted Publisher/环境配置。在Review deployments选择pypi，仅获授权时明确选择Approve and deploy。GitHub发布授权不替代此审核。部署进入待处理状态时请求所需人工审核，并保留环境门禁。
3. 拒绝上传时选择pypi，说明原因并选择Reject。若预期暂停或控件缺失，在上传前停止并取消运行。保留被拒绝/取消运行并解决原因，不得移动标签或重复使用版本以规避拒绝。
4. 记录审核者、决定、评论、时间及结果，保留上传和验证证据。拒绝既不是成功发布，也不是成功验证批准暂停。管理员绕过属例外，需另获所有者明确授权，记录原因、操作者、时间、运行、标签和提交。

## 验证发布或恢复

验证publish.yml及其PyPI验证对准确标签/提交成功。下载两个PyPI文件，将准确文件列表和哈希与锁定候选/来源证明比较，并在新环境分别安装。再次检查隔离版本、初始化home的JSON list、extras及pip check。确认稳定版/Latest及正常更新选择v1.0.3。关闭里程碑前记录证据；保留#161监控。

GitHub和PyPI发布是独立不可逆步骤。GitHub发布后审计失败可能留下没有PyPI文件的锁定版本；保留两次运行和准确资产。不得绕过审计、用修改资产重新上传、跳过已有文件或重用版本。部分1.0.3上传或不匹配会停止推广。诊断首个失败门禁，通过已审核变更和新版本 (通常1.0.4) 前进修复。yank不会允许重用。

## 已验证单文件安装

较新的已认证GitHub CLI必须支持gh attestation verify及签名工作流、源码ref/digest、OIDC issuer和托管runner策略。测试基线为2.102.0；支持所有标志的最早版本未确定。仓库/证明读取权限足够，无需发布权限。[GitHub CLI验证源码](https://github.com/cli/cli/blob/v2.102.0/pkg/cmd/attestation/verify/verify.go)记录策略标志。本地fixture验证策略/顺序/错误行为，不证明真实签名接受。

安装器默认使用已验证Latest不可变资产。--local-source明确信任邻近源码；--main选择未经验证的开发源码。缺少证明或旧的未签名发布会安全失败；无法验证时使用pipx/uv/pip。执行前认证install.sh：

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

下载上限为单文件8 MiB、支持文件256 KiB、元数据1 MiB。认证manifest/来源证明、准确标签/版本与暂存--version检查在替换前完成。发送端在SSH部署前验证，离线目标仅需Python。验证失败保留已有文件。SSH允许列表、既有配对绑定审核及Control登录迁移见发布说明。
