# macOS

当前宿主范围为 OpenClaw、Hermes、WorkBuddy。0.3.1 包提供 arm64 程序，完成构建/项目清单验签；本版尚未完成原生安装升级与完整同候选宿主验收，也没有以项目签名替代 Apple 签名或公证。

- 安装入口：[统一签名包指南](../../docs/signed-release-packaging.md)。选择 darwin-arm64 程序，先验签再首次启动。不要把 Linux 命令执行成功作为 macOS 实机证据。
- 操作与诊断：[个人手册](../../docs/personal-client-operation-guide-20260916.md)、[LaunchAgent 原语说明](../../AGENTSHIELD.md)。检查当前 GUI 用户域、程序路径和实例归属；配置生成/注册/加载/启动分别确认，失败保留现场。
- 活跃范围：[M01–M11 剩余任务](../../docs/personal-macos-luke-remaining-development-20260917.md)、[原任务书](../../docs/personal-macos-luke-taskbook-20260913-202355.md)、[阶段整合复核](../../docs/evidence/personal-experience/macos-stage-review-fixes-20260917/report.md)。阶段已合并与新候选验收分列。
- 共享核心变化：[Linux 交接影响矩阵](../../docs/linux-dual-host-platform-handoff-20260918.md)、[当前导航](../../docs/development/current.md)。审批归属、会话世代、嵌入资源及持久安装身份变更仍需本平台复测。

源码仍位于 [Go CLI](../../apps/agentshield/cmd/agentshield/)及所属 internal 包，遵循 Go 平台后缀；不迁为本目录下的另一套实现。GUI、原生 CLI、fixture 与人工桌面结果分别登记至[评测入口](../../evaluations/README.md)。


## 源码、基础检查与功能验收

[运行时模块](../../apps/agentshield/README.md)、[Web](../../apps/web/README.md)与[宿主适配器](../../adapters/runtime/README.md)分别维护共享核心、界面和协议边界。平台生命周期按本页手册执行，不复制另一套实现到 platforms 目录。

[四目标源码原生检查](../../docs/evidence/repository-reorganization-final-20260919/README.md)已有本平台自建程序的准入与基础启动/配对/控制台/停止记录。它与 0.3.1 正式包使用不同候选，不等于系统服务、升级回滚、通知或完整宿主验收；后续验收仍需固定同一程序、UI、适配器、宿主版本和状态格式，再记录允许、拒绝、撤销与恢复的实际结果。
