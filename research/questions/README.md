# 研究问题与可检验假设

[研究总览](../README.md) → 问题 → [方法](../methods/README.md) → [实验](../experiments/README.md) → [结论](../findings/README.md)。问题的唯一编号定义保留于[原研究问题](../../docs/research/research-questions.md)，下表给出设计下一轮实验的阅读路线，尚不是新的预注册或已接受的创新主张。

| 问题 | 要区分的现象 | 原有材料与下一步 |
| --- | --- | --- |
| RQ1 独立授权与正常任务完成 | 模型提出动作，独立执行面决定授权；拒绝攻击与保持正常任务效用分别计数 | [固定语料](../../benchmarks/hackathon/cases.json)和[主张证据](../../docs/research/claims-evidence.md)；需未见任务、配对对照与不确定性分析 |
| RQ2 同值不同来源 | 参数值相同，可信来源与不可信工具内容的来源身份不同 | [来源约束技术报告](../../docs/research/technical-report.md)；拓展来源类型与未知上下文，测来源登记错误 |
| RQ3 工具成功与实际效果 | 工具响应、裁决回执、接收端观察和任务完成是不同层次 | [效果证据](../../docs/research/claims-evidence.md)；补观察器故障、冲突与外部效果系统 |
| RQ4 保密分析的 locality | 配置的机密内容是否进入远端传输，连接失败是否触发回退 | [归档复现](../../docs/research/result-reproduction.md)；补独立环境与分类错误，不用宿主适配覆盖率替代 |
| RQ5 动态 1/2/3 Skill 的效用与成本 | 相同任务单位下，完成率、模型调用和成本如何变化 | [原协议](../../docs/research/evaluation-protocol.md)；先制定新协议与预算，再运行足够任务单位 |

文献线索见[目录](../literature/README.md)。根总览中的多宿主/隔离能力分层是工程研究专题，不替换 RQ4。重复种子不增加独立任务数；正常、攻击目标、来源案例的分母可以重叠，不能相加。
