# 企业风险接受边界修复后复测002

沿用001全部99项显式HTTP与16项边界断言，不改变错误输入、状态码和无副作用标准。001完整执行150项检查、132通过、18失败；未缺请求、未发生测评器异常。4种不合法输入实际写入风险接受，另有超长owner与极端expiry返回500；低权限对象定位顺序、重复接受与resolved覆盖均有原始证据。非法输入污染后续ack控制，保留为失败，不回填原状态。

新候选`5470ab3780f2-riskboundaryfix1`继承riskfix1py312，明确同Python3.12/二进制摘要/锁定依赖；新增负责人/原因模型验证，finding先定位再授权，终态状态检查及行锁，UTC换算越界受控422。新[合同说明](../../../packages/contracts/enterprise-risk-acceptance.v1.md)保留字段和正常open/acknowledged接受语义。修复前HTTP单测12失败、3通过，修复后逐项回归。

终态不再允许覆盖，会使早期enterprise-risk-001–003脚本中“已接受后再接受以替换到期值”的步骤不再是当前合法流程。旧候选、旧协议和成绩继续有效，不能用本次单测或边界实测声称旧脚本在新候选上依然通过。后续完整到期链需先等待自然到期重开，或用独立finding，再分别接受各时区截止时间；不可通过SQL重置或放宽终态门禁恢复旧测试。并发、持续worker/UI/通知及更多事实来源仍未覆盖。

```bash
python benchmarks/third-party/enterprise_risk_boundaries_trial.py freeze --campaign third-party-evaluation/20261006 --protocol-id enterprise-risk-boundaries-002-protocol --candidate third-party-evaluation/20261006/private/candidates/5470ab3780f2-riskboundaryfix1
python third-party-evaluation/20261006/protocols/enterprise-risk-boundaries-002-protocol/harness-source/enterprise_risk_boundaries_trial.py run --campaign third-party-evaluation/20261006 --protocol-id enterprise-risk-boundaries-002-protocol --run-id enterprise-risk-boundaries-002 --candidate third-party-evaluation/20261006/private/candidates/5470ab3780f2-riskboundaryfix1
```
