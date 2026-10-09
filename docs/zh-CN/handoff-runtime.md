# Handoff 运行时候选实现

这是 [#181](https://github.com/abruption/session-peer/issues/181) 的未发布候选实现，不是已发布 Python v1.0.4 的功能。[已确定的 Handoff v1 设计](contracts/handoff-v1.md)及合成验证数据保持不变；本候选实现尚未完成所有设计验收条件。

## 候选实现支持的路径

同一 POSIX 机器的 Claude 收件箱提交可以使用用户明确初始化的私有记录及独立的私有收据收集器。连接端的 PID、原始进程创建信息和登记端点必须匹配所选代次。同一 POSIX 机器的 Codex 支持带关联 ID 的队列提交，但不发放收据权限，目标代次保持 null。必需的送达或确认等待在队列调用前拒绝；尽力而为的确认、观察请求返回 unsupported，同时保留实际队列提交事实。不会启动模型或会话。无正文的 Codex 观察、有界 Windows 管道、配对设备以及 SSH handoff、收据路径尚不支持。原有普通本地和 SSH 行为及 Codex wake 版本限制不变。

```sh
session-peer handoff init --json
session-peer handoff prepare --to worker --message-file ./private-message.txt --json
session-peer send --to worker --message-file ./private-message.txt --correlation-id PREPARED_UUID --request-ack --wait-for acknowledged --wait-timeout 30 --json
session-peer handoff status --correlation-id PREPARED_UUID --json
session-peer handoff wait --correlation-id PREPARED_UUID --wait-for acknowledged --wait-timeout 30 --json
session-peer ack --receipt - --json
session-peer handoff confirm --receipt - --json
```

消息必须来自仅所有者可访问的普通 UTF-8 文件。请使用 prepare 返回的 ID，而非示例占位符。收据和人工确认 JSON 只通过私有标准输入传递。接收方按自身常规权限流程决定是否提交收据。委托的收据权限不授权其他工具调用、消息发送、模型唤醒或对话记录读取，不推断自动答复。

候选发送接受命名选项、位置参数中的正文、私有消息文件或有界 POSIX 原始标准输入。标准输入使用原有提交截止时间，严格验证 UTF-8，并限制为 400 万原始字节、100 万码点。未结束的管道或 SIGINT 在创建提交意图前拒绝，不虚构 epoch、提交结果。收据和人工确认标准输入是独立的大小与时间限制 API。选择性多主机发送及远程 handoff 响应验证仍是未完成的实现条件。原有普通发送的标准输入和多主机行为不变。实际提交使用共同的外部消息边界，逐行引用正文；最终字符限制包含边界和收据权限。

Codex 准备会私下记录规范线程、保存目录及有界的原始目录、写入进程判断。复用准备好的 ID 时若判断改变，会拒绝而非重新绑定目标；这不是原子的进程代次或消费证明。原有存活写入进程及显式非活动目录规则不变，在唯一一次队列调用前重新检查原始判断。版本查询和队列共用 #268 的目录检查、环境规范化，但原生配置层、守护进程保证仍属于该 issue 的未决调查。有界的专属 POSIX 子进程使用原始截止时间、清理预算，限制原始输出、诊断大小。完整且目标匹配的队列响应可在超时、异常退出后保留 queueId、提交事实；无响应、目标不符、不完整、非法 UTF-8、超限输出即使退出码为 0 也保持 unknown，绝不重发。stderr 诊断不提供提交证据，不调用 app-server、正文或对话记录 API。

发放权限前会检查受保护的准确脚本、Python 解释器及该脚本的 ACK 命令。私有提交输入指定该隔离 Python 收据处理器和记录路径，不依赖 PATH 中未经验证的 session-peer；原始权限令牌仅通过标准输入传递。收据及人工确认输入在 EOF 前共有五秒期限和 4096 字节上限。提交后存储失败时保留独立验证的目标、字符数和 dry-run 事实，省略无法证明的 handoff/ACK，返回失败且禁止重试。

## 证据、隐私和时间限制

完整的收件箱写入只表示提交，不表示消费或轮次完成。只有经认证且对应请求的收据，或时间顺序可证明的明确操作者确认，才能产生 acknowledged。写入或读取响应期间提前到达的收据先保存为有界的未分类证据。仅在提交事实及原始时钟顺序独立成立后分类，不凭空创建收据或回填 ACK 时间。已提交的 ACK 在收集器重启后保留；未使用权限保守失效。即使过期后的重复请求，也必须证明原始令牌哈希。人工确认不会重写旧等待。

Python Claude 原本省略的字段保持省略，不填充 false/null。等待失败仍保留已知提交事实。中断进行中的等待会记录 stopped，并以完整结构化输出和退出码 130 返回；随后状态查询可以退出码 0 成功。状态、等待、收据、人工确认均不提交原生消息。记录缺失、损坏或 ID 未知时返回单独的 handoffQuery 错误，不伪造 epoch。禁止自动重发或改用另一传输路径。

每台目标机器的总预算从准备前开始，默认 30 秒，只接受 ASCII 整数 1..60。总预算内精确保留 5 秒用于清理；观察和提交在总预算减 5 秒时停止，诊断期限也表示该边界。5 秒及以下在提交前拒绝。Python 无法强制取消文件系统、身份检查或 fsync，因此不声称所有环境下的严格实时延迟保证。

原始令牌仅进入授权的原生消息输入、私有 IPC 和标准输入，不进入发送方或收集器的一般输出、参数、URI、环境变量或自身日志；日志只保存哈希。接收方队列或历史可能保留委托令牌，同一用户权限的其他读取者也可能取得它。token_possession 不等于独立的模型身份认证。不读取接收方对话记录。

## 存储方式和剩余条件

2026-10-09 时钟调查：[CPython 3.9.25 的 Darwin 实现](https://github.com/python/cpython/blob/0bbaf5de9744ae1acea3e2c9ad2257d1cc68e847/Python/pytime.c#L823) 会减去各进程独有的起始 tick。候选实现让 Darwin 发送端、记录和收集器共用经过类型验证的 mach_absolute_time/mach_timebase_info 纳秒，其他平台使用原生单调时钟。收件箱处理器仅收到转换到自身时钟域的剩余时间，不收到持久化的跨进程时间戳。缺失或无效的时钟证明会拒绝，旧候选记录不会被静默解释为新时钟。测试比较真实父子进程样本；macOS Python 3.9 也由 CI 单独验证。

POSIX 私有目录为 ~/.local/share/session-peer/handoff。原子保存、fsync 及固定排他锁在实际提交前消耗首次尝试权限。之后即使崩溃发生在真正写入前，也保留 unknown。预先保留未来收据、等待和原生结果空间；10,000 条及 32 MiB 限额包括墓碑和预留空间，不自动驱逐防止重复提交的记录。每条意图最多有 64 次独立等待。

仅在原生启动身份及单调时钟连续性得到证明时，30 天后才将详情压缩为绑定目标的墓碑；无法证明则保守保留，可能更早耗尽容量。跨重启保留仍需验收审查。已知恢复副本在重新使用前必须由操作者明确调用 HandoffLedger.quarantine_restored() 隔离。CLI 恢复和核对工具仍未完成。归档和重新初始化是明确的操作者行动，不自动修复。未标记的回滚或克隆无法可靠检测。不会自动删除或重新绑定旧收集器套接字。收集器最多运行 24 小时，收据权限 TTL 从原始意图的持久提交起算 24 小时，重启撤销未使用权限。发布前仍须检查生命周期和失效与完整设计的一致性。

验证使用专属本地 Unix 收件箱、真实连接 PID 与进程创建信息、私有收集器和标准输入生产者子进程、专属 SQLite 与模拟 Codex 队列子进程、有界原始输入，以及严格 JSON、并发启动、崩溃围栏、延迟、重复、过期收据和 SIGINT 测试。模拟队列、版本信息不证明真实 Codex 会话或所有原生版本兼容。不证明真实 Claude 模型消费、Codex 观察器、远程初始化或 Windows 清理。剩余验收条件解决前 #181 保持开放，确定的设计数据不作为运行时认证。
