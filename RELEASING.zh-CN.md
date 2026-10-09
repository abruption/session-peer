# 发布session-peer

1.1.0是2026-10-09准备的未发布候选，当前已公开稳定版仍为1.0.4。 仅获得准备授权时，必须在创建标签、草稿、调度工作流或发布前停止。明确要求完成此版本发布，即表示授权执行这些发布步骤；但不能替代必需的人工PyPI环境审核或生产环境部署。请区分准备、不可变的GitHub发布、人工PyPI环境审核和发布后验证。受保护的main要求PR经过审核并与main保持最新，同时通过汇总发布门禁；门禁涵盖Python平台测试矩阵、文档、shell、包/单文件/MCP/Relay/Control、集成测试以及Python/Node依赖审计。

## 历史证据与当前边界

在5台主机上进行的v1.0.0 RC4 rc4-rerun-02测试持续了14,436.65秒。记录状态为complete，公开健康检查为241/241，探测为147/147，提交为21/21，Relay重启后的恢复时间为3.182秒。独立确认的ACK为20/21。在Windows原生Claude的T120测试中，TUI已关闭，因此无法确认原始ACK；之后另一次单独测试收到了准确的ACK。所有者在#164中接受了这一例外。请保留20/21这一结果；这段历史记录不能证明v1.0.4或v1.1.0已通过验证。#161仍未解决，外部停滞的根本原因也尚未确认。

Python/PyPI候选版本为1.1.0，计划标签与GitHub版本为v1.1.0；准备阶段不创建二者。只有在获得发布授权后，才能将其设为稳定版和Latest。插件版本独立管理。核心CLI需要Python 3.9+，MCP需要3.10+，Relay接收端/服务器需要Unix或WSL及Python 3.11+。由服务管理器启动的接收端需要在服务PATH中找到Codex，或使用由运维人员管理的codexBin绑定。软件包发布不能证明托管服务的修复已部署、已安装到所有设备、生产服务已重启、线上OAuth运行正常或代理已发送ACK。未知结果不能作为自动重发的依据。

## 源码与配置门禁

