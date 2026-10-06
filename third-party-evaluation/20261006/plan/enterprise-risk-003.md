# 企业风险生命周期解释器一致性复测003

继承001完整业务协议与002产品修复。002真实107HTTP、161/161检查通过，但依赖建立时uv自动选择Python3.13，原001为Python3.12；这是环境混杂，不能把001→002描述成只改变worker一行的严格对照。保留002所有成功数据和Python3.13全量回归，不覆盖环境。

003候选`5470ab3780f2-riskfix1py312`产品源码与002完全一致（含时区修复），明确使用001 Python解释器建立独立虚拟环境，锁文件保持原值。冻结协议新增解释器完整版本、二进制sha256及已安装包名称/版本列表；运行前重新检查相等。该元数据检查不改变业务状态码、时间窗口或19项风险评分函数。001/002解释器以其仍存在的虚拟环境和当时uv日志事后记录，不能伪称其运行前已冻结该字段。

再次执行107项显式HTTP、9个真实reaper子进程、三个实际时区到期窗口；原生Go源码及二进制继续复用且摘要匹配。所有原范围限制继续适用。

```bash
python benchmarks/third-party/enterprise_risk_trial.py freeze --campaign third-party-evaluation/20261006 --protocol-id enterprise-risk-003-protocol --candidate third-party-evaluation/20261006/private/candidates/5470ab3780f2-riskfix1py312
python third-party-evaluation/20261006/protocols/enterprise-risk-003-protocol/harness-source/enterprise_risk_trial.py run --campaign third-party-evaluation/20261006 --protocol-id enterprise-risk-003-protocol --run-id enterprise-risk-003
```
