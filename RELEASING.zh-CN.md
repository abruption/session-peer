# 发布 session-peer

发布 GitHub Release 会触发 `.github/workflows/publish.yml`，该工作流构建选定的标签并通过 Trusted Publishing 将其上传到 PyPI。草稿不会发布。请将准备、批准、发布和验证步骤分开，以确保公开构件始终指向经过审查的代码。

## 当前候选版本：v1.0.0-beta.1

首个 1.0 beta 版本继承 alpha.1 的认证中继，并加入 #120–#123 中冻结的兼容性契约、第一方 control 数据库 migration、有界容量指标，以及从 WSL 到原生 Windows Codex 的投递。其规范的 Python/PyPI 版本为 `1.0.0b1`；面向用户的 Git 标签和 GitHub Release 为 `v1.0.0-beta.1`。`packaging.version.Version` 将这些值视为等同。不要使用裸 `v1.0.0-beta`，它会标准化为 beta 零。

本次发布是明确的预发布版本：

- 将 GitHub Release 标记为 **Pre-release**，切勿标记为 Latest；
- 正常的稳定包升级必须继续选择 v0.9.1；
- 测试人员使用 `pipx install 'session-peer[relay]==1.0.0b1'` 或等效的 `uv` 命令安装精确版本；
- 在 GitHub、PyPI 以及全新安装验证完成之前，保持 v1.0.0-beta 里程碑处于开启状态；
- 插件清单保留其独立版本（0.1.0）。

该候选版本包括本地/SSH 运行、可选的 MCP 和 Antigravity 适配器、配对的直接/中继传输、托管准入、公开 OAuth 注册、主动吊销、运维人员指标以及经过审查的 KR 部署构件。relay 额外依赖项需要 Unix 和 Python 3.11+。默认核心在 Python 3.9+ 上保持无外部依赖。托管的中继属于运维服务，不构成软件包可用性承诺。

仓库必须在根目录下保留冻结的 `cc_peer.py` 以用于旧版自更新 URL，同时将其从 wheel 和 sdist 中排除。包含所有四个 README、安全策略、beta 发布说明、中继生命周期/认证文档以及可选的运行时源码。切勿包含 OAuth 凭据、设备密钥、认证数据库、重放状态、浏览器配置文件、本地证据或会话记录。

## Trusted Publisher 配置

GitHub 环境为 `pypi`，活动工作流为 `publish.yml`。PyPI 项目所有者应保留以下 Trusted Publisher 映射：

| 字段 | 值 |
| --- | --- |
| PyPI project | `session-peer` |
| GitHub owner | `abruption` |
| GitHub repository | `session-peer` |
| Workflow filename | `publish.yml` |
| GitHub environment | `pypi` |

此前成功的发布是参考证据，并非所有者端映射未发生更改的保证。

## 准备与验证

1. 确认发布分支包含 #119–#123 并以 `main` 为目标。不要在先前堆叠 PR 的基础分支上打标签，并要求无冲突干净合并。
2. 确认 `session_peer.__version__ == "1.0.0b1"`，beta 说明已包含在 sdist 中，且四个 README 中的安装命令保持一致。
3. 运行完整的 CI 矩阵。在本地重复运行核心套件、控制 Node 22/24 套件、Node/Python 集成，以及与最终 diff 相对应的构建和归档检查。实时模型提交不属于发布准备的一部分。
4. 从确切的候选版本构建一次：

   ```bash
   python3 -m build
   ```

5. 检查两个归档文件。wheel 包含 `session_peer.py`、`session_peer_mcp.py`、`session_peer_relay/` 及元数据。sdist 还包含经过批准的文档和部署模板。两个归档文件均不得包含 `cc_peer.py`、凭据、数据库、重放状态、私钥、浏览器数据或本地证据。
6. 在全新环境中分别独立安装 wheel 和 sdist。确认 `session-peer --version` 报告 `1.0.0b1`，`session-peer list --output-format
   json` works in an empty home, and relay/MCP extras pass `pip check` 和 help 冒烟测试。
7. 仅在所需检查通过后进行合并。获取 `main`，记录其确切 commit，并在该 commit 上验证版本及预期更改。

## 准备草稿

仅在发布准备 PR 合并后创建草稿。压缩提交（squash）或合并提交（merge）会改变发布 commit。

```bash
git fetch origin main --tags
release_commit=$(git rev-parse origin/main)
gh release create v1.0.0-beta.1 \
  --repo abruption/session-peer \
  --target "$release_commit" \
  --title "session-peer v1.0.0-beta.1" \
  --notes-file docs/releases/v1.0.0-beta.1.md \
  --draft --prerelease --latest=false
```

验证标签、目标、标题、说明、草稿状态及预发布状态。切勿移动现有已发布的标签。创建草稿并不代表授权发布。

## 发布

在发布前立即获取最终用户批准。发布操作将使 GitHub Release 公开并触发 PyPI 上传：

```bash
gh release edit v1.0.0-beta.1 \
  --repo abruption/session-peer \
  --draft=false --prerelease --latest=false
```

若工作流失败，切勿创建第二个发布或使用修改后的构件重试。保留失败的运行记录并进行排查。PyPI 版本是不可变的。

## 验证发布

1. 确认 `publish.yml` 针对预期的标签和 commit 执行成功。
2. 确认 PyPI 准确提供了 `session-peer==1.0.0b1`。下载 wheel 和 sdist，将其哈希值与工作流构件进行比较，并再次检查内容。
3. 在全新环境中安装确切的 PyPI 预发布版本，并重复版本、空主目录 list、relay 额外依赖项和 MCP 冒烟检查。
4. 确认 GitHub 将该发布标记为预发布且未标记为 latest。稳定的 `releases/latest` 端点和常规更新通知必须继续指向 v0.9.1。
5. 单独验证托管的中继；软件包发布并不能证明服务健康状况、OAuth 策略或代理确认情况。
6. 仅在记录 GitHub、PyPI 及全新安装证据后关闭 v1.0.0-beta 里程碑。

通过包管理器安装的环境使用其自身的管理器进行升级。独立的稳定安装继续使用 `session-peer update`；beta 测试人员使用精确的软件包版本。提交绝不是已被采用或确认的证明。
