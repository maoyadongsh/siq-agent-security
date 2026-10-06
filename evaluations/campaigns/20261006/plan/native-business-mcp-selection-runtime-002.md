# 原生来源字段选择：修正接口凭据后的批次

初批 native-business-mcp-selection-001 已终态，锚 `8d5f5957b381e4a4d5e11afdc0ac1a9afb29ee4e8c418704aa761bff4f20a083`。业务读回和摘要成功，五项诊断完整；解析父来源为200，但四项选择使用管理凭据均401，未进入内容选择。这是测评请求凭据选择错误，不将401误记为provenance_missing或内容摘要拒绝，初批失败保留。

本批保留[原协议](native-business-mcp-selection-001.md)的一项真实业务、五项请求、效果／效用判据及预算，仅修正凭据分配：`/v1/provenance-resolve`使用本批管理会话；`/v1/provenance-select`读取本批真实已安装适配器config.json所引用的runtime identity凭据，和原post来源上报使用同一身份。凭据文件必须位于该单元专属状态根，不使用全局decision token替代实例身份；正文／日志／导出不保存凭据。记录凭据角色及安全文件引用，不复制秘密内容。

固定来源api/authz/runtime_identity_auth合同与实现摘要。四项选择预期依次为400 provenance_missing、400 provenance_content_mismatch、400 provenance_content_mismatch、400 provenance_missing；实际HTTP与返回体保留。父来源正常解析200；原报告读回成功和默认pre hook无参数来源继续独立评分。即使全部诊断符合预期，选定参数能力仍为不可用，原生下游约束未到达。

本轮无SIQ或Hermes产品修复、无额外来源签发、无真实模型调用。原宿主与原数据不改，继续精确进程／容器回收。该重跑不增加独立业务任务数。
