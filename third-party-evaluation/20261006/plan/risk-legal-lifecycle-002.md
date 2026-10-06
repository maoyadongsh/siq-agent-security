# 合法风险生命周期总账修订002

001真实执行112项HTTP全部符合状态预期，四轮实际到期均为0/1/0，正常接受、终态拒绝、解决、导出均通过；171项检查中只有最终总账失败（170/171）。原始失败、协议和评分器完整保留。

原因是001预注册及新评分器漏算实际规则引擎创建finding的`finding.open`审计和`agent.finding.opened.v1` outbox。真实数据为11条审计、10条outbox，并非异常多写。本修订按可核对的业务来源补齐总账：创建1 + 确认1 + 接受4 + 到期重开4 + 解决1 = 审计11；创建1 + 接受4 + 到期重开4 + 解决1 = outbox10。评分器同时强制创建事件各恰好1条，不泛化为忽略额外事件。单测夹具也补上真实来源的创建记录。

其余112项HTTP、24项风险断言、4个真实截止窗口、12次reaper调用及14种错误证据反例不变。仍使用同一`5470ab3780f2-riskboundaryfix1`候选、同解释器/依赖，无产品修改。新环境重新执行后单列002结果，不把001事后改分为通过。

```bash
python benchmarks/third-party/enterprise_risk_v2_trial.py freeze --campaign third-party-evaluation/20261006 --protocol-id risk-legal-lifecycle-002-protocol --candidate third-party-evaluation/20261006/private/candidates/5470ab3780f2-riskboundaryfix1
python third-party-evaluation/20261006/protocols/risk-legal-lifecycle-002-protocol/harness-source/enterprise_risk_v2_trial.py run --campaign third-party-evaluation/20261006 --protocol-id risk-legal-lifecycle-002-protocol --run-id risk-legal-lifecycle-002 --candidate third-party-evaluation/20261006/private/candidates/5470ab3780f2-riskboundaryfix1
```

[001协议](risk-legal-lifecycle-001.md)其余所有流程和范围限制保留。长期worker规则重评/通知、并发、UI与外部独立复现仍不由本批证明。
