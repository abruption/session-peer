# 配对设备与私有中继 (v1.0)

## 连接设置向导（明确选择）

`session-peer setup` 不改变安装，只说明本地、SSH 与 Relay 选项。本地、SSH 使用标准
库 CLI；Relay 需要 Unix Python 3.11 及以上版本与可选 `[relay]` 依赖，不需要 Node.js。
缺少依赖时，向导说明原管理器命令或与独立 CLI 分离的环境，不执行安装或切换管理器。
技能、插件不安装运行时或托管服务，也不保证公共服务可用。

```bash
session-peer setup
session-peer setup --mode local
session-peer setup --mode ssh --host worker
session-peer setup --mode relay --interactive --role receiver
session-peer setup --mode relay --interactive --role client --no-browser
```

在两端运行 Relay 向导，分别批准初始化、浏览器或代码授权登录、命名注册、策略与邀请
生成、配对。明确选择信任客户端初始化结果中的标识，选择当前目标、可执行文件、主目录，
并审阅策略。默认只向该设备、目标授予 `list`，`send` 另行选择。请在10分钟内安全传递
私密邀请文件。注册不等于配对，配对不等于代理批准。设置不会发送测试消息。

无界面环境用 `--action init|login|enroll|policy|invite|pair|ready` 和 `--apply` 批准各项
操作，目标、设备、路径、路由参数见 `--help`。`plan`、`targets`、不带 `--apply` 的预览
不构造 Store、不初始化密钥、数据库、设置日志，也不迁移状态。数据库列表只是已落盘
检查点的诊断信息，不证明当前权限。向导报告接收锁和已知服务文件，但不保证发现所有
服务，也不修改已有服务。策略只新建私密0600文件或复用完全相同的文件，不覆盖其他
策略、不扩大权限。应用前重新检查目标，但不保证之后原生会话仍为同一实例。
已有密钥、数据库不完整，或当前轮换密钥丢失时，即使批准初始化也需要手动恢复，
设置工具不会重新生成。

私密 `setup.json` 在请求前持久保存原注册 UUID、名称、服务器、密钥标识及完整注册请求。中断、丢失
响应后，用相同状态、名称明确恢复 `enroll`，现有 API 核对同一操作，不更换成新修改。
意图、密钥、请求（包括证书 PEM 的空白）变化会在联网前被拒绝。登录过期需重新 `login`，但 UUID 保留。邀请生成结果不明时，
等待操作员核对。提示命令和 `--action receiver --apply` 在前台运行，直到 Ctrl-C 或
`--seconds` 到期；不安装自动启动、服务、配置文件，已有 launchd、systemd 管理独立进行。
`--action cancel --apply`、EOF、Ctrl-C 只停止设置等待，不撤销已提交注册或原消息。
目录使用0700、文件使用0600，不共享日志、令牌、邀请秘密。认证后的 probe、列表只检查
元数据，不证明消费、ACK、代理批准或可用性。结果不明的消息不重发，手动命令仍可使用。

这一可选的 Unix/Python 3.11+ 传输方式将请求传递到操作员定义的
Claude、Codex 或已注册的 Antigravity 端点。通常的本地/SSH 命令
保持无外部依赖。这是一个显式的 CLI 工作流；不会安装移动端应用程序、
NAT 穿透、WireGuard 隧道或自动公开服务。

接收端在设备认证前最多允许 16 条直接连接和 2 条已 attach 的 Relay 连接，与 8 条已认证连接分别管理。TLS 必须在两秒内完成，包含网络和调度延迟。TLS 完成后，没有客户端证书的初始配对连接还有两秒用于完成唯一一次配对请求及响应；已认证请求的期限仍为 45 秒。这些较短的期限也可能拒绝合法的慢速连接。存在 8 个空闲或慢速 TLS 直接套接字时，仍有空间接收已配对设备的直接连接和 Relay 请求。但全部 16 个直接连接认证前名额耗尽时，仍可能拒绝已配对设备的直接连接，两个预留的 Relay 名额也可能饱和；不保证在任意洪水攻击下的可用性。超额套接字或接收端开始关闭后的套接字不会创建处理任务。汇总准入计数器保留拒绝和清理失败数量，不包含身份；显式启用的 `receiver_admission` 事件每分钟最多报告一次固定计数器和允许列表内的原因。不会启用应用程序自动重试。

<a id="一次性配对链接v13候选"></a>

## 一次性配对链接（v1.3.0）

