# Windows 三宿主功能集成交付

当前产品候选为 `198c73ebfce2cc7af075a92068911699f2386449`。本轮真实 WorkBuddy Skill 安装激活后，运行身份已写入但 HTTP 响应断连；已修复身份管理接口的响应等待，并同步管理界面和嵌入资源。旧连接写期限的真实 socket 负向、新响应正向、取消/响应错误不写状态、原有身份隔离撤销/合同检查、15 项前端接口测试、类型与嵌入构建、Go vet、四目标干净构建通过。原隔离状态已读回并明确撤销遗留身份；新导入、安装激活、身份签发与钩子安装实际通过。见 [修复与管理链证据](evidence/personal-experience/windows-sunbo/identity-response-budget-20260919/report.json) 和 [候选摘要](evidence/personal-experience/windows-sunbo/identity-response-budget-20260919/unsigned-candidate.json)。

WorkBuddy 原生 Skill 调用未通过：用户协助手动输入后，桌面识别出了正式安装的 Skill；第 5 次任务已发送。会话管理查询随后断连，控制器已撤权并清理钩子，因此立即取消桌面任务；目标文件没有生成。累计 5/5 个授权任务，未自动重试。身份接口修复之外，SEC 管理响应期限也需同步修复；不能将目录识别或安装通过写成受保护的原生调用成功。以下 d9ad885 与更早候选的实测记录保留原身份，不改绑到本次构建。

2026-09-19 04 时当前实现候选更新为 `d9ad885f2f894dce3f7c9dd036130df7bb436e2a`。真实 Windows Hermes 安装绑定 Skill 在旧 5 秒请求预算下出现“服务端 allow、实际工具未写入”；已将 Windows Hermes 新安装及默认 HTTP 等待改为每请求 20 秒，保留更短期限、不重试及超时拒绝。114 项适配器测试、旧行为负向、安装往返/嵌入一致性、Go vet、四目标干净构建通过。新候选原生 `--skills managed-fixture` 已完成正式安装激活、未绑定拒绝、明确签发后写入、撤销后拒绝覆盖；独立核验 4 条回执、5 份签名文档、实际 37 字节文件及 5 个自有 Job 清理通过。原控制器末尾因宿主追加运行时间提醒导致 JSON 解析失败，原失败保留，不能记为脚本全绿。见 [独立原生证据](evidence/personal-experience/windows-sunbo/hermes-sec-d9ad885-20260919/report.json)、[开发检查](evidence/personal-experience/windows-sunbo/hermes-skill-budget-20260919/report.json)、[候选与归档摘要](evidence/personal-experience/windows-sunbo/hermes-skill-budget-20260919/unsigned-candidate.json)。

2026-09-19 Hermes 审批恢复增量：`d9ad885` 的同进程同会话原生调用完成“hold 阻止且文件缺席 → 管理接口明确批准 → 相同参数新调用 ID 精确重试 → 一次性预留后成功写入 → 再次重复调用重新 hold 且文件未变”，86.56 秒。独立验证 5 条签名回执、唯一执行 observation、撤权卸载和 5 个自有 Job 关闭。见 [审批恢复证据](evidence/personal-experience/windows-sunbo/hermes-approval-d9ad885-20260919/report.json)。该次使用实例基线 Grant 和本地模拟模型，不混同已安装 Skill SEC 旅程；人工 GUI、拒绝/过期及跨进程恢复仍未覆盖。

2026-09-19 Hermes 更新/移除增量：同一 `d9ad885` 候选在 Windows 原生 Hermes 完成 V1 安装、比较/暂存不改文件、确认替换 V2、旧 Grant 撤销与旧身份失效、新身份重绑、`--skills` 加载 V2、未绑定拒绝/绑定后写入/撤销后拒绝，以及移除目标与保留用户文件，265.56 秒。独立核验 4 条回执、13 份签名文档及 5 个自有 Job 关闭通过，见 [更新移除证据](evidence/personal-experience/windows-sunbo/hermes-update-d9ad885-20260919/report.json)。加载 V2 由摘要固定的控制器在模型请求现场断言；请求正文未保留，不声称可离线重放该正文。首次控制器 20 秒管理等待超时，原目标保留且完成清理；修正为产品界面相同的 70 秒管理等待后通过，产品源码未修改。首次失败保留，不代表网络源、并发操作者或完整任务书通过。

