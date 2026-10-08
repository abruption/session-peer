# 安全政策

## 报告漏洞

如怀疑存在漏洞，请通过 [GitHub 私密漏洞报告功能](https://github.com/abruption/session-peer/security/advisories/new)提交报告。切勿在公开议题、拉取请求或评论中披露漏洞。

如果您无法使用该表单，请向 [support@abruption.dev](mailto:support@abruption.dev?subject=%5Bsession-peer%5D%20Security) 发送邮件，主题注明 `[session-peer] Security`。电子邮件是另一种私密联系渠道，但并非端到端加密的提交方式。请先提供已隐去敏感信息的描述；切勿发送仍在使用的机密信息或生产数据。

请提供受影响的版本或提交、安装方法、各端点上的操作系统、Python 和代理版本；受影响的命令或组件；攻击者所需的访问权限；预期行为与实际观察到的行为；影响；以及使用虚构账户、路径、会话和消息编写的最小复现步骤。

请从诊断信息中移除令牌、密码、私钥、配对机密、对话文本、会话/线程标识符、个人路径、主机名和地址。在需要表达相互关系时，请使用一致的占位符。切勿上传完整的智能体主目录、SQLite 数据库、JSONL 会话记录、浏览器配置文件或 `.env` 文件。请通过相关服务提供商撤销或轮换已泄露的机密；仅删除公开评论并不能使其失效。

## 审查与受支持的版本

报告由维护者人工尽力审核；不保证响应或修复期限。欢迎报告任何版本的问题。维护工作主要面向最新的 session-peer 版本；旧版本及旧版 cc-peer 软件包不保证获得反向移植（backport）修复。

维护者将与报告者协调调查和披露事宜。私密报告和电子邮件不会自动转为公开议题。欢迎使用英文和韩文提交报告。

对于普通错误和功能请求，请使用[公开议题模板](https://github.com/abruption/session-peer/issues/new/choose)。

## 依赖漏洞监控

Dependabot 漏洞警报已启用，与版本更新拉取请求相互独立。Dependabot 自动安全更新拉取请求仍处于禁用状态，也没有 Dependabot 版本更新配置。维护者会审查警报并手动更新依赖和构建工具的固定版本。

独立的[定期依赖审计](.github/workflows/dependency-audit.yml)每周一 06:23 UTC 运行，也可通过 `workflow_dispatch` 手动启动。它使用 `pip-audit` 审计隔离环境中的 Python `relay,mcp` 运行时依赖，并使用 `npm audit --omit=dev` 审计 `control/` 的 Node 运行时依赖。发现漏洞或审计错误会使该次审计运行失败，并显示在作业摘要以及保留 30 天的可下载 JSON/日志工件中。该工作流不在拉取请求中运行，也不参与 CI 的 `release-gate`；现有 CI 和发布审计仍然适用。
