# 个人版平台范围决策：Linux 仅 Hermes 与 OpenClaw

日期：2026-09-17。用户明确决定：**Linux 系统只基于 Hermes 和 OpenClaw 开发、验收；不再安排 Linux/WorkBuddy 的安装、接入、原生运行或完整旅程任务。** 这是产品范围调整，不是 Linux/WorkBuddy 已通过，也不推断 WorkBuddy 永远不可能提供 Linux 版本。

当前产品矩阵为：**本机 Linux：OpenClaw、Hermes；Luke 的 macOS：OpenClaw、Hermes、WorkBuddy；sunbo 的 Windows：OpenClaw、Hermes、WorkBuddy。** Luke 已阶段性推送 macOS 开发成果，其中 WorkBuddy 为阶段性完成；这不是新候选的三宿主整体验收通过。sunbo 仍在开发，已推送部分 Windows 分支，不能写成未推送或全部完成。这是用户提供的协作状态，最终验收仍以各 OS 的同候选实机证据为准。Linux 已取得的 Hermes/OpenClaw 证据照原候选和证据等级保留。Linux/WorkBuddy 的旧 `blocked`、`unverified` 或预检记录作为历史事实保留，不改写为成功。

2026-09-20 更新：当前源码仅保留上述宿主接入。退役平台不再发现、安装、卸载或显示在平台列表中；旧记录仍可读取、验签、拒绝或撤销，不能激活授权或恢复执行。现有用户配置不会自动改写；升级后遗留的未知平台钩子只输出拒绝，应由用户核对备份后移除其精确钩子条目。历史资料与签名制品按原字节保留，不代表当前支持范围。

N09 v2 矩阵继续保留九格、每格 J1–J11 十一行，避免破坏历史引用。**新的**矩阵可把 Linux/WorkBuddy 整格十一行统一标为 `out_of_scope`，原因 `product_scope_excluded`，分类 `static_check`，不附运行腿、覆盖或 `complete_acceptance`。其余八格仍须逐项验收；矩阵完整性校验通过不等于产品发布验收。`n09-baseline-check.py` 对该约束执行闭集校验。旧 `personal-platform-acceptance/v1` 的十八个候选材料是历史 QA 库存，不能删除旧证据；后续若要发布新的支持矩阵合同，应另建版本并清楚区分历史记录与新分母。

本机 F08 从此只继续托管源的真实网络预检与安全安装路径；Linux/WorkBuddy 诊断结果仅用于说明历史环境事实，不再作为待解锁的本机开发依赖。不得为“消除阻塞”借用其他平台、模拟宿主、放宽权限/SSRF 或把范围排除写成 `passed`。若未来恢复 已排除的平台，需新的产品决定、真实宿主与版本、适配方案及完整原生验收，不能沿用此次范围排除。

范围决策之后新增了[Linux 接入门禁候选](evidence/personal-experience/v6-linux-scope-20260917/report.md)：控制台状态/诊断标为不支持新接入，管理 API 与 CLI 拒绝 Linux 上的新 WorkBuddy 安装和安装预览，已安装的历史钩子仍可查看、卸载。底层跨平台适配器、历史 Grant/回执及旧 hook 保留；**其存在不构成 Linux 支持声明**。该候选已完成组件与隔离 CLI 验证，但尚未重跑 F01/D05 真实网关和性能，不能继承前一二进制的实测结论。Windows/macOS 仍须实机验收。
