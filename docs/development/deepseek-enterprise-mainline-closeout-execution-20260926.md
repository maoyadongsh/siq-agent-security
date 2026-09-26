# DeepSeek 企业主线剩余开发与最终收口——连续执行记录

日期：2026-09-26 起。执行者：DeepSeek。主仓：`/home/maoyd/siq/siq-agent-security`。
任务书：[deepseek-enterprise-mainline-final-closeout-taskbook-20260926.md](deepseek-enterprise-mainline-final-closeout-taskbook-20260926.md)。

本文件是本轮 R00–R09 的**唯一**连续执行记录。状态枚举：`todo / doing / blocked / verified / delivered`。
`verified` 必须注明限定环境（合成/隔离/真实）。本文件不把任何 CL/ENT 改判为完成。

---

## R00：接管、去重与最小基线

**状态：doing（本记录落盘时）**。对应 CL-01；ENT-001、003、020。

### R00.1 事实源阅读（已完成）

已直接阅读：

- `/home/maoyd/siq/AGENTS.md`（工作区边界、合同变更矩阵、测试矩阵、完成定义）
- `AGENTS.md`（仓库指南：安全不变量 1–12、测试要求、提交格式）
- `docs/development/current.md`
- `docs/development/enterprise-auto-onboarding-taskbook-20260925.md`
- `docs/development/enterprise-auto-onboarding-closeout-20260926.md`
- `docs/development/enterprise-permission-coverage-closeout.md`
- `docs/development/enterprise-source-freeze-preflight-handoff.md`
- `docs/development/enterprise-auto-onboarding-progress-20260925.md`（批次索引 + Batch148–187 正文）

未读取任何密码、私钥、真实 `.env` 或设备秘密正文。

### R00.2 工作树路径级枚举（已完成，只读）

工具：`scripts/enterprise-experience/source-freeze-preflight.py`（复用既有冻结前工具，未新建）。

```bash
python3 scripts/enterprise-experience/source-freeze-preflight.py \
  --repo /home/maoyd/siq/siq-agent-security \
  --out /tmp/siq-r00-preflight-Yt2nry/report.json
```

结果（报告在仓库外，`/tmp/siq-r00-preflight-Yt2nry/report.json`，exit **1 / blocked**）：

| 项 | 值 |
| --- | --- |
| 合同/工具版本 | `siq-source-freeze-preflight/v1` / `source-freeze-preflight/0.1.0` |
| HEAD | `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0` |
| 分支 | `main` |
| Git 状态条目（`-uall`） | **813**（已跟踪改动 105 = M 98 + D 7；未跟踪 708） |
| 未解决冲突 | 0 |
| 扫描稳定性 | `scan_stable=true` |
| blocking_reasons | `unreviewed_paths:813` |
| `signed`/`installable`/`published` | 恒 `false` |

与任务书 §2.1 盘点时点（105 / 557 路径记录）相比：已跟踪改动数一致（105），未跟踪**路径记录**从 557 升至 558（目录折叠口径）/708（`-uall` 口径），差异属正常漂移，不是任务数或完成率。

按顶层目录分布（`-uall` 813 条）：`apps` 379、`docs` 153、`edge` 120、`packages` 83、`scripts` 42、`connectors` 32、仓库根与 `skills` 4。

**7 条删除已逐条核对**：全部位于 `apps/agentshield/internal/ui/embedded/assets/` 的带内容哈希 JS 产物（DemoPage / InstalledSkillsPage / SkillImportsPage / SkillUpdatesPage / TaskActivitiesPage / TaskActivityDetailPage / index.local），对应新哈希文件已作为未跟踪文件存在，并新增 `PermissionCenterPage-DG-OBECu.js`；同目录 `index.html` 为已修改。**判定：内嵌 UI 构建产物的哈希换代，非功能删除**，但按预冻结口径仍需在 R07/R08 由源重新构建并纳入允许清单，不得直接信任当前产物。

### R00.3 并行作者核查（未取得独占，按门槛处理）

`ps -eo pid,etimes,user,args` 观察到本机存在其他在途会话：

- Codex 应用服务进程（约 28 小时）；
- 另一 Claude Code 会话（模型 `glm-5.3-flash`，约 5.6 小时）；
- 本会话（`deepseek-flash`）。

仓库内最近 3 小时**无任何源码文件改动**，最后一次源码改动时间为 14:53（`apps/web/src/api/changeExecution.ts` 等）。按任务书 §3.1，时间戳与 git status **不能**单独证明独占。因此：

- 本记录不宣称独占接管；**并行接管**列为门槛项（见 R00.6）；
- 处置：不覆盖任何冲突文件，先推进不与其他会话共享的路径；每个 R 单元动工前记录「允许文件清单 + 基线差异」。

### R00.4 模块 → 责任线 → 最新合同 → 复核结论 → 剩余动作（索引）

来源：上述八份必读文档 + 四个只读检索线的源码核对。**只读核对，不是新增执行测试。**

#### A. 安装与持续发现（原责任线 CL-02，本轮 R01）

| 模块 / 文件 | 最新合同 | 复核结论 | 剩余动作 |
| --- | --- | --- | --- |
| `edge/agent/setup_enterprise_linux.go` | `enterprise-install-plan.v1.schema.json`、`enterprise-install-interactive.v1` | 五阶段编排（prepare→register/recover→confirm→schedule→install）已接线；周期阶段仅限已注册身份（:229-233） | 新设备注册后取得组织周期意图的衔接（R01 主缺口） |
| `edge/agent/serve.go` | `enterprise-discovery-schedule.v1.md` | 首扫心跳 + 周期心跳 + 任务领取已接线，共享任务锁 | 原生 systemd 生命周期、升级/断网留 R09 |
| `edge/agent/discovery_schedule_retirement_cli_linux.go` | `enterprise-discovery-schedule-retirement.v1.md` | 子项完成，§8 修复预览失败关闭；未提交 | 历史副本已写但标记未发布的中断场景仍拒绝再准备（需人工处置） |
| `apps/control-api/app/install_plan.py`、`routers/install_plans.py` | `enterprise-install-plan.v1` | 已接线；目录来源依赖 `SIQ_AS_INSTALL_CATALOG_FILE`，仓库内无 catalog 文件 → 未配置即 503 | 部署配置（外部资源门槛） |
| `apps/control-api/app/routers/discovery_schedules.py`、`discovery_schedule_confirmation.py`、`discovery_scheduler.py` | `enterprise-discovery-schedule.v1`、`-management.v1` | 管理 GET/POST/revoke、设备 confirm/tick、预约事务、迁移 0028 全链已实现 | 确认日志换代；组织侧为新注册设备创建绑定计划的闭环 |
| `edge/agent/discovery_schedule_poll_linux.go` | 同上 | 轮询取消修复子项完成 | `initial_scan.go` 成功返回后的取消检查未覆盖（已单列 CL-02-INITIAL-SCAN-CANCEL） |

#### B. 框架—角色—Skill 关系（原责任线 CL-03，本轮 R02）

| 模块 / 文件 | 最新合同 | 复核结论 | 剩余动作 |
| --- | --- | --- | --- |
| `connectors/openclaw/{skill_selection,skill_roots,framework_source,json5,config_parse}.go` | `enterprise-openclaw-skill-selection.v1`、`enterprise-role-skill-roots.v1`、`enterprise-framework-source.v1` | 原生合同验收子项完成（§10 修复夹具完整性；原 8 类非法 scope 全 `valid=true` 已修） | 真实 OpenClaw 版本兼容；AMD64/macOS/Windows 原生 |
| `connectors/hermes/hermes.go` | `enterprise-framework-source.v2`、`enterprise-role-skill-roots.v2`、`hermes-profile-origin.v2` | 原生协议子项完成（截断缺陷已修）；`computeCursor` 16 MiB 有界摘要未升级为完整文件指纹 | 同上；建议把 `hermes-native-contract-check.py` 纳入 R07 门禁 |
| `apps/control-api/app/{framework_source,role_skill_selection,role_skill_roots}.py` | 同上 v1/v2 | 入库校验已接线（`routers/inventory.py`） | — |
| `apps/control-api/app/routers/role_skill_sources.py` | `enterprise-role-skill-sources-view.v1/v2`、`enterprise-role-skill-snapshot-comparison.v1` | 双只读端点已接线；Hermes 路径按 `asset.framework` 选 v2 | **合同缺口**：:168 会输出 `snapshot-comparison/v2`，前端也接受 v2，但 `packages/contracts/` 只有 v1 文件 |
| `apps/web/src/api/roleSkill*.ts`、`components/inventory/Role{SkillSelection,SkillSources,ConfigurationHistory}Panel.tsx`、`components/framework-tree/`、`components/role-skill-snapshot-comparison/` | 同上 | 已挂载 `AgentDetailPage` / `AgentsPage`；框架树只读、无技能节点 | 精确角色—Skill 关系（见下） |

**R02 根本未实现（合同已声明边界，不得以改名销项）**：不存在「精确安装 / 实际加载」关系。`relationship_status` 仅能为 `unresolved / historical_source_match / outside_declared_sources`，判据是 Directory 扫描 `ancestor_sha256` 是否包含声明根摘要；`runtime_status=unverified`、`effective_permissions=null` 恒成立。目录解析只覆盖 OpenClaw 两个工作区目录（v1）与 Hermes `HERMES_HOME/skills`（v2）；共享来源、多层技能目录、`~`/变量/相对路径、Hermes `external_dirs` 与受信任项目来源、加载层优先级裁决均未实现。

#### C. Linux/DGX/OpenShell 拓扑与运行绑定（原责任线 CL-04，本轮 R03、R04）

| 模块 / 文件 | 最新合同 | 复核结论 | 剩余动作 |
| --- | --- | --- | --- |
| `edge/agent/host_inspection{,_linux}.go` | `enterprise-host-inspection.v1` | 只读识别已实现 | 用户填写标签 vs 硬件证据的展示分离（R03） |
| `connectors/{process,systemd,docker,kubernetes}/*.go` | — | 通用采集器存在、可复用 | 获准范围内的证据拓扑投影（R03） |
| `apps/control-api/app/adapters/openshell/*`、`app/openshell_sync.py` | `openshell-policy-safety.v2`、`enterprise-openshell-connection.v1` | 真实只读预览（E149）与真实沙箱下发/撤销/回滚（E151）已验证 | 仅达 `readback_verified`；`enforcement_verified` 无生产者；网关拒绝事件流未打通 |
| `apps/control-api/app/binding_identity.py` | `enterprise-runtime-binding-identity.v1` | `require_binding_identity_unchanged` 已接入 policies/impact/preview 四处；吊销→409、漂移→409 为真实现 | 快照仅 6 字段（status/env/asset/agent_instance/backend/backend_target）；沙箱 revision 与 Skill 摘要未进入 |
| `apps/control-api/app/binding_evidence_readiness.py` | `enterprise-binding-evidence-readiness.v1/v2` | 模块存在，五维只读评估 | **无任何生产调用方**，仅测试引用 |
| `apps/control-api/app/routers/deployment_impact.py` | `enterprise-deployment-impact.v1` | :46-49 硬编码 `coverage="registered_binding_only"`、`shared_runtime_occupants="unknown"`、`skill_isolation="not_established"`、`execution_confirmation_supported` 类型为 `Literal[False]` | 共享影响与独占标准待业务决策；**不得擅自改 true** |

> 注：任务书给出的 `adapters/openshell/` 顶层路径**不存在**；OpenShell 实现分两处——`apps/control-api/app/adapters/openshell/`（Python 控制面）与 `apps/agentshield/internal/openshell/`（Go 本地）。

#### D. 批量权限到可核对结果（原责任线 CL-05，本轮 R05）

| 模块 / 文件 | 最新合同 | 复核结论 | 剩余动作 |
| --- | --- | --- | --- |
| `apps/control-api/app/batch_reservation.py` | `enterprise-batch-reservation.v1` | 原子预留先落库再执行 | — |
| `apps/control-api/app/routers/deployment_batch_{draft,execute,result}.py` | `enterprise-batch-draft.v1`、`enterprise-batch-execution.v1` | 草稿 / 显式执行 / 逐项结果回读重验均已接线 | — |
| `apps/web/src/api/deploymentBatch.ts:126` `executeBatchDraft` | — | **无生产调用方**（仅测试 3 处）；`BatchDraftPanel.tsx` 只导入 create/read/readResult，注释明确 "Never executes" | 完整影响披露接通后才可接执行入口 |
| `apps/control-api/app/deployment_verify.py` | — | 独立读回 `verified/unreachable/mismatch/no_receipt`；§10 复核修复 no_receipt/unreachable 误报 | `expect_deny` 恒空 → 行为核验无生产者 |
| 前端 `ui/verification.ts` | — | 被 permission-facts 组件消费 | 保留态映射一致性复核 |

#### E. 审计与治理（原责任线 CL-06，本轮 R06）

| 模块 / 文件 | 最新合同 | 复核结论 | 剩余动作 |
| --- | --- | --- | --- |
| `apps/control-api/app/routers/audit.py`、`ocsf.py` | `enterprise-audit-query.v1` | 精确查询 + wire 联测 + OCSF 导出已实现 | 完整版本链（设备→角色/Skill 版本→运行身份→审批/策略→执行/回执→效果）未闭合 |
| 保留 / 删除 / 导出治理 | — | 未实现 | **业务决策门槛**；未决定前不删除任何历史 |

#### F. 发行与文档（原责任线 CL-08，本轮 R08）

| 模块 / 文件 | 复核结论 | 剩余动作 |
| --- | --- | --- |
| `scripts/release/{enterprise_candidate,enterprise_finalize,verify,package,readback}.py` | 候选/签后组包与独立验签存在 | 正式签发需受控入口与可信公钥（外部门槛） |
| `scripts/enterprise-experience/source-freeze-preflight.py` | 冻结前只读盘点，§9 复核已修 | 允许清单需按责任线逐文件填写（R08） |
| `README.md` / `README.en.md` | 与实现存在滞后描述（如「注册恢复尚未接通」） | R08 同步，不填虚构下载地址 |

### R00.5 窄基线验证（已完成，**不是**全量门禁）

R00 只做小范围验证；全量留到 R07。

| 命令 | 结果 |
| --- | --- |
| `apps/control-api/.venv/bin/python -c "import app.main"`（无 `SIQ_AS_DEV`） | 失败关闭：`RuntimeError: 生产模式必须配置 SIQ_AS_DATABASE_URL` —— **符合安全不变量 7，不是缺陷** |
| 同命令加 `SIQ_AS_DEV=1` | `import app.main OK`，路由 40 条 |
| `git status --porcelain=v1 -uall \| wc -l` | 813 |
| `edge/agent`：`go vet ./...`（go1.26.5 linux/arm64） | exit 0 |
| `pytest -q test_binding_evidence_readiness.py test_discovery_schedule.py test_discovery_scheduler.py test_binding_execution_recheck.py test_discovery_schedule_tick.py`（`SIQ_AS_DEV=1`） | **99 passed**，无失败 |

未执行：全量后端、前端构建与测试、Edge race、迁移回放、浏览器验收、真实数据库。这些属 R07。

### R00.6 缺口分类与需主开发者/用户决策的门槛

按任务书要求区分四类：**代码缺口 / 集成证据缺口 / 真实资源缺口 / 业务决策缺口**。

| # | 门槛（任务书 §7 行） | 具体问题 | 未确认时行为 |
| --- | --- | --- | --- |
| D-1 | 并行接管 | 仍在写本仓的 Codex / GLM 会话各自负责哪些文件、何时交接？ | 不覆盖冲突文件，继续不冲突单元 |
| D-2 | 后端新增表达能力（R01） | 组织侧如何为新注册设备表达周期意图：A 环境级默认周期意图（新语义）／B 设备侧「我的待确认计划」查找端点（最小，仍需本机再确认）／C 维持现状（管理员建计划后人工传 ID） | 保持只读，不自动激活、不隐式授权 |
| D-3 | 共享影响 / 运行事实（R04） | 完整覆盖 / 独占的判定标准与独立来源；无法单独隔离 Skill 时的处理 | 保持 `unknown`，执行确认继续禁止 |
| D-4 | 证据时效 | 是否存在有效期、如何失效与复验 | 不自行设 TTL，不把历史观察当实时 |
| D-5 | 保留治理（R06） | 保留期限、法律保留、允许删除对象及授权流程 | 不删除、不自动清理、不假称治理完成 |
| D-6 | 原生验证 + OpenShell 目标（R09） | ARM64/AMD64、第二设备/租户、独立审批者、受控 OpenShell 测试目标 | 仅隔离合成验证，不借交叉编译销项 |
| D-7 | 发行与部署（R08/R09） | 精确提交清单、签发入口引用、发布目的地与回滚方案 | 不提交、签发、发布或切换 |

另需外部资源（非代码）：安装目录 catalog 文件（`SIQ_AS_INSTALL_CATALOG_FILE`）未部署 → `install-options` 返回 503。

### R00.6a 已取得的决策（2026-09-26，主开发者确认）

| # | 决策结论 | 对本轮实施边界的约束 |
| --- | --- | --- |
| D-1 | **只写新增文件** | 不修改任何既有实现文件（`routers/`、`edge/agent/`、`app/main.py`、既有 `packages/contracts/` 正文档名之下新增版本导航行属文档追加，见下）。既有 105 处已跟踪改动与 708 处未跟踪文件均视为并行会话在途产物，不覆盖、不回退、不清理。 |
| D-2 | **设备侧待办查询端点（最小路径）** | R01 只新增只读枚举端点，不引入环境级默认周期意图、不自动激活、不降低设备签名确认强度。 |
| D-3 | **保持 `unknown` 不猜** | R04 不新增共享/互斥判定来源；`shared_runtime_occupants=unknown`、`skill_isolation=not_established`、`execution_confirmation_supported=false` 全部维持原值。 |
| D-5 | **只补齐声明与缺口** | R06 不新增保留执行器、不新增删除/归档路径；只把「声明 180 天但无运行时读取者」写入交付与交接。 |

D-4（证据时效）、D-6（原生验证与 OpenShell 目标）、D-7（发行与部署）**仍未确认**，对应 R07/R08/R09 保持只读或阻塞。

D-1 的执行口径说明：本轮对 `packages/contracts/` 既有文件仅做**追加式版本导航段**（仓库既有惯例，如 `enterprise-role-skill-snapshot-comparison.v1.md`、`enterprise-discovery-schedule.v1.md`），不删改任何既有正文；对 `apps/control-api/app/main.py` 等实现文件**零改动**——新端点因此当前对外不可达，接线作为独立的、可随时执行的待办项登记在交接文档。

### R00.6b 后续决策（2026-09-26，同一轮；覆盖 R00.6a 的相应行）

**R00.6a 保留原文不回溯修改**，本小节记录其后取得的答复。**四项答复都发生在 R08 冻结前盘点完成、D-7 请求正式提出之后**。

| # | 后续答复 | 对实施的影响 |
| --- | --- | --- |
| D-1（修订） | **全部放开**（例外授权） | 允许修改既有实现文件。据此实施三处最小改动：R01 接线（R01.5）、R05 非 openshell-cli 回滚授权链重查（R05.5）、R07 两个既存后端缺陷（R07.8），共涉及 **5 个文件**（4 个已跟踪 + 1 个未跟踪），全部登记进冻结允许清单第四节。**"独立回滚审批"明确不在本次授权范围内**（属业务决策）。 |
| D-6（部分） | **数据库容器、真实 Linux 实机、受控 OpenShell 目标可用** | 这三项资源可用，但**本轮未开始使用**：按 §3.2，启动数据库容器或真实系统服务前须先说明**隔离方式、目标与回收方案**并取得该次许可。ARM64/DGX、第二设备/租户、独立审批者、Mac 浏览器访问远程 Linux **仍未确认**。 |
| D-7.1 | **提交到新分支**（不动 `main`、不推送） | 本轮 26 条路径提交到新分支；`main` 的 `ebaaf3b` 仍不含本轮成果。 |
| D-7.4 | **保留合同追加段** | R02 在三个既有合同件末尾追加的"版本导航"段**保留**，D-1 字面偏差作已确认的例外登记。 |

**D-7.2（推送/发 PR）、D-7.3（806 条 unreviewed 路径归属）、D-7.5（签发）、D-7.6（部署）、D-4（证据时效）仍未确认**。

### R00.7 余项表（出口物）

「下一动作」分为两类：**代码动作**（本轮可执行）或**外部门槛**（需授权/资源/决策）。

| 单元 | ENT | 主要缺口 | 类型 | 下一动作 |
| --- | --- | --- | --- | --- |
| R01 | 002,004-007,017,021 | 新设备注册后无法安全取得组织周期意图（`setup_enterprise_linux.go:229-233` 仅限已注册身份，设备 GET 无列表/自动选择，组织 POST 要求设备已存在 404） | 代码 + **决策 D-2** | 先出最小合同决策，再接线；其余（CLI/串行/回执/换代）已实现 |
| R01 | — | `initial_scan.go` 成功后取消检查未覆盖 | 代码 | 已单列 CL-02-INITIAL-SCAN-CANCEL |
| R02 | 008,009,011,018 | 无「精确安装 / 实际加载」关系；目录解析覆盖窄 | 代码 + 真实来源决策 | 先补 `snapshot-comparison.v2` 合同缺口，再按框架声明语义收口 |
| R02 | — | `enterprise-role-skill-snapshot-comparison.v2` 合同文件缺失 | 文档/合同 | 本轮可直接补（只读核对后写） |
| R03 | 006,010,012 | 无「视角（宿主/容器/远程）+ 不可读原因」投影；模型识别只有名称级 | 代码 | 隔离夹具证明视角与来源边界 |
| R04 | 013,014 | 五维证据缺权威生产者；共享影响/独占标准未定；TOCTOU 窗口未消除 | 代码 + **决策 D-3** | 先定生产者与标准，禁止填 verified；`execution_confirmation_supported` 保持 false |
| R05 | 014-016,018 | `executeBatchDraft` 无调用方；行为核验 `expect_deny` 恒空；回滚审批/过期边界未收口 | 代码（依赖 R04）+ 资源 | 前置具备前保持只读 |
| R06 | 019 | 完整版本链引用缺失；保留/删除/导出治理未实现 | 代码 + **决策 D-5** | 复用现有详情提供正反向可达；不新增聚合接口扩大读取 |
| R07 | 001,003,020,022 | 未在同一候选上跑统一门禁；旧 wire 样本需重生成 | 集成证据 | 待 R01–R06 收束后集中执行 |
| R08 | 004,021,022 | 未冻结、未提交、未签发；允许清单未填 | 集成 + **决策 D-7** | 复用现有发行工具，列授权请求 |
| R09 | 002,005,012,016,021,022 | 无真实设备/身份/原生平台证据 | **真实资源** | 需先取得目标、身份、范围、备份与恢复授权 |

**不把上述任何一项归为「上线待办」**；每项均有明确的下一代码动作或准确的外部门槛。

### R00.7a 余项表状态更新（滚动）

上表为 R00 时刻快照，不回溯修改。滚动状态：

| 单元 | 变化 | 现在状态 |
| --- | --- | --- |
| R01 | D-2 已决策（最小路径）；新增只读枚举端点 + 合同 + 8 用例（含 1 条接线用例），同组 75 用例回归通过；D-1 放开后完成接线 | 源码完成 + 隔离验证通过；**已接线**（`app/main.py:37/182`），CLI 侧未接 |
| R05 | 缺口 3（回滚授权链接查）经 D-1(b) 实施：两条分支共用 `_rollback_live_chain`，断链 → 409 + 零写入；4 条新用例 + 反证 | 缺口 3 的"非 openshell-cli 半边"源码完成 + 隔离验证通过；**独立回滚审批仍缺**（业务决策），缺口 1/2/4 不变 |
| R07 | D-1(a) 修掉两个既存后端缺陷后，后端全量 **2164 passed / 1 skipped / 0 failed** | `backend_full_suite` 不再恒红；统一门禁预期收敛到 `gates_incomplete`（3 条声明不可用门禁恒 `skipped`），**永不为"全绿"** |
| R08 | 允许清单由 21 条扩到 **26 条**（纳入 D-1 例外改动的 5 个文件）；preflight 最近一次 `26/26 verified`，唯一阻塞 `unreviewed_paths:806`；已按 D-7.1 提交到新分支 | 准备与核验完成；**冻结/签发/发布仍不可能由执行者自行完成** |
| R02 | `snapshot-comparison.v2` 合同缺口已补齐并逐行核对实现；"安装/实际加载关系"与"目录解析覆盖"仍缺 | 部分源码完成 + 只读核对；两项仍 todo |
| R02（合同行） | 该行已完成 | 关闭 |
| R04 | D-3 已决策：保持 `unknown` 不猜 | 硬约束确认生效，`execution_confirmation_supported` 维持 `Literal[False]` |
| R06 | D-5 已决策：只补声明与缺口 | 范围锁定为只读引用 + 缺口声明，不做删除/归档 |

### R00.8 本轮工时区间估算（按已识别修改面）

- **开发工时（可不等授权）**：R02 合同缺口 + R06 只读引用 + R03 视角边界夹具 + R01 决策后接线，合计约 **3–6 个工作日**量级；R04/R05 取决于 D-2/D-3 决策与来源是否可得。
- **等授权 / 等资源时间**：不计入上述区间，单列 D-1、D-2、D-3、D-5、D-6、D-7。

