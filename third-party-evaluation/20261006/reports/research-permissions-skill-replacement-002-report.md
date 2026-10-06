# Skill 实际替换：002 应答分类失败记录

本批未通过预冻结条件，未调用业务模型。

Skill 替换已提交，旧 Grant 已撤销，旧凭据决定请求与登记请求均被 401 拒绝。新身份尝试登记旧 session 实际收到 `503/runtime_identity_unavailable`，不符合预设 `409/runtime_identity_authority_conflict`。这不是已证实的越权：没有恢复旧会话或产生工具效果；但也不把一般性 503 当成冲突验收通过。

已用 `TestRuntimeSessionReplacementWithRevokedGrantReportsConflict` 在真实 HTTP 处理器复现同样 503。根因是 EnrollContext 在 ResolveBinding 返回旧 Grant 无效错误后先归为不可用，未识别已验签历史绑定属于其他身份。修复仅在已验证历史 tuple 与新身份派生 Intent/task 不同的情况下返回既有冲突；无法验证历史元数据仍拒绝为不可用。

专属安装/profile/身份与服务均已清理。后续使用新编译候选、新协议及新批次，原失败与原二进制保留。
