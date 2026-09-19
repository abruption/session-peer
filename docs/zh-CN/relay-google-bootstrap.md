# 首次 Google 账号发现（开发）

此项供操作员自选的操作流程用于在将 Google 账号 ID 添加到中继允许列表之前获取经过验证的账号 ID。它不会启用公开注册、授予会话，也不会通过匹配电子邮件地址来关联 Google 和 GitHub 账号。实际提供商验证仍为 RC 门禁；模拟提供商测试属于单独的凭证。

请使用专用的 Google Web OAuth 客户端及其精确配置的回调地址：`https://relay.example.com/api/auth/callback/google`。在准备私有中继期间，请将应用程序保持在 Testing 状态，并限制其 Google 测试用户。通过现有的受保护文件/systemd 凭据路径提供其密钥。

在首次 Google 登录之前，请设置以下两个**临时**控制配置项：

```text
SESSION_PEER_GOOGLE_DISCOVERY_EMAIL=the-explicitly-approved-account@example.com
SESSION_PEER_GOOGLE_DISCOVERY_UNTIL=REPLACE_WITH_UNIX_SECONDS_WITHIN_30_MINUTES
```

这两个设置、已启用的 Google 提供商以及最多 30 分钟以内的未来截止时间都是必需的。此模式在启用期间会阻止所有新的 Google 登录，包括截止时间之后；移除这两个设置即可恢复正常的 Google 身份验证。现有的账号允许列表不会被放宽。

1. 使用这些设置及其正常的受保护状态启动经过审查的控制候选版本。在已批准用户的浏览器中打开其 Google 登录流程。
2. Better Auth 执行其正常的授权码、state 和 PKCE 交换。包装器通过 Better Auth 的固定验证器验证返回的 Google ID 令牌：签名、颁发者、客户端受众、到期时间以及最大令牌生命周期。如果库提供了预期的 nonce，该 nonce 也会被检查。如果提供商流程未提供 nonce，它不会声称已颁发 nonce。
3. 只有包含完全符合预期的电子邮件且满足 `email_verified=true` 的真实 Google 回调才能创建 `<SESSION_PEER_CONTROL_DATA>/google-account-discovery.json`。该私有文件包含经过验证的主体、预期电子邮件、验证时间、颁发者和公共客户端 ID。它不包含授权码或提供商/会话令牌。
4. 回调在账号关联或配置之前有意拒绝登录。在发现时间窗口内，以相同的服务身份并使用相同的受保护配置运行 `node dist/server/confirm-google-discovery.js`，通过受信任的操作员路径确认发现记录。这会检查预期的账号/客户端和私有文件，然后在返回 `persistenceConfirmed: true` 之前同步文件和目录。将其确切的 `accountId` 作为 `google` 条目添加到 `SESSION_PEER_ALLOWED_ACCOUNTS` 中，并移除这两个发现设置。保留其他已批准的账号条目。
5. 通过经过审查的服务流程重新启动，并执行单独的正常 Google 登录和 CLI 设备批准测试。发现回调本身并不是一次成功的登录。

发现文件在私下准备和同步，然后使用不可覆盖的硬链接发布一次，权限为私有 0700 目录中的 mode 0600。重试、不同的主体、过期的窗口或写入失败都无法替换它或授予访问权限。仅凭文件的存在并不能证明持久化：发布后目录同步可能已失败。显式确认步骤会在不更改已验证记录或授予登录权限的情况下重试同步。如果失败，请保持允许列表不变，并首先排查存储问题。如果操作员必须重复发现流程，请先检查并明确归档先前的结果；不要在重启期间自动将其删除。

`accountLinking=false` 仍然有效。电子邮件已属于通过 GitHub 创建的用户的 Google 账号可能会被拒绝，并提示 `account-not-linked`。在该检查之前，发现功能仍然有效。它不授权自动关联；除非在单独的变更中添加了显式的账号关联策略，否则请使用不同的已批准所有者或隔离的测试状态来验证各个独立的提供商。
