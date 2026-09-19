# 应用与运行入口

SIQ 把研究问题落实为可独立运行、边界明确的组件：模型负责提出任务动作，授权服务决定是否允许，观察器提供效果材料。个人客户端、企业控制面和研究应用共享合同，但不共享隐式管理员身份。

| 应用 | 职责与入口 | 运行依赖与边界 |
| --- | --- | --- |
| [AgentShield 本地运行时](agentshield/README.md) | Skill 准入、授权、执行前检查、生命周期、回执与个人管理 API | Go 标准库；内嵌个人 UI；不要求企业 API、数据库或模型 |
| [Web 控制台](web/README.md) | 同一源码树中的个人与企业两种构建 | React/TypeScript；分别连接本地 daemon 和 Control API，不由浏览器签发权威 |
| [Control API](control-api/README.md) | 多租户资产、证据、策略审批、部署读回、Edge 协调与审计 | Python/FastAPI，生产 PostgreSQL + OIDC/JWKS；独立部署 |
| [Secure Agent](secure-agent/README.md) | 研究参考应用：规划、Skill 选择、受约束工具执行与完成核验 | Python 标准库 + 本地运行时；显式 fixture 或已配置模型，不能执行任意 Skill 代码 |

## 如何选择

安装使用从[签名包指南](../docs/signed-release-packaging.md)开始；改本地产品从 AgentShield 和 Web 开始；企业治理从 Control API、[Edge](../edge/agent/README.md)与[Connectors](../connectors/README.md)开始；研究复现从 [REPRODUCIBILITY](../REPRODUCIBILITY.md)开始。源码构建、正式发行和冻结研究快照各自有身份，不能互相替代验收。

跨组件字段以 [contracts](../packages/contracts/README.md) 为准。贡献者应先确定改动所属层，再运行该模块的检查；共同安全边界和原生平台证据见[贡献指南](../CONTRIBUTING.md)、[平台矩阵](../platforms/support-matrix.md)与[测评索引](../evaluations/README.md)。