该区间随真实结果修订，不使用完成百分比。

---

## R01：普通安装到新设备计划及持续发现衔接

**状态：doing**。对应 CL-02；ENT-002、004–007、017、021。

### R01.1 当前事实（源码确认）

- `edge/agent/setup_enterprise_linux.go` 已实现五阶段编排，且阶段顺序为 prepare → register/recover → confirm → schedule → install；周期失败停在服务安装之前，语义正确。
- 周期阶段被显式限制为**已注册身份**：

  ```go
  // Organization-created schedules are bound to an already registered device.
  // Do not partially register a new identity before discovering an unusable ID.
  if scheduleAction != nil && kind != "registered" {
      return errEnterpriseSetup
  }
  ```

- 设备侧只能按 ID 取回单一计划：`GET /edge/v1/discovery-schedules/{schedule_id}`，合同明确「**不提供列表或自动选择**」。
- 组织侧创建要求设备已存在：`POST /api/v1/environments/{environment_id}/discovery-schedules` 先按 `intent.device_identity` 定位设备，不存在即 404。
- 合同自述：「新设备首次注册尚需后续组织侧创建其绑定计划，不能将此可选编排称为全自动注册到周期启用。」

**结论**：R01 主缺口成立且已定位到准确判据，不是文档口径问题。

### R01.2 已取得决策（D-2 → 设备侧待办查询端点）

三条路径的产品语义差异见 R00.6，主开发者已选**最小路径**：只新增设备侧只读枚举端点，不引入环境级默认周期意图、不自动激活、不降低确认强度。

### R01.3 本轮实施（源码完成 + 隔离验证通过）

| 项 | 内容 |
| --- | --- |
| 新增代码 | `apps/control-api/app/routers/discovery_schedule_pending.py`（新文件；**已于 R01.5 接入 `app/main.py`**） |
| 新增合同 | `packages/contracts/enterprise-discovery-schedule-pending-list.v1.md`（新文件） |
| 新增测试 | `apps/control-api/app/tests/test_discovery_schedule_pending.py`（新文件，7 用例） |
| 既有文件改动 | 仅 `packages/contracts/enterprise-discovery-schedule.v1.md` 末尾追加版本导航段（无正文删改） |
| 迁移 | 无 |

端点：`GET /edge/v1/discovery-schedules`。范围严格限定为**当前认证设备自身**的 `status=pending_confirmation` 行；租户/环境/设备全部从验证身份定位，不接受客户端指定，因此不存在跨租户或跨设备枚举入口。白名单投影只含 schedule_id / status / revision / intent / intent_digest，与既有按 ID 读取使用**完全相同**的 `require_binding` 与投影一致性校验。

**与既有语义的唯一行为差异**：本页内无法通过校验的行不返回 409，而是列入 `integrity_failed` 且不投影其内容，分页继续推进。理由已写入合同：按 ID 读取只针对单行，失败应当 409；枚举端点若同样失败则一行损坏会让其后所有待办永久不可达。两种处理都不静默把损坏行当作"没有待办"。

**只读保证**：不创建运行绑定、扫描、任务、预约、权限、审计或其他业务写入，不激活、不恢复、不确认、不派发；无新增数据库迁移。**枚举不等于授权**——列出的计划仍需设备按既有 `POST /edge/v1/discovery-schedules/confirm` 完成 Ed25519 签名确认才生效，未引入任何"设备自动采纳"路径。

**实测命令与结果**（合成设备、临时密钥、独立 SQLite；不读真实 env/私钥）：

```text
cd apps/control-api
.venv/bin/python -m pytest app/tests/test_discovery_schedule_pending.py        → 7 passed
.venv/bin/python -m pytest app/tests/test_discovery_schedule_{pending,confirmation,management,tick}.py \
                              app/tests/test_discovery_scheduler.py            → 75 passed（同组回归无退化）
.venv/bin/ruff check app/routers/discovery_schedule_pending.py \
                     app/tests/test_discovery_schedule_pending.py              → All checks passed
```

用例覆盖：设备范围锁定与只读性（计划/任务/轮次/审计计数不变、枚举后计划仍为 `pending_confirmation`）、同设备 `active` 计划不进待办列表、三类认证拒绝（缺凭据/错 secret/未知身份）、损坏行进 `integrity_failed` 且不投影、损坏行之后分页仍可推进。

### R01.4 未完成与依赖

- ~~**待接线**：`app/main.py` 未注册本 router，端点对外不可达。~~ **已由 R01.5 完成接线，端点可达已验证。**
- **未做**：设备侧 CLI 的交互式发现（`confirm-discovery-schedule` 目前只有 `--schedule-id` / `--intent` / `--resume` 三选一，没有"列出我的待办"入口）。端点已具备，CLI 侧接线属后续可执行代码动作。
- **不承诺**：本单元不改变组织侧创建时序（新设备仍需组织侧在其注册后创建绑定计划），R01 的"安装→持续发现联动"只补齐了**设备侧可发现性**这一半。
- **范围**：源码完成 + 隔离验证通过。不代表真实设备已获得周期发现，不代表原生安装旅程已验收。

### R01.5 接线实施（D-1(c)，2026-09-26）

**状态：source complete + isolated verified（**不是**实际交付）**。改动仅两处纯追加：

| 文件 | 改动 |
| --- | --- |
| `apps/control-api/app/main.py:37` | router 导入元组新增 `discovery_schedule_pending,` |
| `apps/control-api/app/main.py:182` | `include_router` 元组新增 `discovery_schedule_pending.router,` |

**接线为何需要独立证据**：本文件其余 7 条用例挂在**独立 app**上（`create_app` 风格的最小应用），只能证明 router 自身行为，**证不了它被 `app.main` 注册**——正是"新增文件却不接线"这类缺陷的常见逃逸口。故新增第 8 条用例 `test_endpoint_is_wired_into_the_real_app`：走**共享的真实 app**，缺设备凭据时断言**不是 404**（404 即意味着接线掉了），并钉住实测命中的固定码。

**证据（命令 → 结果）**：

| 命令 | 结果 |
| --- | --- |
| 路由表检查（`app.openapi()["paths"]`，**不是** `app.routes`） | `/edge/v1/discovery-schedules` GET **已注册** |
| `pytest app/tests/test_discovery_schedule_pending.py` | **8 passed**（7 原有 + 1 接线） |
| 全量 `pytest` | **2164 passed / 1 skipped / 0 failed** |

**踩坑记录（对后来者有用）**：`app.routes` 中包含的是 FastAPI 的**惰性** `_IncludedRouter` 对象（41 项里只有 3 项是 `APIRoute`），直接遍历它看不到后端点，会误判"未接线"。核对路由必须走 `app.openapi()["paths"]`。

---

## R02：精确角色—Skill 关系与版本漂移

### R02.1 合同缺口（已定位、已修复、已核对）

缺口：`routers/role_skill_sources.py:168` 会对 Hermes 输出 `enterprise-role-skill-snapshot-comparison/v2`，前端 `roleSkillSnapshotComparison.ts:12,40` 也接受并校验 v2，但 `packages/contracts/` 只有 v1 文件。同类（roots、sources-view、framework-source）均已有 v2。

**处置与证据**（只读核对后补写，未凭猜测）：v1 与 v2 的差异不是字段，而是快照根声明的可核对条件。已在实现中逐行核对：

- `apps/control-api/app/routers/role_skill_sources.py:173-177` 读取 `snapshot['configuration']['skill_source_roots']`，要求 `roots['status']` 为 `layout_candidate`（Hermes）或 `declared`（OpenClaw），否则返回 `snapshot_unavailable`。
- `apps/control-api/app/routers/role_configuration_history.py:37-50` 是产生该结构的投影：`configuration` 由 `framework_source` + `skill_source_roots` + `task_id` + `batch_digest` 组成，roots 经 `app/role_skill_roots.py::parse_role_skill_roots` 校验（`role_skill_roots.py:19` 要求 `basis='hermes_profile_layout'` 且 `status='layout_candidate'`）。
- 顶层字段两侧完全一致（`role_skill_sources.py:166-172` 无框架分支），故合同把差异精确表述为"仅可核对条件不同，字段相同"。
- 既有 `enterprise-role-configuration-history.v2.md` 已独立记载同一 v1/v2 配对规则，新合同与其一致。

| 项 | 内容 |
| --- | --- |
| 新增合同 | `packages/contracts/enterprise-role-skill-snapshot-comparison.v2.md`（新文件） |
| 既有文件改动 | `.../snapshot-comparison.v1.md` 末尾追加版本导航段（无正文删改） |
| 代码改动 | 无 |
| 迁移 | 无（合同明确写"无新增数据库迁移"） |

### R02.2 仍未完成

- **无「精确安装 / 实际加载」关系**：现有证据只能到"配置里声明了哪些角色/Skill"，不能证明某 Skill 被实际安装或被运行时加载。`binding_evidence_readiness` 已给出原因码 `layout_candidate_is_not_installation_or_load`，但**没有生产者**把"安装/加载"这一维变成可核对事实——需要设备侧采集端提供来源，属代码 + 真实来源决策。
- **目录解析覆盖窄**：`external_dirs` 与受信任项目来源不在 v2 覆盖集合内（已在新合同显式声明，不假装覆盖）。
- **状态**：合同缺口部分为源码完成 + 只读核对；上述两项为 todo。

---

---

## R03：Linux/DGX/OpenShell 证据拓扑

**状态：todo**。对应 CL-04；ENT-006、010、012。

### R03.1 当前事实（源码确认）

- 主机识别：`edge/agent/host_inspection.go` + `host_inspection_linux.go`（`/etc/os-release`、DMI `product_name`、device-tree `model`），合同 `enterprise-host-inspection.v1`。
- 通用采集器均已存在可复用：`connectors/process/process.go`、`connectors/systemd/systemd.go`、`connectors/docker/docker.go`、`connectors/kubernetes/kubernetes.go`。
- OpenShell 适配器分两处（任务书假设的顶层 `adapters/openshell/` **不存在**）：
  - Python 控制面 `apps/control-api/app/adapters/openshell/`（`base/client/cli_backend/bounded_command/policy_compiler/policy_safety/network_change/enterprise_connection/operation_registry/contracts/fake_backend.py`）；
  - Go 本地 `apps/agentshield/internal/openshell/`（`client/command/bounded_command/discovery/gateways/identity/policy/policy_state/runtime_load/task_exec/types/yamlkit/diagnose.go`）。
- 真实链路已有证据：E149 只读预览（真实网关、revision=2、策略 SHA-256 `900e7713…`）、E151 真实下发/撤销/回滚（允许 curl 200/exit 0；撤销 403/exit 22；回滚恢复 200）。

### R03.2 缺口

1. **视角语义缺失**：没有把「宿主 / 容器 / 远程」视角与「不可读取原因」作为一等投影；`host_inspection` 只给名称级信息（`DMI product_name`、`model`），**名称不构成型号识别**。
2. **运行行为证据缺失**：E151 只达 `readback_verified`，未升级 `enforcement_verified`；网关拒绝事件流未打通；`drift.py` 只做「期望 vs 读回」比对，不覆盖网关侧执行行为。
3. 未实现：部署持久恢复；生产身份；多客户端并发；原生平台仅 Linux ARM64。

### R03.3 本轮实施（缺口 1；缺口 2 经核实为**不可由本轮制造**）

| 项 | 内容 |
| --- | --- |
| 新增代码 | `apps/control-api/app/evidence_topology.py`（新文件，内部只读投影，非 HTTP 接口） |
| 新增合同 | `packages/contracts/enterprise-evidence-topology.v1.md`（新文件） |
| 新增测试 | `apps/control-api/app/tests/test_evidence_topology.py`（新文件，10 用例） |
| 既有文件改动 | 无 |
| 迁移 | 无 |

设计要点（对应任务书"证明视角与来源边界，不新增执行桥、不默认扫整机、不读 Docker socket"）：

- **刻意不合并两件事实**：声明视角（`Environment.env_type`）与观测表面（该环境内 `Evidence.source_type` 归类）。两者不一致时报告 `declared_and_observed_conflict`，**不静默取其一、不因同时存在相容表面而降级为一致**。
- **未列出的采集器不猜测归属**：归入 `unmapped` 并报 `connector_perspective_unmapped`，不计入任何表面桶。框架类采集器（hermes/openclaw/piagent/workbuddy/dify/mcp/siq）单列 `agent_config`，**不塞进宿主/容器三视角**。
- **远程视角如实缺席**：`account`（云账号）→ 声明视角 `remote`，仓库内无任何采集器产生远程表面证据，故恒为 `source_absent` 并报 `account_perspective_source_absent`，**不借用宿主/容器表面顶替**。
- **不可读原因是记录事实**：`payload_not_retained`（`payload_ref` 为空，只有元数据可读）与 `evidence_expired`（`expires_at` 已过），只做聚合计数，**不载入 payload 正文**。
- **不生产行为证据**：`enforcement_verified` 恒 `False`；`behavioral_evidence` 恒 `not_established` / `behavioral_fixture_source_absent`。

**关于缺口 2 的结论（修正 R00 时点的措辞）**：`enforcement_verified` 不是"缺一个生产者"，而是仓储内**刻意保留**的值——`app/adapters/openshell/contracts.py:11` 与 `base.py:57` 明确写"需要真实行为 fixture 证据"、`apps/agentshield/internal/openshell/types.go:17` 注释同样保留、`policy.go:627` 声明"pass 永远是 readback_verified"、`openshell-policy-safety.v2.md:118` 记为 reserved，且 `client_test.go:674` 有专门的"不得宣称 enforcement_verified"断言。因此本轮**不制造**该事实，也不提供升级路径；它只能在 R09 的真实行为 fixture 下产生。

**实测命令与结果**（合成租户/环境/证据行，独立 SQLite；不读真实 env/私钥）：

```text
cd apps/control-api
.venv/bin/python -m pytest app/tests/test_evidence_topology.py   → 10 passed
.venv/bin/ruff check app/evidence_topology.py \
                     app/tests/test_evidence_topology.py         → All checks passed
```

用例覆盖：只读（租户/环境/证据/审计/outbox 计数不变）与租户隔离（他租户环境与不存在环境除回显参数外结果完全相同）、相容表面判 `observed_from_records`、无证据判 `declared_only`、容器表面落在宿主环境的冲突不降级、未归类采集器不静默归桶、云账号远程视角无来源、未知 `env_type` 不猜视角、可读性原因、行为证据恒不生产、验证身份必填。

### R03.4 未完成

- 真实 DGX / 容器 / OpenShell 目标的证据拓扑核对：**真实资源缺口**，归 R09（依赖 D-6）。
- 部署持久恢复、生产身份、多客户端并发：未实现，与 R04/R09 相关。
- **范围**：源码完成 + 隔离验证通过。不代表任何真实目标的视角或覆盖已被核对。

---

## R04：绑定版本、失效联动及共享影响

**状态：doing（源码完成 + 隔离验证通过；五维权威生产者与快照扩字段仍缺）**。对应 CL-04；ENT-013、014。

### R04.1 当前事实（源码确认）

- 已接线且为真实现：`binding_identity.py:25` `require_binding_identity_unchanged`，快照字段恰为 6 个（`status, environment_id, asset_id, agent_instance_id, backend, backend_target_id`，`binding_identity.py:10`）；接入 4 处——`routers/policies.py` 的 `execute_deployment`（:600-605）、`routers/deployment_impact.py`、`routers/deployment_preview.py` 单项与批量。吊销→409 `binding_revoked`、来源漂移→409 `binding_source_identity_changed`。
- 已实现但**未接线**：`binding_evidence_readiness.py` 的 `assess_binding_evidence`（:140）无任何生产调用方（`rg` 仅命中自身与其测试）。
- 硬编码、无来源：`routers/deployment_impact.py:46-49`

  ```python
  coverage = "registered_binding_only"
  shared_runtime_occupants = "unknown"
  skill_isolation = "not_established"
  execution_confirmation_supported: Literal[False] = False
  ```

  同为常量者还有 `binding_evidence_readiness.py:190` 的 `"execution_confirmation_supported": False`。
- 吊销合法入口：`POST /api/v1/runtime-bindings/{binding_id}/revoke`（`routers/bindings.py:131`）。
- 各文档一致登记：复验 → `apply_dynamic` 之间**残余 TOCTOU 窗口未消除**。

### R04.2 缺口与约束

- 五维证据（设备 / 角色-Skill 摘要 / 执行身份 / 沙箱 revision / 共享占用）无权威生产者与验证路径；
- 沙箱 revision 与 Skill 摘要未进入绑定身份快照；
- 共享独占标准未定（**D-3**），单条数据库绑定、人工 attestation、用户勾选均不足以证明独占。

### R04.3 硬约束（本轮不得违反）

**不得擅自把 `execution_confirmation_supported=false` 改为 true。** 该值当前在类型层面被限死为 `Literal[False]`，任何改动需先经主开发者复核完整证据与影响合同。不自行增加锁/租约协议或独占性标准来「完成任务」。

### R04.4 本轮实施：绑定失效联动只读投影（缺口之三的只读一半）

**为什么这是本轮可做的最小实现。** R04 的三个缺口里，只有「失效联动」可以在**不改既有文件**（D-1）且**不猜独占标准**（D-3）的前提下落地：缺口一（五维证据无权威生产者）需要真实运行/沙箱/连接身份来源，属 R09 资源门槛；缺口二（沙箱 revision 与 Skill 摘要进入绑定身份快照）必须改 `binding_identity.py` 的 6 字段快照及其 4 处调用方，直接违反 D-1。

**实际缺口（源码确认，非推断）**：`routers/bindings.py:131` 的吊销**不做任何依赖检查**——只置 `status="revoked"` + `revoked_at` + 审计 + `runtime_binding. revoked.v1` 事件，没有级联、没有"谁受影响"的读侧视图。使用点的拒绝只来自 `require_binding_identity_unchanged` 的固定码 `binding_revoked`。也就是说：**吊销的后果是"到用的时候才发现"，事前无从核对**。

本轮改动**全部为新增文件，既有实现零改动**（D-1）：

| 文件 | 内容 |
| --- | --- |
| `apps/control-api/app/binding_invalidation_surface.py` | `project_binding_invalidation_surface(session, identity, binding_id, draft_scan_limit=200)` 内部只读投影 |
| `packages/contracts/enterprise-binding-invalidation-surface.v1.md` | 合同：两类引用的覆盖差异、五值状态词表、吊销固定结论集、刻意不改变的事实 |
| `apps/control-api/app/tests/test_binding_invalidation_surface.py` | 7 用例 |

#### 投影的实质内容

- **硬引用**：`Deployment.runtime_binding_id` 外键，按状态计数（`by_status`）。语义固定为**历史记录**，报 `deployment_records_are_history_not_current_state`，不解释为当前运行占用。
- **软引用**：草稿 `preview.items[].binding_id`（JSON）。**只扫调用方自身身份、且未过期**的草稿，复用 `BatchDeploymentPreview` 解析。其它身份草稿恒为 `not_determinable` + `draft_ownership_is_actor_scoped`（与 `_owned_draft` 同一所有权规则，不越权也不声称全覆盖）；过期草稿不扫，报 `expired_drafts_outside_scan_scope`——依据是 `batch_execution.py:44` 在起始每项前检查 `deadline`，过期草稿不可能再启动新项。
- **扫不完不等于没引用**：`draft_scan_limit`（默认 200）扫满 → `draft_scan_truncated`；预览不可解析 → `draft_preview_unreadable` + `unreadable_draft_ids`。两者都使结论降为 `not_determinable`，**不**降为 `dependency_absent`。扫描元数据 `{scanned, limit, truncated}` 一并返回。
- **`effect_if_revoked` 固定结论集**：只声明既有代码路径可判定的拒绝语义（`binding_revoked`），显式声明 `existing_effects_are_not_reverted: true`——**吊销不是回滚**。
- **契约兼容性**：不新增端点、不新增迁移、不改任何既有响应体。`execution_confirmation_supported` 恒 `False`，`shared_runtime_occupants` 恒 `"unknown"`，`coverage` 恒 `"recorded_dependencies_only"`——与 `deployment_impact.py:46-49`、`binding_evidence_readiness.py:187-190` 的保留语义一致，未升格、未放松。

**本轮实跑命令与结果**（源码身份：本轮工作树，改动未提交）

| 命令 | 结果 |
| --- | --- |
| `./.venv/bin/python -m pytest app/tests/test_binding_invalidation_surface.py -p no:randomly -q` | **7 passed** |
| 同组回归：`test_binding_invalidation_surface + test_binding_evidence_readiness + test_runtime_binding + test_binding_execution_recheck + test_binding_source_identity + test_registration_environment_binding + test_change_execution_evidence_boundaries + test_effect_evidence_contracts + test_batch_draft_revalidate` | **94 passed, 1 warning in 8.87s** |
| `./.venv/bin/ruff check app/binding_invalidation_surface.py app/tests/test_binding_invalidation_surface.py` | All checks passed |
| `scripts/enterprise-experience/contract-version-chain-audit.py --repo . --out <mktemp>` | exit 1（**基线不变**）：`undocumented_versions=1`（既有 `local-admin-session/v1`）、`broken_navigation_links=0`、`documented_but_unemitted=88`、`test_only_version_references=16`。新增合同文件**未**产生新断点 |

**过程中修正的两处自身缺陷（记录以备复现）**：① 用例之间共享同一 session 级 SQLite，草稿按身份扫描会跨用例累计，导致 `scanned` 计数不确定——改为每个用例独占 `actor_id`；② 跨租户泄漏断言最初把**调用方自己给出的** `binding_id` 当作泄漏点，改为只对 `dependents` 子树做泄漏检查（回显请求参数不构成泄漏）。

### R04.5 未完成与下一动作

- **未接线**：内部只读投影，无 HTTP 路由；`assess_binding_evidence` 与本模块均**无生产调用方**。
- **未完成（依赖 R09/D-1）**：五维证据的权威生产者；绑定身份快照扩入沙箱 revision 与 Skill 摘要（需改既有文件，D-1 冻结）；共享独占标准（D-3 已决定保持 `unknown`）。
- **下一可执行动作**：R05 准备（`executeBatchDraft` 接线的前置影响披露）仍受 R04 完整影响披露约束，**不得提前开放执行确认入口**（§4）；因此下一步转入 R07/R08 可做的测试准备与文档/工具核对。

### R04.6 独立回滚审批：**只读合同草案**（2026-09-26，按主开发者答复"先只出只读合同草案"实施）

**交付 4 个新文件**（源码/合同/测试/交接，全部**未接线**、未改任何既有文件）：

| 文件 | 内容 |
| --- | --- |
| `packages/contracts/enterprise-rollback-approval.v1.md` | 合同草案：7 条要素、四值状态词表、三条不变量、结论词表**与可达性**、与既有实现的关系 |
| `apps/control-api/app/rollback_approval_readiness.py` | 内部只读就绪度核对：纯函数 `evaluate(facts)` + 今日快照 `requirements_table()`；`runtime_effect` 恒 `"none"` |
| `apps/control-api/app/tests/test_rollback_approval_readiness.py` | **11 条**用例，逐条钉住三条不变量 + 纯函数/确定性 + 源码只读边界 |
| `docs/development/deepseek-r04-rollback-approval-handoff-20260926.md` | 交接：要答的 4 个业务问题（含选项与影响）、若批准实现的最小方案、本层的诚实边界 |

**命令与结果**：

```text
cd apps/control-api
.venv/bin/python -m pytest app/tests/test_rollback_approval_readiness.py -p no:randomly   → 11 passed（exit 0）
.venv/bin/ruff check --no-cache --config pyproject.toml <两个文件>                          → All checks passed!
```

**今日事实（只读快照）**：7 条要求 **0 成立 / 5 `absent` / 1 `declared_only` / 1 `not_determinable`** → 结论 `rollback_approval_not_ready`。
唯一"有东西"的两条分别是：要求 6（审批证据不可由请求正文覆盖）**只有声明**（`contracts.py:239-240` 的构造约定）；
要求 3（审批者 ≠ 申请者 ≠ 操作者）**本层不可观测**。其余 5 条无证据源。

**与既有复验的关系（逐行核对，非印象）**：回滚链**已有**执行前复验 —— `app/routers/policies.py:939`
`authorize_rollback`（写前重查活体授权链，`:859` `_rollback_live_chain`），它证明"意图未漂移"；
**不**证明"第二个身份为这次操作担责"。本模块只登记这个缺口，**不**把复验当审批，也**不**复制其判定逻辑。

**两条自查如实留痕**：

1. **一个真缺陷（模块侧修，非放宽测试）**：首版用集合成员判定取值，`1 in {True}` 为真、`0.0 in {False}` 为真，
   使 JSON 里的数字 `1` 被当成"成立"。已改为**按类型严格**判定（只有布尔 `True` 或 `"present"`/`"verified"` 才可能成立）。
   由 `test_unrecognized_value_is_never_treated_as_present` 钉住（该用例正是先红后绿）。
2. **一个不可达结论档**：`rollback_approval_requirements_met_but_not_wired` 因不变量 2 **经本层恒不可达**
   （第 3 条永不可能 `present`）。这不是缺陷而是设计结果，测试 `test_met_but_not_wired_is_unreachable_through_this_layer`
   **明写钉住**，模块 docstring 也写明保留该档只为表达上限；**未**伪装成可达。

