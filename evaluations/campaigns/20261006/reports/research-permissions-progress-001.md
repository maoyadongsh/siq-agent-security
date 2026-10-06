# DGX 真实分析助手权限测评：交付状态

用户指定的 DGX Spark + Hermes + OpenShell + 智能分析助手 Agent/已安装 Skill 权限测评已完成。当前无测评批次运行。结论及限制见[最终报告](research-permissions-final-report.md)，详细需求和证据见 [RG01–09 台账](../plan/dgx-research-permission-closeout-001.json)，复现见[操作说明](../README-PERMISSIONS.md)。

- 日常入口 Agent 只读拒写、批准窄写后成功，使用原前端和默认 API。
- 已安装 Reader/Writer 的真实内容、Grant/SEC 和读写效果分别对应；skill-business-003 专项复核通过。
- skill-revoke-004 同任务同文件先写成功、撤销 SEC 后实际第二次写被拒绝，22 项独立核验通过。
- 安装漂移收容、候选更新/正式替换、公司边界、业务撤权、14 个工具入口及 relay 恢复均有所选合同变体证据。
- 最终 10 个主证据批次 67 条签名记录重新核验、20 项当前文件检查和环境检查通过。

[37 个业务 HTTP 批次](../inventory/research-permissions-business-batches-008.json)包含失败/诊断，不是模型调用数或通过率。全部历史失败保留；revoke-002/003 证明门禁有效但最终回答被财务合同拦截，004 在明确运行时的中性权限任务下通过，没有修改财务保护。

任意 Skill 自动归属、解释器细粒度隔离、任意撤权时点审计完整性、生产 IAM 和完整金融分析质量不在已证明范围；replacement-003 历史收尾原因仍未唯一证实。所选案例通过不表示这些限制消失。Windows/WorkBuddy 历史结果单列，未做新跨 OS 测评，也未获得独立第三方机构认证。

主方案其他轨道按用户最新范围延期；没有把它们标为完成。修改前进度保存在 `plan/revision-history/research-permissions-final-delivery-001/`。
