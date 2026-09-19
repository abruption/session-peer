# 控制看门狗与中继恢复 (RC 候选)

`Upholds=` 可以重启已停止的中继，但无法检测到 systemd 仍视为活跃的卡死（frozen）控制进程。因此，控制应用程序参与了 systemd 看门狗。这在 systemd 之外是可选的，且不增加任何 Python 或 Node 软件包依赖。它要求服务主机上存在 `/usr/bin/systemd-notify`。

使用 `Type=notify`、`NotifyAccess=all`、`WatchdogSec=30` 和 `WatchdogSignal=SIGKILL`。通过 `flock --no-fork --nonblock` 启动 Node，使 Node 成为主 PID 并与 `WATCHDOG_PID` 匹配。现有的排他写入者锁保持持有状态。不同的看门狗 PID 或不完整的看门狗配置属于启动错误，而非静默禁用。可执行文件必须是位于被 `ProtectHome` 隐藏的主目录之外、属主为 root 的 Node 运行时。

在环回监听器启动后，控制仅在其健康检查通过时发送 `READY=1` 和 `WATCHDOG=1`。同一事件循环最多每五秒（或配置的看门狗周期的三分之一）检查一次：

- 发布者未失败且监听器正在运行；
- 最新成功的公共状态处于其 180 秒的有效期内，且不超前于未来时间五秒；
- 常规状态文件仍与该发布内容完全匹配；
- 控制数据库版本与已发布的版本一致。

HTTP `/healthz` 端点使用相同的状态检查。读取失败、状态缺失或改变、发布者失败以及不健康的检查均不会发送心跳。卡死的事件循环同样无法发送心跳。这些检查并不意味着 OAuth 请求成功或原生代理投递成功。

通知使用无 shell、单次执行（single-flight）的子进程，具有两秒超时和 `SIGKILL` 终止。其环境中仅传递 `NOTIFY_SOCKET`；不继承 OAuth 配置、令牌和凭据路径。通知器不会设置 `MAINPID` 或使用 `--no-block`：systemd-notify 的确认应答可避免在 systemd 将通知归属之前退出。`NotifyAccess=all` 允许该单元 cgroup 内的子进程进行通知；它不会授权其他单元。关闭会停止调度心跳；已在运行的通知器受相同的两秒超时限制。

操作员的协同堆栈仍必须将控制的失败与中继终止相关联（`BindsTo`/顺序），并且仅在新的就绪检查通过后才重启中继（`Upholds`/顺序）。30 秒的看门狗是有界的故障检测，而不是即时的健康检测，也不能替代 Python 状态验证和实时吊销检查。保持启动、重启和速率限制显式。迁移和重放初始化绝不能成为自动恢复的依赖项。

在公开应用之前，请使用精确编译的候选版本和实际沙箱来验证主 PID 归属、长于看门狗周期的健康运行、控制 cgroup SIGSTOP、持续不健康状态、SIGKILL、自动重启后的全新就绪状态、中继崩溃、显式堆栈停止以及重启限制。保留所有密钥、操作收据、重放证据和版本高水位线。无论是重启还是让计数器追赶，都不能建立安全的备份恢复。

本地单元测试涵盖通知门控、失败、有界并发、环境隔离和状态健康检查。它们并不建立实际的 systemd 通知投递或 SIGSTOP 恢复门控；这需要 KR 运行时实验。

参考资料：[systemd v255 通知语义](https://github.com/systemd/systemd/blob/v255/man/systemd-notify.xml) 以及 [服务看门狗选项](https://github.com/systemd/systemd/blob/v255/man/systemd.service.xml)。
