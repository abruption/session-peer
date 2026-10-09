# 显式 Codex 唤醒

## 连续 wake 的限制

CLI 和 MCP 在入队前读取 `SESSION_PEER_WAKE_DEPTH` 和 `SESSION_PEER_WAKE_ORIGIN`，每次 wake 将层数加一并保留来源 UUID。默认上限为 3 层，超过时返回 `wake_depth_exceeded`，不提交内容。运维人员可以通过 `--wake-max-depth` 或 `SESSION_PEER_WAKE_MAX_DEPTH` 在 0–16 范围内显式调整；0 禁用 wake。无效或不完整的上下文在提交前以 `invalid_wake_context` 拒绝。普通发送仍只入队，行为不变。

所拥有的 app-server 接收递增后的上下文。SSH 通过验证类型的参数传递上下文，不依赖环境转发；目标端可以降低携带的上限，但不能提高。多个目标保持同一来源，但预算独立。MCP 读取启动时的环境，不能认证调用线程。Wake 在队列消息前添加诊断标记，并在提交或成功的 dry-run 后添加包含 `depth`、`origin` 和 `maxDepth` 的 `wakeProvenance`。标记也计入 32 KiB 上限。标记和正文都不授予权限；不会读取队列、历史或对话正文来恢复层数。

非活动目标的激活默认按规范化 home 和线程计算，每 60 秒最多 3 次。运维人员管理的 `SESSION_PEER_WAKE_TARGET_RATE` 接受 0–16；0 禁止激活非活动目标。预留记录存于现有 wake 锁下。`wake_rate_exceeded` 在入队前拒绝，无法读取、过大或格式错误的状态以 `wake_rate_state_invalid` 拒绝。失败或中断仍占用名额，时钟回退时保守地保留记录。Dry-run 和已确认活动的写入进程不消耗激活名额。现有 `wake_in_progress` 和 `already_active` 不变。不同目标或主机的预算独立，运维人员或同用户进程可重置协作状态，所以这不是全局费用上限或调用者认证。

固定的 Codex 0.154.0 源码中，shell 的 `inherit="all"` 在没有排除规则或 `include_only` 过滤时保留这些变量；`inherit="core"` 和 `inherit="none"` 在没有显式设置时删除。默认敏感名称过滤不匹配它们。stdio MCP 默认允许列表不包含它们，新 MCP 进程需要显式 `env_vars` 转发。已有或共享 MCP 进程不会获得后来调用者的环境。静态 `env` 配置可能重置上下文或产生冲突。上下文丢失后创建新的本地来源，因而无法保证全局层数上限；本地激活速率是独立的补充防护。不自动修改审批、配置或原生环境策略。

