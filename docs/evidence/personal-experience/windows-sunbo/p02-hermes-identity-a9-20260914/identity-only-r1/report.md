# Windows Hermes launcher 身份诊断

本次身份诊断通过：实际 guard 所在 CPython 的 PID 与 venv launcher 不同，guard 自报 PPID 等于 launcher。父持有 actual handle，在映像 SHA 计算前后均观察到它仍存活、PID 一致，并属于本次具体 Job；映像匹配执行前已固定的 base CPython 3.11.16。

actual 和 launcher 均在 Job 关闭前已 signaled、exit 0；launcher 完成 wait，actual/launcher/Job 句柄均有关闭记录。Job 关闭前 active 0、terminated 0。控制器耗时约 12.268 秒、外层约 12.791 秒；无超时、强制终止或输出读取超时。guard 记录一次安装与 12 秒正常自退，无拒绝事件；栈、stdout、stderr、stdin 文件均为空。

独立重算了冻结审阅清单的 11 个 payload、原始运行文件、安装来源与复制 guard 摘要；固定 argv、内嵌 identity、前后源 SHA 均一致。新根 protected 三 ACE，原父 ACL 未变，独立只读回查一致；helper ready/handshake 文件不存在。详见 [白名单摘要](summary.json) 和 [原始来源摘要索引](raw-source-index.json)。

这次使用同一安装 venv launcher，但 `-S -s -B -c` 显式导入新 sitecustomize，在身份观测后退出。没有进入 Hermes main，也没有 provider、模型、SIQ、helper 或网络调用。Hermes A/B 仍为 **not_run**，不计正常宿主启动或原生工具链验收通过。

Job total 为 3，本轮只单独识别 launcher 与 actual 两个角色；未收集第 3 个进程身份，不能从计数补齐进程链。v7/v8 没有 actual PID，不能用本轮结果改写旧失败原因。该结果只为下一轮提供具体方向：重新核验当轮 live actual handle、精确 Job 与预钉映像，再讨论绑定当轮实际 PID；不能沿用此次 PID 或放宽 helper 许可。

自 watchdog 安装前的解释器初始化窗口仍未覆盖；Python audit hook 不是 OS 沙箱，磁盘 SHA 也不是内存证明。本轮未测试主动绕过 guard。公开文件为字段白名单派生，省略本机绝对路径、用户名、数值 PID、SDDL 和原始输出；原件未改，SHA 只用于追溯私有来源。
