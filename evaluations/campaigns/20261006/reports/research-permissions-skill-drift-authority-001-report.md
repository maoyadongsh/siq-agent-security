# Skill 漂移授权因果对照 001

**公共 API 对照通过，未调用模型、未创建业务任务。** 同一 Runtime Identity、同一凭据、同一 Grant，原安装时 `/v1/runtime-identity/self` 返回 200；仅替换自有已安装 `SKILL.md` 后返回 401 / `runtime_identity_required`；恢复原文件 inode 后返回 200，返回身份和响应摘要与变更前完全一致。随后撤销自有身份和 Grants、卸载自有 Skills。

6 项执行检查及 [10 项独立核验](research-permissions-skill-drift-authority-001-verification.json)通过，SEC 签名有效，2,907 项冻结源码未变化。前后安装内容及 HTTP 响应摘要保存在 [原始结果](research-permissions-skill-drift-authority-001.json)。本批证明安装完整性是运行认证门槛；401 是公共认证响应，不是签名工具决定，不能替代真实模型效用或文件效果测评。

代码合同要求实例、会话和 SEC 引用安装 Skill 的同一 Grant。因而失去安装完整性时可能终止整个运行，而不是让运行继续到模型发出下一工具后才拒绝。新的真实任务用例将据此预先冻结“完整合法前缀 → 同一执行子身份认证失效 → 有界任务收容 → 原字节保持”的验收，原漂移批次失败保持不变。
