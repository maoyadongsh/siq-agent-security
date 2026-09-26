# 企业权限治理端到端能力覆盖核对（CL-05-PERMISSION-COVERAGE-CLOSEOUT）

日期：2026-09-26。只读核对，不修改生产逻辑。阅读时快照：HEAD `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0`（分支 main），2026-09-26T05:59:38Z，工作树 639 条未提交/未跟踪条目。核对基于**当时工作树**（含 DeepSeek 在途的 deployment_impact/deployment_submission 修改），非原子快照，非 HEAD 发布态；行号以阅读时为准。

本轮**未执行任何测试**；所有测试引用为历史记录（各自 handoff 记录过通过），不写成本轮通过。

## 1. 需求分母（原任务书与合同，不增不减）

来源：enterprise-auto-onboarding-taskbook-20260925.md §4C/D 表格及 §3.2；closeout CL-04/05/06；四份合同。

| requirement_id | 原文位置 | 要求（权限相关摘要） |
| --- | --- | --- |
| ENT-013 | 任务书 :89 | 绑定环境/设备/框架/角色/Skill 摘要/运行身份/沙箱 revision；来源不足显示未绑定；共享沙箱连带影响明示；继承/交集/冲突/不可表达权限有后端规则；撤销/漂移使旧绑定失效 |
| ENT-014 | 任务书 :90 | 并列展示声明/推断/观察/有效权限及来源、时间、有效期；"允许上限"≠"实际使用"；effective 同步限定部署目标；读回失败/过期不显示已核验 |
| ENT-015 | 任务书 :91 | 多选/筛选外提示/数量限制/逐项影响预览；先收窄撤销后扩大与模板；服务端绑定操作者/目标/版本/期限/预览摘要；CAS、幂等、部分失败、未知结果查询；扩大权限独立审批，不得自批 |
| ENT-016 | 任务书 :92 | 持久化部署；revision/摘要核对；隔离范围内 allow/deny 行为测试；无法表达的限制拒绝部署；丢响应不盲重放；离线撤权不标已生效；回滚审批/校验、不复活过期授权 |
| ENT-018 | 任务书 :99 | 资产/权限/安全/审计入口；可直接查看风险、权限和运行记录 |

权限域（任务书 §3.2、openshell-policy-safety.v2 编译域、policy_compiler 域表）：**网络、文件系统/路径、进程/命令执行、凭据/秘密、工具/技能**。操作分类：查看权限事实、收窄/撤销、扩大/授予、批量、生效验证、恢复/回滚。分母未加入任务书未要求的域（如 Kubernetes RBAC）；未删除任何已列要求。

## 2. 覆盖矩阵

完整逐行矩阵见 enterprise-permission-coverage-closeout.json（16 行，字段一一对应）。摘要（状态枚举：full=完整代码路径 / partial=部分实现 / view=只读展示 / unsup=明确不支持）：

| 行 | 域 / 操作 | 状态 | 要点 |
| --- | --- | --- | --- |
| 1 | 网络 / 查看事实 | view | GET /permissions（inventory.py:578）+ 前端 PermissionsPage；五态并列；effective 仅 openshell_sync（openshell_sync.py:51，限定 effective 部署目标） |
| 2 | 网络 / 单策略收窄撤销 | partial | 申请、独立审批、预检、执行和读回路径已有；不等于完整共享影响、技能隔离或真实正负行为已验证 |
| 3 | 网络 / 跨策略批量撤销 | partial | 批次执行协议已有；**execute confirm_execution 无页面调用**，但 BatchDraftPanel 已调用 readBatchResult 并展示逐项及 unconfirmed 结果；完整影响确认仍是开放执行入口的前置 |
| 4 | 网络 / 扩大授权 | partial | AgentDetailPage 表单→POST /policies→标准 CR 审批（SoD 拦自批）；专门扩大旅程/策略模板未收口 |
| 5 | 文件系统 / 查看事实 | view | sync_openshell 写 fs.read/fs.write effective facts（openshell_sync.py:71-83） |
| 6 | 文件系统 / 收窄或扩大 | unsup | plan kind=generation→422 static_generation_unavailable（policies.py:560）；create_generation 经 CLI 拒绝（cli_backend.py:161）；无编辑入口 |
| 7 | 进程 / 查看事实 | view | run_as facts（openshell_sync.py:105+）；无前端创建入口（仅审查章节展示） |
| 8 | 进程 / 收窄或扩大 | unsup | 同行 6，fail-closed；无静默丢弃 |
| 9 | 凭据 / 查看事实 | partial | Findings 的 credential 风险不等于凭据权限事实；sync 不产生该域权限 facts，不得称已具备凭据有效权限读回展示 |
| 10 | 凭据 / 授予或修改 | unsup | secrets 只能引用（422 拒明文）；compiler secrets→unsupported 列表；无执行通道 |
| 11 | 工具/技能 / 查看事实 | view | skill-installations/observations、skill-selections（effective_permissions: null 如实展示） |
| 12 | 工具/技能 / 独立限制 | unsup | skill_isolation=not_established 恒定（deployment_impact.py:46-48）；tools_mcp→unsupported_by_backend |
| 13 | 跨域 / 生效验证 | partial | 独立读回 verified/unreachable/mismatch/no_receipt（deployment_verify.py:101-176）；**行为核验缺失：expect_deny 恒空**，enforcement_verified 无生产者 |
| 14 | 跨域 / 回滚恢复 | partial | 后端存在本操作精确前置快照回滚与活体授权复验；缺前端入口，未证明所有过期授权不复活或独立回滚审批闭环；还支持具备 operation_id 的部分失败部署恢复，不能仅按 effective 判断资格 |
| 15 | 绑定 / 撤销漂移联动 | partial | 执行前复验+回滚拒绝联动已实现（binding_identity.py；recheck 合同）；沙箱 revision/Skill 摘要绑定缺失 |
| 16 | 审计 / 追溯治理 | partial | 精确查询+批次同事务审计（CL-06）；完整版本化引用链/保留导出治理待做 |

