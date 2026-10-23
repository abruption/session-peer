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

- [v1.3.0发行说明](releases/v1.3.0.md)介绍已合并的六项功能、支持的组合和发行验证。

- [v1.2.1准备记录](releases/v1.2.1.md)说明用于Orca Claude搜索、技能元数据读取及兼容技能副本的2026-10-19补丁候选；发布仍是独立步骤。

- [v1.2.0发布记录与历史准备](releases/v1.2.0.md)区分2026-10-16发布与2026-10-15开始、2026-10-16更新的准备、已合并的6项PR范围和剩余验收条件。

- [v1.1.2历史准备记录](releases/v1.1.2.md)介绍#298和2026-10-13的准备；此后v1.1.2已发布。不得重用该版本或命令。

- [v1.1.1维护说明](releases/v1.1.1.md)介绍2026-10-12准备的文档与测试维护版本；运行时行为与1.1.0相同。软件包发布需单独确认。

- [实验性Handoff运行时](handoff-runtime.md)说明1.1.0中已发布的有限私有收据功能、支持路径及剩余验收条件。
- [v1兼容性契约](compatibility-v1.md)对stable、versioned、migrated、internal和experimental surface分类。
- [代理传输架构](architecture/agent-transports.md)和[中继开发计划](relay-development-plan.md)介绍实现边界。
- [v1.1.0发布说明](releases/v1.1.0.md)保留已发布1.1.0的证据、变更及部分支持范围。
- [v1.0.4说明](releases/v1.0.4.md)描述2026-10-07的先前维护版本；[v1.0.3说明](releases/v1.0.3.md)保留先前安全版本历史；[验证记录](validation/69-rc.md)保留范围明确的证据及限制。
- relay69原型完成后，其独有回归测试已迁移到产品中继测试套件，原型源代码已删除。废弃的原型代码仍保留在Git历史中。
