# 诊断与回复地址契约

`session-peer doctor` 检查拥有目标会话的机器。搭配
`--host` 时，相同的标准库脚本会通过 SSH 在该主机上运行，因此路径、
用户、进程、套接字和数据库均在正确的安全边界内进行评估。

该命令为只读操作。它不会连接到 Claude 收件箱、提交 Codex
队列项、扫描任意文件系统根目录、更改权限、登记 SSH
主机密钥或修改 agent 设置。

## JSON 模型

Doctor 使用通用响应信封。`ok` 表示诊断
命令是否已运行；这并不意味着每个可选 agent 都已安装或可用。
请使用嵌套状态来判断：

```json
{
  "schemaVersion": 1,
  "ok": true,
  "host": "worker.example.ts.net",
  "command": "doctor",
  "status": "partial",
  "claude": {
    "status": "inbox_unavailable",
    "sessionsDir": "/home/alice/.claude/sessions",
    "records": 1,
    "invalidRecords": 0,
    "aliveSessions": 1,
    "availableInboxes": 0,
    "checks": [
      {"status": "warning", "code": "inbox_unavailable", "message": "..."}
    ]
  },
  "codex": {
    "status": "available",
    "selectedHome": "/home/alice/.codex",
    "homeSource": "default",
    "executable": "/home/alice/.local/bin/codex",
    "homes": [
      {
        "codexHome": "/home/alice/.codex",
        "stateDb": "/home/alice/.codex/state_5.sqlite",
        "status": "available",
        "code": "state_db_readable",
        "sessionCount": 12
      }
    ],
    "checks": []
  },
  "capabilities": {
    "replyObservation": {
      "status": "unsupported",
      "reason": "no_cross_agent_acknowledgement_api",
      "claudeLocalIdleNotice": "native_claude_only",
      "automatedWait": false
    }
  }
}
```

当两种 agent 传输都可用时，顶级 `status` 为 `healthy`；
当其中一种可用时为 `partial`；两者均不可用时为 `issues_found`。Agent
状态包括：

| Status | Meaning |
| --- | --- |
| `available` | 所需的本地证据可读且存在。在实际发送之前，Claude 收件箱验证仅限于文件系统检查。 |
| `unavailable` | 未找到存活的可用会话。 |
| `inbox_unavailable` | 记录到了存活的 Claude 进程，但没有可用的收件箱。 |
| `missing_tool` | 目标上没有 Codex 可执行文件。 |
| `missing_home` | 配置的会话目录或 Codex 状态数据库不存在。 |
| `wrong_home` | 配置的路径具有错误的文件类型。 |
| `permission_denied` | 目标操作系统用户无法检查所需的路径或记录。 |
| `unsupported` | 已知文件存在，但其 schema 不受支持。 |
| `unknown` | 检查未能证实更具体的状态。 |

Code 值为稳定的机器可读原因。Message 供人类阅读，并
可能在不变更 schema 的情况下变得更加具体。

## 返程路由检查

`doctor --host worker --check-return-route` 要求 `worker` 测试一条返回
所检测来源的 SSH 命令。`--reply-to USER@HOST` 会覆盖该检测到的
地址。该检查使用固定的 `true` 命令，并禁用了批处理模式、密码和
键盘交互式身份验证，启用了严格主机密钥检查，并
禁用了主机密钥更新。它绝不会使用凭据或放宽策略进行重试。

```json
{
  "returnRoute": {
    "status": "failed",
    "transport": "ssh",
    "host": "alice@origin.example.ts.net",
    "reason": "authentication_failed",
    "sshUser": "alice",
    "sshUserSource": "explicit"
  }
}
```

返回状态为 `verified` 或 `failed`。失败原因包括
`return_host_unavailable`、`ssh_executable_missing`、`authentication_failed`、
`host_key_failed`、`timeout`、`transport_failed` 和 `remote_command_failed`。
当前机器上当前用户的返回地址会被规范化为已验证的本地路由，
绝不会启动 SSH。

## 结构化 Reply-To

