# AI辅助设置与运维

[返回概览](../../README.zh-CN.md)

本指南是一份可交给编程代理或AI助手的简洁工作说明。它帮助AI选择最小的
session-peer配置，完成工作和验证，并报告剩余限制。它不会授予新的权限，
也不会把“消息已提交”变成接收方代理已经阅读消息的证据。

## 复制这段请求

替换方括号中的内容，然后把整个代码块交给AI。让AI先检查当前机器和仓库，
再向你提问。

```text
Read AGENTS.md if it exists, then read docs/ai-assistant-guide.md and every guide it links that is relevant to this goal.

Goal: [install session-peer / connect an SSH host / configure MCP / configure Antigravity / configure paired devices / diagnose a failure]
Environment: [operating system, local or remote, SSH alias if any]
Target agents: [Claude Code / Codex / Antigravity]

Work through the goal to a verified result. Reuse authorization already given in this conversation. Before account changes, OAuth consent, DNS or firewall changes, service deployment, reboot, payment, merge, release, or publication, confirm that the action is explicitly authorized. Never ask me to paste secrets into chat; use an existing credential manager or protected file. Start with read-only discovery, use dry-run where available, preserve unknown message outcomes, and do not retry a send merely to turn an unknown result into success.

At the end report: outcome, files or systems changed, commands and tests run, message acknowledgement evidence, remaining limitations, and any rollback instructions. Redact tokens, cookies, session IDs, private paths, conversation text, and private keys.
```

## 选择最小范围

- 对同一台机器或SSH主机上的会话，只安装核心CLI。
- 仅在目标代理需要时配置可选适配器。
- 仅在MCP客户端需要session-peer工具时添加MCP。
- 仅当SSH不合适且运维人员接受额外的身份、恢复和服务工作时，
  才使用配对设备或加密中继。

不要仅仅因为仓库中包含中继代码就部署中继。普通使用应继续默认采用
依赖更少、更简单的本地或SSH工作流。

## 必需的工作流程

1. 确认操作系统、Python版本、安装方式、当前用户、目标账户、代理主目录，
   以及目标是本地、SSH、MCP还是配对设备。
2. 修改文件前阅读相关指南并检查已安装版本。如果探测结果给出不同的代理
   主目录，不要假定默认路径。
3. 从只读探测开始。发送真实消息前，使用doctor、list和dry-run确定准确的
   目标及传输方式。
4. 进行最小且可逆的更改。修改共享服务或远程主机前，保留现有配置并记录
   回滚方法。
5. 不要把凭据放入命令、日志、源代码管理、Issue评论或聊天中。使用受保护的
   文件、系统凭据功能或用户的凭据管理器。
6. 验证安装路径和实际请求的传输方式。本地单元测试不能证明SSH、OAuth、
   公共WSS或接收模型正常工作。
7. 报告事实及其限制。submitted、posted或queued不等于确认；如果完成情况
   很重要，应要求并观察明确回复。

## 基准命令

优先采用隔离的工具安装。在原生Windows上，请使用Python包管理器，
不要使用POSIX Shell安装脚本。

```bash
python3 --version
pipx install session-peer
# Alternative: uv tool install session-peer

session-peer --version
session-peer doctor
session-peer list --output-format json
```

在不传递消息的情况下解析目标。只有远程目标才需要添加SSH主机选项。

```bash
session-peer doctor --host SSH_ALIAS
session-peer list --host SSH_ALIAS --output-format json
session-peer send --host SSH_ALIAS --to TARGET --dry-run --message "hello" --output-format json
```

dry-run解析出一个预期会话后，只发送一次新消息。不要复用README中的虚构名称
或标识符。

```bash
session-peer send --host SSH_ALIAS --to TARGET --message "Reply with: SESSION-PEER-ACK-UNIQUE-MARKER" --output-format json
```

## 安全与授权边界

- 将代理数据库、收件箱、对话记录、Cookie、OAuth令牌、设备状态、私钥、
  重放状态和凭据文件视为私密信息。
- 不要在机器之间复制浏览器配置或凭据。需要交互式同意时，使用已持有用户
  认证会话的浏览器。
- 不要为了让测试通过而削弱主机密钥检查、认证、防火墙规则、浏览器完整性
  保护或服务沙箱。
- 安装或诊断请求本身并未授权账户更改、公开暴露、付款、破坏性清理、重启、
  合并、打标签、发布版本或发布软件包。
- 如果某项操作已获明确授权，请完成可逆的准备和验证，不要重复请求相同权限。
- 超时或响应丢失后仍要保留请求和操作标识符。应核对状态，不要创建重复操作。

## 完成报告

AI应按以下格式留下简短报告：

```text
Outcome:
Changes:
Validation:
Acknowledgement evidence:
Remaining limitations:
Rollback:
```

只有在全新Shell中能运行目标命令，安装才算完成。只有实际测试了所需的本地、
SSH、MCP或配对路径，传输设置才算完成。中继部署还需要检查服务健康状态、
持久化状态、重启、备份和恢复。不要把排除或中断的测试描述为已通过。

## 相关指南

- [CLI参考](cli-reference.md)
- [诊断与回复](diagnostics.md)
- [MCP配置](mcp.md)
- [代理适配器](agent-adapters.md)
- [Antigravity](antigravity.md)
- [Wake行为](wake.md)
- [配对设备与加密中继](paired-devices.md)
- [安全政策](../../SECURITY.zh-CN.md)
