# 发布 session-peer

公开 GitHub Release 会触发 `.github/workflows/publish.yml`，验证锁定资产，并将 wheel 和 sdist 通过 Trusted Publishing 上传 PyPI。草稿不会发布。请分开准备、最终批准、公开和验证。受保护的 `main` 需要最新 PR 以及覆盖各平台 Python、文档、Shell、软件包、MCP、Relay、control、集成测试和依赖审计的 `release gate`。实际 OAuth、代理 ACK 和生产 Relay 状态是独立的运维证据。

## 不可变发行准备（下一个获批发行）

2026-10-03所有者启用了GitHub Immutable Releases和针对 `refs/tags/v*` 的活动标签规则
24408525，禁止更新和删除且无绕过，允许创建。历史 `v1.0.2` 仍无资产且为
`immutable: false`，不是经过验证的独立发行。每次发行前重新检查设置。
本变更仅准备未来发布，不授权发布。

所有者在受保护 `main` 的准确标签提交上手动运行 `prepare-release.yml`。
检查源码、引用、版本、祖先、可重现构建和包安装后，在空稳定草稿中证明并附加七个资产：
wheel、sdist、`session_peer.py`、`install.sh`、`SKILL.md`、`SHA256SUMS` 和
`release-provenance.json`。清单覆盖五个载荷，签名证明也覆盖清单和证据。
附加不会发布。发布会锁定文件；`publish.yml` 验证并上传准确锁定的包到PyPI，
不重新构建或添加资产。保留PyPI工作流和环境映射。