最新观察 `ec2fbe2` CI：38 成功、2 跳过、2 失败。Control API 已通过；两个失败 job 均只有 Issue #87 的三项旧正式清单摘要检查失败，详见 [CI 结果](evidence/personal-experience/windows-sunbo/hermes-update-d9ad885-20260919/ci-followup.json)。后续文档提交的 CI 不能自动继承为通过。

本次仅改 Windows Hermes 预算，未改变 OpenClaw/WorkBuddy 运行路径；下方各批证据仍保留原候选身份。Hermes 审批拒绝/过期/跨进程恢复、WorkBuddy Skill 完整旅程与新候选确认、正式签发仍待完成。没有新增云模型调用，WorkBuddy 保持 4/5 个授权任务。以下 eac2a99 增量为历史记录。

2026-09-19 03 时当前实现候选：`eac2a99089e8d17a752bd6159ce15dcdf9b9c2b8`。已补安装后会话选择、明确绑定、读回和撤销的管理界面及嵌入页面；服务启动时将 SEC 安装读取一次性接到现有三宿主安装库，修复在线路径误用 Hermes-only CLI reader；不支持的 Windows 长安装目标明确拒绝为无效请求。正式 Windows HTTP 夹具完成安装、准备、登记、签发、运行复验、读回、重复/错签名拒绝、撤销及撤销后失效。旧启动行为在负向回归中失败，修复通过；合同、前端、vet 与四目标干净构建通过。见 [检查与限制](evidence/personal-experience/windows-sunbo/skill-session-management-20260919/report.json)、[候选摘要](evidence/personal-experience/windows-sunbo/skill-session-management-20260919/unsigned-candidate.json)。

本次改动涉及公共安装读取。`eac2a99` 已在真实 OpenClawGateway WSL 宿主完成最小回归：正式接入、正常读取、越权拒绝、失联拒绝、身份撤销拒绝及卸载，66.60 秒；独立核对 4 条回执、文件副作用、二进制摘要和受管入口移除，自有进程无残留。使用本地模拟模型，没有云模型调用。见 [本候选 OpenClaw 结果](evidence/personal-experience/windows-sunbo/openclaw-candidate-eac2a99-20260919/report.json)。新候选 Hermes 原生 CLI 五场景回归及独立核验已通过（356.69 秒，10 条回执、17 份签名、10 个自有 Job 关闭），见 [Hermes 本候选结果](evidence/personal-experience/windows-sunbo/hermes-candidate-eac2a99-20260919/report.json)；新候选 WorkBuddy 原生确认仍未完成，下方旧候选证据保留；桌面 Skill 加载、完整审批恢复与正式签发仍未验收。WorkBuddy 仍为 4/5 个授权桌面任务。

2026-09-19 02:00 历史增量：当批运行确认候选为 `2d5ee6c725e865b2c0769f0d35ac839161dbb717`，修复 Windows WorkBuddy 卸载后宿主配置变化导致无法重装，以及真实钩子 4/5 秒预算不足。WorkBuddy 5.5.6 桌面在默认权限、GLM-5.3-Flash 下通过正式接入、正常写入及对应 pre/post 回执、越权拒绝、服务失联拒绝和撤权卸载；总共 4/5 个任务，含修复前一次失败。独立验证 7 条回执和 2 份身份/撤销签名；其中序号 0–2 是明确标记的合成诊断，真实桌面对应 3–6。自有服务与桌面已关闭，清理无错误。见 [结果及限制](evidence/personal-experience/windows-sunbo/workbuddy-desktop-2d5ee6c-20260919/report.json)。

OpenClaw 的实际可用路径是本机 WSL，Hermes 是 Windows 原生 CLI；两者复用 ff16606 的真实基本保护闭环证据。新修复只改变 Windows WorkBuddy 路径，未重跑两者，也不将旧证据冒充新二进制实测。三宿主基本保护链已有实际证据；原任务书的完整审批恢复、全部 Skill 旅程及正式发行仍不能据此声称全部验收。以下早期进度保留为历史，本段覆盖其中“WorkBuddy 0/5、尚待选目录、候选 ff16606”的当前状态。


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