个人端线（apps/agentshield grant-batch-revoke，grant_batch.go）是企业控制面**之外**的 Go 内嵌 UI 能力，个人端已验收的撤权（business-grant-revoke-e166）**不计入**企业端覆盖。

## 3. 关键安全语义核对结论

以下是指定代码路径的静态核对，不是全系统安全证明；未运行负例不能据此排除其他路径缺陷。

1. **effective 来自读回**：所检查的 openshell-cli 路径在 apply 后独立 readback 通过时写入 effective，level=readback_verified；没有本轮真实行为验收。当前 Edge publish_policy 成功回执仍按不支持处理，不外推“sent 永远不可能经任何其他路径变化”。
2. **desired/declared/observed 不冒充 effective**：成立。PermissionFact.state 枚举分离（models.py:375）；全库仅 sync_openshell 写 state=effective 且 authority=openshell；绑定 active≠运行归属证明（enterprise-runtime-binding-identity.v1）。
3. **不支持即拒绝**：成立。未知字段 UnsupportedCapability→422 compile_rejected（policy_compiler.py:80-82, policies.py:550）；静态边界→422 static_generation_unavailable；非 block 模式→422 capability_unsupported；无静默丢弃路径。
4. **技能无法独立约束时诚实展示**：成立（deployment_impact.py:46-48 恒定 not_established；BatchItemReview.tsx:47 UI 明示"尚未建立证明，不能确认执行"）。
5. **shared_runtime_occupants=unknown、execution_confirmation_supported=false**：仍成立（deployment_impact.py:46-48 硬编码常量；合同语义未放宽）。
6. **提出者不能自批**：覆盖写通道。唯一批准入口 _approve_change_request（policies.py:310）+ change_review 复核 blockers（:188-205）；批量执行 confirm_execution 仅确认执行已批变更、不是审批（enterprise-batch-execution.v1）；batch revoke 合同明示 never authorizes bulk approval。
7. **批量逐项绑定**：成立。原子预留先落库再执行（batch_reservation.py:26-104）；逐项结果回读重验 change_id/env/binding/target+双摘要（deployment_batch_result.py:57-76）。
8. **离线/超时/丢响应区分**：成立。sent 占位→永不 effective；后端不可达→unreachable；结果不明→502 deployment_submission_unconfirmed；执行期 unconfirmed 停止后项且不标无效果。
9. **回滚授权与过期边界**：已实现当前权限、绑定、变更/策略、来源身份、目标授权与网关身份复验，并仅恢复本操作前置快照；这不自动证明旧快照中的所有权限仍未过期，也不等于新增独立回滚审批已完成。该要求保留为待核实/实现项。
10. **审计查询≠完整追溯**：当前确为精确查询+同事务批次审计；完整设备→角色/Skill 版本→运行身份→执行→效果链未闭合（CL-06 遗留），未发现混淆宣称。

**疑似缺陷**：本轮未发现可写"已证实漏洞"的点（未执行负例）。一个设计性观察：readback 验证的 expect_deny 恒为空列表（policies.py:631），即当前验证只证 allow 侧配置一致，deny/行为侧无证据——这是已知的诚实缺口（ENT-016 行为核验），非隐藏缺陷；编译器也明确拒绝制造虚构 deny 探针（test_deployment_does_not_invent_conflicting_deny_probe）。

## 4. 后续开发切片（≤4）

**S1 批量执行与恢复的前端闭环**（ENT-015/018，依赖 S4 和恢复授权边界确认）
- 用户可见缺失：多选批次确认执行和回滚触发未接通；未知结果查询已有，不重建。
- 拥有者文件：apps/web/src/api/deploymentBatch.ts（已有 executeBatchDraft 无调用方）、components/batch-deployment/BatchDraftPanel.tsx、pages/ChangesPage.tsx、api/changeExecution.ts；新增确认对话框组件。
- 最小范围：完整影响披露及其执行绑定前置完成后，显式确认 UI→既有 execute；复用逐项结果/unknown 查询。回滚资格来自后端现有协议（包括具备操作证据的部分失败恢复），不是仅检查 effective 即开放。
- 必须保持：confirm_execution 不承载审批；自批拦截；执行失败不清理预留。
- 最小验收：合成浏览器冒烟全链 + 既有 batch 测试不回归；showing unconfirmed 不渲染为成功。
- 前置未满足时保持只读，不因后端端点可调用就加按钮；回滚审批/授权期限语义需先核清。此处不是执行入口开发授权。

