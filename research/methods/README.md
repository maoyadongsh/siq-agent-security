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


## 机制如何进入可检验实验

| 工程机制 | 可检验对照 | 实现与实验入口 |
| --- | --- | --- |
| 独立 Intent 与参数来源 | 相同参数值、不同来源身份；值未变而授权或作用域改变 | [运行时与 provenance](../../apps/agentshield/README.md)、[运行时基准](../../benchmarks/runtime-security/README.md) |
| SEC 的安装归属 | 名称/路径相同，但安装摘要、实例、会话或授权不匹配 | [skillcontext](../../apps/agentshield/internal/skillcontext/)；当前组件断言不替代跨宿主实验 |
| 批准后的最终检查与唯一预留 | 批准后撤权、改参、重复回调、预留响应丢失 | [适配器协议](../../adapters/runtime/README.md)、[OpenClaw 固定补丁](../../patches/openclaw/README.md) |
| 效果与完成分层 | 工具返回成功但效果缺失，或实际内容/接收端冲突 | [Secure Agent](../../apps/secure-agent/README.md)、[控制案例](../../benchmarks/hackathon/README.md) |

这些组合提供可审查的技术贡献与实验切入点。它们不是对全部前沿方法的优越性结论；与外部工作的比较需使用同任务、同威胁边界和同成本预算的新协议。来源登记、观察器可靠性、同用户宿主边界与未知效果应同时作为实验条件报告。