以下链接流程从 v1.3.0 起可用。两端都需要新的 `pairing-offer-v1` 协议。现有私密邀请文件仍然受支持。该功能沿用Unix Python 3.11+及relay额外依赖，不增加Windows支持、中介服务、网页、公开监听端口或托管服务。

先初始化两端设备，并通过可信渠道核对公开身份。`device rotation-status` 会显示稳定设备标识和当前密钥指纹；轮换密钥后两者可能不同。接收目标策略须单独审核。配对不会授予所有会话的访问权限，不会改变原生CLI的审批流程，也不会授权代理执行。

在接收端明确核对自身身份及目标客户端的当前密钥，然后在控制终端显示链接：

```sh
session-peer device offer --state /private/device-state \
  --peer-key CLIENT-CURRENT-64-HEX-KEY --direct PRIVATE-IP:3770 --show-link
```

私下传递较长的 `session-peer://pair/v1#...` 链接。客户端在不回显的终端提示中输入，不要把链接放在 `--link` 后面或任何命令参数中：

```sh
session-peer device pair --state /private/client-state --link --route direct
session-peer device offer-status --state /private/device-state --offer-id OFFER-UUID
session-peer device offer-cancel --state /private/device-state --offer-id OFFER-UUID
```

客户端检查自身当前密钥是否等于指定密钥，并在显示候选接收端身份或路径之前，要求输入通过独立渠道核实的当前密钥指纹。只有匹配后才显示双方身份和路径，进行最终确认。这避免引导用户复制未核实的屏幕值，但不能证明输入的真实来源。链接不能自行证明身份。信任登记和网络连接在确认后进行；接收端创建提议时也会在事务内重新核对已确认的客户端身份。无法使用控制终端时会拒绝，不会回显秘密或自动批准。设置向导的链接/私密文件选项使用相同确认流程；自动化仍可使用现有文件命令。

客户端的稳定标识和密钥代数，只能来自完全匹配的既有有效密钥绑定；首次见到的密钥使用其指纹和代数0。已知处于待定、旧代或吊销状态的密钥不能按新密钥处理。若缺少所需既有绑定，该流程会拒绝轮换后的接收端或客户端身份；输入指纹不能凭空授予其他稳定标识的权限。必要时使用原有可信文件或恢复流程，不要复制私钥或设备状态。

### 过期、取消与中断后的核对

配对提议带有256位秘密，按接收端系统时钟在10分钟后过期，并绑定一个指定的当前密钥。状态为open、reserved、consumed、cancelled和expired。预留、经过认证且绑定邀请的提交、取消和过期在接收端数据库中串行处理。另一份邀请不能接管待定预留，已配对设备也不会降级为待定。取消只移除该提议拥有的待定信任，不吊销既有密钥绑定或已经完成的配对。完成后，应在相应端点使用现有显式命令 `device revoke --peer RECEIVER-OR-CLIENT-PRINCIPAL` 吊销信任。

只有保存的提议ID、受保护的链接内容摘要、接收端标识/密钥及当前客户端密钥全部匹配，才能核对中断的提交结果。没有匹配历史的过期链接会在联网前被拒绝。过期后的核对只能通过认证提交取得已经完成的结果，不能重新准备、延期或撤销吊销。接收端清理结果后，即使仍将该peer视为已配对，也无法再核对原提议；此实现不重建历史回执，也没有超期修复命令。保留双方状态，与操作者明确制定恢复计划；盲目吊销密钥可能使恢复更困难。流程不会发送原生消息，也不会自动重发。

创建限制为每分钟5份、同时最多8份有效提议。准备请求持久限制为全局每分钟32次、每份提议每分钟8次，错误猜测也计数；全局限制同样适用于既有私密文件配对。达到上限后，拒绝尝试不会更新或延长该窗口。未知ID不会分配独立状态。终态结果保留7天，提议总数上限为1,024份；清理时将符合条件的提议元数据和邀请行一并移除。包括未认证负载在内，限制可能暂时拒绝正常配对。已配对的原生请求不使用此准备额度。这些是资源限制，不是身份或投递证据，并以接收端时钟可信为前提。接收端在信任变更决策前检查过期，持久提交可能稍后完成；客户端时钟偏差也可能使请求提前被拒绝。