**未做（硬约束逐条遵守）**：未改 `execution_confirmation_supported`（R04 硬约束）；
未选审批人、未定义审批凭证、未设有效期（业务决策，交 `...-r04-rollback-approval-handoff-20260926.md` §4 的四个问题）；
**不产生** `effective`/`enforcement_verified`；未接线；未改回滚语义。

---

## R05：批量权限到可核对结果及恢复

**状态：doing（只读核查 + 可复现探针 + 缺口 3 非 openshell-cli 半边已实施并隔离验证；缺口 1/2/4 与独立回滚审批仍未动）**。对应 CL-05；ENT-014–016、018。实施与证据见 **R05.5**。

### R05.1 当前事实（源码确认）

- 后端整链已实现且已接线：`batch_reservation.py`（原子预留）、`routers/deployment_batch_draft.py`（`POST /api/v1/deployment-batch-drafts`、`GET/{id}`、`POST/{id}/revalidate`）、`routers/deployment_batch_execute.py:34`（`POST/{id}/execute`，`confirm_execution` 仅确认执行已批变更、**不是审批**）、`routers/deployment_batch_result.py:41`（`GET/{id}/reservation`，逐项重验 `change_id/env/binding/target` + 双摘要）。
- 前端 `BatchDraftPanel.tsx` 已消费 `createBatchDraft` / `readBatchDraft` / `readBatchResult`（含 `unconfirmed` / `needs_attention` 展示），并显式注释：`Preview/read only until complete impact disclosure is available. Never executes.`
- `apps/web/src/api/deploymentBatch.ts:126` 的 `executeBatchDraft` **无生产调用方**（全仓仅定义 1 处 + 测试 3 处）。

### R05.2 缺口

1. 执行触发未接线（依赖 R04 的完整影响披露）；
2. `deployment_verify.py` 的 `expect_deny` 恒空 → 行为核验无生产者，`enforcement_verified` 无生产路径；
3. 独立回滚审批 / 过期授权不复活边界未收口（`enterprise-permission-coverage-closeout.md` §3 第 9 项明列为「待核实/实现」）——**本轮已核实到可复现粒度并有对照实测，见 R05.4**：openshell-cli 分支边界**已建立且有测试**，非 openshell-cli 分支**无任何重查**；两个分支对"授权过期后能否回滚"给出相反答案——**该相反答案已由 R05.5 消除**（两条分支共用同一处判定）；独立回滚审批**在两条分支上仍都不存在**；
4. `unconfirmed` 结果无自动恢复驱动器（合同明确不自动重放——保持）。

### R05.3 下一动作

前置未具备前**保持只读**（缺口 3 的既有分支缺陷已按 R05.5 最小修复，不改变这一条）；不以新增按钮宣布完成。行为核验需受控探针 + 精确目标/版本/范围 + 超时与结果证据，真实探针执行须另获授权。

### R05.4 本轮只读核查：回滚授权与"过期授权不复活"边界（缺口 3）

§4 禁止在 R04 完整影响披露前开放依赖它的**执行确认入口**，故本轮对 R05 只做**只读核查 + 可复现探针**，不新增任何执行路径、不改既有文件。

**核查结论一：openshell-cli 后端下边界已建立且有测试**（不是缺陷，是既有成果）。

`routers/policies.py:860` 的回滚端点只在 `SIQ_AS_ENFORCEMENT_BACKEND == "openshell-cli"` 时进入真实回滚分支，并在写前以 `authorize_rollback`（同文件 `:889-936`）**重查实时授权链**：绑定必须仍 `active` 且 backend/target 与回执一致、变更单必须 `approved|effective`、目标策略不得为 `rejected|failed|superseded|rolled_back`，另加 `_ensure_binding_in_selector`、`require_binding_source_identity`、`require_target_authority` 与 endpoint/gateway 指纹比对（`caps.endpoint_fingerprint`、`gateway_name_sha256`）。任一不满足即返回 `False` → 适配器抛 `openshell_rollback_authorization_failed`。既有测试 `test_policy_flow.py:675`（`test_rollback_rejects_revoked_runtime_binding`）断言**吊销后回滚 502、后端零写入、部署仍为 `effective`**。这正是"过期授权不复活"。落地位置可考。

**核查结论二：非 openshell-cli 取值下**没有**这条重查**（本轮实测复现）。

`policies.py:876` 之外的分支（`backend` 非 `openshell-cli`，默认值即 `none`；测试夹具为 `fake`）**整段跳过**，直接执行 `cr.status = "rolled_back"`、`deployment.status = "rolled_back"`（`:984-987`），其间**不重查**绑定状态、变更单状态、策略状态、目标授权或指纹。

复现方式（临时探针，**已删除，不是交付物**）：隔离 SQLite + dev 身份，构造 `effective|sent|failed` 的部署后分别注入两种"授权已过期"状态，再调用回滚端点。

| 注入状态 | 后端 | HTTP | 部署状态 | 变更单状态 |
| --- | --- | --- | --- | --- |
| 绑定已吊销（`RuntimeBinding.status='revoked'`） | 默认 `fake` | **200** | `rolled_back` | `rolled_back` |
| 策略已被新版取代（`DesiredPolicy.status='superseded'`） | 默认 `fake` | **200** | `rolled_back` | `rolled_back` |
| 绑定已吊销（对照，既有测试 `test_policy_flow.py:675`） | `openshell-cli` | **502** | `effective`（不变） | — |

实测输出（原样）：

```text
[PROBE-REVOKED] backend=fake http=200 body_status='rolled_back' cr_status='rolled_back' dep_status='rolled_back'
[PROBE-SUPERSEDED] backend=fake http=200 body_status='rolled_back' cr_status='rolled_back' dep_status='rolled_back'
```

**这意味着什么（如实说清，不夸大）**：非 openshell-cli 取值下不会有真实后端写入，回滚是**账面状态迁移**而非真实撤权。所以这不是"绕过真实撤权"，而是**状态声明与实时授权链脱钩**：在绑定已吊销、策略已被取代的情况下，系统仍写下"已回滚"，并把一个 `superseded` 的变更单**改写**为 `rolled_back`——而同一文件在 openshell-cli 分支里**明确把 `superseded` 当作拒绝回滚的理由**。两条分支对"授权过期后能否回滚"给出相反答案，其中一条没有任何重查。哪条为准属业务决策（门槛 D-3 同族），执行者不擅自选定。

**核查结论三：回滚没有独立审批**。端点与写前授权都只要求 `policy:manage`（`:863`、`:891`），没有独立审批人、没有回滚审批记录、没有职责分离；能部署的角色即可单方回滚。这与 openshell-cli 分支内**同一个** `policy:manage` 一致——即"独立回滚审批"目前**在两条分支上都不存在**，属缺口 3 中"未收口"的那一半，需业务决策与授权模型变更，**不是本轮可自行实现的范围**。

**最小修复规格（供主开发者，未实施）**：非 openshell-cli 分支在写状态前套用与 `authorize_rollback` **同一套**实时链判定（绑定 `active` + backend/target 一致、变更单 ∈ `{approved, effective}`、策略 ∉ `{rejected, failed, superseded, rolled_back}`），不满足则 409 且不写状态；或反过来**显式声明**"非真实后端下回滚仅为账面回置、不构成撤权事实"并在合同/响应中标注。二选一都要改既有文件 `routers/policies.py`，受 D-1 约束本轮未执行；修复体积约 20-30 行 + 2-3 个用例。

**已登记但未判定为缺陷的观察**：`:984` 的 `session.get(ChangeRequest, deployment.change_request_id)` 未带 `tenant_id` 过滤——可达性由 `Deployment` 自身的租户过滤（`:866`）与 `change_request_id` 外键保证，**实测无跨租户可达路径**，仅与同文件其余查询的写法不一致，登记备查。

### R05.5 缺口 3 的实施（D-1(b)，2026-09-26）

**状态：source complete + isolated verified（合成夹具；**不是**实际交付）**。上一节的最小修复规格经主开发者批准（D-1 = 全部放开）后落地。源身份：工作树 `ebaaf3b`（`main`，682 项未提交改动，含并行作者改动；本轮只改下列文件）。

**改了什么**（`apps/control-api/app/routers/policies.py`，一处抽取 + 一处分支收紧）：

1. 新增 `_rollback_live_chain(session, identity, deployment)`（`:859-902`）：把原先**只写在 openshell-cli 分支里**的活体授权链判定抽成唯一一处，返回 `(live_binding, live_cr, live_policy)` 或 `None`。判定内容：绑定仍 `active` 且 `backend_target_id == deployment.target`；变更单仍 `approved|effective|deploying`；目标策略 ∉ `{rejected, failed, superseded, rolled_back}`。openshell-cli 的 `authorize_rollback` 改为调用它（`:938-941`），不再自带一份。
2. 非 openshell-cli 分支（默认 `none`；测试夹具 `fake`）在写状态前套用同一判定（`:1010-1022`）：不满足则审计 `deployment.rollback_refused`（`summary.detail = rollback_authorization_expired`）→ `409 rollback_authorization_expired`，**零状态写入**。
3. 破坏性发现（修的过程中实测撞到，已固化为注释）：该判定内的 `session.expire_all()` 会**丢弃未提交的 ORM 变更**。若把守卫写成 openshell-cli 分支之后的独立 `if`，第二次判定会把该分支刚写入、尚未 commit 的 `deployment.verification` 一并丢掉——表现为**回滚返回 200 且状态为 `rolled_back`，但 `verification.rollback` 消失**。故守卫必须是 `elif`（openshell-cli 分支已由 `authorize_rollback` 在写前完成同一判定，无需重复）。

**规格细化一处（必须说明，不是"为了过测试而放松"）**：R05.4 写下的规格是变更单 ∈ `{approved, effective}`；实施后为 `{approved, effective, deploying}`。原因是**实测**：非 openshell-cli 后端下应用不会有回执确认，变更单停在 `deploying`（`policies.py:738` 在派发时写入），部署停在 `sent`；而本端点自身就允许回滚 `sent` 部署，既有测试 `test_policy_flow.py:137`（`test_deployment_requires_approval`）断言的正是"`sent` 部署回滚 → 200"。照字面实施该规格会让这条**既有绿色用例**变成 409——即拒绝一次完全正当的回滚。`deploying` 是**审批已授予、应用在途**，不是死亡态；白名单仍是 fail-closed，未列出的状态（`draft`、未批准、`rejected`、`superseded`、`rolled_back` 等）一律拒绝。该边界已由新增反例守卫用例钉住（见下）。

**证据（命令 → 结果）**：

| 命令 | 结果 |
| --- | --- |
| `cd apps/control-api && ./.venv/bin/python -m pytest app/tests/test_policy_flow.py` | **28 passed**（原 24 + 新增 4） |
| `./.venv/bin/python -m pytest`（`apps/control-api` 全量） | **2164 passed, 1 skipped, 0 failed**（110.76s） |
| 反证：以临时插件把 `_rollback_live_chain` 强制返回"链仍活"（等价复现**修复前**的非 openshell-cli 分支，插件在 `/tmp`，非交付物） | 3 条新拒绝用例**全部 FAIL**；反例守卫用例仍 PASS → 新用例不是空跑 |
| `./.venv/bin/ruff check .` | 本文件与新增用例**零告警**；全仓余 6 条（`app/main.py:8` I001 导入序、`migrations/*` 5 条）均在**本轮未触碰**的文件里，登记不代改 |

**新增用例**（`apps/control-api/app/tests/test_policy_flow.py`）：

- `test_rollback_refuses_dead_authorization_chain_without_writing_state`（参数化 3 例：绑定吊销 / 策略被取代 / 变更单被驳回）：断言 `409 rollback_authorization_expired`、部署仍为 `sent`、变更单未被改写、且恰好留下 1 条 `deployment.rollback_refused` 审计（`summary.detail` 同码）。共用夹具 `_sent_deployment_with_fake_backend` 走真实 API（提出→批准→部署），不直插状态。
- `test_rollback_still_allowed_when_change_request_is_in_flight`：反例守卫，钉住"`deploying` 不算死亡态"，防止后来者把白名单收紧到再次拒绝正当回滚。

**仍未完成（照旧，不受本次实施影响）**：

- **回滚没有独立审批**：本次只收紧"授权链是否仍活"，**没有**引入独立回滚审批人、回滚审批记录或职责分离；`policy:manage` 仍可单方回滚。属业务决策（需授权模型变更），执行者未自行选定。
- **新增观察（源码推导，未实测，登记不修）**：`emergency_applied`（break-glass 变更单，`policies.py:344`）不在白名单内。成功部署后变更单会被改写为 `effective`（`:660`），故实际窗口很窄——只在**break-glass 部署失败且带 `operation_id`** 时，openshell-cli 分支的授权重验会拒绝回滚（502）。该行为在本次抽取**之前就已存在**（原 openshell 分支同样是 `{approved, effective}`），本轮只是把它集中到一处后变得可见。是否把 break-glass 视为活体授权属业务决策，未改。
- 缺口 1（执行触发未接线）、缺口 2（`expect_deny` 恒空 → `enforcement_verified` 无生产者）、缺口 4（`unconfirmed` 无自动恢复驱动器，合同明确不自动重放）状态不变。

---

## R06：完整审计引用与保留/导出治理

**状态：todo（保留治理等待 D-5）**。对应 CL-06；ENT-019。

### R06.1 当前事实（源码确认）

- `routers/audit.py` 恰有 **1 个端点**：`GET /api/v1/audit-events`（过滤 actor_id/action/resource_type/request_id/resource_id/actor_type/decision + cursor + limit + include_total；权限 `audit:read`；租户隔离；响应头 returned/truncated/next_cursor/total）。
- `routers/export.py` 恰有 **1 个端点**：`GET /api/v1/export/ocsf`（class=detection_finding|api_activity，since，limit 1..2000 默认 500）；已含成功响应 `Cache-Control: no-store` 与 `except (ValueError, OverflowError) → 422 invalid_since`；写 `export.ocsf` 审计。
- `ocsf.py`：`OCSF_VERSION = "1.1.0"`，纯函数映射，无 I/O。
- 变更执行证据：`routers/change_execution.py` + `apps/web/src/api/changeExecution.ts`（§9 主开发者验收已过），新增 `test_change_execution_evidence_boundaries.py`（7 用例）。

### R06.2 缺口

1. **保留治理为零**：`models.py:47` `Tenant.retention_days: int default 180` **除 models 与迁移测试夹具外无任何读取点**；无保留期执行器、无清理任务、无 cron；控制面 routers **无任何 DELETE / purge / soft-delete**。
2. **导出治理受限**：单一端点、两类 class、无分页/cursor；导出审计 summary 仅 `{class,count,since}`，**无「是否被 limit 截断」标记**。
3. **引用链未闭合**：无设备→框架/角色→Skill 版本→运行绑定→申请/审批/策略→部署/回执→配置/行为证据的完整版本化引用。
4. 待裁决：`ui/verification.ts` 仍把 `behavior_verified→behavior_enforced`（DEV13-C 未改）；非字符串 `level` 投影为 `none`；错误响应缺 `Cache-Control: no-store`。

### R06.3 下一动作与约束

- 先以一条业务链核对缺边的**生产位置**，在所属业务写入处以版本化安全标识补齐（审计与状态同事务），历史缺失明确标记，**不事后回填伪历史**；
- 复用现有详情与精确查询提供正/反向可达，**不通过新聚合接口扩大读取范围**；
- 保留/删除治理先确认政策与权限（**D-5**）。未决定前保持「不删除历史」的安全现状，只做设计/合同准备，不虚报治理完成。

### R06.4 本轮实施：版本化引用链审计工具（缺口 3 的一半：把"是否闭合"变成可核对结论）

D-5 决策把保留治理锁定为"只补齐声明与缺口"，因此本轮的**可执行代码动作**落在缺口 3 的**可核对化**上：不再靠人工阅读判断版本链是否闭合，而是提供只读工具自动判定并精确定位断点。

| 项 | 内容 |
| --- | --- |
| 新增工具 | `scripts/enterprise-experience/contract-version-chain-audit.py` |
| 新增别名表 | `scripts/enterprise-experience/contract-version-aliases.json` |
| 新增测试 | `scripts/enterprise-experience/test_contract_version_chain_audit.py`（12 用例） |
| 既有文件改动 | 仅两处合同末尾追加版本导航段：`enterprise-skill-upload.v1.md`、`enterprise-skill-collection.v1.md`（无正文删改） |
| 迁移 / 端点 | 无 |

工具判定三类事实：

1. **发出但未建档**（阻塞缺口）：代码中出现 `<family>/v<n>` 字面量，该 family 在 `packages/contracts/` 下已有其它版本建档，但本版本既无文件、也无显式别名。这正是 R02 的 `snapshot-comparison/v2` 缺口的形态——生产者已按新版本输出，旧严格消费者会拒绝。
2. **测试文件引用**（提示，不阻塞）：`tests/`、`test_*.py`、`*_test.go`、`*.test.ts`、`testdata/` 下的字面量单独归类。测试刻意引用非法版本或哨兵版本（实测有 `local-skill-update-schedule/v99`、`workbuddy-hook-correlation/v99`、`enterprise-install-plan/v0`），把断言当生产者会产生大量假阳性。
3. **版本导航链接断裂**（提示）：合同文档内指向不存在文件或目录的 markdown 链接（外部 URL 与锚点不算）。

**只读边界**：只按固定文本后缀读取；跳过 `.git`/`node_modules`/`.venv`/`dist` 等目录与 `.private`/`.seed`/`.pem`/`.key` 等敏感后缀；跳过打包进二进制的 `embedded/assets` 构建 JS；不联网、不写库、不执行仓库内任何文件；报告**独占创建**，已存在即拒绝覆盖（exit 3），避免把上一次结论悄悄换成这一次的。

**别名机制是显式声明而非猜测**：`family/vN` → 实际承载该版本语义的合同文件，且目标必须是仓库内真实存在的 `packages/contracts/` 文件（不接受 URL、绝对路径、`..` 或目录），否则工具以用法错误退出。

**实测结果**（真实工作树，非合成）：

```text
apps/control-api/.venv/bin/ruff check scripts/enterprise-experience/contract-version-chain-audit.py \
        scripts/enterprise-experience/test_contract_version_chain_audit.py      → All checks passed
python3 -m unittest discover -s scripts/enterprise-experience \
        -p "test_contract_version_chain_audit.py"                                → Ran 12 tests, OK
python3 scripts/enterprise-experience/contract-version-chain-audit.py --repo . \
        --out <mktemp>/chain.json \
        --aliases scripts/enterprise-experience/contract-version-aliases.json
  → documented_family_count=320 documented_version_count=375
    emitted_version_count=557  alias_count=2
    undocumented_versions=1  test_only_version_references=16
    documented_but_unemitted=88  broken_navigation_links=0
    closed_version_chain=false  exit=1
```

**工具发现的真实缺口与处置**：

| # | 缺口 | 处置 |
| --- | --- | --- |
| 1 | `enterprise-skill-upload/v2`：`app/skill_upload.py:44` 生产端接受，`edge/agent` 发出，但 `packages/contracts/` 无 v2 文件 | **语义已建档**，只是文件名 family 不同——完整定义在 `enterprise-skill-ancestry.v2.md`（逐字核对该文已写明"v2 对应 enterprise-skill-upload/v2，控制面同时接受 v1/v2，响应仍为 enterprise-skill-upload-result/v1"）。已在 `enterprise-skill-upload.v1.md` 补版本导航段 + 登记别名，**不另建重复文件** |
| 2 | `enterprise-skill-collection/v2`：`connectors/directory/skills_linux.go`、`edge/agent/skill_upload.go` 发出，无同名文件 | 同上：`enterprise-skill-ancestry.v2.md` 已写明"Linux Directory 新增 … `collect_skills_v2` 操作，返回 enterprise-skill-collection/v2"。已补版本导航段 + 登记别名 |
| 3 | `local-admin-session/v1`：`apps/web/src/local/api.ts:154` 接受 v1（回退 43200 秒），`packages/contracts/` 只有 `local-admin-session.v2.schema.json` | **未处置，如实保留为未闭合项**。已核实现有生产者**只发 v2**（`apps/agentshield/internal/server/session.go:87`、`authz.go:296`、`browser_connect.go:202`），v1 只是本地面板的历史兼容读取。该子系统（本地 agentshield 控制台）不在本轮企业主线范围内，且按 D-1 本轮不改既有实现文件。**建议移交该子系统负责人**：或在 v2 schema 文件补 v1 历史兼容说明，或移除 v1 分支——属其自身决策 |

**因此 `closed_version_chain=false` 是当前真实状态，不是工具误报**：企业主线相关断点已全部闭合，剩余 1 条属本地控制台历史兼容路径。

### R06.5 保留治理（D-5：只补齐声明与缺口）

按 D-5 **不做**保留执行器、**不做**到期删除/归档、**不新增** DELETE/purge 端点。本轮只把事实写清：

- `models.py:47` `Tenant.retention_days: int default 180` 是**声明值**；除 models 与迁移测试夹具外**无任何运行时读取点**，因此**当前不存在任何保留期强制执行**。
- 控制面 routers **无任何 DELETE / purge / soft-delete**；「不删除历史」是当前唯一实际行为。
- 导出治理仍受限：单一端点、两类 class、无分页/cursor；导出审计 summary 仅 `{class,count,since}`，**无"是否被 limit 截断"标记**——一次导出可能被静默截断而审计看不出来。

**不得把 180 天声明写成"已治理 180 天"**。合同与交付文档中该值一律标注为"声明值，无强制执行"。

### R06.6 未完成

- **保留治理为零**（D-5 已决定不做，属**明确记录在案的缺口**而非遗漏）。
- **导出截断标记缺失**：未修（需改既有 router，受 D-1 约束）。
- **引用链的业务级补齐**：本轮只交付"是否闭合"的自动判定工具；各业务写入处的版本化安全标识补齐仍为 todo，需逐条以业务链核对（见 R06.3）。
- **范围**：工具为源码完成 + 隔离测试通过，并在真实工作树实际运行过一次；不代表版本链已闭合。

---

## R07：同一候选的统一集成与防御门禁

**状态：todo（等 R01–R06 收束）**。对应 CL-01、07；ENT-001、003、020、022。

### R07.1 现有可复用门禁工具（已盘点）

`scripts/enterprise-experience/` 共 **47 个 `.py`**（`ls …|wc -l` 实测；R00 时点为 43，本轮新增 `enterprise-gate-run.py` 与 `test_enterprise_gate_run.py`，另有并行作者线新增），其中与门禁直接相关者：

- `source-freeze-preflight.py`（+ `test_source_freeze_preflight.py`，10 用例）——冻结前只读工作树盘点；
- `deployment-postgres-check.py`——临时回环 PostgreSQL 迁移与持久化部署竞态检查；
- `audit-query-wire-check.py`——后端真实响应导出 → 前端消费者契约检查；
- `gateway-edge-smoke.py`、`hermes-native-contract-check.py`、`skill-collection-native-smoke.py`、`source-baseline.py`；
- **30 个** `*-browser-smoke.py` 隔离浏览器验收脚本（`ls scripts/enterprise-experience/*-browser-smoke.py | wc -l` 本轮实测；此前各处沿用的 **24** 为更早时点数字，未逐项复核，**以本轮实测的 30 为准**）。

`scripts/release/`：`enterprise_candidate.py`（从已审阅 40 位 commit + 独立源码清单离线构建候选，**从不签名或安装**）、`enterprise_finalize.py`（外部签发后组包，双次全制品核验）、`verify.py`、`package.py`、`readback.py`、`skill_source_smoke.py`，单测 17 passed（历史记录）。

### R07.2 缺口

1. **无「同候选统一集成」机制**：各交付线均为独立未提交产物，`enterprise_candidate.py` 只从**单一审阅 commit** 导出允许清单 `SOURCE_PATHS`，不覆盖 web/control-api 全量集成；
2. **历史矛盾已部分澄清**：`enterprise-audit-query-wire-handoff.md`（2026-09-25）记录前端标准构建 **exit 1**（7 个 TS 错误在 `RuntimeBindingsPage` 在途文件）且前端全量 4 failed（同文件）；`enterprise-runtime-binding-ui-review.md`（同日）称该文件已修复。**R00 实测**：`apps/web` 下 `npx tsc -b` 当前 **exit 0**，即该 TS 失败在当前工作树**已不存在**。仍待 R07 用正式模式构建与全量前端测试最终判定，不据单一 tsc 结果关闭。
3. 测试可移植性未纳入 CI/门禁；未在全新机器 `npm ci` 验证。

### R07.3 本轮抢跑：后端全量真实基线（**首次在同一工作树上跑全量后端**）

任务书 §4 允许"R04 缺业务决策时推进 R07 测试准备"。本轮据此先跑了一次**后端全量**，把"基线到底绿不绿"从未知变成已知——这是后续所有集成判定的分母。

```text
cd apps/control-api
.venv/bin/python -m pytest app/tests -p no:randomly
  → 9 failed, 2143 passed, 1 skipped, 1 warning in 110.27s
```

**结论：当前工作树后端全量不是绿的。** 9 处失败，且**全部与本轮改动无关**——以 `--ignore` 排除本轮新增的两个测试文件后，失败集合与计数**完全一致**（同一 9 条），本轮改动不构成回归源。

