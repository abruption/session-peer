# 配对设备与私有中继 (v0.9 beta)

这一可选的 Unix/Python 3.11+ 传输方式将请求传递到操作员定义的
Claude、Codex 或已注册的 Antigravity 端点。通常的本地/SSH 命令
保持无外部依赖。这是一个显式的 CLI 工作流；不会安装移动端应用程序、
NAT 穿透、WireGuard 隧道或自动公开服务。

## 安装

在两台设备上的隔离环境中从 PyPI 安装 session-peer v0.9.0 或更高版本：

```sh
python3 -m venv ~/.local/share/session-peer-relay/venv
~/.local/share/session-peer-relay/venv/bin/pip install 'session-peer[relay]'
```

中继扩展组件（relay extra）自 v0.9.0 起在 PyPI 上提供，并保持 Beta 状态；
发布并不代表确立了长期的运维稳定性。请使用下文安装的
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
或清空日志以重试未知项。保留/轮换以及长期运行的集群管理仍属于发布候选版（RC）强化工作。

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
