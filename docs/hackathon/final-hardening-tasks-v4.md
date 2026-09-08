# Final Hardening V4 开发任务台账

更新：2026-09-08。开发已启动；实际结果见 [开发进度](final-hardening-progress-v4.md)。未通过最终门禁的任务保持 in_progress/todo。

[当前开发目标](final-hardening-goal-v4.md) · [用户原文](final-hardening-requirements-v4.md) · [源码审计](final-hardening-audit.md) · [机器可读台账](final-hardening-tasks-v4.json)

JSON 为任务状态事实源；本页与 JSON 同步维护。`evidence_required` 是验收要求，`evidence` 才是实际结果；预计产物路径不表示文件已经生成。不得因文件存在或 V3 曾通过而把 V4 标为完成。

阶段：0 基线/范围 → 1 Model Egress → 2 Dynamic Skills 与所需 C/F UI → 3 Regression → 4 PR/Remote CI → 5 Clean RC → 6 Evidence → 7 Demo/Video/Docs → 8 总验收。C/F 为原文 P1，但其可见性要求也是 DoD，须进入最终回归；不增加比赛外功能。

D4–D8 的打包代码应在 D1 前实现并参与测试，任务完成门禁必须等 D2 后的干净源码实构建。若远端 CI 或 RC 发现代码问题，修复提交后回到 D2，重新冻结；禁止绕过顺序。文档证据可以提前整理，最终定稿依赖真实产物。

external/manual 项与独立工程并行跟踪，不是本轮已有权限的假设；视频录制是必需工程交付，视频上传才是外部动作。PR 保持待审，可冻结其已通过 CI 的精确 head，不自行 merge。

| ID | 优先级 | 阶段 | 状态 | 任务 | 依赖 |
| --- | --- | ---: | --- | --- | --- |
| V4-BASE | P0 | 0 | done | 同步比赛基线并创建 V4 分支 | — |
| V4-AUDIT | P0 | 0 | done | 重新审计当前源码与已有证据 | V4-BASE |
| V4-SCOPE | P0 | 0 | done | 锁定范围、不变量与执行门禁 | V4-AUDIT |
| V4-A1 | P0 | 1 | done | 可信数据分级与来源敏感度 | V4-SCOPE |
| V4-A2 | P0 | 1 | done | ModelProvider 能力与 locality 声明 | V4-A1 |
| V4-A3 | P0 | 1 | done | 分离远程规划与本地敏感推理 | V4-A2 |
| V4-A4 | P0 | 1 | done | 显式 Provider 切换与审计 | V4-A2 |
| V4-A5 | P0 | 1 | done | ModelRouter 研究路径强制策略 | V4-A3, V4-A4 |
| V4-A6 | P0 | 1 | done | Planning payload 白名单与最小化 | V4-A1, V4-A3 |
| V4-A7 | P0 | 1 | done | 模型出网元数据与 UI 合同 | V4-A5, V4-A6 |
| V4-A8 | P0 | 1 | done | Model Egress 八项正负向测试 | V4-A4, V4-A5, V4-A6, V4-A7 |
| V4-B1 | P0 | 2 | done | 内部 TaskPlan V2 合法子集 | V4-A8 |
| V4-B2 | P0 | 2 | done | 闭集 Registry 元数据和依赖 | V4-B1 |
| V4-B3 | P0 | 2 | done | 拒绝未知 Skill 与伪造 authority Skill | V4-B2 |
| V4-B4 | P0 | 2 | done | 依赖校验与有界重规划决策 | V4-B2, V4-B3 |
| V4-B5 | P0 | 2 | done | 子集执行、Authority 和 Completion 适配 | V4-B4 |
| V4-B6 | P0 | 2 | done | 动态计划 Demo 与服务状态 | V4-B5 |
| V4-B7 | P0 | 2 | done | Skill Planning 八项测试 | V4-B3, V4-B4, V4-B5, V4-B6 |
| V4-C1 | P1 | 2 | done | DGX 真实硬件卡与探测状态 | V4-A7, V4-B7 |
| V4-C2 | P1 | 2 | done | 逐个 Model Action 标注 locality | V4-C1 |
| V4-C3 | P1 | 2 | done | 精简真实 DGX 指标 | V4-C1 |
| V4-C4 | P1 | 2 | done | DGX 故障 fail-closed | V4-A8, V4-C1, V4-C2 |
| V4-F1 | P1 | 2 | done | 冻结四块比赛页面结构 | V4-B7 |
| V4-F2 | P1 | 2 | done | 实际选择的 Skills 视觉突出 | V4-F1, V4-B6 |
| V4-F3 | P1 | 2 | done | 决策和 reason_code 可读 | V4-F1 |
| V4-F4 | P1 | 2 | done | MCP 与同值不同来源展示 | V4-F3 |
| V4-F5 | P1 | 2 | done | 伪成功和效果状态展示 | V4-F3 |
| V4-I1 | P0 | 3 | done | Secure Agent 完整回归 | V4-B7, V4-C4, V4-F2, V4-F4, V4-F5 |
| V4-I2 | P0 | 3 | done | AgentShield 安全内核回归 | V4-I1 |
| V4-I3 | P0 | 3 | done | Full Repo checks 和依赖安全检查 | V4-I2 |
| V4-I4 | P0 | 3 | done | Competition 九场景 E2E | V4-I3 |
| V4-I5 | P0 | 3 | done | 独立 StepFun cohort | V4-I4 |
| V4-I6 | P0 | 3 | done | DGX 本地敏感推理与零远程泄漏证明 | V4-I5 |
| V4-I7 | P0 | 3 | done | 控制基准和性能 delta | V4-I6 |
| V4-D1 | P0 | 4 | in_progress | 提交并创建 V4 → V3 PR | V4-I7 |
| V4-D2 | P0 | 4 | in_progress | 真实 pull_request CI green | V4-D1 |
| V4-D3 | P0 | 4 | done | 仓库治理人工操作文档 | V4-AUDIT |
| V4-D4 | P0 | 5 | in_progress | 精确提交冻结与 clean checkout 构建 | V4-D2 |
| V4-D5 | P0 | 5 | in_progress | 精确 Candidate Source Identity | V4-D4 |
| V4-D6 | P0 | 5 | in_progress | 准备 RC 版本与命名 | V4-D5 |
| V4-D7 | P0 | 5 | in_progress | RC 产物清单与解包启动 | V4-D6 |
| V4-D8 | P0 | 5 | in_progress | 复用签名机制并准确标注发布信任 | V4-D7 |
| V4-E1 | P0 | 6 | in_progress | 五主题 Canonical Evidence Index | V4-D8 |
| V4-E2 | P0 | 6 | in_progress | 引用式 Evidence Manifest | V4-E1 |
| V4-E3 | P0 | 6 | in_progress | 简化入口并保留原始证据 | V4-E2 |
| V4-E4 | P0 | 6 | in_progress | 比赛摘要与准确分母 | V4-E3, V4-I7 |
| V4-G1 | P0 | 7 | done | 冻结唯一主故事与一键演示入口 | V4-E4 |
| V4-G2 | P0 | 7 | done | Act 1 正常动态选择与交付 | V4-G1 |
| V4-G3 | P0 | 7 | done | Act 2 MCP Injection | V4-G2 |
| V4-G4 | P0 | 7 | done | Act 3 同值不同来源 | V4-G3 |
| V4-G5 | P0 | 7 | done | Act 4 Fake Success | V4-G4 |
| V4-G6 | P0 | 7 | done | Act 5 可选 Human Approval | V4-G5 |
| V4-H1 | P0 | 7 | in_progress | 录制最终 2–3 分钟真实视频 | V4-G6 |
| V4-H2 | P0 | 7 | in_progress | 视频真实性与可复核性审核 | V4-H1 |
| V4-J1 | P0 | 7 | done | 同步 README、HACKATHON 和架构叙事 | V4-E4, V4-G6 |
| V4-J2 | P0 | 7 | done | 保留所有剩余风险并审查夸大声明 | V4-J1 |
| V4-J3 | P0 | 7 | in_progress | 更新工程报告与提交清单 | V4-H2, V4-J2 |
| V4-REPORT | P0 | 7 | in_progress | Final Engineering Report V4 | V4-J3, V4-D3 |
| V4-ACCEPT | P0 | 8 | todo | V4 总验收与功能冻结 | V4-REPORT |
| V4-EXT-GOV | P0 | 8 | todo / external/manual | 人工设置 main 保护 | V4-D3 |
| V4-EXT-SIGN | P0 | 8 | todo / external/manual | 正式签名材料与签名执行（条件项） | V4-D8 |
| V4-EXT-RELEASE | P0 | 8 | todo / external/manual | 官方 RC 发布（条件项） | V4-D8 |
| V4-EXT-VIDEO | P0 | 8 | todo / external/manual | 比赛视频上传（外部提交） | V4-H2 |

