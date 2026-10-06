# 企业风险完整worker周期：首次缺陷与修复复测

2026-10-06，作者侧本机执行。**旧候选128/133；修复候选133/133。**每批86项显式HTTP全部符合预期、8次真实完整`app.worker.once`执行，无缺失请求或运行器异常。首次发现的问题不在HTTP状态码，而在周期规则重新扫描后的业务状态。

## 产品问题与实际影响

原规则只查同范围的open finding。用户确认风险后，周期扫描没有复用acknowledged记录，而是另建一条open。随后接受原风险，新open仍继续存在；原记录到期重开后出现同范围两条open。用户的确认/接受操作因此不能维持预期的处置状态，风险台账和通知时点出现重复与歧义。

001中五项断言失败：确认保持、接受保持、到期身份、重开幂等、已解决后复发。它们是一个状态去重缺陷沿业务链传播的表现，不是五个独立漏洞。此结果也说明：此前只运行到期处理函数的171/171不足以证明完整worker链路正确，旧结论范围仍限定于其原协议。

修复仅改变[规则引擎](../../../apps/control-api/app/rules.py)：同tenant/rule/asset/resource下复用open、acknowledged、risk_accepted，只刷新last_seen_at，保留负责人、接受原因及截止时间。已resolved不参加去重；条件仍然存在时创建新open，保留已解决历史。不删除或自动合并已有重复记录。顺序语义见[新合同](../../../packages/contracts/enterprise-risk-rule-lifecycle.v1.md)，并发唯一性仍未证明。

## 真实入口与阶段结果

真实Edge CLI/Hermes Connector读取专属合成配置→签名采集→生产模式API/独立PostgreSQL→HTTP确认原生资产→实际规则生成两项风险→人工确认/接受→完整worker→到期/解决/复发。没有SQL造finding、重置业务状态或修改时钟。身份使用本机测试issuer，非客户IdP。

| 阶段 | 旧候选001 | 修复候选002 |
|---|---|---|
| open重评 | 复用原记录 | 复用原记录 |
| acknowledged重评 | 另建open，原确认记录仍在 | 保持原ID和acknowledged |
| risk_accepted两次重评 | 原接受记录与提前创建的open并存 | 保持原ID及接受元数据，无新建 |
| 真实截止时间后重评 | 原ID重开，但已有另一open | 原ID重开，仍仅一条目标风险 |
| 重复到期周期 | 两条open持续存在 | 不重复重开或产生事件 |
| resolved后条件仍命中 | 复发记录已在确认阶段提前创建 | 此时新建open，保留原resolved与证据 |
| 后续发布周期 | 事件可投递，不能纠正处置重复 | 新事件投递完成，不重复创建 |

修复批次初始2项finding，最终3项：未处置的“无负责人”、原“无effective权限”已解决、新“无effective权限”open。fixture的修复引用仅为合成工单，底层条件故意保留，用于验证复发，不声称真正完成整改。

每批8个子进程都调用完整`once`：发布outbox、接受到期、dismissal、breakglass、drift及rules。后三类业务无待处理对象；backend=none使drift明确skipped，不算其功能验收。接受期限为UTC现在+5秒；两个到期前周期实际在截止前结束，到期周期实际在截止后开始。

## 审计与真实通知

002原目标完整审计5条：创建、确认、接受、到期、解决。资产范围outbox6条：初始两条、接受、到期、解决及复发创建。接收端为本批专属loopback HTTP服务，实际收到的event_id和完整payload逐项与数据库对应，最终六条均发布。

每批接收端总收取16条，包括前置治理等其他事件；不能全部计为风险通知。worker先发布，再处理到期和规则，因此新事件在后续周期投递。无失败条件下每条一次不代表exactly-once，也未验证外部客户通知服务、重试和崩溃恢复。风险接受和worker均未增加effective权限，不能声称运行时隔离或自然攻击收益。

## 固定对象、失败保留与工程验证

001：`5470ab3780f2-riskboundaryfix1`。002：`5470ab3780f2-riskworkerfix1`。解释器与依赖指纹一致；业务运行/评分脚本摘要相同。产品仅修改rules.py，增加合同及9项回归测试。

- 修正为显式UTC的同9项回归测试：旧实现4失败、5通过；修复后全部通过。首次无时区单测夹具及首次命令目录错误日志保留，未列为产品缺陷。
- 相关规则、worker、风险输入和时区专项75通过；修复候选完整API套件2296通过、1项可选浏览器采集样本跳过。两轮PostgreSQL迁移均通过。
- 测评框架684通过、118子检查通过。当前新增测试文件格式修正后lint通过；冻结候选保留运行时原测试文件，AST一致，未修改已冻结制品。
- 私有原包与白名单导出分别离线重算；001仍128/133、passed=false，002为133/133。补充核对原生配置/CLI、8份worker原始输出和16份Webhook正文摘要；12种实际证据篡改均被拒绝。
- 导出已知secret/seed与凭据模式扫描无匹配；本批API子进程、数据库容器、原生临时目录与接收端均清理。首次补充检查错取运行器PID的材料保留，正式清理检查已改为api_started.child_pid。

两批共172项显式HTTP、16次完整worker；原生Edge内部HTTP未独立计数。模型推理0，新增独立攻击任务0。检查数不能当独立统计样本数。

## 复核入口

- [001预注册](../plan/risk-worker-cycle-001.md)、[002修复复测](../plan/risk-worker-cycle-002.md)。
- [001导出包](../data/risk-worker-cycle-001/manifest.json)、[原失败核验](risk-worker-cycle-001-export-verification.json)、[原始材料复核](risk-worker-cycle-001-review.json)。
- [002导出包](../data/risk-worker-cycle-002/manifest.json)、[修复核验](risk-worker-cycle-002-export-verification.json)、[原始材料与篡改反例](risk-worker-cycle-002-review.json)。
- [001摘要锚](../inventory/anchors/risk-worker-cycle-001.json)、[002摘要锚](../inventory/anchors/risk-worker-cycle-002.json)、[工程记录](risk-worker-engineering-validation.json)。
- [001导出及清理](risk-worker-cycle-001-export-review.json)、[002导出及清理](risk-worker-cycle-002-export-review.json)。

这些材料由作者执行和持有，非外部时间戳或独立第三方认证。

RB13仍部分完成。当前完整周期的顺序风险处置与本机通知切片已验证；下一优先项是接受/解决/重开的真实并发竞争与规则首次创建竞争，再补长期调度、通知故障、企业UI、更多来源事实、真实IdP和独立复现。不得把此次修复候选成绩与旧候选其他成绩拼成“全产品通过”。
