# DGX Spark · Secure Research & Delivery

用户交给 Agent 一个任务：分析选定仓库代码，写出安全审查报告，交付给 Alice。
Agent 实际调用 `secure-research`、`secure-report` 和 `secure-delivery`；SIQ
在每次工具动作前验证授权与参数来源，并通过文件观察器和受控接收端事件验证效果。

当前按用户指示以 **Step Plan / step-3.7-flash** 为主模型，接口为
`https://api.stepfun.com/step_plan/v1`。本机 **Ornith-1.5-35B-A3B-NVFP4**
作为显式备用模型。配置说明见 [Step Plan 接入](docs/hackathon/step-plan.md)。

## 启动与演示

在仓库根目录运行，需 Python、npm、Go 和已配置的 StepFun 接入：

```bash
./scripts/hackathon/start.sh
./scripts/hackathon/healthcheck.sh
```

启动脚本构建现有本地 Web 和 Go 二进制，默认使用 StepFun，创建
`.tmp/hackathon-profile/current/` 独立状态。浏览器地址默认为
`http://127.0.0.1:47621/demo`，使用本次启动输出的配对码连接。
配对码单次有效、五分钟过期；会话只放在 HttpOnly / SameSite=Strict cookie。
仅监听 loopback，浏览器页面不持有 SIQ 管理、决策或观察器凭据。

配对码过期、已使用或换浏览器时，在本机运行
`./scripts/hackathon/pair.sh` 获取新的五分钟单次配对码。无需重启；任务历史、
已有浏览器会话和 SIQ 授权均保留。

页面展示当前任务、受信 Intent、动作时间线和效果/完成状态。可选择正常交付、
MCP 收件人注入、同值不同来源、工具伪成功、交付内容冲突、人工审批和机密数据状态拦截。

收件人动作会直接展示 SIQ 读回的来源类型、信任级别、摘要和任务/会话范围。
同值 MCP 场景会显示“值与受信联系人相同”，同时保留真实的来源拒绝裁决。
也可通过脚本提交：

```bash
./scripts/hackathon/demo-normal.sh
./scripts/hackathon/demo-mcp-attack.sh
./scripts/hackathon/demo-provenance.sh
./scripts/hackathon/demo-fake-success.sh
./scripts/hackathon/demo-approval.sh
./scripts/hackathon/demo-trifecta.sh
./scripts/hackathon/stop.sh
./scripts/hackathon/reset.sh
```

提交脚本返回任务 ID，后续状态在页面读取。服务一次运行一个任务；提交使用
幂等请求 ID。`reset` 先停止本配置管理的服务，校验 PID 与进程启动时间，再把
当前状态移入独立 profile 下的审计归档，新启动得到干净的任务/消息/授权状态。
它不删除个人 SIQ 状态，也不移除已有审计文件。已有 current 时 start 显式拒绝复用。

审批场景在报告生成后暂停。页面展示待启动的报告校验进程、原报告路径、参数摘要
和到期时间，操作员可批准或拒绝。批准后仍须 SIQ 重查，约 60 秒未处理则过期。
该进程使用固定程序读取并核对报告，不接受任意 shell 代码。

`start.sh --mode test` 明确选择 FixtureProvider，适合可重复故障验证；页面会标明
“测试模型 · 无真实推理”。真实模型是否选择恶意 MCP 候选由实际推理决定，不能把
测试模型强制选择的攻击路径当成 ornith 的攻击成功率。

配置与验证命令见 [DGX 部署说明](deploy/dgx-spark/README.md)和
[Secure Agent README](apps/secure-agent/README.md)。

比赛材料：[架构](docs/hackathon/architecture.md)、[五分钟讲稿](docs/hackathon/demo-script.md)、
[提交清单](docs/hackathon/submission-checklist.md)、[能力边界](docs/hackathon/limitations.md)。

## 当前证据与边界

- [最新 ornith 配置与验证](docs/hackathon/structured-model-output.md)：JSON Schema 约束、直接输出，最新五项任务 5/5 完成；之前失败样本分别保留。
- [真实 GitHub 任务](docs/hackathon/live-source-validation.md)：选定源码读取、报告与受控投递完成，22 条签名回执、两项效果读回。
- [仓库回归](docs/hackathon/repository-regression.md)：649 项 Control API 测试、79 项 Agent 测试及本地构建、审计、迁移检查。
- [StepFun 最新效用样本](docs/hackathon/step-plan.md)：低推理强度配置下 5/5 完成，之前超时样本保留。
- [Lethal Trifecta](docs/hackathon/lethal-trifecta-demo.md)：真实 StepFun 准备任务，同一执行会话内读取机密样例、接收网页响应、拒绝后续出网；签名链已验证。

- [ornith 真实任务](docs/hackathon/evidence/ornith-agent-20260908.json)：三次实际模型调用，约 30.3 秒，SIQ report/delivery 均 verified，附真实报告、签名回执和效果读回。
- [浏览器七场景](docs/hackathon/evidence/browser-trifecta-final-20260908/result.json)：同一测试服务连续执行，含状态拦截、审批、页面错误、移动端布局与凭据存储检查，截图在同目录。
- [环境检查](docs/hackathon/evidence/dgx-spark/ornith-environment-20260908.json)：真实 DGX Spark / GB10，模型及四类服务可达。
- [DGX 性能报告](docs/hackathon/dgx-performance-report.md)：真实 ornith/Agent 耗时与 SIQ 内核阶段分别列出 P50/P95/P99。
- [来源展示与重新配对](docs/hackathon/demo-evidence-contract.md)：SIQ 来源断言读回、同值不同来源和会话保留验证。

默认演示的源仓库、通讯录、MCP 和交付接收端是受控 fixtures；主模型是真实 StepFun，ornith 为备用。
不发送外部邮件。Completion 验证已承诺的文件/HTTP 字节，不能证明模型审查结论
正确，也不能当成通用 SaaS 效果验证。同机测试 oracle 不是独立管理的生产证明；
内置 Python Skill 的工具边界不是 OS 沙箱。

人工审批链路已有[六种实际 SIQ 验证](docs/hackathon/approval-integration.md)，真实 ornith
审批任务已有成功与失败记录，均保留证据。[任务基准](docs/hackathon/benchmark-report.md)
已完成 23 项固定提案对照；StepFun 与 ornith 最新独立小样本均完成 5/5，之前 4/5 的失败记录保留。
小样本不代表普遍模型稳定性。[最终工程报告](docs/hackathon/final-engineering-report.md)记录全部本地验收；
[候选包](docs/hackathon/rc-preparation.md)为已实际启动验证的本地未签名准备件，不是正式发布。完整目标与逐项状态见
[Master Plan V3](docs/hackathon/master-plan-v3.md)和[开发台账](docs/hackathon/progress.md)。
