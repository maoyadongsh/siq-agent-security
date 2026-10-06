# 风险处置真实并发预注册001

2026-10-06，候选riskworkerfix1。目标为接受、解决、确认及到期处理相遇时状态与成功响应、审计和outbox一致。先真实复现，保留失败，不修改既有顺序测试结论。

真实原生Edge/Hermes采集→生产API/PG→确认资产→规则生成finding，使用no-effective-permissions。主HTTP固定3项新增，治理与原生基座继承；并发与准备请求独立记录extra_http，不混入基座分母。每组有独立finding ID，通过实际API解决旧风险及规则重新命中取得新ID，不SQL插入、删除或重置finding。

五组：两个accept-risk；两个resolve；accept-risk与resolve；accept-risk先进入锁等待后acknowledge；两个真实reap_expired_risk_acceptance子进程。前四组评测事务锁定目标finding，先发第一请求并观察一个PG锁等待，再发第二请求观察两个不同PID锁等待后释放。预期一个200一个409 invalid_state，最终状态、owner/接受或解决元数据与赢家一致，只新增一条对应审计及一条事件；accept_ack预期接受先完成、确认拒绝。不把线程启动当已并发。

到期组先真实接受至UTC现在+3秒，等待实际截止之后。专属审计触发器只在到期审计INSERT时等待评测者持有的advisory锁。第一个worker等待后启动第二个；保留第二个等待或在锁持有期间合法跳过已锁记录而完成的事实。释放后预期两返回重开数合计1、原finding重开一次、owner/元数据不变、审计和outbox各增1。触发器只延迟，不篡改数据或决策；原始stdout/stderr、PG等待快照及UTC时间可复核。不能把强制重叠频率当自然负载或吞吐。

各组准备/清理均用真实HTTP、到期和重开；全部准备请求需200，清理reaper需真实重开1。主测评器、分配、评分器冻结；五组风险断言加准备、effective=0和屏障清理，共8项。所有失败与运行器异常保留，不在失败后覆盖原包。

限制：本次仅到期函数并发，非完整worker通知；没有规则首次创建并发、长期调度、其他OS、客户IdP或独立第三方。0模型调用、0新增独立攻击任务。仅自有PG/API/issuer/原生配置与锁屏障，结束删除屏障并清理资源。
