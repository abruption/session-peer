# 私有中继控制与认证 (RC 候选)

状态：#69 的实现候选方案，并非已部署的生产服务。
以下 control 到 relay 的协约结合了 Python 所有者的最终
接口指令；实际的跨服务集成仍是一个独立的关卡。本项目不会在普通 Python 安装中添加任何侦听器、
OAuth 账户或 Node 依赖。

## 信任边界

`control/` 是一个独立的 Node 22/24 React/Vite + BetterAuth **1.7.5** 服务。
GitHub 和 Google 是唯一配置的登录提供商。缺失提供商
凭据不会暴露任何虚假登录。密码登录/注册已被禁用。OAuth
账户 ID 是授权身份，而非电子邮件地址。每次 control
API 调用都会再次检查原生 BetterAuth 会话、显式允许名单或已提交的
公开注册记录，以及内部用户 ID 所有权。暂停注册
不会驱逐已提交的公开身份。
不允许基于电子邮件的自动账户关联。启用具有相同电子邮件的另一个提供商
不会暗中向其授予现有用户的设备。

仅限允许名单的运行模式仍然是故障闭锁默认设置。运维人员可以显式
启用不受限的已验证公开注册。已验证的提供商回调会在
BetterAuth 创建用户之前预留其身份；若运维人员随后关闭新的注册，
已提交的身份仍可继续使用。账户和会话的创建
也受 BetterAuth DB 钩子检查。被拒绝的回调无法占用
永久公开配额或授予 control 访问权限。

Web 端 `/login`、`/device`、`/devices` 在生产中使用 HTTP-only 安全 Cookie。
设备页面会显示代码、客户端和作用域，要求代码匹配
确认以及显式的批准/拒绝，并针对意外请求发出警告。
额外的 control 声明表将已验证的代码绑定到**精确的浏览器
会话**，而不仅仅是用户。BetterAuth 自身的第一方声明是绑定到用户的；
此封装层提供了更窄的会话限制。

CLI 登录使用 BetterAuth 的 `deviceAuthorization()` 和 `bearer()`：

- `POST /api/auth/device/code`，`client_id=session-peer-cli`。
- 打开所提供的验证 URI；进行身份验证并检查/批准该代码。
- 按公布的时间间隔（5 秒）轮询 `POST /api/auth/device/token`。
  授权类型为 `urn:ietf:params:oauth:grant-type:device_code`。
- `access_token` 是**第一方 BetterAuth 会话令牌**，而不是 OAuth
  提供商访问令牌、OAuth 保护的资源令牌或中继 JWT。
- 仅将其作为 `Authorization: Bearer …` 发送到此配置的 control 源。
  令牌随 BetterAuth 会话（24 小时）一同过期；此处未添加任何刷新令牌或
  永久后台登录承诺。OS 凭据存储和
  CLI 用户体验属于 Python/客户端所有者的集成职责。
- 仅浏览器 Cookie 会话可以验证/批准/拒绝；bearer 批准会被
  拒绝。设备代码有效期为 5 分钟；拒绝、过期、轮询限制
  和一次性兑换均使用固定的 BetterAuth 实现。

OAuth 回调（需要运维人员应用配置）：

```
https://relay.abruption.dev/api/auth/callback/github
https://relay.abruption.dev/api/auth/callback/google
```

## 最终 control API (未发布候选)

仅限 JSON 正文；最大 16 KiB。未知的协议字段将被拒绝。
经身份验证的 API 请求限制为 60 次/用户/分钟。限制为每个所有者 16 个活动
质询、包括墓碑在内总共 32 个设备身份，以及 4096 个持久
操作。绝不会为了腾出空间而暗中删除操作记录；
达到限制时将故障闭锁，包括待处理的操作。

