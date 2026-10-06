# 原生企业资产风险生命周期与导出测评001

预注册，未执行结果。延续RB13真实资产与风险处理范围，固定候选`5470ab3780f2-governancefix1`，API、Edge及Hermes Connector来源相同；只创建本批生产模式API和独立PostgreSQL17，用测试RS256/JWKS与两个fixture租户，不使用现有业务数据库。

## 入口与完整流程

1. 沿用已冻结的治理与合成Edge协议负向检查，同时真实原生Edge注册、实际Connector采集配置，形成可关联签名证据的资产。
2. 对原生资产经HTTP确认，不设置owner，不创建effective权限。调用实际规则引擎，应形成unowned-confirmed-agent和no-effective-permissions两项风险；再次执行不产生重复finding。权限未知不得提升为生效。
3. 实际列表limit=1及游标翻页应覆盖两项、不重不漏；截断与返回条数响应头诚实。跨租户asset查询404。风险确认成功后重复确认409。
4. 风险接受：跨租户404、无权限403、缺owner422、已过期422，数据库finding/审计/outbox均不变。审计触发器故障时500、状态同事务回滚。恢复后正常接受包含owner、reason、expiry并有审计和outbox；已接受状态直接resolve应409。
5. 三种时区分别设置真实截止时刻（当前UTC+4秒），通过API传递-08:00、+08:00、UTC形式；即刻调用候选真实`reap_expired_risk_acceptance`子进程，不应重开且状态不变。待实际时钟越过截止后再次调用，应重开并新增过期审计；再调用无重复。早期子进程结束必须早于截止，否则记录时序校准失败，不能当作产品缺陷或通过。不修改主机时间、不伪造数据库到期值。
6. UTC恢复控制结束后由HTTP解决风险，带可追溯fixture工单引用，重复解决409；此处验证引用字段与审计，不宣称引用的外部工单真实存在。
7. OCSF detection_finding实际NDJSON导出：limit1有截断、全量2项无截断、另一租户和未来since返回空；class_uid、status_id、finding ID和独立SQL真值一致。每次导出恰新增本租户一条审计，count为实际返回条数，summary不含导出正文。非法class、极端since和无权限拒绝不产生导出审计。api_activity按独立SQL顺序核对操作、actor、resource和summary。
8. 记录完整HTTP响应、白名单元数据头、原始worker输出、SQL状态、事件和摘要；离线重算，清理本批资源，保留所有失败。

## 分母、身份与边界

107项评测器显式HTTP：原治理/合成Edge73+原生控制请求5+风险/导出29；原生Edge内部HTTP未独立计数。19项风险专项断言、6项原生断言；9个真实reaper子进程，3个真实等待窗口。模型调用0，不增加独立自然攻击任务。

源码初查发现reaper可能只移除时区而不换算UTC。这是待验证假设，不能在执行前当成已确认缺陷。时间窗不足、API或子进程失败与产品逻辑错误分开记录；首次错误保留，修复后另候选与另协议复测。

这是实际后台处理函数的受控调度，不是长期运行的worker服务、通知投递或生产负载测评。OCSF核对以本产品合同为准，不宣称外部OCSF schema认证。风险接受不等于授予运行权限，导出不等于完整归档；无模型/业务运行时保护或跨OS结论。

## 执行

使用固定候选`apps/control-api/.venv/bin/python`运行：

```bash
python benchmarks/third-party/enterprise_risk_trial.py freeze --campaign third-party-evaluation/20261006 --protocol-id enterprise-risk-001-protocol
python third-party-evaluation/20261006/protocols/enterprise-risk-001-protocol/harness-source/enterprise_risk_trial.py run --campaign third-party-evaluation/20261006 --protocol-id enterprise-risk-001-protocol --run-id enterprise-risk-001
```

离线核验使用同冻结目录的verify_governance.py及执行输出的manifest锚点。修改判据或产品后不覆盖001协议及数据。
