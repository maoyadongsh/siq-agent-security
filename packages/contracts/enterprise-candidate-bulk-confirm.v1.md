# 企业候选批量确认 v1

POST /api/v1/candidates/bulk-confirm，请求 {schema_version: enterprise-candidate-bulk-confirm/v1, items:[{asset_id, expected_updated_at}]}，1–50 个不同候选。只确认已查看的对象版本，不支持隐式全选或覆盖业务用途/负责人，不创建权限、策略或运行时授权。

先按认证租户定位所有对象，任一个不存在/跨租户返回统一 404，再校验 agent:confirm 权限（403）。所有对象必须 candidate/needs_review，更新时间与预览一致；原子条件更新在状态与版本冲突时返回 409。按 ID 排序获取写入锁，所有状态/观察实例/逐项审计及 outbox 同事务；任一失败全部回滚，不返回部分成功。沿用逐项确认创建默认 observed 实例的现有兼容行为，不将该实例描述成运行时已绑定。

响应 {schema_version: enterprise-candidate-bulk-confirm-result/v1, items:[AgentAssetOut]}，按请求顺序，Cache-Control=no-store。网络结果不明时客户端必须重新读取候选/资产状态，不能把再次调用的 409 当失败回滚或盲目重试。旧逐项确认同样使用状态/版本条件更新，不能与批量确认并发重复创建默认实例。真实 PostgreSQL 并发验收单独记录。

前端候选列表提供逐项勾选及“选择已加载前 50 个”，不是跨页隐式全选；提交前弹窗列出固定对象/版本并要求显式核对。提交过程禁用重复提交和弹窗关闭。失败/响应无法核验时转只读核对，每组最多 5 个并发 GET；全部仍待确认时重新展示版本并清除勾选确认，状态混合时不自动处理剩余项。已全部确认只报告当前状态，不能归因于本次写入。关闭/刷新清除选择，不持久化到浏览器存储。