**这 9 条不是"偶发抖动"，而是两个可精确定位的既存缺陷**：

| # | 缺陷 | 证据 | 性质 |
| --- | --- | --- | --- |
| 1 | `test_deployment_preview_consistency.py:60` 的 `_reservations()` 读取 **`DeploymentSubmission.state`**，而该模型 `models.py:702-717` **没有 `state` 列**（列为 id/tenant_id/change_request_id/deployment_id/request_key/request_digest/preview_digest/created_at） | 单独运行该文件 **15 passed**；全量运行时抛 `AttributeError: 'DeploymentSubmission' object has no attribute 'state'`（7 条失败） | **空通过（vacuous pass）**：隔离运行时表内无行，列表推导体从不执行；全量运行中其它测试写入行后体执行即崩。这是"隔离绿、集成红"的典型样本，正是 R07 存在的理由 |
| 2 | `test_enrollment_flow.py:182` 断言 env_a 新建的扫描任务出现在 `/edge/v1/tasks` | 单独运行通过；全量运行 `assert any(...)` 失败（1 条失败） | 跨文件共享 session 级 `client` + `env_a` 夹具的状态污染，需按顺序/隔离归因 |

另 1 条为 `test_deployment_preview_consistency.py::test_denials_precede_any_external_probe`，同属缺陷 1 的同一文件。

**未处置**：按任务书 §8 质量底线，失败应先归因再修，且**不删断言、不关校验、不加 skip**；同时按 D-1 本轮不修改既有实现与测试文件。因此这两个缺陷**如实登记为 R07 待修项**，不在本轮动手。

**方法学提示（对后续门禁的要求）**：缺陷 1 证明**单独运行测试文件不足以作为门禁**。R07 的统一门禁必须跑**全量**（或至少固定顺序的全量），否则这类"空通过"会持续逃逸。本轮 `-p no:randomly` 固定顺序，结果可复现。

### R07.4 下一动作

待 R01–R06 收束后固定受审查文件集，集中跑一次：前端标准正式构建（`VITE_DEV_MODE=false`，输出 mktemp 独立目录）、后端、Edge、实际变更 Connector、迁移回放与必要 wire/防御门禁；旧 `/tmp` 样本须重新生成并校验来源。失败先归因，**不删断言、不关校验、不加 skip、不换替代构建**。开工前先修 R07.3 登记的两个既存缺陷，否则门禁无法变绿。

### R07.5 本轮抢跑②：非后端门禁的首次同工作树基线（§5 不退化证据的第一批）

R07.3 只覆盖了后端。本轮把**其余可离线执行的门禁**也首次在同一工作树上跑了一遍——只读观测 + 临时构建，不安装依赖、不改源码、不启动任何服务。§8.6 明确允许"隔离合成测试及临时构建"，正式构建输出到 mktemp 独立目录。

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 前端全量单测 | `cd apps/web && npx vitest run` | **112 files / 1003 tests 全过**（1.79s） |
| 前端**正式**构建 | `VITE_DEV_MODE=false npx tsc -b` → exit 0；`VITE_DEV_MODE=false npx vite build --outDir <mktemp> --emptyOutDir` | **exit 0**，产物 410 文件 / 16 MB；`index-BfPmfkY7.js` 492.71 kB（gzip 146.30 kB） |
| 正式产物不含开发身份 | `grep -rl` 于产物目录 | `X-Dev-Tenant-Id` / `X-Dev-User-Id` / `X-Dev-Roles` / `VITE_DEV_MODE` / `tnt-A` **命中文件数均为 0**——常量折叠把开发身份注入整段消除，正式包不可用于模拟身份 |
| Edge Agent | `gofmt -l .` / `go vet ./...` / `go test -race ./...` | 0 未格式化 / vet 0 / **4 包全过**（`edge/agent` 8.879s） |
| 12 个 Connector 模块 | 同上三连 | gofmt 12/12 干净 / vet 全 0 / **`-race` 全部 ok**（dify、directory、docker、hermes、kubernetes、mcp、openclaw、piagent、process、siq、systemd、workbuddy） |
| AgentShield（本地控制台，Go） | 同上三连 | vet 0 / **`-race` 全部 ok**（40+ 包，含 `rulepack`、`threat`、`runtimecheck`、`receipt`、`signing`、`provenance`、`openshell`、`intent`、`grant`、`ledger`；最长 `skillinstall` 138s、`server` 96.8s） |
| 共享威胁规则包双份一致性 | `md5sum` 比对 + Go 侧 `rulepack_test.go:27` 漂移断言 | 两份 `threat_rules.v1.json` **字节相同**（`4863baaa5c159472c537a159d04c5a87`，13,219 B，mtime 同为 09-07 08:22）；Go 侧**已有**显式漂移失败断言（非本轮新增） |
| 后端威胁/漂移/证据边界子集 | `pytest test_threat_rulepack + test_threat_analysis + test_openshell_evidence + test_drift_evidence_boundaries + test_effect_evidence_contracts + test_change_execution_evidence_boundaries + test_threat_device_evidence` | **258 passed** |

**对 §5 的意义**：这是"原防攻击能力不退化"的**第一批同候选实测证据**——提示注入/凭据外传识别（`threat`、`rulepack`）、准入隔离与污点（`intent`、`runtimecheck`、`provenance`）、签名回执（`receipt`、`signing`）、撤权与 Authority（`grant`、`runtimeidentity`）在**当前工作树同一份源码**上全绿。但仍**不是**完整结论：后端全量仍未绿（R07.3 的 9 条既存失败），迁移回放、浏览器验收、真实设备/原生平台证据均未纳入。

**门禁设计缺陷（本轮实测发现，供 R07 定稿吸收）**：

1. **`gofmt -l .` 会被已忽略的临时目录误报**。`apps/agentshield` 下 `gofmt -l .` 报 1 个未格式化文件 `.tmp/fx01/refcalc.go`，而该路径被 `.gitignore:61` 忽略、`git ls-files` 计数为 **0**（未跟踪）。排除 `.tmp/` 后未格式化数为 **0**。→ 门禁必须**限定到跟踪文件**（如 `gofmt -l $(git ls-files '*.go')`），否则既有临时目录会持续制造假失败，进而诱导"顺手格式化"这类范围外改动。
2. **`vitest --reporter=basic` 在 vitest 4 已移除**，直接报 `ERR_LOAD_URL` 崩溃并掩盖真实测试结果。→ 门禁脚本**不得带自定义 reporter**，或固定使用受支持值。本轮改用默认 reporter 才拿到真实基线。
3. **正式产物内确实残留一处示例数据**：`env-dev-docker`（`apps/web/src/pages/AuditPage.tsx:42`，注释标明"控制面不可达时的安全示例数据；已连接时由 `GET /audit-events` 覆盖"）。**已核实为有意设计、不含任何凭据或开发身份**，故**不计缺陷**；登记以免后续门禁把它误报为泄漏。

### R07.6 全量门禁执行器实跑（首次用统一机制跑完 48 项，**结论不是绿的**）

R07.5 是手工分类跑的基线。本轮用新写的 `enterprise-gate-run.py` 把**同一批**门禁按统一机制再跑一次，验证机制本身可用，并拿到首份**机器可读、逐门禁留痕**的结果。

```bash
python3 scripts/enterprise-experience/enterprise-gate-run.py --repo . \
  --out "$(mktemp -d)/gate-run.json" --timeout 2400
```

| 项 | 值 |
| --- | --- |
| 报告 | `siq-enterprise-gate-run/v1`；`tool_version=enterprise-gate-run/0.1.0` |
| 时点 | `2026-09-26T07:43:15Z` → `07:47:26Z`（**4 分 11 秒**） |
| `head_sha` / `branch` | `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0` / `main` |
| `worktree_modified_count` | `681` |
| 门禁总数 | **48** |
| 状态分布 | **`passed` 44 / `failed` 1 / `skipped` 3** |
| `failed_gate_ids` | `["backend_full_suite"]` |
| `blocked_gate_ids` | `[]` |
| `skipped_gate_ids` | `["migration_replay_postgres", "browser_acceptance", "real_device_native_evidence"]` |
| `conclusion` | **`gates_failed`** |

**通过的门禁**（44 项）：后端以外全部。前端单测 2.2s、**前端正式构建（`VITE_DEV_MODE=false`）** 5.6s、正式产物开发身份断言、规则包双份一致性、Edge + 12 Connector + AgentShield 的 gofmt/vet/`-race`、版本化引用链审计。

**失败的门禁**（1 项）：`backend_full_suite` —— `pytest app/tests -p no:randomly`，**9 failed / 2150 passed / 1 skipped**（110.96s）。失败集合与 R07.3 登记的**完全一致**（`test_deployment_preview_consistency.py` 8 条 + `test_enrollment_flow.py::test_tasks_scoped_to_environment` 1 条），即两个既存缺陷，非本轮引入。通过数由 2143 升到 2150，**差额恰为本轮新增的 7 条 R04 用例**。

**跳过的门禁**（3 项，报告内带 note 与 reason，恒为 `skipped`，**永不可能是 pass**）：`migration_replay_postgres`（需临时数据库容器，§3.2 需先取得隔离/目标/回收许可）、`browser_acceptance`（需运行中的控制面与浏览器）、`real_device_native_evidence`（需真实设备/身份，且不得制造 effective 事实）。

**结论怎么读**：

1. 本报告的 `conclusion` **在本环境永远不可能是"全绿"**，有两道独立机制保证：3 条声明不可用门禁恒 `skipped`（对应 `gates_incomplete`），以及后端既存缺陷（对应 `gates_failed`，优先级更高，故本次为后者）。这不是缺陷，是刻意设计。
2. 报告自带 `not_evidence_of`：`green_gates_are_not_production_effect`、`gate_run_is_not_a_signed_candidate`、`gate_run_is_not_a_source_freeze`、`local_run_is_not_a_ci_attestation`、`skipped_gate_is_never_a_pass`。**门禁绿 ≠ 生产效果 ≠ 已签候选 ≠ 源码冻结 ≠ CI 存证。**
3. `--only` 单跑任一子集时工具强制把 `conclusion` 置为 `partial_run_not_a_gate`，防止把局部跑当门禁结果。

**门禁设计缺陷 4（本轮实跑发现，**必须记入定稿**）**：**Go 测试结果缓存会把"没跑"呈现为"通过"**。本次 `go_edge_race` 用时 0.111s 且 stdout 为 `ok … (cached)`（4 个包全部缓存），12 个 Connector 同样全缓存；在可读到的 60 条 `ok` 行中 **54 条带 `(cached)`**，只有 `apps/agentshield` 是当场真跑（126s，内含 22.9s / 4.6s / 1.4s 等真实耗时）。Go 的测试缓存按**输入内容**寻址，所以"缓存命中"确实等价于"同一份输入此前通过"，**结论不算错**；但它**不是本轮执行证据**，而任务书要求把历史结果与本次结果分开列。→ 定稿门禁必须加 `-count=1` 强制重跑，或至少把 `(cached)` 计数写进报告并按"历史通过"标注。**未加 `-count=1` 之前，Go 侧门禁只能作为"同内容历史通过"的证据。**

**实跑 B（缺陷 4 修复后，不带缓存重跑，**此份为准**）**：同一命令、同一工作树，`2026-09-26T07:48:47Z` → `07:53:30Z`（**4 分 43 秒**），`head_sha` 与 `worktree_modified_count=681` 均与 A 相同。

| 项 | 实跑 A（含缓存） | **实跑 B（`-count=1`，无缓存）** |
| --- | --- | --- |
| 状态分布 | 44 passed / 1 failed / 3 skipped | **47 passed / 1 failed / 3 skipped** |
| `failed_gate_ids` | `["backend_full_suite"]` | **`["backend_full_suite"]`**（不变） |
| 后端结果 | 9 failed / 2150 passed / 1 skipped | **9 failed / 2150 passed / 1 skipped**（110.34s；失败集合逐条相同） |
| Go 门禁缓存 | 60 条 `ok` 中 54 条 `(cached)` | **0 条 `(cached)`**，14 个 Go `-race` 门禁全部当场重跑，每个门禁的 `post_check` 均为 `no_cached_packages_in_output_tail` |
| Go 真实耗时 | `go_edge_race` 0.111s（缓存） | **`go_edge_race` 8.87s、12 个 Connector 各 1.2–2.3s、`go_agentshield_race` 137.4s** |
| `conclusion` | `gates_failed` | **`gates_failed`**（失败集合与 A 逐条一致，说明缓存**没有掩盖任何失败**——两个缺陷本就相同，这一点现在有证据而不是推断） |

**A/B 对照的实际价值**：A 里 Go 侧 54 条是"同内容历史通过"，B 把它们变成"本轮真实重跑且通过"，且两轮失败集合完全相同。**§5 的"同候选不退化"结论以 B 为准；A 只能作为历史记录。**

**缺陷 4 已在本轮修掉（工具是本人新增文件，不受 D-1 限制）**：`enterprise-gate-run.py` 的 14 个 Go `-race` 门禁改为 `go test -race -count=1 ./...`，并新增**新鲜性断言** `check_go_output_is_fresh` 作为这些门禁的 `post` 条件——输出尾部一旦出现 `(cached)` 即判定**失败**，目的是**防止 `-count=1` 被误删后门禁悄悄退回"历史通过"**。为此把 `post` 回调的签名统一为接收命令结果（`post(outcome)`），`run_gate` 相应改为传递 `outcome`。新增 4 条用例（共 **16 passed**）：门禁清单必须带 `-count=1` 且 `post` 必须是该断言、缓存输出不算新鲜通过、`post` 确实收到命令结果、`post` 失败能把本来通过的命令降级为失败。`ruff check` 通过（仓内 `ruff format` 非既有约定，230 个文件会被重排，未执行）。

### R07.7 两个既存后端缺陷的根因与最小修复规格（诊断；实施见 R07.8）

这两条是本轮门禁唯一变不绿的原因，也是"为什么后端门禁必须跑全量"的活证据。以下规格已把根因定到行、把验证方式定到命令，**改动都在既有测试文件内**，故需 D-1 例外授权（已获批 D-1 = 全部放开，实施与证据见 R07.8）。

**缺陷 1：`test_deployment_preview_consistency.py` 读取不存在的列，孤立运行空通过**

- 根因（源码确认）：[`test_deployment_preview_consistency.py:58-63`] 的 `_reservations()` 构造 `(row.id, row.state)`，而 `DeploymentSubmission`（[models.py:703-722]）**没有 `state` 列**——按设计它是不可变预留记录。
- 为什么孤立运行反而"过"：列表推导**只有在存在行时才求值属性**。孤立运行时该表为空 → 生成器体不执行 → 无 `AttributeError` → **空通过**；全量运行时别的测试文件已在会话级共享库里写下预留行 → 每条调用 `_reservations()` 的用例都抛 `AttributeError`。
- 本轮实测：孤立 **8 passed**（2.59s）；全量 **8 failed**。同一个文件，同一份源码。
- 最小修复：把 `_reservations()` 改为断言**真实存在**的字段（`(row.id, row.request_key, row.preview_digest)`），若原意是观察"不重放"，则改为断言 `Deployment.status` 未变 + 预留行数不增。**不要把 `state` 加进模型**——那会凭空给预留记录造一个状态机。
- 这条缺陷同时证明 R07 门禁设计（`why: 全量且固定顺序；单独运行测试文件会产生空通过`）是对的，不是保守。

**缺陷 2：`test_enrollment_flow.py::test_tasks_scoped_to_environment` 依赖会话级共享环境，被 10 条上限截断**

- 根因（源码确认）：用例用**会话级共享** `env_a` 建扫描任务，再断言它出现在 `GET /edge/v1/tasks` 结果里；而该端点是**领取**语义，按 `created_at` 取**最旧 10 条**（[`environments.py:486-491`] `.order_by(EdgeTask.created_at).limit(10)`，且逐个条件 UPDATE 领取）。
- 全量运行时 `env_a` 已积累 ≥10 条更早的可领取任务 → 新任务排在第 11 位之后 → 断言 `assert any(task["id"] == created["task_id"] …)` 失败（`assert False`）。
- 最小修复：**给该用例独立环境**（照 [`test_policy_flow.py:17-35`] 的 `env_iso` 写法），不要动 10 条上限——那是 P1-5 原子领取/租约的既有语义，改上限会扩大单次领取面。
- 附带说明：该端点**有副作用**（领取即租出），所以"重试一次"或"多查几页"都不是修复，只会污染其他用例。

**两条修好之后**：`backend_full_suite` 才可能由 `failed` 变为 `passed`；即便如此 `conclusion` 仍是 `gates_incomplete`（3 条声明不可用门禁恒 `skipped`），**永远不会是"全绿"**。

### R07.8 两个既存后端缺陷的实施（D-1(a)，2026-09-26）

**状态：source complete + isolated verified（SQLite 隔离夹具 + 合成适配器；**不是**实际交付）**。改动全部落在**既有测试文件内**，不触产品实现。

**缺陷 1 实际改法**（[`test_deployment_preview_consistency.py`]）：`_reservations()` 不再读不存在的 `row.state`，改为对**真实存在**的五个字段做快照——`(id, change_request_id, request_key, request_digest, preview_digest)`。取五个而非三个（诊断时段建议的 `(id, request_key, preview_digest)`）的原因：本题断言的是"预览**不产生**预留、也**不改写**既有预留"，行集或任一内容字段变化都应能被前后对比发现，多带的两个字段只增不减判别力，且**没有**给预留记录凭空造状态机。

**缺陷 2 实际改法**（[`test_enrollment_flow.py`]）：新增用例级夹具 `_fresh_env(client, headers, prefix)`，用例 `test_tasks_scoped_to_environment` 改为**自建两个独立环境**（真实 API 创建，不再用会话级共享 `env_a`/`env_b`），并把"为什么不能依赖共享环境 + 为什么不放宽 10 条上限（属既有 P1-5 领取语义）"写入夹具 docstring。10 条上限**未动**。

**证据（命令 → 结果）**：

| 命令 | 结果 |
| --- | --- |
| `pytest app/tests/test_deployment_preview_consistency.py`（修复前，全量上下文） | 8 **failed**（`AttributeError: 'DeploymentSubmission' object has no attribute 'state'`） |
| `pytest app/tests/test_deployment_preview_consistency.py`（修复后，孤立） | **8 passed** |
| 全量 `pytest`（修复前） | 9 failed / 2150 passed / 1 skipped |
| 全量 `pytest`（修复后） | **2164 passed / 1 skipped / 0 failed** |
| `ruff check`（本轮触碰的文件） | 零告警 |

**残留（登记不代改）**：`ruff check .` 全仓余 6 条告警，均在**本轮未触碰**的文件里——`app/main.py:8`（I001 导入块排序，来自并作者的 router 导入行；本轮加入的两行本身位置正确）与 `migrations/{env.py, versions/000*.py}` 5 条（I001/F401）。属并作者线，按 R00.3 与 §3.2 执行者**不代为修整**，登记待主开发者处置。

### R07.9 全量门禁实跑 C（三处既有缺陷修复后）

命令（与 A/B 完全相同，唯一差别是本轮改动已落在工作树里）：

```bash
python3 scripts/enterprise-experience/enterprise-gate-run.py --repo . --out /tmp/gate-run-C-20260926T161341.json
```

**结论：`conclusion=gates_incomplete`，进程退出码 `1`（`EXIT_NOT_GREEN`）**。报告 `started_at=2026-09-26T08:13:41Z`、`finished_at=08:18:25Z`（4 分 44 秒），`head_sha=ebaaf3b6…`、`branch=main`、`worktree_modified_count=682`。

| 项 | 实跑 A | 实跑 B | **实跑 C（本轮）** |
| --- | --- | --- | --- |
| 状态分布 | 44 passed / 1 failed / 3 skipped | 47 passed / 1 failed / 3 skipped | **48 passed / 0 failed / 3 skipped** |
| `failed_gate_ids` | `["backend_full_suite"]` | `["backend_full_suite"]` | **`[]`** |
| 后端结果 | 9 failed / 2150 passed / 1 skipped | 9 failed / 2150 passed / 1 skipped | **2164 passed / 1 skipped / 0 failed**（门禁内部 110.39s；与独立运行逐字一致） |
| Go `-race` 缓存 | 60 条 `ok` 中 54 条 `(cached)` | 0 条缓存 | **0 条缓存**（`post_check` 全部 `no_cached_packages_in_output_tail`） |
| Go 真实耗时 | `go_edge_race` 0.111s | 8.87s / 137.4s | **9.08s / 137.19s**（与本轮改动无关，量级一致） |
| `conclusion` | `gates_failed` | `gates_failed` | **`gates_incomplete`** |
| 退出码 | 1 | 1 | **1** |

**三件事必须一起读**：

1. **`conclusion` 仍不是绿的，而且永远不会是绿的**——3 条门禁（`migration_replay_postgres`、`browser_acceptance`、`real_device_native_evidence`）是**声明为不可用**的 `skipped`，报告自带 `not_evidence_of` 里的 `skipped_gate_is_never_a_pass`。`gates_incomplete` 是本次能达到的**最好**结论，不是"差一点全绿"。
2. **退出码 1 是正确的**：工具只在 `gates_green` 时返回 0。**注意不要把它读成"失败"**——它表达的是"本次结论不是全绿"，其中 0 条失败门禁、3 条声明不可用。
3. **48 条 `passed` 的边界**：`passed` 表示"该命令在本工作树上本轮真实执行且退出码为 0"，**不表示**生产效果、不是已签候选、不是源码冻结、不是 CI 存证（报告 `not_evidence_of` 逐条写明）。`worktree_modified_count=682` 说明这仍是**未提交工作树**上的结果。

报告为**独占创建**（路径已存在则拒绝覆盖），三份报告（A/B/C）全部原样保留在仓库外 `/tmp`，未纳入版本控制。

### R07.10 把恒 `skipped` 的 `migration_replay_postgres` 改成**显式启用**的资源门禁（2026-09-26）

R07.2 缺口 1 是"该门禁在任何机器上都恒 `skipped`"——等于**写死了一条永远不成立的判据**。本轮把"能不能跑"从**静态声明**改成**运行期判定**，但**不改变默认行为**：

| 设计点 | 做法 | 为什么必须这样 |
| --- | --- | --- |
| 默认不触碰 docker | 未传 `--enable-ephemeral-postgres-gate` 时**连只读探测都不做** | 门禁工具的默认语义是"只读 + 临时构建"；默认探测等于把 docker socket 变成隐式依赖 |
| 三种"没跑"必须可区分 | `requires_database_container`（未启用）／`docker_daemon_or_client_unavailable`、`postgres_image_absent_and_auto_pull_forbidden`（**实测**原因）／被 `--only` 排除 | "没启用"和"探测后确实不可跑"是两种不同的诚实；后者带 `measured: true` 与探测证据 |
| 绝不自动拉镜像 | 探测只用 `docker version` / `docker image inspect`；镜像缺失即判不可跑 | 拉取 = 引入新依赖，须单独授权（§3.2） |
| 只读探测也不越界 | 探测 `argv` 被测试断言**不含 `pull`**、首参数恒为 `docker` | 防回归成"顺手拉一个" |
| 只有**真的跑了**才撤登记 | `run_gates` 仅当记录里出现该门禁 id 时才从 `skipped_gates` 移除声明 | 否则"启用但没跑成"会被读成"不可跑项消失" |
| 留证必须能被断言 | `check_postgres_evidence` 要求 `passed`、`ephemeral_database=true`、`production_identity_tested=false`、`checks` 非空、`script_sha256` 与当前脚本一致 | 防"用旧脚本的结果充当本次证据"，防"临时库被说成真实环境" |
| 记录不是绿的 | 跳过项仍留 `skipped`，故 `conclusion` 仍只可能 `gates_incomplete` | 见 R07.9 第 1 条 |

**新增代码**（`scripts/enterprise-experience/enterprise-gate-run.py`）：`docker_probe`、`check_postgres_evidence`、`postgres_gate_decision`、`postgres_gate`，`run_gates(..., postgres_decision=)`，`main` 增 `--enable-ephemeral-postgres-gate`，报告增 `optional_gate_decisions`。**`build_gates` 签名未改**（`gate_builder` 注入契约保持兼容）。模块 docstring 的安全边界已同步改写：默认不启动服务、不连数据库，唯一例外是显式开关下的**一次性回环容器**，而该例外本身需先取得 §3.2 许可。

**命令与结果（本轮全部为只读/无容器运行）**：

```bash
python3 -m unittest test_enterprise_gate_run                                    # 23 tests OK（原 15，新增 8）
python3 scripts/enterprise-experience/enterprise-gate-run.py --repo . --out /tmp/gate-optin-D-20260926T162452.json --only contract_version_chain
python3 scripts/enterprise-experience/enterprise-gate-run.py --repo . --out /tmp/gate-optin-E2-20260926T162533.json --only contract_version_chain --enable-ephemeral-postgres-gate
docker ps -a --filter name=siq-deployment-check-                                # 0 行
```

| 实跑 | `optional_gate_decisions[0]` | `skipped_gate_ids` 含 `migration_replay_postgres` | 容器 |
| --- | --- | --- | --- |
| D（未启用） | `action=skipped`、`reason=requires_database_container`、`measured` 缺席 | **是** | 未创建 |
| E2（启用但被 `--only` 排除） | `action=skipped`、`excluded_by_only=true`、`measured` 缺席 | **是** | 未创建 |

