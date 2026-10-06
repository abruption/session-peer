# Handoff v1 契约 — 设计提案 v0.2

## 状态与来源

这是面向 Python #181 和 TypeScript 0.4.0 设计审查的未实现设计。它不是已冻结的协议、发布承诺，也不是实际 ACK 支持的证据。合并本文档不授权运行时实现、发布、原生提交或运营变更。夹具包含的是合成示例，而非已记录的投递。

已发布的 Python 参考版本是 [v1.0.3](https://github.com/abruption/session-peer/tree/0d252550ab40c26d1ac4a19193df6ca2f84d830b)。常规输出的源代码是 [adapters](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/adapters.py)、[Codex](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/codex.py)、[SSH](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/ssh.py) 和 [output](https://github.com/abruption/session-peer/blob/0d252550ab40c26d1ac4a19193df6ca2f84d830b/session_peer_core/output.py)。[共享夹具](https://github.com/abruption/session-peer/blob/main/tests/fixtures/handoff-v1.json) 区分了规范化的旧版示例与提议的显式启用示例。运行时参考版本与设计夹具的固定版本相互独立：不会将 TypeScript 已发布的历史参考版本悄然改为尚未发布的 Python 版本。

## 证据与兼容性

提交指原生传输层的接受；投递指准确的原始用户消息 ID 被注入准确的原始目标代次的证据。确认应答是具有明确关联的回执，不代表完成、承担责任，也不证明模型读过每个字节。删除队列、进程退出、轮次完成、没有回复以及成功的状态查询都不是 ACK。未知的原生轮次状态绝不会变成 completed。

常规 send 输出继续保留各运行时的格式。Python Claude 成功时省略 status、submitted 和 consumptionConfirmed；Codex 的 queued 成功包含 submitted true 和 consumptionConfirmed false。submitted false 的旧版 unknown 不是未发生任何效果的普遍证明。不要添加缺失的 false/null 字段、重新解释可选字段的缺失、覆盖 consumptionConfirmed 或更改常规退出码。规范化的夹具值只隐藏身份信息；每个示例都记录来源，但不构成完整的输出模式。

显式启用会在现有外层 schemaVersion 1 下，向每个目标结果添加一个 handoff 对象。不存在 fanout 层级的 handoff。显式等待只能更改外层 ok 和退出码：它保留原生 status、target、queueId、submitted、consumptionConfirmed，以及所有独立有效的提交证据。结果接收方必须使用自己的原始请求上下文来选择这一验证模式，不能使用不可信的返回字段。只有原始请求是显式等待，且 handoff 经过完整验证、具有原生提交证据并匹配原始原生目标时，才允许将 queued/posted、submitted true、ok false 和退出码 1 的组合视为等待失败。仅收到 handoff 绝不会在未启用请求中允许这一组合。此等待失败路径也执行 target/home 验证。尽力而为的观测失败不能改变原生提交成功。无效或超限的 handoff 不能抹除单独验证且目标正确的原生快照，也不能将其提升为 ACK；显式等待会验证失败，且不会重新提交。错误的原生目标不构成独立有效的提交证据。

## 公开模式

以下语法是本提案的规范。除运行时特有的外层封装外，所有对象都是封闭对象。问号表示可选且不可用时省略；可为 null 的字段在下方明确列出。条件规则列于语法之后。

```text
handoff.schemaVersion = 1
handoff.correlationId = UUID-v4 lowercase canonical
handoff.ledgerEpoch = UUID-v4 lowercase canonical
handoff.state = validated | refused | submitted | delivered | acknowledged | unknown | timed_out_unknown
handoff.submission.status = not_attempted | submitted | refused | unknown
handoff.observation.status = not_requested | pending | observed | unsupported | failed
handoff.observation.injectionObserved = boolean
handoff.observation.clientUserMessageId? = safe-id
handoff.observation.turn? = {id: safe-id, status: running | completed | failed | interrupted | unknown}
handoff.ack.status = not_requested | pending | acknowledged | unsupported
handoff.ack.assurance? = token_possession | operator_confirmed
handoff.ack.receivedAtUtcMs? = safe-integer
handoff.ack.late? = boolean
handoff.wait.for = none | delivered | acknowledged
handoff.wait.status = not_requested | pending | satisfied | timed_out_unknown | stopped | unsupported | failed
handoff.wait.operationId? = UUID-v4 lowercase canonical
handoff.wait.deadlineAtUtcMs? = safe-integer
handoff.wait.reason? = insufficient_budget | deadline_before_effect | evidence_unsupported | evidence_failed | history_unavailable | stopped_by_operator | invalid_handoff
handoff.targetGeneration = safe-generation | null
handoff.decisionOwner = sender_operator
handoff.retry = {allowed: false, reason: receiver_dedup_unavailable}
handoff.nextActions = unique subset of [keep_waiting, reconcile, stop_waiting]
```

投递需要观测到注入、准确的 clientUserMessageId，以及非 null 的原始 targetGeneration。轮次证据需要观测到注入；轮次与回执状态相互独立。接受回执不会凭空产生注入证据。acknowledged 状态需要 acknowledged ack，并带有 assurance、回执时间和 late 标志；其他 ACK 状态省略这些字段。submitted、delivered 和 acknowledged 状态需要 submitted submission。validated 需要 not_attempted；refused 需要 refused；unknown 需要 unknown。超时状态允许 submitted 或 unknown，绝不允许 refused/not_attempted。

每次显式等待都具有 operationId 和截止时间，即使是在效果发生前拒绝。无等待的记录两者都没有。satisfied 的 delivered 等待需要注入证据；satisfied 的 acknowledged 等待需要有效 ACK。stopped/failed/unsupported 等待保留已知的效果证据。nextActions 取决于有效且经过验证的通道以及保留的历史：不受支持或已过期的通道绝不提供 keep_waiting。stop_waiting 只结束观测，不取消原生工作。所有原生本地/SSH 结果都禁止重试。v1 中没有 resend_same_id 操作；仅有关联和用户批准不能确立安全重发。接收方去重（#182）不是实现此禁止重发契约的前提条件。

## 状态与退出码元组

缺失表示旧版字段仍然不存在。原生表示各运行时未更改的快照。同一张表适用于本地和 SSH，不适用于尚未实现的配对设备传输。

| 模式 / 证据 | state | submission | wait status | 外层 status / submitted | ok / 退出码 |
| --- | --- | --- | --- | --- | --- |
| 常规 send | 缺失 | 缺失 | 缺失 | 原生 / 原生或缺失 | 原生 |
| 显式启用的 dry-run | validated | not_attempted | not_requested | 原生 / 原生或缺失 | true / 0 |
| 效果发生前所需通道不可用 | refused | refused | unsupported | 存在时为原生 / 无合成字段 | false / 1 |
| 确定在效果发生前耗尽预算 | refused | refused | failed | 存在时为原生 / 无合成字段 | false / 1 |
| 已知入队，尽力而为的观测器失败 | submitted | submitted | not_requested | queued / true | true / 0 |
| 已知入队，显式 ACK 截止时间到期 | timed_out_unknown | submitted | timed_out_unknown | queued / true | false / 1 |
| 已知注入，ACK 截止时间到期 | timed_out_unknown | submitted | timed_out_unknown | 原生 / 原生或缺失 | false / 1 |
| 可能已发生效果，无回执 | unknown | unknown | not_requested | 原生 / 原生或缺失 | false / 1 |
| 有效回执满足显式等待 | acknowledged | submitted | satisfied | 原生 / 原生或缺失 | true / 0 |
| 成功查询先前超时的状态 | timed_out_unknown | submitted | timed_out_unknown | 缺失 / 缺失 | true / 0 |

无效标志、无效超时词法形式、缺失目标和格式错误的 ID 保留用法/无目标退出码 2，也可能完全没有 JSON/handoff。不会为这些失败编造合成的关联 ID 或旧版 false/null。中断使用退出码 130，且不取消/重发。成功的状态查询报告查询成功，而非确认应答。

## 能力与引导

每项能力都是未来的验收条件，不是当前的产品支持。在声明支持 ACK 之前，路由必须独立验证回执消费方、生成方以及不可变的原始目标代次。null 代次不能生成回执授权，也不能支持必需的 delivered/acknowledged 等待；该要求会在效果发生前以 wait unsupported 拒绝。引导失败表示 unsupported，不意味着允许尝试通用消息投递。新发现的当前代次绝不替代原始绑定。目标重启会阻止新提交/重新绑定，但本身不会使绑定至原始代次的延迟回执失效。经过验证的原始元组和原始能力凭证证明的是委托的令牌持有，而非原始代理/模型身份。后继者的新代次被拒绝。持有复制的原始元组和原始能力凭证两者的后继者或同一用户的读取者，在 token_possession 保证下无法区分；不得声称本方案通过认证模型身份排除了这种重放。

| 路由 / 观测器 | 注入观测 | 回执 ACK |
| --- | --- | --- |
| 同机私有收集器与兼容生成方 | 仅在 version/home/writer/ID 验证后支持 Codex | 私有引导后支持 |
| 通往已安装兼容回执处理器的明确受信任反向 SSH | 单独验证的 Codex 路由 | 处理器/配置验证后支持 |
| 未安装兼容处理器的源码流式 SSH | 单独验证的 Codex 路由 | 不支持 |
| Claude 原生观测器 | 默认不支持 | 仅兼容的显式回执生成方 |
| 配对设备、Relay、Side Session、wake | 初始路由范围之外 | 不支持 |

如果通道不受支持，要求 delivered 或 acknowledged 的等待会在效果发生前拒绝。尽力而为的关联 send 可以在 observation/ack unsupported 的情况下提交，而不生成未使用的秘密能力凭证。收集器不调用投递、wake、模型提示或批准。原生 app-server 回退至队列，仅在原始原生提交尚不可能已经开始时允许；尝试后的不确定性和观测器失败绝不触发另一次提交。version、platform、home 和原始 writer 身份检查为强制要求。不扫描转录内容或任意回复正文。

## 回执线格式与生命周期

Receipt v1 与 Reply-To v1 分离，后者的解析器和权限保持不变。回执句柄是非秘密的本地选择器，不是 URI 或授权。实际 bearer 能力凭证只通过已授权的私有效果输入和私有处理器 stdin 传递。不含秘密的保证覆盖发送方/收集器的 argv、URI、环境、常规 JSON、诊断、错误/ACK 结果及其自身的原始日志/持久化。该保证不覆盖预期接收方的原生队列、历史或转录内容：原生效果输入可能在 CLI 控制之外保留于其中，同一用户的读取者可能获得委托的回执专用授权。token_possession 不是独立的代理认证。我们的观测器仍然绝不读取转录内容。撤销、24 小时 TTL 和原子的首个回执接受限制的是新的回执授权，而非接收方的存储寿命。

```json
{
  "schemaVersion": 1,
  "kind": "receipt",
  "ledgerEpoch": "11111111-1111-4111-8111-111111111111",
  "correlationId": "22222222-2222-4222-8222-222222222222",
  "targetGeneration": "fixture-generation",
  "receiptId": "33333333-3333-4333-8333-333333333333",
  "capability": "<PRIVATE_INPUT_ONLY>"
}
```

能力凭证是 32 个密码学随机字节，编码为 43 个无填充的 base64url 字符。示例占位符不是有效的线格式输入。受保护的收集器仅存储绑定至 epoch、关联和原始代次的能力凭证 SHA-256 哈希；每次处理器请求都必须执行恒定时间验证，包括只读的重复请求。原子且持久的首个回执提交包含回执 ID/绑定、已证明的分类、assurance、late 标志、收集器接收时间，以及支撑它的等待顺序/截止时间事实。状态及相关等待转换与该记录一致地提交，而不通过后续单独写入完成。错误 ID、错误令牌、后继代次、冲突回执、过期且未提交的授权和无效帧不能推进状态。ACK 到达时间由收集器指定；调用方时间戳不具备权威性。

收集器是用户拥有的进程，独立于发送方会话。文件/目录为私有 0600/0700；端点为本地经过所有者检查的私有 IPC，或明确配置的受信任反向 SSH 处理器。不允许公开监听器、自动安装 SSH 密钥、更改配置文件、读取转录内容、导出秘密或通用 CLI exec。重启恢复已提交的回执哈希和已分类的回执；对于已尝试的意图，绝不重新生成丢失的原始能力凭证。能力凭证寿命为意图提交后 24 小时，并在详情过期、撤销、隔离或首个有效回执时终止。唯一的过期例外是只读获取已经提交的同一回执：必须提供原始 epoch、关联、代次、receiptId，以及原始能力凭证哈希的恒定时间证明。TTL 过期/首个回执消耗授权不允许接受新回执或创建/提升状态。撤销、隔离、详情缺失/过期或错误令牌连这一例外也会拒绝。仅凭标识符不会获得通用状态/查询权限。已授权的发送方操作员状态查询使用单独的、经过所有者检查的本地接口。

手动生成方是提议的无提交 handoff confirm 操作。它要求准确的 epoch/ID/原始代次，以及本地发送方操作员关于已观测到明确关联回复的声明；stdin 只接收元数据，不接收转录/正文。它记录 operator_confirmed，绝不记录 token_possession。确认是新的当前证明/事件，不是旧回执到达时间的追溯证明。只有原始等待的顺序/迟到分类可被证明时，例如依据持久的终态等待事实，才可成为 acknowledged。否则以 ok false、退出码 1 和固定 reason receipt_order_unprovable 拒绝确认；保留原始 pending/unknown ACK 和原始等待，不提交已接受的 ACK，也不编造 late 布尔值。已提交的有效回执绝不会因这次失败的确认而降级或被替换。令牌持有生成方必须是已安装且兼容的回执专用处理器，读取私有输入；它不能执行任意命令。两种生成方均仍是实现验收条件。在验证生成方之前，不声明任何 assurance。

## 发送方账本、新鲜性与保留

单一私有、串行化的持久账本拥有一个随机 epoch。其绑定目标的已准备意图在效果发生前提交并同步；效果意图屏障提交后，在该完整 epoch 中只授权一次原生尝试。该提交后的崩溃，包括实际效果开始前的崩溃，均恢复为 unknown，绝不再次提交。绑定包含 agent、目标、home/writer 身份、代次和受保护的内部载荷摘要；摘要不是公开输出。冲突或目标重启绝不悄然重新绑定意图。

新 ID 通过自动准备或新的无效果 handoff prepare 操作生成并预留。调用方提供的未知 UUID 因无法证明新鲜性，在效果发生前拒绝。提供的已知准备 ID 必须匹配其准确绑定，且尚未尝试。提供的已尝试 ID 仅用于查询/核对，绝不用于另一次 send。有序 fanout 为每个目标仅生成并持久关联一个意图；调用方不能将同一 ID 复用于多个目标。核对绝不重新生成 ID 或能力凭证。

每个 epoch 的上限为保留的 10,000 条意图/屏障记录和 32 MiB 日志，以先达到者为准。准入在效果发生前为终态记录及一个回执预留有限存储，而非在提交后填满容量。不允许屏障淘汰/LRU。详情自准备起保留 30 天，能力凭证寿命为 24 小时，每个意图最多 64 次等待；过期详情变为紧凑的目标绑定屏障 tombstone，在整个 epoch 内保留。tombstone 计入配额。等待配额耗尽时拒绝新的等待，不改变原生效果事实。清理详情绝不恢复提交权限；配额耗尽时拒绝准备/效果，直到操作员明确归档，不进行自动重置。

缺失、损坏、详情过期或已知被恢复的历史使 status/reconcile 返回 unknown，并禁止重试。已知的 tombstone 保留其原始 epoch 和目标绑定：它可以返回常规 handoff，state/submission 为 unknown，不声明 ACK/注入，也不提供 keep_waiting。缺失/损坏的账本或未知 ID 无法恢复该上下文，必须返回下方单独的查询错误封装，不包含 handoff，也不编造 epoch。已有账本绝不自动重建；首次使用要求明确的本地初始化和新的 epoch。已知恢复会隔离所有旧意图，在核对保留证据之前禁用效果和回执接受。新 epoch 要求操作员明确初始化并生成新的 ID；它不对旧请求作任何保证。仅本地的设计无法可靠检测未标记的回滚或跨机器账本克隆：屏障保证仅限于已证明完整、保留且未回滚的历史。外部单调锚点/防克隆存储不在 v1 范围内；这一限制必须保持可见，不能隐藏在普遍的 exactly-once 声明背后。

提议的查询错误使用退出码 1。其 handoffQuery 是只包含所示字段的封闭模式；context 为 ledger_missing、ledger_corrupt 或 id_unknown。调用方语法有效的 correlationId 会原样返回，不被视为历史证明。不添加 ledgerEpoch、handoff、顶层 status/submitted/consumptionConfirmed 或合成的原生快照。外层 host/command 为查询目标和 handoff，reason 为 handoff_history_unavailable。这是显式启用的查询结果，不改变常规旧版错误。

```json
{
  "schemaVersion": 1,
  "ok": false,
  "host": "fixture",
  "command": "handoff",
  "reason": "handoff_history_unavailable",
  "handoffQuery": {
    "schemaVersion": 1,
    "correlationId": "22222222-2222-4222-8222-222222222222",
    "status": "unknown",
    "context": "ledger_missing",
    "retry": {"allowed": false, "reason": "history_unavailable"}
  }
}
```

## 等待历史与迟到回执

每次等待都有独立的操作 ID、目标、单调时钟截止时间以及不可变的终态结果。status 返回该意图最近开始的等待（按串行化序列顺序），若没有则返回 not_requested；这不暗示未来会有单独的等待历史 API。当前回执/状态可以独立推进。因此，迟到 ACK 可以将当前状态设置为 acknowledged，而返回的原始等待仍保持 timed_out_unknown。它绝不将该等待改写为 satisfied。

如果回执在原始 send 等待的观测截止时间或之后被接受，则为迟到；若没有 send 等待，则与最早的显式等待比较。若没有等待，late 为 false。之后的等待可以由已接受的迟到回执满足；ack 的 late 标志仍为 true。在运行期间，回执接受与截止时间转换按同一单调时钟串行化，已证明的顺序/分类以原子方式持久提交。完整提交的有效 ACK 恢复其原始分类、assurance、late 及不可变的等待事实：绝不会仅因重启后的时钟变化而降级。提交前崩溃或其他未提交/未分类的时序证据不能成为 acknowledged，也不能提供合成的 late 标志。将其保留为未分类证据，必需的等待保持未满足，现有 pending/unknown ACK 保持不变。手动确认是遵循上述证明或拒绝规则的新事件，绝不追溯改写。UTC 时间戳仅用于诊断。重复等待不会产生新的原生提交。

## 预算与边界

默认预算为每个目标 30 秒；CLI 仅接受 1 至 60 的 ASCII 十进制整数，不允许前导零、符号、空白、小数点或指数。新标志不改变旧版解析。总单调时钟预算在设置、预检、准备、效果和观测之前开始。在其中为清理精确预留 5 秒；预算不超过 5 秒时，以 insufficient_budget 在效果发生前拒绝。观测/效果截止点为开始时间加预算再减 5 秒；清理不能延长开始时间加预算的上限。等待截止时间诊断描述这一截止点，而非重新开始的远程预算。

SSH 只传递剩余时长，并保持调用方原始截止时间；远程处理器不能重置预算，也不能用 UTC 授权效果。如果剩余总预算不超过清理预留时间，则在效果发生前拒绝。在截止点边界，以 now >= cutoff 判定过期；严格在截止点之前提交的回执可以满足该等待，在截止点或之后提交的回执为迟到。一旦效果可能发生，超时就是 unknown；不允许重试/回退或新的提交。有序 fanout 为每个目标分配各自有界的预算，而不是反复使用某个主机的预算。无法保证清理/自有资源受限的实现不能声明支持该路由。

```text
safe-integer = JSON integer token, 0..9007199254740991; booleans/fractions/exponents rejected
safe-id = 1..128 UTF-8 bytes, no U+0000..001F or U+007F..009F, valid Unicode scalars
safe-generation = 1..256 UTF-8 bytes, same control/scalar rule
receipt/confirmation frame = raw strict UTF-8 JSON input, at most 4096 bytes including LF/whitespace
public handoff size = compact UTF-8 encoding of the handoff subtree, at most 8192 bytes
opt-in destination stdout frame = at most 1048576 bytes including LF/whitespace
opt-in fanout = at most 32 destinations and 34603008 total stdout bytes including LF/whitespace
duplicate JSON keys, unknown nested keys, NaN/Infinity and trailing data rejected
turn/native IDs are opaque; only correlation/epoch/wait/receipt IDs use UUID-v4 syntax
```

JSON 数字令牌必须在有损解析前验证；即使 JavaScript Number 等于 1，词法形式 1.0 和 1e0 仍被拒绝。词法限制仅适用于 handoff/handoffQuery 子树及私有回执/确认模式，不适用于无关的旧版外层字段。保留现有旧版解析及重复键/非有限数规则；不会仅因存在 handoff 请求就使旧版字段无效。handoff 子树大小使用规范的紧凑编码计算（无可选空白、使用 UTF-8 标量字符而非 ASCII 转义、以逗号/冒号分隔）；封装线格式中的子树空白则计入外层帧限制。私有回执/确认的原始输入包含每个字节，包括可选的尾随 JSON 空白和 LF；尾随的非空白数据被拒绝。不额外允许任何换行字节。目标/总量限制只适用于新的显式启用模式；在任何效果发生前拒绝过多目标，不改变常规未启用模式的线格式/输出限制。在分配前逐步限制 stdout；有界汇总格式为紧凑 JSON 加可选 LF。有界且完整的外层帧中，若可选子树格式错误或超限，保留独立验证的原生证据，拒绝 ACK/显式等待，绝不重新提交。若超过外层帧限制，不得通过部分解析判为成功；仅保留此前已独立验证的证据，否则返回 unknown。边界在持久化前检查，而非截断后。发送方/收集器的常规 stdout、诊断、错误/ACK 结果及自身日志绝不包含能力凭证或载荷摘要；它们不读取接收方的转录/正文。有界元数据观测不得通过输出过滤来隐藏返回正文的 API。

## 提议的 CLI 与零提交操作

这些是提议的写法，不是已发布 Python 中可用的命令。准备绑定与 send 相同的目标/消息输入，但不提交；确认接受仅含元数据的私有 stdin。明确的本地账本初始化是单独的显式启用设置前提，绝不是自动恢复操作。

```text
handoff init
handoff prepare --to TARGET --message-file PRIVATE_FILE
send --to TARGET --message-file PRIVATE_FILE --correlation-id PREPARED_UUID
send --to TARGET --request-ack
send --to TARGET --observe-delivery
send --to TARGET --wait-for delivered|acknowledged --wait-timeout SECONDS
handoff status --correlation-id UUID
handoff wait --correlation-id UUID --wait-for delivered|acknowledged --wait-timeout SECONDS
handoff confirm --receipt -
ack --receipt -
```

没有 correlation-id 时，request-ack/observe-delivery/wait-for 自动预留新意图；其余常规 send 保持不变。仅关联的 send 使用尽力而为的证据，不显式等待。status、wait、confirm、ack、init 和 prepare 不产生任何原生提交。回执选择器不包含秘密。确认 stdin 包含 schemaVersion、ledgerEpoch、correlationId、targetGeneration，以及调用方的 confirmed=true 声明；它拒绝额外字段/正文/能力凭证，且仅记录 operator_confirmed。标志不兼容和不受支持的路由要求在持久效果意图之前检查。远程设置与主机选项必须遵循现有 SSH 信任限制，而非任意回执路由。

ACK 证据还要求非 null 的原始 targetGeneration 和 submitted submission；接受有效回执后，当前状态为 acknowledged。观察到注入始终意味着 submitted submission。提供的已准备 ID 不得属于先前真实的 send 调用，包括产生副作用前的终止拒绝。dry-run 不消耗首次提交权限。dry-run 不可与 request-ack、observe-delivery、wait-for 一起使用，否则返回用法退出码 2；correlation-only dry-run 使用已准备的 ID。

如果重启后的收集器无法证明能力凭证寿命的单调时钟连续性，它会保守地使未使用的新回执授权过期，而不是延长 TTL 或重新生成授权。有效提交的回执分类/assurance/late 仍可恢复；经过认证的同一回执只读重复请求遵循明确的过期例外。对已尝试意图开始新等待时，如果预算不足，只使该等待失败，保留提交和注入事实，不把原意图重新归类为 refused。reconcile 操作表示状态和证据比对，而非新提交或隐式修复命令。

## 冻结与实现验收条件

本提案在冻结前要求 TypeScript 审查其准确提交和夹具。新的 prepare/confirm 写法、ledgerEpoch 和等待 operationId 字段、5 秒清理预留、数字令牌验证以及恢复限制，都是明确的 v0.2 修订，不是已经接受或发布的能力。

夹具必须覆盖各运行时的可选字段缺失、由请求上下文允许的 queued true 显式等待超时、伪造的未启用 handoff、错误原生目标、认证成功/错误令牌/过期的重复请求、已提交/提交前/顺序未知的回执恢复、手动确认拒绝、原始/新/null 代次、不反射秘密、上下文缺失的查询错误与已知 tombstone 的区别、等待历史、缺失/恢复/过期/已满账本、自定义未知 ID、截止时间/帧边界、格式错误的模式以及 SSH 保留。严格的 SSH 显式启用验证必须在 handoff 被拒绝时仍保留有效的原生快照；旧版 Claude 重建或通用失败路径都不得丢弃它。完整响应只有通过同一严格且识别原始请求的解析器，才能在传输超时/非零退出后保留；部分帧仍为 unknown。

实现验收前须验证：生成方引导与收集器所有权/重启、持久意图与容量预留、各受支持 platform/version/home 下的清理、仅元数据的 Codex 观测、严格的本地/SSH 元组，以及零提交 status/wait/ack/confirm 操作。本设计 PR 不提供原生/实际运行证据。Side Session 与 wake 实验是单独的未来工作，不是前提条件。不会悄然加入配对设备/Relay 去重和操作员监控。
