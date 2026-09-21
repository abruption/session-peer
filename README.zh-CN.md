# session-peer

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![PyPI每周下载量](https://api.pepy.tech/badge/session-peer/week)](https://pepy.tech/projects/session-peer)
[![PyPI每月下载量](https://api.pepy.tech/badge/session-peer/month)](https://pepy.tech/projects/session-peer)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abruption/session-peer/blob/main/LICENSE)

[English](https://github.com/abruption/session-peer/blob/main/README.md) · [한국어](https://github.com/abruption/session-peer/blob/main/README.ko.md) · [日本語](https://github.com/abruption/session-peer/blob/main/README.ja.md) · **简体中文**

**通过一个CLI查找本机或SSH远程主机上的Claude Code与Codex会话，并向其发送消息。**

你可以请另一台机器上的会话审查改动、汇报进度或接手任务。
例如，请SSH主机`worker`上的`api-worker`会话审查改动。
session-peer使用代理原生的收件箱和队列，由接收方决定如何处理收到的消息。

## 快速开始

需要Python 3.9或更高版本。核心CLI没有第三方Python依赖。

```bash
pipx install session-peer
# 另一种方式: uv tool install session-peer

session-peer list
session-peer list --host worker
```

## 发送第一条消息

以下名称和UUID均为虚构示例。请先查询目标，再替换为实际会话。

```bash
session-peer send --to api-worker --message "请汇报进度"
session-peer send --host worker --to 'codex:00000000-0000-4000-8000-000000000001' --message "请审查改动"
```

将`worker`替换为SSH主机或别名，将`api-worker`替换为查到的会话名称。
请将示例UUID替换为从目标主机查询到的完整线程ID。
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
| 可选MCP工具 / Codex插件 | [MCP配置](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/mcp.md) |
| 启动已接收队列消息的Codex会话 | [显式wake](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/wake.md) |

## 安装方式

运行时可使用`pipx`或`uv`安装，也可以在已激活的虚拟环境中运行
`python -m pip install session-peer`。代理技能请从[专用仓库](https://github.com/abruption/session-peer-skill)单独安装：

```bash
npx -y skills@latest add abruption/session-peer-skill \
  --skill session-peer --global \
  --agent claude-code --agent codex --agent antigravity \
  --copy --yes
```

在隔离网络或SSH部署中，POSIX的`./install.sh [--host worker]`仍会附带迁移期兼容技能副本。
原生Windows的运行时请使用Python包管理器。可选MCP工具需要Python 3.10或更高版本以及
`session-peer[mcp]`。请参阅[安装详情](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/cli-reference.md#install)。

## 让AI助手代为处理

如果你更愿意描述目标，而不是逐篇阅读所有文档，请把
[AI辅助设置与运维指南](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/ai-assistant-guide.md)交给编程代理。
其中提供可复用的请求、授权和密钥处理边界、验证步骤及完成报告格式。
账户更改、公开访问、付款、重启、合并、发布版本和公开发布仍由用户控制。

## 可选的1.0 Alpha功能

显式选择的`1.0.0a1`预发布版新增了认证公共中继，并保留v0.9的实验性[Antigravity](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/antigravity.md)桥接。未筛选的`list`也会显示正在运行的已注册桥接。
[设备配对与加密中继](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/paired-devices.md)需要Unix、Python 3.11以上及`[relay]`扩展。设备身份固定，目标需在接收端显式授权。盲转发WSS中继无法解密应用消息；托管服务的可用性与软件包分开运营。
请使用`pipx install 'session-peer[relay]==1.0.0a1'`显式安装Alpha版；普通升级不会选择预发布版本。请先查看[session-peer项目页面](https://abruption.dev/projects/session-peer/)及上方的设备配对文档。Alpha发布不代表长期稳定性，普通本地与SSH命令仍不需要第三方依赖。

## 发送前须知

- 使用正确的目标账户和代理主目录。自定义Codex主目录请通过`--codex-home`指定查询结果中的`codexHome`路径。SSH访问权限和接收方权限仍然适用。
- 普通发送不会启动未运行的会话。显式wake可能启动代理并消耗使用额度；在MCP中需要单独的wake权限。
- 分享诊断结果前，请隐去密钥等敏感信息、对话内容、会话ID和个人路径。

## 文档

- [项目指南网站](https://abruption.dev/projects/session-peer/)：核心概览、快速开始和文档入口
- [仓库文档导航](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/README.md)：用户、集成、运维、开发和历史资料
- [CLI参考](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/cli-reference.md)：命令、JSON、环境变量、更新、限制及验证记录
- [诊断与回复](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/diagnostics.md) · [多个Codex主目录](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/multi-home-list.md)
- [从cc-peer迁移](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/cli-reference.md#moving-from-cc-peer) · [发行版本](https://github.com/abruption/session-peer/releases)
- [适配器开发](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/agent-adapters.md) · [发布流程](https://github.com/abruption/session-peer/blob/main/RELEASING.zh-CN.md)

README和详细文档提供英文、韩文、日文和简体中文版本。英文文档为正本，
CI会检查翻译文件、命令、要求和行为是否保持一致。这些翻译不会改变CLI的输出语言。

## 支持与安全报告

普通错误和功能建议请使用[GitHub Issues](https://github.com/abruption/session-peer/issues/new/choose)，
安全漏洞请通过[私密报告](https://github.com/abruption/session-peer/security/advisories/new)提交，
并参阅[安全政策](https://github.com/abruption/session-peer/blob/main/SECURITY.zh-CN.md)。
非公开咨询或无法使用私密报告时，请发送邮件至
[support@abruption.dev](mailto:support@abruption.dev)，标题中注明`[session-peer]`。
支持服务不保证响应时限。邮件由维护者手动审核，不会自动转为公开Issue。目前接受英文或韩文报告。

[MIT许可证](https://github.com/abruption/session-peer/blob/main/LICENSE)。