两条实跑证明"没轮到它"与"没启用"都会**如实地**留在 skipped 里，且都不会去碰 docker。**`action=run` 分支至今未真实执行过**：它要等 A1 拿到 §3.2 许可（R09.4）——本节的诚实结论是"分支已就位并被合成用例覆盖，尚未产生真实证据"，**不是**"门禁已经能跑了"。

#### R07.10a 启用后跑出来的两个缺陷（都已修，**都由实跑暴露，不是推演**）

| # | 现象 | 实测根因 | 最小修复 |
| --- | --- | --- | --- |
| 1 | 门禁 `failed`、`exit_code=1`、耗时 **0.03s**，stderr 里是 `FileExistsError` —— 看起来像"A1 失败了" | 我用 `tempfile.mkdtemp()` 先建了证据目录，而 A1 脚本要求传入一个**不存在**的新目录（`out.mkdir(parents=True, exist_ok=False)`），正是为了不可能覆盖上一次留证 | 用 `mkdtemp` 取一个不会撞名的路径后**立即 `os.rmdir`**，把"不存在"的路径交给脚本；新增用例 `test_postgres_evidence_dir_is_handed_over_not_pre_created` 断言**交付时该目录不存在** |
| 2 | `--only migration_replay_postgres_ephemeral` 报 `no gate matched --only` —— 门禁永远无法被单独选中 | `--only` 的过滤发生在**追加门禁之前**，所以这个 id 永远不在候选集合里 | 改为"先算选中集合 → 判定是否探测 → 追加门禁 → **再**过滤"；"被 `--only` 排除时连只读探测都不做"的性质保持不变 |

**缺陷 1 值得单独记一笔**：它把"我的接线错了"呈现成"A1 门禁失败"。若当时只看结论行而不读 stderr，就会得出"真实 PostgreSQL 上跑不过"的**假结论**——这正是任务书要求"失败也要给出证据路径与原始输出"的理由。

#### R07.10b 启用后的真实执行（A1 已获许可，2026-09-26）

许可到位后实跑三次，全部**通过**：

| 实跑 | 命令 | 结果 |
| --- | --- | --- |
| A1 本体（直跑脚本） | `apps/control-api/.venv/bin/python scripts/enterprise-experience/deployment-postgres-check.py /tmp/a1-evidence-20260926T162846` | `{"passed": true, "checks": 18}`，**7.0s** |
| F2（门禁内单跑） | `... enterprise-gate-run.py --only migration_replay_postgres_ephemeral --enable-ephemeral-postgres-gate` | 门禁 `passed`（`exit 0`，6.75–7.02s），`post_check` 通过：18 项检查、`migrated_head=0028`、镜像 id 与脚本摘要逐字一致 |
| A1b（**全量** + 该门禁） | `... enterprise-gate-run.py --out /tmp/gate-run-A1b-20260926T163429.json --enable-ephemeral-postgres-gate` | **49 passed / 0 failed / 0 blocked / 2 skipped**，`conclusion=gates_incomplete`（4 分 49 秒）；`skipped_gate_ids` 已**只剩** `browser_acceptance` 与 `real_device_native_evidence`；后端同为 `2164 passed / 1 skipped` |

**`migration_replay_postgres` 不再是恒 `skipped`**：A1b 的报告里它是一条**真实执行过**的门禁记录，而"声明不可用"的跳过项由 3 条减为 2 条。这是 R07.2 缺口 1 的**部分**闭合——完全闭合还需 A2/A3 那两条（`browser_acceptance`、`real_device_native_evidence`）。

**遗留**：（a）`enterprise-gate-run.py` 仍有 1 条**既有** `UP017`（`utc_now` 用 `timezone.utc`），本轮 hunk 未触碰该行，按最小改动原则不动它；（b）测试文件仍有 4 条**既有** `E731`（`builder = lambda …`），本轮新增用例按 `def` 写法，未新增错误。

---

## R08：源码冻结、签名制品与文档准备

**状态：todo**。对应 CL-08；ENT-004、021、022。

### R08.1 当前事实

- 发行工具已复核通过（`enterprise-release-tools-closeout-handoff.md` §9），本次**无代码修改**；
- 文档准备已落盘：`README.md` / `README.en.md` 三处逐条对应修改，`docs/enterprise-production-runbook-v1.md` 新增 §9 排障、§10 发行包与部署前置条件；
- **注意**：README 中英**没有**标题级的「安装 / 升级 / 卸载 / 签名包」章节；相关内容以引用块与链接存在于 `README.md:49/51`，实际说明在 `docs/signed-release-packaging.md`（`## 构建固定版本` / `## 使用现有发行密钥签发` / `## 用户从完整包安装` / `## 发布与回读`）。

### R08.2 缺口

1. 源码未冻结：HEAD `ebaaf3b6…` **不含**工作树最新成果；无冻结 commit、无独立审阅的 `siq-release-source-inventory/v1` 清单；
2. 未产出正式候选与签名制品（`signed/installable/published` 恒 false，preflight 报告同样恒 false）；
3. 待回填：0.4.0-rc.2 公开发布入口、下载地址与回读结果；正式发行后的版本号与制品摘要。

### R08.3 下一动作

复用 `source-freeze-preflight.py` + `enterprise_candidate.py` + `enterprise_finalize.py` + `verify.py`；**不新建第二套发布器**。按责任线逐文件填写允许清单，形成可审阅的发行准备清单与**精确授权请求**（D-7）。未签候选保持 `signed/installable/published=false`，不交生产安装器冒充正式包。

### R08.4 本轮实施：责任线允许清单 + 快照核验（**未冻结、未签约、未发布**）

按 R08.3 的字面要求执行第一步：**按责任线逐文件填写允许清单**，并用**既有**工具核验，不新建第二套发布器。

允许清单草案：[`deepseek-enterprise-mainline-closeout-freeze-allowlist-20260926.txt`](deepseek-enterprise-mainline-closeout-freeze-allowlist-20260926.txt)，共 **26 条路径**，全部来自本轮 R00–R08 由执行者创建或修改的文件，按责任线分组（R01 设备侧待办枚举 3 / R03 证据拓扑 3 / R04 失效联动 3 / R02 合同 v2 1 / R06 链审计 3 / R07 门禁执行器 2 / 文档 3 / **未跟踪合同件的追加段 3** / **D-1 例外授权改动的文件 5（4 已跟踪 + 1 未跟踪）**）。

实际执行的命令与结果：

```bash
python3 scripts/enterprise-experience/source-freeze-preflight.py --repo . \
  --allowlist docs/development/deepseek-enterprise-mainline-closeout-freeze-allowlist-20260926.txt \
  --out "$(mktemp -d)/freeze.json"
```

| 项 | 值 |
| --- | --- |
| `tool_version` / `schema_version` | `source-freeze-preflight/0.1.0` / `siq-source-freeze-preflight/v1` |
| `head_commit` / `branch` | `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0` / `main` |
| `allowlist.requested` → `verified` | **26 → 26**（`unverified=0`、`excluded=0`、`missing=0`） |
| `unstable.scan_stable` | `true`（扫描前后 Git 状态与 dev/ino/大小/mtime 一致） |
| `worktree` | `tracked_changes=106`、`untracked_entries=726`、`unresolved_conflicts=0` |
| `signed` / `installable` / `published` | **`false` / `false` / `false`**（工具恒定值，未签候选不得冒充正式包） |
| `conclusion` / `blocking_reasons` | **`blocked`** / `["unreviewed_paths:806"]` |

**本轮已重跑三次以覆盖后补内容**（清单由 21 条扩到 **26 条**，纳入 D-1 例外授权修改的 5 个既有件）：
`generated_at=2026-09-26T07:54:13Z` → `21/21`、`unreviewed_paths:810`；
**最近一次 `generated_at=2026-09-26T08:15:29Z` → `26/26`**、`unverified/excluded/missing` 全 0、`scan_stable=true`、`tracked_changes=106 / untracked=726 / conflicts=0`、`signed/installable/published` 全 `false`、`conclusion=blocked`，**唯一**阻塞为 `unreviewed_paths:806`（该数字随并作者线写入而变动：810 → 806；**它不是本清单能收敛的量**）。
**注意：冻结时仍须再跑一次**——两份文档在核验之后还会继续追加内容（本小节本身就是追加物），**任何一次快照都会在写完后立刻变旧**，这是文档型交付物的常态，故允许清单与快照必须在**冻结时刻**重新生成，不得复用本节数字。

**结论怎么读（防止被误当成"冻结完成"）**：

1. 21 条路径**全部核验通过**，这证明的是"本轮这批文件的只读快照是确定且完整的"，**不是**"源码已冻结"、**不是**发行授权、**不是**发行来源清单（工具自带 `interpretation` 字段即为此而设）。
2. `conclusion=blocked` 的**唯一**原因是 `unreviewed_paths:810`——即允许清单之外的工作树路径未被复核。这 810 条**绝大部分是并行作者线的产物**，属于 R00.3 未取得独占的那部分，按 §3.2 与 D-1 的执行者**不得**代为判断或收编。**这条阻塞不是本轮能自行消除的，必须由主开发者决策**（见下方 D-7 请求）。
3. 工作树规模相对 R00.2 的只读盘点（`103 改动 / 682 未跟踪`）已增长到 `105 / 726`，增量与本轮 21 个新文件相符，并含并行作者线的持续写入。**冻结基线必须取冻结时刻的实时快照，不得复用本表数字。**

**本轮对 D-1 的一处边界偏差（主动登记，请复核；措辞已按实测订正）**：R02 的合同缺口修复是在三个合同件末尾追加"版本导航"段（`enterprise-discovery-schedule.v1.md`、`enterprise-skill-upload.v1.md`、`enterprise-skill-collection.v1.md`）。此前的写法是"三个**既有合同件**"，**该措辞不准确，已按 `git ls-files` 与 `git cat-file -e HEAD:<path>` 实测订正**：

| 事实 | 实测结果 |
| --- | --- |
| 这三个路径是否已跟踪 | **否**（`git ls-files --error-unmatch` 失败） |
| 这三个路径是否在 HEAD 中 | **否**（`git cat-file -e HEAD:<path>` 全部失败） |
| 本轮 R02 开工时是否已存在 | **是**（因此当时只能追加，不能新建） |
| 作者归属 | **未确认**（本未提交时期的工作树产物，可能是并行作者线） |

所以准确的表述是：**"追加到工作树内既存、未纳入版本控制、归属未确认的合同件"**，而**不是**"修改已跟踪的既有合同件"。三处追加均为纯文档段、不含实现逻辑、不改任何既有描述。**另需注意**：`packages/contracts/` 目录本身是已跟踪的（334 个已跟踪文件），所以"这个目录里的文件都已在版本控制下"这个直觉在这里不成立——这三个 enterprise-* 合同件恰好不在其中。请在冻结前**明确保留或回退**；回退方式为删除三个文件末尾的追加段，不涉及其他文件。

### R08.5 精确授权请求（D-7，需主开发者/用户逐项答复）

R08 的剩余内容**全部**卡在下列授权上，无一项可由执行者自行推进。按 §7「给出选项影响、不泛泛索要信息」的要求逐项列出：

| # | 请求 | 可选项与影响 | 不做会怎样 |
| --- | --- | --- | --- |
| D-7.1 | **是否允许提交**？ | (a) 允许提交到**新分支**（不动 `main`）——可保留本轮成果、可回退、不影响并作者；(b) 暂不提交——成果继续以未跟踪状态留在共享工作树，**有被并作者操作覆盖的风险**；(c) 只提交 21 条清单内路径——需先把它们从共享工作树分离（`git add` 指定路径）； | 未跟踪文件不受 Git 保护，工作树被清理即丢失 |
| D-7.2 | **是否允许推送/发 PR**？ | (a) 否（默认，本轮不改远程状态）；(b) 推送到新建远端分支供复核 | 无法远端复核；本轮无阻塞 |
| D-7.3 | **810 条 unreviewed 路径如何处置**？ | (a) 由主开发者指定并作作者线归属后分批纳入允许清单；(b) 本轮只冻结本 21 条、其余留待并作者各自收口；(c) 沿用 R00.3 的"未取得独占"判定，**整体冻结推迟**到并作者全部收口 | 冻结无法完成，R08.2 的"无冻结 commit、无独立审阅清单"缺口保持敞开 |
| D-7.4 | **三个合同件（工作树内既存、未纳入版本控制）的追加段保留还是回退**？ | (a) 保留（符合仓储既有约定，但需 D-1 例外确认）；(b) 回退（严格守 D-1，R02 的合同缺口改由新文件承载） | R02 的合同缺口修复方式悬空 |
| D-7.5 | **是否签发行候选**？ | 需先具备：冻结 commit + 清单收敛 + 独立审阅。**当前不具备**，故本轮不请求签发；仅请求确认"提交/推送/签发是三个独立门槛，不打包成一次授权" | 若合并授权，等于在未独立审阅的情况下签发 |
| D-7.6 | **是否部署**？ | 无目标、无身份、无备份恢复授权，**本轮不请求**（见 R09 / D-6） | — |

### R08.6 提交实施（D-7.1 已授权：新分支，不推送）

**授权**：主开发者 2026-09-26 答复 D-7.1 = **提交到新分支**（`main` 不动、不推送）。据此执行：

```bash
git checkout -b deepseek/enterprise-mainline-closeout-20260926   # 从 ebaaf3b 起
# 按允许清单逐条 git add（26 条），不 add 任何其它路径
git commit -F -    # 正文写明"共享工作树快照、非独立成果切片"及四项边界
```

| 项 | 值 |
| --- | --- |
| 分支 | `deepseek/enterprise-mainline-closeout-20260926` |
| 提交 | `6ba1f7c968823236e6f35a4c7ef33b76e8044944`（父提交 `ebaaf3b`） |
| 内容 | **恰好允许清单的 26 条路径**，`git show --name-only` 与清单**逐条一致、无清单外路径**；26 files changed, 4811 insertions(+), 91 deletions(-) |
| `main` | **未动**（仍为 `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0`） |
| 推送 | **未执行**（D-7.2 未授权） |
| 工作树 | 提交前 682 条状态项 → 提交后 **656 条**（682 − 26，**恰好是本清单这 26 条**；并作者线的其余改动**一条未动、未被覆盖、未被清理**） |

**提交时已写入提交正文的四项诚实边界**（复核者请先读这段，再读 diff）：

1. **这是"共享工作树快照"，不是"执行者独立成果"的干净切片**。Git 只能按**文件**暂存：四个**已跟踪**文件（`policies.py`、`main.py`、`test_policy_flow.py`、`test_enrollment_flow.py`）中**非本轮**的 hunk 与**本轮**的 hunk 一起进入快照（`main.py` 本轮只加 2 行，快照里是 42 行；`test_policy_flow.py` 本轮约 90 行，快照里是 215 行）。未跟踪文件则整篇进入。
2. **三个 `enterprise-*` 合同件在 HEAD 中不存在、未纳入版本控制**（实测），本轮只在其末尾追加"版本导航"段；其正文作者归属未确认。
3. **仍是未提交工作树上的结果**：门禁 `passed` ≠ 生产效果 ≠ 已签候选 ≠ 源码冻结 ≠ CI 存证；`signed/installable/published` 恒为 `false`。
4. **合并/复核必须与并行作者线逐条对照**（门槛 D-7.3 未决）。

**这次提交解决了什么、没解决什么**："26 个文件不再以未跟踪状态裸放在共享工作树、受 Git 保护"这一项**解决了**（这是 D-7.1 给的理由）；**没有**解决 `unreviewed_paths:806`、没有形成冻结 commit、没有签发、没有发布——`main` 上的 `ebaaf3b` 仍**不含**本轮成果。

**关于本文档与自身快照的滞后（不是遗漏，是常态）**：本小节、以及 R05.5/R07.8/R07.9/R08.6 与措辞订正，都是在 `6ba1f7c` **之后**才写入工作树的，因此 **`6ba1f7c` 快照里的这两份文档不含这些追加**。文档型交付物必然滞后于它自己的快照——这正是 R08.4 要求"允许清单与快照必须在**冻结时刻**重新生成、不得复用本节数字"的同一个道理。冻结时以当时重新生成的清单与 preflight 报告为准。

**本轮明确不做**：不提交、不推送、不建分支、不签发、不发布、不覆盖历史制品（§3.2）。上表 D-7.1/D-7.2/D-7.4 是**请求**，未获答复前保持现状。

### R08.7 允许清单第 5 次核验（39 条；R04 只读交付 + R09.13 证据纳入，2026-09-26）

R04.6 与 R09.13 新增 **6 条新文件路径**（4 条 R04 交付 + 5 条证据 = 9 条中已计入清单的 9 条，见下）后重跑同一条命令：

```bash
python3 scripts/enterprise-experience/source-freeze-preflight.py --repo . \
  --allowlist docs/development/deepseek-enterprise-mainline-closeout-freeze-allowlist-20260926.txt \
  --out /tmp/preflight-r0913-20260926T112124.json
```

| 项 | 值 |
| --- | --- |
| `allowlist.requested` → `verified` | **39 → 39**（`unverified=0`、`excluded=0`、`missing=0`） |
| `unstable.scan_stable` / `conflicts` | `true` / `0` |
| `head_commit` / `branch` | `0355db0…` / `deepseek/enterprise-mainline-closeout-20260926` |
| `worktree`（**报告自身字段，同口径**） | `tracked_changes=105`、`untracked_entries=714`、`unresolved_conflicts=0` |
| `signed` / `installable` / `published` | `false` / `false` / `false` |
| `conclusion` / `blocking_reasons` | **`blocked`** / `["unreviewed_paths:806"]` |

**逐条归属（与上一份 `r099b` 报告 `status_entries` 逐条相减，不靠印象）**：新增 **12 条、消失 0 条**，与本次改动**逐条对应**：

| 类别 | 条数 | 路径 |
| --- | --- | --- |
| `??`（新文件） | **9** | `rollback_approval_readiness.py`、`test_rollback_approval_readiness.py`、`enterprise-rollback-approval.v1.md`、`deepseek-r04-rollback-approval-handoff-20260926.md`、`docs/evidence/agentshield/openshell-siq-analysis-2026-09-26/` 下 5 个文件 |
| ` M`（改既有件） | **3** | 本执行记录、交接文档、允许清单本身 |

即：`tracked 102 → 105`（**+3**）与 `untracked 705 → 714`（**+9**）**完全由本次改动解释**，并作者线**一条未动、零消失**。清单条数 **30 → 39**（新增 4 条 R04 交付 + 5 条 R09.13 证据）。
**核验通过仍只表示这批文件的只读快照确定完整**，不是发布授权、不是源码已冻结；`unreviewed_paths:806` 与冻结时刻重跑的要求**照旧**（R08.4 的"不得复用本节数字"同样适用于本小节）。

### R08.8 自查：分支自身不自洽 —— R09.7 的验收工具**从未入库**（2026-09-26）

在提交前逐条核对允许清单时发现：**39 条路径里有 1 条虽然每次都通过了 preflight 核验，却从未进入任何提交** —— `scripts/enterprise-experience/http-contract-acceptance.py`（R09.7/R09.8 的 HTTP 契约级验收工具）。它是 `??`（未跟踪）状态，`git log --all --full-history -- <该路径>` **为空**、`git ls-tree -r HEAD` 命中 **0**。

**后果是分支自身不自洽**：它的合成回归测试 `scripts/enterprise-experience/test_http_contract_acceptance.py` **已在 `6516e58` 入库**（该提交 4 条路径之一），而该测试第 19 行按同目录定位被测脚本：

```python
SCRIPT = Path(__file__).with_name("http-contract-acceptance.py")
```

**因此在分支 HEAD 的干净检出上，这条测试连收集都过不去。**

**复现（不改共享工作树，按 §3.2 不用 `checkout` 换回 HEAD）**：用 `git archive` 把 HEAD 的该目录导出到临时目录再跑：

```bash
TMP=$(mktemp -d /tmp/branch-consistency-XXXXXX)
git archive HEAD scripts/enterprise-experience | tar -x -C "$TMP"
apps/control-api/.venv/bin/python -m pytest \
  "$TMP/scripts/enterprise-experience/test_http_contract_acceptance.py" -p no:randomly -q
```

实测 **exit 2**，收集期报错：

```text
E   FileNotFoundError: [Errno 2] No such file or directory:
    '<TMP>/scripts/enterprise-experience/http-contract-acceptance.py'
1 error in 0.05s
```

**根因**：不是 preflight 失效（它如实报了 `verified=39`，因为文件确实在工作树上），而是**我此前按"本轮改动的文件"挑选提交路径时漏选了这一个**——该工具一直只以未跟踪状态存在，工作树内跑测试因而一直是绿的，**只有把分支当独立制品检出时才会暴露**。

**处置**：本条路径在允许清单内、内容无变化，**已并入本次提交**（提交后该目录 20 条路径中工具与测试成对在场）。

**修复后复核（提交后、同一 `git archive` 手法）**：把新 HEAD 的该目录导出到临时目录再跑同一条 `pytest`，**`16 passed`、exit 0** —— 与提交前同一命令的 `FileNotFoundError` / exit 2 构成**正反对照**，证明这次的修法确实让该测试在分支上可运行，而不是把断言放宽或跳过。同时更正交接文档 §7 第 1 项此前"本轮文件不再以未跟踪状态裸放在共享工作树"的表述——**对 39 条路径里的这一条当时并不成立**。

**本轮其余路径未发现同类问题**（逐条比对，非印象）：对允许清单 39 条逐条查 `git ls-tree -r HEAD` 与在盘存在性——**不在 HEAD 的共 10 条**，其中 9 条正是本次提交新增的 R04 交付（4 条）与 R09.13 证据（5 条），**预期如此**；**剩下的第 10 条就是上面这个工具**。39 条**全部在盘存在**，无第二条"本应已入库却仍是未跟踪"的路径。

---

## R09：获准真实验收、升级恢复与部署交付

**状态：blocked（需授权与真实资源）**。对应 CL-02、07、08；ENT-002、005、012、016、021、022。

本单元不能仅凭任务书执行生产操作。需先取得目标、身份、操作范围、备份与恢复授权（**D-6 / D-7**）。缺平台或授权时列 blocked 于具体项，不声称全项目完成。

### R09.1 具体项清单（逐项写清"缺什么、要什么命令、什么算通过"）

下表按 §7「列 blocked 于具体项」的要求逐项展开。**每一项当前都是 blocked**，不存在"可顺手做掉"的项：全部需要真实资源或用户授权，且 §3.2 明确禁止执行者自行取得。

| # | 具体项 | 证明什么 | 缺的资源/授权 | 获准后的执行步骤 | 通过判据 |
| --- | --- | --- | --- | --- | --- |
| A1 | 真实 PostgreSQL 迁移回放与部署竞态 | 迁移在非 SQLite 上可回放、部署无竞态；补上 R07 恒 `skipped` 的门禁 | **数据库容器**（§3.2 要求先说明隔离方式、目标与回收方案并取得许可） | `python3 scripts/enterprise-experience/deployment-postgres-check.py`（临时回环实例） | 迁移全量前滚+回滚通过；竞态用例无失败；实例已回收 |
| A2 | 30 个浏览器验收脚本 | 前端—后端真实 HTTP 契约 | **运行中的控制面 + 浏览器环境** | 逐个 `python3 scripts/enterprise-experience/*-browser-smoke.py`（30 个） | 全绿；失败项单独归因，不加 skip |
| A3 | 真实 Linux AMD64 原生安装 | 安装→注册→持续发现→周期确认全链在真实设备上成立（R01 的"实际交付"） | **一台真实 Linux AMD64 设备 + 授权身份** | 按 `docs/enterprise-production-runbook-v1.md` 走安装；`setup_enterprise_linux.go` 路径 | 安装后设备能发现待确认计划并可完成确认；审计链完整 |
| A4 | Linux ARM64 / DGX 原生 | R03 证据拓扑中的 ARM64/DGX 视角 | **ARM64/DGX 机器**（D-6） | 同上，平台相关命令按 runbook | 同上，且平台按架构正确归类 |
| A5 | 受控 OpenShell 测试目标 | 真实强制点生效/回滚/漂移（含 R05 的 openshell-cli 分支） | **受控 OpenShell 目标 + 授权** | `openshell-deployment-live-check.py` / `openshell-preview-live-check.py` | 真实生效与真实回滚各有回执；授权过期时被拒 |
| A6 | 第二设备 + 第二租户 | 跨设备/跨租户隔离在真实身份下成立 | **第二设备、第二租户、独立审批者** | 用真实身份重跑隔离断言 | 跨租户不可达（404 先于 403）；独立审批者确非同一人 |
| A7 | 行为核验（`expect_deny` 非空） | R05 缺口 2：逼出 `enforcement_verified` 的**唯一**合法来源 | **受控探针目标 + 精确版本/范围 + 超时与结果证据** | 受控探针执行 → 真实 deny 观测 → 写入证据 | 有真实 deny 观测且非 mock；**不得由本轮制造** |
| A8 | Mac 浏览器访问远程 Linux | 跨平台前端行为 | **Mac 机 + 可访问的远程 Linux** | `environment-list-pagination-browser-smoke.py` 等 | 行为与 Linux 侧一致，无平台特有失败 |
| A9 | 正式构建的**签名**候选 | 从"未签候选"到"可交付包" | **D-7 签发授权**：受控签发入口引用、可信公钥、独立 verifier 身份 | `enterprise_candidate.py` → 外部签发 → `enterprise_finalize.py` → `verify.py` → `readback.py` | 双次全制品核验一致；`signed/installable/published` 由 false 变 true **且**有回读结果 |
| A10 | 部署与回滚实测 | 升级/失败/回滚在真实环境可恢复 | **D-7 部署授权**：目标环境、操作范围、备份与恢复方案 | 按 runbook 部署；失败则按恢复方案回退 | 部署成功 + 一次真实回滚成功 + 备份可恢复 |