| Endpoint | Result / checks |
| --- | --- |
| `GET /api/relay/devices` | Only caller-owned devices; no certificates/secrets |
| `POST /api/relay/challenge` | `{operation: "register" | "admission", payload}`; owner/operation/full-payload bound nonce, 60-second window |
| `POST /api/relay/devices` | Initial registration or key renewal; payload + `challengeId`, new-key `proof`, old-key `previousKeyProof` for renewal |
| `GET /api/relay/operations/:id` | Owner-only pending/committed result, for lost-response reconciliation |
| `POST /api/relay/admission` | Admission payload + `challengeId`, `proof`; short-lived ES256 relay JWT |
| `POST /api/relay/devices/:principal/revoke` | Owner session; no lost-device key requirement; permanent tombstone |

### 注册与证书更新

```text
{ principal, certificatePEM, keyGeneration, name, operationId, expectedGeneration }
```

`principal` 是一个固定的、随机的 64 位小写十六进制设备身份，与证书分离。`operationId` 是在得知
结果前一直保留的 UUID v4。初始注册要求 principal 等于初始证书 DER
SHA256、设备尚不存在、`keyGeneration=0`，
且省略 `expectedGeneration`。更新则要求同一所有者现有的活动 principal、
`expectedGeneration=current generation` 以及 `keyGeneration=expectedGeneration+1`。
服务器会计算/检查增量；客户端无法选择跳跃或回滚。
最大世代为 2147483647。更新时会保留所有者、principal 和现有名称；
`name` 用于初始注册（更新时发送现有
名称）。名称为 1–80 个字符，不含控制字符。

证书输入恰好为一个公开的 PEM 证书，<=8192 字节，具有
P-256 密钥且当前有效期限超过 60 秒。新证书
必须不同于存储的证书。允许使用相同密钥进行证书更新。
拥有权是通过签名而非公共 CA 验证来确立的；注册
绝不会取代端点 E2EE 配对/PIN 授权。切勿提交私钥。

初始注册和更新都使用质询操作 **register**，然后
调用 `POST /api/relay/devices`。新密钥的 `proof` 对返回的精确 `proofMessage` 进行签名。
更新时还额外需要旧密钥对**同一消息**的 `previousKeyProof`。
不允许仅凭登录进行替换。只有持有存储的旧密钥才能
忽略旧证书的有效日期，从而允许更新已过期的证书；
新证书的有效性及普通准入有效性仍受到强制执行。丢失
旧密钥需要所有者吊销并创建新的 principal。已吊销的身份绝不能
通过注册、更新或重试来恢复。

变更、质询消耗和已提交收据构成同一个 SQLite 事务。
更新会立即使所有者未完成的质询失效，立即重新发布状态，
并拒绝跨越世代变更的准入签名。

### 操作结果 / 重试边界

注册质询在返回前会持久预留所有者/operationId/有效载荷
摘要。变更前查询所有者将返回：

```json
{ "operationId": "<fixed UUID v4>", "committed": false }
```

已完成的注册和 `GET /api/relay/operations/:id` 返回：

```json
{
  "operationId": "<fixed UUID v4>",
  "committed": true,
  "principal": "<unchanged ID>",
  "keyFingerprint": "<SHA256 certificate DER>",
  "keyGeneration": 1
}
```

未知的 ID 和其他所有者的 ID 均返回 404。待处理的预留
在质询过期后仍将保留。对于相同的已完成所有者/有效载荷/operationId 进行重试，
将返回存储的历史收据，而不会再次执行变更或证明，
即使质询已过期或设备随后已被吊销也是如此。更改了有效载荷
或不同所有者的 operationId 重用将被拒绝。收据**不是当前设备
状态**；请使用设备列表查看当前世代/吊销情况。对已吊销收据
重试无法复活设备。发布失败将回滚变更并使其操作保持
未提交状态，同时健康检查会在发布恢复之前阻止
准入。丢失响应时请保留 ID 并查询状态；切勿创建新
操作或自动重试可能已被接受的原生代理提交。

### 质询证明与时间单位

