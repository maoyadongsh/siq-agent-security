# N09 验收证据 v2：逐行覆盖与提交门槛

本规格取代未合入主线的 N09-A/B v1 矩阵推导规则，保留原始报告与摘要；不修改 v3 任务书的 J1–J11 历史记录。原三系统三平台九格结构保留，但 2026-09-17 产品决策使 Linux/WorkBuddy 不再属于适用验收分母。合同为 `packages/contracts/personal-acceptance-baseline.v2.schema.json`。

## 语义

- `native` / `controlled_start` 描述已观察到的接入方式，独立于证据层级；允许搭配 `native_machine`，绝不强制或隐式升级为 `complete_acceptance`。
- 9 个系统/平台格各保留 11 行。2026-09-17 的[产品范围决策](personal-platform-scope-decision-20260917.md)将 Linux 限定为 Hermes/OpenClaw；Linux/WorkBuddy 格仍留作历史可比占位，新矩阵可以将该格全部 11 行标为 `out_of_scope` / `product_scope_excluded`。这不是通过，不要求 Linux/WorkBuddy 实机验收；其他八格的分母不变。安装 J1 是产品安装，不能用适配器安装替代；J6 包括 Skill 安装、确认更新与移除；J7 包括本次调用的可信 Skill 归属与追溯。
- 每行以 `coverage[{leg_id, checks}]` 指向实际通过的具名断言，且与 evidence_refs 一致。leg 必须声明平台/OS、二进制摘要、时间、报告摘要和实际检查数。
- 未覆盖项用 unverified 并写 required_evidence；缺环境/宿主能力用 blocked 或 unavailable。保留部分原生观察不等于完成该行，更不等于通过 N09。
- `out_of_scope` 只允许整个 Linux/WorkBuddy 格统一标记，必须写产品范围原因，不得附虚构 leg、覆盖或 `complete_acceptance`；历史 blocked 材料原样保留。
- `complete_acceptance` 只能引用报告明确给出的 `acceptance_scope`（platform、os、completed_items），禁止把没有逐项验收范围的任意 passed 报告作为完整验收。该声明仍需要人工代码与场景复核，不能由记录条数或哈希生成。

## 严格校验

输入版本只接受 v2，旧 v1 必须经过覆盖审查后显式转换。JSON 拒绝重复键、非有限值、超大文件、未知字段、错误类型；SHA 为 64 位小写十六进制，时间须有时区且顺序合法。路径必须是 docs/evidence/ 内的真实文件，拒绝相似目录前缀、路径穿越、绝对路径、Windows 路径及符号链接。

所有引用必须登记摘要，报告内容与摘要、二进制、检查数对应。passed=true 不覆盖 checks 中的 false；不接受空/重复检查、journey_checks 缺失/失败断言、重复 leg、跨 OS/平台证据。校验通过仅表示完整性及声明的引用关系有效，不证明代码安全性或测试设计充分。

OpenClaw leg 的成功定义必须同时满足：run 正常完成、精确 C1/C2/C3/C4/C5/C6a/C6b/C7/C8/C9/C10 检查集全部真。异常中断或空/部分检查不能生成 passed=true。C6b 仅是直接 API 批准消费，不能写成原生批准后执行；没有观测副作用次数，不能声称 exactly-once。

## 本批审查结论与边界

修订矩阵见 `docs/evidence/personal-experience/n09-independent-review-20260914/matrix.json`。N09-A/B 原始证据基于 GLM 未提交二进制 fe03e7e0，原样保留，未冒充最新 main 的独立实测。L3 的 11 项中有重复检查名，且 API 元数据不能证明真实调用来源，故排除其通过声明。OpenClaw J2/J6 无对应场景；J5 缺原生批准后执行；J7 缺可信 Skill 来源；J11 日志卫生不等于隐私全流程。两平台都没有整个产品 J1–J11 完整验收结论。

本批是离线复核和工具修复，不调用 GLM 脚本默认的本机模型转发服务，不触发收费模型或用户现有 daemon/gateway。后续原生测试必须另建隔离环境并固定候选二进制。
