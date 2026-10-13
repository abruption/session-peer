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

## 2026-10-13：CLI 1.3.3 验收测试 (#304)

此记录与上方 2026-09-17 开发分支的验证分别记录。
基准为已发布的 session-peer 1.1.1，提交 b48144bdf2ad1569031562136f5a60e33780020e。
两台设备的 native CLI 均为 1.3.3，专用 TUI 使用 Gemini 3.8 Flash (Low)。
适配器仍处于实验阶段。本次测试不代表发布版本，也不保证普遍的版本兼容性、
Windows 支持、sidecar 自动启动或服务可用性。

### 已观察到的证据

- 在 macOS 27.0.1 arm64 / Python 3.15.0 和 Ubuntu 24.04.5 arm64 / Python 3.12.3 上，
  Antigravity 适配器测试分别通过 23 项。owner 与 native 调用的模拟，以及真实 Unix socket
  和子进程 fixture，不等同于真实模型集成测试。
- 已安装 CLI 的参数解析测试在每个平台通过 7 项，覆盖前导短横线、分隔符、多行韩语及
  接收目标和标题保留。采用空 HOME、最小环境和有界 loopback 模拟服务，没有使用凭据或成功的实际投递。
- 专用接收 TUI 通过正常终端工具注册了有界 bridge。macOS 本地、Linux 本地和
  macOS→Linux source-streamed SSH 提交均返回 native exit zero，并在各 TUI 中观察到不同的精确回复标记。
- 在 TUI 生成有界的合成回复、显示工作中状态时还进行了提交，随后观察到对应回复。
  这是特定日期的 UI 观察，不保证调度、延迟或所有 busy 状态。
- macOS dry-run 在未调用 native 提交的情况下结束。再次使用原 ID 和正文返回缓存的重复结果；
  同一 ID 的不同正文被拒绝。SSH 路由中指定不同 generation 的请求也在 native 调用前被拒绝。
- 显式停止两台设备的 bridge 后，注册从发现列表消失。两台仍运行的 TUI 重新注册后，
  generation 发生变化，固定到原 generation 的请求在本地和 SSH 路由中被拒绝。fixture 还检查 SIGTERM、
  SIGINT、SIGHUP 清理，重启后 generation 变化，以及相同 lock inode 的保留。
- JSON 消费确认始终为 false。观察到 TUI 回复只是该测试消息的独立证据，不是新的自动 ACK 或等待功能。

### 失败记录与正式支持的剩余条件

macOS 首次 shell-background 启动因无法验证必需的祖先进程而拒绝注册。
改为通过终端工具运行 foreground 长期命令后注册成功。不能假定分离 shell 后 bridge 仍保留 TUI 祖先关系。
首次 Linux fixture 传输遗漏 MCP 模块，导致一次 import 失败。补传该受版本控制的源文件后，
全部 23 项通过。这是测试准备错误，不是产品修复的证据。

新增测试覆盖启动失败结果的缓存和禁止重试，以及 UTF-8 精确的 32 KiB 边界。
它们不证明跨重启去重，也不证明 unknown 结果没有产生效果；自动重发仍被禁止。
长时间持续运行、真实 TUI 重启及 owner 退出、强制崩溃验收、实际通信断开结果、
双向 CLI 回复路由仍是未执行的正式支持条件。
本次也未重新验证 Claude、Codex、Antigravity 的完整互操作性或 paired Relay 投递。
官方 sidecar 文档描述了托管启动，但其与当前依赖祖先进程的 bridge 的兼容性需要单独研究。
没有修改全局 sidecar 设置、复制认证信息或部署到生产环境。