客户端的精确意图记录也限于1,024份，不会静默淘汰；到达上限时，既有匹配记录仍可继续核对。初始实现既不自动清理，也不提供显式客户端记录清理命令；与接收结果不同，7天后仍然保留，因此将来可能拒绝新的链接配对。新记录以 `pairing_intent_capacity` 拒绝，保留结果核对证据。升级前的文件配对待定状态，只有在唯一有效邀请、证书、有效密钥及过期时间证明归属时才接管；不明确或无法证明的有效待定状态会保留并拒绝，交由操作者核对，不会静默转交另一邀请。明确过期的待定信任可在事务内清理，但保留密钥绑定，不移除已配对或已吊销peer。另一份有效文件邀请不能接管待定预留，因此更换邀请可能需要等待过期。不要删除设备数据库或重发原始原生消息来绕过拒绝。

若设置向导在确认后中断，私密设置日志会在数据库创建前保存公开提议ID。确定没有创建的拒绝可重试。结果不明确时，使用以下显式状态/取消操作；省略ID选项时使用保存的ID。没有历史不是未创建的证据，也可能是结果已清理，应视为未知。状态查询仍保持待定；对于找不到历史记录的已保存ID，显式取消操作只停止本地等待，不执行撤销远端权限或已配对信任的操作。返回ID在下一次明确确认的创建前保留为当前记录，但并非永久审计日志。已知有效提议保持待定直到明确取消；保留的终态可解除对应意图，其他ID不能清除。捕获到手动显示失败时也返回可供状态/取消使用的公开ID；只有向导日志能跨越进程崩溃保留。不会自动创建新提议或重新显示秘密。

恢复或隔离状态在过期清理、删除及计数写入前就受恢复隔离保护。其提议状态只是历史诊断证据，不是当前权限，不能解除向导待定状态。隔离期间拒绝配对变更及取消，恢复仍须单独明确执行。

```sh
session-peer setup --mode relay --state /private/device-state --action offer-status --offer-id OFFER-UUID --apply
session-peer setup --mode relay --state /private/device-state --action offer-cancel --offer-id OFFER-UUID --apply
```

### 威胁模型与秘密处理

不使用会合中介或短数字码。长度受限的专用URI携带既有邀请和指定公钥，不会在浏览器中打开或抓取，也不注册操作系统URL处理器。链接属于凭据：即使内容位于URI的 `#` 后，终端录制、剪贴板或浏览器历史仍可能保留它。不要粘贴到地址栏、日志、分析工具、有不可信参与者的聊天或Issue中。常规JSON、诊断和设置日志不包含链接或原始秘密；私密意图记录只能保存受保护摘要和公开身份上下文。

既有的证书固定端到端TLS与客户端私钥持有证明仍是必需条件。被攻陷的中间节点可观察连接元数据、延迟、重放或拒绝服务，但不会得到端点私钥或代理消息明文。替换接收证书会被独立指纹核验拒绝。真实链接泄漏也不能授权其他客户端密钥。知道指定公开证书的人可能通过预留干扰服务，但无法获得密钥持有证明或原生目标权限。端点、私钥或身份确认渠道被攻陷不在此保护范围内。不增加托管可用性、消费确认、ACK或恰好一次处理保证。

## 连接失败诊断与安全的连接重试

`no_authenticated_route` 保留 `retryAllowed:false` 和 `consumptionConfirmed:false`。`routeFailures` 给出每条失败路径最后一次的 `stage`、允许列表中的 `reason` 和 `attempts`。有界的 `attemptHistory` 保留每次尝试的阶段、原因和 `elapsedMs`；HTTP 拒绝还可能包含 `httpStatus`，WebSocket 关闭可能包含 `closeCode`。控制、准入、升级、attach、对端 TLS 和 probe 故障可以区分，但不会记录 URL、凭据、原始异常或消息正文。第二次尝试成功时会有 `setupDegraded:true`、`setupAttempts:2` 和 `setupFailureHistory`，不能算作干净的稳定性测试通过。

仅在**WebSocket 升级前的控制或准入超时**时，等待 0.5 秒后再尝试连接一次。attach、对端 TLS 和 probe 超时不会重试。WebSocket 升级超时也不重试，因为 origin 可能已经配对并消耗了接收端房间。使用新的准入票据和通道，不重用已消耗的票据，也不重发代理消息。HTTP 拒绝、身份/证书错误和未知失败也不会重试。直接路径获选时仍可取消 Relay 尝试。提交后丢失响应仍为 `unknown`，不重发、不切换路径。此有限缓解措施不代表公开网络故障已经解决；部署后必须重新验证实际 ACK 和长时间运行。