隔离子进程测试验证 CLI、MCP、SSH 上下文及 app-server 替代进程的环境。另有需明确选择的原生测试，验证 macOS arm64 版 Codex 0.154.0 的实际环境构建路径：`command/exec` 的 6 种 shell 策略，以及通过 `mcpServerStatus/list` 启动专用 stdio MCP 测试服务器的 4 种情况。该服务器没有回执功能。仅检查合成环境信息，不使用用户凭据、线程、轮次、提示词、模型、MCP 工具调用或 wake。将单独准备的固定二进制文件指定为 `SESSION_PEER_CODEX154_ENV_BINARY`，然后运行 `python3 -m unittest tests.codex.test_wake_native_environment`。测试不下载或安装任何内容，并拒绝不匹配的二进制文件。未指定时跳过，不能视为原生执行证据。发行压缩包的 SHA-256 为 `344310a0a591c1b192e04feff304321a69907c9498baaac331ca7e16ebcef9d7`，解压后的二进制哈希也固定在测试中。这仅证明该平台和版本的环境路径，不证明模型轮次、实际 wake、其他平台或后续 Codex 版本。来源：[固定 shell 策略](https://github.com/openai/codex/blob/6b9826e3aa83b1a5947db50f4332cb9c65f1b340/codex-rs/protocol/src/shell_environment.rs)、[固定 MCP 环境](https://github.com/openai/codex/blob/6b9826e3aa83b1a5947db50f4332cb9c65f1b340/codex-rs/rmcp-client/src/utils.rs)、[当前配置参考](https://developers.openai.com/codex/config-reference/)。

`session-peer send --to codex:<uuid> --wake --wake-timeout 30 "message"`

普通 send 仍为仅入队。Wake 可能会产生模型使用量，并在目标现有配置下修改会话历史记录和项目文件。它需要 macOS/Linux 以及 **Codex CLI 0.154.0**，即生命周期和原生写入器排他性经过测试的版本。在经过独立验证之前，其他版本会遵循故障关闭。此版本边界仅适用于 wake。

操作员可以像往常一样选择 `--codex-home` 和 SSH `--host`。原始工作目录来自该主目录保存的线程记录。在入队之前，缺失、已归档、未初始化、未知所有者和目录不可用的目标将被拒绝。不会直接修改任何状态/队列数据库。session-peer 防护会针对相同的规范主目录和 UUID 串行化唤醒请求；原生 Codex 的写入器锁也能防止无关的同时恢复。

## 原生生命周期

`codex exec resume UUID` 在 0.154.0 中需要 prompt，并且在不添加输入的情况下无法激活队列。Wake 改为启动原生的 `codex app-server`，初始化其 stdio 协议，然后使用确切的 UUID 和原始 cwd 调用 `thread/resume`。恢复本身会消费挂起的队列消息；session-peer 绝不会调用 `turn/start`、将消息复制到 prompt 中、分叉线程、解锁写入器或更改信任/沙箱/审批配置。交互式审批请求会显式失败。app-server API 是实验性的；支持其他 CLI 版本需要重新验证。

已处于活动状态的写入器会接收一次队列提交，且不会启动第二个进程。对于不活动的目标，wake 会在截止时间（默认为 30 秒，范围 1–60）内等待一次原生轮次完成。随后它会终止其所属的进程组。这**不是**持久的后台 worker，也不是排空整个队列的保证。长时间运行的轮次可能会因超时而中断；可能会残留部分工作。现有的活动进程绝不会被终止。

相同的生命周期和超时也在 SSH 目标上运行。连接丢失并不证明未送达。即使调用方断开连接，远程唤醒也具有其自身受限的生命周期。取消操作会尝试正常终止所属进程，然后进行强制清理。不会发生自动重新发送。

## 结果

现有的提交字段保持不变：`submitted`、`queueId`（当原生队列返回时）、`codexHome`、`status` 和 `consumptionConfirmed`。一个独立的 `wake` 对象包含 `status`、`reason` 以及解析后的 `cwd`。

- `validated`：仅 dry-run；未排队或启动任何内容。
- `already_active`：消息已排队；现有写入器保持运行。
- `completed`：原生恢复轮次已完成。
- `refused`：安全/预检要求未满足。
- `failed`：原生传输、恢复、审批或轮次失败。
- `timed_out`：所属激活超出截止时间并尝试了清理。
- `unknown`：中断或模棱两可的激活结果。

提交可以成功而唤醒失败。在此情况下，CLI 退出码非零，并且 JSON 保留队列 ID、`submitted: true` 以及失败信息。**切勿自动重新发送。** `completed` 不是特定队列项已被接收的证据；`consumptionConfirmed` 保持为 false。先前排队的项或不同的并发提交可能是已完成的轮次。

对于 MCP，请在目标功能中同时添加 `send` 和 `wake`，然后调用 `send_message(..., wake=true, wake_timeout=30)`。仅有发送权限并不会授予唤醒权限。将客户端的 MCP 超时配置为高于整个队列/SSH/唤醒预算（例如 150 秒）；否则客户端超时可能会掩盖已提交的结果。

<a id="validation-evidence"></a>
## 验证证据

在配备 CLI 0.154.0 的 mac-mini-m4 上，一个隔离的测试线程被初始化、停止、排队并通过 app-server 恢复，且无需新的 prompt。观察到了原生轮次开始/轮次完成事件。在第一个 app-server 持有相同 UUID 的同时进行第二个 app-server 恢复操作失败，提示 `already has an active writer`。随后，针对另一条受控消息，实现的 CLI 返回了 `submitted: true`、一个队列 ID 以及 `wake.status: completed`。未使用任何项目信任或审批绕过标志。

自动化测试使用测试固件 SQLite 数据库、真实咨询锁和原生进程替代品。它们涵盖了不活动/活动/已归档/缺失的目标、默认的仅排队行为、截止时间和审批失败、进程清理、并发防护拒绝、中断的提交、远程部分结果保留以及独立的 MCP 权限。实时模型/SSH 检查为人工操作；公开 CI 不会接收模型凭据。

真实的 Codex 0.154.0 MCP 客户端随后完成了本地 list/send/wake 以及使用远程 Orca 自定义主目录进行的 mac-mini → macbook list/send/wake。远程默认主目录吊销了身份验证：其已排队的提交和失败的原生轮次被保留为部分失败，而未更改身份验证或重新发送。本地和 KR SSH Claude 协议测试收件箱也各自从真实 Codex MCP 客户端接收到了一条消息。这些是专用的协议测试固件，而不是生产环境 Claude 对话。

最初的非交互式 Codex 测试在其现有审批策略下按预期拒绝了写入工具。成功的测试显式设置了测试客户端的 `mcp_servers.session_peer.tools.send_message.approval_mode="approve"`，并在服务器策略中仅授予了测试目标权限。随附的插件并未设置此审批覆盖。插件市场注册和安装在一次性 CODEX_HOME 中进行了验证；生产环境插件配置未受影响。实时唤醒在 macOS 上进行了测试；Linux 进程/锁行为由 CI 测试固件覆盖，而非带有凭据的模型运行。

macOS/Linux 清理在回收组长前向所属进程组发送 TERM 后再发 KILL，包括忽略 TERM 的子进程。清理后不复用组 ID。脱离到其他会话的进程和远程进程不在范围内；清理不撤回已经提交的请求。