## V4-BASE · 同步比赛基线并创建 V4 分支

原文：§1。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`docs/hackathon/final-hardening-goal-v4.md`。

依赖：无。

验收：

- [x] fetch --all --prune、比赛分支 pull --ff-only 成功
- [x] 记录 starting_sha、干净工作区及最近十条提交
- [x] 从最新比赛 HEAD 创建 codex/hackathon-final-hardening-v4；不改 main

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：git fetch --all --prune: exit 0; git pull --ff-only: Already up to date；starting_sha=9b4aaeae1a089b54fbbc50c33cdb72616be2b1b1；git status --short --branch: clean before edits；git switch -c codex/hackathon-final-hardening-v4: succeeded

## V4-AUDIT · 重新审计当前源码与已有证据

原文：§2。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`docs/hackathon/final-hardening-audit.md`。

依赖：V4-BASE。

验收：

- [x] 覆盖原文列出的八个目录和六份文档
- [x] 分类 implemented/evidenced/needs-hardening/unverified/future
- [x] 旧证据保留原 SHA、provider 与范围；源码检查不冒充新回归

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/final-hardening-audit.md（源码/证据文件检查，未重跑应用回归）

## V4-SCOPE · 锁定范围、不变量与执行门禁

原文：§0, §3, §76, §77, §81, §82。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`docs/hackathon/final-hardening-goal-v4.md`、`docs/hackathon/final-hardening-tasks-v4.json`。

依赖：V4-AUDIT。

验收：

- [x] INV-1 至 INV-8 全程保留
- [x] 不新增禁止模块、不重构冻结内核，明确 bug 除外
- [x] 按 P0 顺序执行；采用建议提交序列并遵循仓库提交格式
- [x] 外部动作不阻塞无依赖工程；未执行不标完成

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：V4 implementation in current branch; validation checkpoint docs/hackathon/final-hardening-progress-v4.md

## V4-A1 · 可信数据分级与来源敏感度

原文：§4, §5, §6。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/contracts.py`、`apps/secure-agent/secure_agent/service.py`、`apps/secure-agent/secure_agent/confidential.py`。

依赖：V4-SCOPE。

验收：

- [x] PUBLIC/INTERNAL/CONFIDENTIAL/SECRET 显式枚举
- [x] 区分 public metadata、public source、private source、confidential fixture、secret
- [x] 敏感度来自 operator/config；模型不得降级；公共 GitHub 源码不默认当企业私有

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-A2 · ModelProvider 能力与 locality 声明

原文：§7。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/models.py`。

依赖：V4-A1。

验收：

- [x] Provider 明确 locality、allowed_sensitivity、can_receive_raw_source
- [x] StepFun=remote，Ornith=local_dgx；受信配置与端点验证决定，不能取模型自报

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-A3 · 分离远程规划与本地敏感推理

原文：§8, §68, §69。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/application.py`、`apps/secure-agent/secure_agent/models.py`、`docs/hackathon/architecture.md`。

依赖：V4-A2。

验收：

- [x] StepFun 处理非敏感理解、规划、Skill 选择
- [x] DGX 本地承担敏感源码/私有文档分析
- [x] 规划和研究可使用不同 provider；模型输出保持 proposal，SIQ 独立授权

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-A4 · 显式 Provider 切换与审计

原文：§9。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/models.py`、`apps/secure-agent/secure_agent/service.py`、`scripts/hackathon/manage.py`。

依赖：V4-A2。

验收：

- [x] 超时/失败不静默换模型或迁移源码
- [x] provider_transition 包含 from_provider/to_provider/reason/task_id/sensitivity/allowed
- [x] operator 显式切换也必须重查策略并记录允许/拒绝；拒绝不发请求

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-A5 · ModelRouter 研究路径强制策略