响应：`{challengeId, nonce, issuedAt, expiresAt, proofMessage}`。所有 control
API 和公开状态的 `issuedAt`/`expiresAt` 值均为 UNIX **秒**数值。
BetterAuth 的原生认证 API 保留其安装的 SDK 形式；`expires_in` 和
`interval` 为相对秒数。客户端使用 P-256 ECDSA/SHA256 对返回的精确
UTF-8 消息进行签名，DER 签名编码为不带填充的 base64url：

```text
session-peer-control-v1:
<origin>
<operation>
<challengeId>
<nonce>
<SHA256 of server-canonical payload JSON>
```

客户端要求必须包含 `session-peer-control-v1:` 前缀，然后对返回的
精确字符串签名，无需解析/重构其余部分。无末尾换行符。服务器规范化会绑定每个注册字段，
包括 operationId/expectedGeneration；客户端无需进行 JSON 规范化。
准入证明使用已注册证书的当前密钥。注册证明
使用提交的证书；更新的 previousKeyProof 使用存储的旧密钥。

`keyFingerprint` 为小写的 **SHA256(证书 DER)**，与现有的
Python fingerprint/keyId 含义相匹配。`cnf.jwk` 从该证书的
公钥中提取。它**不是 SHA256(SPKI DER)**。仅凭 JWK 无法重构证书
DER；中继会将已签名的证书指纹与当前状态进行比对，并
信任已验证身份的 control 签发者与 cnf 的已签名绑定，然后使用 cnf
验证拥有权。请勿计算 JWK/SPKI 哈希并将其与此字段比对。
用于签名的 `kid` 标识单独的 control 签名密钥（目前为 SPKI 哈希）；
它不是设备证书指纹。

### 准入令牌与中继交换

准入有效载荷：

```text
{ role: "client" | "receiver", devicePrincipal, receiverPrincipal }
```

两个 principal 必须均为活动状态且归同一个内部用户 ID 所有；receiver
角色必须标识其自身。Room = SHA256(UTF8(userId + NUL + receiverPrincipal))，
无域名前缀。调用方无法设置 room/user/issuer/audience/TTL。

JWT 使用 **ES256**、已识别的签名 `kid`、`typ=JWT`。声明包括 `iss`/`aud` =
配置的中继源、`sub` = 内部不透明用户 ID、`devicePrincipal`、
`receiverPrincipal`、`keyFingerprint`、`keyGeneration`、`role`、`room`、`iat`、
`exp` (iat+60 秒)、`jti`、`cnf.jwk` (仅公开 EC P-256，无私钥材料)。
响应 `{token, expiresAt, room}` 使用 UNIX 秒过期时间。无论是提供商
访问令牌还是第一方会话令牌都不会发送给 Python 中继。

中继交换：

```http
Authorization: Bearer <JWT>
X-Session-Peer-Proof: <unpadded base64url DER ECDSA signature>
```

设备使用 P-256 ECDSA/SHA256 对精确的 UTF-8 `session-peer-admission-v1:` + **整个 JWT**
进行签名，无末尾换行符。这与 control nonce 证明是分开的。
Python 必须在原子性单次使用 jti 消耗和 Cookie 签发之前，验证签名/签发者/受众/时间/生命周期<=60/已识别的 kid、
公开 P256 cnf、当前状态/所有者/世代/指纹/角色/接收方/room 以及
拥有权。失败的证明不得消耗另一台设备的 jti。重放存储必须在
JWT 过期之前跨重启/多个工作进程进行验证。这些是 Python 集成关卡；
control 格式测试并不能确立 Python 接收方实现了它们。
OAuth 登录/注册不会取代端点 E2EE 配对/PIN 策略。

## 运维人员指标

