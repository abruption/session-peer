# 公开 WSS 试点 — 2026-09-17

经用户批准的临时 KR 试点，已完成并移除。这是一次有界的集成检查，并非生产部署或持续运行的结果。

## 路径与隔离

Mac 客户端 → 公开 Cloudflare HTTPS/WSS → KR Caddy 精确测试主机名 → 127.0.0.1:3769 盲中继 → 已认证接收端 → 现有 Antigravity 桥接。应用 TLS 1.3 通道在 WebSocket 内部固定设备证书；公开 TLS 终结不会接收应用明文。原生访问仅限于一个显式允许的对端和现有的 `agy-kr` 会话别名。

先前的 SSH 转发进程在测试前已停止。公开目的地路由使用 en1 / 本地互联网网关，而非 Tailscale 接口。SSH 单独用于管理和只读脚本记录观察。这并未确立关闭 VPN 的手机测试或原始 TCP NAT 穿透。

中继以 DynamicUser、ProtectHome、ProtectSystem=strict、NoNewPrivileges、256 MiB 内存、50% CPU、64 个任务、10 个连接的应用限制以及 30 分钟的运行时上限运行。在 Caddy 变更之前已启动独立的 30 分钟 systemd 清理定时器。未进行 DNS 或防火墙更改。

## 观察结果

- 公开未认证准入：HTTP 401。
- 已认证配对 `list`：返回现有 Antigravity 会话。
- 公开发送标记：`SP090_PUBLIC_e037d3d2d993`。
- 请求 ID：`e037d3d2-d993-4fae-8c03-dbc66619967c`。
- 原生结果：已提交，`consumptionConfirmed=false`。
- 独立观察到的 MODEL 脚本记录：`ACK_SP090_PUBLIC_e037d3d2d993`。
- 重复相同的请求 ID/正文：持久化回执，带有 `duplicate=true` 和相同的原生请求 ID。未请求第二次原生提交。

这一独立观察到的 ACK 增强了针对此特定消息的证据。它并没有将通用发送契约更改为投递确认，也没有确立崩溃下的精确一次投递。

## 清理

移除了确切的临时 Caddy 块，同时保留其他配置。验证/重载成功。Caddy SHA256 恢复到测试前的值 `60ae35627b82d65724ceac89421e1f92ba475b675fd146b4036129f352197ebb`。公开测试主机名恢复其原始 HTTP 301 响应。停止了中继服务并关闭了环回端口 3769。清理定时器仅在成功回滚后解除。停止了临时接收端和原生桥接；用户的 Antigravity TUI 保持运行。测试凭据和临时服务安装随后被移除。

## 剩余发布关卡

主目标集成/发布 PR 和 CI、最终编辑后的软件包重新验证、发布合并/标签/PyPI 验证以及持续的真实设备运行仍然有待完成。此处的实时代理覆盖范围为 Antigravity；Claude 套接字夹具和其他单元测试不是实时 Claude/Codex 模型证据。
