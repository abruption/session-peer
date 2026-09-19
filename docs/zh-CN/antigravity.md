# Antigravity CLI 适配器（实验性）

此实验性可选适配器在 session-peer v0.9.0 中可用。
使用 `pipx install session-peer` 或 `uv tool install session-peer` 安装。
发布版本可用性并不代表确立了长期的运维稳定性。
它使用了内部适配器/传输重构（#47），并可被授权作为配对设备投递的目标（#69）。
Antigravity 本身绝不会被自动安装。未过滤的列表包含活跃的桥接注册项。

它使用用户启动的本地桥接和[官方 agentapi 接口](https://antigravity.google/docs/sidecars/)投递到**现有 TUI**。
Mac 和 Linux CLI 1.2.4 实验验证了空闲状态下的投递。后续 macOS CLI 1.2.7 RC 测试在对齐文档中的 `agentapi send-message` 位置参数后，通过了直接投递和公共中继投递。CLI sidecar
自动启动机制**尚未**建立。`agy -p` 以及使用 `--conversation` 启动另一个
写入端并不是投递的替代方案。不支持 Windows 桥接操作；其他适配器在该平台上仍然可用。

## 从接收端 TUI 注册

要求接收端 agy TUI 通过其常规工具运行器执行此命令：

```sh
session-peer antigravity-bridge serve --thread FULL-CONVERSATION-UUID
```

以拥有该 TUI 的账户运行。归其他用户所有的工作区目录无法识别 CLI 的主目录。
默认主目录为 `~/.gemini/antigravity-cli`；使用 `--antigravity-home /absolute/path`
指定自定义主目录。注册会验证祖先 `agy` 进程、UID、启动时间以及针对该确切主目录
和对话打开的存在文件（presence file）。Linux 使用 `/proc`；macOS 使用 `ps`
和 `lsof`。在 macOS 上，进程启动时间使用固定的 C 语言区域设置读取，因此从本地化 TUI 启动的桥接仍可被使用其他语言区域设置的中继工作进程发现。打开的存在文件描述符是身份证据，**并非持有内核锁的证明**。
多个匹配的祖先注册不会用于推断发送方。

桥接继承已验证的工具环境并调用 `<home>/bin/agentapi send-message`。
它绝不会提取进程环境或复制令牌。切勿从不相关的 SSH shell 运行它、
伪造凭据或绕过工具权限拒绝。普通的 SSH 进程无法代表 TUI 创建此注册。
将其作为长时间运行的命令启动；就绪 JSON 意味着本地端点正在监听，
并不意味着模型已消费任何内容。

默认值：生命周期 3,600 秒（最大 86,400 秒），最多 1,000 个唯一请求（最大 10,000 个）。
`--ttl` 和 `--max-requests` 可调低或调高这些显式边界。
不会安装守护程序、全局 sidecar 配置或自动重启机制。

## 发现与发送

```sh
session-peer list --agent antigravity --host ubuntu@worker --json
session-peer send --host ubuntu@worker --to antigravity:FULL-CONVERSATION-UUID \
  --antigravity-home /home/ubuntu/.gemini/antigravity-cli \
  --antigravity-generation GENERATION-FROM-LIST \
  --message 'Please review the proposed change' --json
```

本地投递可省略 `--host`。普通的 SSH 传输将独立源码流式传输到目的地；
发送无需在远程安装软件包。接收桥接必须已经在运行。已注册的会话也会出现在
未过滤的 `list` 中，带有 `agent: antigravity`、`antigravityHome`、
`ownerPid`、`ownerStart`、`generation` 以及 `status: registered`。
该状态并不意味着空闲。发现范围为 `registered_bridges`：历史或未注册的
TUI 会话不会被枚举，即使使用 `--all` 也是如此。带有原因 `no_live_registration`
的 `not_installed` 表示没有活跃桥接，并非证明 agy 未安装。

`--antigravity-home` 过滤目的地上的已知注册。针对同一 UUID 存在两个活跃主目录
会导致 `ambiguous_home` 失败，除非进行了过滤。代际固定（generation pinning）
可防止通过被替换的注册进行投递。`--dry-run` 在不调用 agentapi 的情况下验证注册。
消息正文限制为 32 KiB UTF-8。原生发送者身份是接收端 TUI 的 agentapi 身份；
`From:` 标头是描述性的，不是对远程代理的加密身份验证。

## 结果契约

- `status: submitted`、`ok: true`、`submitted: true` 意味着 agentapi 以零状态码退出。
- `consumptionConfirmed: false` 仍为 false；不提供自动化的 ACK/等待机制。
  不支持 `--wake`。需要时请单独验证回复。
- 超时、启动失败、非零原生退出状态码或丢失桥接响应将返回
  `status: unknown`、`ok: false`、`retryAllowed: false`；切勿自动重新发送。
- 请求验证错误会在原生调用前被拒绝。请检查 `reason` 和 `error`。
  在获得结构化响应之前的远程传输失败也可能导致结果未知。
- `requestId` 和 `generation` 标识本次尝试。可选的 `--request-id UUID`
  需要 `--antigravity-generation UUID`。在**同一桥接代际**内使用相同的
  ID/正文将返回缓存的结果，且 `duplicateSuppressed: true`。使用该 ID 更改内容
  将被拒绝。不存在持久发件箱、跨重启重放或精确一次（exactly-once）保证。
  切勿更改 ID 来重试未知项。

桥接具有相同的 UID 检查和私有 `/tmp/session-peer-agy-UID` 目录（0700）、
注册和套接字（0600）、有界帧 JSON 读取以及 15 秒原生调用超时。
原生 stdout/stderr 会被丢弃；错误中不包含机密。传递给 agentapi 的消息正文
是原生进程参数，对拥有足够权限的进程检查可能是可见的。
以同一操作系统用户运行的其他程序属于同一信任边界内。

## 停止与重新注册

```sh
session-peer antigravity-bridge stop --thread FULL-CONVERSATION-UUID
```

在接收机器/账户上使用相同的主目录选项（如果进行了自定义）运行。
停止、TTL、属主终止、SIGINT/SIGTERM/SIGHUP 会移除套接字和注册。
活跃的原生请求可能会将其清理推迟 15 秒截止期限。SIGKILL 或机器故障
无法运行清理；下一次启动服务在移除陈旧文件前会持有排他锁，并使用新的代际。
小锁文件会特意保留以防止拆分锁竞争。请勿解除活跃锁文件的链接。

TUI 重启后，从该 TUI 显式重新注册。发现会再次检查属主，因此仅凭陈旧路径
或重用的 PID 是不够的。权限或检查失败无法使会话变为可发送。
当不存在活跃桥接时，`doctor` 将 Antigravity 报告为 `disabled`；
此可选功能不会降低原本正常的 Claude/Codex 设置的健康状态。

MCP 需要显式的目的地 `agents: ["antigravity"]` 和 `send` 权限；
源端注册不授予发送权限。MCP 目前无法固定自定义 Antigravity 主目录/代际；
请使用 CLI 进行该控制。多个主目录仍具有歧义并采取安全失败（fail-closed）。
Reply-To URI 携带 agent/UUID，而不是主目录固定。

## 验证

`python3 -m unittest tests.test_antigravity -v` 涵盖分片/无效/超大帧、
精确目标/代际检查、PID 重用、权限、请求冲突、超时、dry-run、
SSH 结构化结果、发送者身份和 MCP 允许列表。真实的 Unix 套接字 +
子进程测试夹具在没有模型凭据的情况下测试 SIGTERM 清理和陈旧重启。
有关实时测试边界和剩余工作，请参阅[开发验证](validation/85-antigravity.md)。