### R09.2 R09 的三条硬约束（执行时不得违反）

1. `enforcement_verified` **只能由 A7 的受控探针真实产生**；在此之前该值保持**无生产者**，不得由任何测试夹具、mock 或本文件"推演"生成。
2. A3/A4/A5/A6 全链必须**同一候选**（同一 commit / 同一签名制品）；用不同提交的不同部分拼出来的"整体通过"不算数。
3. 任何一项在缺资源时**列 blocked，不降级为"部分通过"**；`signed/installable/published` 未签时恒为 `false`。

### R09.3 资源门槛的部分答复与"可用 ≠ 已用"（2026-09-26）

主开发者已答复 **D-6 的三项资源可用**：数据库容器、真实 Linux 实机、受控 OpenShell 目标。**本轮没有开始使用其中任何一项**，两条原因都不是流程形式主义：

1. **§3.2 的前置许可**：启动数据库容器或真实系统服务前，执行者须先说明**隔离方式、目标与回收方案**并取得该次许可。该方案**尚未提出、该许可也未取得**——本文件不把"资源可用"读成"可以自行动手"。
2. **A3/A5/A7 要的是"授权身份"，不只是"机器"**：真实安装（A3）、真实强制点（A5）、行为核验（A7）都要在真实身份/真实目标上操作，并涉及设备侧状态与宿主服务；§3.2 明确禁止执行者自行注册真实设备、执行真实权限变更或操作宿主真实 systemd。

**因此 A1–A10 的状态一行未变，仍全部 `blocked`。**"可用"只解除了"有没有这台机器/这个容器"，**没有**解除"能不能现在动它"。下一动作：按 §3.2 对**第一项**（A1 数据库容器）写出隔离/目标/回收方案并请求该次许可，取得后逐项推进，每一步仍按 A1–A10 自己的判据验收。（**本节是 R09.3 时点的状态。该下一动作已执行**：A1 于 R09.4 获批跑通、A2 于 R09.5 执行完毕；**A3–A10 至今仍全部 `blocked`**，A1/A2 的 `verified` 各带其限定，见 R09.4 / R09.5 / R09.6。）

### R09.4 A1 的隔离／目标／回收方案（§3.2 前置说明）与执行结果

本节即 §3.2 要求"先说明隔离方式、目标与回收方案"的那份说明。**方案先写、许可后到、再执行**：许可于 2026-09-26 取得（主开发者答复"批准并执行完整 A1"），执行结果见本节末的（8）。

#### （1）隔离方式：一次性回环实例，与宿主既有服务无交集

| 隔离维度 | 具体做法（均为脚本内既有实现，非本轮新增） |
| --- | --- |
| 镜像 | `postgres:17-alpine`，**本机已存在**（实测 `sha256:ff80089083d7365046af7f03d949a2defa14e0b09e14bd5b8f08a242291be8b2`）→ **无需拉取**；脚本以 `docker image inspect` 断言，缺镜像直接拒绝（不 pull） |
| 网络 | `--publish 127.0.0.1::5432`：**只绑回环 + 由内核分配随机端口**；端口只能经 `docker port <本容器名>` 读回，**不可能**落到既有库上 |
| 存储 | `--tmpfs /var/lib/postgresql/data:rw,size=256m`：**无卷、无宿主持久化**，容器销毁即数据消失 |
| 资源 | `--memory 512m --cpus 1` |
| 身份 | 仅 `X-Dev-*` 开发身份头 + `SIQ_AS_DEV=1`；**不注册真实设备、不执行真实权限变更、不写真实元数据** |
| 凭据 | 口令每次随机 24 字节，只经环境变量注入容器；日志落盘前 `replace(password,"[REDACTED]")` |
| 环境 | 子进程环境**白名单**（`PATH`/`HOME`/`LANG`）+ 指向本容器的 `SIQ_AS_DATABASE_URL` + 临时 `SIQ_AS_SIGNING_KEY_FILE`；**不读真实 `.env`／私钥／种子**（§8.7） |
| 容器命名 | `siq-deployment-check-<12 位随机十六进制>`，与既有容器名（`siq-platform-*`、`siq-org-iam-postgres` 等）**无交集**；回收时按**精确名字**删除 |

#### （2）宿主上正在运行的真实服务（**只读盘点，本方案一律不触碰**）

`docker ps` 实测（同机还跑着整条 SIQ 栈与多个无关项目）：`siq-platform-agent-security-api-1`／`-web-1`、`siq-platform-postgres-1`（`127.0.0.1:55432`）、`siq-org-iam-postgres`（`0.0.0.0:5434`）、`siq-platform-gateway-1`、`siq-platform-iam-1`、`siq-platform-hub-1`、`siq-platform-workbench-1`、`siq-platform-flow-1`、`milvus-*`、`minio`、`pgadmin`、`gpcapital-*`、`hrsight-postgres`、`docker-postgres-1`（`0.0.0.0:15432`）、`postgres:16`（`0.0.0.0:5432`）、`qwen38-*`、`qwen3-vl-*` 等。

因此本方案明确**不做**：不停止／重启／进入任何既有容器；不连接任何既有数据库（尤其 `siq-platform-postgres-1`、`siq-org-iam-postgres`）；不执行 `docker system prune`／`rmi`；不改宿主 systemd；不动兄弟仓源码/配置。已占用的回环端口为 `8005／54431／55432／59100／59101／63871`，与本实例的随机端口由内核互斥分配。

#### （3）目标：证明什么、**不**证明什么

证明：迁移在**真实 PostgreSQL**（非 SQLite）上可前滚/回滚（`upgrade 0017 → downgrade 0016 → upgrade head → downgrade 0020 → upgrade head`）；有数据的**破坏性回滚被拒绝**（`device-scoped discovery cannot be merged`、`discovery schedule history must be preserved`）且 head 与保留行数不变；部署竞态下**真实行锁**可被 `pg_stat_activity` 观测（`wait_event_type='Lock'`）、两请求得到同一 `deployment_id` 且 `execute` 恰一次；调度器 PostgreSQL worker 的真实锁竞争／跨租户唯一约束／审计失败原子回滚；并让 R07 的门禁 `migration_replay_postgres` **实际执行并留证**。

**不**证明：不是生产效果、不是真实身份验证（证据里 `production_identity_tested: false`）、**不产生 `enforcement_verified`**（R09.2 第 1 条：该值只能由 A7 受控探针产生）、不改变 `signed/installable/published`（恒 `false`）。

#### （4）回收方案：失败路径也必须删干净

1. 脚本 `try/finally`：无论断言成功失败，`docker rm -f <精确容器名>` 并**断言返回码为 0**；容器本身另带 `--rm`；tmpfs 与 `TemporaryDirectory` 随进程销毁。
2. 收尾只读核验（三项全过才算回收完成）：`docker ps -a --filter name=siq-deployment-check-` **为空**；`docker image ls postgres:17-alpine` 镜像 id **与盘点一致**；既有容器的 `Up`/端口映射**与（2）的盘点逐条一致**。
3. 证据保留：本次新建的独占输出目录（`0700`；拟用 `/tmp/a1-evidence-<时间戳>` 与统一报告的 `/tmp/gate-run-A1-<时间戳>.json`）——**均在仓库外、不入版本控制**，含 `result.json` 与已脱敏日志。
4. 预算：单次约 1–3 分钟；峰值 ≤512MiB 内存 + 256MiB tmpfs + 1 CPU。

#### （5）获准后要跑的命令（原样照抄，可复核）

```bash
# ① A1 本体（一次性实例，留证目录须为**不存在**的新目录）
python3 scripts/enterprise-experience/deployment-postgres-check.py /tmp/a1-evidence-$(date +%Y%m%dT%H%M%S)

# ② 并入统一门禁报告（会跑全部可离线门禁约 5 分钟；不用 --only，因为它会强制结论为 partial_run_not_a_gate）
python3 scripts/enterprise-experience/enterprise-gate-run.py --repo . \
  --out /tmp/gate-run-A1-$(date +%Y%m%dT%H%M%S).json --enable-ephemeral-postgres-gate
```

#### （6）A1 依赖的脚本**不在本轮允许清单里**（归属未确认，必须说清）

实测：`scripts/enterprise-experience/deployment-postgres-check.py` 在 Git 中**已被跟踪**，但工作树版本与 HEAD 版本**不同**（`git diff --stat` = 96 insertions / 15 deletions），且该路径**不在本轮 26 条允许清单内**。本轮对它的全部动作只有**读取**（`Read`），**没有写入一个字**。差异内容属并行作者线，例如：就绪探测由 `docker exec pg_isready` 改为直连**已发布 TCP 端点**、迁移序列由 3 步扩到 5 步（含 `downgrade 0020`）、新增 `0017` 的破坏性降级守卫用例、日志同时收 stdout+stderr。

这对 A1 有三个直接后果，获准前必须先讲清：

1. **A1 的证据将引用一个"未确认归属、未入允许清单"的脚本**——本节的方案与事实全部基于**工作树当前版本**（含上述并行改动），不是 HEAD 版本。若并作者在 A1 运行前后再改它，`check_postgres_evidence` 的 `script_sha256` 断言会**明确失败**（这是设计使然：证据必须对应实际执行的那份脚本）。
2. **它使"同候选"多一个待决项**：R09.2 第 2 条要求同一候选，而 A1 的取证工具本身不在候选清单里——要让 A1 成为**同一候选**下的验收，需并作者确认该脚本的归属并把它并入清单，或明确接受"工具未入候选"这一偏差。
3. **本轮不把它加进允许清单、不提交它**：那属于并作者对其改动的处置（D-7.3）。

#### （7）A2 的目标问题（一并提出，因为宿主上的控制面**不是本候选**）

`docker inspect` 实测：`siq-platform-agent-security-api-1` 的镜像是 `sha256:24a03ceb4b48…`、**启动于 2026-09-24**，无对外发布端口（仅 `siq_platform_backend`/`siq_platform_data` 网络内可达），未设 `SIQ_AS_DEV=1`。它**不是**本工作树（`ebaaf3b` + 本轮改动）的构建产物，用它跑 30 个浏览器验收**违反 R09.2 第 2 条"同一候选"**，只能算诊断、不算 A2 验收。因此 A2 需要单独答复目标（见交接 §7）。

---

#### （8）执行结果（2026-09-26，许可后）

| 项 | 结果 |
| --- | --- |
| 命令①（A1 本体） | `/tmp/a1-evidence-20260926T162846` → `{"passed": true, "checks": 18}`，**7.0 秒**，`migrated_head=0028` |
| 命令②（全量门禁 + 该门禁） | `/tmp/gate-run-A1b-20260926T163429.json` → **49 passed / 0 failed / 0 blocked / 2 skipped**，`conclusion=gates_incomplete`，4 分 49 秒 |
| 三次独立运行一致性 | 直跑、门禁内单跑（F2）、全量（A1b）三次的 `migrated_head` 均为 `0028`、`script_sha256` 均为 `2802b08969f0…`、`checks` 均为 18 |
| 18 项检查覆盖 | 部署预约重放与审计、4 条持久化/撤销/审计失败语义、`openshell` 成功／适配器失败／审计失败后置 3 种结局、真实行锁串行化、`0017` 破坏性降级守卫、`device-scope` 自动降级被拒、调度器 4 项（含真实锁竞争与跨租户唯一约束） |
| 身份与真实性声明 | `ephemeral_database: true`、**`production_identity_tested: false`**；**未**产生 `enforcement_verified` |

**回收核验（方案（4）的三项只读检查，全部通过）**：

| 检查 | 结果 |
| --- | --- |
| `docker ps -a --filter name=siq-deployment-check-` | **0 行**（无残留容器） |
| `docker image inspect postgres:17-alpine` | `sha256:ff80089083d7365046af7f03d949a2defa14e0b09e14bd5b8f08a242291be8b2`，与盘点**逐字一致**（镜像未被改动、未被拉取） |
| 宿主既有容器集合 | `docker ps` 与运行前盘点**逐行 diff 为空**（45 条不变，无新增/删除/重启）；`siq-platform-postgres-1`（`127.0.0.1:55432`）、`siq-org-iam-postgres`（`5434`）、`siq-platform-agent-security-api-1/web-1`、`siq-platform-gateway-1`（`192.168.2.121:10082`）、`siq-platform-workbench-1`（`:1361`）端口映射均未变 |
| 泄密检查 | 证据目录内**无** 48 位十六进制独立串（仅 64 位 sha256 摘要的前缀匹配）、无 `password=` 形式暴露；目录权限 `700` |

**A1 到此的状态 = `verified`（隔离验证通过，**不是**实际交付）**：它证明的是"迁移与竞态在真实 PostgreSQL 引擎上成立"，证据来自**一次性、回环、无卷、合成身份**的实例；它**不**证明生产效果、**不**是已签候选、**不**产生 `enforcement_verified`，也**不**关闭任何 ENT。同一候选偏差仍在：取证脚本属并作者未提交改动（见（6））。

### R09.5 A2（30 个浏览器验收）实跑结果：**25/30 通过，5 项按 UI 断言归因**

**先纠正一处我自己提出的错误前提**：我在 R09.4（7）把 A2 描述为"需要运行中的控制面"，并据此请了"一次性服务实例"的许可。实测**不成立**：30 个脚本**全部自带隔离环境**，**不需要任何外部控制面、不需要容器**，因此**不需要那份许可**；另 **2 个需要原生 Edge 与框架连接器二进制**（临时 `go build` 即可，也不需要控制面实例）。该许可**未被使用**。

**一处被 R07.11 更正的范围描述（重要，方向是"我原来低估了这批脚本"）**：本节初稿写的是"28 个自带隔离环境 … 其中 **3 个**还自带隔离 dev API"，把这一类别笼统称作 "dev API"。R07.11 逐脚本核对后**实测为 8 个**，而且它们做的不是 mock：每个都先 `sock.bind(('127.0.0.1', 0))` 取空端口，再以子进程 `uvicorn.run(app.main:app, host="127.0.0.1", port=…)` 起**真实控制面进程**（`SIQ_AS_DEV=1` + `SIQ_AS_ALLOW_SQLITE=1` + 临时 `sqlite:///…/api.db` + `X-Dev-*` 合成身份），即**真实 socket 上的真实 HTTP**。名单（由套件按 `SIQ_AS_DEV` 标记逐个判定并写入 `result.json` 的 `real_dev_api_scripts`，**不是硬编码**）：`business-navigation`、`candidate-review`、`change-execution`、`change-review`、`deployment-preview`、`deployment-recovery`、`onboarding`、`workspace`。**A2 的 5 个失败项全部落在这 8 个之内**——见下条。

| 项 | 实测 |
| --- | --- |
| 脚本总数 | **30**（`ls scripts/enterprise-experience/*-browser-smoke.py \| wc -l`） |
| 参数族 | 4 个 `--output`；22 个 `--web`+`--out-dir`；4 个 `--web`+`--out`；2 个 `--edge`+`--connector-dir`+`--web`+`--out-dir` |
| Python | `/home/maoyd/miniconda3/bin/python`（**本机唯一装了 playwright 的解释器**，仓储文档同款用法）；浏览器 `~/.cache/ms-playwright/chromium-*` **已存在** |
| 前端构建 | 按仓储既有约定：`VITE_DEV_MODE=true npm exec -- vite build --outDir /tmp/siq-a2-dev-web-SIMULATED-NOT-RELEASABLE-<rand>`（**模拟身份、独立临时目录、不可发布**，与正式构建分离，符合 §8.6） |
| 结果 | **25 PASS**（含 `four-entry-navigation` 24/24、`overview-four-entry` 24/24、`runtime-binding-explorer` 45/45，其余按各自 JSON 自述累计 **199 项** `checks`；口径不一致，**不作单一总数**） |
| **5 FAIL** | `change-execution`、`deployment-preview`、`workspace`、`onboarding`、`candidate-review` —— **全部失败在 UI 可见性/文本断言，无一在业务逻辑** |

**5 项失败的逐条归因（且都指向并作者未提交的前端改动）**：

| 脚本 | 实测失败点 |
| --- | --- |
| `change-execution` | `expect(dialog.get_by_text('上次提交结果尚未确认')).to_be_visible()` 超时；该文本的渲染条件是 `uncertain && submission?.state !== 'recorded'`（`ChangeExecutionDialog.tsx:28`），文本**存在于构建产物**，即"条件不成立"而非"文本不存在" |
| `deployment-preview` | 同一断言、同一文本、同一对话框 |
| `workspace` | `assert {label.strip() for label in links} == labels, role` → 角色 **viewer** 的链接集合与预期不符 |
| `onboarding` | 首个交互即失败：`get_by_label('设备可访问的控制面根地址')` **not visible**（该 label 在 `EnvironmentSetup.tsx:99`，且**存在于构建产物**）；原生 Edge 与 `hermes-connector` 已按临时构建就位（9.7MB / 3.8MB），失败发生在浏览器侧 |
| `candidate-review` | 同 `onboarding`：同一 label、同一 `not visible` |

**为什么可以判断"不是本轮引入"**（三条可复核证据）：① 本轮三个提交（`6ba1f7c`/`1f50a16`/`7209a76`）的路径清单里 **`apps/web` 一条都没有**；② `apps/web` 在工作树里有 **122 条未提交改动**（`git status --porcelain -- apps/web`），其中恰好包含失败点所在的组件：`ChangeExecutionDialog.tsx`、`ChangesPage.tsx`、`Layout.tsx`、`EnvironmentSetup.tsx`（后者 `+47/−18`）；③ 25 个通过项与这 5 个失败项用的是**同一份** dev 构建与同一套 mock。**结论**：这 5 项应交给前端作者线复核（"脚本期望过时"还是"组件可见条件真的变了"需他们裁决），**本轮不改这些文件、不加 skip、不记为通过**。

**A2 证明了什么、没证明什么**：证明的是"当前候选的**前端在模拟身份条件下的交互行为有 25 个脚本通过**，且其中 8 个脚本的断言链路**穿过了真实控制面进程与真实 HTTP**"；**不**证明**契约级**性质，**不**证明真实 IAM（`production_deployed: false`、身份为合成的 `X-Dev-*`）。因此 R09.1 里 A2 的"证明什么"一栏（"前端—后端真实 HTTP 契约"）**表述过宽**。

**这 8 个脚本的真实性有独立证据，不是我读了源码就下的结论**：E1 保留下来的逐脚本证据目录 `/tmp/siq-gate-browser-evidence-7b8qd7p5/` 里，失败脚本 `change-execution` 与 `deployment-preview` 各自写出了 `target-labels.json`，其内容是**服务端生成的标识符**（`cr_6f5601a2…`、`pol_ee861253…`、`env…` 等）——**只有真的完成了 HTTP 往返、并从真实响应里读到数据，才可能出现这些 id**。也就是说：这 5 项失败**发生在真实 HTTP 往返之后**，不是"连不上后端"或"契约不符"。**注意这仍不等于契约验收**：失败/通过都是**脚本自述**的 UI 断言结论，套件并不独立核对状态码、JSON 形状、404-先于-403 的隔离序、错误码与响应头——**这些正是"真实 HTTP 契约验收"要另立方案去补的**，也正是一开始请的"一次性实例"许可的正当用途。

**本轮自己踩的坑（都已修）**：① 先按 `--output` 一刀切调用 30 个脚本 → 26 个 `exit=2`；② 改用"检测 `"--web"`"时用了双引号模式，漏掉脚本里的单引号写法 → 仍是 26 个 `exit=2`。两次都是**我的调用方式错，不是脚本失败**——若不看 stderr 就会把"参数不对"误记成"26 项失败"。另：8 个脚本用 `--out` 而非 `--out-dir`。③ **ruff 误报绿**：仓库根没有 `pyproject.toml`/`ruff.toml`，直接 `ruff check scripts/...` **不带配置**会退回默认规则并打印 `All checks passed!`，而仓库基线是 `--config apps/control-api/pyproject.toml`（`line-length=120`，select `E,F,W,I,UP,B`）。按基线复跑后确实抓到**我自己新引入的 1 条 E501**（已改用相邻字符串拼接修掉）。**正确调用**：`apps/control-api/.venv/bin/ruff check --no-cache --config apps/control-api/pyproject.toml <files>`；本次残余 = **5 条既存**（1 条 `UP017` 在 `utc_now`、4 条 `E731` 测试内 lambda），**均不在我改动的行上**。

**门禁登记的更正**：`enterprise-gate-run.py` 里 `browser_acceptance` 的登记原因原为 `requires_running_services`，**实测不准确**（25 个脚本不需要任何服务）。已改为实测事实（需要前端模拟构建 + playwright，且当前有 5 项 UI 断言失败）。**未**把它接成可执行门禁：一次全跑约 4 分钟且需 dev 构建，是否纳入统一报告属 R07 设计决策，**留作下一动作**。（**该"下一动作"已完成，见 R07.11**：接法不是"无脑塞进统一报告"，而是**默认关闭**的第二条 opt-in 门禁；本节末尾"未把它接成可执行门禁"是 R09.6 时点的状态描述，**已被 R07.11 取代**。）

### R09.6 门禁登记更正 + 新增断言 + 复跑核验

**改了什么**（都在 `scripts/enterprise-experience/`，未新增路径）：

1. `enterprise-gate-run.py` 的 `DECLARED_UNAVAILABLE`：
   - `browser_acceptance`：`reason` 由 `requires_running_services`（**实测不成立**）改为 `requires_frontend_simulated_build_and_playwright`；`note` 写实测事实（28/30 不需控制面、实跑 25/30、5 项已归因、自述 `mocked browser only`）。
   - `migration_replay_postgres`：`note` 补一句"该路径已于 2026-09-26 获批并在一次性回环容器上执行通过，需 `--enable-ephemeral-postgres-gate` 显式启用"——**原因仍是资源要求 + 需逐次许可，不是"不可执行"**；未显式启用时仍如实记为 `skipped`。
2. `test_enterprise_gate_run.py` 新增 `test_browser_acceptance_declaration_carries_the_measured_reason`：断言登记集合恰好是那 3 项、`browser_acceptance` 的原因**不再是**被推翻的旧值、note 含 `mocked browser only`、且每项 `reason`/`note` 都非空。**测试数 24 → 25，全过。**

**实跑核验**（不是只跑单测）：

| 核验 | 命令 | 结果 |
| --- | --- | --- |
| 单测 | `apps/control-api/.venv/bin/python -m pytest scripts/enterprise-experience/test_enterprise_gate_run.py -q` | **25 passed**（1.30s） |
| 静态检查（**必须带仓库配置**） | `apps/control-api/.venv/bin/ruff check --no-cache --config apps/control-api/pyproject.toml <两文件>` | 余 **5 条既存**（1 `UP017` + 4 `E731`），**均不在改动行**；我新引入的 1 条 `E501` 已修 |
| 报告渲染（真实运行，**默认不碰 docker**） | `enterprise-gate-run.py --repo . --out /tmp/gate-A2record-20260926T165110.json --only rulepack_python_go_identity` | `conclusion=partial_run_not_a_gate`；三行 `skipped_gates` 正确带出**新** `reason` 与新 `note`，`not_evidence_of` 五项齐全 |
| 冻结前盘点复跑 | `source-freeze-preflight.py --allowlist ... --out /tmp/preflight-r09-20260926T165214.json` | `requested=26 / verified=26`（内容级 sha256）、`unverified=excluded=missing=0`、`scan_stable=true`、`conflicts=0`、`head_commit=7209a76`、`unreviewed=806`、`conclusion=blocked`；**清单仍 26 条**（本轮未新增路径） |

**提交与工作树账目**：本轮 4 条路径已提交为 **`34722e8`**（`git show --name-only` 与该 4 条逐条一致，无清单外路径），分支 `deepseek/enterprise-mainline-closeout-20260926`，父 `7209a76`，**未推送**，`main` 仍 `ebaaf3b`。**账目可复核**（用 `--untracked-files=no` / `=all` 两个**同口径**指标，而不是会折叠未跟踪目录的默认 `git status --porcelain`）：提交前 preflight 记 `tracked_changes=106`、`untracked=704`；提交后实测 `tracked-changed=102`、`untracked=704` —— **差恰好 4**，等于本次提交路径数，并作者线一条未动。（此前文档里"656 条状态项"用的是默认折叠口径，与 preflight 的 810/806 不同源，**不宜跨口径比较**，此处改用同口径数字。）

