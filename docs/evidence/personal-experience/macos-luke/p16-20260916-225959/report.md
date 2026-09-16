# macOS Luke：真实休眠／唤醒与隔离状态恢复

本机 macOS 26.6.2 / arm64 在 Aqua 会话完成一次**真实系统 Sleep/Wake**。初次通过 System Events 请求只发生 1 秒屏幕关闭／点亮，电源日志仍为 0 次 Sleep/Wake，故不计入通过。随后执行不修改电源策略的 `pmset sleepnow`；`pmset -g log` 记录 22:57:10 因 Software Sleep 进入系统休眠、约 117 秒后在 22:59:07 DarkWake、22:59:08 FullWake，启动以来的 Sleep/Wake 计数变为 1。`kern.boottime` 前后保持同一个 22:31:44 启动实例，不把重启当唤醒。脱敏结果见 [sleep-wake.json](sleep-wake.json)。

唤醒后同一隔离 v2 状态 `compatible=true/status=ok`，本地回执链仍 `verified=true`、22 条、head seq 21 且摘要未变；只读哨兵与日常 WorkBuddy 配置摘要未变。以受测 arm64 二进制手动启动隔离 47614 返回 `product=siq-agent-security/status=ready/local_mode=true`，然后正常停止，端口已释放。没有停止其他服务、改变休眠断言、执行 sudo 或改安全策略。

本批只证明正常休眠／唤醒后的状态与手动服务恢复，不证明断电耐久性、自动 LaunchAgent 重启或独立注销／登录。Mac-P03 真实重启后恢复见 [P13](../p13-20260916-223833/report.md)；历史 0.1.0 对 v2 状态拒写失败见 [P15](../p15-20260916-225339/report.md)。
