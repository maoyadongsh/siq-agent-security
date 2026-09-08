> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# Final Hardening V4 · Current-State Audit

检查日期：2026-09-08。源码基线：`9b4aaeae1a089b54fbbc50c33cdb72616be2b1b1`。目标：[V4 原文](final-hardening-requirements-v4.md)；实施：[完整任务台账](final-hardening-tasks-v4.md)。本次检查当前源码、工作流、文档和历史证据文件，未启动服务、模型推理、DGX preflight、回归或新基准；不把读取旧报告计作本轮实测通过。

## 分类口径

| 分类 | 意义 |
| --- | --- |
| implemented | 当前源码可定位到实现；不代表已在本轮执行通过。 |
| evidenced | 存在可定位的历史原始证据；保留其 provider、source SHA、dirty 状态和样本边界。本轮未重新验签/复跑。 |
| needs-hardening | 已有实现不满足 V4 明确要求，须修改并验证。 |
| unverified | 本轮尚无可用的实际执行/外部状态证据，不能标通过。 |
| future | 原文排除的扩展能力，不进入本轮功能开发。 |

## 目录审计

| 范围 | 当前代码/文件事实 | 分类与差距 | 承接任务 |
| --- | --- | --- | --- |
| `apps/secure-agent/` 数据合同 | `contracts.py` 的 `UserTask` 和 `Source` 无敏感度字段；`TaskPlan.parse` 要求恰好三项且顺序等于 `SKILL_INPUTS` | needs-hardening：可信分级与内部 TaskPlan V2 缺失 | A1、B1–B4 |
| `apps/secure-agent/` 模型传输 | `models.py` 的 `_json` 用 HTTP transport 发请求；`research` 序列化 source content；`plan` 发送 `asdict(task)` 并要求 use each skill exactly once | needs-hardening：模型独立出网路径缺少明确能力策略、locality、敏感度路由和规划白名单 | A2–A6 |
| `apps/secure-agent/` 调用审计 | `_json` 已记录 provider/model/operation、usage、finish_reason、generation、status/error_code、elapsed_ms，HTTP error body 不进入诊断 | implemented + needs-hardening：尚需 task_id/payload digest/classification 和 provider_transition；全路径 secret/config 负向仍需重验 | A4、A7、A8 |
| `apps/secure-agent/` 两阶段执行 | `application.py` preparation 调用 `self.model.plan`，无条件跑 `plan.skills[0]`、渲染报告、提交 report/delivery effects，再用 `CommittedProvider` 重读源码执行 | needs-hardening：仅改 parser 不足，必须同步子集对应的预承诺、effects、完成语义；保留源摘要及绑定校验 | B5、I1 |
| `skills/` | 三个 `secure-*` SKILL.md 已存在并声明 allowed-tools；`SkillRunner.run` 有 report/research 和 delivery/report 前置检查，工具访问经 ToolGateway | implemented：复用真实 Skills；needs-hardening：`SkillRegistry.catalog` 未显式定义完整 requires/allowed_tools/security_requirements，不能代表动态选择 | B2–B7 |
| `apps/agentshield/` | 独立本地内核及既有 Intent/Provenance/Effect/Completion/Approval 接入；ADR-018 明确 same-UID 和未来 Managed Linux 边界 | implemented + 历史 evidenced：本轮不重构签名/回执/内核；完整安全回归 unverified | I2、J2 |
| `apps/web/src/local/` | `pages/DemoPage.tsx` 已展示任务、模型诊断、SIQ 动作、来源读回、同值解释、审批和效果；任务 Skills 来自 snapshot 的 skills 字段 | implemented + needs-hardening：明确每个 task 的已选计划、逐动作 remote/local、实时 DGX 卡与 unavailable/fail-closed，不用静态 catalog 冒充选择 | B6、C1–C4、F1–F5 |
| `deploy/dgx-spark/` | preflight/start/healthcheck/env 示例存在；`preflight.py` 从 DMI/GPU/模型列表和服务探测取事实，inference_verification 默认 unverified | implemented + 历史 evidenced：真实硬件证据可复用索引；本轮当前本地推理和 confidential-local-only 路径 unverified | C1–C4、I6 |
| `benchmarks/hackathon/` | `cases.json`、runner、verifier、corpus schema 与测试存在；README 明确 fixed control corpus 与真实 model-utility cohort 区分 | implemented + 历史 evidenced：V4 新 cohort/路由/动态子集回归未执行；不能直接继承 V3 统计 | I4–I7、E4 |
| `scripts/hackathon/` 演示 | start/stop/reset/pair、正常/MCP/provenance/fake-success/approval/trifecta、浏览器和 model checkpoints 已有 | implemented：复用入口；research-only/report 子集及新 provider/locality 故障状态待开发验证 | B6、I4、G1–G6 |
| `scripts/hackathon/` 候选包 | `package_rc.py` source-info 记录 source_sha、dirty、source_files、final_commit=None，文案为 unsigned dirty-source candidate | needs-hardening：尚未要求 clean source；须精确提交、工具链身份、拒绝 dirty 和解包实启 | D4–D8 |
| `docs/hackathon/` | V3 计划、进度、架构、证据、报告、演示讲稿和候选说明均已有 | needs-hardening：V4 五主题 INDEX、canonical manifest、最终报告与新视频证据缺失 | E、G、H、J、REPORT |
| `.github/workflows/` | `ci.yml` 与 `runtime-security.yml` 有 pull_request 入口；后者含 Secure Agent、打包/合同测试、23 项控制执行与证据校验步骤 | implemented：工作流文件存在；unverified：未查询/执行 V4 PR 远端 CI，不能据文件存在报 green | D1、D2 |

