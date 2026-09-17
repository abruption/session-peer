# session-peer

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abruption/session-peer/blob/main/LICENSE)

[English](https://github.com/abruption/session-peer/blob/main/README.md) · [한국어](https://github.com/abruption/session-peer/blob/main/README.ko.md) · [日本語](https://github.com/abruption/session-peer/blob/main/README.ja.md) · **简体中文**

**通过一个CLI查找本机或SSH远程主机上的Claude Code与Codex会话，并向其发送消息。**

你可以请另一台机器上的会话审查改动、汇报进度或接手任务。
session-peer使用代理原生的收件箱和队列，由接收方决定如何处理收到的消息。

## 快速开始

需要Python 3.9或更高版本。核心CLI没有第三方Python依赖。

```bash
pipx install session-peer
# 另一种方式: uv tool install session-peer

session-peer list
session-peer list --host worker
session-peer send --to api-worker --message "请汇报进度"
session-peer send --host worker --to 'codex:<full-thread-uuid>' --message "请审查改动"
```

将`worker`替换为SSH主机或别名，将`api-worker`替换为查到的会话名称。
`<full-thread-uuid>`应填写从目标主机查询到的完整线程ID。
目标主机需要Python以及目标代理的收件箱或队列，但通过SSH查询和发送消息时，
无需在目标主机上安装session-peer本身。

**`posted` / `queued`表示提交成功，不代表已读或任务完成。**
已保存的Codex线程可能并未运行。如果需要确认完成，请明确要求对方回复。

## 常用功能

| 任务 | 命令 / 指南 |
|---|---|
| 按代理筛选 | `session-peer list --agent codex` |
| 检查连接和代理配置 | `session-peer doctor --host worker` |
| 仅解析目标，不发送消息 | `session-peer send --to api-worker --dry-run -m "hello"` |
| 获取JSON结果 | `session-peer list --output-format json` |
| 从文件读取消息 | `session-peer send --to api-worker -m - < message.txt` |
| 可选MCP工具 / Codex插件 | [MCP配置](https://github.com/abruption/session-peer/blob/main/docs/mcp.md) |
| 启动已接收队列消息的Codex会话 | [显式wake](https://github.com/abruption/session-peer/blob/main/docs/wake.md) |

## 安装方式

可以使用`pipx`或`uv`，也可以在已激活的虚拟环境中运行`python -m pip install session-peer`。
如需同时安装独立CLI和代理技能：

```bash
git clone https://github.com/abruption/session-peer
cd session-peer
./install.sh
# 远程安装: ./install.sh --host worker
```

Shell安装脚本需要POSIX环境。原生Windows请使用Python包管理器。
可选MCP工具需要Python 3.10或更高版本以及`session-peer[mcp]`。
请参阅[安装详情](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#install)。

## 发送前须知

- 使用正确的目标账户和代理主目录。SSH访问权限和接收方权限仍然适用。
- 普通发送不会启动未运行的会话。显式wake可能启动代理并消耗使用额度。
- 分享诊断结果前，请隐去密钥等敏感信息、对话内容、会话ID和个人路径。

## 文档

- [CLI参考](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md)：命令、JSON、环境变量、更新、限制及验证记录
- [诊断与回复](https://github.com/abruption/session-peer/blob/main/docs/diagnostics.md) · [多个Codex主目录](https://github.com/abruption/session-peer/blob/main/docs/multi-home-list.md)
- [从cc-peer迁移](https://github.com/abruption/session-peer/blob/main/docs/cli-reference.md#moving-from-cc-peer) · [发行版本](https://github.com/abruption/session-peer/releases)
- [适配器开发](https://github.com/abruption/session-peer/blob/main/docs/agent-adapters.md) · [发布流程](https://github.com/abruption/session-peer/blob/main/RELEASING.md)

四种语言的README提供相同的入门内容，详细文档目前为英文。
更新翻译时，请保持命令、环境要求和行为描述与英文版一致。CLI输出语言不受影响。

## 支持与安全报告

普通错误和功能建议请使用[GitHub Issues](https://github.com/abruption/session-peer/issues/new/choose)，
安全漏洞请通过[私密报告](https://github.com/abruption/session-peer/security/advisories/new)提交，
并参阅[安全政策](https://github.com/abruption/session-peer/blob/main/SECURITY.md)。
非公开咨询或无法使用私密报告时，请发送邮件至
[support@abruption.dev](mailto:support@abruption.dev)，标题中注明`[session-peer]`。
支持服务不保证响应时限。邮件由维护者手动审核，不会自动转为公开Issue。目前接受英文或韩文报告。

[MIT许可证](https://github.com/abruption/session-peer/blob/main/LICENSE)。
