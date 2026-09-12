# M67：macOS 启动与合入验证

候选：codex/personal-client-upgrade-recovery，基于 69d9c59 的 M48–M67 本地增量。日期 2026-09-12。规格 §3.11.29，CLI launch-agent-start --confirm-start。

先复用已注册配置加载与生命周期锁，已报告 PID 时不重启；尚无进程时确认主 Writer 可用并释放，复验归属后 kickstart 精确 GUI 实例。读取配置、正 PID 和目录健康后才返回成功；超时保留现场。不会因为 API 返回健康而省略加载配置归属核对。无新增持久合同。

验证通过：Go vet/全量，CLI/state/clientrelease race，159 项 Python 合同及 Ruff，四目标交叉编译；启动的初次、复用、不健康、无 PID、kickstart 失败、异配置、Writer 冲突、健康期间文件漂移 8 项模拟场景和 CLI 确认参数负向。加载测试同步回归通过。

| 构建 | SHA-256 |
| --- | --- |
| linux/arm64 | 80f072ea3074956f03e44a6f6af2f3511459ce588d2d72a703e8b30a1f7d2deb |
| linux/amd64 | d9ca59810a4f7af97951d6c2fee535a7a10e43b1deae04402fccb078892c4760 |
| darwin/arm64 | 36eae075ef9cb25c32411868f2a07e662c0a45cc9fba2da5bef72e761b2a9037 |
| windows/amd64 | 9bbfbc5b9f03dc6d270d7a690e1b2845de0be6254078cb07454bec1edf5503a2 |

没有 macOS 实机启动证据，不计为跨 OS 原生通过。用户本轮授权先提交并合入 main，当前批次合入不表示 UX-003 或完整个人/LAN 目标完成。后台退出/恢复、Windows 生命周期和其他未验收项继续保留。

最终 Linux arm64 候选原生回归：TestNativeSetupAndReuse 通过（3.04 秒）；TestNativeUserServiceUpgrade 与 TransientFailure 通过（合计 4.60 秒）。均为隔离 runtime 服务，覆盖 setup/复用/ui/自启管理/teardown，以及升级、失败恢复、回退与源快照恢复；不是正式不同发行版本验收。
