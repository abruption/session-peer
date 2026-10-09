<div align="center">

# session-peer

[![PyPI](https://img.shields.io/pypi/v/session-peer)](https://pypi.org/project/session-peer/)
[![PyPI每周下载量](https://api.pepy.tech/badge/session-peer/week)](https://pepy.tech/projects/session-peer)
[![PyPI每月下载量](https://api.pepy.tech/badge/session-peer/month)](https://pepy.tech/projects/session-peer)
[![CI](https://github.com/abruption/session-peer/actions/workflows/ci.yml/badge.svg)](https://github.com/abruption/session-peer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/abruption/session-peer/blob/main/LICENSE)

[English](https://github.com/abruption/session-peer/blob/main/README.md) · [한국어](https://github.com/abruption/session-peer/blob/main/README.ko.md) · [日本語](https://github.com/abruption/session-peer/blob/main/README.ja.md) · **简体中文**

**使用一个命令行工具（CLI），即可查找本机或通过SSH连接的远程主机上的Claude Code与Codex会话，并向其发送消息。**

</div>

可以请另一个会话审查改动、汇报进度或接手任务。
session-peer使用各智能体自身的收件箱和队列；接收方智能体自行决定如何响应。

<a id="see-it-in-action"></a>

## 演示

![Codex向Claude Code发送请求并收到明确ACK的演示](https://raw.githubusercontent.com/abruption/session-peer/main/docs/assets/session-peer-live-codex-claude.gif)

这是真实的本地请求与回复，使用session-peer 1.0.2完成：Codex向Claude Code发送请求，
并收到`ACK DEMO-READY`。这段约22秒的动画对CLI输出和消息摘录进行了匿名化与重新绘制，
并非屏幕录像；发送成功本身并不代表收到ACK。

## 快速开始

<a id="installation-options"></a>

### 安装

需要Python 3.9或更高版本。核心本地与SSH CLI没有第三方Python依赖。
当前稳定版：**1.0.4**。

请参阅2026-10-07维护版本的[发布说明](docs/zh-CN/releases/v1.0.4.md)。软件包发布与生产环境部署是两项独立操作。

发布候选 **1.1.0** 正在准备，尚未发布。计划变更与剩余验收条件请参阅[候选说明](docs/zh-CN/releases/v1.1.0.md)。

```bash
pipx install session-peer
session-peer --version
session-peer list
```

如果使用uv，可运行 `uv tool install session-peer`。原生Windows、
虚拟环境pip、独立脚本与SSH安装方式请参阅
[安装指南](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/cli-reference.md#install)。

通过SSH查找会话时，请将示例主机 `worker` 替换为实际主机或别名。
然后将虚构的会话名称和完整UUID替换为查询结果中的目标：

```bash
session-peer list --host worker
session-peer send --to api-worker --message "请汇报进度"
session-peer send --host worker --to 'codex:00000000-0000-4000-8000-000000000001' --message "请审查改动"
```

SSH目标需要Python以及目标智能体自身的收件箱或队列，
但无需安装session-peer CLI。如使用自定义Codex主目录，请通过 `--codex-home`
指定查询结果中的 `codexHome`，并可用 `--dry-run` 在不发送消息的情况下验证。
请使用拥有该会话的目标账户（`--host USER@HOST`）。
SSH访问权限和接收方权限仍然适用。

**`posted` / `queued` 仅表示消息已提交到接收箱或队列，不代表消息已被消费、已收到ACK或任务已完成。**
需要时请明确要求对方回复。普通发送默认拒绝未运行的Codex目标，
也不会启动它们。切勿自动重试结果不确定的发送。

可选的 [智能体技能](https://github.com/abruption/session-peer-skill) 与运行时分开安装，
其Skills CLI命令请参阅安装指南。

### 更新

请使用安装运行时的同一管理工具更新：

```bash
pipx upgrade session-peer
# 或者: uv tool upgrade session-peer
# 或者，在其虚拟环境中: python -m pip install --upgrade session-peer
```

在本地安装中，`session-peer update` 会替换独立脚本的运行时文件；
通过软件包管理器安装的版本只会显示升级指引。此命令不会更新智能体技能；
请使用原安装工具（Skills CLI，或随附副本的 `install.sh`）。
请参阅[更新详情与远程限制](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/cli-reference.md#updating)。

<a id="documentation"></a>

## 文档

- [文档导航](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/README.md)：用户、集成、运维和开发指南
- [CLI参考](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/cli-reference.md)：选项、JSON、安装变体与迁移
- [诊断与回复](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/diagnostics.md) · [多个Codex主目录](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/multi-home-list.md)
- [AI辅助安装](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/ai-assistant-guide.md) · [项目网站](https://abruption.dev/projects/session-peer/) · [发行说明](https://github.com/abruption/session-peer/releases)
- [发布流程](https://github.com/abruption/session-peer/blob/main/RELEASING.zh-CN.md)

[设备配对与加密Relay](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/paired-devices.md)需要
Unix、Python 3.11以上和 `session-peer[relay]`，并要求固定设备身份及显式接收策略。
软件包发布不保证托管服务可用性。
盲转发Relay无法解密应用消息的内容。
[MCP与Codex插件](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/mcp.md)需要Python 3.10以上及
`session-peer[mcp]`；MCP wake需要同时具备 `send` 和 `wake` 两项能力。
[Wake](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/wake.md)仅在显式请求时运行，
可能启动一轮任务、消耗使用额度或修改项目文件。
[Antigravity桥接](https://github.com/abruption/session-peer/blob/main/docs/zh-CN/antigravity.md)仍处于实验阶段。

英文为正本，韩文、日文和简体中文指南保持同步。
翻译不会改变CLI的输出语言。

## 许可证

[MIT](https://github.com/abruption/session-peer/blob/main/LICENSE)。

## 支持与安全

错误与功能建议请使用 [GitHub Issues](https://github.com/abruption/session-peer/issues/new/choose)。
安全漏洞请通过 [私密报告](https://github.com/abruption/session-peer/security/advisories/new) 提交，不要发布到公开议题，
并遵循[安全政策](https://github.com/abruption/session-peer/blob/main/SECURITY.zh-CN.md)。
分享诊断结果前，请隐去敏感信息、对话、会话ID和个人路径。

非公开咨询或替代安全联系方式，请发送邮件至
[support@abruption.dev](mailto:support@abruption.dev)，标题注明 `[session-peer]`。
我们会尽力提供支持，但不保证响应时限。邮件由维护者手动审核，不会自动转为公开议题。
欢迎英文与韩文报告。
