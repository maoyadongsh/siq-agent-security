# 方法与威胁边界

[研究总览](../README.md) · [问题](../questions/README.md) · [实验](../experiments/README.md)

本项目研究如何让模型的提议经独立授权后执行，并用绑定动作的证据解释结果。现有方法由[技术报告](../../docs/research/technical-report.md)、[威胁模型](../../docs/threat-model.md)、[本机规格](../../docs/agentshield-dev-spec-v1.md)和[版本化合同](../../packages/contracts/)约束；这里组织阅读顺序，不创建另一套协议。

| 方法环节 | 可核对实现 | 需要保留的限制 |
| --- | --- | --- |
| 提议与授权分离 | [Secure Agent](../../apps/secure-agent/)、[Go 运行时](../../apps/agentshield/) | 模型不签发权限；effective 以运行时读回为准 |
| 来源与动作绑定 | [主张—证据](../../docs/research/claims-evidence.md)、[合同](../../packages/contracts/) | 来源登记与敏感性分类有信任前提；不是任意文本的可靠语义判源 |
| 审批到执行一致性 | [本机规格](../../docs/agentshield-dev-spec-v1.md)、[宿主适配](../../adapters/runtime/) | 配置、钩子加载与实际拦截分层验证；未接入路径不自动受保护 |
| 回执与效果观察 | [固定基准与校验器](../../benchmarks/hackathon/) | 签名证明密钥下的记录；未知效果不算无效果，工具声称成功不算完成 |
| 隔离和平台边界 | [平台矩阵](../../platforms/support-matrix.md)、[OpenShell 接入](../../apps/agentshield/internal/openshell/) | 工具层授权不等于同用户进程间 OS 隔离，诊断成功不自动授予 supported |

[现有评测协议](../../docs/research/evaluation-protocol.md)是回顾性的。新增确认性实验应先定义假设、任务单位、先导/保留集、排除标准、配对分析和预算；固定对照中的消融只在可丢弃夹具中运行，不降低正式产品安全约束。[数据卡](../../docs/research/dataset-card.md)记录语料构造、污染与公开边界。
