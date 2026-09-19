# 中继生命周期加固（开发）

这些更改目前正在针对 #69 进行开发。它们不是已发布的 RC，尚未通过 24 小时运行门禁或真实的 OAuth 提供商验证。

## 稳定设备与显式轮换

初始证书指纹保留为逻辑设备 ID。公钥版本具有单独的指纹和代系。策略、路由和请求收据保持附加到逻辑 ID，包括跨接收方密钥变更。附加式 SQLite 迁移保留了现有的 v0.9 身份和收据。

在轮换前停止设备接收方以及其他使用其状态的命令：

```sh
session-peer device rotate --state /private/device-state \
  --operation-id REPLACE-WITH-A-FULL-UUID --route direct
session-peer device rotation-status --state /private/device-state
```

从丢失的响应中恢复时请保留操作 ID。切勿通过启动全新的轮换来解决未知结果。每个配对的对等节点必须具有显式配置的可达接收方路由，并支持 `identity-rotation-v1`。使用现有的 `device routes` 命令更新路由。接收方无法在离线客户端上透明地轮换其固定密钥；请先使该客户端接收方上线。

Prepare 会通过固定的 TLS 证明旧密钥，并验证由新密钥生成的签名。Commit 需要使用新密钥的 TLS 连接。在过渡期间，待处理和已退役的密钥仅拥有探测、收据状态和轮换对账访问权限。已提交的旧密钥有十分钟的恢复窗口期，并且无法提交消息。吊销优先于此窗口期。新的请求和冲突无法为同一代系创建第二次轮换。仅在所有记录的对等节点均已提交之后，才会发生本地激活。失败的尝试将保留相同的提案和私钥。

设备状态锁在普通命令或接收方持有状态时互斥轮换/备份。单独的接收方锁可防止两个本地接收方进程使用同一状态。这些是本地文件系统锁，而不是分布式租约：不支持将活跃身份复制到第二台计算机。

## 日志限制与恢复

```sh
session-peer device diagnostics --state /private/device-state
session-peer device backup --state /private/device-state \
  --policy /private/policy.json --out /private/new-snapshot
session-peer device restore --state /private/new-restored-state \
  --backup /private/new-snapshot
```

Diagnostics 报告全局 10,000 次请求限制、剩余行数、待处理的未知结果、SQLite/WAL 大小以及可用磁盘空间。通知、警告和严重阈值分别为 70%、85% 和 95%。达到容量上限时，新的提交会被拒绝；现有的收据和管理功能仍然可用。绝不会为了腾出空间而修剪收据证据。容量预留和收据创建是事务性的。

备份需要排他性状态锁，并包含身份版本、策略、一致的 SQLite 快照以及清单。输出是包含密钥的私有**未加密暂存目录**；请使用经批准的加密备份系统进行保留。切勿通过源代码版本控制发布或移动该目录。备份状态不会将密钥复制到中继或 OAuth 控制服务。

恢复会准备一个私有暂存目录，提交持久的恢复标记，然后才以原子方式发布目标。中断的暂存无法使用。现有收据仍可查询；缺失的收据返回未知，而不是证明未执行。传出和传入发送、密钥轮换变更以及新的配对/注册均保持受阻。收据状态查询仍然可用。不存在可以清除此保护措施的单命令覆盖。在规划恢复之前，请对账快照后的本地效应，并吊销/隔离旧身份。此开发实现尚未提供完整的丢失密钥恢复工作流。

## 可选的控制服务准入

独立的静态令牌中继仍然可用。由控制服务管理的中继使用：

```sh
session-peer relay serve --auth-state /run/session-peer-auth/state.json \
  --auth-issuer https://relay.example.com \
  --auth-replay-state /private/relay-state/spent-tickets.json --bind 127.0.0.1 --port 3769 --seconds 0
```

`--auth-state` 与 `--accounts` 互斥。只读状态包含验证公钥和最少量的设备所有权/吊销记录。不存在端点私钥、登录会话令牌和 OAuth 提供商机密。