原文：§10。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/skills.py`、`apps/secure-agent/secure_agent/application.py`、`apps/secure-agent/secure_agent/models.py`。

依赖：V4-A3, V4-A4。

验收：

- [x] 替换直接 self._model.research 路径，含 preparation 和 CommittedProvider 复用路径
- [x] PUBLIC 可按策略远程或本地；INTERNAL 可信配置；CONFIDENTIAL 仅 DGX 本地；SECRET 本地或拒绝
- [x] 未知等级/本地不可用拒绝，不回退远程；来源注入不得改变路由

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-A6 · Planning payload 白名单与最小化

原文：§11。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/models.py`、`apps/secure-agent/secure_agent/contracts.py`。

依赖：V4-A1, V4-A3。

验收：

- [x] 仅允许经可信策略批准的 task goal、repo identifier、selected paths、Skill catalog、public metadata
- [x] 不含 raw source、secret、机密 fixture、来源签名、SIQ 签名材料或 admin credential
- [x] 用户 goal/question 自身含敏感文本也不得绕过分类直接发远程；白名单不等于自动公开

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-A7 · 模型出网元数据与 UI 合同

原文：§12。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/models.py`、`apps/secure-agent/secure_agent/service.py`、`apps/web/src/local/pages/DemoPage.tsx`。

依赖：V4-A5, V4-A6。

验收：

- [x] 每次远程调用记录 model_provider/model/operation/task_id/payload_digest/payload_classification/elapsed_ms/status
- [x] 拒绝和失败也可追踪，不记录 API key/raw confidential prompt/full sensitive payload
- [x] 公开 StepFun Remote Planning / Ornith DGX Local Analysis 状态；检查 recipient 等全部模型调用面

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-A8 · Model Egress 八项正负向测试

原文：§13, §70。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/tests/test_models.py`、`apps/secure-agent/tests/test_provider_config.py`、`apps/secure-agent/tests/test_skills.py`。

依赖：V4-A4, V4-A5, V4-A6, V4-A7。

验收：

- [x] ME-01 PUBLIC 配置允许 StepFun research
- [x] ME-02 CONFIDENTIAL raw-content StepFun 调用拒绝，断言零外发
- [x] ME-03 CONFIDENTIAL Ornith local 允许
- [x] ME-04 StepFun timeout 不迁移源码
- [x] ME-05 operator 显式切换有审计
- [x] ME-06 模型不能改敏感度
- [x] ME-07 source injection 不能升级远程 provider
- [x] ME-08 secret/config 不进入 diagnostics
- [x] 采用 transport spy/捕获请求校验所有 payload，不能只断言错误文本

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-B1 · 内部 TaskPlan V2 合法子集

原文：§14, §15, §16。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`packages/contracts/model-task-plan.schema.json`、`apps/secure-agent/secure_agent/contracts.py`、`apps/secure-agent/secure_agent/models.py`、`apps/control-api/app/tests/test_hackathon_model_contracts.py`。

依赖：V4-A8。

验收：

- [x] 允许 research、research+report、research+report+delivery 三种选择
- [x] 应用内部 V2 合同先行，同步 provider schema、fixtures 和消费者；旧合同明确兼容或版本化
- [x] prompt 不再要求三项必须全部出现，计划本身不授予权限

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-B2 · 闭集 Registry 元数据和依赖

原文：§17, §18。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/skills.py`、`skills/secure-research/SKILL.md`、`skills/secure-report/SKILL.md`、`skills/secure-delivery/SKILL.md`。

依赖：V4-B1。

验收：

- [x] research requires=[]；report requires=[research]；delivery requires=[report]
- [x] 包含 name/description/input_schema/output_schema/requires/allowed_tools/security_requirements
- [x] 确定性 validator 使用受信内置 registry；不加载第三方可执行 Skill

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-B3 · 拒绝未知 Skill 与伪造 authority Skill

原文：§19。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/contracts.py`、`apps/secure-agent/secure_agent/skills.py`。

依赖：V4-B2。

验收：

- [x] unknown Skill 返回 skill_unregistered
- [x] 禁止将未知名称映射成 shell/HTTP/generic tool
- [x] tool 名、approval/signing Skill 不能获得可执行入口

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-B4 · 依赖校验与有界重规划决策

原文：§20。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/contracts.py`、`apps/secure-agent/secure_agent/runtime.py`。

依赖：V4-B2, V4-B3。

验收：

- [x] delivery 缺 report、跳依赖、顺序错误返回 plan_dependency_invalid
- [x] 重复 Skill 拒绝，除非另有明确合同
- [x] 不偷偷补齐计划；可直接返回结构化错误；如采用 replan 最多两次总规划并可审计

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-B5 · 子集执行、Authority 和 Completion 适配

原文：§16, §17, §71。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/application.py`、`apps/secure-agent/secure_agent/authority.py`、`apps/secure-agent/secure_agent/runtime.py`、`apps/secure-agent/secure_agent/security.py`。

依赖：V4-B4。

验收：

- [x] 两阶段预承诺和重读按已选 Skills 运行；research-only 不生成或交付报告
- [x] report-only 组合不触发 recipient/MCP/send_message
- [x] effect requirements 仅包含 operator 授权且实际选择的效果，研究完成不冒充交付 verified
- [x] 保留签名 Intent、来源绑定、摘要承诺、撤销和所有 ToolGateway 入口，不重写核心合同

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-B6 · 动态计划 Demo 与服务状态

原文：§21。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/service.py`、`scripts/hackathon/manage.py`、`apps/web/src/local/pages/DemoPage.tsx`。

依赖：V4-B5。

验收：

- [x] 支持只分析不要发出去与完整交付两条输入
- [x] 每个 task 公开实际 selected Skills、执行状态及未选择项；不拿静态 catalog 冒充计划
- [x] research-only/research+report 可单命令或 dashboard action 重复

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-B7 · Skill Planning 八项测试

原文：§22, §71。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/tests/test_models.py`、`apps/secure-agent/tests/test_skills.py`、`apps/secure-agent/tests/test_application.py`。

依赖：V4-B3, V4-B4, V4-B5, V4-B6。

验收：

- [x] SP-01 research only=1 Skill
- [x] SP-02 research+report=2 Skills
- [x] SP-03 full delivery=3 Skills
- [x] SP-04 delivery without report 拒绝
- [x] SP-05 unknown Skill 拒绝
- [x] SP-06 duplicate Skill 拒绝
- [x] SP-07 tool name as Skill 拒绝
- [x] SP-08 approval/signing Skill 拒绝
- [x] 负向用例在工具执行前拒绝；合法子集经过真实 SIQ 与 ToolGateway

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-C1 · DGX 真实硬件卡与探测状态