`GET /api/admin/metrics` 是仅限浏览器会话的运维人员端点。运维人员是
经过身份验证的用户，且在 `SESSION_PEER_ALLOWED_ACCOUNTS` 中显式列出了至少
一个提供商身份；公开注册绝不会授予此角色。
响应包含汇总的服务健康状况、注册状态和计数、设备计数、
操作计数以及当前公开状态修订版本。它绝不会返回电子邮件、
提供商账户 ID、内部用户 ID、设备 principal、证书、令牌或
密钥。React 路由为 `/admin/metrics`，每 30 秒刷新一次
汇总视图。

`admin.abruption.dev` 继续作为现有的 Authelia 管理门户。其根路径和
`/api/*` 路由已由认证控制台占用。请使用精确的 `/session-peer` 门户页面，
并用 Authelia 同时保护该页面和 `/session-peer/api/metrics`。聚合 API 由
独立的 `127.0.0.1:3771` 监听器提供，绝不能经由公共中继主机路由。这样
Authelia 就是唯一的浏览器登录边界，同时公共中继无需信任转发的身份标头。
为直接访问中继的情况保留现有 `/admin/metrics` 和 `/api/admin/metrics`
的提供商运维人员授权。

### 原子公开状态与协约过渡

```text
{ schemaVersion: 1, revision, issuer, audience, issuedAt, expiresAt,
  jwks: { keys: [public signing JWK with kid/alg/use] },
  devices: { principal: { userId, keyFingerprint, generation, revoked } } }
```

无名称、电子邮件、证书、会话/OAuth 令牌或私钥。用户 ID 是
匿名化的所有权元数据。没有任何公开 HTTP 路由提供该目录的服务。
只读**目录绑定**（而非单文件绑定）可在不授予对私有数据库/签名密钥/本体/其他服务文件
访问权限的情况下，暴露原子替换。
切勿扩大 DynamicUser 父目录的范围以暴露私有同级项。

每次发布都会在任何设备变更事务或文件替换之前，在 control
SQLite 数据库中持久预留一个新的安全整数 `revision`。
即使变更回滚，预留仍然有效；允许存在间隙，但不允许重用。SQLite
使用 WAL 配合 synchronous FULL。启动时会拒绝早于现有
公开文件的计数器。Python 还会额外持久化其最高修订版本和内容哈希。
完整的主机回滚仍需要外部恢复隔离；绝不能通过等待恢复的
计数器追赶上来复活已吊销的设备。

公开目录显式设为 0755，即使在 umask 0077 下也是如此。每个新状态
文件在 fsync/rename/目录 fsync 之前都会执行 fchmod 0644；其私有父目录和
私有数据库/签名材料仍然受到保护。目录绑定挂载无需替换目录
即可观察到原子文件替换。

状态每 **60 秒**重新发布一次，在 **issuedAt+180 秒**时过期，
并在发生变更时立即发布。如果状态缺失/格式错误/
过期或 issuedAt>now+5 秒，Python 将故障闭锁。它会在每次准入时重新读取，
并每秒重新检查现有连接，关闭已吊销/轮换的会话。仅凭 JWT TTL
并不是活动会话吊销。实际的连接/时钟/重启行为需要
Python/分级环境验证。发布失败会回滚数据库变更并
将健康状态标记为失败；SQLite 和文件并不是分布式原子事务。
发布后发生数据库提交失败可能会暂时拒绝访问；切勿将该失败
操作报告为成功或绕过过时状态检查。

最终协约取代未发布的候选版本 55ff3bb/6815e1e/fae9029（SPKI 设备哈希、
毫秒级质询、独立域 rotate 端点、2s/10s
状态）。切勿将旧工件/客户端与此验证器混用。启动时会拒绝包含
`contract_migration_required` 的已存 SPKI 设备行；绝不会
暗中重新解释旧设备指纹或操作历史。注册模式标记还会
拒绝较早的已填充候选数据库，而不会重新编号世代或丢弃收据。请使用新的隔离候选状态，
或规划经过运维人员审查且保留旧状态的显式迁移。此处不执行自动
凭据/设备状态删除。