消息现在携带一个惰性的、带版本的 URI，其后是旧版命令：

```text
Reply-To: session-peer://v1/reply?agent=claude&session=api-worker&transport=ssh&host=alice%40origin
Reply: python3 /path/to/session_peer.py send --host alice@origin --to api-worker --no-reply-to
```

该 URI 可以作为 `send --to URI` 传入。在发现或派发之前，会对版本、字段名、重复字段、
agent、传输、UUID、主机、控制字符以及冲突的 CLI 路由
标志进行验证。其内容绝不会被解析
为 shell 语法。各字段为：

| Field | Requirement |
| --- | --- |
| `agent` | 必需：`claude` 或 `codex`。 |
| `session` | 必需的会话名称/PID，或完整 Codex UUID。 |
| `transport` | 必需：`local` 或 `ssh`。 |
| `host` | 仅 `ssh` 必需；已知时包含 SSH 用户。 |
| `codexHome` | 当发送方能够识别其处于活动状态的已配置主目录时，对 Codex 可选。 |

发送 JSON 包含置于发出消息中的路由信息的 `replyRoute`。
本地路由为 `verified`；SSH 路由在可选的
doctor 探测成功前为 `unverified`，原因为 `reverse_ssh_not_checked`。当 `--to`
使用结构化地址时，`addressResolution` 会记录其选定的传输方式
以及任何 `ssh_self` 规范化。

## 为什么没有通用的 wait

Claude Code 文档记录了针对主 Claude 对话监视另一个本地 Claude 会话的原生
单次 `notify_when_idle` 订阅。同一
文档将其限制为该机器上的会话，并排除了子 agent、
agent 团队成员以及该机器之外的会话。Codex 队列提交
也未通过 session-peer 公开任何跨 agent 确认机制。

因此，便携的 `--wait` 将需要从可变的
转录记录中推断完成情况。新的转录事件可能属于另一个请求，而
缺失的事件可能意味着挂起输入、离线会话、更改的存储
格式或未完成的轮次。session-peer 将该功能报告为
`unsupported`，而不是返回虚假确认。对于完成
工作流，请在消息中放入需求和关联令牌，并要求
目标向其 `Reply-To` URI 发送一条新消息。

参考资料：[Claude Code 消息投递](https://code.claude.com/docs/en/cross-session-messaging#message-delivery)、
[空闲通知](https://code.claude.com/docs/en/cross-session-messaging#get-a-notice-when-another-session-goes-idle)
以及 [会话收件箱套接字](https://code.claude.com/docs/en/cross-session-messaging#the-sessions-inbox-socket)。

## List 发现结果

`list` 默认列出两个 agent；`--agent claude|codex` 选择其中一个。
`discovery` 对象报告每个请求的 agent。Claude 保留 `ok`/`error`；
Codex 报告 `ok`、`not_installed` 或 `error`，以及每个主目录的诊断信息。
失败会保留成功的行，但设置 `ok=false`、顶级错误摘要
和退出码 1。未自动安装 Codex 为 `not_installed`，这是一个
退出码为 0 的空结果。缺失显式配置的主目录仍为错误。
缺失 Claude 会话目录为空结果；不可读目录
为错误。SSH 会保留部分结果和重复主机的信封。
每一行都有一个 `agent` 鉴别器。有关候选发现、
元数据和权限边界，请参见[多主目录列出](multi-home-list.md)。

## CLI 输入与输出选择

在 list/send/doctor/update 上使用 `--output-format json` 获取结果信封；
`--json` 仍为别名。`--output-format text` 是默认的人类可读输出。
这些选项不会将发送主体解释为 JSON。请使用 `send --message TEXT`
（或 `-m TEXT`）、旧版位置消息或标准输入（`--message -`）。
矛盾的输出标志属于用法错误（输出至 stderr，退出码 2）；冲突的主体
来源会在读取标准输入或派发之前失败，并以所选结果格式
输出，退出码为 1。现有的 CLI、SSH 和 MCP 提交/接收语义保持不变。