2026-09-19 02 时补充：干净交付源码 `017c405`（产品代码与 `2d5ee6c` 相同）的 WorkBuddy 用户级 Skill 安装、检查、激活准备、更新、移除及签名历史读取通过，用时 160.43 秒；用户级/项目级受控会话绑定及混用、缺失、替换目标拒绝检查通过。首次两范围串行检查触及共用 300 秒上限，项目级当时停在更新提交的目录身份校验，整次退出 1，保留 [首次结果](evidence/personal-experience/windows-sunbo/workbuddy-desktop-2d5ee6c-20260919/skill-lifecycle-initial.json)。仅单独重跑项目级同一用例，177.10 秒通过、进程退出 0，见 [项目级结果](evidence/personal-experience/windows-sunbo/workbuddy-desktop-2d5ee6c-20260919/skill-lifecycle-project.json)。这些是 Windows 私有目录的组件流程，未启动宿主或模型，不证明桌面发现/加载 Skill 或审批恢复。另同步四处旧预算文字为已实现的完整 HTTP 链 20 秒、宿主等待 30 秒；安装内容校验仍为 5 秒。`017c405` 的两个失败 CI job 均确认是 `internal/skillmanifest` 三项旧正式清单摘要不匹配测试，继续由 Issue #87 跟踪，不更改旧签名。

## ff16606 历史修复与复用证据

- 本阶段历史实现提交为 `ff166068a9047d0cfca73f8dcfb6f8c2dd9102d8`；当前实现已由开头的 2d5ee6c 替代。WorkBuddy 已登记钩子的 matcher 被缩窄、设置 async 或重复登记时，正式安装/修复入口现在重建单独的同步全匹配产品钩子，同时保留用户钩子的原匹配范围和元数据。
- 新负向回归在旧实现失败、修复实现通过；正式 `Install → 损坏匹配范围 → Inspect → Install 修复 → Inspect → 撤权卸载` 组件流程通过。该流程使用隔离文件配置，不冒充 WorkBuddy 桌面真实工具调用。
- Go vet 通过；四目标构建通过。默认临时目录的适配器包回归因私密权限校验失败；私密目录重跑有 Hermes 取消用例 helper 未启动的失败，并在 5 分钟上限超时。WorkBuddy 定向生命周期/受管身份/修复检查通过；全量 Go 检查退出 1，包含大量权限夹具失败、清单不匹配及超时，不能宣布全绿。具体结果见本批证据目录。
- 未签名交接包与源码/二进制/Skill 摘要已准备，见 [签名交接](windows-signing-handoff-20260918.md) 及 [候选记录](evidence/personal-experience/windows-sunbo/workbuddy-repair-20260918/unsigned-candidate.json)。正式签名仍由 Issue #87 跟踪。

2026-09-19 00 时增补：同一 `ff16606` 自建 Windows 候选复用现有 Hermes 原生隔离流程，正常读写、越权拒绝、失联拒绝、恢复后允许、身份撤销后拒绝五场景通过（290.91 秒）。独立核验 10 条回执、17 份签名文档、实际文件副作用与 10 个已关闭 owned Job 通过；卸载后受管插件文件已确认不存在。预置原生启用配置不是本批安装器创建，未独立断言整个 profile 逐字节还原。没有付费模型调用，不证明审批恢复或其他宿主。见 [本候选 Hermes 结果](evidence/personal-experience/windows-sunbo/hermes-candidate-ff16606-20260919/report.json)。

### 三宿主使用方式与证据边界

2026-09-19 01 时增补：同一 `ff16606` Linux/amd64 候选在本机 `OpenClawGateway` WSL、OpenClaw 2026.9.4 的真实 `agent --local` 上完成受管安装、允许读取、越权写入拒绝、服务失联拒绝、身份撤销拒绝及卸载，耗时 67.09 秒。使用本地合成模型，没有云模型调用。独立检查确认 4 条持久回执、读取观察、禁止写入无副作用、固定哨兵未变化、受管配置和插件入口已移除、自有进程无残留。首次运行因核验脚本错误地预期恢复后回执数量不变而失败；实际新增项是失联拒绝记录的正常补记。修正该核验条件后通过，首次失败和清理结果保留。产品代码和候选未变化。见 [OpenClaw 本候选结果](evidence/personal-experience/windows-sunbo/openclaw-candidate-ff16606-20260919/report.json)。这不是 Windows 原生 Agent、审批恢复、可信 Skill 归属或整个 profile 逐字节还原的证明。

早期 WorkBuddy 桌面选择器、窗口恢复和重新安装准备失败记录保留在历史提交 284d792、01cca6d；当前状态见本文开头的 2d5ee6c 实机结果。重装和预算问题已修复，隔离实例已完成撤权卸载。

