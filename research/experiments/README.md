# 实验设计与复现路线

[研究总览](../README.md) · [方法](../methods/README.md) · [结果解释](../findings/README.md)

历史研究命令以根 [REPRODUCIBILITY.md](../../REPRODUCIBILITY.md) 为复现说明；现有执行器保留在 `benchmarks/` 和 `scripts/`，产品构建不依赖本目录。先读[环境矩阵](../../docs/research/environment-matrix.md)、[回顾性协议](../../docs/research/evaluation-protocol.md)与[数据卡](../../docs/research/dataset-card.md)。

| 路线 | 输入和执行器 | 回答什么 / 不能证明什么 |
| --- | --- | --- |
| A 交互式固定演示 | 明确 `--mode test`，[演示脚本](../../scripts/hackathon/)与真实本机运行时 | 观察界面、配对及受控效果；无需模型密钥/GPU，不测模型受攻击概率 |
| B 固定控制 | 23 个自有控制案例，[run.py](../../benchmarks/hackathon/run.py)与[verify.py](../../benchmarks/hackathon/verify.py) | 复算预期、回执链和效果；筛选单案例是部分覆盖，公开夹具不是保留集 |
| 运行时工程套件 | [runtime-security](../../benchmarks/runtime-security/README.md) | 测版本化工程场景；不与 23 案例或模型 cohort 合并分母 |
| C 可选真实模型/DGX | [DGX 操作手册](../../deploy/dgx-spark/README.md)、独立 model-utility cohort | 正常任务效用、成本/locality 等特定观察；需授权的环境、私有配置与预算 |
| 外部论文/基准复现 | [AgentDojo 试点](../../third-party-evaluation/20261006/reports/agentdojo-pilot20-report.md)及 [third-party 执行器](../../benchmarks/third-party/README.md) | 项目方完成 240 单元探索，未证明增量邮件防护；外部题库不等于独立执行，SafeClaw 工作仍为计划 |
| 外部团队复现 SIQ | [外部入口与模板](../../evaluations/external/README.md) | 记录执行者、利益关系、候选和证据；托管 CI 与维护者运行不算独立复现 |

每次使用全新的输出和状态路径，记录完整源码 SHA、dirty 状态、语料/应用摘要、工具链/模型/宿主版本、所有尝试与失败、超时及成本。重跑产生新记录，保留早期失败；报告校验失败应调查原因，不修改数字或签名来通过。私有状态含签名材料；按[导出政策](../../docs/research/data-export-policy.md)生成可公开摘要，勿上传原始状态或配对信息。

20261006 的真实业务权限复现使用[专项入口](../../third-party-evaluation/20261006/README-PERMISSIONS.md)及逐批协议，不套用历史演示参数。[后续方案](../../docs/research/SIQ_后续第三方测评实施方案_20261006-200416.md)将公开开发包、确定性机制试验、真实模型任务和独立隐藏集分开；每次使用新活动目录，已完成收口不自动启动这些新工作。
