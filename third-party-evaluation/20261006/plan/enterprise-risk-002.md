# 企业风险生命周期修复后复测002

继承[001完整协议](enterprise-risk-001.md)，107项显式HTTP、19项风险断言、3种时区、9个真实reaper子进程及所有结果判据不变。001实际107项请求全部完成，157/161通过，4项时区行为检查失败；无测评器中断、无缺失项，原证据不可覆盖。

新候选`5470ab3780f2-riskfix1`从governancefix1相同源码提交及原明确补丁构造，只新增风险接受reaper UTC换算与15项时区回归测试。修复先将aware时间换算UTC再去时区，与现有API到期检查一致；历史naive时间和严格小于到期判据不变。不调整冻结评分器或阈值。原生Edge/Hermes Go源码完全未变，复用父候选已记录摘要的同一组二进制，不声称重新构建原生制品。

修复前新增测试15项中6项失败，覆盖正负整小时/半小时时区的提前和延后重开；修复后聚焦测试通过。真实002仍以新环境、新资产、新截止时刻实际执行；两个批次分别报告，不合并为全通过。

```bash
python benchmarks/third-party/enterprise_risk_trial.py freeze --campaign third-party-evaluation/20261006 --protocol-id enterprise-risk-002-protocol --candidate third-party-evaluation/20261006/private/candidates/5470ab3780f2-riskfix1
python third-party-evaluation/20261006/protocols/enterprise-risk-002-protocol/harness-source/enterprise_risk_trial.py run --campaign third-party-evaluation/20261006 --protocol-id enterprise-risk-002-protocol --run-id enterprise-risk-002
```

所有001范围限制继续适用：实际reaper受控调用不是持续worker服务验收，fixture工单不是外部工单查验，产品OCSF映射不是外部标准认证，真实IdP、其他OS和独立第三方仍需后续证据。
