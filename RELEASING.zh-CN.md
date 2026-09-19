# 发布 session-peer

发布 GitHub release 会触发 `.github/workflows/publish.yml`，该工作流构建标签并通过 Trusted Publishing 将其上传到 PyPI。草稿发布不会执行发布。请将发布准备、审批、发布和验证作为独立的步骤保持分开，以便标签和上传的产物始终指向经过审查的代码。

## 当前候选版本：v0.9.0

v0.9.0 候选版本集成了已批准的 #47 适配器/传输重构、#69 中继实验室和 #85 Antigravity 适配器，外加一个通过原生适配器路由配对请求的可选产品中继包。先前的 #87/#88 PR 已合并到依赖分支；它们已获批准的变更被显式带入面向 main 的发布 PR 中。候选版本说明：`docs/releases/v0.9.0.md`。在 #89 中跟踪发布；保持其打开状态，直到产物验证完成。
插件清单保留其独立版本（0.1.0）。

### #90、#91 和 #92 之后的最终集成

发布定稿分支始于 main 的 `27b28dd`，其中包含 v0.9 功能准备（#90）、支持/安全试点（#91）以及四种语言的 README（#92）。后者包括协调一致的 v0.9 功能描述和 sdist 内容。软件包版本已经是 `0.9.0`；不要为了本次文档定稿再次提升版本。该基准不是最终的发布 commit：在定稿 PR 合并后，记录确切的 main commit。

- 保持 #89 打开：合并准备 PR 既不是发布也不是产物验证。
- 在 sdist 中包含所有三份已翻译的 README、`docs/cli-reference.md`、安全策略和 v0.9 发布说明，以及可选的中继文件。
- 保留独立的插件版本、冻结的旧版更新器、可选额外依赖以及排除实验性代码。在 CI 中验证 wheel 和 sdist 的安装。
- 准备本次定稿时，最新发布的版本为 v0.8.0。候选版本的措辞绝不能被解读为成功的 PyPI 上传。
- 仅在合并后创建草稿；发布 release 仍需要下文所述的单独最终审批。不要在此 PR 中自动关闭 #89。

中继 extra 需要 Unix 和 Python 3.11+。除无依赖的核心外，还要验证 `.[relay,mcp]`，包括 `docs/relay-public-pilot-2026-09-17.md` 中的公开试点证据。有边界的实时测试不是浸泡测试：实际的运维验证仍是 v1.0.0-rc 的关卡。

仓库必须继续包含根目录下冻结的 `cc_peer.py`，用于旧版自更新 URL。它必须保持在 session-peer 的 wheel 和 sdist 之外。

## Trusted Publisher 配置

GitHub 环境为 `pypi`，活动工作流为 `publish.yml`。PyPI 项目所有者应保留以下 Trusted Publisher 映射：

| 字段 | 值 |
| --- | --- |
| PyPI project | `session-peer` |
| GitHub owner | `abruption` |
| GitHub repository | `session-peer` |
| Workflow filename | `publish.yml` |
| GitHub environment | `pypi` |

v0.6.1 版本成功使用了此路径。GitHub 无法检查 PyPI 所有者端的映射，因此先前的成功只是证据，并不能保证其未发生变更。

## 准备与验证

1. 创建发布 issue 并从当前的 `origin/main` 切出分支。
2. 在一个发布准备 PR 中更新 `session_peer.__version__`、持久的 README 措辞、本运行手册以及 `docs/releases/<version>.md`。
3. 运行 CI 使用的检查：

   ```bash
   python3 -m compileall -q cc_peer.py session_peer.py session_peer_mcp.py tests
   python3 -m unittest discover -s tests -v
   python3 -m unittest discover -v
   python3 -m build
   ```

   在另一个安装了 `.[mcp]` extra 的 Python 3.10+ 环境中重复该测试套件。独立环境应仅跳过可选的 SDK 测试。在发布检查中不要启用实时唤醒/模型测试。

4. 检查两个归档文件。`session_peer.py`、许可证、元数据和 README 属于 sdist；wheel 包含 `session_peer.py`、`session_peer_mcp.py`、可选的 `session_peer_relay/` 包以及元数据。sdist 还包括 MCP/唤醒/多主目录文档以及插件文件。任何归档文件均不得包含 `cc_peer.py`、凭据、会话数据库或本地笔记。
5. 在崭新的环境中分别独立安装 wheel 和 sdist。确认 `session-peer --version`、`session-peer list --output-format json` 以及导入元数据。使用隔离的临时 HOME 进行无会话冒烟检查。在安装了 extra 的情况下验证 `session-peer-mcp --help`；默认策略必须保持本地只读。
6. 仅在所有必需检查均通过后才合并发布准备 PR。拉取 `main`，记录其确切 commit，并确认其仍包含预期的更改和版本。

## 准备草稿

仅在发布准备 PR 合并后才创建草稿，因为 squash 或 merge commit 会更改发布 commit：

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

验证草稿的标签、目标 commit、标题、说明、草稿状态和预发布状态。如果 GitHub 在保存草稿时创建了标签，请确认其解析为所记录的发布 commit。切勿移动已发布的现有标签。

## 发布

在发布前立即获取最终审批。发布是使 GitHub release 公开并启动 PyPI 上传的操作：

```bash
gh release edit v0.9.0 --repo abruption/session-peer --draft=false --latest
```

如果工作流失败，不要创建第二个 release 或使用修改后的产物重试。保留失败的运行并诊断失败阶段。已被 PyPI 接受的版本无法替换。

## 验证发布

1. 确认发布触发的 `publish.yml` 运行成功完成，并使用了预期的标签和 commit。
2. 确认 PyPI 暴露的恰好是 `session-peer==0.9.0`。下载 wheel 和 sdist，将其文件名和 SHA-256 哈希与工作流产物进行比对，并再次检查其内容。
3. 从 PyPI 将 0.9.0 安装到崭新环境中。确认版本及本地只读列表。无提交的 dry-run 可以使用显式的临时 Codex 主目录和可执行文件；如果预期的目标失败能证明未运行任何队列命令，则该失败是可接受的。
4. 确认 GitHub 将 v0.9.0 标记为 latest，并且 `session-peer update --check` 会将其报告给较旧的独立安装。
5. 仅在记录了 GitHub、PyPI、全新安装和更新器验证之后，才关闭发布 issue。

包管理器安装的实例使用各自的管理器进行升级。独立安装使用 `session-peer update`；若需刷新捆绑的 Claude skill，则需要 `install.sh`。提交绝不是消费或确认的证据。