原文：§23, §24。优先级：P1；状态：done；类型：engineering。

修改/交付位置：`deploy/dgx-spark/preflight.py`、`apps/secure-agent/secure_agent/service.py`、`apps/web/src/local/pages/DemoPage.tsx`。

依赖：V4-A7, V4-B7。

验收：

- [x] 实际 preflight/runtime 提供 DGX 名称、GPU、local model、inference/runtime 状态
- [x] GB10/READY 不硬编码；读取失败 UNVERIFIED
- [x] 模型列表可达不等于 inference 成功；展示证据时间避免把历史结果当当前健康

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-C2 · 逐个 Model Action 标注 locality

原文：§25。优先级：P1；状态：done；类型：engineering。

修改/交付位置：`apps/web/src/local/pages/DemoPage.tsx`。

依赖：V4-C1。

验收：

- [x] 每个动作显示 REMOTE StepFun 或 LOCAL DGX Spark Ornith
- [x] 敏感研究明确 LOCAL ANALYSIS；来源是受信配置和实际调用记录

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-C3 · 精简真实 DGX 指标

原文：§26。优先级：P1；状态：done；类型：engineering。

修改/交付位置：`deploy/dgx-spark/preflight.py`、`apps/web/src/local/pages/DemoPage.tsx`。

依赖：V4-C1。

验收：

- [x] 仅 current model、inference duration、GPU model 和可选 GPU utilization
- [x] 不堆 CUDA kernel statistics/full nvidia-smi；缺测不造数

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-C4 · DGX 故障 fail-closed

原文：§27。优先级：P1；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/secure_agent/models.py`、`apps/web/src/local/pages/DemoPage.tsx`、`apps/secure-agent/tests/test_application.py`。

依赖：V4-A8, V4-C1, V4-C2。

验收：

- [x] GPU/local model 不可达显示 DGX LOCAL MODEL UNAVAILABLE
- [x] CONFIDENTIAL 任务失败关闭，远程 transport 调用数为零
- [x] 错误不含凭据、配置值或原始敏感 payload

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-F1 · 冻结四块比赛页面结构

原文：§42, §43。优先级：P1；状态：done；类型：engineering。

修改/交付位置：`apps/web/src/local/pages/DemoPage.tsx`、`apps/web/src/local/pages/demo.css`。

依赖：V4-B7。

验收：

- [x] 保持 CURRENT TASK / AGENT SKILLS / SECURITY DECISIONS / EFFECT-COMPLETION
- [x] 评委十秒内识别任务、选用能力、裁决和结果；不增加复杂安全后台控件

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-F2 · 实际选择的 Skills 视觉突出

原文：§44。优先级：P1；状态：done；类型：engineering。

修改/交付位置：`apps/web/src/local/pages/DemoPage.tsx`、`apps/web/src/local/pages/demo.css`。

依赖：V4-F1, V4-B6。

验收：

- [x] 显示 1/2/3 项真实计划及完成/运行标记
- [x] research-only 单项明确；未选 report/delivery 不显示为已执行

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-F3 · 决策和 reason_code 可读

原文：§45。优先级：P1；状态：done；类型：engineering。

修改/交付位置：`apps/web/src/local/pages/DemoPage.tsx`。

依赖：V4-F1。

验收：

- [x] ALLOW/DENY/HOLD 和 reason_code 默认可见
- [x] 专业详情折叠；UI 不自行裁决或伪造运行结果

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-F4 · MCP 与同值不同来源展示

原文：§46。优先级：P1；状态：done；类型：engineering。

修改/交付位置：`apps/web/src/local/pages/DemoPage.tsx`、`scripts/hackathon/browser-smoke.py`。

依赖：V4-F3。

验收：

- [x] MCP attacker@evil.example / UNTRUSTED / DENY 从真实读回显示
- [x] alice@company.example Trusted Directory ALLOW 与 MCP DENY 均可验证
- [x] 不依赖字符串相同推导信任

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-F5 · 伪成功和效果状态展示

原文：§47。优先级：P1；状态：done；类型：engineering。

修改/交付位置：`apps/web/src/local/pages/DemoPage.tsx`、`scripts/hackathon/browser-smoke.py`。

依赖：V4-F3。

验收：

- [x] TOOL REPORTED success、EFFECT EVIDENCE missing、COMPLETION INCOMPLETE 分开
- [x] 保留 verified/incomplete/conflicting；UNKNOWN 不视为成功

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-I1 · Secure Agent 完整回归

原文：§58, §59。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/secure-agent/tests/`。

依赖：V4-B7, V4-C4, V4-F2, V4-F4, V4-F5。

验收：

- [x] 全部现有测试通过
- [x] 新增 model-egress/dynamic-plan/DGX-locality/provider-switch/skill-dependency 测试通过
- [x] 记录实际命令、数量、失败与对应 SHA，不沿用 V3 数字

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-I2 · AgentShield 安全内核回归

原文：§60。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`apps/agentshield/`。

依赖：V4-I1。

验收：

- [x] go test ./...、go test -race ./...、go vet ./... 全通过
- [x] Authority Hard Gate、Intent V2/V3、Provenance、EffectEvidence、Completion、Approval、Binding Revocation 不回归
- [x] 遵守就近 AGENTS.md 的格式和三 OS 交叉编译要求

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-I3 · Full Repo checks 和依赖安全检查

原文：§61。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`.github/workflows/ci.yml`、`.github/workflows/runtime-security.yml`、`apps/control-api/`、`apps/web/`、`edge/agent/`、`adapters/`、`connectors/`。

依赖：V4-I2。

验收：

- [x] Control API、Web tests/build（含 local）、Agent/Edge、Contract、Adapters、runtime smoke 通过
- [x] dependency audits、gitleaks、govulncheck 实际执行并记录结果
- [x] 使用锁定依赖和现有检查；修复引发的新变更重跑受影响回归

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-I4 · Competition 九场景 E2E

原文：§62。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`scripts/hackathon/`、`benchmarks/hackathon/`。

依赖：V4-I3。

验收：

- [x] 重跑 normal/research-only/research+report/MCP attack/same-value/fake success/conflicting effect/approval/trifecta
- [x] 使用真实工具、SIQ 回执与效果读回；标明 FixtureProvider 与实际模型
- [x] 浏览器记录真实状态、无页面错误、移动布局和凭据存储检查

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-I5 · 独立 StepFun cohort

