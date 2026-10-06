# 规则首次发现与人工处置刷新并发预注册001

2026-10-06，候选5470ab3780f2-riskracefix1。真实原生采集资产经HTTP确认后首次扫描，两项真实规则为无负责人、无effective权限。三个PG可观测重叠组：首次扫描/首次扫描，接受/规则刷新，解决/规则刷新。

首次创建：只在租户A的finding.open审计INSERT上设置等待advisory锁的实验触发器。首个扫描出现锁等待后，调用租户B规则扫描，预期在屏障释放前正常200且零结果；再启动第二个A扫描，观察两个不同PID锁等待后释放。预期最终各规则一条open（共2），审计与outbox各2；两响应一组created=2 updated=0、一组created=0 updated=2。不能把响应成功当去重成立。

首次结果立即冻结在观察记录中，不重写失败。随后正常HTTP解决全部已生成finding，真实规则重扫取得两条新open；旧finding均保留resolved，作为刷新组独立起点。若首阶段重复，清理HTTP条数按实际结果计，不假装两批总请求相等。

刷新接受：持目标行锁，先发accept-risk并确认锁等待，再发run-rules并确认第二个等待，释放后两者200。目标必须risk_accepted，owner/完整接受元数据与HTTP一致；只新增一条接受审计与事件，规则不得另建open或覆盖状态。等待真实4秒截止后reaper重开，再HTTP解决并扫描取得新目标，不SQL重置状态。

刷新解决：同样先发resolve再扫描，二者200；旧ID必须resolved并保留修复引用。允许扫描在解决前读取并只刷新旧记录，或在解决后观察到终态并创建复发记录，两种均为合法重叠次序；不能为制造失败强制其中一种。之后在两者完成后再扫描，必须恰有一个新的同范围open，原解决历史不改。

主HTTP只有risk_confirm新增，其余并发/准备请求进入extra_http并与事件流逐项核对。八项风险判据：first_overlap、first_unique、other_tenant、fresh_preparation、refresh_accept、refresh_resolve、later_recurrence、cleanup。实际字段见冻结ASSERTIONS。所有额外HTTP应200，真实清理reaper重开1，effective始终0，实验屏障删除。

三组屏障是实验控制，不代表自然竞态概率或性能；不验证持续调度、通知故障、UI、客户IdP或独立第三方。无需模型，新增自然攻击与确认任务0。仅自有API、PG、测试issuer与原生临时配置，不调用用户外部服务。
