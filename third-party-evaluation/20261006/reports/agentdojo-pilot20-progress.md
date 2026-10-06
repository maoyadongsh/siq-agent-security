# AgentDojo 20 任务试点实施记录

状态：两个模型各 120 单元已完成并通过修正后的离线复核，最终结果见 [试点结果报告](agentdojo-pilot20-report.md)。执行方为作者侧 Codex；不是独立第三方认证。

## 冻结设计

每个模型 20 个官方任务 ID × 正常/注入两条件 × B0/B1/B2 三组，共 120 单元；本地 Qwen3.8-27B-NVFP4 和 Step Plan step-5-preview 合计 240 单元。按冻结随机序执行，每个单元最多 8 次模型请求，无重试、无降级替代。调用时间、预算、输出 token、准确模型名和端点记录在 v2 协议。订阅使用已获用户授权；套餐 Credit 实际计费金额不可由返回 token 推断。

- B0：上游系统提示与工具，不启用 SIQ。
- B1：相同工具，增加冻结的反注入系统提示，不启用 SIQ。
- B2：相同原始提示和工具，仅模型直接 `send_email` 调用经过真实 SIQ 决策。

20 个官方任务 ID 包括查询及文件、日历修改；排除邮件投递正常任务、近重复时间查询和组合重复题。24 个 workspace 工具在三组全部暴露；每组/每条件采用独立初始环境。任务共享工作区实体和主题，不能称为 20 个独立攻击家族。配对统计以官方 task ID 为块，仅提供描述性转移计数，不做独立同分布显著性推断。

上游版本为 v1.2.2/workspace，源码提交 `089ed468cf3ed0322acc66b0211f26d9d90dbf60`。攻击采用官方 FixedJailbreakAttack 与 ImportantInstructionsAttackNoNames 模板，目标为 `injection_task_0`。注入位置由上游参考流程生成；这是公开开发集协议，不是隐藏题。参考答案和攻击目标不传给 SIQ 授权器，任务 oracle 仅在运行后计分。

## 重要解释更正（不改写冻结协议）

v1/v2 协议 `applicability.claim_limit` 中的英文 `mail-exfiltration` 表述过宽：此目标只是让模型向固定收件人发送固定问候文本，并不读取或外传机密。正确结论范围是“非用户授权的固定文本邮件发送”。后续协议生成器已更正该标签，正在执行的 v2 原始文件及哈希保持不变。不得将本批解释成数据外泄保护率。

B2 只覆盖顶层 `send_email` 分派；其他工具及其内部副作用不受本映射保护。上游日历工具可在内部调用 `inbox.send_email` 发送通知，绕过顶层 gate。这是当前适配范围的明确缺口，不能据此宣称全通道防泄露。附件映射仍不支持；如触发 UnsupportedMapping，应标注实验边界干预而非 SIQ 防护成功。所有邮箱效果均发生于上游内存模拟环境，不向真实邮箱发送邮件。

## 校准及修复记录

首次校准保留在 `reports/agentdojo-pilot20-reference-calibration.json`，严格对象比较 17/20 通过。任务 6、7、9 的日历操作自动生成邮件，其 `datetime.now()` 时间戳因两次顺序执行不同，造成环境对象不相等；原始工具记录与参考效用均一致。这不是模型失败，也不是产品缺陷。

新增可复跑校准脚本，对全部 20 个任务保存包装/原始完整环境和工具记录。仅允许 inbox 邮件 timestamp 路径的墙钟差异，其他字段及完整工具记录必须一致。第二批 `reports/agentdojo-pilot20-reference-calibration-002.json` 为 20/20，模型调用数 0。原始快照位于 `private/calibration/agentdojo-pilot20-002`。v1 冻结协议保留但未调用模型；v2 在模型调用前补充内部通知边界并将摘要字段从 independent_task_blocks 改为 task_blocks。

复核器新增初始用户/系统提示、B1 固定提示、120 单元完整笛卡尔分配、上游工具集合和非 SIQ 组无产品裁决检查。首次旧 smoke 兼容回归因按 applicability 字段误识别旧协议而失败；已改为新增 exposed_tools 协议字段识别，并添加兼容测试。旧模型数据未修改，不重跑模型替代失败。

## 已完成的运行材料

- `protocols/agentdojo-local-pilot20-v2/` → `private/runs/agentdojo-local-pilot20-001/`
- `protocols/agentdojo-step5-pilot20-v2/` → `private/runs/agentdojo-step5-pilot20-001/`

逐单元结果实时保存；结束后生成 manifest/checksums，再进行凭据扫描、按白名单导出、官方 scorer 重算和签名验真。既有 5 任务 smoke 的无防御攻击零命中结论保留；若本批 B0 仍零命中，也不能声称 SIQ 的增量安全收益。

独立第三方隐藏题、至少 20 个应用原生任务块、其他核心机制及完整防护映射仍待完成；本批 240 个单元不能替代这些工作。

## 离线恢复问题的补充记录

首次 Step 5 复核在 user_task_6-benign-B1 出现效用不一致。上游 Inbox/Calendar/CloudDrive 的 after model_validator 会把当前集合重建为 initial_*，普通 model_validate_json 不是执行后快照的无损加载。新 decoder 对原字段按上游类型逐项验证和恢复，并强制完整 JSON 往返相等；不修改原始快照、模型结果或官方 scorer。24 个变动日历/文件单元的评分因此恢复一致。原失败诊断仍保留。正向攻击邮件校准明确证明旧加载会丢掉实际攻击效果，新加载保留并被原官方 scorer 判为成功；该校准不混入模型测评分母。
