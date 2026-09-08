# ADR-0017：独立效果证据与最小完成状态

- 日期：2026-09-08
- 状态：设计接受，合同已定义；运行时、observer 与 Completion 待实现
- 依据：用户 Provenance-Bound Effect Security V1 模板 §45–63、INV-4/6

## 问题

现有工具 Observe 回执证明收到上报，不能证明文件已写入或请求到达目标服务器。将工具成功响应直接解释为任务完成，会遗漏虚假成功、目标替换与被拒绝动作仍产生效果的情况。

## 决策

新增独立 `effect-evidence/v1` 合同，分别表达执行状态、来源类型、独立性、覆盖范围和结果。沿用 canonical JSON 与本地 Ed25519 签名；只记录资源引用及证据摘要，不保存原始文件或响应内容。签名证明记录完整性，不证明上报内容客观真实。

每条记录必须关联实际 action_id 和 decision_receipt_id。运行时须验证两者对应关系、资源和 effect_type，再接受证据；schema 合法不能替代这些检查。被拒绝动作若产生独立可见效果，归为 `unauthorized_effect_observed`，不能计为预期成功。

`tool_report` 只能是 self_reported，coverage/result 保持 unknown；unknown 来源三个维度均保持 unknown。现有 `/v1/observe` 不获得提升来源等级的能力。可信 observer 使用独立 `capEffectObserve`，由 admin 管理配置；decision token 不能充当独立证明权威。具体 observer 身份及允许来源须由受信注册信息决定，不由提交正文决定。

第一阶段实现文件前后状态与受控网络服务端记录。文件 observer 的 host_independent 只表示独立于工具自报；同 UID、同宿主环境不构成 OS 隔离。测试 oracle 的 external_independent 只针对所观测的本地测试服务，不扩展为真实公网或平台支持声明。

证据以不可变记录持久化：相同 ID 相同内容幂等，不同内容冲突；重启后重新验签、关联校验。矛盾证据保留且不得通过选择性取样变成 verified。

最小 CompletionStatus 为 verified/incomplete/conflicting/unknown，由已验证 Intent 的效果要求、Actions、Observations 和有效 EffectEvidence 计算。没有效果要求返回 unknown/not_required；模型不能写 completed=true。本轮不实现通用业务工作流。

## 验收与限制

后续运行时必须验证普通 token 伪造独立来源、未知 action、回执错配、假成功、拒绝后实际效果、证据冲突、重复提交和重启恢复。合同测试只证明结构及自报上限，不作为这些运行时门禁已完成的证据。
