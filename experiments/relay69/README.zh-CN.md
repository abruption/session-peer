# #69 配对设备中继实验室

基于本地 #47 提交 `993d04d` 的实验性、仅用于测试固件的代码。**不是生产环境接收器、插件或已安装的 CLI 命令。** 普通软件包、本地/SSH 行为以及已安装版本均未改变。未使用任何原生 Claude/Codex 会话、收件箱、队列、模型凭据或配额。

## 本地复现

需要 Python 3.11+ 和支持 TLS 1.3 的 OpenSSL。测试过的环境为 macOS Python 3.14/3.13 和 Ubuntu arm64 Python 3.12。

```sh
python3 -m venv /tmp/session-peer-relay-lab
/tmp/session-peer-relay-lab/bin/pip install -r experiments/relay69/requirements.txt
/tmp/session-peer-relay-lab/bin/python -m unittest tests.test_relay69 -v
```

测试使用回环 TCP、真实 TLS、本地 WebSocket 中继和一次性状态。在没有可选依赖项的情况下，普通的 unittest 发现机制会跳过此模块。本实验不包含在 wheel 或 sdist 中。任何 import 操作都不会启动监听器。

## 组件与边界

- `identity.py`：本地生成的 P-256 私钥和短期自签名证书。密钥/状态权限为 0600/0700，绝不会放入邀请中或复制到中继。这是文件系统保护，而非生产级操作系统密钥链。
- `wire.py`：使用 Python/OpenSSL MemoryBIO 通过 TCP 或二进制 WebSocket 帧实现 TLS 1.3/ALPN。客户端显式信任并固定被邀请的证书。已配对的接收器在 list/send 之前需要已识别的客户端证书。未知的未经身份验证客户端每次连接只能尝试一次邀请预留。公共中继 URL 需要 WSS；明文 WS 仅限于回环测试。拒绝 HTTP 和 WS 重定向。
- `store.py`：十分钟有效、单次使用的邀请预留；待定/已配对/已吊销的设备状态；独立于 agent 数据库的执行日志。配对仅在双向 TLS 证明了提议的密钥之后才会提交。处于待定状态的发起方可以使用相同的密钥调和丢失的提交响应。吊销会关闭活动通道；轮换是吊销加上重新配对，而非无缝续期。
- `relay.py`：限定角色/房间范围的准入凭据会签发 120 秒有效的 HttpOnly 会话 cookie。身份验证在协议升级前发生。中继仅转发密文，不持有端点密钥。它可以看到路由/角色、IP、时间、长度和密文。Cloudflare/Caddy 可以看到外部 TLS 元数据**以及准入凭据/cookie**，但看不到内部 TLS 明文或密钥。外部身份验证不是端到端身份，不能替代对端 TLS 验证。
- `app.py`：所有接收到的操作都会通过 #47 `LocalTransport` 和一个显式实例化的确定性测试固件适配器。线上操作为 probe/list/send/status；不提供任意命令、路径、原生适配器或唤醒功能。请求绑定版本、双方身份、UUID、过期时间、操作和主体；TLS 通道提供记录完整性和重放保护。

日志在调用测试固件适配器之前提交待处理意图。具有相同主体的相同 peer+message ID 会返回已存储的结果；不同的主体将被拒绝。在适配器调用和结果提交之间发生的崩溃将保持未知状态，且绝不会自动重新执行。这更倾向于最多一次尝试而非活性。这**不是**恰好一次的原生投递。`submitted` 与 `consumptionConfirmed` 是分开的，后者保持为 false。`relayAttached` 描述载体连接；只有经过身份验证的端点探测才能确立接收器的就绪状态。

自动路由会在经过身份验证的直连探测和中继探测之间竞速，若两者在同一选择周期内完成，则优先选择直连。消息仅发送给唯一的胜出者。提交后的失败不会切换路由或重新发送。在检查未知结果时，请使用带有原始消息 ID 的 status。

## 显式命令

在工作树根目录下使用实验 venv 运行：

```sh
python -m experiments.relay69 init --state /private/test/receiver
python -m experiments.relay69 invite --state /private/test/receiver \
  --out /private/test/invitation.json --direct 127.0.0.1:3769
python -m experiments.relay69 serve --state /private/test/receiver \
  --bind 127.0.0.1 --port 3769 --seconds 1800
python -m experiments.relay69 pair --state /private/test/client \
  --invite /private/test/invitation.json --route direct
python -m experiments.relay69 request --state /private/test/client \
  --peer RECEIVER_FINGERPRINT --route direct --op send --message fixture-only
```

在配对之前，通过单独受信任的管理途径，将邀请的证书指纹与接收器的 `init` 输出进行比对。实验室使用现有的 SSH 传输公开邀请材料，使用私密文件传输一次性密钥。切勿将邀请、准入密钥或 cookie 粘贴到日志或 URL 中。`request --op status --message ORIGINAL_MESSAGE_ID` 可调和不确定的结果。`revoke --state RECEIVER_STATE --peer CLIENT_FINGERPRINT` 可吊销该测试客户端。

对于中继模式，在 git 外部准备两个随机的 256 位准入凭据，每个角色一个。中继 `--accounts` 文件是 `{hash: SHA256(credential), room: test-room, role: receiver|client}` 的 JSON 数组。端点仅在权限为 0600 的 `--admission-file` 中接收其自身的凭据；它们绝不会接收对方的私有 TLS 密钥。在 invite 和 serve 中均添加 `--relay wss://HOST/v1/connect`，并使用 `pair --route relay`。接收器和客户端均向外出站连接。中继命令接受 `--bind`、`--port`、`--accounts` 和 `--seconds`。

公开试验使用了专用主机名、现有的 CF/KR TLS 终止以及 KR 到 US 的 tailnet 上游。公开配置特定于基础设施，不会由此代码库自动配置。目前未保留任何已部署的试验。

## 运行限制

中继允许 10 个连接、每秒 20 个 HTTP 准入/升级请求、100 个有效 cookie、256 KiB 帧、4 帧接收水位线、32 KiB 传输写入水位线、2 秒转发截止时间和 32 MiB 总转发字节数。TLS JSON 消息限制为 64 KiB，消息主体限制为 32 KiB。接收器将连接数限制为 8 个，每个连接的请求数限制为 100 个；其日志在达到 10,000 条记录时停止，而不是静默逐出重复数据删除历史。这些限制属于测试预算，并非经过调优的产品保证。

服务生命周期最长为 30 分钟。公共后端还使用了独立的 systemd 运行时间限制、DynamicUser、无 capabilities、只读代码、ProtectHome、显式禁止目录、私有 tmp/devices、256 MiB 内存、50% CPU 和 64 个任务。Cgroup IP 规则仅允许 KR 访问 US 后端。沙箱预检断言其他主目录和产品目录不可读。未安装任何新的防火墙规则、DNS 记录、持久账户或全局 Python 包。Mac 测试固件客户端使用独立的状态/venv；它们并未声称具备 Linux 沙箱的操作系统隔离性。

实际应用将需要更强大的设备生命周期/UX、绑定来源的准入配置、单设备配额、离线恢复、依赖项和协议审查，以及平台服务/密钥存储设计。接收契约必须继续区分中继连接、端点接受和原生提交。参见[实测报告](REPORT.zh-CN.md)。
