# session-peer CLI 参考

[返回概览](../../README.zh-CN.md)

以下是详细的命令行为、安装选项、传输限制和历史验证记录。
机器consumer还应遵循[v1兼容性契约](compatibility-v1.md)。

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/pypi/pyversions/session-peer)](https://pypi.org/project/session-peer/)

通过单个 CLI 在本地或经由 SSH 向 **Claude Code 和 Codex 会话**发送消息。Claude 目标使用其原生收件箱套接字/管道；Codex 目标使用 `codex queue`。SSH 会在目的地运行相同的 Python 脚本，因此无需在目标端安装 session-peer 即可接收发送或列出请求。

本项目延续自 cc-peer，并保留了其 Git 历史记录和议题编号。session-peer 发布版本托管于 [PyPI](https://pypi.org/project/session-peer/) 和 [GitHub](https://github.com/abruption/session-peer/releases)；旧的 PyPI cc-peer 项目在发布最终的 0.5.1 版本后已归档。有关明确的迁移步骤，请参阅[从 cc-peer 迁移](#moving-from-cc-peer)。

## 支持与安全

- **错误与功能请求：** 请使用[议题模板](https://github.com/abruption/session-peer/issues/new/choose)。请先搜索现有议题。
- **安全漏洞：** [私下报告](https://github.com/abruption/session-peer/security/advisories/new)。参见 [SECURITY.md](../../SECURITY.zh-CN.md)。
- **私人咨询：** 发送邮件至 [support@abruption.dev](mailto:support@abruption.dev?subject=%5Bsession-peer%5D%20Support)，并在主题中注明 `[session-peer]`。如果您无法使用私下漏洞报告功能，电子邮件也是一种替代途径。

公开议题对所有人可见。请提供最小化、已脱敏的复现步骤；切勿附带对话历史记录、会话数据库、身份验证文件、令牌或私钥。电子邮件由人工审核，不会自动发布为议题。技术支持尽力而为，不保证响应时间。欢迎使用英文和韩文提交报告。

## 快速开始

使用 `pipx install session-peer` 或 `uv tool install session-peer` 安装 CLI。有关独立 CLI 加 Claude 技能的说明，请参阅[安装](#install)。

```bash
session-peer list                              # Claude, Codex + registered Antigravity
session-peer list --agent claude                # Claude-only filter
session-peer list --agent codex                 # saved Codex threads
session-peer list --agent codex --host worker   # saved threads on an SSH host

session-peer send --to api-worker --message "message"     # Claude name or PID
session-peer send --to 'codex:<full-thread-uuid>' --message "message" --output-format json
session-peer send --host worker --to 'codex:<full-thread-uuid>' --dry-run -m "message"
```

将 `<full-thread-uuid>` 替换为目标端 Codex 列表中的完整 ID。`list` 默认包含所有已注册的适配器。Antigravity 仅列出活跃的、显式注册的桥接器。**请使用 `--agent codex` 进行过滤，而非 `--codex`**：`--codex` 不是受支持的标志，且与 `--codex-home` 和 `--codex-bin` 存在歧义。`send` 根据其目标选择代理，而非通过 `--agent` 标志。

**已投递/已入队并不代表已确认。** 已保存的 Codex 线程不一定正在运行。普通的发送不会激活会话；[显式 `--wake`](wake.md) 是可选功能，且不确认消息已被消费或回复。

### 可选配对设备与 Antigravity (v0.9)

这些功能自 PyPI v0.9.0 起提供。Antigravity 仍处于实验阶段，配对传输仍处于 Beta 阶段；仍需进行操作验证。使用 `pipx install 'session-peer[relay]'` 安装额外组件。`[relay]` 额外组件（Unix、Python 3.11+）支持通过直接连接或自建 WSS 中继进行经过身份验证的配对设备传递。配对会固定设备身份；单独的操作员策略允许特定的代理目标和操作。盲中继无法解密应用消息。在公开端点之前，请遵循[配对设备设置与操作指南](paired-devices.md)。该测试版不提供 NAT 穿透或托管公共服务。

Antigravity 需要在现有 TUI 内显式启动桥接器；参见 [Antigravity 设置](antigravity.md)。它是可选的，不会改变 Claude/Codex 发现机制；活跃的 Antigravity 注册项也会出现在未过滤的列表中。常规的本地和 SSH 命令保留其仅依赖标准库的安装方式。参见 [v0.9 发布说明](releases/v0.9.0.md)。

### 消息输入与结果输出

`--message TEXT`（短形式 `-m`）指定发送到目标端的文本。`--output-format text|json` 选择命令结果的格式，而非消息格式。它适用于 `list`、`send`、`doctor` 和 `update`；默认值为 `text`。现有的 `--json` 保留为 `--output-format json` 的别名。

```bash
session-peer send --to worker --message "Report progress" --output-format json
session-peer send --to worker -m - --output-format json < message.txt
session-peer list --output-format json
```

传统的按位置传入消息和省略消息的 stdin 输入方式仍然有效。请使用位置参数消息或 `--message` 之一，切勿两者并用。`--message -` 从 stdin 读取；显式的空消息仍然会被拒绝。要发送以破折号开头的文本，请使用 `--message='--literal text'` 或 stdin。内部 SSH `--b64` 输入不能与任何一种公开消息形式结合使用。

`--json --output-format json` 是合法的；无论先后顺序，将 `--json` 与 `--output-format text` 组合都会报错。无效或矛盾的输出选项属于 argparse 用法错误（stderr，退出码 2）；消息来源冲突属于普通命令错误（请求时为 JSON，退出码 1）。无论哪种情况均不会提交任何消息。JSON 结果仍然描述提交情况而非接收情况；这些标志并未引入结构化的 JSON 消息输入协议。

<a id="install"></a>
## 安装

Python 3.9+，仅限标准库 —— 无外部依赖。

### pip

在激活的虚拟环境中：

```bash
python -m pip install session-peer
```

或者使用 [pipx](https://pipx.pypa.io/) 进行隔离安装：

```bash
pipx install session-peer
```

或者使用 `uv tool install session-peer`。包管理器会安装 `session-peer` 命令，但不会安装[代理技能](#the-skill)。请从专用仓库安装 Claude Code、Codex 和 Antigravity 技能：

```bash
npx -y skills@latest add abruption/session-peer-skill \
  --skill session-peer --global \
  --agent claude-code --agent codex --agent antigravity \
  --copy --yes
```

<a id="installsh"></a>
### install.sh

一步安装命令和技能。适用于隔离环境主机或通过 SSH 远程部署：

```bash
git clone https://github.com/abruption/session-peer && cd session-peer

./install.sh                          # this machine
./install.sh --host build-server      # a remote machine, over SSH
./install.sh --host web-01 --host db  # several at once
```

这会将 `session_peer.py` 放置在 `~/.local/share/session-peer/` 中，将 [session-peer 技能](https://github.com/abruption/session-peer-skill/blob/main/session-peer/SKILL.md)的兼容副本安装在 `~/.claude/skills/session-peer/` 和 `~/.agents/skills/session-peer/` 中，并建立链接 `~/.local/bin/session-peer`。由其他管理器安装的技能、符号链接及现有 cc-peer 文件均会保留。`./install.sh --uninstall [--host ...]` 只移除安装器拥有的文件；没有所有权标记的旧技能会保留。

`session-peer update` 会从最新的 GitHub Release 刷新独立程序。`./install.sh --host <host>` 通过 SSH 推送当前检出版本的程序和技能。当已安装版本不同或不存在时，`session-peer update --host <host>` 仅推送程序；添加 `--check` 仅报告而不作任何更改。有关包管理器安装和远程限制，请参阅[更新](#updating)。

**远程安装直接通过 SSH 连接本身推送文件**，因此目标端无需互联网访问权限。安装独立文件需要 `python3` 和 SSH 访问权限。收发消息还需要目标端上存在所选代理的原生收件箱或队列。

或者完全跳过安装程序，仅复制单个文件：

```bash
curl -O https://raw.githubusercontent.com/abruption/session-peer/main/session_peer.py
chmod +x session_peer.py
```

<a id="the-skill"></a>
### 技能

公开技能的正式版本由 [session-peer-skill 仓库](https://github.com/abruption/session-peer-skill)维护。独立安装程序为隔离网络和 SSH 安装保留兼容副本，并将其分别放置在 Claude Code 的 `~/.claude/skills/session-peer/SKILL.md` 和 Codex 的 `~/.agents/skills/session-peer/SKILL.md` 中。Claude 路径依次遵循 `CLAUDE_CONFIG_DIR`、`ANTHROPIC_CONFIG_DIR` 和默认位置。安装器不会覆盖或删除由其他管理器维护的技能。若要为 Claude Code、Codex 与 Antigravity 进行全局安装，请使用上面的 Skills CLI 命令。技能负责指导目标和消息选择，Python 程序负责发现与传输。安装不会改变任何代理的权限或入站设置。

## 用法

```bash
session-peer list                                  # Claude + Codex on this machine
session-peer list --host web-01                    # Claude + Codex over there
session-peer list --host web-01 --all              # Claude stale records / no inbox
session-peer list --agent codex --all              # include archived Codex threads
session-peer doctor                                # local inbox/tool/home diagnostics
session-peer doctor --host web-01                  # run the same checks there
session-peer doctor --host web-01 --check-return-route  # also test SSH back here

session-peer send --to api-worker "message"        # local session
session-peer send --host web-01 --to api-worker "message"
session-peer send --host deploy@web-01 --to api-worker "message"  # explicit SSH user
session-peer send --host web-01 --to 4011 "message"          # address by pid
git log --oneline -5 | session-peer send --host web-01 --to api-worker -   # stdin

session-peer send --host web-01 --to api-worker --dry-run "x"   # resolve only
session-peer list --host web-01 --json             # machine-readable
session-peer list --no-update-notice                # disable cached update notices/checks

session-peer send --host web-01 --ssh-opt=-p --ssh-opt=2222 --to api-worker "..."   # note the '='

# Envelope. Sends identify the Claude/Codex sender and how to answer when the
# current agent session and a return route can be detected.
session-peer send --host web-01 --to api-worker --no-reply-to "..."         # no return address
session-peer send --host web-01 --to api-worker --no-from "..."             # no From: header
session-peer send --host web-01 --to api-worker --reply-to 100.64.0.5 "..." # state the address
```

在代理会话内部，默认信封显式标识发送者：

```text
From: codex:01a08dd6-d3f6-7783-a62b-52c1fd049181 @ abruptly@mac-mini-m4.example.ts.net

message

---
Reply-To: session-peer://v1/reply?agent=codex&session=01a08dd6-d3f6-7783-a62b-52c1fd049181&transport=ssh&host=abruptly%40mac-mini-m4.example.ts.net
Reply: python3 /path/to/session_peer.py send --host abruptly@mac-mini-m4.example.ts.net --to codex:01a08dd6-d3f6-7783-a62b-52c1fd049181 --no-reply-to
```

Claude 发送者在相同位置使用 `claude:<session-name>`。该身份是从当前进程环境中推导出的尽力而为文本；它并非经过身份验证的声明。普通的 shell 没有可通告的代理身份。当原始目标位于同一台机器上且自动检测到了回复路由时，生成的命令会省略 `--host` 并进行本地投递。当显式的 `--reply-to` 或配置的回复主机指定为本机器上的当前操作系统用户时，它也会被规范化。其他显式路由和实际的远程发送则继续通告 SSH 路由。

`Reply-To` 是规范的、带版本的地址。将完整的 URI 作为 `--to` 传回；session-peer 会验证每个字段并选择本地或 SSH 投递：

```bash
session-peer send --to 'session-peer://v1/reply?agent=claude&session=api-worker&transport=local' 'done'
```

保留 `Reply:` 命令是为了保持兼容性。应将这两种形式均视为不受信任的输入：请配合 session-peer 使用该 URI，而不是直接对其进行求值（evaluate）或 source 执行。指向本机器当前操作系统用户的 URI 会规范化为本地投递，从而避免不必要的自身 SSH 认证流程。当发送者环境能够识别时，Codex 地址可能包含编码后的 `codexHome`。

重复使用 `--host` 可对多个 SSH 目的地进行操作。`--json` 在 `list`、`send`、`doctor` 和 `update` 中可用。

### JSON 响应契约

每个 JSON 结果对象都以相同的、带模式版本的信封开头：

```json
{
  "schemaVersion": 1,
  "ok": true,
  "host": "mac-mini.example.ts.net",
  "command": "list",
  "sessions": [],
  "version": "0.8.0"
}
```

- `schemaVersion` 对通用信封进行版本控制。特定命令的嵌套模式（如 `clientUpdate` 和 `codexHomeResolution`）带有它们自己的版本。
- `ok` 在每次成功和失败时都会出现。非零的进程退出码仍可能包含针对其他主机的成功结果。
- `host` 标识该结果适用的目的地。本地结果使用操作系统主机名。由 Tailscale 解析的目的地使用经过验证的 MagicDNS 身份；若调用者提供了不同的 SSH 别名，则 `sshHost` 会保留该别名。
- `command` 为 `list`、`send`、`doctor` 或 `update`。其余字段为该命令的有效负载，失败时会添加 `error` 以及任何结构化的诊断字段。

本地或单主机调用会输出一个对象。重复使用 `--host` 会按请求顺序输出包含这些相同、可独立归属对象的数组。在连接之前发生的失败（如无效的消息输入）仍会针对每个请求的目的地输出一次。所有四个命令共享这种基数关系，因此使用者只需根据对象还是数组进行分支处理，然后使用相同的信封字段即可。

常规命令会读取专用的 24 小时更新缓存。缺失、过期或无效的缓存会启动一次分离的、尽力而为的 GitHub 刷新，且绝不延迟或更改所请求的命令。当最新的缓存证明调用的 CLI 落后于稳定版本时，JSON 结果会添加 `clientUpdate`：

```json
{
  "clientUpdate": {
    "schemaVersion": 1,
    "status": "available",
    "current": "0.7.0",
    "latest": "0.7.1",
    "checkedAt": "2026-09-16T10:00:00Z",
    "source": "github_release_cache",
    "command": "session-peer update"
  }
}
```

人类可读的输出会在 stderr 上获得相同的简短提示。当客户端为最新版本、缓存不可用或过期、主机离线或禁用了通知时，该字段会被省略，因此仅凭缺少该字段并不能证明客户端为最新版本。对于多主机命令，这一事实仍局限于单个调用的 CLI，并会被复制到每个结果对象中；目的地的 `remoteVersion` 字段保留各自独立的含义。远程子进程不会执行自己的刷新。

当本地 `tailscale status --json` 通过设备主机名、短 MagicDNS 名称、完整 MagicDNS 名称或 Tailscale IP 识别 `--host` 时，session-peer 会验证并将当前的 MagicDNS FQDN 报告为 `host`。SSH 仍接收提供的值作为其目标别名（不同时单独报告为 `sshHost`），同时 `HostName` 覆盖将连接路由到该 FQDN，而 `HostKeyAlias` 保留现有的主机密钥查找。这保留了匹配的 `Host`、`User`、`Port` 和 `IdentityFile` 设置。被报告为离线的已知节点将在发起 SSH 之前失败。未包含在 tailnet 映射中的主机仍为普通 SSH 目的地。

主机身份不提供登录账户：`known_hosts`、Tailscale 对等节点和 MagicDNS 名称标识的是机器，而不是其操作系统用户。请将账户指定为 `--host USER@HOST`，或为原始别名进行配置：

```sshconfig
Host web-01
    User deploy
```

显式的 `USER@HOST` 具有最高优先级。否则 session-peer 会使用相同的别名和选项运行 `ssh -G`，以报告生效的 OpenSSH 配置或本地用户默认值。它绝不会根据其他机器进行推测，也不会尝试使用不同的用户名重试失败的登录。

成功的远程结果和 SSH 连接失败会添加 `sshUser` 和 `sshUserSource`；当 `ssh -G` 无法解析时，来源为 `explicit`、`ssh_config_or_local_default` 或 `unknown`。连接失败还会添加 `sshFailure`，分类为 `authentication_failed`、`host_key_failed`、`timeout` 或 `transport_failed`。认证错误会指引调用者使用 `--host USER@HOST` 或原始别名的 SSH `User` 设置，并且绝不会进行重试。

退出码：`0` 命令成功（包括列出或预检运行 dry-run），`1` 操作错误，`2` CLI 用法错误或未解析的目标被报告为 no-target，以及 `130` 中断（Ctrl-C）。Codex 队列拒绝（包括缺失 rollout）属于操作错误（`1`）；预检运行期间缺失已保存的线程返回 `2`。发送操作退出码为 `0` 并不确认消息已被消费或回复。

<a id="updating"></a>
### 更新

对于通过包管理器安装的版本，请使用安装该命令的同一包管理器：

```bash
pipx upgrade session-peer
# or: uv tool upgrade session-peer
# or, in its virtual environment: python -m pip install --upgrade session-peer
```

对于这些安装，本地 `session-peer update` 会打印包管理器指引，而不会替换包管理的文件。`session-peer update --check` 检查最新的稳定 GitHub Release，刷新共享缓存并报告确切的升级命令，但仍不会替换这些文件。

对于独立程序：

```bash
session-peer update --check                       # check the latest GitHub release
session-peer update                               # update the local program
session-peer update --host web-01 --check         # inspect the remote standalone copy
session-peer update --host web-01                 # push this program if versions differ
```

远程更新是与**本地程序的版本**进行比较，而非最新的 GitHub Release。即使远程版本更新它也会推送；在分发之前，请先检查并更新本地程序。远程副本不会从 GitHub 获取更新。远程版本探测仅检查 `~/.local/share/session-peer/session_peer.py`，不检查 pip/pipx/uv 安装；远程更新会安装该独立路径及其 CLI 链接。对于通过包管理器安装的远程 CLI，请改用该主机上自带的管理器进行升级。

无论是本地还是远程的 `update` 都不会刷新 Claude 技能。从所需发布版本的检出目录重新运行 `install.sh` 可同时刷新独立程序和技能。本地的 `session-peer update --check` 和 `session-peer update` 也会填充自动通知所使用的相同缓存。

### 环境变量

| 变量 | 作用 |
| :-- | :-- |
| `SESSION_PEER_REPLY_HOST` | 覆盖所通告的回复主机：`--reply-to` → `SESSION_PEER_REPLY_HOST` → `CC_PEER_REPLY_HOST` → 自动检测的 Tailscale MagicDNS 名称或 IP。要生成回复行，仍需要可检测到的 Claude 或 Codex 发送者会话。 |
| `CC_PEER_REPLY_HOST` | 遗留回退选项；对于新配置，建议优先使用 `SESSION_PEER_REPLY_HOST`。 |
| `CLAUDE_CONFIG_DIR` | Claude Code 保存其配置的目录（默认为 `~/.claude`）。`session-peer list` 会遵循此目录以进行会话发现，`install.sh` 也会遵循此目录以放置技能。 |
| `ANTHROPIC_CONFIG_DIR` | 当 `CLAUDE_CONFIG_DIR` 未设置时的回退项。 |
| `CODEX_HOME` | Codex 发现/队列目录（默认为 `~/.codex`）；可由 `--codex-home` 覆盖。 |
| `SESSION_PEER_CODEX_HOMES` | 在隐式发送/预检运行之前，用于检查重复线程 UUID 和稳定活跃写入者的额外目标目录。由绝对路径（或 `~/…`）组成的 JSON 数组，不是 shell 命令或以路径分隔符分隔的列表。它不会合并列表；明确的活跃写入者可能会更改隐式发送目录。 |
| `SESSION_PEER_NO_UPDATE_NOTICE` | 设置为 `1`、`true`、`yes` 或 `on` 以禁用自动缓存更新通知和后台刷新。每个命令的等效标志为 `--no-update-notice`。显式的 `session-peer update --check` 仍会进行检查。 |
| `XDG_CACHE_HOME` | 更新缓存的基础目录；否则使用 `~/.cache/session-peer/update.json`。 |

使用 `--host` 时，发现过程使用目标端环境；本地环境变量不会自动转发。`--codex-home` 和 `--codex-bin` 显式选择该目标端上的路径。

## Codex 会话

Codex 发现使用只读 SQLite 连接读取 `state_5.sqlite`。此内部模式是实验性的，已在 macOS 上的 Codex CLI 0.154.0 上进行测试；跨平台固件测试并不代表在所有操作系统上都进行了实时 Codex 验证。已保存的会话不一定处于活跃状态。`--all` 包含已归档的线程。

`--codex-home` 覆盖目标端的 `CODEX_HOME`（默认为 `~/.codex`）。`--codex-bin` 覆盖用于发送的 `codex` PATH 查找。在 SSH 上，这些是远程路径。发送需要具备 `queue` 命令的 Codex 可执行文件以及该目录下相应的已保存线程/rollout；仅凭列表并不能证明队列可以接受它。

### Orca 与多个 Codex 目录

由 Orca 启动的会话可以使用按账户划分的目录，而单独的终端或 SSH 命令则使用 `~/.codex`。同一个 UUID 可能同时存在于两者之中。向其中一个副本成功提交队列并不能证明目标会话正在使用该目录。

显式的目标目录仍然是最可靠的选择。例如，将 `<account-id>` 和 `<full-thread-uuid>` 替换为预期的账户和线程：

```bash
session-peer list --host mac --agent codex \
  --codex-home '~/Library/Application Support/orca/codex-accounts/<account-id>/home' --json
session-peer send --host mac --to 'codex:<full-thread-uuid>' \
  --codex-home '~/Library/Application Support/orca/codex-accounts/<account-id>/home' \
  --dry-run --json "message"
```

本地使用时请省略 `--host mac`。仅在准备提交时才移除 `--dry-run`。给 `~` 加上引号可使其在目标端进行展开；绝对远程路径同样有效。当前版本将 `--codex-home` 视为目标约束，同时仍会验证所有匹配已知目录的写入者证据。旧版本也接受显式目录语法，但不提供这项安全保证。

重复目录拒绝基线在 v0.6.1 中发布。下文描述的活跃写入者选择、重新验证以及详细的 `codexHomeResolution` 证据在 v0.6.2 中提供；当同一个线程 UUID 存在于多个已知目录中时，v0.6.1 需要显式指定 `--codex-home`。

在未指定 `--codex-home` 的情况下，选择机制仍优先使用目标端的 `CODEX_HOME`，其次是 `~/.codex`。在发送或预检运行之前，歧义防护机制会检查一个有界的清单：

- 所选目录，以及在其状态数据库存在时的默认 `~/.codex`。
- 仅在 macOS 上，直接位于 `~/Library/Application Support/orca/codex-accounts/*/home` 下的现有状态数据库。
- 来自目标端 `SESSION_PEER_CODEX_HOMES` 的额外目录，例如：

```bash
export SESSION_PEER_CODEX_HOMES='["/srv/codex/account-a", "/srv/codex/account-b"]'
```

请在目标命令的环境中进行配置；本地 export 的变量不会被 `--host` 转发。在 Windows 上，使用符合 JSON 要求的带反斜杠转义的绝对 Windows 路径。允许配置空数组；对于隐式发送，格式错误的配置会引发错误。

对于每次发送和预检运行，session-peer 都会查找保存该 UUID 的所有已知目录，并检查每个目录中确切的 `thread-writer-locks/<uuid>.lock`。单个候选目录和显式 `--codex-home` 也包括在内。它会独立探测内核建议锁，并通过两次稳定的 `lsof` 观察来关联打开该文件的进程。隐式发送会选择唯一具有稳定同用户 Codex 写入者的目录。显式目录必须与该写入者一致；如果另一个目录拥有唯一的活跃写入者，命令将返回结构化冲突，且绝不会暗中更换目录。在队列提交前会再次检查所选 PID、进程启动时间以及持有的锁。空闲或过期的锁不会仅仅因为文件存在而胜出。

未知证据、多个活跃写入者、缺少 `lsof`、权限失败、PID/启动时间/inode 变化以及冲突证据都会在排队前以安全方式失败（fail-closed）。已归档的保存副本仍然计算在内。无法读取或不兼容的已知数据库以及缺失的已配置数据库也会阻止提交。如果所有保存副本都处于非活动状态，要有意为未来 resume 排队，必须同时使用显式 `--codex-home` 和 `--allow-inactive-codex-home`；`--wake` 已被视为显式激活 opt-in。没有显式目录时仅使用 inactive 标志会被拒绝。解析后的符号链接别名和重复路径视为同一个目录。

除非 `--codex-home` 精确选择一个目录，否则 `list` 会汇总已知目录。不存在常规的文件系统扫描或进程环境检查，且进程参数不会公开。活动检查在目标机器上运行，包括通过 SSH。缺少 POSIX `flock` 或 `lsof` 的平台无法建立活跃写入者所有权，并会在需要该证据时以安全方式失败。未配置/自定义的布局以及在检查后创建的副本仍可能被遗漏。使用 `session-peer doctor` 可在不提交的情况下检查所选目录、有界候选列表、可执行文件以及受支持的状态数据库模式。

### 提交与 JSON 结果

提交使用 `codex queue`，绝不直接写入数据库。`queued` 意味着 CLI 接受了提交，并不意味着轮次已消费或已确认。session-peer 不会唤醒或恢复会话。队列数据库写入和 Claude 套接字连接可能需要调用者执行环境的批准；该工具不会更改沙盒或入站策略。队列超时（30 秒）具有未知的提交结果：重试前请先检查目标端。这不是等待回复的超时，且 session-peer 不会自动重试。

Codex 消息限制为 32 KiB 的 UTF-8 文本（包括发送者/回复头），这是 session-peer 的可移植性策略，而非实测的 Codex 服务器限制。NUL 字符不能作为 CLI 参数传递。`--dry-run` 会在不进入队列的情况下验证可执行文件和已保存的目标，但不能保证后续提交一定会成功。

本地 Codex 列表 JSON 使用通用响应信封，并在 `discovery.codex.homes` 中包含 `sessions`、`version` 以及针对各个目录的诊断信息。每个会话条目包含 `agent`、`id`、`name`（第一行，最多 120 个字符）、`cwd`、`updatedAt`（Unix 秒）、`archived`、规范的 `codexHome` 和 `stateDb`。顶层 `codexHome` 仅在单个候选目录且无清单错误时保留。每个成功的远程结果包含相同的字段，以及针对已安装独立副本的可选 `remoteVersion`。单个远程主机会返回一个对象；重复指定主机则返回一个数组。

在通用信封内，Codex 发送 JSON 包含 `target: {agent, id}`、`status: queued`（或预检运行下的 `validated`）、`chars`、`dryRun` 以及可选的 `queueId`。它还包括：

- `codexHome`：解析后的绝对目标目录，而非发送端的推测。
- `codexHomeResolution`：带模式版本的 `status`、`selected`、`reason` 和有界候选证据。状态为 `explicit`、`selected`、`ambiguous` 或 `unknown`；候选者公开已保存线程、写入者锁、稳定所有者 PID 和进程启动时间的事实信息，而不包含进程参数或环境变量值。
- `submitted`：仅在成功完成队列 CLI 执行后为 `true`，预检运行为 `false`。
- `consumptionConfirmed`：始终为 `false`；无论是入队还是验证都不能证明已被消费。

错误会将通用信封的 `ok` 设置为 `false`，添加 `error`，并在目录证据导致失败时包含 `codexHomeResolution`。超时具有未知的提交结果；错误发生时缺少 `submitted` 绝不能被解释为没有任何内容入队的证据。列表结果不描述提交，且没有提交/消费字段。

对于每个命令，单个远程主机会返回扁平对象，多个主机会返回数组。当存在 `CODEX_THREAD_ID`（或兼容性回退项 `CODEX_SESSION_ID`）时，消息信封和回复命令会标识发起的 Codex 线程。

### 诊断与回复观察

`doctor` 在拥有会话的机器上执行只读检查。它报告 Claude 配置的会话目录和收件箱可用性，Codex 的可执行文件和有界目录/状态数据库候选，不支持的数据库模式，并将权限或未知失败报告为不同的代码。它不会连接到收件箱、写入队列、扫描任意目录或更改代理/SSH 设置。

反向 SSH 仅在指定 `--check-return-route` 时进行检查。目标端会运行一个固定的 `ssh ... true` 探测，且禁用了提示、密码身份验证、主机密钥注册和配置更改。正向 SSH 成功绝不能作为反向路径可用的证据。当自动 Tailscale 检测无法识别来源时，请使用 `--reply-to USER@HOST`。JSON 详情和状态值记录在 [docs/diagnostics.md](diagnostics.md) 中。

这里特意没有提供通用的 `--wait`。Claude Code 具有原生的同机器 `notify_when_idle` 机制，但这并不涵盖远程会话、子代理或 Codex，且套接字/队列提交成功并非确认。因此 session-peer 报告 `capabilities.replyObservation.status: unsupported`，而不是去跟踪可变的脚本记录并冒误匹配的风险。当关注完成情况时，请要求目标向提供的 `Reply-To` 地址发送显式回复。可选唤醒功能仍在 [#46](https://github.com/abruption/session-peer/issues/46) 中跟进。

<a id="moving-from-cc-peer"></a>
## 从 cc-peer 迁移

仓库重命名和软件包过渡已经完成：[session-peer 0.6.0](https://pypi.org/project/session-peer/0.6.0/) 已发布，[cc-peer 0.5.1](https://pypi.org/project/cc-peer/0.5.1/) 是最终的仅支持 Claude 的兼容性版本。**旧的 PyPI cc-peer 项目已归档；GitHub session-peer 仓库仍保持活跃。** 现有的遗留分发包仍可下载，未因迁移而撤回（yank）。参见已完成的[过渡议题 #48](https://github.com/abruption/session-peer/issues/48)。

使用 `pipx install session-peer`、`uv tool install session-peer` 或[独立安装程序](#installsh)显式安装新产品。不会安装 `cc-peer` 命令别名。两款产品可以共存。在检查工作流之后，请使用安装旧软件包的同一包管理器将其移除，例如 `pipx uninstall cc-peer`。对于脚本安装，请使用固定 cc-peer v0.5.1 标签中的 `install.sh --uninstall`；运行前请检查其路径并备份本地自定义设置。新的卸载操作仅移除 session-peer 文件。

更新脚本和代理说明以调用 `session-peer`，并使用新的独立程序路径 `~/.local/share/session-peer/session_peer.py`，而非旧的 `~/.claude/skills/cc-peer/cc_peer.py`。新的 Claude 技能单独存放于 `~/.claude/skills/session-peer/`。Claude/Codex 配置、会话数据和旧安装不会自动迁移或移除。在方便时，将 `CC_PEER_REPLY_HOST` 替换为 `SESSION_PEER_REPLY_HOST`；旧变量仍保留作为回退项。

最终的 cc-peer 版本并不是持续提供功能或安全维护的承诺。冻结的根目录 `cc_peer.py` 保留在标签中以用于旧的自动更新 URL，但已从新的 wheel 和 sdist 中排除。其本地更新命令会引导用户来到此处，而不是安装其他产品。

## Claude Code 会话

### 优先使用官方功能

对于 Claude 到 Claude 的工作流，请首先考虑 Claude Code 内置的[跨会话消息传递](https://code.claude.com/docs/en/cross-session-messaging)和[远程控制](https://code.claude.com/docs/en/remote-control)。当该工作流不可用或不适用时，session-peer 提供了基于 shell 的本地/SSH 途径，并为 Claude 和 Codex 目标提供了统一的 CLI。本节中针对 Claude 的指导说明并非 Codex 队列的前提条件。

### 收件箱传输工作原理

Claude Code 的[会话收件箱套接字](https://code.claude.com/docs/en/cross-session-messaging#the-sessions-inbox-socket)接收一个 JSON 行：

```json
{"type":"user","message":{"role":"user","content":"your message"}}
```

session-peer 在拥有该收件箱的机器上发起连接。对于 SSH 发送，它将其源码通过管道传送到远程的 `python3 -` 并在那里建立连接，而不是转发 Unix 套接字。原生 Windows 目标则改用命名管道以及来自会话 `.key` 文件的认证行。

会话记录通常存放于 `~/.claude/sessions/<pid>.json`，并在 `messagingSocketPath` 中包含套接字路径。切勿盲目猜测 `/tmp/cc-socks/`：先前的测试发现该布局与 `/run/user/1001/cc-socks/` 同时存在。没有绑定收件箱的活跃 PID 将被视为不可达。记录模式是内部接口且可能会发生变动；使用 `session-peer list --all` 可检查陈旧或没有收件箱的记录。记录或套接字的存在并不能保证调用者拥有向其写入的权限。

### 接收端决定后续操作

**“已投递”不等于“已送达”。** 写入套接字成功；Claude 是否会读取该消息取决于该会话的[入站控制](https://code.claude.com/docs/en/cross-session-messaging#control-inbound-messages)。

消息可能会被暂扣以等待批准，或者被拒绝。在先前的验证中，处于 bypass 模式的接收者会暂扣由脚本发起的消息，直到获得批准。切勿从成功的套接字写入推断消息已被接收，也不要为了让测试通过而更改权限模式。

如果您特意希望某个工作进程在无人值守的情况下接收传入消息，请显式配置该接收端：

```json
{ "crossSessionInbound": "accept" }
```

如果这是针对单个工作进程的设置，请使用项目设置或 `--settings` 来限定其范围；用户设置也会影响该操作系统用户的其他会话。接受消息可能会开启接收轮次并消耗额度。session-peer 绝不会代您应用此设置，且接收端自身的工具权限仍然适用。

### 为什么不使用 `tmux send-keys`？

终端击键可能会落入正在运行的子进程或权限提示中，而不是预期的聊天输入中。相反，session-peer 使用代理的收件箱/队列边界。Claude 将收件箱消息视为对等文本，受其[接收会话规则](https://code.claude.com/docs/en/cross-session-messaging#how-a-session-treats-an-incoming-message)约束，而不是将其视作用户键入的批准。

## 限制

- **发送者身份是尽力而为的。** 当在可检测到的 Claude 或 Codex 会话中运行时，session-peer 会添加带有代理修饰的文本 `From:` 头。在该上下文之外，它可能会省略该头。这并非经过身份验证的身份协议；环境变量和会话注册表只是本地提示。
- **通告的回复需要一条可用的返回路径。** 当能够确定代理发送者和回复主机时，`Reply-To` 和兼容性的 `Reply:` 行会描述一条返回路由。正向 SSH 成功并不能证明反向 SSH 访问可行；请使用可选的 doctor 检查。该地址不授予任何访问权限，且 session-peer 不会关联或等待回复。
- **Tailscale 状态是本地路由提示。** 已知的在线对等节点通过其当前的 MagicDNS 名称进行寻址，已知的离线对等节点在发起 SSH 之前会被拒绝。未知的目的地仍然作为普通 SSH 处理；session-peer 并不声称每个 SSH 主机都属于 tailnet。
- **无法跨跳板机（bastion）进行发现。** `--host` 是单次 SSH 跳跃；请通过 SSH 配置的 `ProxyJump` 自行进行链式跳转。
- **目标端用户和执行权限至关重要。** Claude 收件箱和 Codex 状态/队列归目标账户所有。请使用正确的账户和主目录。`known_hosts` 条目不存储该账户。调用者的沙盒可能仍会拒绝访问；session-peer 不会绕过任何一个代理的权限或配额。
- **`--host` 和 `--ssh-opt` 的受信任程度与您的 ssh 配置相同。** 它们会被传递给 `ssh`，因此谁控制了它们就控制了连接的目标。会导致 ssh 运行本地命令的值（`ProxyCommand` 及其类似项）会被拒绝，且以 `-` 开头的 `--host` 会直接被驳回 —— 但如果您将 `session-peer` 加入代理的白名单，应将其视为授予了 SSH 权限，而不仅仅是消息收发权限。消息正文和会话名称没有此类风险：它们在传递到任何 shell 之前均会被引用（quote）。
- **Windows 支持。** 支持 Claude 的命名管道传输。`install.sh` 以及独立的远程安装程序/更新程序使用 POSIX shell；在原生 Windows 上请使用 Python 包管理器。实时的 Codex 验证仍仅限 macOS；Codex 目录、Reply-To、doctor 和 JSON 测试夹具在 Windows CI 中运行。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

默认测试套件不需要活跃的代理、SSH 服务器或网络。它包含遗留兼容性测试、共享 CLI 辅助函数、基于测试夹具的 Codex 发现和队列子进程测试，以及隔离的独立安装/共存检查。Codex 覆盖范围包括 argv/有效负载处理、目标目录选择、真实建议锁探测、稳定所有者证据、不分发消息的预检运行、失败/超时语义以及远程选项转发。多目录夹具复现了跨默认目录和 Orca/已配置目录的重复 UUID、唯一/多个/变动的写入者证据、安全失败的清单错误、显式选择、别名去重、单目录兼容性以及结构化的目录/提交元数据。它们绝不会根据保存的行推断活跃写入者，也不会向真实会话提交消息。更新通知覆盖范围检查了新鲜度和过期性、严格的稳定版本、原子私有写入、单飞（single-flight）后台刷新、退出行为、包管理器指引、多主机作用域以及故障隔离。

CI 在 Ubuntu/macOS 上配合 Python 3.9 和 3.13，以及在 Windows 上配合 Python 3.13 运行测试（在此跳过 POSIX 安装程序测试）。单独的作业使用 `shellcheck` 检查 shell 语法，检查独立安装/重新安装/卸载，以及 wheel/sdist 内容和安装。这并非完整的传输覆盖：Claude 发现夹具、真实 UDS 有效负载检查以及更广泛的退出码/远程命令回归测试仍在 [#28](https://github.com/abruption/session-peer/issues/28) 中跟进。

## 验证记录

### session-peer v0.8.0 候选版 (2026-09-16)

- 集成了来自 #76、#77、#78、#80 和 #82 的统一 Claude/Codex 列表、可选 MCP 工具和 Codex 插件、显式有界 Codex 唤醒、多目录 Codex 列表，以及具名消息和输出格式化选项。
- 有关 JSON 兼容性、可选依赖项、Codex 0.154.0 唤醒边界以及验证限制，请参阅 [v0.8.0 发布说明](releases/v0.8.0.md)。
- 在安装 MCP SDK 的情况下通过了 301 项本地测试；独立运行跳过了两项可选 SDK 测试。Wheel 和 sdist 独立安装并报告 v0.8.0。
- 发布准备工作不包括发布 GitHub Release 或上传到 PyPI。

### session-peer v0.7.0 (2026-09-16)

- 针对缓存更新通知、共享 JSON 信封、只读诊断、结构化 Reply-To 解析/路由、同机器规范化以及可选反向路由分类通过了 240 项本地测试。
- CI 覆盖了 Ubuntu 和 macOS（Python 3.9/3.13）、Windows（Python 3.13）、软件包构建和隔离安装、独立安装冒烟测试、shellcheck 以及机密扫描。
- 独立检查并安装了 wheel 和 sdist 内容。两个产物均报告 v0.7.0，并排除了冻结的遗留 `cc_peer.py`。
- 实际的 SSH doctor 运行找到了 Claude 收件箱以及有界的默认/Orca Codex 目录。其可选的反向探测独立于成功的正向连接报告了认证失败。未提交实时消息。

### session-peer v0.6.2 (2026-09-15)

- 针对特定 UUID 的 Codex 写入者验证、同机器回复本地化、SSH 目标用户解析以及结构化连接失败诊断通过了 198 项本地测试和发布构建检查。
- 独立检查并安装了 wheel 和 sdist 内容。两个产物均报告 v0.6.2，并排除了冻结的遗留 `cc_peer.py`。
- 在发布准备期间未提交实时消息。队列接受、消费、确认和反向 SSH 可达性仍属于不同的结果。

### session-peer v0.6.1 (2026-09-15)

- 在集成了带有重复目录保护、发送者代理信封和 MagicDNS SSH 路由的 v0.6.0 Codex 适配器后，通过了 174 项本地测试和发布 CI 检查。检查了 wheel/sdist 构建和隔离安装。
- 本地 Codex 列表和显式指定目录的预检运行在未提交的情况下成功完成。通过 Tailscale IP 提供的只读 SSH 列表经由当前的 MagicDNS `HostName` 连接，并保留了原始值作为 `sshHost`/`HostKeyAlias`。
- 作为发布准备工作的一部分，未提交实时消息。队列接受、消息消费、确认和反向 SSH 可达性仍属于不同的结果。

### session-peer v0.6.0 过渡 (2026-09-10)

- 通过了 134 项本地测试和发布 CI 检查。检查了 wheel/sdist 构建和隔离安装、实际的 PyPI 安装、包管理器更新保护以及旧版 CLI 的共存/移除。
- 在**两台 macOS 机器上运行 Codex CLI 0.154.0**，本地/SSH 已保存会话发现、预检运行以及实际的队列提交均能正常工作。提交的正文与队列记录匹配。这些检查确立了**已入队**，而非已消费或已确认，且并未确立可靠的活跃会话指标。
- 通过新 CLI 进行的 Claude 本地/SSH 收件箱写入成功。每周使用限额阻止了新的接收轮次/回复验证；这些写入不被声称为已完成的往返通信。
- 在两台 macOS 主机和两台 Ubuntu 主机上检查了独立 CLI/Claude 技能迁移。安装和只读发现检查并未启动代理轮次或更改入站设置。

有关发布流程和验证限制，请参阅 [RELEASING.md](../../RELEASING.zh-CN.md) 和 [#48](https://github.com/abruption/session-peer/issues/48)。

### 历史 cc-peer Claude 传输验证

在重命名之前，曾在 Tailscale 网络上通过 SSH 在五台机器上测试了 Claude Code **v2.1.263**：两台 macOS 26（Apple 芯片）、两台 Ubuntu 24.04（arm64，位于不同区域的 Oracle Ampere A1）以及一台 Windows 10 22H2。这些历史观察结果并不代表使用 session-peer v0.6.0 重复了每项测试：

- 从 macOS 向两个区域的 Linux 会话发送消息；每条消息都作为 `origin.kind: "peer"` 的 `type: user` 记录在接收脚本记录中。
- 有效负载完整性 —— 引号、反引号、`$HOME` 和表情符号逐字节完整送达。
- 暂扣路径：bypass 模式会话显示了批准对话框，并在批准后记录了 `Released 1 held cross-session message`。
- 实际环境中的两种套接字布局：一台 Ubuntu 主机上为 `/tmp/cc-socks/`，另一台运行相同构建的主机上为 `/run/user/1001/cc-socks/`。
- Windows 命名管道传输（`\\.\pipe\LOCAL\cc-msg-<hash>`），并带有从会话 `.key` 文件中读取的必需认证行。在 Windows 机器上验证了 `list`、`send` 和 `--host`。

两个代理的发现格式在各个上游版本之间可能会发生变化。先前成功的传输测试并不保证在较新的代理构建版本中仍能进行发现或投递。

## 许可证

MIT

### 组合会话发现

默认情况下，`list` 和 `list --json` 会同时查询 Claude 和 Codex。使用 `--agent claude` 可保留先前的仅 Claude 默认设置，或使用 `--agent codex` 仅查询 Codex。每个会话行都包含 `agent: "claude" | "codex"`；特定于代理的字段（如 PID 和线程 UUID）保持不变。人类可读的组合输出包含 AGENT 列。Claude 行排在 Codex 行之前，以保留 Claude 发现顺序；Codex 行按更新时间降序排列，然后按目录和 UUID 排序。

列表响应包含 `discovery`，以每个请求的代理为键，带有 `status: "ok" | "not_installed" | "error"`（中间状态仅限 Codex），以及针对失败来源的 `error` 说明。任何发现失败都会返回 `ok: false`、顶层错误摘要和退出码 1，同时保留成功发现的会话。未自动发现 Codex 安装属于正常的空结果（`not_installed`，退出码 0）；显式配置的目录缺失则属于错误。Claude 会话目录缺失属于空结果。两者都不是 Codex 进程正在运行的证据。格式错误的单个 Claude 记录将像以前一样继续被跳过。

这些语义同样适用于本地和通过 SSH 的场景。重复指定的主机在现有的有序数组中保留独立的结果；任何失败都会导致总体退出码为 1。Codex 列表包括默认目录、环境选择目录、Orca 目录和配置的目录。使用 `--codex-home PATH` 仅检查该目录。`--all` 保留 Claude 的陈旧/无收件箱记录，并包含已归档的 Codex 线程。

### 可选 MCP / Codex 插件

对于结构化、受目的地限制的 `list_sessions` 和 `send_message` 工具，请在 Python 3.10+ 环境下安装 `session-peer[mcp]` 并遵循 [MCP 设置](mcp.md)。默认策略仅允许本地列出。独立 CLI 和 shell 安装程序保留其现有的依赖项要求。

有关可选激活已入队 Codex 会话的说明，请参阅[显式唤醒](wake.md)。

有关候选来源、各目录错误、重复 UUID 以及为发送选择确切目录的说明，请参阅[多目录 Codex 列表](multi-home-list.md)。

### 内部扩展架构

代理适配器和本地/SSH 执行共享内部带版本的契约，同时保留单文件 CLI。参见[适配器开发](agent-adapters.md)以及[架构决策](architecture/agent-transports.md)。不支持外部插件加载。`doctor.capabilities.agents` 描述了已实现的 list/send/wake/wait/ack 支持；它并不授予权限或证明就绪状态。