**S2 扩大授权与策略模板的独立审批旅程**（ENT-015）
- 缺失：扩大权限无专门旅程与模板；审查界面未突出 needs_generation/unsupported 项。
- 拥有者文件：apps/web/src/pages/ChangesPage.tsx、ChangeReviewDialog.tsx、AgentDetailPage.tsx；后端 change_review.py 仅补展示投影（只读字段）。
- 必须保持：扩大与收窄同一独立审批与 SoD；模板不得绕过 CR。
- 验收：扩大 CR 自批负例（既有 test_change_review）+ 合成旅程正向；模板生成的策略必经 preview_digest 绑定。
- 用户决策点：策略模板的初始范围清单需业务方提供。

**S3 行为核验通道（allow/deny 实证）**（ENT-016）
- 缺失：expect_deny 恒空；无 enforcement_verified 生产者。
- 拥有者文件：apps/control-api/app/deployment_verify.py、adapters/openshell/contracts.py、routers/policies.py（verify checks 构造）。
- 最小范围：隔离范围内 deny 探测 fixture 通道，产出 level=enforcement_verified（仅真实通道可标，组件测试禁止，遵循 openshell-policy-safety.v2 O04）。
- 必须保持：配置读回与行为验证等级分离；不得把填入 expect_deny 当作执行了行为探针，不因行为核验未完成而擅自重定义既有 effective/readback_verified 合同；不得为通过而收缩期望集。
- 验收：真实 OpenShell 正负行为对照（deny 实测）——**同时是资源门禁**：需受控真实网关目标，无授权只做准备。
- 用户决策点：提供获准测试的 OpenShell 目标与范围。

**S4 绑定失效联动与共享影响确认收口**（ENT-013，CL-04 协同）
- 缺失：沙箱 revision、Skill 摘要未进绑定身份；完整共享影响确认与执行复验未绑定（当前 registered_binding_only 不可当执行确认）。
- 拥有者文件：app/binding_identity.py、routers/bindings.py、models.py+必要迁移及 deployment_impact.py；影响预检与单/批预览的一致性子项已验收，不能再列为等待项；它们没有解决本切片的完整共享影响缺口。
- 必须保持：人工登记/attestation 不升格归属证明；unknown 保持 unknown；复验失败不释放既有 pending 记录的现有语义。
- 验收：revision 变化/吊销/Skill 摘要变化的正负测试；共享影响明示后禁止自动部署。
- 用户决策点：共享沙箱独占性判定标准需业务确认，不由模型设定。

执行顺序：先推进 S4 的证据与共享影响前置；满足后才推进 S1，S2 仍受同一前置与模板决策约束。S3 的实现合同准备可并行，但真实探针必须有目标与授权。

资源门禁（非代码任务，单列）：真实 OpenShell 目标与授权范围（S3、S2 部分验收）、真实设备/双架构原生验收（CL-07）、保留期限/删除规则等合规决策（CL-06）。这些资源门禁不替代代码缺口。

## 5. 直接回答

- **已有哪些可用代码路径**：网络收窄申请、独立审批、预览、提交/批次预留、OpenShell 动态执行、独立配置读回和受限回滚已有实现；不是完整影响确认和真实行为闭环全部就绪。批次逐项/未知结果查询已有前端。
- **哪些只是展示或模拟证据**：文件系统/进程有配置读回事实；凭据风险展示不是凭据权限读回，技能声明/安装观察不等于运行加载及有效权限。fake 仅组件证据，个人端撤权不计入企业端；当前 expect_allow/expect_deny 属配置检查，不能把其中任何一侧称为行为实证。
- **还缺哪些必须开发的链路**：批量执行/回滚的前端触发、扩大授权专门旅程、行为核验通道、沙箱 revision/Skill 摘要绑定与撤销联动、完整审计追溯链与保留导出治理。
- **主开发者先做哪一项**：**S4** 的证据绑定与共享影响前置。`BatchDraftPanel` 明确在完整影响披露接通前只读，`execution_confirmation_supported=false` 不能由新增按钮变成已确认。S1 待前置满足后再接既有执行协议，不能将“没有调用方”误判成唯一缺口。

## 6. 主开发者复核口径

16 行是审阅条目，不是任务书全部“权限域 × 操作”的笛卡尔积，也不是可据以计算完成率的分母。明确不支持表示安全边界诚实，不表示原任务要求已经完成；凭据/工具域限制仍需按原目标处理。全库唯一生产者、所有通道均无静默丢弃等全称断言未由本次只读审阅充分证明，只作为待验证主张，不能据此放宽安全门禁。历史测试引用仅作定位，不代表每项引用均有对应当前行为验收。