## 指定文档复核

| 文档 | 当前状态与 V4 差异 |
| --- | --- |
| [README](../../README.md) | 仍包含 V3 比赛分支、早期 ornith/测试数字；当前目标入口需切换，最终能力叙事必须等 V4 验收再改成完成声明。 |
| [HACKATHON](../../HACKATHON.md) | StepFun primary / Ornith explicit backup，固定完整交付流程；证据直链较多。需要规划/研究分离、动态子集、INDEX 和冻结演示入口。 |
| [final-engineering-report](final-engineering-report.md) | V3 baseline、implementation commit、本地候选 dirty-source、unsigned/unpublished、local CI-equivalent 均有披露。保留历史身份，V4 新建 final-hardening-report。 |
| [acceptance-matrix](acceptance-matrix.md) | 标题为 V3 requirement audit；旧版视频非必需、dirty-source 候选接受口径不能作为 V4 DoD。 |
| [limitations](limitations.md) | same-UID、工具网关、效果和小样本边界已披露；V4 需显式补充 remote StepFun 外部边界、PUBLIC 可远程、敏感工作负载政策路由范围。 |
| [submission-checklist](submission-checklist.md) | 明确 no recorded video yet，候选 2 未签名未发布，远端 CI 与正式治理不以本地测试替代。V4 录制是必需交付。 |

## 已有证据入口与可信范围

- [最新 StepFun 历史 cohort](evidence/benchmark-20260908/step-plan-low.json) 和 [Ornith 历史 cohort](evidence/benchmark-20260908/ornith-direct.json) 均为已有 JSON；结构包含 source_sha、working_tree_dirty、files_sha256、cases、summary。本次读取结构，不进行新的模型调用，不重新赋予 V4 源码身份。
- [历史 DGX preflight](evidence/dgx-spark/step-plan-environment-20260908.json) 包含 hardware/model/services、source SHA 与 dirty 标记；模型 listing、实机身份和实际推理证据必须分别判断。
- [历史回归索引](evidence/final-regression-20260908/checks.json) 存在；它证明先前记录了哪些检查，不证明 V4 新代码或当前环境通过。
- [历史浏览器结果](evidence/browser-trifecta-final-20260908/result.json)、[基准报告](benchmark-report.md)、[V3 最终报告](final-engineering-report.md) 继续保留。证据汇总需引用 canonical files，不能复制数据或删除失败样本。
- main 保护状态、账号权限、V4 PR、CI run、正式签名、官方发布和视频上传均 **unverified**；本次未更改 settings、未创建 PR、未发布产物。旧治理 readback 不是当前权限/授权的证据。

## 当前结论与下一步

最高优先级是将 `Source.content → ModelProvider.research → HTTPS` 的独立模型出网边界显式治理；现有证据不能证明所有私有源码已泄漏，也不能证明所有模型流量已受 SIQ 治理。先完成 A1–A8，再改 B1–B7；必须连同 preparation、recipient 和 cached/committed provider 路径审视，避免只补 UI 标签或 parser。

本轮 future：Managed Linux full implementation、Multi-Agent Delegation DAG、通用沙箱、通用 SaaS Effect Verification、Neural Taint、General Memory IFC、新企业授权平面、新微服务或 Agent 框架。维持 INV-1–INV-8 和既有签名边界，按任务台账逐项收敛，不扩张模块。