## 构建、密钥与运维

从 `control/`：

```
npm ci
npm run typecheck
npm test
npm run build
```

生产环境必须显式配置一个 HTTPS 源（不得使用通配符受信任源）、
一个 >=32 字符的随机 BetterAuth 密钥、可选的应急
提供商账户 ID 允许名单、显式的公开注册开关以及启用的
运维人员拥有的 OAuth 应用。示例**非保密**值：

```
NODE_ENV=production
SESSION_PEER_CONTROL_ORIGIN=https://relay.abruption.dev
SESSION_PEER_ALLOWED_ACCOUNTS=[{"provider":"github","accountId":"REPLACE_WITH_NUMERIC_PROVIDER_ID"}]
SESSION_PEER_PUBLIC_SIGNUP=true
SESSION_PEER_CONTROL_DATA=/var/lib/session-peer-control/private
SESSION_PEER_RELAY_PUBLIC=/var/lib/session-peer-control/relay-public
GITHUB_CLIENT_ID=REPLACE_WITH_OPERATOR_APP_ID
GOOGLE_CLIENT_ID=REPLACE_WITH_OPERATOR_APP_ID
```

若缺少允许名单，则默认拒绝全部，除非运维人员显式设置
`SESSION_PEER_PUBLIC_SIGNUP=true`。公开注册没有邀请名单或用户数量
上限。将其重新设为 `false` 会关闭新注册，而之前已提交的公开身份和显式允许名单条目仍然可用。
提供商验证最多会创建十分钟的待处理身份预留，
并且 SQLite `IMMEDIATE` 事务可防止并发回调竞争
同一身份。OAuth 密钥和 BetterAuth 密钥来自
`*_SECRET_FILE`/`BETTER_AUTH_SECRET_FILE` 以及 systemd LoadCredential；
切勿提交它们或复制浏览器凭据。在运维人员控制的
本地/测试环境中也支持原始环境变量值；切勿打印环境转储。
对于已启用的 GitHub/Google 提供商，请在部署覆盖配置中添加 LoadCredential 条目及相应的
`GITHUB_CLIENT_SECRET_FILE`/`GOOGLE_CLIENT_SECRET_FILE` 路径。
缺失或配置不全的凭据将拒绝启动。已禁用的提供商不得配置
客户端 ID 或密钥文件。

运行 `npm run db:migrate` 时请使用相同的受保护配置，然后
运行 `npm start`。迁移是显式的；生产环境不会在每次启动时
暗中重写认证模式。本地开发仅允许在 localhost 或 127.0.0.1 上使用 HTTP，且不得使用生产密钥。状态必须位于源码之外且位于
iCloud 之外。私有签名密钥仅生成一次，权限为 0600 模式，并在
重启后保留。所有私有数据库/状态父级仅限所有者访问；备份必须将
control SQLite 一致快照、签名密钥和 OAuth 策略作为单独的
受保护资源包含在内。这**不是**中央本体 SQLite。

`deploy/session-peer-control.service` 是安装模板，而非已启用的
单元：回环 3770、DynamicUser、独占 flock 写入锁、私有持久
状态、受保护的 homes/system/kernel、仅暴露其只读 control 树的隔离
`/opt` 挂载、不可访问的其他服务 data/config/log 路径、无
capabilities、256MiB/50% CPU/64 任务。
部署必须在 `/usr/bin/node` 处提供受支持的 Node，安装已构建的
control 树，在服务私有状态中迁移认证模式，并设置提供商
凭据/策略。启动锁可防止多个 systemd control 写入者同时运行；
手动启动必须使用相同的锁。安装过程中请检查锁所有权/状态路径。
Node 内存/运行时行为仍需在分级环境中进行观察。

