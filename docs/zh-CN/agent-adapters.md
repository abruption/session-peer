# 开发内部 agent 适配器

这是一份源码扩展指南，而非外部插件安装接口。有关契约版本控制、兼容性、结果语义和信任边界，请参见[架构决策](architecture/agent-transports.md)。

适配器子类化 `AgentAdapter`，声明一个唯一的小写 `name`，并实现 `list(context)` 和 `submit(context, text)`。在 `main()` 执行前使用 `AGENTS.register(...)` 显式注册它。如果必须通过 SSH 工作，请将其实现保留在独立源码中。对于基本的新适配器，无需更改 CLI 路由器或 SSH 派发器。

最小确定性示例（仅供测试使用）：

```python
class ExampleAdapter(AgentAdapter):
    name = "example"
    capabilities = AgentCapabilities()  # list/send; no wake/wait/ack

    def list(self, context):
        return {"sessions": [{"agent": self.name, "id": "one", "status": "idle"}],
                "discovery": {"status": "ok"}}

    def submit(self, context, text):
        target = self.identity(context.options.to, context)
        return {"ok": True, "target": {"id": target.identifier},
                "status": "validated" if context.options.dry_run else "submitted",
                "submitted": not context.options.dry_run,
                "consumptionConfirmed": False}

AGENTS.register(ExampleAdapter())
```

该示例没有真正的收件箱；切勿将其作为实际投递适配器随附发布。仅用于测试的 `tests/fixtures/agent_adapter.py` 提供了契约测试中使用的可执行示例，并已从发布的发行版中排除。

- `list` 返回 `sessions` 以及一个 `discovery` 对象，其 `status` 等于 `ok`、`error`（带有 `error` 文本）或 `not_installed`。每一行都标识其 agent。保留原生身份字段。针对不同的行布局实现 `display_row`/`render`。Codex 额外保留现有的顶级主目录元数据。
- `submit` 接收已经过验证、包装好的消息恰好一次。在原生副作用之前遵循 dry-run。返回原生提交事实；不要从套接字/队列接受推断确认。已知提交之后的原生失败必须保留其 ID 和部分结果。
- `identity` 和 `target` 转换原生身份与 CLI/Reply-To 目标。默认值为 `name:identifier`；Claude 保留无前缀的名称/PID。
- `diagnose`、`diagnostic_text`、`listing_notes`、`submission_text`、`remote_submission` 和 `remote_options` 在不改变通用路由的情况下，专门处理证据以及现有输出的兼容性。参数选项仍必须在解析器中显式声明；agent 无法注入 shell 代码。
- 功能布尔值仅报告实现支持情况。为 false 的功能会在提交前失败。宣告 wake 不会跳过原生运行时检查或 MCP 授权；wait/ack 在此版本中没有 CLI 实现。

MCP 仅允许显式授权的目标和 agent。仅靠源码注册绝不会授予远程/发送权限。可选依赖项必须保持在核心导入路径之外；添加后端依赖项需要单独的打包决策。未实现公共外部加载和安装。

在未安装和已安装可选 MCP SDK 的情况下分别运行现有测试套件和共享契约测试。同时独立构建/安装 wheel 和 sdist，并运行隔离的独立安装器测试。使用测试固件传输来进行新的契约覆盖，而不是使用生产会话。