| 宿主 | 已接入的产品路径 | 尚不能声称的范围／外部条件 |
| --- | --- | --- |
| OpenClaw | 实例发现与预览安装；运行时插件将可信 sessionKey 与 sessionId 绑定到在线身份；ff16606 在 WSL 的真实 CLI 基本保护闭环已通过 | 不代表 Windows 原生 Agent 或完整旅程。原生 hold 必须有宿主可信执行前复验能力，缺少时继续阻断，不注入能力开关。 |
| Hermes | Windows 原生 CLI/profile 启用与受管插件；真实会话自动接入；pre/post、hold 批准后精确重试预留、撤销与配置还原 | 已有 494464e 的正式接入/自检证据，ff16606 另完成上述五个原生基本保护场景；审批及完整旅程仍未验收；进程退出或关联过期不凭旧缓存自动恢复；Windows 无 shell 安装包装器。 |
| WorkBuddy | Windows 桌面配置根的 PreToolUse/PostToolUse command 钩子；明确管理身份/凭据引用；在线裁决、持久关联、审批预留、撤销、Skill 用户级/项目级安装及卸载 | 2d5ee6c 已完成真实桌面正常写入、越权/失联拒绝、撤权卸载；累计使用 4/5 个任务。审批恢复、可信 Skill 归属及原生安装前拦截未实机验收。 |

三者的“发现、安装文件、受管身份配置、运行检查、可信 Skill 归属”各自独立。未知 Skill 归属不提升为 verified；用户直接绕过受控安装入口的行为不宣称被装前拦截。没有新增宿主插件 API、对外监听或替代安全引擎。当前交付仍不证明所有本地功能要求及真实调用全部完成，不能据此标记整项目完成。

2026-09-19 新候选 Skill 归属接通：`eac2a99` 在真实 OpenClawGateway WSL 宿主完成产品导入、安装、激活、原生 Skill 目录识别、安装绑定身份接入；同一原生会话在未签发 SEC 时拒绝，管理员明确签发后读取成功并产生 `verified / controlled_session` 归属及 observation，撤销 SEC 后拒绝。独立核对 4 条持久回执、哨兵不变、受管插件卸载和自有进程无残留，耗时 70.98 秒。见 [Skill 归属结果](evidence/personal-experience/windows-sunbo/openclaw-sec-eac2a99-20260919/report.json)。使用合成 Skill 与本地模拟模型；不证明正式发行包、Windows 原生 OpenClaw Agent、逐调用因果、更新或审批恢复。

2026-09-19 OpenClaw 更新/移除增量：同一 `eac2a99` 候选的本地 V1→V2 旅程完成 31 项检查（80.08 秒）：取消与未确认不改旧版本、内容漂移/伪造签名拒绝、更新撤销旧 Grant/SEC、新版本明确重新授权后真实读取、安全移除及未知用户文件保留。独立核对安装目录消失、三个自定义文件和哨兵不变、受管插件卸载及无自有进程残留。见 [完整结果和前三次失败](evidence/personal-experience/windows-sunbo/openclaw-update-eac2a99-20260919/report.json)。本机 OpenClaw 2026.9.4 的新会话实测路径为公开 `--session-key agent:<agent>:<new-key>`，先完成不调用工具的一轮以建立原生 epoch，再申请该实际会话的 SEC；单用旧脚本的 `--session-id` 路径缺少钩子必需元数据，继续拒绝。没有改写宿主会话库、伪造 epoch 或放宽 Authority。前两次为验证脚本在 Agent 配置前查询目录失败，第三次在新会话元数据检查失败；最终修正夹具顺序与公开会话入口后通过。该结果不覆盖云端更新源、双操作者并发、原生 hold 审批恢复或正式发行包。

## 历史固定源码与已有检查

