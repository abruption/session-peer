# 发布 session-peer

公开 GitHub Release 会触发 `.github/workflows/publish.yml`，构建指定标签的 wheel 和 sdist，并通过 Trusted Publishing 上传 PyPI。草稿不会发布。请分开准备、最终批准、公开和验证。受保护的 `main` 需要最新 PR 以及覆盖各平台 Python、文档、Shell、软件包、MCP、Relay、control、集成测试和依赖审计的 `release gate`。实际 OAuth、代理 ACK 和生产 Relay 状态是独立的运维证据。

## 稳定版 v1.0.0 条件

经过审查的 RC4 运行时在五主机 `rc4-rerun-02` 中获得 14,436.65 秒的 `complete`、公开 health 241/241、probe 147/147、提交 21/21、Relay 重启后 3.182 秒恢复。独立 ACK 为 20/21。原始 T120 Windows native Claude ACK 因 TUI 关闭未能确认；同一路径后续单独的一次检查得到准确 ACK。用户已在 #164 明确接受这一运维例外。不得把原始结果改写成 21/21。#161 的外部停滞位置仍未确定，缓解措施不等于修复根因。稳定版不得改变 RC4 的运行时行为，且必须再次通过准确 `main` 的 CI。

Python/PyPI 版本是 `1.0.0`，Git 标签和 GitHub Release 是 `v1.0.0`。不标记为预发布，并设置为 Latest。普通升级和独立版更新提示可能选择 v1.0.0 而非 v0.9.2。插件版本独立。核心在 Python 3.9+ 上无依赖；MCP 要求 3.10+，Relay 接收端/服务器要求 Unix 或 WSL 上的 3.11+。软件包发布不保证托管 Relay/OAuth 可用。由服务管理器启动的 macOS、Linux 接收端，其 PATH 必须包含目标 TUI 的 `codex` 可执行文件目录（`codexBin` 仅适用于 WSL）。Relay 登录会过期，可能需要重新授权。

根目录 `cc_peer.py` 为旧版 URL 保留，但必须排除在 wheel 和 sdist 外。应包含四种语言的 README、安全策略、稳定版说明、Relay 文档和可选运行时。不得包含凭据、设备密钥、认证数据库、replay 状态、浏览器配置、局部证据或对话。

## Trusted Publisher

PyPI 项目 `session-peer` 对应 GitHub `abruption/session-peer` 的 `publish.yml` 和环境 `pypi`。仓库不保存长期 PyPI 凭据。过去成功不证明配置未变，发布前需要确认。

## 准备与验证

1. 处理 v1.0.0 里程碑和 #152 文档关卡，记录 #164 运维例外。#161 保留为根因未明的 v1.0.1 监控。与 RC4 相比，只允许版本、生成文件、文档和测试差异。不要把 `release/0.9.x` 合并到 `main`。
2. 确认 `session_peer.__version__ == "1.0.0"`、生成的 `session_peer.py` 一致、四种语言 README 安装命令一致、sdist 包含四种语言的稳定版说明。运行本地全部测试、PR 的 `release gate` 和合并后准确 `main` 的 CI。
3. 从准确候选以 `python3 -m build` 构建 wheel 与 sdist 并检查内容。分别在全新环境安装，检查 `session-peer --version`、空主目录 JSON `list`、`pip check`、Relay/MCP 扩展与 help。不把实际模型消息纳入此关卡。
4. 检查通过后才合并，重新确认 `main` 的准确提交、版本与说明。确认 PyPI 尚无 `1.0.0` 文件。

## 草稿与公开

准备 PR 合并后才建立草稿；squash/merge 会改变发布提交。不要移动已发布的标签。

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v1.0.0 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.0" \
  --notes-file docs/releases/v1.0.0.md \
  --draft --latest
```

检查标签、目标、标题、说明、草稿、稳定版和 Latest 意图。草稿不构成发布授权。

## 公开

**公开前必须获得用户最终批准。** 发布命令：

```bash
gh release edit v1.0.0 \
  --repo abruption/session-peer \
  --draft=false --prerelease=false --latest
```

工作流必须检查标签/版本/受保护 main、可复现的 wheel 与 sdist、归档/安装/审计、SHA256SUMS 和 provenance，然后才通过 OIDC 上传。已有 PyPI 文件属于硬错误。失败后不能用修改过的产物重传。如果 `1.0.0` 部分发布或哈希不符，停止升级、保存证据，通过审查后的新版本（通常是 `1.0.1`）修复。撤回版本也不能重复使用。

## 发布后验证

1. 确认准确标签与提交的 `publish.yml` 成功。下载 PyPI wheel 和 sdist，与工作流候选及 provenance 比对哈希，并分别在新环境安装。
2. 检查版本、空主目录 JSON `list`、Relay/MCP、`pip check`、GitHub 稳定版/Latest、普通升级选择。托管 Relay 另行验证；queued 不是 ACK。
3. 记录证据之后才关闭 v1.0.0 里程碑。整个设备群部署或生产服务重启是单独的运维决定。