```bash
# Set the next approved version; no tag/version is changed by this document.
release_tag=vX.Y.Z
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
git tag "$release_tag" "$release_commit"
git push origin "$release_tag"
gh release create "$release_tag" --repo abruption/session-peer \
  --target "$release_commit" --title "session-peer $release_tag" \
  --notes-file "docs/releases/$release_tag.md" --draft --latest
gh workflow run prepare-release.yml --repo abruption/session-peer \
  --ref main -f tag="$release_tag"
# Review successful preparation, the seven draft assets, and their attestations.
# Obtain final approval before the separate publication command:
gh release edit "$release_tag" --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

验证独立安装和更新需要近期GitHub CLI的 `gh attestation verify`，支持签名工作流、
源码引用和摘要以及托管运行器策略。默认安装经过验证的最新不可变发行。
`--local-source` 明确信任相邻源码，`--main` 明确选择未经验证的开发代码。
旧发行或缺少证明时不会自动回退。验证发行发布前请用pipx/uv/pip。
执行安装程序前使用以下命令认证（需要轻量版本标签）。

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

已确认的GitHub CLI基准版本为2.102.0，尚未确定支持所有策略参数的最早版本。
在线证明查询需要已认证的gh（`gh auth login` 或 `GH_TOKEN`）；安装程序仅需仓库和
证明读取权限，不需要发布权限。参见[GitHub CLI验证器源码](https://github.com/cli/cli/blob/v2.102.0/pkg/cmd/attestation/verify/verify.go)。
本地fixture仅验证策略、顺序和错误行为，不证明实际签名接受。

GitHub与PyPI发布是分别不可逆的两个步骤。准备阶段与PyPI上传前均保留强制依赖审计。
两次审计之间披露的新CVE可能导致仅有锁定的公开GitHub发行，而没有对应PyPI版本。
准备时的审计成功不是当前审计证据。发布工作流和PyPI验证成功之前应视为未完成，
保留两次执行记录和准确资产，诊断失败条件，必要时通过已审查的新版本向前修复。
本流程不授权绕过审计；修改审计策略需要所有者另行决定。

上限为独立程序8 MiB、支持资产256 KiB、元数据1 MiB。替换前必须通过认证的清单和证明、
准确标签和版本、暂存文件的 `--version` 检查。SSH部署前在发送端验证，离线目标仅需Python。
验证失败保留已有文件。下面v1.0.2步骤为历史记录；未来发行使用上述准备工作流。


## v1.0.0 证据与 v1.0.2 维护条件

经过审查的 RC4 运行时在五主机 `rc4-rerun-02` 中获得 14,436.65 秒的 `complete`、公开 health 241/241、probe 147/147、提交 21/21、Relay 重启后 3.182 秒恢复。独立 ACK 为 20/21。原始 T120 Windows native Claude ACK 因 TUI 关闭未能确认；同一路径后续单独的一次检查得到准确 ACK。用户已在 #164 明确接受这一运维例外。不得把原始结果改写成 21/21。#161 的外部停滞位置仍未确定，缓解措施不等于修复根因。这是 v1.0.0 的历史证据，并非 v1.0.2 变更的验证结果。

Python/PyPI 版本是 `1.0.2`，Git 标签和 GitHub Release 是 `v1.0.2`。不标记为预发布，并设置为 Latest。普通升级和独立版更新提示可能选择 v1.0.2 而非 v1.0.1。插件版本独立。核心在 Python 3.9+ 上无依赖；MCP 要求 3.10+，Relay 接收端/服务器要求 Unix 或 WSL 上的 3.11+。软件包发布不保证托管 Relay/OAuth 可用。由服务管理器启动的 macOS、Linux 接收端，应在 PATH 中包含目标 TUI 的 `codex` 可执行文件目录，或设置运维人员管理的绝对 `codexBin` 路径。Relay 登录会过期，可能需要重新授权。#161 的根因仍未确定，应保持开启。

根目录 `cc_peer.py` 为旧版 URL 保留，但必须排除在 wheel 和 sdist 外。应包含四种语言的 README、安全策略、稳定版说明、Relay 文档和可选运行时。不得包含凭据、设备密钥、认证数据库、replay 状态、浏览器配置、局部证据或对话。

## Trusted Publisher

PyPI 项目 `session-peer` 对应 GitHub `abruption/session-peer` 的 `publish.yml` 和环境 `pypi`。仓库不保存长期 PyPI 凭据。过去成功不证明配置未变，发布前需要确认。

## 准备与验证

1. 确认 v1.0.2 里程碑中已完成的修复，并将 #161 保留为根因未明的监控事项。审查相对 v1.0.1 的运行时差异及 v1.0.2 说明。不要把 `release/0.9.x` 合并到 `main`。
2. 确认 `session_peer.__version__ == "1.0.2"`、生成的 `session_peer.py` 一致、四种语言 README 安装命令一致、sdist 包含四种语言的稳定版说明。运行本地全部测试、PR 的 `release gate` 和合并后准确 `main` 的 CI。
3. 从准确候选以 `python3 -m build` 构建 wheel 与 sdist 并检查内容。分别在全新环境安装，检查 `session-peer --version`、已初始化代理主目录的 JSON `list`、`pip check`、Relay/MCP 扩展与 help。显式指定的空 Codex 主目录应以 `state_db_missing` 失败，这并非安装失败。不把实际模型消息纳入此关卡。
4. 检查通过后才合并，重新确认 `main` 的准确提交、版本与说明。确认 PyPI 尚无 `1.0.2` 文件。

## 草稿与公开

准备 PR 合并后才建立草稿；squash/merge 会改变发布提交。不要移动已发布的标签。

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

检查标签、目标、标题、说明、草稿、稳定版和 Latest 意图。草稿不构成发布授权。

## 公开

**公开前必须获得用户最终批准。** 发布命令：

```bash
gh release edit v1.0.2 \
  --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

工作流必须检查标签/版本/受保护 main、可复现的 wheel 与 sdist、归档/安装/审计、SHA256SUMS 和 provenance，然后才通过 OIDC 上传。已有 PyPI 文件属于硬错误。失败后不能用修改过的产物重传。如果 `1.0.2` 部分发布或哈希不符，停止升级、保存证据，通过审查后的新版本（通常是 `1.0.3`）修复。撤回版本也不能重复使用。

## 发布后验证

1. 确认准确标签与提交的 `publish.yml` 成功。下载 PyPI wheel 和 sdist，与工作流候选及 provenance 比对哈希，并分别在新环境安装。
2. 检查版本、已初始化代理主目录的 JSON `list`、Relay/MCP、`pip check`、GitHub 稳定版/Latest、普通升级选择。托管 Relay 另行验证；queued 不是 ACK。
3. 记录发布证据后再关闭 v1.0.2 里程碑。#161 继续在原监控里程碑中保持开启，不声称根因已修复。整个设备群部署或生产服务重启是单独的运维决定。
