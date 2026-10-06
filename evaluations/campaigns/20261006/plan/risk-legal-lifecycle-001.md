# 修复候选合法风险生命周期预注册001

候选固定`5470ab3780f2-riskboundaryfix1`，本批不修改产品。旧风险脚本曾在已接受状态覆盖到期值；当前终态门禁正确禁止该行为，本协议改用真实时间到期、实际reaper重开，再接受下一次风险。旧协议和结果不改分。

## 真实入口与流程

1. 使用同候选API、原生Edge及Hermes Connector来源，生产模式PostgreSQL/JWT测试发行器。原生发现资产经HTTP确认，实际规则引擎生成2项风险，列表分页、未知权限和规则幂等仍按旧风险规格检查。
2. 风险acknowledged后先验证越权、缺owner、过期与审计故障的拒绝和原子性。初次合法接受的expiry为当前UTC+4秒，保存数据库前后、响应和审计。
3. 已接受状态再次接受（改reason）应409且无任何副作用，直接解决仍409。实际reaper早于截止运行应0次重开；真实时钟越过截止后应1次重开；重复调用应0次。随后状态为open，保留原接受元数据。
4. 同一finding依次执行-08:00、+08:00、UTC三种到期表达，每次都先读回open，设置新的UTC+4秒截止，验证重复接受409、到期前0/到期后1/重复0，再进入下一阶段。不修改主机时间，不用SQL重置任何finding状态，不允许已接受状态重签。
5. 第四次真实重开后正常解决，重复解决与resolved后接受均拒绝，修复引用不变。完整生命周期审计应为1次ack、4次接受、4次到期重开、1次解决；outbox为4次接受的resolved事件、4次reopened、1次真实解决的resolved事件；effective权限仍0。
6. 按真实数据库核对OCSF finding和审计导出、范围、截断、no-store、返回条数及导出审计。拒绝非法导出不得创建成功审计。

## 分母与通过条件

112项评测器显式HTTP（原风险流程107+5次终态接受拒绝），24项风险专项断言（原19+5），另保留原生和治理检查。原生Edge内部HTTP未独立计数。12个实际reaper子进程、4个真实截止窗口，模型调用0、独立自然攻击任务增量0。每个早期子进程必须在真实截止前结束，否则判定时序控制失败，不得借延迟宣称安全正确。

数据记录同一finding每次接受前的完整状态，必须与前次reaper重复调用后的状态一致。每次到期恰新增1条worker审计和1条reopened outbox，并保留owner及原接受元数据；最后的总账必须闭合。新增评分器负向检查覆盖未重开即再次接受、假时序、缺事件/重复事件、错误actor、终态允许/变更、借用finding和伪effective。

## 解释边界

这是受控调度实际reaper的顺序业务闭环，不是长期worker循环、调度SLA、通知/Webhook、并发状态竞争、真实客户IdP、其他OS或独立第三方验收。没有运行完整worker.once的规则重评阶段，不能据此证明接受风险在周期规则重评时始终受到抑制。风险接受不等于授予运行权限，fixture修复引用不是外部工单真实性核验。

## 执行

使用候选Python3.12；冻结并重新核对解释器二进制、版本、依赖、候选源码和测评源码：

```bash
python benchmarks/third-party/enterprise_risk_v2_trial.py freeze --campaign third-party-evaluation/20261006 --protocol-id risk-legal-lifecycle-001-protocol --candidate third-party-evaluation/20261006/private/candidates/5470ab3780f2-riskboundaryfix1
python third-party-evaluation/20261006/protocols/risk-legal-lifecycle-001-protocol/harness-source/enterprise_risk_v2_trial.py run --campaign third-party-evaluation/20261006 --protocol-id risk-legal-lifecycle-001-protocol --run-id risk-legal-lifecycle-001 --candidate third-party-evaluation/20261006/private/candidates/5470ab3780f2-riskboundaryfix1
```

运行、离线核验、白名单导出、原始CLI/worker输出复核及资源清理都必须有记录；失败另编号修订，不覆盖本协议。
