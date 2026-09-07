# SIQ Agent Security 学术建议可行性评估与优化开发方案

**生成时间：2026-09-07 08:15:59 +08:00**

## 1. 输入与证据边界

本方案依据本地 35 篇论文综述、仓库设计/ADR/合同/开发台账，以及用户提供的 ChatGPT 共享链接。共享链接当前只返回登录页，无法读取对话正文；因此本方案不把未读取的共享对话内容伪装成已提取结论，待提供正文后再增量仲裁。

论文综述是研究输入，不是安全证明。论文中的攻击成功率、模型或评测集数字不能直接成为本项目产品指标，必须在本项目支持矩阵和可复现语料中重新测量。

## 2. 可行性判断

**方向可行，但必须分层落地，不能承诺完整防御通用智能体。** 与本项目设计一致且可直接工程化的方向包括：模型及工具返回不可信、最小权限、完全中介、TCB 抗篡改、Skill provenance、轨迹级风险、资源预算、信息流标签和直接/间接攻击分别评估。

不宜直接采纳的方向包括：仅靠关键词或模型判断认知投毒；把所有网络/sudo/写文件能力判为恶意；仅靠 TTY 或同 UID token 实现强隔离；无真实沙箱证据时宣称 L3；用论文 ASR/GUARDED JOINT 分数替代本项目证据；在本轮自研通用沙箱、通用 IFC 或概率 TCB。

## 3. 差距与工程任务

| 方向 | 现有基础 | 可行性 | 新增任务 |
| --- | --- | --- | --- |
| Skill provenance | manifest 签名、hash、staging、admit | 直接增强 | provenance.v1：来源、发布者指纹、版本、依赖摘要、验证和撤销状态 |
| 指令/数据分离 | 扫描不执行、模型不能审批、回执脱敏 | 基本具备 | 工具返回和记忆在协议层标为 data，不得解析为 policy 指令 |
| 轨迹级认知投毒 | task digest、执行账本、单调用 receipt | 部分具备 | 有界轨迹摘要、触发条件组合、动作前重算、轨迹回放语料 |
| 资源劫持 | grant、session 容量、task lease | 部分具备 | token/时间/并发/CPU/存储/网络/审批次数预算和消耗账本 |
| 信息流控制 | redaction、export privacy、evidence scope | 部分具备 | 有限标签、保守传播、受控 downgrade、泄漏测试 |
| 完全中介 | hooks、fail-closed、OpenShell adapter | 平台相关 | OS×平台绕过测试；无 hook 平台只标 audit-only |
| 多 Agent 委托 | 单 Edge/Agent 绑定 | 后续可行 | AgentInstance、RuntimeBinding、签名委托和范围约束 |
| 评估体系 | Python/Go oracle、威胁语料 | 直接增强 | AMR/RNR、直接/间接 ASR、OOD 和版本基线 |

### O1：provenance.v1（P0）

新增版本化 provenance 合同，admission、manifest、grant、evidence 和企业导入只引用摘要和 ID。验证来源、发布指纹、版本和依赖漂移；旧签名或撤销发布者拒绝；历史 provenance 只追加。

### O2：轨迹级决策上下文（P0/P1）

在 Edge receipt 和执行账本中增加 task、tool、资源类别、前置观察摘要、副作用类别、策略版本和时间窗口的有界摘要；原始参数不进入审计。支持隐藏触发器轨迹回放，最终 action 仍由规则/策略决定。

### O3：资源劫持防护（P0/P1）

将 grant 扩展为执行次数、运行时间、session、CPU/内存/存储、token/费用、网络字节和审批次数预算。耗尽时拒绝新动作并审计；重试和委托不能绕过主体/租户预算。

### O4：工具与记忆信息流标签（P1）

为 candidate、evidence、tool output、memory、receipt 增加有限敏感度和来源标签，采用保守 join；降级生成新派生证据并需要受控批准。标签缺失显示 unknown，不默认 public。

### O5：Connector 完全中介（P1）

统一 scope、timeout、预算、子进程身份、返回摘要和副作用声明。Linux 先实测低权限用户、进程组、namespace/seccomp；Windows Job Object；macOS sandbox profile。无能力的平台只生成审计证据。

### O6：多 Agent 委托（P2）

增加 AgentInstance、RuntimeBinding 和委托 envelope，绑定 tenant、父任务、资源、有效期和 nonce；跨 Agent 消息签名，子 Agent 不得扩大父委托。

### O7：研究型评估基线（P1/P2）

建立正常误拦截 AMR、风险不拒绝 RNR、直接/资源劫持 ASR、域内/域外、单调用/轨迹级、工具返回/记忆注入基线。每个数字绑定 commit、规则版本、OS、语料摘要和命令；论文指标仅作外部参考。

## 4. 排期

| 阶段 | 时间 | 任务 | 退出条件 |
| --- | --- | --- | --- |
| P0 合同止血 | 第 1 周 | O1、O2 最小字段、DEV03/DEV10 收尾 | 固定向量、双读、敏感出口检查通过 |
| P1 运行时资源 | 第 2—4 周 | O2/O3/O5/O7 | Hermes/OpenClaw/CodeBuddy 有正负样本和预算拒绝证据 |
| P2 信息流企业 | 第 5—7 周 | O4、真实 PG、OIDC、O6 | 身份、租户、outbox、导出闭环 |
| P3 真实验收 | 第 8—10 周 | OS/平台、OpenShell L3、OOD、独立复核 | 所有承诺可回链；未测能力明确标记 |

## 5. 风险和不采纳项

- 轨迹摘要可能形成侧信道：默认 digest、类别、计数和限长脱敏摘要；必要时退回 digest-only。
- IFC 标签可能爆炸：首版仅有限标签和保守 join，不实现逐 token 或模型机制解释。
- 多 Agent 委托依赖身份事实稳定，本地模式继续单用户边界。
- 不以增加规则数量代替行为验证，不引入模型自动审批。
- 真实 PostgreSQL、OIDC、OS 隔离、OpenShell 行为和独立安全复核不受源码单测替代。

## 6. 立即执行清单

1. 冻结 provenance.v1 和轨迹摘要字段，生成 Python/Go 固定向量。
2. 将最小轨迹摘要接入 Edge execution ledger 和 receipt，增加一正一负轨迹测试。
3. 将 token、时间、session 和网络字节预算接入 task lease，覆盖耗尽、重试和跨主体负向。
4. 为 Connector contract 增加 scope、timeout、side-effect 字段并逐适配器迁移。
5. 创建 AMR/RNR/直接与间接 ASR 基线工具，不预填未经测量的 SLA。
6. 在真实 PG、OIDC、OS 隔离和 OpenShell 环境就绪后执行 P2/P3。

**当前结论：** O1—O5 可在现有仓库继续开发；O6 和真实 O5 验收依赖外部环境；概率性 TCB、通用 IFC 和未知攻击泛化仍是研究风险，不能宣称本项目已经解决。
