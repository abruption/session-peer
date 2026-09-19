# Cloudflare 背后的原生客户端 (RC 验证)

中继的浏览器 UI 和原生 API 具有不同的客户端。成功的浏览器 OAuth 回调或公共健康检查 GET 并不意味着设备代码 POST 或经过身份验证的 WebSocket 连接可以正常工作。

在 KR 试点中，原生设备代码请求返回了 HTTP 403 / Cloudflare 1010 (`browser_signature_banned`)。相应的 Cloudflare 安全事件识别出 `source=bic`、`ruleId=bic`、`action=block`。这确定了该请求的原因是 Browser Integrity Check；并未确定 Bot Fight Mode 是其原因。

## 原生 POST 例外基线

所有者首先批准了设备代码/令牌路径，然后明确批准了三个注册/准入 POST 路径。这仍作为单个 Configuration Rule 保留在 `http_config_settings` 中，带有 `action=set_config` 和 `action_parameters={"bic":false}`。其表达式为：

```text
(http.host eq "relay.abruption.dev" and ssl and http.request.method eq "POST" and http.request.uri.path in {"/api/auth/device/code" "/api/auth/device/token" "/api/relay/challenge" "/api/relay/devices" "/api/relay/admission"} and http.request.uri.query eq "")
```

这仅针对五个不带查询参数的 HTTPS POST 端点禁用 BIC。全区域 BIC 设置、托管 WAF、Bot Fight Mode、DDoS 防护、安全级别、现有速率规则以及源站入站限制保持不变。现有的 Cloudflare 速率规则保护的是另一项服务；绝不能将其描述为中继特有的速率保护。Control 自身的请求限制、固定客户端 ID、代码过期/轮询限制、显式公开注册开关或账户允许名单，以及显式浏览器批准继续适用。匹配此规则不授予任何身份验证。

该配置是在明确批准后应用的。v2 规则的 Cloudflare Trace 匹配了所有五个预期路径，并排除了十种其他情况，包括其他方法/主机、查询参数、末尾斜杠、明文 HTTP、浏览器批准/撤销、操作查找以及中继会话/WebSocket 端点。第一阶段还通过了实际的原生代码发放、浏览器批准和令牌轮询。Trace 只是配置验证，而不是下游原生成功交付的凭证。

## 变更与回滚

在将此类规则应用于其他部署之前，请先阅读现有配置阶段并保留其他规则。不要用上述示例替换现有规则集，也不要针对整个区域禁用 BIC。记录新的规则 ID/版本，重新读取存储的表达式，并检查预期情况与排除情况。

仅回滚新增的规则（通过其 ID 禁用/删除），保留并发的配置变更。作为回滚边缘规则的一部分，请勿恢复应用程序数据库、密钥、收据或重放状态。

仅限 POST 的基线不涵盖操作查找或中继会话/WebSocket GET 路由。随后获批的操作查找覆盖范围在下文说明；中继会话/WebSocket GET 仍然没有 BIC 例外。请勿伪装浏览器用户代理、将浏览器 Cookie 传输给 CLI，或针对明确不可重试的拦截持续重试。避免在日志和报告中出现设备代码、令牌和机密。

## 批准的操作收据查找

所有者随后授权解决原生收据查找的 403 问题。新的原生查找返回了错误 1010；由于 GraphQL 诊断 API 耗尽了配额，无法读取确切的历史安全事件。仅针对 BIC 的变更首先恢复了单个接收方收据 URL，而无需重复注册。该小范围的成功实验并未解决其他 ID。

同一规则的版本 4 现在额外匹配中继主机上**不带查询参数的 HTTPS GET**，且路径为 `/api/relay/operations/` 后跟规范的小写 UUIDv4。其 58 字节路径、十六进制字符、连字符位置、版本和变体使用该部署支持的 `starts_with`、`len`、`substring` 和逐字符比较进行检查。未曾使用付费的正则表达式功能或计划升级。不支持的替代表达式在不更改活动配置的情况下被拒绝；它不是操作方案。

Trace 通过了 21 种情况，包括现有的操作 ID 和格式错误的 ID、大写、错误的版本/变体、末尾斜杠、查询参数、方法/主机/协议以及不相关的 API 排除项。随后，两个原本注册的设备均以 CLI exit 0 对账了它们已提交的收据，无需重新注册。另一位经过身份验证的所有者和不存在的规范操作 ID 从应用程序收到了 404。此例外仅绕过 BIC：它不授予所有权，也不绕过 API 身份验证。

在复用此配置之前，请验证目标区域/阶段中的确切表达式，并保留其其他规则。试点的已脱敏表达式、API 结果和回滚 diff 与 `DYNAMIC-RECEIPT-BIC-RESULT.md` 一起保留在 [RC validation](validation/69-rc.md) 所引用的操作凭据目录中。

参考资料：[Cloudflare error 1010](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/) 和 [Browser Integrity Check](https://developers.cloudflare.com/waf/tools/browser-integrity-check/)。