原文：§63。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`benchmarks/hackathon/run.py`、`benchmarks/hackathon/verify.py`、`docs/hackathon/evidence/`。

依赖：V4-I4。

验收：

- [x] 重新独立运行 StepFun E2E cohort，保留所有样本
- [x] 报告 attempts/completed/timeouts/format failures、provider/config、source SHA
- [x] 不删失败、不暗中重试或以 Ornith/fixture 代替；签名回执与效果验证

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-I6 · DGX 本地敏感推理与零远程泄漏证明

原文：§64。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`benchmarks/hackathon/`、`deploy/dgx-spark/`、`docs/hackathon/evidence/`。

依赖：V4-I5。

验收：

- [x] 真实 DGX 上 public source analysis 与 confidential-local-only analysis 实际运行
- [x] 记录实际 local model 与硬件；机密 raw source 未到远程 provider 有捕获/计数证据
- [x] 新 cohort 与 V3 旧样本分开，保留失败与 unavailable，不从路由标签推断零泄漏

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-I7 · 控制基准和性能 delta

原文：§41, §78。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`benchmarks/hackathon/`、`scripts/hackathon/performance-report.py`、`docs/hackathon/benchmark-report.md`。

依赖：V4-I6。

验收：

- [x] 重跑冻结 23 control tasks 并复用签名验证器
- [x] 比较 benign completion/unsafe materialization/provenance blocks，解释任何 delta
- [x] 仅更新本轮重新测量的性能，给出 cohort/sample/分母；旧失败和原始数据保留

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-D1 · 提交并创建 V4 → V3 PR

原文：§28, §29, §77。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`.github/workflows/`、`docs/hackathon/final-hardening-report.md`。

依赖：V4-I7。

验收：

- [ ] 提交所有预期文件；PR head=codex/hackathon-final-hardening-v4，base=codex/dgx-spark-hackathon-v3
- [ ] PR 包含 Architecture changes/Security invariants/Model egress/Skill planning/Tests/Benchmark delta/Known limitations
- [ ] 使用 env -u GITHUB_TOKEN gh/git；记录 PR URL 与 head SHA；不直接 merge 或改 main

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-D2 · 真实 pull_request CI green

原文：§30。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`.github/workflows/ci.yml`、`.github/workflows/runtime-security.yml`、`docs/hackathon/final-hardening-report.md`。

依赖：V4-D1。

验收：

- [ ] PR 触发实际 GitHub Actions，ci/runtime-security/competition tests/web build/secure-agent tests 全 green
- [ ] 允许需求由 job/step 覆盖，但逐项映射，缺项补工作流
- [ ] 记录 workflow run ID、commit SHA、job count、conclusion；最后源码变更后重验同一 SHA
- [ ] 本地 CI-equivalent 不替代远端；pending/skipped/未执行不得算通过

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-D3 · 仓库治理人工操作文档

原文：§31。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`docs/hackathon/repository-governance-actions.md`。

依赖：V4-AUDIT。

验收：

- [x] 重新只读确认保护现状，不沿用旧 admin/protection 状态
- [x] 写明 Require PR、Require CI checks、Block force push、Require conversation resolution、敏感路径 CODEOWNERS review
- [x] 提供精确人工设置/复核步骤；无明确授权不修改 repository settings

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：V4 implementation in current branch; validation checkpoint docs/hackathon/final-hardening-progress-v4.md

## V4-D4 · 精确提交冻结与 clean checkout 构建

原文：§32。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`scripts/hackathon/package_rc.py`、`scripts/hackathon/test_package_rc.py`、`docs/hackathon/rc-preparation.md`。

依赖：V4-D2。

验收：

- [ ] 在远端 CI green 的精确 commit 上 freeze；无需自行 merge，保留审阅 PR
- [ ] 从独立 clean checkout 构建；git diff --quiet、git diff --cached --quiet，status clean，检查未跟踪文件
- [ ] dirty source 拒绝打包，构建后源码仍干净；不采用 dirty manifest 替代
- [ ] 构建逻辑若需修复，回到提交和远端 CI，再冻结新 SHA

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-D5 · 精确 Candidate Source Identity

原文：§33。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`scripts/hackathon/package_rc.py`、`scripts/hackathon/test_package_rc.py`。

依赖：V4-D4。

验收：

- [ ] source-info.json 至少 git_sha/git_ref/build_time/go_version/python_version/node_version/target
- [ ] 源码身份与冻结 commit、二进制、压缩包和实际 toolchain 一致
- [ ] 不再生成 dirty worktree manifest；旧候选不重新贴新 SHA

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-D6 · 准备 RC 版本与命名

原文：§34。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`scripts/hackathon/package_rc.py`、`docs/hackathon/rc-preparation.md`。

依赖：V4-D5。

验收：

- [ ] 目标 siq-agent-security-v0.3.0-rc.1；先查已有 tag convention/冲突
- [ ] 如冲突遵循既有规则并记录选择；不覆盖已有 tag
- [ ] 不发布 v0.3.0 stable；正式发布单独外部动作

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-D7 · RC 产物清单与解包启动

原文：§35, §72。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`scripts/hackathon/package_rc.py`、`scripts/hackathon/launch_rc.py`、`scripts/hackathon/package_checkpoint.py`、`docs/hackathon/evidence/`。

依赖：V4-D6。

验收：

- [ ] linux-arm64 binary 及已有其他受支持 targets
- [ ] SBOM/SHA256SUMS/Skill inventory/Source identity/Hackathon quick start/Evidence summary 齐全
- [ ] 从实际解包候选启动并跑任务，核验散列/回执/效果；不把交叉编译当原生认证
- [ ] 保存 candidate hash、source SHA、启动证据，main 未越权修改

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-D8 · 复用签名机制并准确标注发布信任

原文：§36。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`scripts/hackathon/package_rc.py`、`skills/siq-agent-security/skill-manifest.json`、`docs/hackathon/rc-preparation.md`。

依赖：V4-D7。

验收：

- [ ] 审计并复用已有 release signing/provenance；不建立第二套签名
- [ ] 缺正式签名条件标 unsigned release candidate
- [ ] 测试密钥、历史 v0.2.0 签名、checksum 不能冒充本候选 publisher identity

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-E1 · 五主题 Canonical Evidence Index

原文：§37, §38, §73。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`docs/hackathon/evidence/INDEX.md`。

