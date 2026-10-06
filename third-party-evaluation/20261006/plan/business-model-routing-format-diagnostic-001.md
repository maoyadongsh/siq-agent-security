# Step规划输出格式兼容性诊断预注册

原`business-model-routing-live-001`五任务已完成并冻结：HTTP200/finish_reason=stop，但均为contract_fields_invalid，未执行研究/投递。原封套`0859ee1b7a49e59986f99978bfd3b1029ce1f0061d65d010b15e32c7a1f95f8f`保持不变。

本诊断只取其中PUBLIC默认和CONFIDENTIAL默认的两个已保存、纯合成规划请求，各测试`response_format=json_schema`和`response_format=text`，共4次，无自动重试。JSON Schema取候选原model-task-plan-v2；其他字段、提示、模型和max_tokens4096完全不变。用原TaskPlan.parse验证最终content，不提取reasoning、不补goal、不删除多余字段来制造通过。

每请求45秒并有转发进程2秒终止宽限，全批240秒、最多4次，预算与helper沿用已测控制。保存原始请求/响应、HTTP状态、finish_reason、真实usage、原验证错误与外部摘要锚。诊断没有业务工具执行，不是SIQ防护实验，不能把成功JSON当业务完成。

若某配置通过，只支持在该配置下另冻完整业务批；原json_object失败继续报告。若均失败，保留当前接入限制，继续其他可执行测评，不能把无效输出作为安全收益。

[官方JSON Mode说明](https://platform.stepfun.com/docs/guide/json_mode)说明JSON结果仍需应用验证；该旧资料不足以确定Step Plan step-5-preview的严格schema支持。新格式支持与效果以本诊断实际响应为准，不采用第三方转售端点的能力宣传推定官方端点支持。
