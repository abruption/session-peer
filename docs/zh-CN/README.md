# session-peer 文档

英文版是规范源。韩文、日文和简体中文版保持相同的导航及规范行为。请从最符合目标的
最短指南开始；协议和验证记录是审查材料，不是并行的安装路径。

## 用户

- [CLI参考](cli-reference.md)介绍本地及SSH发现、发送、JSON、更新和限制。
- [诊断与回复](diagnostics.md)介绍准确的提交状态和安全的故障排查。
- [多个Codex主目录](multi-home-list.md)、[显式wake](wake.md)和[Antigravity](antigravity.md)介绍可选的代理工作流。

## AI辅助设置与集成

- [AI助手指南](ai-assistant-guide.md)是让代理执行设置或验证时使用的受限交接文档。
- [MCP](mcp.md)和[代理适配器](agent-adapters.md)介绍可选集成及策略边界。

## 配对设备与运维人员

- [配对设备](paired-devices.md)是使用直连或托管端到端加密中继的用户路径。
- [中继认证](relay-auth.md)、[生命周期与恢复](relay-lifecycle.md)、[看门狗](relay-watchdog.md)和[边缘策略](relay-edge-policy.md)是运维参考。
- [部署资料](../../deploy/README.md)区分可复用示例和Abruption KR运维参考。

## 开发与历史

- [v1兼容性契约](compatibility-v1.md)对stable、versioned、migrated、internal和experimental surface分类。
- [代理传输架构](architecture/agent-transports.md)和[中继开发计划](relay-development-plan.md)介绍实现边界。
- [发布说明](releases/v1.0.0-alpha.1.md)描述已发布行为；[验证记录](validation/69-rc.md)保留范围明确的证据及限制。
- relay69原型完成后，其独有回归测试已迁移到产品中继测试套件，原型源代码已删除。废弃的原型代码仍保留在Git历史中。