依赖：V4-D8。

验收：

- [ ] 首页仅五主题：Agent Skills、NVIDIA DGX Spark、StepFun、Security、Effect & Completion
- [ ] 分别证明实际选用 Skills、实机/本地模型/runtime、真实 StepFun inference/provider、安全和效果状态
- [ ] HACKATHON → INDEX → canonical evidence 最多两次点击

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-E2 · 引用式 Evidence Manifest

原文：§39, §73。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`docs/hackathon/evidence/evidence-manifest.json`。

依赖：V4-E1。

验收：

- [ ] 包含 source_sha/dgx/stepfun/skills/security/effect/benchmark
- [ ] 只引用 canonical files，不复制原始证据数据
- [ ] 验证引用存在且 source/cohort/provider 范围一致；UNKNOWN 保留
- [ ] 最终 evidence/docs-only commit 与冻结构建 SHA 明确区分，不创建源码自引用哈希

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-E3 · 简化入口并保留原始证据

原文：§40。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`README.md`、`HACKATHON.md`、`docs/hackathon/evidence/`。

依赖：V4-E2。

验收：

- [ ] README/HACKATHON 通过 INDEX 进入证据，不直链几十个 dashboard/browser/regression 文件
- [ ] 原始证据、早期失败和旧候选数据不删除不改写
- [ ] 新证据独立命名，旧文档标历史版本避免混淆

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-E4 · 比赛摘要与准确分母

原文：§41。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`HACKATHON.md`、`docs/hackathon/benchmark-report.md`。

依赖：V4-E3, V4-I7。

验收：

- [ ] 主页面目标摘要：23 controls、benign 5/5、unsafe target materialization 0/13、provenance blocks 8/8、latest StepFun 5/5、latest Ornith 5/5
- [ ] 必须按本轮实际结果展示；若不达目标保留实际值并返回修复，不硬填
- [ ] 明确 small sample、earlier failures retained；固定提案与模型 cohort 不混算

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-G1 · 冻结唯一主故事与一键演示入口

原文：§48, §49, §74。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`docs/hackathon/demo-script.md`、`scripts/hackathon/`、`HACKATHON.md`。

依赖：V4-E4。

验收：

- [x] 分析 GitHub 项目、生成安全报告、发送 Alice
- [x] StepFun Plan → research → DGX Local Analysis → report → delivery → SIQ → EffectEvidence → Verified Completion
- [x] research-only/normal/MCP/same-value/fake-success 全部单命令或 dashboard action 可重复
- [x] 使用冻结 RC/源码与配置；不临场扩展十种功能

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-G2 · Act 1 正常动态选择与交付

原文：§50。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`scripts/hackathon/demo-normal.sh`、`docs/hackathon/demo-script.md`。

依赖：V4-G1。

验收：

- [x] 实际 Agent 选择三 Skills，全部成功，有真实选用及执行证据
- [x] 确认报告和接收端 effect verified；不以工具 success 代替

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-G3 · Act 2 MCP Injection

原文：§51。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`scripts/hackathon/demo-mcp-attack.sh`、`docs/hackathon/demo-script.md`。

依赖：V4-G2。

验收：

- [x] 恶意 MCP 将 Alice 指向 attacker@evil.example；模型可选但 SIQ DENY
- [x] 真实模型不选攻击值时如实披露；可演示明确标注的 fixture 提案，不假冒真实模型受骗
- [x] 讲清 Model can be fooled. Runtime authority cannot be self-created.

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-G4 · Act 3 同值不同来源

原文：§52。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`scripts/hackathon/demo-provenance.sh`、`docs/hackathon/demo-script.md`。

依赖：V4-G3。

验收：

- [x] 相同 alice@company.example：Trusted Directory ALLOW / MCP DENY
- [x] 实际 provenance 读回证据；解释 SIQ 同时授权值及其来源

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-G5 · Act 4 Fake Success

原文：§53。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`scripts/hackathon/demo-fake-success.sh`、`docs/hackathon/demo-script.md`。

依赖：V4-G4。

验收：

- [x] success=true、effect not observed、Completion INCOMPLETE
- [x] 画面及讲稿准确区分工具自报与真实效果证明

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-G6 · Act 5 可选 Human Approval

原文：§54。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`scripts/hackathon/demo-approval.sh`、`docs/hackathon/demo-script.md`。

依赖：V4-G5。

验收：

- [x] HOLD → Approve → Recheck → Execute 可重复
- [x] 现场时间短则作为 secondary optional demo；I4 中审批回归仍必需

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-H1 · 录制最终 2–3 分钟真实视频

原文：§55, §56, §75。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`docs/hackathon/demo-script.md`、`docs/hackathon/submission-checklist.md`。

依赖：V4-G6。

验收：

- [ ] 实际录制至少一份视频，不把脚本/截图当成已录制
- [ ] 0:00–0:15 Problem；0:15–0:40 Skills/DGX/StepFun；0:40–1:15 normal；1:15–1:45 MCP；1:45–2:10 same-value；2:10–2:30 fake-success；2:30–2:45 conclusion
- [ ] 记录文件路径/hash/source SHA/model config（脱敏）/DGX config/date

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-H2 · 视频真实性与可复核性审核

原文：§57。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`docs/hackathon/submission-checklist.md`、`docs/hackathon/final-hardening-report.md`。

依赖：V4-H1。

验收：

- [ ] 画面片头或片尾含 provider/task ID/source SHA
- [ ] 不把 ALLOW 剪成 DENY、不隐藏失败而不披露、不用 fixture/Ornith 冒充 StepFun
- [ ] 可剪等待时间并披露；核对时长、可播放性、实际录屏证据

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-J1 · 同步 README、HACKATHON 和架构叙事

原文：§65, §66, §68, §69。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`README.md`、`HACKATHON.md`、`docs/hackathon/architecture.md`。

依赖：V4-E4, V4-G6。

验收：

- [x] Secure Runtime for Agent Skills；Skills define capabilities, SIQ permissions
- [x] StepFun plans / DGX sensitive analysis local / SIQ authorizes 的目标仅在对应能力验收后表述为完成
- [x] 最终图示含 Model Router、Intent/Context/Provenance/Runtime/Approval/Receipt、Tools、Execution、EffectEvidence、Completion

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-J2 · 保留所有剩余风险并审查夸大声明

原文：§67, §79, §80。优先级：P0；状态：done；类型：engineering。