- 实现候选：`494464ea9f3cff90be4dc0ceac0dd5980c464617`。Windows amd64 自建二进制 SHA256：`ad7680ba64672c9abbaab341ecebea4946e317e2fc3c6160cb5a0ade7e6d9d16`。已有干净候选构建退出 0。
- 收口前分支 head：`1b54d048874e072a5c39a0d07b6e1c4878ba6500`；与实现候选相比只有 Hermes r3 的四份证据文件，产品源码和嵌入 UI 未变化。这是上批材料的状态，本轮修复已产生上述新实现候选。
- 最近 UI 类型检查和本地嵌入构建退出 0，输出已纳入 494464e。沿用已有定向 Go/Web/合同检查与各批四目标构建记录，不将不同历史候选拼为最终全通过。
- Hermes 正式接入/自检 r3 的独立核查已通过；r1/r2 原失败保留。材料见 `docs/evidence/personal-experience/windows-sunbo/hermes-product-runtimecheck-20260918-r3/`。
- 1b54d04 的 PR CI 为 38 成功、2 跳过、2 失败。两个失败 job 均在 `internal/skillmanifest` 的三项测试遇到旧发布清单与实际 Skill 内容摘要不符；仍是实际失败，未删除或放宽测试。
- Windows 全量 Go/相关 race 的历史失败及超时尚未由最终候选全量回归关闭。本轮收口不重新启动完整测评；这些结果不能写为通过。

## 未测与外部依赖

运行接线复查：安装内容复验已另按服务端实际 5 秒期限检查，用户级 2.76 秒、项目级 2.90 秒均通过，见 [期限检查](evidence/personal-experience/windows-sunbo/workbuddy-desktop-2d5ee6c-20260919/skill-runtime-budget.json)。它不能证明完整 HTTP 链或原生加载。该次复查发现界面缺少签发/撤销操作入口，已在本文开头的 eac2a99 增量补齐；服务端已有 `POST /v1/skill-contexts`、`GET /v1/skill-contexts/{id}` 和 `POST /v1/skill-contexts/{id}/revoke` 管理接口。离线 `skill-context` 命令的安装解析只接 Hermes，不能作为 WorkBuddy/OpenClaw 替代入口。界面接线与正式 HTTP 夹具已完成；尚不能据此宣布完整原生用户旅程通过。

1. 三宿主完整原生旅程及统一最终候选验收未完成。现有固定 303 项台账为 78 通过、3 失败、5 受阻、217 未测；属于各自证据范围，不是本次交付候选覆盖率。其他 OS 和 WSL2 保持各自标记。
2. WorkBuddy 已完成本轮授权的最小桌面保护闭环，累计 4/5 个任务。最新 [18 行候选矩阵](evidence/personal-experience/windows-sunbo/workbuddy-desktop-2d5ee6c-20260919/matrix.json)只填入有实机证据的三项；结构/摘要校验退出 0，完整原生门槛退出 3。其他宿主的历史证据没有改绑到新候选，完整审批与 Skill 旅程不因此标绿。
3. `productionGitFetch` 按 ADR-0051 保持关闭，等待真实托管网络安全验收。HTTPS ZIP、本地目录及本地 ZIP 路线保留；不通过开放环境开关绕过这一门禁。
4. 新正式发行清单需要受授权签名流程。旧发行清单、签名和信任根保持不变，不用测试签名冒充正式发行；当前 PR 不具备发布或合并放行结论。
5. 第二 Windows 登录身份、可追溯的受支持旧版本及另一台同 OS 复跑/维护者接受分别保留为外部或待验事项。
6. 用户禁止系统重启、注销、关机和睡眠/休眠；相应系统中断项单列排除，不记通过。没有因此放宽服务失联、撤销及 fail-closed 行为。

## 工作区与交付边界

交付沿用 PR #83，基于 PR #82 的 Windows 私密状态分支；维护者应保留依赖顺序。只提交本轮相关材料，不写 main、不合并、不发布或修改治理。

原工作树的 `apps/agentshield/cmd/agentshield/launch_agent_switch_test.go` 未验证修改，已在后续仓库整理中原样归档到本地 `codex/windows-deferred-launch-fixture-20260918`（`3f7bbcfe43f2d8aa3d09dac168ea5edcb71b3e21`），并从主集成工作树移开。它不进入本次交付候选，不当作已完成的全量测试修复。分支、Issues 和 PR 的最新组织见 [Windows 协作索引](windows-branch-pr-status-20260918.md)。

上一批 Hermes r3 的自有进程/Job 清理已有记录；被暂停的 A05 草稿没有启动宿主、服务或模型。该历史收口批次没有新增宿主进程、系统任务或修改日常配置；本轮新增 Hermes 隔离调用及清理结果见上方，未修改日常配置。此前失败和清理证据不覆盖、不删除。

给合伙人的结论：Windows 三宿主及共性功能已汇集在同一实现分支，可按现有 PR 审阅；本轮交付侧重功能实现与集成。完整原生验收、正式签发和上述外部事项仍有明确限制，不能对外表述为所有 Windows 测试通过或正式发布就绪。
