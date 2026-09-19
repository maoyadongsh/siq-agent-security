# Windows

当前宿主范围为 OpenClaw、Hermes、WorkBuddy。0.3.0 提供 amd64 程序和已签名 Skill，Windows junction 源码修复已经随 #90 合入并进入新包；本版仍只有构建/验签，本版原生安装、升级及完整宿主验收未运行。项目签名不等于 Authenticode。

- 安装入口：[签名包 PowerShell 步骤](../../docs/signed-release-packaging.md)，选择 windows-amd64.exe；依次验签、初始化启动、浏览器配对。沿用系统正常脚本策略，不降低签名或路径检查。
- 操作与恢复：[个人手册](../../docs/personal-client-operation-guide-20260916.md)、[任务生命周期 CLI](../../AGENTSHIELD.md)。核对 SID、任务 XML、DACL、实例目录与实际程序；未知归属、迁移状态或锁不得手动删除来推进。
- 有效任务：[sunbo 平台任务书](../../docs/personal-windows-sunbo-taskbook-20260913-202355.md)、[整合复核](../../docs/windows-main-integration-review-20260919.md)及其后续[源码与签名边界](../../docs/skill-source-release-boundary-20260919.md)。旧待合并栈和待签阻塞已被后续记录取代，不据旧顶部快照恢复阻塞。
- 证据解释：历史 OpenClaw 使用 WSL Agent，Hermes 是原生 CLI，WorkBuddy 为原生最小 Skill 读写；不能拼为一个 Windows 同候选完整旅程，也不承诺 WorkBuddy WSL2 形态。

[`*.ps1` 资源](../../apps/agentshield/cmd/agentshield/)和 Windows Go 文件保留所属包；目录整理必须保留大小写、执行脚本资源和字节属性。跨平台编译不替代 DACL、junction、任务升级回滚与 GUI 的原生验证。[支持范围](../support-matrix.md)及[评测入口](../../evaluations/README.md)与实现状态分别记录。


## 源码、基础检查与功能验收

[运行时模块](../../apps/agentshield/README.md)、[Web](../../apps/web/README.md)与[宿主适配器](../../adapters/runtime/README.md)分别维护共享核心、界面和协议边界。平台生命周期按本页手册执行，不复制另一套实现到 platforms 目录。

[四目标源码原生检查](../../docs/evidence/repository-reorganization-final-20260919/README.md)已有本平台自建程序的准入与基础启动/配对/控制台/停止记录。它与 0.3.0 正式包使用不同候选，不等于系统服务、升级回滚、通知或完整宿主验收；后续验收仍需固定同一程序、UI、适配器、宿主版本和状态格式，再记录允许、拒绝、撤销与恢复的实际结果。