**未做（刻意）**：没有把 30 个浏览器脚本接成可执行门禁。理由：整批约 4 分钟、需先做一次模拟身份前端构建、且当前有 5 项失败——把它塞进统一报告会让"门禁红"变成前端线的既有状态而非本轮可判定的信号。（**本条在 R07.10 时点成立，现已由 R07.11 取代**：该决策当时的顾虑之一正是"失败会污染统一报告"，R07.11 的解法是**默认关闭**（不传开关就仍是本节的形态与结论），只有显式 `--enable-browser-smoke-gate` 时才如实报红。**下面 R07.11 的记录是本条的后续，不是矛盾。**）

### R09.7 「真实 HTTP 契约验收」的 §3.2 前置方案（**状态：已批准并执行，结果见 R09.8**）

**为什么需要独立做**：A2 的 8 个脚本已经走真实进程与真实 HTTP（见 R09.5 更正），但它们只输出**脚本自述的 UI 断言**结论；套件不独立核对状态码、JSON 形状、隔离序、错误码族与响应头。本次要补的正是这一层——**不是**再跑一遍浏览器，也**不是**要一个"生产环境"。

**目标（target）**：在本机起**一次性**控制面进程，只绑回环，进程与数据全部落在临时目录，跑完回收。

| 项 | 取值 |
| --- | --- |
| 解释器 / 服务 | `apps/control-api/.venv/bin/python`（已含 `uvicorn 0.52.2`，**不安装任何依赖**）；`uvicorn.run(app.main:app, host="127.0.0.1", port=<bind(0) 取到的空端口>)` |
| 模式 | `SIQ_AS_DEV=1`、`SIQ_AS_ALLOW_SQLITE=1`、`SIQ_AS_DATABASE_URL=sqlite:///<mktemp>/api.db`；**非生产模式**，因此不触碰任何真实数据库 |
| 身份 | `X-Dev-Tenant-Id` / `X-Dev-User-Id` / `X-Dev-Roles` 合成身份（`app/security.py:180-188` 仅在 dev 模式采纳）。**明确：这不是真实 IAM 身份** |
| 环境 | 白名单构造的 `env`（只含上述变量与临时 `HOME`），**不读取真实 `.env`、不继承运行环境里的秘密**；签名种子写在临时目录内，**不是真实秘密** |
| HTTP 客户端 | 标准库 `urllib.request`（**不新增依赖**） |
| 容器/宿主 | **零容器**；**不启动/不触碰**任何宿主真实服务、数据库或 systemd；只监听 `127.0.0.1` |

**要核对的判据（逐条写清，任一不符即非零退出，不降级为 skip）**：

1. **启动即健康**：`GET /health` → 200 且 JSON 形状与合同一致（字段名与类型，不只是"能连上"）。
2. **租户隔离序（404 先于 403）**：用租户 A 的身份取租户 B 的对象 → **404**；取本租户但**不存在**的对象 → 404；取存在但**无权限**的对象 → **403**。三者顺序不能颠倒（"先 403 后 404"会把对象存在性泄漏给无权者）。
3. **错误码族与形状**：至少覆盖 401/403/404/409/422 各一次，核对状态码与其在合同文档中声明的响应体字段。
4. **响应与审计中无秘密**：把临时签名种子的字节串、身份头的原始值作为**哨兵串**，断言**不出现在**任何响应体、审计查询结果或服务端 stdout/stderr 里。
5. **审计与状态同事务**：发一个会改写状态的请求，随后查询审计：要么"状态变了且审计有对应条目"，要么"都没变"，**不接受**两者不一致。
6. **fail-closed 启动拒绝（最容易被忽略、也最值得核）**：**不带** `SIQ_AS_DEV` 且**不给** PostgreSQL/JWKS 配置时启动，进程必须**拒绝启动并非零退出**（`app/config.py:73-96,119-136` 的校验），且错误输出里**不含**秘密。这条不验证"能跑"，验证的是"配置不全时不肯跑"。
7. **分页/一致性类**：按合同文档声明的分页与计数语义核对一个列表端点的返回（若有声明的计数头/字段，则核对它；**只核对已声明的**，不发明新合同）。

**隔离与回收方案（§3.2 要求逐项说清）**：

- **隔离方式**：`mktemp -d` 独立目录承载 SQLite 与签名种子；只绑 `127.0.0.1`；`env` 白名单；不读真实 `.env`/私钥/种子；不联网（除本机回环）。
- **目标**：仅本机回环进程；宿主上的既有服务、容器、数据库一律**不碰**。
- **回收**：`finally` 中终止**进程组**并等待退出、断言端口已释放（`ss -ltn` 不含该端口）、断言临时目录已删除且不存在、断言无残留 `.db`/`.db-wal`；异常路径同样执行回收并如实记录失败原因。
- **失败面与超时**：每一步都有超时（启动等待、请求、回收），超时即失败退出，**不挂住**、不留孤儿进程。

**证据（独占创建，已存在即拒绝覆盖，exit 3；不覆盖任何既往报告）**：工具版本、`app/` 源码 sha256、进程 PID 与端口、每条判据的实测值（状态码/字段/命中与否）、退出码、回收核验结果，以及一句范围自述（**合成身份、非生产、非真实设备、不产生 `enforcement_verified`**）。

**本方案不证明什么（防止被下游误读）**：不是真实 IAM、不是生产模式、不是真实设备、不是签发/部署依据；`enforcement_verified` 仍**只**能由 A7 的受控探针产生（R09.2 第 1 条）。

**所需许可（§3.2 逐次许可）**：**启动一个一次性本地服务进程**（回环、临时目录、跑完回收）。不涉及容器、真实数据库、真实身份、宿主服务。

**状态变更（2026-09-26，保留上文以免读者失去方案原文）**：本节上文是**执行前的方案**。主开发者当日答复该次许可为**"批准并执行完整 R09.7"**（即 7 类判据全跑；状态写入只允许发生在那一份一次性临时 SQLite 内），我随后执行，实测结果见 **R09.8**。方案与实现的两处差异（都是实现时的收紧或更正，已在下文逐条写明）：① 判据 2 的"跨租户取对象 → 404"实测改用**对象级写端点**并用**同正文**判定不可区分；② 判据 6 的探针前提写错过一次（见 R09.8 的"首次红"）。

### R09.8 真实 HTTP 契约验收实跑（R09.7 方案的执行结果）

**授权依据**：§3.2 逐次许可——主开发者 2026-09-26 从四个候选项中选定本项并**批准完整执行**（7 类判据全跑；状态写入仅限一次性临时 SQLite）。未新增依赖、未起容器、未碰宿主服务/数据库/systemd。

**交付物**：`scripts/enterprise-experience/http-contract-acceptance.py`（新增，sha256 `34b4840b…`，32441 字节；允许清单第 29 条）。**它不是门禁**：没有 `--enable-*` 开关、不参与 `enterprise-gate-run.py` 的 8 类门禁、默认不会被任何既有流程触发——只按 §3.2 逐次许可运行并出货报告。是否接成第三条显式 opt-in 门禁，留作下一动作（属 D 门槛决定，我不擅自接）。

**两次运行（都保留，不做覆盖）**：

| 运行 | 证据目录 | 判据 | 不成立 | 退出码 | 结论 |
| --- | --- | --- | --- | --- | --- |
| ① 首次 | `/tmp/r09-contract-20260926T175013/report.json` | 83 | **2** | 1 | `contracts_failed` |
| ② 更正探针前提后 | `/tmp/r09-contract-20260926T175026/report.json` | 83 | **0** | 0 | `contracts_held` |

**首次那两条红是"我的探针写错"，不是产品缺陷（必须留在记录里，因为它正是这类验收最容易造出的假信号）**：我把 `SIQ_AS_ALLOW_SQLITE` 写成了"dev 模式下不显式置 1 就拒绝"，而 `app/config.py:78` 的真实语义是 `allow_sqlite = _bool("SIQ_AS_ALLOW_SQLITE", dev_mode)`——**默认值就是 `dev_mode` 本身**，即 dev 模式**默认允许** SQLite；被声明的拒绝条件是"**显式否认**"（`SIQ_AS_ALLOW_SQLITE=0`）。按代码行更正探针后，该条如声明般拒绝（`returncode=1`，报出"SQLite 仅显式开发模式允许"）。教训直接写进工具注释（`http-contract-acceptance.py` 的 `judge_fail_closed_startup`）：**探针要对着代码行写，不要对着印象写**。

**逐组实测（第二次运行，8 组 83 条全成立）**：

| 判据组 | 条数 | 关键实测值 |
| --- | --- | --- |
| `health_json_shape` | 4 | `/health` 与 `/api/v1/health` 均 200 且体为 `{"status":"ok"}` |
| `locate_before_permission` | 9 | 同租户无 `env:manage` → **403** `forbidden`；同租户不存在的 id + 无权限 → **404**（不是 403）；跨租户 id + 有权限 → **404**；两者**正文逐字节相同**（`{"detail":"not_found"}`，即存在性不可区分）；跨租户 404 后对象 mode 仍为 `discovery` |
| `error_code_family` | 11 | 401 `missing_credentials` / 403 `forbidden` / 404 `not_found` / 409 `environment_name_conflict` / 422（非法枚举、缺必填、空串过滤、超长过滤）各中；**角色矩阵实测**：`tenant_admin` 无 `audit:read` → 403，`auditor` → 200 |
| `audit_state_same_transaction` | 11 | 建对象留下**恰 1 条** `environment.create`（`actor_id`/`actor_type` 为合成身份）；`summary` 实测为 `{}`（不落内部字段）；成功改 mode 产生**成对**的 `mode.update`；**409 回滚后审计总数 1→1**、**404 定位失败同样 1→1**（失败不写审计）；租户乙按同一 `resource_id` 查询返回 **0 行** |
| `declared_pagination` | 23 | `X-SIQ-List-Limit/Returned/Truncated` 与 `X-SIQ-Next-Cursor` 均按 `enterprise-audit-query.v1.md §5` 出现；`include_total` 全量口径 **4**（3 建 + 1 改），**翻页后仍为 4**（不受 cursor 影响）；`limit=999` → 钳到 **200**；租户乙同过滤条件 total = **1**（租户谓词内、不并甲）；`enterprise-environment-list.v1.md` 全条：未给 `limit` 时全量 3 条且 `Truncated=0`、`Cache-Control: no-store`、`limit=1` 时给环境 id 游标、**逐页走完 3 条不重不漏**、cursor 不带 limit → 422 `environment_list_cursor_unavailable`、**跨租户 cursor 同 422 同 detail**、超 64 字符 → 422 |
| `no_secret_echo` | 13 | 三类**真秘密材料**（dev JWT 共享密钥 47 字符、签名种子 base64 44 字符、合成 bearer 32 字符）在 **4 个面**全部未命中：HTTP 响应/响应头、审计事件正文、服务 stdout/stderr（实测 392 字节、**非空**）、临时工作目录内文件（含一次性 SQLite 库，`hits=[]`） |
| `fail_closed_startup` | 9 | 4 类拒绝全部 `returncode=1` 且报出原因：生产模式缺 DB URL、生产模式给 SQLite、生产模式缺 JWKS、dev 模式**显式否认** SQLite；**均为配置期静态判定**（探针只调 `load_settings()`，未起服务、未连数据库） |
| `teardown` | 3 | 进程已退出 / 回环端口已释放（重新 bind 成功）/ 临时目录已移除，全 `true` |

**回收的独立复核（不只信工具自述）**：运行后另行核对 —— `ls -d /tmp/siq-http-acceptance-*` **无残留**；工具自报 `head=66aae3d`、`branch=deepseek/enterprise-mainline-closeout-20260926`、工作树 `102 / 807`。**口径警告（沿用本轮纪律）**：该 807 是 `git status --porcelain --untracked-files=all` 的**逐文件**计数，与 preflight 报告里的 `untracked=705` **不同源**（preflight 自有一层目录归并/排除口径），**两者不可相减、不可跨口径比较**；同口径对比才是"变没变"的依据。服务日志全文（392 字节）只含 uvicorn 启动/关闭行与 `app.main:75` 的 dev 模式告警，**无秘密**。

**方案→实现的第三处差异（回收核验手法）**：R09.7 方案写的是用 `ss -ltn` 断言端口已释放；实现改为**对该端口重新 `bind()` 成功**来判定。等价、少一个外部命令依赖，且失败面更窄（绑得上就是没人监听）。

**这份证据证明什么、不证明什么**：

- **证明**：在当前工作树候选上，上述**已声明**的契约条目在真实 HTTP 往返下成立（合成身份、dev 模式、临时 SQLite、回环 socket，零容器）。
- **不证明**：不是真实 IAM、不是生产模式、不是真实设备、不是签发/部署依据；**不产生 `enforcement_verified`**（仍只能由 A7 的受控探针产生，R09.2 第 1 条）；**不能用来给 A2 判绿**——A2 的 5 项失败落在**前端 UI 断言层**，本工具根本不驱动浏览器，两者不重叠，83 条全绿**不表示**那 5 项已修复。
- **只核对已声明项**：两侧分页语义均取自 `packages/contracts/enterprise-audit-query.v1.md` 与 `enterprise-environment-list.v1.md` 的原文；未声明的行为（例如未给 `limit` 时 `X-SIQ-List-Limit` 该取什么值）**没有断言**，也没有发明新合同。

**允许清单与冻结核验**：清单 28 → **29 条**（本节新增上述工具）→ **30 条**（R09.9 再新增其合成回归测试，README 头部的范围声明未变）。两次 preflight 均为 `requested=verified`、`missing=0 / unverified=0 / excluded=0 / conflicts=0`、`scan_stable=true`、`unreviewed=806`（并行作者线，同前）、`conclusion=blocked` 不变：

| 次序 | 报告（`/tmp/`） | 清单 | 工作树（preflight **自身**口径） | 相对上一份的**已归属**差异 |
| --- | --- | --- | --- | --- |
| 第 3 次 | `preflight-r097-20260926T175046.json` | `29 / 29` | `103 / 705` | 相对第 2 次（`108 / 704`）：**−6 条已跟踪**＝并行作者线提交了 6 个已跟踪文件（两份滚动文档、`enterprise-gate-run.py`、`run-browser-smoke-suite.py` 及其两个测试；`head` 同期由 `b4586c1` 前移到 `66aae3d`）、**+1 未跟踪**＝本节的新工具、清单文件自身由干净回到 ` M` |
| 第 4 次 | `preflight-r098-20260926T175326.json` | `30 / 30` | `105 / 706` | 相对第 3 次：**+2 条已跟踪**＝我在两次核验之间写的这两份滚动文档（mtime `17:51:22` / `17:52:20`，均在 r097 之后）+ **+1 未跟踪**＝R09.9 的测试文件 |

**订正（上一版本节的一句话说错了，按四份报告逐条对照后定论）**：上一版这里写「`tracked 102→103` 的 +1 不是本轮…未做归属判定，属 D-7.3」。把本轮四份 preflight 报告的 `worktree.status_entries` 逐条相减后可以**确定**：那个 +1 **就是我自己**对允许清单文件的那次编辑（该文件在 r0711 提交后是干净的，r097 时回到 ` M`）——**不是**并行作者线的产物；同期减少的 6 条已跟踪项才是并行作者线的提交（`head` 同时前移可独立佐证）。因此**本轮账目里已不再有"未归属的已跟踪改动"**。口径纪律照旧：**只做同口径相减**（四份都是 preflight 报告自身字段）；工具自报的 `--untracked-files=all` 逐文件计数与它不同源，**不可相减**。

### R09.9 验收工具自身的合成回归守卫（防"工具自己报假绿"）

**为什么做**：R09.8 的结论完全建立在"工具自己说 83 条成立"之上——而一个只会打印成功的工具，和一份真结论，在报告形态上**无法区分**。因此按 §3.2 允许的隔离合成测试，给工具配一组**不启动任何服务、不发任何真实 HTTP、不依赖 playwright** 的用例，钉死它最可能造假的几个面。

**文件**：`scripts/enterprise-experience/test_http_contract_acceptance.py`（新增，允许清单第 30 条）。**没有为了测试通过而改动被测工具**。

| 钉死的假绿面 | 条数 | 具体钉什么 |
| --- | --- | --- |
| 判定聚合 | 3 | 任一条判据不成立 → 该组 `failed` 且整体必须 `contracts_failed`；全部成立是通往 `contracts_held` 的**唯一**路径；`run_error` 压过一切绿判据 |
| 回收核验不许"没测到当成立" | 1 | `process_exited=None`、`port_released=False` 时判据必须**判红**（把 `None`/`False` 写成成立 = 假绿），`temp_dir_removed=True` 才成立 |
| 秘密扫描必须能**抓到** | 4 | 把哨兵串植入工作目录文件 / 一次性 SQLite 库 / 日志 → **必须命中**（只在干净输入上返回空集 = 空集的另一种说法）；`signing.seed` 是**输入材料**、排除在扫描对象外，否则判据永远红；日志在删目录前必须已拷出 |
| 隔离与退出码 | 8 | 启动环境是**白名单**（只放行 `PATH/LANG/LC_ALL/TZ` + 6 个 `SIQ_AS_*` + `HOME`），不继承调用方的任何其它变量；`SIQ_AS_DATABASE_URL` 指向临时目录；响应辅助函数对非 JSON/缺头健壮；结论→退出码映射稳定；证据目录**已存在时拒绝覆盖且不触碰原目录** |

**实测**：`16 passed`（0.16s，无网络、无服务进程、无浏览器），`ruff check --no-cache --config apps/control-api/pyproject.toml` → `All checks passed!`（仓库根无配置，裸跑 `ruff` 是**假绿**，见本轮纪律）。

**如实留痕：测试自己先后红过两次，都修在测试侧**——① `UP037`（注解上多余的引号）；② `importlib` 动态加载未登记 `sys.modules`，导致被加载文件的 `@dataclass` 在**装饰那一刻**抛 `AttributeError: 'NoneType' object has no attribute '__dict__'`（`http-contract-acceptance.py:92` 起）。修法是在 `exec_module` 前登记 `sys.modules[_SPEC.name] = tool`，并把原因写进测试注释（`enterprise-gate-run.py` 无 `@dataclass` 所以同样写法能过，属"踩到才知道"的差异）。

**边界**：这 16 条**只**保证"工具不会把红说成绿"，**不**证明它在生产环境正确、不覆盖任何数据库/网络行为；**不产生 `enforcement_verified`**，不参与任何门禁，不改变 R09.8 那份契约验收证据的效力范围。

### R09.10 本轮工具层的同候选回归与 lint 残留清零（R09.9 的收尾）

**为什么做**：R09.9 收尾时按**仓库口径**（`ruff check --no-cache --config apps/control-api/pyproject.toml`，line-length 120，select `E,F,W,I,UP,B`；裸跑 `ruff` 是**假绿**）对本轮**全部 8 条工具路径**跑了一遍，残留 6 条：**5 条落在本轮路径**（`enterprise-gate-run.py:144` 1 条 `UP017`、`test_enterprise_gate_run.py` 4 条 `E731`）、**1 条在既有件** `source-freeze-preflight.py:291`（`UP017`）。本轮此前登记的"残留 5 条"正是前一组。

**改动（行为等价，无逻辑变更）**：

| 文件 | 改动 | 说明 |
| --- | --- | --- |
| `enterprise-gate-run.py` | `from datetime import datetime, timezone` → `from datetime import UTC, datetime`；`datetime.now(timezone.utc)` → `datetime.now(UTC)` | 仅别名现代化（Python ≥3.11） |
| `test_enterprise_gate_run.py` | 4 处 `builder = lambda _repo, _build: synthetic_gates({...})` → 局部 `def builder(_repo, _build): return ...` | 测试内的桩函数，语义不变 |

**未做（刻意）**：`source-freeze-preflight.py` 的那 1 条既有 `UP017` **没有改**——该文件**不在本轮允许清单内**，属既有件/并作者线，按 §3.2 不擅自扩大改动面。因此**仓库里仍有 1 条 lint 残留，但本轮路径已为 0**。

**验证（三层，全部实测）**：

1. `ruff`（本轮 8 条路径）→ `All checks passed!`（不再有本轮残留）。
2. `pytest scripts/enterprise-experience -q -p no:randomly` → **92 passed**（本目录 5 个工具测试文件：契约验收 16、门禁 33、浏览器套件 18、契约版本链、源码冻结前置）。
3. **真实运行一次改过的执行器**（不是只跑单测）：`enterprise-gate-run.py --only rulepack_python_go_identity,contract_version_chain` → 两条 `passed`，报告 `/tmp/gate-R099-rulepack-20260926T175635.json`（`real 0.9s`）。**顺带核到了被改的代码路径**：报告里 `started_at=2026-09-26T09:56:35Z` / `finished_at=…:36Z` 格式正确，`head_sha=b27608a…`，结论 `partial_run_not_a_gate`（按设计，带 `--only` 就永远不能是门禁结论）。

**落盘与账目**：本节改动 = 2 条已跟踪源码路径（`enterprise-gate-run.py`、`test_enterprise_gate_run.py`）+ 2 条滚动文档，合计 **4 条已跟踪路径**，**清单条数不变（30）**。本次提交前的同口径读数（`2026-09-26T09:57:00Z` / `--out /tmp/preflight-r0910-20260926T175700.json`）= **106 tracked / 705 untracked**，相对上一份（`102 / 705`）**差恰好 +4**，与本节改动逐条对应。

**边界（不许被下游读大）**：这是**工具层**的同候选回归——92 条单元/合成用例 + 1 次两门禁真实运行；**不是**纵向"不退化"证明（无改前基线），**不覆盖**后端全量（R07.9 的 `2164 passed / 1 skipped`）与前端全量（R07.5 的 `1003 passed`），**更不覆盖** A2 那 5 项前端 UI 失败。

### R09.11 留证断言在**真实语料**上的演练（把 R07.11b 登记的那条限度收窄到 1 条）

**要解决的账**：R07.11b 末尾如实登记过一条限度——**门禁的 `post` 校验只在命令通过时执行**，而 `browser_acceptance_simulated` 当前恒红（25/30），所以留证的 8 条证据断言**在真实数据上从未被求值**，只有合成用例覆盖。**一个永远走不到的检查器和没有检查器不可区分**——这正是本轮反复要防的那类假信号。

**做法（只读、不新增门禁、不新增文件）**：给 `enterprise-gate-run.py` 加 `--validate-browser-evidence <result.json>` 纯核对模式：

| 特征 | 说明 |
| --- | --- |
| 不短路 | 新增 `audit_browser_evidence()` 把 **9 条**断言逐条算出并打印（`check_browser_evidence()` 原样不动，门禁语义零变更） |
| 纯读 | **不跑套件、不构建前端、不起服务、不写报告**；该模式下连 `build_dir` 临时目录都不创建，`--out` 也不再强制（正常门禁路径仍强制——有用例钉住） |
| 不许误读 | 退出码 0 只表示"这份留证自述**内部自洽**"，措辞恒为 `verdict=evidence_assertions_held`，**从不出现 `gates_green`**（有用例断言这一点） |

**真实语料实测（不是合成）**——两份**既有**留证，一份是 R07.11b 后的、一份是 R07.11b 前的：

| 留证 | 断言 | 成立 | 不成立的是 |
| --- | --- | --- | --- |
| `/tmp/siq-gate-browser-evidence-yguusfnq/result.json`（E4，17:43:35，R07.11b 之后） | 9 | **8** | 只有 `suite_passed`（`passed=False`，即 25/30 那 5 项前端失败） |
| `/tmp/siq-gate-browser-evidence-41rshtk2/result.json`（E1 期，R07.11b 之前） | 9 | 6 | `suite_passed` + **`suite_digest_matches`**（记录的 `c3324651…` ≠ 现套件 `af07098c…`）+ **`real_dev_api_measured`**（`NoneType`） |

**第二份是有意选的负对照**：它证明这些检查**在真实数据上不是空跑**——摘要绑定与"范围自述必须有度量字段"两条都**确实抓到了**真实的漂移与缺失。否则"8/9 成立"可能只是断言太松。

**结论**：R07.11b 那条限度的范围由「**8 条断言全部未在真实数据上求值**」收窄为「**仅 `suite_passed` 这一条未在真实数据上求值**」——而它是否成立**不取决于工具**，只取决于 A2 那 5 项前端 UI 失败被前端作者线裁决之后，30 个脚本是否全绿。

**落盘与账目**：改动 = 2 条已跟踪源码路径（`enterprise-gate-run.py`、`test_enterprise_gate_run.py`）+ 2 条滚动文档 = **4 条**，**清单条数不变（30）**。提交前同口径读数（`2026-09-26T09:58:33Z` / `/tmp/preflight-r0911-20260926T175833.json`）= **106 tracked / 705 untracked**，相对上一份（`102 / 705`）**差恰好 +4**。**正常门禁路径另做一次真实复跑**（改了 `--out` 的必填性之后必须证明它没受影响）：`--only rulepack_python_go_identity,contract_version_chain` → 两条 `passed`、结论 `partial_run_not_a_gate`、报告 `/tmp/gate-R0911-real-20260926T175833.json`（`head=f67f0ed`）。

**边界**：本条**不**让门禁变绿（`suite_passed` 仍为红）、**不**覆盖门禁自身的通过路径（仍未演练）、**不是**"不退化"证明、**不产生 `enforcement_verified`**；它只是把"留证自述的自洽性"这一层从"只有合成证据"升级为"**有真实语料证据且有真实负对照**"。

### R07.11 可选浏览器验收门禁（把 `browser_acceptance` 从"恒登记"变成"可执行"）

