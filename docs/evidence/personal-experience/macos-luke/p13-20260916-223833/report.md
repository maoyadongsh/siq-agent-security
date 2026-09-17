# macOS Luke：真实重启后的隔离状态恢复

用户要求先推送再重启。重启前已将当前分支推送到 `origin/codex/macos-luke-p06-20260916-153008`，远端读回 SHA 为 `9cba48f07de430936c4d73da0b88f8f428a2f2fe`，工作区干净；随后调用 macOS System Events 的正常 `restart`，未使用 sudo、强制关机或更改安全策略。重启后用户重新登录并返回本任务。脱敏断言见 [post-reboot.json](post-reboot.json)。

重启前 `kern.boottime` 为 2026-09-12 16:35:34；重启后为 2026-09-16 22:31:44，当前 GUI 用户域为 Aqua、macOS 26.6.2、arm64。这是实际 OS 启动实例变化，不以 shell 重开冒称重启。

同一隔离状态目录在重启后 `state-status` 为 `compatible=true/status=ok`；本候选 Mach-O arm64 二进制 SHA256 仍为 `f067f96b05c3472b8ebe2d43ac9c19ce79c5063af19ec1dc66999a6da1bd3e23`。以原私有状态手动启动 47614，`status --port 47614` 返回 `product=siq-agent-security/status=ready/local_mode=true`；停止后端口释放。回执链重启前后均 `verified=true`、22 条、head seq 21、head hash `5de8d4d9c0f09a2ce5aebf9676c66daa333015513974cccc0c76fb35b2b0e9be`。安全只读哨兵和受控越权哨兵摘要不变，离线写目标仍不存在。隔离 WorkBuddy 项目配置中产品钩子为 0、原有用户钩子每事件 1；日常 WorkBuddy 配置摘要未变。

**验收边界：** 本批证明真实重启后状态可读、回执链完整且隔离服务可手动恢复。重启前并未注册测试 LaunchAgent，故不声称登录自动启动、launchd manager 跨重启归属或崩溃自动重启。未做独立注销/登录、休眠/唤醒、断电测试；旧 v1 macOS 拒写、宿主审批继续、通知点击回跳和独立审阅仍按 [P12 总结](../p12-20260916-221900/report.md)保留缺口。Intel/amd64 仍属用户取消的实机范围，不冒称通过。

没有将私有状态、配对码、token、账号内容、原始提示或绝对用户路径归档。没有单独停止或修改 47612/47613；整机重启后它们与 47614 均未监听，本批手动恢复过的 47614 也已停止。
