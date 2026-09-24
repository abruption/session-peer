# 配对设备与私有中继 (v1.0)

这一可选的 Unix/Python 3.11+ 传输方式将请求传递到操作员定义的
Claude、Codex 或已注册的 Antigravity 端点。通常的本地/SSH 命令
保持无外部依赖。这是一个显式的 CLI 工作流；不会安装移动端应用程序、
NAT 穿透、WireGuard 隧道或自动公开服务。

## 连接失败诊断与安全的连接重试

`no_authenticated_route` 保留 `retryAllowed:false` 和 `consumptionConfirmed:false`。`routeFailures` 给出每条失败路径最后一次的 `stage`、允许列表中的 `reason` 和 `attempts`。有界的 `attemptHistory` 保留每次尝试的阶段、原因和 `elapsedMs`；HTTP 拒绝还可能包含 `httpStatus`，WebSocket 关闭可能包含 `closeCode`。控制、准入、升级、attach、对端 TLS 和 probe 故障可以区分，但不会记录 URL、凭据、原始异常或消息正文。第二次尝试成功时会有 `setupDegraded:true`、`setupAttempts:2` 和 `setupFailureHistory`，不能算作干净的稳定性测试通过。

仅在**WebSocket 升级前的控制或准入超时**时，等待 0.5 秒后再尝试连接一次。attach、对端 TLS 和 probe 超时不会重试。WebSocket 升级超时也不重试，因为 origin 可能已经配对并消耗了接收端房间。使用新的准入票据和通道，不重用已消耗的票据，也不重发代理消息。HTTP 拒绝、身份/证书错误和未知失败也不会重试。直接路径获选时仍可取消 Relay 尝试。提交后丢失响应仍为 `unknown`，不重发、不切换路径。此有限缓解措施不代表公开网络故障已经解决；部署后必须重新验证实际 ACK 和长时间运行。

接收端每分钟最多向 stderr 输出一条经过清理的 `relay_connection_failed` 警告。疑似正常空闲到期的关闭与故障警告分开。显式使用 `device serve --diagnostic-events` 和 `relay serve --diagnostic-events` 时，只向 stderr 记录房间、attach、关闭阶段、耗时、允许列表内的原因及关闭代码。默认关闭；不会记录设备身份、房间名、URL、标头、凭据或正文。Relay 指标还会增加房间创建与配对、每条连接的 attach 发送以及到期计数。attach 发送不能证明客户端已收到。接收端的 `idle_expiry_like` 不能证明服务器端原因。

WebSocket 关闭的 `closeSource` 区分代码来自接收还是发送。Relay 计数器区分接收端先到和客户端先到的房间。`receiverWsAgeMs` 只表示等待时长，不能证明连接健康；需要对照配对时间与接收端的 `attach_received`、对端 TLS 事件。

`stream_close.closeCode` 是从远端收到的关闭代码。`1006` 表示未收到关闭帧，可能提示连接停滞。`peer_closed` 表示另一条连接结束后 Relay 关闭了本连接；`remote_going_away` 表示远端在 Relay 未发起关闭时自行发送了 1001 代码。`receiverRoleBusy`、`clientRoleBusy` 统计同一房间中被拒绝的重复连接；接收端计数上升可能意味着接收端重连时 Relay 仍持有旧连接。

若等待房间已开启至少 1 秒后被 Relay 正常关闭，接收端会在 0.5 秒后重连，而不会增加退避时间。其他失败以及 1 秒内关闭的房间仍按指数退避，最长 5 秒。Relay 连接两端均使用 10 秒的 WebSocket ping 间隔与超时，因此停滞连接约 20 秒即可检测到，而不是约 40 秒。这些改动只缩短重连空档，并不能修复停滞的网络路径。

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
      "codexHome": "/home/alice/.codex"
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

由 launchd 或 systemd 等服务管理器启动的接收端继承的是该管理器的最小 `PATH`，而不是登录 shell 的环境。在 macOS 和 Linux 上，目标 TUI 所用的同一个 `codex` 可执行文件所在目录必须位于接收端的 `PATH` 中；launchd 默认的 `/usr/bin:/bin:/usr/sbin:/sbin` 不包含 `~/.local/bin` 或 `/opt/homebrew/bin`。`codexBin` 仅适用于下文的 WSL 绑定。在依赖接收端之前，请在相同环境下对已绑定的目标运行 `send --dry-run` 进行确认。否则 Codex 投递会失败，目前会报告为 `native_outcome_unknown` (#176)。

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

Linux/macOS 目标省略两个可执行文件字段。Windows 客户端继续使用普通本地 CLI。成功提交仍为 `consumptionConfirmed: false`，消费须由独立观察到的回复确认。即使更新策略或接收端，也不要自动重试 unknown 发送。

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