修改/交付位置：`docs/hackathon/limitations.md`、`README.md`、`HACKATHON.md`、`docs/hackathon/final-hardening-report.md`。

依赖：V4-J1。

验收：

- [x] 保留 same-UID 未 OS-isolated、Python ToolGateway 非 OS sandbox、remote StepFun external boundary、PUBLIC source 可策略允许远程
- [x] 保留 no general semantic provenance/universal SaaS effect verification/universal MCP security/full multi-agent delegation
- [x] 保留 no Windows production certification/production HA；small cohorts 非统计保证
- [x] 不称 all model traffic secure 或 all enterprise code stays local；原文最终中英文产品声明仅全部验收完成后使用

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：docs/hackathon/evidence/INDEX.md；docs/hackathon/final-hardening-progress-v4.md

## V4-J3 · 更新工程报告与提交清单

原文：§65。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`docs/hackathon/final-engineering-report.md`、`docs/hackathon/submission-checklist.md`、`docs/hackathon/acceptance-matrix.md`。

依赖：V4-H2, V4-J2。

验收：

- [ ] 明确 V3 历史结果与 V4 新验收，不覆盖旧事实
- [ ] 所有交付链接有效；未执行 CI/签名/发布/视频上传保持待办
- [ ] 最终源码、构建和证据身份准确对应

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-REPORT · Final Engineering Report V4

原文：§78。优先级：P0；状态：in_progress；类型：engineering。

修改/交付位置：`docs/hackathon/final-hardening-report.md`。

依赖：V4-J3, V4-D3。

验收：

- [ ] A starting_sha/final_sha/branch；B StepFun/Ornith/sensitivity policy；C selected Skills/dependency validation
- [ ] D Intent/Context/Provenance/Runtime/Effect/Completion；E DGX hardware/local model/actual tests
- [ ] F CI run IDs/jobs/status；G tag-candidate/hash/SBOM/source identity
- [ ] H normal/dynamic/MCP/same-value/fake-success/approval；I 仅实际重测性能；J Residual Risks
- [ ] 区分 frozen_source_sha、最终 documentation SHA、CI head SHA；不可伪造自包含 final hash

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-ACCEPT · V4 总验收与功能冻结

原文：§70, §71, §72, §73, §74, §75, §80, §81, §82, §83。优先级：P0；状态：todo；类型：engineering。

修改/交付位置：`docs/hackathon/final-hardening-report.md`、`docs/hackathon/final-hardening-tasks-v4.json`。

依赖：V4-REPORT。

验收：

- [ ] 逐项验收 Model Egress、Skills、Release、Evidence、Demo、Video DoD
- [ ] 五分钟内从实际证据回答原文七个评委问题
- [ ] inspect → implement → test → run → benchmark → verify → PR → remote CI → clean build → RC → document 均有实绩
- [ ] 全部验收后 STOP FEATURE DEVELOPMENT；稳定、清楚、真实、可重复、有证据
- [ ] 外部动作无权限逐项给操作步骤，不把未执行写成完成

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-EXT-GOV · 人工设置 main 保护

原文：§31, §81。优先级：P0；状态：todo；类型：external/manual。

修改/交付位置：`docs/hackathon/repository-governance-actions.md`。

依赖：V4-D3。

验收：

- [ ] 仅取得明确 settings 授权后由 maintainer 设置并只读复核保护
- [ ] 遵循 D3 列出的 PR/check/force-push/conversation/CODEOWNERS 要求
- [ ] 当前存在 admin 能力也不等于授权；不阻塞本地工程

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-EXT-SIGN · 正式签名材料与签名执行（条件项）

原文：§36, §81。优先级：P0；状态：todo；类型：external/manual。

修改/交付位置：`docs/hackathon/repository-governance-actions.md`、`docs/hackathon/rc-preparation.md`。

依赖：V4-D8。

验收：

- [ ] 具备正式 publisher 授权和密钥时复用现有流程
- [ ] 无正式条件保留 unsigned RC 并给签名/验证步骤；不接触或公开私钥
- [ ] 此项不是创建第二套 signing 系统的许可

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-EXT-RELEASE · 官方 RC 发布（条件项）

原文：§34, §81。优先级：P0；状态：todo；类型：external/manual。

修改/交付位置：`docs/hackathon/rc-preparation.md`、`docs/hackathon/submission-checklist.md`。

依赖：V4-D8。

验收：

- [ ] 具备明确发布授权后核对 exact source/tag/hash/CI 并上传 RC artifacts
- [ ] 不发布 stable、不覆盖已有 tag；发布前保留可审阅产物和步骤
- [ ] 准备本地 RC 不等于已公开发布

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## V4-EXT-VIDEO · 比赛视频上传（外部提交）

原文：§75, §81。优先级：P0；状态：todo；类型：external/manual。

修改/交付位置：`docs/hackathon/submission-checklist.md`。

依赖：V4-H2。

验收：

- [ ] 确认赛事大小/格式/目标平台要求与上传权限后提交真实成片
- [ ] 记录提交链接、视频 hash、时间及源码/模型/DGX 配置
- [ ] 大型视频不强塞 Git；未上传不标 submitted

证据要求：记录实际执行命令、时间、source SHA、结果及证据路径；未运行保持 unverified。

实际证据：待执行，无 V4 完成声明。

## 原文全章节追踪

下表覆盖原文 §0–§83；章节背景、约束、测试编号、DoD 和最终评委标准均有承接任务。

