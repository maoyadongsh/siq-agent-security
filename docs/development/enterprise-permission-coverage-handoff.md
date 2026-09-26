# CL-05-PERMISSION-COVERAGE-CLOSEOUT 交接说明

日期：2026-09-26。执行者：后端能力与交付工程师（本子任务）。状态：核对完成，未提交、未推送、未部署。

## 1. 实际新增文件

| 文件 | 性质 |
| --- | --- |
| docs/development/enterprise-permission-coverage-closeout.md | 覆盖核对报告（分母、矩阵摘要、十项安全语义结论、≤4 开发切片、资源门禁、四问回答） |
| docs/development/enterprise-permission-coverage-closeout.json | 逐项矩阵（16 行 × 17 字段）+ 安全语义 10 条 + 切片/门禁/个人端排除清单。复查材料，非新公共合同 |

未修改任何其他文件；未触碰 Kimi（OpenClaw 采集）、Qwen（AuditPage 可复现性）、DeepSeek（deployment_impact.py/deployment_submission 在途）、主开发者（Edge 安装换代）各自在途文件；未改动上一轮 source-freeze-preflight 工具。

## 2. 核对方法（对应任务 Method A–E）

- **A 冻结分母**：任务书 ENT-013~016/018（taskbook :89-92,99，已逐行回读核实原文）、closeout CL-04/05/06、四份合同（deployment-impact.v1、runtime-binding-identity.v1、batch-execution.v1、openshell-policy-safety.v2 全文）。域：网络/文件系统/进程/凭据/工具技能；操作：查看/收窄/扩大/批量/生效验证/回滚。
- **B 逐项真实调用链**：两条并行 Explore 追踪（前端、后端），再对本轮关键结论亲自回读源码（SoD policies.py:310；needs_generation 422 :558-560；cli_backend.py:552；fake_backend.py:173；deployment_impact.py:46-48；openshell_sync.py:51-83；deployment_verify.py:101-176；batch_reservation/deployment_batch_result；rollback 授权器 :889-936；Edge 回执恒 fail-closed environments.py:60-74,605）。未以文件/按钮存在性证明链路。
- **C 矩阵**：见 JSON；证据级别区分 source_read / historical_tests / this_round_execution（本轮无）/ real_environment（本轮无）。个人端（agentshield grant_batch.go、business-grant-revoke-e166）显式排除于企业覆盖。
- **D 十项安全语义**：逐条结论在 MD §3 与 JSON security_semantics；无"已证实漏洞"（未执行负例）；一处设计性观察（expect_deny 恒空）如实记录为已知缺口。
- **E 收敛**：4 个切片（S1 批量执行/回滚前端闭环、S2 扩大旅程与模板、S3 行为核验通道、S4 绑定身份收口），真实平台项单列资源门禁；权限扩大授权、审批豁免、保留期限、共享沙箱独占性等均未擅决，标为用户决策。

## 3. 执行过的命令（均为只读）

- `git -C /home/maoyd/siq/siq-agent-security rev-parse HEAD / branch / status --porcelain`（快照记录）
- `grep -n "ENT-01[3-8]" docs/development/enterprise-auto-onboarding-taskbook-20260925.md`（回核引用行号）
- 源码阅读（Read/grep），未运行任何测试、未连接真实后端/CLI/设备/数据库。

## 4. 校验结果（少而充分）

- Markdown 与 JSON 逐项一致（状态/证据级别/引用/缺失链对应）。
- JSON 经标准库 `json.load` 解析通过；枚举与必填字段一致（见下方命令记录）。
- 所引用文件与测试均确认存在于本仓（本轮以 grep/ls 回核，含 145 个测试文件清单内的引用项）。
- `git diff --check`：新文件无空白错误；无尾随空白。
- 快照：HEAD `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0`，main，2026-09-26T05:59:38Z，639 条脏条目；阅读期间工作树有他人在途变动的可能，不声称原子快照。

## 5. 已知限制

- 行号以阅读时工作树为准，DeepSeek 在途修改 deployment_impact.py/deployment_submission 后可能漂移。
- 全部测试引用为历史记录（各自 handoff），本轮未复跑；历史通过不作为本轮证据。
- fake 后端证据仅组件级；企业真实 OpenShell/设备验收未做（资源门禁）。
- JSON 为复查材料，不是新公共合同，未加入任何合同目录。

## 6. 范围声明

仅完成企业权限治理能力覆盖核对并产出报告；不声明 CL-05 完成，不声明整体项目完成。未提交、未推送、未部署；未读取 admin-password.private、真实 .env、令牌、私钥、设备种子；未扫描 backups、运行状态目录或真实用户配置。

## 7. 主开发者复核与修正（2026-09-26）

原建议不能直接作为执行入口开发依据，已同步修改 Markdown 与 JSON，保留 16 行审阅条目和四个切片，不修改产品代码：

1. `BatchDraftPanel.tsx` 已调用 `readBatchResult`，包含刷新、逐项记录及 unconfirmed 提示。“前端不能查询未知结果”错误，已纠正。
2. 同一页面明确只读直至完整影响披露接通；影响合同仍是 registered_binding_only/unknown/not_established/false。没有 executeBatchDraft 页面调用方并非唯一缺口。撤回“S1 补按钮即可闭环”，改为先 S4 证据与共享影响前置，再允许安排 S1；没有修改任何安全门禁。
3. 网络单策略行由 full_code_path 改为 partial；已有执行/读回接口不等于完整目标已经实现。明确不支持也不能作为原任务完成。
4. credential 风险展示不等于凭据权限事实。该行由 view_only 改为 partial；配置读回 expect_allow/expect_deny 两侧均不是实际网络行为探针。
5. 回滚活体复验不直接证明任何旧快照权限都未过期或独立回滚审批完整。后端也支持部分具备 operation_id 的 failed 部署恢复，不应预先把前端资格限定为 effective。
6. 影响与预览一致性线已验收，不再写为 S4 等待中的开发冲突；不把这两项完成误当成共享影响完整。
7. JSON 中 `owner_files` 的“新增 rollback 客户端”说明原来不是实际路径，改为现有拥有者文件。全称安全结论收窄为所列源码路径依据，未实测的不称已证明。

执行了标准库 JSON 解析、16 行/必填字段/枚举检查、source_references 与 test_references 及 owner_files 的路径存在性核对、Markdown 行号与状态对应核对，以及 diff/尾随空白检查。未运行产品测试、未联网核验外部规范、未调用任何真实后端。文件存在不能证明测试覆盖了对应结论，历史测试引用只作定位。

当前矩阵仍是源码级收口审阅材料，不是所有“域×操作”的完整分母，不能计算完成率，也不是接口开放/扩大权限的授权。后续开发顺序以本节及已修正 MD/JSON 为准，前文原交付的方法与快照保留为历史记录。

本次仅修改本任务三个文档文件。未提交、未推送、未部署，不关闭 CL-05。
