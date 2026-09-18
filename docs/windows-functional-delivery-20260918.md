# Windows 三宿主功能集成交付

本轮按用户最新要求先完成全部功能维度的实现核对，再统一收口；最终集中测评在时间和额度不足时可不执行。本文描述已经集成的实现与保留限制，不声明 Windows 全项验收通过。

任务依据：共享协作验收规则、Windows sunbo 任务书、平台材料规格（仓库 `docs/` 下 20260913 版本），覆盖 Win-P00–P05；不扩展到 LAN。原任务书的安全不变量和真实证据要求保留；执行顺序及本轮测试交付要求以用户最新指令为准。

## 集成范围

| 维度 | 已集成实现 | 代码入口或实现提交 |
| --- | --- | --- |
| 构建、启动、管理 | Windows npm 启动器、原生客户端安装、管理配对和状态恢复 | `apps/web/scripts/vite-local.mjs`；`cmd/agentshield/client_install.go`；63fffcf、4449c94 |
| 三宿主发现和接入 | OpenClaw、Hermes、WorkBuddy 实例发现，预览/确认/备份/配置应用/卸载；Hermes 原生启用和有界自检 | `internal/inventory`、`internal/adapterinstall`；13129e1、b8779b8、494464e |
| Windows 权限与身份 | 明确选择本地盘符 profile、独立起草/批准/部署/身份确认，WorkBuddy 受管 command 身份及专属凭据 | `internal/runtimeidentity`、`internal/grant`、`internal/runtimepath`；1b3751c、974819b、f703684 |
| 会话、审批与撤销 | OpenClaw 原生 epoch 绑定；每次在线复验身份；WorkBuddy 持久关联、原 hold 查询、唯一 reserve 与 post 关联；不确定结果不自动重执行 | `adapters/runtime/openclaw-agentshield/index.ts`、`cmd/agentshield/workbuddy_managed_resume.go`、`internal/workbuddycorrelation` |
| Skill 安装、更新、移除 | WorkBuddy 用户级/项目级目标确认；安装恢复、更新比较与确认、自动只读检查、先撤销后清理；保留未知用户对象 | `internal/skillinstall`、`internal/server/skill_install.go`、Web Skill 安装/更新/移除界面；2285309、1122cf4 |
| 系统生命周期 | 本用户 Task Scheduler 注册/启动/停止/注销；签名任务升级/回退和中断恢复 | `cmd/agentshield/windows_task*.go`、`internal/state/windows_task*.go`；ef9cae9 |
| 文件与状态保护 | Windows 私密 DACL、资源事实及 reparse 拒绝、Writer 恢复、N01 兼容屏障与迁移恢复；保留撤销历史 | `internal/privatefs`、`internal/runtimepath`、`internal/statefs`、`internal/state` |
| 通知与操作界面 | Windows 桌面投递、点击打开受限管理入口；通知不能直接批准；实例权限、作用域与诊断界面 | `internal/notify/desktop_windows.go`、`cmd/agentshield/desktop_notify.go`、`apps/web/src/local`；4449c94 |
| 活动、结果与隐私 | 任务/决策/观察关联，未知结果保留；原文默认关闭、独立授权/撤销/到期读取限制与脱敏导出 | `internal/server/task_activity_*`、`internal/server/raw_task_content.go`、`internal/rawcontent`、`internal/export` |

表中 Go `cmd/` 与 `internal/` 均相对 `apps/agentshield/`。这是实现交付清单，不是逐项真实宿主通过清单；宿主原生安装前拦截、可信 Skill 归属及子任务边界仍以实际支持能力和证据为准，未知归属不升级为 verified。

## 固定源码与已有检查

- 实现候选：`494464ea9f3cff90be4dc0ceac0dd5980c464617`。Windows amd64 自建二进制 SHA256：`ad7680ba64672c9abbaab341ecebea4946e317e2fc3c6160cb5a0ade7e6d9d16`。已有干净候选构建退出 0。
- 收口前分支 head：`1b54d048874e072a5c39a0d07b6e1c4878ba6500`；与实现候选相比只有 Hermes r3 的四份证据文件，产品源码和嵌入 UI 未变化。本交付说明同样不改变产品候选。
- 最近 UI 类型检查和本地嵌入构建退出 0，输出已纳入 494464e。沿用已有定向 Go/Web/合同检查与各批四目标构建记录，不将不同历史候选拼为最终全通过。
- Hermes 正式接入/自检 r3 的独立核查已通过；r1/r2 原失败保留。材料见 `docs/evidence/personal-experience/windows-sunbo/hermes-product-runtimecheck-20260918-r3/`。
- 1b54d04 的 PR CI 为 38 成功、2 跳过、2 失败。两个失败 job 均在 `internal/skillmanifest` 的三项测试遇到旧发布清单与实际 Skill 内容摘要不符；仍是实际失败，未删除或放宽测试。
- Windows 全量 Go/相关 race 的历史失败及超时尚未由最终候选全量回归关闭。本轮收口不重新启动完整测评；这些结果不能写为通过。

## 未测与外部依赖

1. 三宿主完整原生旅程及统一最终候选验收未完成。现有固定 303 项台账为 78 通过、3 失败、5 受阻、217 未测；属于各自证据范围，不是本次交付候选覆盖率。其他 OS 和 WSL2 保持各自标记。
2. WorkBuddy 当前账号此前只授权一次基础写入且已经消耗。完整桌面模型调用须额外授权；代码和组件结果不能替代其桌面验收。
3. `productionGitFetch` 按 ADR-0051 保持关闭，等待真实托管网络安全验收。HTTPS ZIP、本地目录及本地 ZIP 路线保留；不通过开放环境开关绕过这一门禁。
4. 新正式发行清单需要受授权签名流程。旧发行清单、签名和信任根保持不变，不用测试签名冒充正式发行；当前 PR 不具备发布或合并放行结论。
5. 第二 Windows 登录身份、可追溯的受支持旧版本及另一台同 OS 复跑/维护者接受分别保留为外部或待验事项。
6. 用户禁止系统重启、注销、关机和睡眠/休眠；相应系统中断项单列排除，不记通过。没有因此放宽服务失联、撤销及 fail-closed 行为。

## 工作区与交付边界

交付沿用 PR #83，基于 PR #82 的 Windows 私密状态分支；维护者应保留依赖顺序。只提交本轮相关材料，不写 main、不合并、不发布或修改治理。

原工作树的 `apps/agentshield/cmd/agentshield/launch_agent_switch_test.go` 未验证修改，已在后续仓库整理中原样归档到本地 `codex/windows-deferred-launch-fixture-20260918`（`3f7bbcfe43f2d8aa3d09dac168ea5edcb71b3e21`），并从主集成工作树移开。它不进入本次交付候选，不当作已完成的全量测试修复。分支、Issues 和 PR 的最新组织见 [Windows 协作索引](windows-branch-pr-status-20260918.md)。

上一批 Hermes r3 的自有进程/Job 清理已有记录；被暂停的 A05 草稿没有启动宿主、服务或模型。本次收口没有新增宿主进程、系统任务或修改日常配置。此前失败和清理证据不覆盖、不删除。

给合伙人的结论：Windows 三宿主及共性功能已汇集在同一实现分支，可按现有 PR 审阅；本轮交付侧重功能实现与集成。完整原生验收、正式签发和上述外部事项仍有明确限制，不能对外表述为所有 Windows 测试通过或正式发布就绪。
