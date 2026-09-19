# #85 Antigravity 适配器开发验证

2026-09-17；本地分支 `feat/85-antigravity-adapter`，隔离工作树 `/tmp/session-peer-85`，基于 #47 `993d04d`。无中继依赖、发布、远程推送或 PR。版本保持 0.8.0 作为开发元数据；此功能不在已发布的 0.8.0 发行版中。Issue：https://github.com/abruption/session-peer/issues/85

## 已实现

独立源码中可选的已注册会话适配器、本地/SSH list 和 send、doctor 功能、确切的 UUID/主目录/进程身份和代际检查、私有同 UID 帧套接字、受限请求/生命周期/原生子进程、代际内请求去重/冲突处理、信号清理和陈旧重启。发送方检测需要唯一的已注册祖先。当添加第三个内置适配器时，MCP 列出保留显式 agent 允许列表。

## 证据

- macOS Python 3.14：安装了可选 MCP SDK（包括真实的 MCP stdio 测试）时通过 332 个测试。未安装 SDK 时：332 个测试，2 个可选跳过。
- KR Ubuntu Python 3.12：17 个适配器测试通过；真实 Unix 套接字、虚构原生可执行文件、SIGTERM 清理和陈旧重启测试固件，无模型调用。
- 构建了 wheel/sdist 并在隔离的虚拟环境中独立安装；对 CLI bridge help 和仅注册列表进行了冒烟测试。无全局安装。
- 真实的 KR agy 1.2.4 TUI：用户通过其工具运行器启动了有边界的 bridge。源码流式传输的 SSH `list` 找到了正确的 ubuntu 主目录，尽管工作区位于另一个用户的目录下。两个不同的集成标记各自生成了一条 SYSTEM 接收记录和一条确切的 MODEL ACK。重复请求被抑制；具有相同 ID 和旧代际的更改主体被拒绝。Dry-run 未调用原生投递。结构化 `consumptionConfirmed` 保持为 false，而独立的转录观察证实了这些测试 ACK。
- 显式停止 bridge 移除了套接字和注册；随后的 SSH list 未返回任何已注册会话。用户 TUI 在原始 cwd 中保持存活。远程测试源码/测试已被移除。私有单 UID 运行时目录中特意保留了一个空锁文件，以避免分块锁竞争；未保留任何活动的 bridge/套接字/注册。

详细的净化后证据位于本地 `/tmp/session-peer-85-evidence/`：`list.json`、`send.json`、`observation.json`、`cleanup.json`、`linux-tests.log`、`full-tests.log`。第一次实时测试的转录标记与第二次测试标记一起保留在 `cleanup.json` 中；`send.json` 包含第二次运行。未收集任何原始环境、令牌、凭据或无关转录。

## 限制 / 后续步骤

这是一个实验性的显式注册工作流。没有 CLI sidecar 自动启动、无头写入器替换、无人值守注册、持久发件箱、自动 ACK/wait/wake、跨 UID 访问或恰好一次声称。原生发送方是 TUI 的 agentapi 身份；描述性的 From 标头并不是加密发送方证明。新实现的实时原生测试是 Linux；macOS 具有协议/生命周期测试固件加上早期的原生 PoC，而不是该分支的实时原生测试。不支持 Windows bridge；未在本地运行 Windows CI 和 Python 3.9 执行。SIGKILL 无法同步清理；重启仅在获取排他锁后才移除陈旧条目。PID 轮询无法消除验证与 agentapi 调用之间的所有进程退出竞争。

早期的 KR PoC 演示了忙碌投递、SSH 断开连接、bridge 和 TUI 重启，共涉及 7 条消息。这些结果为本次实现提供了参考，但不算作该分支的实时执行。产品级的重新连接持久性、长时间运行操作以及配对/中继集成仍属于单独的 v0.9/RC工作。
