# Skill SEC 撤销确认 003：中性载荷仍触发财务分类，整批失败

五条签名记录与 16 项独立局部核验再次证明同任务撤销 SEC 后实际覆盖写被拒绝、首次文件字节保持。但最终回答为 financial_evidence_missing，原协议要求的正常业务回答没有满足，因此整批仍失败。

本批把财务文件改为中性权限文本，结果证明仅改载荷还不够。当前代码诊断表明请求进入通用 Wiki 全文 fallback，进而启用财务证据合同；同产品既有的 OpenShell/Hermes 运行时请求分类能区分不含财务要求的权限任务。下一批明确指定真实运行时并保持原工具操作；7 项离线测试通过，包含带公司上下文的权限请求和“附加营收同比要求仍启用财务保护”的负向检查。未修改产品分类/财务保护函数。此项是任务适配限制，不能声称泛化自然语言分类已修复。

[原始执行](research-permissions-skill-revoke-003.json)、[局部核验](research-permissions-skill-revoke-003-verification.json)、[回执](../data/research-permissions-skill-revoke-003-verified-receipts.json)、[原文件](../data/research-permissions-skill-revoke-003-before.md)、[最终文件](../data/research-permissions-skill-revoke-003-after.md)、[源码冻结检查](research-permissions-skill-revoke-003-source-check.json)。原结果不改写；后续另建 004。
