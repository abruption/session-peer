# 跨主目录的 Codex 会话

`session-peer list --json` 包含 Claude 以及跨已知主目录保存的 Codex 会话。`--agent codex` 过滤至 Codex；`--agent claude` 跳过 Codex 清单。在没有 `--codex-home` 的情况下，目标上的候选为：

1. 默认的 `~/.codex`。
2. `CODEX_HOME`（若非空）。
3. macOS 下的直接账户主目录 `~/Library/Application Support/orca/codex-accounts/*/home`。
4. `SESSION_PEER_CODEX_HOMES`，即绝对（或 `~/`）主目录路径的 JSON 数组。

没有递归文件系统扫描或进程/凭据检查。显式的 `--codex-home PATH` 会绕过自动清单和无关的配置错误。数据库以只读方式打开。Send/wake 保留其现有的更严格的主目录解析；列出不会选择活动写入器。

## 行与发现

每个 Codex 行均包含其规范的 `codexHome` 和绝对 `stateDb` 路径。身份为 主机 + 规范主目录 + UUID：不同主目录中的相同 UUID 保持分开。同一主目录的符号链接别名会被去重并合并其 `sources`。Codex 行按 `updatedAt` 降序排序，然后按主目录和 UUID 排序。`--all` 在每个主目录中独立包含已归档记录。人类可读输出会在每行旁边显示主目录。

示例（在现有的 schemaVersion 1 信封内）：

```json
{
  "sessions": [
    {"agent": "codex", "id": "same-uuid", "codexHome": "/home/me/.codex", "stateDb": "/home/me/.codex/state_5.sqlite"},
    {"agent": "codex", "id": "same-uuid", "codexHome": "/home/me/custom", "stateDb": "/home/me/custom/state_5.sqlite"}
  ],
  "discovery": {
    "codex": {
      "status": "ok",
      "homes": [
        {"codexHome": "/home/me/.codex", "stateDb": "/home/me/.codex/state_5.sqlite", "sources": ["default"], "status": "ok", "sessionCount": 1},
        {"codexHome": "/home/me/custom", "stateDb": "/home/me/custom/state_5.sqlite", "sources": ["configured"], "status": "ok", "sessionCount": 1}
      ]
    }
  }
}
```

旧版的顶级 `codexHome` 仅在清单识别出恰好一个候选主目录且无清单错误时保留；在多个主目录时将其省略。使用者应使用该行对应的主目录，而不是从线程 UUID 推断主目录。

主目录诊断使用 `status: ok | absent | error`。不存在可选的默认或 Orca 数据库不是错误。通过 `--codex-home`、`CODEX_HOME` 或 `SESSION_PEER_CODEX_HOMES` 显式命名的缺失主目录属于错误，即使它是可选候选的别名。成功读取的空数据库为 `ok` 且会话数为零。

错误携带稳定的 code：`state_db_missing`、`state_db_not_regular`、`permission_denied` 或 `state_db_read_failed`（包括损坏/不兼容的数据库）。清单失败出现在 `discovery.codex.errors` 中，包含 `source`、`error`、可选的 `path` 以及代码 `home_resolution_failed`、`candidate_enumeration_failed` 或 `invalid_home_configuration`。无效的额外主目录配置会被整体拒绝；默认/环境变量/Orca 结果得以保留。

任何失败都会将 Codex 汇总设置为 `error`，将命令设置为 `ok: false`，退出码 1，并保留其他主目录和 Claude 行。在没有可读数据库且没有错误的情况下，自动发现报告 `not_installed`、空会话并退出 0。这是对先前缺失默认数据库错误的变更。成功的发现不是活动、接收或队列消费的证据。

## SSH、send 和 MCP

通过 SSH 流式传输的源码会使用该主机自身的用户/环境枚举其上的主目录。重复的 `--host` 保留现有的有序响应数组；一次失败会导致整体退出码为 1，但不会丢弃其他主机的结果。

显式使用所选行中的主目录：

```sh
session-peer list --host user@worker --agent codex --json
session-peer send --host user@worker --codex-home '/path/from/selected/row' --to codex:<uuid> 'message'
```

MCP 继续显式传递其配置的主目录。此 CLI 默认设置不会授予 MCP 访问其他主目录的权限；为额外的主目录创建另一个授权目标。Python 3.9 独立依赖保持不变。
