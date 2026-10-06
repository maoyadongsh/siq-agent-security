# 企业风险完整worker周期预注册 001

2026-10-06。固定候选5470ab3780f2-riskboundaryfix1；继承原生Edge/Hermes配置采集、生产API/独立PostgreSQL、真实签名身份与治理拒绝对照。新增批次，不改旧成绩。

目标：同一(rule_id, asset_id, resource_ref, tenant)风险在open、acknowledged与risk_accepted有效期内被规则重新扫描，不应另建open记录绕过处置；实际到期重开原ID；已resolved但原因持续存在时允许生成新的open记录，同时保留已解决历史。该预期由风险接受到期重开语义和风险处置功能导出，首轮要检验现有实现是否满足，不能先调实现再记首试通过。

步骤：原生采集→HTTP确认→实际规则生成2项finding→完整worker(open)→HTTP acknowledge→worker(acknowledged)→HTTP接受至UTC现在+5秒→worker(accepted/accepted_repeat)→实际等待截止后→worker(expired/expired_repeat)→HTTP读取→HTTP resolve，合成修复引用但故意保留规则条件→worker(resolved/flush)→HTTP读取。8个独立子进程均调用真实app.worker.once；不替换子函数、不SQL插入/重置finding、不修改时钟。

每阶段保留独立SQL finding/审计/outbox/发布状态/effective事实，原始子进程stdout/stderr和UTC起止。到期前两个worker必须在截止前结束，到期后worker须在截止后开始；超窗失败，不伪装功能通过。正向期望rules created=0 updated=2；resolved首次重评created=1 updated=1，后续created=0 updated=2。初始2项，最终3项，其中目标历史resolved、新目标open及其他未处置风险open。

接受/确认不能被新open绕过；到期只产生一次worker审计及reopened事件；原目标审计共5条：创建、确认、接受、到期、解决。全资产outbox共6条：最初2、接受1、到期1、解决1、复发创建1。专属loopback HTTP接收端真实收取全部worker Webhook，按event_id和完整payload与SQL逐项关联。发布发生在reaper和rules之前，因此用后续周期投递新事件；正常无失败条件下每条收取1次，不外推exactly-once或客户通知。effective始终0。

12项预注册断言见冻结enterprise_risk_worker.ASSERTIONS；HTTP数由协议expected_status完整分配。每项HTTP及断言均保留失败，评分不抛异常隐藏业务负例。模型调用0、自然攻击样本0。完整worker含outbox、reaper、dismissal、breakglass、drift、rules；本fixture后3项无待处理对象，backend=none使drift明确skipped，不宣称覆盖其业务。

资源：仅自有临时数据库、测试issuer/API、原生临时配置和接收端，结束核对清理；不发送外部Webhook。未验证：持续调度、竞争/崩溃、故障重试、客户IdP、企业UI、共享运行隔离及独立第三方。