准入需要一个短期 ES256 票据以及已注册 P-256 设备密钥的签名。Audience、issuer、generation、owner、receiver 和 room 均会被检查。在签发既有的一次性 WebSocket Cookie 之前，票据会被消费一次。缺失/无效的状态会导致闭锁失败（fail-closed）；现有的连接每秒都会重新检查吊销情况。控制服务签发和 Python CLI 已通过测试夹具集成。仅靠令牌验证测试不能证明真实的浏览器登录有效。

## 浏览器登录（集成候选）

```sh
session-peer device login --state /private/device-state --server https://relay.example.com
session-peer device enroll --state /private/device-state --name laptop --operation-id FULL-UUID
session-peer device pair --state /private/device-state --invite /private/invite.json --route relay --login
session-peer list --device DEVICE-ID --device-state /private/device-state --relay-login --output-format json
```

无头登录使用 `--no-browser`：在单独的浏览器中打开打印出的 URL 并确认其用户代码。私有设备代码和生成的会话令牌不会被打印出来。登录凭据作为私有 0600 文件存储在显式设备目录中。过期的登录需要另一次显式登录。核心本地/SSH 命令不会启动登录或联系此服务。

控制服务使用带有 GitHub/Google 的 Better Auth，并在 `control/` 下独立归属。Python 客户端和服务 API 已通过跨语言测试夹具集成。专用提供商凭据已准备就绪；真实的 OAuth 验证仍待完成。绝不能将单元测试报告为正常工作的公开登录。

对于控制服务管理的轮换，请将 `--login` 添加到 `device rotate` 中。它使用新旧密钥证明以及稳定的操作 ID 将暂存的公钥注册到控制服务，然后在完成独立的固定端点过渡时，将该新密钥用于外部准入。失败后请复用相同的操作 ID。

中继在签发 Cookie 之前提交已消耗的 JWT ID，并在重启时保留此小型重放文件。它不持久化有效负载。控制公有状态每 60 秒刷新一次，并在 180 秒内过期；缺失、过期或无效的状态会拒绝准入并关闭现有的受管连接。

受管准入还在现有的全局十个连接限制范围内，将单个用户限制为最多八个开放的中继连接，将单个设备限制为四个。公有状态带有持久递增的修订版本；中继会记住其最高修订版本，即使在重启后也会拒绝回滚或在相同修订版本上的冲突内容。该高水位线与已消耗票据文件一同保留，在控制状态恢复期间切勿将其丢弃。

操作员必须以服务身份初始化重放状态一次：

```sh
session-peer relay init-replay --out /private/relay-state/spent-tickets.json
```

这会拒绝覆盖任何文件。准入仅接受在此显式初始化后至少 65 秒签发的票据。`serve` 拒绝重新创建缺失的重放状态。切勿将初始化放入自动重启钩子中。发生状态丢失后，在进行显式恢复之前请先对账/隔离控制权限。尽管已消耗的票据 ID 很快就会过期，但同一文件还保留了控制修订版本高水位线，必须在服务生命周期内妥善保存。

## KR 服务备份与恢复暂存

已部署的 KR 服务在其加密的 Restic 作业之前使用 `deploy/kr/session-peer-backup-snapshot.py`。该辅助程序会短暂停止协同栈，并创建一个仅 root 权限的恢复集，其中包含事务一致的控制数据库、准入签名密钥、提供商配置、公有认证状态以及中继重放/高水位线文件。它在使快照可见之前验证数据库完整性和签名密钥已发布的 JWK，然后恢复先前处于活跃状态的栈。部分快照将中止 DR 作业。

Restic 范围还包含不可变的控制和中继运行时、就绪辅助程序以及已安装的服务单元。恢复必须首先还原到隔离的仅 root 权限目录中，并验证快照清单、文件哈希和模式、SQLite 表计数、状态/重放修订版本、已消耗条目、签名密钥以及运行时链接。切勿覆盖正在运行的活跃服务，也不要自动晋升旧的控制数据库、签名密钥或重放高水位线。生产环境替换仍需要停止的栈以及显式的回滚/吊销隔离。