接收端每分钟最多向 stderr 输出一条经过清理的 `relay_connection_failed` 警告。疑似正常空闲到期的关闭与故障警告分开。显式使用 `device serve --diagnostic-events` 和 `relay serve --diagnostic-events` 时，只向 stderr 记录房间、attach、关闭阶段、耗时、允许列表内的原因及关闭代码。默认关闭；不会记录设备身份、房间名、URL、标头、凭据或正文。Relay 指标还会增加房间创建与配对、每条连接的 attach 发送以及到期计数。attach 发送不能证明客户端已收到。接收端的 `idle_expiry_like` 不能证明服务器端原因。

WebSocket 关闭的 `closeSource` 区分代码来自接收还是发送。Relay 计数器区分接收端先到和客户端先到的房间。`receiverWsAgeMs` 只表示等待时长，不能证明连接健康；需要对照配对时间与接收端的 `attach_received`、对端 TLS 事件。

`stream_close.closeCode` 是从远端收到的关闭代码。`1006` 表示未收到关闭帧，可能提示连接停滞。`peer_closed` 表示另一条连接结束后 Relay 关闭了本连接；`remote_going_away` 表示远端在 Relay 未发起关闭时自行发送了 1001 代码。`receiverRoleBusy`、`clientRoleBusy` 统计同一房间中被拒绝的重复连接；接收端计数上升可能意味着接收端重连时 Relay 仍持有旧连接。

显式启用的 Relay 和接收端生命周期事件包含 `eventTimeUtcMs`（UTC Unix 毫秒）。客户端每次尝试建立 Relay 连接都会生成新的随机 UUIDv4 `attemptId`，并在成功结果或逐次失败元数据中记录。新版 Relay 在已配对房间事件中记录该 ID，并通过 attach 通知传给新版接收端；接收端的 `attach_received` 和 peer-TLS 事件也记录同一 ID。该 ID 不由身份、房间名、请求 ID 或消息内容派生，也不会改变授权或重试安全性。归因失败时，应确认完全相同的 `attemptId` 只对应一个 Relay 房间和一条接收端连接，并在比较 UTC 时间时考虑时钟偏差。若事件缺失、重复或某条连接使用旧版本，不要仅凭时间或汇总计数推断，应记为 `unattributed`。

如果公开路径停滞再次出现，可在显式启用的 Relay `stream_close` 事件中比较每条连接的 `ingressFrames`/`ingressBytes`、`egressCompletedFrames`/`egressCompletedBytes` 以及首末帧 UTC 时间。这些是加密 WebSocket 帧计数，不是消息数。发送完成只表示 Relay 的套接字 send 已返回，不能证明 Cloudflare、接收端、TLS 或应用程序收到了这些字节。先比较同一房间和 `attemptId` 下的两个角色，再对照接收端事件。事件缺失或匹配模糊时仍应记为 `unattributed`。仅凭计数无法判定 Cloudflare、OCI 或中间链路的责任。元数据时间和帧大小也会透露活动信息，因此应将 opt-in 日志私密且限期保存。

若等待房间已开启至少 1 秒后被 Relay 正常关闭，接收端会在 0.5 秒后重连，而不会增加退避时间。其他失败以及 1 秒内关闭的房间仍按指数退避，最长 5 秒。Relay 连接两端均使用 10 秒的 WebSocket ping 间隔与超时，因此停滞连接约 20 秒即可检测到，而不是约 40 秒。这些改动只缩短重连空档，并不能修复停滞的网络路径。

### macOS Direct监听检查（#341）

本节说明v1.3.1之后尚未发布的变更。`device serve`启动时的`ready:true`只确认本地监听器已建立。此次变更增加`directReadyConfirmed:false`；旧接收端可能没有该字段。TCP连接、启动就绪和对端TLS成功是不同的观测。TLS握手可能只是尚未认证的配对初始连接，因此本身不能证明配对完成、原生目标访问或ACK。现有配对设置的就绪检查使用已认证的probe/list请求。

启用`--diagnostic-events`后，此次变更会输出`direct_transport`生命周期记录。`phase`在进入TCP回调时为`accepted`，在握手成功或失败时为`peer_tls`。有上限的每个接收端的累计计数器为`accepted`、`tlsCompleted`和`tlsFailed`。按单调时钟，每阶段每60秒最多输出一条，合计每分钟最多两条；TLS成功和失败共享同一阶段的限制。正常关闭时额外尝试输出一次包含零计数的`summary`快照，重复关闭不会再次输出。这是关闭时的快照，不是定期通知或无损事件历史。连接受理拒绝、未完成或已取消的握手及计数器上限可能使各项数量不相等。尽力而为的Direct记录不包含端点地址、对端ID、消息数据或异常原文。仅凭缺少记录不能断定未接受连接。

