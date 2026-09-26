# 企业候选批量驳回 v1

POST /api/v1/candidates/bulk-dismiss，请求 {schema_version: enterprise-candidate-bulk-dismiss/v1, items:[{asset_id, expected_updated_at}], reason_code}。items 沿用批量确认的 1–50 个显式、去重、版本绑定对象；reason_code 为 duplicate / out_of_scope / not_agent，保存固定中文原因，不接受自由文本或批量期限。

全部对象先认证租户定位 404，再检查 agent:confirm 403；仅 candidate/needs_review 且版本一致，条件更新冲突 409。按 ID 排序写入，整批状态、逐项审计/outbox 同事务，失败全部回滚。与逐条驳回共享条件更新，不能覆盖已经确认的对象。不删除安装文件、不停止进程、不授予权限、不创建实例。不存在默认自动过期；后续再发现遵循原候选状态规则。

响应 {schema_version: enterprise-candidate-bulk-dismiss-result/v1, items:[AgentAssetOut]}，按请求顺序，no-store。未知网络结果必须只读核对，不自动重试。审计只保存原因 SHA-256，不复制自由文本；事件 agent.asset.dismissed.v1 只含资产引用。原逐条接口原因字段保持兼容，但审计改为摘要并补 outbox。

前端复用候选显式选择与批量复核组件，以 action=confirm/dismiss 区分终态。驳回必须选择原因并勾选核对，修改原因清除勾选，未知结果期间原因锁定；仅当所有读回对象都是 dismissed 才报告当前全部已驳回。confirmed 不能当驳回成功。全部仍为候选时更新版本并要求重新确认，混合状态不得自动拆批处理。刷新/关闭清空选择，不持久化浏览器存储。