| 章节 | 要求 | 任务 |
| --- | --- | --- |
| §0 | 本轮任务性质 | V4-SCOPE |
| §1 | Repository Baseline | V4-BASE |
| §2 | 开发前必须完成 Current-State Audit | V4-AUDIT |
| §3 | 本轮最高安全原则 | V4-SCOPE |
| §4 | WORKSTREAM A — Model Egress & DGX Locality | V4-A1 |
| §5 | 当前需要解决的问题 | V4-A1 |
| §6 | A1 — 数据分级 | V4-A1 |
| §7 | A2 — Model Capability Policy | V4-A2 |
| §8 | A3 — 推荐比赛架构 | V4-A3 |
| §9 | A4 — 不允许隐式 fallback | V4-A4 |
| §10 | A5 — Research Routing | V4-A5 |
| §11 | A6 — StepFun Planning Payload | V4-A6 |
| §12 | A7 — Model Egress Evidence | V4-A7 |
| §13 | A8 — Model Egress Tests | V4-A8 |
| §14 | WORKSTREAM B — Dynamic Agent Skills Orchestration | V4-B1 |
| §15 | 当前问题 | V4-B1 |
| §16 | B1 — TaskPlan V2 | V4-B1, V4-B5 |
| §17 | B2 — Dependency Graph | V4-B2, V4-B5 |
| §18 | B3 — Skill Registry Schema | V4-B2 |
| §19 | B4 — Model Cannot Invent Skills | V4-B3 |
| §20 | B5 — Model Cannot Skip Dependencies | V4-B4 |
| §21 | B6 — Dynamic Skill Demo | V4-B6 |
| §22 | B7 — Skill Planning Tests | V4-B7 |
| §23 | WORKSTREAM C — DGX Spark Competition Visibility | V4-C1 |
| §24 | C1 — Dashboard Hardware Card | V4-C1 |
| §25 | C2 — Model Locality Indicator | V4-C2 |
| §26 | C3 — DGX Runtime Metrics | V4-C3 |
| §27 | C4 — DGX Fail-State | V4-C4 |
| §28 | WORKSTREAM D — Release Hardening | V4-D1 |
| §29 | D1 — 当前分支 PR | V4-D1 |
| §30 | D2 — Remote CI | V4-D2 |
| §31 | D3 — Main Protection | V4-D3, V4-EXT-GOV |
| §32 | D4 — Clean Source Build | V4-D4 |
| §33 | D5 — Candidate Identity | V4-D5 |
| §34 | D6 — Release Candidate | V4-D6, V4-EXT-RELEASE |
| §35 | D7 — RC Artifacts | V4-D7 |
| §36 | D8 — Signing | V4-D8, V4-EXT-SIGN |
| §37 | WORKSTREAM E — Evidence Consolidation | V4-E1 |
| §38 | E1 — Evidence Index | V4-E1 |
| §39 | E2 — Evidence Manifest | V4-E2 |
| §40 | E3 — Raw Evidence | V4-E3 |
| §41 | E4 — Benchmark Summary | V4-I7, V4-E4 |
| §42 | WORKSTREAM F — Competition UI Freeze | V4-F1 |
| §43 | F1 — UI 四块保持不变 | V4-F1 |
| §44 | F2 — Agent Skills 必须视觉突出 | V4-F2 |
| §45 | F3 — Security Decision | V4-F3 |
| §46 | F4 — Provenance Visualization | V4-F4 |
| §47 | F5 — Effect Visualization | V4-F5 |
| §48 | WORKSTREAM G — Demo Freeze | V4-G1 |
| §49 | 主 Demo | V4-G1 |
| §50 | Demo Act 1 — 正常任务 | V4-G2 |
| §51 | Demo Act 2 — MCP Injection | V4-G3 |
| §52 | Demo Act 3 — Same Value / Different Provenance | V4-G4 |
| §53 | Demo Act 4 — Fake Success | V4-G5 |
| §54 | Demo Act 5 — Human Approval | V4-G6 |
| §55 | WORKSTREAM H — Demo Video | V4-H1 |
| §56 | H1 — 录制 2–3 分钟 Demo | V4-H1 |
| §57 | H2 — 视频必须真实 | V4-H2 |
| §58 | WORKSTREAM I — Regression | V4-I1 |
| §59 | Secure Agent Tests | V4-I1 |
| §60 | AgentShield Tests | V4-I2 |
| §61 | Full Repo Checks | V4-I3 |
| §62 | Competition E2E | V4-I4 |
| §63 | StepFun E2E | V4-I5 |
| §64 | DGX Local Model E2E | V4-I6 |
| §65 | WORKSTREAM J — Documentation Claims | V4-J1, V4-J3 |
| §66 | README 关键叙事 | V4-J1 |
| §67 | 禁止新的夸大声明 | V4-J2 |
| §68 | 最终比赛安全架构 | V4-A3, V4-J1 |
| §69 | 最终比赛公式 | V4-A3, V4-J1 |
| §70 | DoD — Model Egress | V4-A8, V4-ACCEPT |
| §71 | DoD — Skills | V4-B5, V4-B7, V4-ACCEPT |
| §72 | DoD — Release | V4-D7, V4-ACCEPT |
| §73 | DoD — Evidence | V4-E1, V4-E2, V4-ACCEPT |
| §74 | DoD — Demo | V4-G1, V4-ACCEPT |
| §75 | DoD — Video | V4-H1, V4-ACCEPT, V4-EXT-VIDEO |
| §76 | 本轮禁止重构 | V4-SCOPE |
| §77 | Suggested Commit Sequence | V4-SCOPE, V4-D1 |
| §78 | Final Engineering Report V4 | V4-I7, V4-REPORT |
| §79 | Residual Risks 必须保留 | V4-J2 |
| §80 | 最终比赛产品声明 | V4-J2, V4-ACCEPT |
| §81 | Codex 最终执行要求 | V4-SCOPE, V4-ACCEPT, V4-EXT-GOV, V4-EXT-SIGN, V4-EXT-RELEASE, V4-EXT-VIDEO |
| §82 | 最终优先顺序 | V4-SCOPE, V4-ACCEPT |
| §83 | 最终判断标准 | V4-ACCEPT |

## 执行验证命令基线

执行者先核对现有工作流和就近 AGENTS.md，以下命令作为入口；本次任务落盘未运行这些工程回归。

```bash
PYTHONPATH=apps/secure-agent apps/control-api/.venv/bin/python -m unittest discover -s apps/secure-agent/tests -v
GOTOOLCHAIN=go1.26.6 go -C apps/agentshield test ./...
GOTOOLCHAIN=go1.26.6 go -C apps/agentshield test -race ./...
GOTOOLCHAIN=go1.26.6 go -C apps/agentshield vet ./...
apps/control-api/.venv/bin/python -m unittest discover -s scripts/hackathon -p "test_*.py" -v
npm --prefix apps/web run test
npm --prefix apps/web run build
npm --prefix apps/web run build:local
git diff --check
```

完整 Control API/迁移、Edge/Connector、Schema、Adapters、gitleaks、govulncheck 与 dependency audits 以 `.github/workflows/ci.yml`、`.github/workflows/runtime-security.yml` 和仓库约定为准。真实模型 cohort、DGX、浏览器、签名证据验证按现有 `benchmarks/hackathon/README.md`、`deploy/dgx-spark/README.md` 和 `scripts/hackathon/` 执行，新证据独立存放。