在用户允许防火墙提示前进行的2026-10-27隔离配对试验中，使用Homebrew Python 3.14.9接收端时，两个方向的客户端均进入TLS阶段但返回`peer_tls/timeout`，明确试验`0.0.0.0`也未解决。一台Mac上使用python.org Python 3.13.7的接收端成功完成了来自另一台Mac的配对及已认证probe。反向连接仅在使用另行选择的短时private TCP转发进程连接loopback TLS接收端时成功；该进程不充当TLS终结端点，仅转发不作解析的TLS字节。这些是不同的试验拓扑，不代表通用支持，也未确定macOS、Tailscale或Python的根因。观测范围请参阅[#341](https://github.com/abruption/session-peer/issues/341)。

用户允许`Python.app`接收入站连接后，两台Mac均使用此前失败的已发布v1.3.1 Homebrew Python 3.14.9运行时、tailnet绑定地址和各自相同的端口，成功完成Direct配对及已认证probe。试验使用新的身份，没有使用转发进程、替代解释器或原生调用。这一前后对照支持macOS应用程序防火墙等待批准是本次事件的原因；恢复并非诊断PR修复了网络路径。

[Apple防火墙说明](https://support.apple.com/en-euro/guide/mac-help/mh34041/27/mac/27)指出，响应提示之前，入站连接尝试会被拒绝。预期的接收端触发该提示时，应由所有者确认实际Python应用程序，并按需要明确允许。保持防火墙启用、所选private绑定、固定证书的TLS及接收策略；该权限不授予原生代理访问权。

请记录实际运行的Python映像及发行来源、macOS版本、Tailscale版本及类型、绑定地址，以及检查是自连接还是远程连接。防火墙显示允许并不证明端到端就绪。不要自动将监听范围扩大至`0.0.0.0`、修改防火墙或访问策略、切换运行时，或推断某个转发配置已受支持。配对结果不确定时，应保留`pending`状态和`retryAllowed:false`。独立试验结果不授权重试或清除此状态。

记录数量有上限，但现有同步stderr日志器在输出目标阻塞时没有强制超时机制。

## 安装

在两台设备上的隔离环境中从 PyPI 安装 session-peer v0.9.0 或更高版本：

```sh
python3 -m venv ~/.local/share/session-peer-relay/venv
~/.local/share/session-peer-relay/venv/bin/pip install 'session-peer[relay]'
```

中继扩展组件（relay extra）自 v0.9.0 起在 PyPI 上提供。
软件包发布不保证托管 Relay 的可用性。请使用下文安装的
`session-peer` 可执行文件。管理命令（`device`/`relay`）输出 JSON。
请勿混用具有不同软件包版本的 Python 环境。

## 身份、策略与配对

在各个端点上：

```sh
session-peer device init --state /private/device-state
```

返回的 `device` 为其公钥证书指纹。每个设备保留其自身的私钥；
切勿将该私钥复制到中继或另一个端点。请使用新的私有状态目录（0700）。
系统会拒绝现有的不安全文件/目录，而不是静默对用户数据执行 chmod。
该数据库是 session-peer 自身的设备日志（journal）；它不是 Codex
对话数据库或本体（ontology）库数据库。

在接收端机器上创建一个 0600 权限的策略文件。将客户端指纹、
代理目标和主目录替换为独立发现的值。例如：

```json
{
  "targets": {
    "review": {
      "agent": "codex",
      "target": "codex:FULL-THREAD-UUID",
      "codexHome": "/home/alice/.codex",
      "codexBin": "/home/alice/.local/bin/codex"
    }
  },
  "peers": {
    "CLIENT-64-HEX-FINGERPRINT": {
      "capabilities": ["list", "send"],
      "targets": ["review"]
    }
  }
}
```

Claude 绑定使用 `agent: claude` 以及不带主目录的精确会话名称/PID。
Antigravity 绑定使用 `agent: antigravity`、`target: antigravity:UUID`
和 `antigravityHome`；请先按照[其桥接流程](antigravity.md)注册该 TUI。
接收端以拥有这些代理会话的账户运行。切勿仅仅为了访问另一个用户的会话
而以 root 身份运行接收端。

配对证明了对设备密钥的持有。**它并不授予原生代理访问权限**：接收端策略
必须单独允许该指纹、操作和目标别名。对端无法提供可执行文件、主目录、
wake 标志、SSH 目的地或任意原生命令参数。策略变更在重启接收端后生效。
限制：最多八个已配置目标和 128 个策略设备。

由 launchd 或 systemd 启动的接收端继承服务管理器的最小 `PATH`，而不是登录 shell 的环境。对于 macOS/Linux Codex 目标，可将目标 TUI 使用的 `codex` 目录加入接收服务的 `PATH`（例如 launchd 的 `EnvironmentVariables.PATH` 或 systemd 的 `Environment=PATH=...`），也可在操作员管理的绑定中把 `codexBin` 设为以 `codex` 结尾的绝对路径，例如 `/opt/homebrew/bin/codex`。接收端启动时验证它是可执行的普通文件，并将符号链接解析到实际目标。Unix Codex 不使用 `codexPython`。原有的活跃 writer 和 home 检查保持不变。在实际发送前，请在相同的接收端环境下运行 `send --dry-run`。如果找不到可执行文件，提交前将以 `codex_executable_not_found` 拒绝。不要自动重试结果为 unknown 的发送。

## 面向原生 Windows Codex 的 WSL 接收端

当 Codex 会话和 CLI 在同一台 Windows 工作站上原生运行时，请在 WSL2 中运行接收端。由操作员策略而不是已配对的对端固定挂载的状态主目录和可执行文件：

```json
{
  "targets": {
    "windows-review": {
      "agent": "codex",
      "target": "codex:FULL-THREAD-UUID",
      "codexHome": "/mnt/c/Users/alice/.codex",
      "codexBin": "/mnt/c/Users/alice/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe",
      "codexPython": "/mnt/c/Python313/python.exe"
    }
  },
  "peers": {
    "CLIENT-64-HEX-FINGERPRINT": {
      "capabilities": ["list", "send"],
      "targets": ["windows-review"]
    }
  }
}
```

`codexHome` 必须是本地 Windows 驱动器上的绝对 WSL 路径。`codexBin` 和必填的 `codexPython` 分别为名为 `codex.exe`、`python.exe` 的绝对路径，必须是操作员管理的可执行普通文件（不可为符号链接）。请指定已安装的原生 Windows Python 3.9+，而非 Microsoft Store 执行别名。

接收端以固定参数调用 `/usr/bin/wslpath`，将 standalone 核心流式传入原生 Python，不构造 shell 命令。原生 Python 读取 Windows SQLite/WAL 并检查 writer 锁、唯一所有者、同用户 SID、进程创建时间和 Codex 可执行文件身份。不会使用 Linux SQLite 打开 Windows DB，也不会绕过 writer 检查。非活动、歧义或无法检查的 writer 均被拒绝。现有 WSL 策略也必须添加 `codexPython`；缺失或无效时分别返回 `native_windows_python_required` 或 `invalid_codex_python`。

Linux/macOS 目标省略 `codexPython`，可按上述说明选择设置 `codexBin`。Windows 客户端继续使用普通本地 CLI。成功提交仍为 `consumptionConfirmed: false`，消费须由独立观察到的回复确认。即使更新策略或接收端，也不要自动重试 unknown 发送。

支持原生本地 CLI 不代表支持所有 Windows SSH shell。源码流式 SSH 需要可用的 python3 和兼容 POSIX 的远程 shell；Windows Store 执行别名并不足够。请在本地运行原生 CLI，或使用已安装 Python 的 WSL SSH 端点。

启动直接连接接收端（默认为环回；若针对其他机器，请选择可访问的私有接口）：

```sh
session-peer device serve --state /private/device-state \
  --policy /private/receiver-policy.json --bind PRIVATE-IP --port 3770 --seconds 3600
session-peer device invite --state /private/device-state \
  --direct PRIVATE-IP:3770 --out /private/invitation.json
```

通过受信任的通道将邀请凭据传输到客户端上的私有文件中，然后在十分钟内运行：

```sh
session-peer device pair --state /private/client-state \
  --invite /private/invitation.json --route direct
```

邀请包含一次性密钥和固定的接收端证书。待处理的配对可以通过证明相同的
设备密钥来调和丢失的提交响应。证书替换将会失败。配对完成后请删除邀请文件；
它们包含机密信息。IPv6 直接地址使用 `[address]:port`。直接访问需要
TCP 可达性；不存在自动路由器、防火墙、VPN 或 NAT 配置。

## 配置私有中继

在受信任的管理机器上：

```sh
session-peer relay provision --out /private/new-room --room personal
```

这将创建 `accounts.json`（准入哈希）、`receiver.token` 和 `client.token`。
将每个令牌保存在 0600 权限的文件中。中继服务器上仅安装哈希。
将接收端/客户端准入令牌与私有设备身份密钥分开分发。令牌控制中继准入；
内部固定 TLS 独立控制配对和原生访问。中继绝不会获取端点私钥。

```sh
session-peer relay serve --accounts /private/accounts.json \
  --bind 127.0.0.1 --port 3769 --seconds 3600
```

对于持久化 Linux 托管，请将 wheel 安装到 `/opt/session-peer-relay/venv` 中，
将哈希存储在 `/etc/session-peer-relay/accounts.json` 中，并调整经审查的
[systemd 模板](../../deploy/examples/static-account/session-peer-relay.service)。在启用前使用
`systemd-analyze verify` 进行验证。该模板以动态用户（dynamic user）、
无特权功能（capabilities）、不可访问的主目录、只读系统、私有临时目录
和显式资源限制运行。它适用于**盲中继**，而非原生接收端；
后者需要其代理拥有的运行时路径和套接字。

将环回中继置于专用主机名上的 HTTPS/WSS 反向代理之后：

```caddyfile
relay.example.com {
    reverse_proxy 127.0.0.1:3769
}
```

本示例并非指示重载现有的生产环境 Caddyfile。请使用部署现有的证书/DNS 策略，
验证确切的 diff，检查现有的 WebSocket 用户，并规划回滚方案。重载/边缘更新
可能会关闭连接。任何令牌都不属于 URL/查询参数。避免输出标头/正文调试日志。
代理可以看到 IP、主机名和准入元数据，而应用消息和配对机密则保留在端点
TLS1.3 内部。请勿禁用外部 TLS 验证。

使用 `--relay wss://relay.example.com/v1/connect` 和
`--admission-file /private/receiver.token` 启动接收端，然后使用该
`--relay` URL（以及可选的 `--direct`）创建邀请。客户端可以使用
`--route relay` 和 `--admission-file /private/client.token` 进行配对。
明文 `ws://` 仅限于环回以进行隔离测试。接收端就绪输出确认其本地监听器；
`relayReadyConfirmed: false` 刻意不声明端到端中继就绪。

## 列出、发送与调和

```sh
session-peer list --device RECEIVER-FINGERPRINT --device-state /private/client-state \
  --relay-admission-file /private/client.token --json
session-peer send --device RECEIVER-FINGERPRINT --device-state /private/client-state \
  --relay-admission-file /private/client.token --device-route auto \
  --to review --message 'Please inspect the proposed change' --json
```

`--to` 是接收策略中允许的目标别名，而不是任意的原生 UUID 或 shell 命令。
`--agent` 筛选允许的列出结果。设备路由与 `--host` 互斥；原生主目录/
二进制文件/SSH 选项属于接收策略，在配对请求中会被拒绝。此处不支持 `--wake`
和显式 SSH Reply-To。保留描述性的 From 标头，但不会通告自动配对的
Reply-To 路由。此测试版中未实现 MCP 设备目的地；其现有的本地/SSH
策略保持不变。

自动路由竞速已通过身份验证的就绪探测，若两者同时完成则优先选择直接连接。
它在选定的**一条**连接上发送应用请求。在提交结果不明确后，它绝不会发生
故障转移并重新发送。设置 `--device-route direct` 或 `relay` 以强制指定路径。
消息在加上信封后限制为 32 KiB UTF-8。`--dry-run` 解析配置的原生目标，
而不进行原生提交。

32 KiB 限制计算包含发送方信封的 UTF-8 消息字节。转义后的完整应用 JSON 必须不超过 64 KiB，包含操作员绑定路径的内部 worker JSON 必须不超过 256 KiB。大量转义字符可能使不足 32 KiB 的正文达到应用上限。明确的超限在应用写入或原生 journal intent 之前返回 `refused`；后续不确定的 I/O 失败仍为 `unknown`，不允许自动重发。

`submitted`/`queued` 仍与消费（consumption）截然不同。`consumptionConfirmed`
始终为 false；必须独立观察到模型 ACK。原生操作在有界子进程中运行，
因此它们不会阻塞准入/吊销。在原生效果发生之前，持久化请求意图已被提交。
相同的请求 ID 和规范目标绑定/正文将返回其记录的结果；更改目标/正文会导致冲突。

使用 `--request-id UUID` 来保留尝试标识符。在丢失响应后，请查询原始 ID
而不是生成新的 ID：

```sh
session-peer device status --state /private/client-state --peer RECEIVER-FINGERPRINT \
  --request-id ORIGINAL-UUID --admission-file /private/client.token
```

`unknown`（包括接收端/工作进程崩溃）绝不允许自动重新执行。这是最多一次
（at-most-once）执行尝试，而不是精确一次（exactly-once）消费。
日志上限为 10,000 个请求，存满后会拒绝进一步的新提交。请勿删除待处理条目
或清空日志以重试未知项。v1.0 CLI 不会自动轮换日志或管理长期运行的设备群；运维人员必须在不丢弃未决结果的前提下规划容量和保留策略。

## 吊销、重启与恢复

```sh
session-peer device peers --state /private/device-state
session-peer device revoke --state /private/device-state --peer CLIENT-FINGERPRINT
```

吊销可防止新的授权工作并关闭受跟踪的通道。已被接受的原生调用可能会完成；
请调和其 ID。接收端重启会保留身份、配对和日志。中继重启会断开连接；
端点会重新连接并获取新的准入凭据。在发起新提交之前，就绪探测必须成功。
中继凭单具有短暂性且一次性有效；连接和帧大小均有上限。中继上不存在
明文/离线原生请求的队列。

默认前台服务生命周期为一小时；`--seconds 0` 为服务管理器显式选择持久化运行。
使用 SIGTERM 停止，并在清理前等待有界原生关闭。使用一致的 SQLite 快照
加上身份文件备份私有状态，保护该备份，且绝不要独立于 WAL 复制活动数据库。
身份证书有效期为一年；到期需要计划新的身份/重新配对，而不是静默替换设备固定公钥。

隔离的实时验证使用环回/SSH 隧道；它并未确立关闭 VPN 情况下的公共 WSS
就绪状态。公开试点、重启/浸润测试以及发布关卡均在[现行开发计划](relay-development-plan.md)中进行跟踪。

### 更新配对路由

当配对设备更改其地址时，保留固定的身份和投递日志。这会替换保存的路由；
请包含您希望保留的所有路由。

```sh
session-peer device routes --state ./client-state --peer RECEIVER_FINGERPRINT \
  --relay wss://relay.example.com/v1/connect
```

路由变更不会授权新身份或恢复已被吊销的设备。有关有界实时 Antigravity
测试和剩余发布关卡，请参阅[公开试点证据](relay-public-pilot-2026-09-17.md)。

## 首次连接公共Relay

需要Python 3.11+的macOS/Linux(Windows使用WSL)和另装的Relay extra，skill/plugin本身不会安装。新pipx环境使用 `pipx install --python python3.11 'session-peer[relay]'`，已有环境保留原管理器；standalone继续用于local/SSH，另选Relay环境。两端分别使用私有state执行以下命令，将 `FULL-UUID` 替换为新的操作UUID，响应不确定时保留此UUID。

```sh
session-peer device init --state /private/device-state
session-peer device login --state /private/device-state --server https://relay.abruption.dev
session-peer device enroll --state /private/device-state --name laptop --operation-id FULL-UUID
```

按上方schema创建receiver policy，启动 `session-peer` `device serve --state /private/device-state --policy /private/receiver-policy.json --relay wss://relay.abruption.dev/v1/connect --login --seconds 3600`。在另一终端运行 `session-peer` `device invite --state /private/device-state --relay wss://relay.abruption.dev/v1/connect --out /private/invite.json`，安全转交邀请。已登录并注册的client须在10分钟内运行 `session-peer` `device pair --state /private/client-state --invite /private/invite.json --route relay --login`，然后 `session-peer list --device RECEIVER-ID --device-state /private/client-state --device-route relay --relay-login --json`。保持receiver运行。注册、配对和native权限互不等同。发送前先dry-run；queued不是ACK。引导不会自动安装、登录或重试。一般403/404或 `no_authenticated_route` 不能证明receiver已停止。仅按证据区分登录缺失/过期和设备查询失败，不确定的发送须核对而非重发。

配对接收端会在引用正文之外显示已认证的 TLS 证书指纹。它识别的是配对设备的密钥，而不是人员或原生代理会话；正文中的 From 或 Reply-To 声明不能替换它。最终的引用正文、指纹和警告必须在开始记录或原生投递之前满足 32 KiB 限制。Reply-To 的可信度不会超过其外围标记的可信度；第三方路由应由会话所有者确认。此机制不绕过审批，也不保证完全抵御提示注入。