**为什么做**：R09.5 实测推翻了 `browser_acceptance` 原登记的 `requires_running_services`，"恒 `skipped`"就不再是事实描述。按 R07.10 给 `migration_replay_postgres` 的模式（**默认连探测都不做、显式 opt-in 才跑、证据附摘要级断言**）把它做成同构的第二条可选门禁。

**新增两个文件**（都属于本轮成果，非改动既有文件）：

| 文件 | 作用 |
| --- | --- |
| `scripts/enterprise-experience/run-browser-smoke-suite.py` | 套件本体：模拟身份前端构建 + 遍历全部 `*-browser-smoke.py` + 写 `result.json`（**独占创建**）。参数**从每个脚本自己的 `--help` 读出**，不硬编码参数家族 |
| `scripts/enterprise-experience/test_run_browser_smoke_suite.py` | **18** 条合成用例（不启浏览器、不构建前端、不依赖 playwright） |

`enterprise-gate-run.py` 侧新增：`--enable-browser-smoke-gate`、`--browser-smoke-python`、`--browser-smoke-edge`、`--browser-smoke-connector-dir`；`browser_probe`/`check_browser_evidence`/`browser_gate_decision`/`browser_gate`；`run_gates` 的声明覆盖改为**按 id 分派**（两条可选门禁各自只撤自己那条登记）。新增 9 条合成分支用例。

**设计要点（都是"不制造事实"的取向）**：

1. **默认连探测都不做**：未传 `--enable-browser-smoke-gate` 时不探解释器、不构建、不跑脚本；被 `--only` 排除时同理（`excluded_by_only` 明记）。
2. **不安装依赖**：解释器缺 playwright 时**不代跑**，记为实测原因 `playwright_not_importable` 并保持非绿。
3. **缺原生二进制 → `blocked`**，不替脚本造参数；套件因此不可能"通过"。
4. **证据摘要级断言**：`passed is True` / `simulated_build is True` / `production_deployed is False` / `production_identity_tested is False` / `counts.total > 0` / `suite_sha256` 与当前套件字节一致。
5. **失败即失败**：5 项 UI 断言失败**不加 skip**，门禁 `failed`；结论 `partial_run_not_a_gate`（定向）或 `gates_incomplete`（全跑）。

**实跑记录**：

| 轮次 | 命令要点 | 结果 |
| --- | --- | --- |
| E1 定向 | `--only browser_acceptance_simulated --enable-browser-smoke-gate` | 门禁 `failed`、`exit_code=2`、**耗时 0 秒**而 `real 4m24s` —— 即**整批 30 个脚本真跑完了，却在最后一步失败**（缺陷 1）。**证据未丢**：30 个脚本各自的留证目录仍在 `/tmp/siq-gate-browser-evidence-7b8qd7p5/`，逐个读其自身 JSON：17 个显式 `passed: true`，其余为 `?`（无 `passed` 键或未生成）——**与 A2 独立测得的失败集合完全一致**（change-execution / deployment-preview / workspace / onboarding / candidate-review 全为 `?`） |
| E2 定向 | 同上（修复后） | 门禁 `failed`、`exit_code=1`、**25 passed / 5 failed / 0 blocked（of 30）**、`real 4m24s`；stderr 尾部即计数行。与 A2 **独立测得同一组数字**（25/5）——这是"套件不是随机通过"的证据 |
| **E3 全跑** | `--out /tmp/gate-F3-browser-20260926T170755.json --enable-browser-smoke-gate`（在 E2 修复后、含全部 48 个基础门禁） | **49 个门禁记录：48 passed / 1 failed / 0 blocked**，结论 `gates_failed`；唯一失败项即 `browser_acceptance_simulated`（`exit_code=1`，stderr 尾部同一计数行 **25 / 5 / 0（of 30）**，并列出 5 个失败脚本名：`candidate-review` / `change-execution` / `deployment-preview` / `onboarding` / `workspace`-browser-smoke）。**这 5 个名字与 A2 独立测得的失败集合、以及 E1 从各脚本自身 JSON 反推出的 `?` 集合三方一致**。其余：`backend_full_suite` **2164 passed / 1 skipped / 1 warning in 113.75s**、`web_unit_suite` 与 `web_prod_build_bundle` 均 passed；**`skipped` 仅剩两条且都是声明级**：`migration_replay_postgres`（本轮**刻意不启用**——再跑一次数据库容器需按 §3.2 重新取得该次许可，故以静态原因记 `skipped`、`measured=None`）与 `real_device_native_evidence`。整体 `real 9m11s`，`head=f1709cd515fe`，分支 `deepseek/enterprise-mainline-closeout-20260926` |

| **E4 定向（R07.11b 之后）** | `--only browser_acceptance_simulated --enable-browser-smoke-gate --browser-smoke-python …`（沿用同一批临时原生二进制） | 门禁 `failed`、`exit_code=1`、**25 passed / 5 failed / 0 blocked（of 30）**、`duration_seconds=264.011`，结论 `partial_run_not_a_gate`，报告 `/tmp/gate-E4-browser-20260926T173911.json`。**第四次独立复现同一失败集合**（与 A2、E1 反推、F3 一致）。新增的范围度量在**真实语料**上落地：`real_dev_api_scripts` = **8 条**（名单与 R09.5 所列一致）、`failed_are_subset_of_real_dev_api` = **`true`** —— 即"5 项失败全部发生在真实后端脚本内"这句话是**结果文件自述**，不是我的推断 |

**一处必须写清的限度（E4 暴露的、容易误读的设计事实）**：门禁的 `post` 校验**只在命令 `status == "passed"` 时才执行**（[`enterprise-gate-run.py:583`]，与 PostgreSQL 门禁同一处逻辑）。浏览器门禁**当前恒红**，所以它的 6 项证据摘要断言在 E4（以及 E2/F3）里**根本没有被执行**——用真实 `result.json` 单独调用校验器，返回的是 `browser_evidence_not_passed`（第一条就拦下），走不到新增的 `real_dev_api_scripts` 断言。**因此**：新增断言的**真实数据**演练**尚未发生**，目前只有 21 条合成用例覆盖（含缺字段与类型错两个失败分支）；要真正演练，须等那 5 项 UI 失败被前端作者线裁决后再跑一次**通过**的门禁。**这不是缺陷，但要如实登记**：门禁红时，"证据是否合格"这条链是**没被检验过**的，不能写成"证据断言已验证"。

**E3 的结论读法（重要，避免误读为"回退"）**：F3 是本候选**第一次把可选浏览器门禁接进全跑**，因此它相对 R07.9 的 C 轮（48 passed / 0 failed / 3 skipped，结论 `gates_incomplete`）**不是能力回退，而是"把一个此前恒登记为不可用的声明换成了真实可执行门禁"**。换来的代价是：该门禁**实测就是红的**（5 个 UI 断言失败），于是全跑结论从"不全"变成"失败"。两条都是诚实的对外表述：**默认（不传开关）仍是 C 轮的形态**；**启用后如实报红**，不因"这是新加的门禁"而给它豁免或降级成 skip。

**本轮自己踩的两个坑（都已修，且都写成了回归用例）**：

- **缺陷 1（最严重）**：我把证据目录交给套件创建，套件**等到最后**写结果时才 `mkdtemp`+独占创建。但每个脚本用 `mkdir(parents=True, exist_ok=False)` 建自己的输出目录，**顺手把父目录（也就是证据根）一起建了出来**，于是最后一步必然 `FileExistsError` → 退出 2。后果是**一次 4 分 24 秒的真实运行结果全丢**。修法：改为**开跑前先 `os.mkdir(out_dir, 0o700)` 占位**，结果文件再用 `O_EXCL` 写。回归用例 `test_evidence_dir_is_claimed_before_scripts_run`（断言脚本被调用时根目录**已经存在**）。**注意这与 R07.10 缺陷 1 是镜像关系**：那次是我**预建**了脚本要求"必须不存在"的目录；这次是我**没有**预建脚本会连带创建的目录。两次的教训是同一条：**必须读清对方对目录生命周期的约定，而不是照搬上一次的模式**。
- **缺陷 2**：探针写成了 `import playwright; print(playwright.__version__)` —— `playwright` **没有** `__version__` 属性，于是**装了 playwright 的解释器被判成没装**（实测 `/home/maoyd/miniconda3/bin/python` 有 playwright 1.58.0，却被记为 `playwright_not_importable`）。这正是"把可跑误记为不可跑"的典型写法。修法：改用发行版元数据 `from importlib.metadata import version; print(version('playwright'))`，并在两处（套件与门禁）用同一个常量；回归用例断言探针命令含 `importlib.metadata`、**不含** `__version__`。

**测试与静态检查**：`scripts/enterprise-experience/` 全部 **73 passed**（本轮 **18 + 9 = 27** 条为新增；该目录逐文件为 `contract_version_chain_audit` 12 + `enterprise_gate_run` 33 + `run_browser_smoke_suite` 18 + `source_freeze_preflight` 10 = 73，用 `pytest --collect-only` 实测，不是估算）。**一处与不可变记录的差异需说明**：提交 `52cb855` 的**提交信息**里写的是"回归用例 17 + 9 条"——17 是落笔时的记忆数字、**不准确**，实测为 18；提交信息无法追改（改写历史属 §3.2 禁止的破坏性操作），故在此**如实标注**：**以本节实测的 18 为准**。ruff 按仓库基线（`--config apps/control-api/pyproject.toml`）对四个文件检查：新增/改动的行**零告警**，全仓该目录仍只余 5 条既存项（1 `UP017` + 4 `E731`）。

**落盘与提交**：7 条路径提交为 `52cb855`（父 `f1709cd`，分支 `deepseek/enterprise-mainline-closeout-20260926`，**未推送**，`main` 仍 `ebaaf3b`）；同口径账目 `107 tracked / 706 untracked → 102 / 704`（差 7 = 5 个已跟踪改动 + 2 个新增）。清单因此由 26 条增至 **28 条**，复核报告 `/tmp/preflight-r0711-20260926T171754.json`（`requested=28 / verified=28`、`head=f1709cd`）。**E3 全跑报告**：`/tmp/gate-F3-browser-20260926T170755.json`；**E4 定向报告**：`/tmp/gate-E4-browser-20260926T173911.json`。

**R07.11b 的落盘**：6 条路径提交为 **`bed0fbb`**（父 `b4586c1`，**未推送**，`main` 仍 `ebaaf3b`）；同口径账目 `108 tracked / 704 untracked → 102 / 704`（差 6 = 4 个已跟踪代码文件 + 2 份文档，**无新增路径**，故清单仍 28 条）。复核报告 `/tmp/preflight-r0711b-20260926T174446.json`（`requested=28 / verified=28`、`unverified=excluded=missing=0`、`scan_stable=true`、`conflicts=0`、`head=b4586c1`）。

### R07.11b 范围声明按实测改精确（原声明**低估**了这批脚本）

**触发**：R09.7 的方案调研时逐脚本核对，发现套件与门禁里那句"`mocked browser only`、不是真实后端 HTTP 契约"对**一部分脚本不成立**——30 个里有 **8 个会自起真实回环 dev 控制面**（真实 socket + 真实 HTTP + 合成 `X-Dev-*` 身份）。这不是措辞小疵：它同时**低估**了这批脚本（说成全是 mock）又**高估**不了契约层（套件确实不做契约断言），两个方向都会让下游读者判错。

**改法（都是"让证据自述"而不是"换一句更漂亮的话"）**：

| 改动 | 内容 |
| --- | --- |
| `run-browser-smoke-suite.py` | 新增 `real_dev_api_scripts()`：按 `SIQ_AS_DEV` 标记（which：只有它置位，`X-Dev-*` 才被 `app/security.py` 采纳）**逐个内容判定**，把名单与 `failed_are_subset_of_real_dev_api` 写进 `result.json`。**不硬编码数字**——30/8 会随脚本增删腐坏 |
| `SCOPE_NOTE` | 改为："共享夹具是 mocked browser only … **但按 `real_dev_api_scripts` 列出的脚本会额外自起回环 dev 控制面**（真实 socket、真实 HTTP、合成 X-Dev 身份，非真实 IAM）；套件本身只断言各脚本通过/失败，**不做契约级断言**" |
| `enterprise-gate-run.py` 登记 | `note` 与 `why` 同步改写（同时避开两个方向的失真）；旧措辞"不是真实 HTTP 契约"删除 |
| 门禁证据校验 | 新增断言：证据里必须有 `real_dev_api_scripts` 且为 **list**，否则门禁 `failed`（`browser_evidence_missing_real_dev_api_measurement`）——**报告里的范围描述必须有结果文件背书**，不能只是转述一句声明 |
| 用例 | 套件侧新增 `ScopeMeasurementTests`（3 条：度量为真、失败落在该子集内会被标出、范围声明不宣称契约级证据）；门禁侧新增 3 条断言（缺字段/类型错均失败、字段被带进 `evidence`）。合计 **73 → 76 passed** |

**真实语料演练（E4，见上表）**：定向复跑实测 `real_dev_api_scripts` = **8**、`failed_are_subset_of_real_dev_api` = **`true`**，与只读度量结果一致；同时发现门禁的 `post` 校验只在通过路径执行，故这 6 项断言在门禁红时**不被演练**——如实登记，不写成"已验证"。

**这个字段顺手给出的一条交叉线索**：`failed_are_subset_of_real_dev_api` 实测为 `true`——A2 的 5 项失败**全部**落在真实后端脚本内，与 E1 留存证据里出现的服务端生成 id（`cr_…`/`pol_…`）互相印证：失败发生在**真实 HTTP 往返之后**的 UI 断言层。（**这不等于契约验收**，理由见 R09.5 与 R09.7。）

### R09.12 A7「行为核验」的 §3.2 前置方案（**状态：待批，尚未执行任何一步**）

**主开发者 2026-09-26 选择**：下一步优先清 A7（受控 OpenShell 目标 → 行为核验）。本节是执行前的 §3.2 前置说明，**不含任何实测数字**。

**A7 为什么是唯一合法的 `enforcement_verified` 生产者（代码级事实，不是说法）**：

| 事实 | 出处 |
| --- | --- |
| `verify()` 契约要求"至少验证预期允许和预期拒绝各一项"，并明写：配置读回类检查只能产出 `readback_verified`；`enforcement_verified` 需要**真实行为 fixture 证据**（当前所有后端均无行为 fixture 通道，**禁止**产出该级别） | `app/adapters/openshell/base.py:52-58` |
| openshell-cli 路径确实**只**给 `expect_allow`，`expect_deny` **恒为空列表**，代码内写明理由：**不发明可能与策略冲突的固定 deny probe** | `app/routers/policies.py:631` |
| 存量合同里那个非空 `expect_deny`（`denied.invalid:443`）在**另一个工具**里，是兼容性自检用的**固定样例**，不是"某次策略的真实 deny 目标" | `scripts/openshell_compat_check.py:121` |
| 三层防伪消费方都只认"非空 `expect_deny` + 行为观测"这条来源 | `fake_backend.py:280`、`app/tests/test_evidence_topology.py:169` |

**结论**：`enforcement_verified` 在当前候选上**没有生产者，而且本来就不该有**。要产生它必须有**真实 deny 观测**，不能靠给 `expect_deny` 填一个好看的值。

**缺的三样（逐项写清"缺什么、为什么执行者不能自备"）**：

| # | 缺什么 | 为什么不能由执行者自备 |
| --- | --- | --- |
| 1 | **受控 OpenShell 测试目标**：`--target` 名（`[A-Za-z0-9_.-]{1,128}`）、HTTPS **回环**网关端点、CLI 绝对路径、XDG root（须已含 `config` 与 `state`） | 目标是**真实存在的受控资源**，必须由你指定。既有只读工具已强制"显式 HTTPS 回环网关 + 绝对路径 CLI/XDG"（`openshell-preview-live-check.py:24-31`），我**不会**去试探未授权的网关 |
| 2 | **真实行为探针通道**（从 `expect_deny` 的**来源**到**观测**）：探针目标必须由**策略里真实存在的 deny 规则**导出，观测必须是**行为**（请求被拒），不是读回 | 这是**代码改动**，落在 `app/adapters/openshell/*` 与 `app/routers/policies.py` —— **都不在本轮允许清单内**，且它正是 `enforcement_verified` 的生产者。**必须**先拿到 D-1 范围的明确授权；且**不得**由测试夹具/mock/"推演"生成该值（R09.2 第 1 条） |
| 3 | **范围与证据格式**：允许探测的目标集合、超时、失败判据、证据字段（`gateway_version`、`endpoint_fingerprint`、scope digest、deny 观测原文） | 由你定；我按定好的口径写证据，**不自行定义"算通过"** |

**执行步骤（获准后按序，不可换序）**：

1. **只读先行**（用清单内既有工具，不产生任何 enforcement 结论）：`openshell-preview-live-check.py --cli <绝对路径> --endpoint <https 回环> --xdg-root <绝对> --target <名> --out-dir <新目录>`。它**只读、从不 apply**，`--out-dir` 独占创建（已存在即报错）。这一步只证明"能只读探到该网关/目标的策略投影"，**不证明任何强制点生效**。
2. **行为探针**（需第 2 项授权）：以策略中**真实的 deny 目标**构造 `expect_deny`，在受控目标上观测**真实拒绝**，并与 ≥1 个 `expect_allow` 同时留证。
3. **同一候选约束**：步骤 1–2 的证据必须绑定**同一个 commit**（与 A3/A4/A5/A6 同规），报告写清 `head_sha`。
4. **回收核验**：进程退出 / 端口释放 / 临时目录移除三项**独立复核**，另加宿主容器与网关集合 `diff`；不修改宿主 systemd、不碰其它网关。

**通过判据（逐条写进证据，不四舍五入）**：出现**真实 deny 观测**（非 mock、非读回），`expect_deny` 非空且**每一条的来源可追溯到编译产物里的 deny 规则**，并且未通过项如实记为未通过。**只有此时** `verification.level` 才允许被标为 `enforcement_verified`；在此之前该值**保持无生产者**。

**非声明**：本节**不是执行**、不含实测数字；**不**授权执行者自行探测任何网关；**不**关闭任何 ENT。

### R09.13 受控目标被指定：智能分析助手（siq_analysis）OpenShell 链接**只读实跑**（2026-09-26）

使用者 2026-09-26 指定受控目标 = **siq 投研决策引擎 `siq-research-engine` 的智能分析助手**所适配的 OpenShell 网关。
本轮只做**链接与只读读回**；未启停网关、未创建/删除沙箱、**未 `policy set`**、未改对方仓库。
证据目录：`docs/evidence/agentshield/openshell-siq-analysis-2026-09-26/`（README + 4 份原始输出）。

**实跑命令与结果**（全部只读，逐条可复验）：

| # | 命令 | 结果 |
| --- | --- | --- |
| 1 | `SIQ_AS_OPENSHELL_ENV_SH=/home/maoyd/siq-research-engine/scripts/openshell/env.sh .venv/bin/python scripts/openshell_compat_check.py` | **PASS，exit 0**；探测版本 `v0.0.83`，兼容矩阵 **8/8 一致**（含 `sandbox_list_decodable=false` 与矩阵冻结值一致） |
| 2 | 对方 `env.sh` 内钉住的 CLI：`sandbox list` / `policy get <target> -o json` / `policy list <target>` | 网关 `siq-openshell-dev` 在 `127.0.0.1:17671`+`172.23.0.1:17671` LISTEN（`ss -ltnp` 证实三个监听同为 pid 3704433，2026-09-22 00:29 启动）；沙箱 `siq-analysis-canary-27d1289f98fa` / `…d4a890ec23d3` 均 `Ready`；两者均 `version=2`、`policy_source=sandbox`，网关**自报** `status:"effective"` |
| 3 | `openshell status --gateway-endpoint https://127.0.0.1:17671`（**TLS 校验开启**，未用 `--gateway-insecure`） | `Status: Connected`、`Version: 0.0.83`；服务端证书 SAN 含 `IP Address:127.0.0.1`，故回环 HTTPS 端点成立 |

与 2026-09-05 那次（`docs/evidence/agentshield/openshell-siq-research-engine-2026-09-05/`）的差别：
当时 L3 **只有握手**、明确"无可做读回闭环的分析沙箱"；本轮分析助手侧**已有 2 个 `Ready` 的真实 canary 沙箱**，
链接面从"握手"推进到"有可读回的真实目标"。**仍然没有**任何强制点生效结论。

**新发现：既有只读预览工具对同一目标**构造性**失败（E149 证据在当前候选不可复现）**：

- 按 `docs/development/ux-openshell-live-preview-e149-validation-20260923.md` 里记载的同一条命令、同一目标运行
  `scripts/enterprise-experience/openshell-preview-live-check.py` → **rc=1**，第 136 行 `('/deployment-preview', 409)` 断言失败。
- 探针本身正常（`handshake_verified=True`、`gateway_version=0.0.83`、`endpoint_fingerprint=6225b824…`）。
  用 `/tmp` 下一次性只读复现脚本拿到正文：`{"detail": "deployment_target_authority_unverified"}`，
  且**已执行命令列表里没有 `policy get`** —— 失败发生在读目标策略**之前**。
- 根因（读代码逐行）：`prepare_deployment`（`app/routers/policies.py:436`）在 openshell-cli 分支
  `:534-536` **无条件**调 `require_target_authority`；该闸（`app/target_authority.py:136-151`）强制读
  `SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE`，缺则失败关闭为 409。而该工具在 `:58-62` 把 `os.environ` 清成
  `PATH/HOME/USER/LANG/LC_ALL` 白名单后才设自己的变量，**从不设**该变量 —— **外部无论如何设置都会被清掉**。
  即：**在当前候选上，该工具不可能通过自己的预览断言**（构造性，非本次配置错误）。
- 引入该闸的 `app/target_authority.py` 是**未跟踪新文件**（mtime 2026-09-25 16:34），晚于 E149 文档（2026-09-23）。
  故 E149 记录的 **8 项全通过已陈旧**，属交接文档 §5 要回答的「同候选非退化证据」缺口。
- **本轮不改**这四条路径（`app/target_authority.py`、`app/routers/deployment_preview.py`、
  `openshell-preview-live-check.py`、E149 文档）——**逐条比对确认四者均不在冻结允许清单 30 条内**。

**自查更正**：R09.12 前置方案里写"清单内既有工具 `openshell-preview-live-check.py`"**有误**——它**不在**允许清单内。
该表述按本条更正；R09.12 的"只读先行"因此**不能**按原计划作为"清单内工具"来用。

**未做（仍待许可 / 仍 blocked）**：

- `openshell_compat_check.py --live --sandbox <canary>`：**会真实修改**分析助手 canary 沙箱的网络段（allow `example.com:443`），
  属真实权限变更，按 §3.2 需**该次**许可；且其产出上限只有 `readback_verified`，其 `expect_deny` 是**固定兼容样例**不是真实拒绝观测。
- **行为 fork 通道**（`enforcement_verified` 的唯一合法生产者）仍不存在，且实现它要动 `app/adapters/openshell/*` 与
  `app/routers/policies.py` —— 需 D-1 范围明确授权；**不得**由夹具/mock/推演生成该值。

## 本轮决策门槛汇总

见 R00.6（提出）与 R00.6a / R00.6b（答复）。

| 门槛 | 提出 | 答复 |
| --- | --- | --- |
| D-1 并行接管 | R00.6 | **两次**：先「只写新增文件」，后放开为**例外授权「全部放开」**（据此改 5 个既有件，见 R01.5 / R05.5 / R07.8）。**并作者文件归属仍未确认** |
| D-2 R01 周期意图衔接 | R00.6 | **已决策：设备侧待办枚举端点（最小路径）** |
| D-3 共享影响 / 运行事实 | R00.6 | **已决策：保持 `unknown` 不猜** |
| D-4 证据时效 | R04 | **未确认**（未自行设 TTL） |
| D-5 保留治理 | R00.6 | **已决策：只补齐声明与缺口** |
| D-6 原生验证与受控目标 | R09 | **部分**：**A1 已获批并执行完毕**（§3.2 前置说明写在 R09.4，许可 = "批准并执行完整 A1"）：`migration_replay_postgres` 由恒 `skipped` 变为**真实执行且通过**，宿主容器集合 `diff` 为空（45 项）、零残留（R09.4(8) / R07.10b）；**A2 已执行**、实测**不需要运行中的控制面**，故"一次性服务实例"许可**未使用**（R09.5）；**A2 的 30 个脚本已被 R07.11 收拢为一个显式 opt-in 门禁**（默认不探测；接入后全跑 F3 = 48 passed / 1 failed / 0 blocked / 2 skipped，唯一失败项即该门禁，见 R07.11 的 E3）。真实 Linux 实机（A3+）**可用但未启用**（R09.3），启用前仍须按 §3.2 写出隔离/目标/回收方案并取得该次许可；**受控 OpenShell 目标已于 2026-09-26 由使用者指定**（= 智能分析助手网关，见 R09.13），**只读链接已实跑成立**，但 `--live` 真实写入与行为 fixture 通道**仍未获许可/仍不存在**，A5/A7 仍 blocked |
| D-7 发行与部署 | R08 | **部分**：D-7.1 提交到新分支、D-7.4 保留追加段**已答复**；D-7.2 推送、D-7.3 并作者归属、D-7.5 签发、D-7.6 部署**未确认** |