Caddy 集成应将 `/api/control/*`、`/api/auth/*`、`/api/relay/*` 以及
网页/资产分流至 3770，与现有的 Python 中继 WebSocket/准入路径分开。
在与分级环境所有者共同审查集成工件和资源隔离之前，切勿重载
Caddy 或开放主机名。未知路径返回 404；
`.env` 和源码/状态文件不是静态资产。安全标头包括
no-store、严格的 CSP、防框架嵌套和 no-referrer。HTTP 服务器既不信任
X-Forwarded-Host 也不信任任意 Host 值。代理必须保留配置的
源 Host。服务器会从回环套接字覆盖其认证 IP 标头；不受信任的
X-Forwarded-For 无法绕过认证速率限制器。该保守的候选版本在
本地代理间共享认证端点限制，因此多用户容量仍需在
分级环境中进行评估。多个 Set-Cookie 标头分别保留。
未启用请求 URL/标头/正文/令牌日志记录；诊断
消息仅包含固定的操作错误代码。

## 验证边界

本地测试使用真实的 BetterAuth/SQLite/device-code 端点、生成的测试夹具
P-256 证书与加密算法，以及回环上的已编译 HTTP 服务器。认证
夹具在私有临时 control 数据库中预置测试用户/账户/会话。
单独的回调测试仅模拟出站 GitHub/Google 传输，使用夹具
凭据和已签名的夹具 Google 令牌；它们运行固定的原生 OAuth
state/PKCE/callback/allowlist/account-linking 路径。不发送任何提供商请求。
**不存在生产虚假 OAuth 端点或认证绕过**。OpenSSL 仅供测试使用。
测试涵盖所有者隔离、策略吊销、CSRF、精确浏览器会话声明、
代码批准/拒绝/过期/兑换、质询过期/重放/篡改、密钥
替换拒绝、双密钥轮换、世代竞争、同一消息 previousKeyProof、仅所有者持久操作
查找/待处理/已提交/重新打开数据库重试、
过期证书更新、已吊销墓碑、原子状态发布失败
及非秘密状态、
回环/静态/Host/正文限制行为、拒绝伪造的 Google ID 令牌以及
未列入允许名单/相同电子邮件不同提供商的身份。这些不是带凭据的提供商
OAuth、Mac 用户浏览器、Python JWT 集成、24 小时运行或真实 Claude
配额恢复测试。在 RC PR 之前请分别记录每一项。此实现未授权任何
合并、发布标签、发布或远程推送。

官方参考资料（实现已对照安装的 1.7.5 源码进行验证）：
- https://better-auth.com/docs/plugins/device-authorization
- https://better-auth.com/docs/plugins/bearer
- https://better-auth.com/docs/concepts/users-accounts

## 注册示例

这些简略形式仅用于说明。请获取新的质询并对其返回的
精确 `proofMessage` 签名；证书、签名和质询占位符
不是可运行的凭据。

初始质询有效载荷 (`operation: "register"`):

```json
{
  "principal": "<initial certificate DER SHA256>",
  "certificatePEM": "<device certificate>",
  "keyGeneration": 0,
  "name": "laptop",
  "operationId": "11111111-1111-4111-8111-111111111111"
}
```

将该有效载荷加上 `challengeId` 和新密钥 `proof` 发送至
`POST /api/relay/devices`。首次轮换时，保留相同的 principal，
设置 `expectedGeneration: 0` 和 `keyGeneration: 1`，提供替换
证书和稳定可靠的新轮换操作 UUID。针对同一质询消息添加
旧密钥的 `previousKeyProof`。在响应不确定的情况下请保留该操作 ID，
并使用 `GET /api/relay/operations/<operationId>` 查询其仅所有者可查的
历史收据。

初始注册必须省略 `expectedGeneration`；轮换时则必须提供。
切勿推断或暗中转换较旧候选版本所使用的世代。
`tests/test_control_integration.py` 中的可执行 Node/Python 夹具涵盖了
注册、准入、已吊销凭据、跨所有者拒绝以及带响应丢失的
轮换。预置的测试夹具会话并不能作为实际 OAuth 的证据。