1. 对照已发布1.0.4与四语言说明审核v1.1.0候选。PR #261与功能PR #283–#289已合并；已审查候选PR #290须通过正常保护流程先于准备PR合并。将准备分支更新至集成main，保留两种parser保护与固定契约字节，并复查#180/#181/#268未支持条件和独立技能PR #30。保留已公开v1.0.3安全历史和技能0.3.2/最低0.9.1/完整1.0.1。检查软件包/生成版本、四语言README的公开版/候选区分与归档。冻结cc_peer.py并排除发布；同样排除凭据、密钥、DB、重放状态、浏览器配置、本地证据与聊天。
2. 运行完整的本地测试和PR发布门禁。合并后，必须确认合并后的公开main在准确提交上通过CI。私有安全公告修复分支上的检查不能替代公开发布门禁。验证在干净环境中安装wheel/sdist、在隔离环境中导入已安装的软件包、CLI版本准确、在已初始化主目录中执行JSON list、extras以及pip check。显式指定的空Codex主目录必须因state_db_missing而安全失败（fail closed）。执行此门禁期间不要提交真实消息。
3. 确认PyPI上尚无1.1.0文件。2026-10-07的准备检查中，历史1.0.4版本JSON返回了HTTP 404。检查GitHub Immutable Releases和v*标签规则：允许创建标签；禁止更新或删除标签，且不设置绕过权限。所有者于2026-10-03启用了该规则（规则编号24408525），2026-10-05的检查确认严格的main发布门禁。2026-10-07的GitHub API检查再次确认Immutable Releases已启用、规则24408525有效、适用于refs/tags/v*，并且禁止更新/删除且没有绕过权限。历史版本v1.0.2并非不可变，也没有发布资产，因此不是经过验证的单文件发布版本。发布前请重新检查当前设置。
4. 确认Trusted Publisher将session-peer映射到abruption/session-peer、publish.yml和pypi。2026-10-05通过已登录的PyPI浏览器确认过该映射；这属于历史证据，并非新的PyPI浏览器复核。2026-10-07的GitHub API检查再次确认必须由审核者`abruption`审核、允许自审 (`prevent_self_review: false`)，并允许`v*`标签。2026-10-05检查时，管理员绕过权限已启用 (`can_admins_bypass: true`)；不要将这项历史观察当作对当前绕过策略的确认。所有者此前的[2026-09-29映射检查](https://github.com/abruption/session-peer/issues/235#issuecomment-5882178667)同样属于历史证据。请重新检查设置并按正常流程进行人工审核，不得擅自绕过。

## 准备不可变草稿

准备PR合并后，记录准确的main提交，并在该提交上创建轻量标签。不要移动已有标签。由仓库所有者在受保护main的这一准确提交上执行准备；如果main在调度与验证之间出现新提交，流程将fail closed（安全侧停止）。

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

prepare-release.yml会验证源码/ref/版本/提交祖先关系，执行两次可复现构建、归档检查、隔离环境安装测试和依赖审计。它会向空草稿附加并证明恰好七个资产：wheel、sdist、session_peer.py、install.sh、SKILL.md、SHA256SUMS和release-provenance.json。manifest涵盖五个发布载荷（payload）；签名来源证明还涵盖manifest和证据。不会覆盖已有资产。发布前请检查成功的准备工作流、准确提交、七个文件、哈希和证明。将文件附加到草稿不等于发布。

## 发布锁定的GitHub版本

只有获得所有者对该版本的明确授权后才能发布。若已有明确指令要求完成此次发布，该指令已满足流程审批要求，不要仅因本手册再次要求确认。但这不能替代必需的人工pypi环境审核。发布会锁定标签和资产，并启动publish.yml。

```bash
gh release edit v1.1.0 --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

publish.yml要求仓库所有者，验证准确标签/源码/main祖先关系，下载已锁定不可变资产并验证认证来源证明与manifest。不会重新构建或增加资产。PyPI任务前必须再次通过安装检查与当前依赖审计。准备时审计成功不是当前审计证据。

## 对待处理的PyPI部署进行人工审核

1. 上传前确认准确的Actions运行正在等待pypi审核。记录运行URL/ID、尝试次数、标签、提交、SHA256SUMS、release-provenance.json和等待时间。源码测试和仓库设置都不能证明工作流确实暂停；下一次发布时实际观察暂停情况仍是#235的验收检查。
2. 必需的人工审核者检查候选证据以及当前Trusted Publisher/环境设置。在**Review deployments**中选择**pypi**，仅在获得授权时才明确选择**Approve and deploy**。GitHub发布授权不能替代此项审核。部署进入待处理状态后，应请求必需的人工审核，并保持环境门禁。
3. 如需拒绝上传，请选择**pypi**，说明原因并选择**Reject**。如果没有出现预期的暂停或控制选项，请在上传前停止并取消运行。保留被拒绝或取消的运行记录并查明原因；不得为规避拒绝而移动标签或重用版本。
4. 记录审核者、决定、评论、时间和结果，并保留上传与验证证据。拒绝不表示发布成功，也不表示已成功验证审批门禁按预期暂停。管理员绕过属于例外，必须另行获得所有者的明确授权，并记录原因、操作者、时间、运行、标签和提交。

## 验证发布或恢复

确认publish.yml及PyPI验证在准确的标签/提交上成功。下载PyPI上的两个文件，比较文件清单及哈希与锁定候选/来源证明，并分别在干净环境中安装。再次检查隔离环境中的版本、已初始化主目录上的JSON list、extras和pip check。确认该版本已设为稳定版/Latest，且常规更新会选择v1.1.0。关闭里程碑前记录证据；将#161保留为监控事项。

GitHub发布和PyPI发布是两个彼此独立且不可逆的步骤。GitHub发布后若审计失败，可能留下一个已锁定但没有PyPI文件的版本；请保留两次运行记录和准确的资产。不得绕过审计、修改资产后重新上传、跳过已存在的文件或重用版本。若1.1.0只上传了部分文件或文件不匹配，应停止发布升级。诊断第一个失败的门禁，并通过经过审核的变更和新版本（通常为1.1.1）进行前向修复（fix forward）。撤回（yank）也不能让版本重新用于发布。

## 已验证单文件安装

较新且已登录的GitHub CLI必须支持gh attestation verify，以及签名工作流、源码ref/digest、OIDC issuer和GitHub托管runner策略。测试基线为2.102.0；尚未确定最早支持全部标志的版本。拥有仓库/证明的读取权限即可，无需发布权限。[GitHub CLI验证源码](https://github.com/cli/cli/blob/v2.102.0/pkg/cmd/attestation/verify/verify.go)列出了策略标志。本地fixture验证策略、顺序和错误处理，不代表真实签名已通过验证。

安装器默认使用已验证的Latest不可变资产。--local-source表示明确选择信任相邻源码；--main选择未经验证的开发源码。缺少证明或遇到旧的未签名发布时，安装器会fail closed（安全侧停止）；无法完成验证时请使用pipx/uv/pip。执行前请验证install.sh：

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

下载上限为单文件8 MiB、辅助文件256 KiB、元数据1 MiB。替换文件前会验证认证过的manifest/来源证明、准确的标签/版本，以及暂存文件的--version。发送端会在SSH部署前完成验证；离线目标只需要Python。验证失败时不会改动已有文件。SSH选项允许列表、既有配对绑定检查及Control登录迁移请参阅发布说明。
