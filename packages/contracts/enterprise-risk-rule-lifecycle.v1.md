# Enterprise risk rule lifecycle v1

版本1，2026-10-06。明确企业确定性规则引擎的周期重评与人工风险处置关系；适用于`POST /api/v1/findings/run-rules`及worker的`run_rules`。接口字段不变，无数据库结构变更。

同一`(tenant_id, rule_id, asset_id, resource_ref)`范围内，open、acknowledged、risk_accepted均属于未解决风险。再次命中只能刷新现有finding的last_seen_at，不改变ID、状态、负责人或风险接受元数据，不重复创建finding.open审计或opened事件。acknowledged表示已开始处置；risk_accepted的到期重开由reaper负责，规则扫描不得旁路人工处置生成另一条open。

完整worker先运行到期重开，再进行规则重评；到期重开原ID，规则命中继续刷新此ID。已resolved不参加上述去重；若实际条件仍存在，创建新open并保留原解决历史与证据。不同tenant、rule、asset或resource不得相互抑制；空值按原查询语义精确匹配。

规则不创建effective权限，不下发策略。已有重复历史不在本修复中自动合并或删除。该合同为顺序调用语义；并发首次发现的唯一性、与人工处置的竞争、跨worker领取仍需单独验证，不据本修复宣称并发安全或exactly-once。审计/outbox与新finding保持原事务边界。
