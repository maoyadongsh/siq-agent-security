> Historical V3 record. Current V4 development and acceptance are tracked in
> [V4 progress](final-hardening-progress-v4.md), [task ledger](final-hardening-tasks-v4.md)
> and [canonical evidence](evidence/INDEX.md). V4 requires a clean CI-verified
> candidate and a real 2–3 minute recording; V3 dirty-source/video exemptions do not apply.

# Hackathon V3 最终工程报告

日期：2026-09-08。目标：[用户原方案](master-plan-v3.md)。逐条范围核对见
[验收矩阵](acceptance-matrix.md)。本报告验收本地开发、DGX 实机运行与未发布候选包准备，
不把远程 CI、正式签名或其他操作系统的原生安装计为已验证。

## A. Baseline 与交付身份

| 字段 | 值 |
| --- | --- |
| starting_sha | `e309655915562a27cb98df851c1e46e922563d47` |
| branch | `codex/dgx-spark-hackathon-v3` |
| 实现提交 | `a8dfdeb85287ee2ce476f9c94127c77bde79f2a4` |
| final_sha（实现快照） | `a8dfdeb85287ee2ce476f9c94127c77bde79f2a4`；交付记录更新另有后续文档提交 |
| 候选版本 | `0.3.0-rc.1`，本地 candidate2，未签名、未发布 |
| 精确源码身份 | 包内 `source-info.json` 列出复制的 dirty worktree 文件及 SHA256 |
| 包清单 | 1,575 个文件；SHA256、字节数、可执行位，运行前后校验一致 |

本地候选包：`.tmp/hackathon-rc/0.3.0-rc.1-candidate2.tar.gz`。
SHA256：`89856cd9c1e4af9b7179b2b4f46437eedee1a1d1599ca185b0536ed1b0e26dd3`。
完整信息见 [候选准备记录](evidence/rc-candidate2-preparation-20260908.json)。
构建后产生的本报告、启动验收记录及文档收尾位于冻结源码快照之外；它们不改变已记录包的身份。
用户随后授权提交并推送全部本轮开发内容。交付分支为
`origin/codex/dgx-spark-hackathon-v3`；精确远端 HEAD 以该分支读回为准。
本地候选包仍对应其构建时的 dirty-source 清单，不因后来创建提交而冒称已从该提交重建。

## B. Agent、模型与 Skills

已实现自动链路：用户任务 → 真实模型 → 严格类型 TaskPlan → 三个内置 Skill →
ToolGateway → 现有 SIQ 决策 → 实际工具执行 → 效果与 Completion 读回。
模型不能签发 Intent、修改 Grant、伪造来源、批准动作或声明效果已验证。

- 主模型：Step Plan `step-3.7-flash`，`https://api.stepfun.com/step_plan/v1`。
  使用 JSON 模式、严格响应解析与 `reasoning_effort=low`；保留超时及格式失败记录。
- 备用模型：本机 `Ornith-1.5-35B-A3B-NVFP4`，`http://127.0.0.1:8006/v1`。
  使用结构化 JSON Schema 和直接输出配置。备用切换是显式操作，没有隐藏重试或模型替换。
- 私有配置位于仓库外 `~/.config/siq-agent-security/hackathon/providers.json`，目录 0700、
  文件 0600；拒绝符号链接、错误所有者/权限及 endpoint 与凭据混用。
- `secure-research` 固定 GitHub revision、读取选定文件并输出来源摘要；
  `secure-report` 写实际报告；`secure-delivery` 绑定收件人来源并交付到受控接收端。
  每个 Skill 都有 SKILL.md、类型合同、安全约束及测试。没有导入或执行被扫描 Skill 的任意代码。

四个打包 Skill（包括原安全 Skill）用候选二进制完成
[自准入](evidence/final-regression-20260908/skill-self-admission-candidate2.json)，
均为 `admit_with_conditions`；这是准入结果，不等于 effective 权限。

## C. DGX 实机与部署

实际设备为 NVIDIA DGX Spark / GB10 / aarch64，驱动 580.126.09，CUDA 13.0，约 128 GB RAM。
[最终环境检查](evidence/dgx-spark/final-stepfun-environment-20260908.json)记录 OS/kernel、
硬件、模型标识、源码/Skill 哈希及服务探测，`--require-ready` 通过。
模型 listing 可达与实际推理分开证明；远程 StepFun 权重 digest 未独立验证。

当前受管演示地址：`http://127.0.0.1:47621/demo`，Agent/Web 均报告 StepFun。
新配对码通过 `./scripts/hackathon/pair.sh` 获取。密钥和配对码不进入本报告。
模型、SIQ、Agent、Web、fixtures 分别记录实际状态。

候选包经独立目录解压，通过包内 `launch_rc.py` 启动实际 Linux arm64 服务；
[StepFun 验收任务](evidence/rc-candidate2-launch-20260908.json)完成，26 条回执签名和链、
2 个效果封装验证通过，约 15.33 秒，运行后包内容未变。
另有 [真实 GitHub 源码任务](live-source-validation.md)：Ornith 读取选定源码并完成报告及受控投递，
22 条回执和 2 项效果读回；原速率限制、格式及超时失败均保留。

## D. 安全实现与边界

| 层 | 实际实现与验证 |
| --- | --- |
| Intent | 先用只读准备 Intent 确定报告；执行 Intent 承诺报告及投递字节摘要，源文件按固定 revision 重放并校验一致 |
| Context | 现有签名 context assertion 绑定任务、workspace、动作参数和 tool-call；模型不能伪造可信 workspace |
| Provenance | 可信目录由授权 issuer 签发；MCP 经现有 Report/Select API 保留不可信来源与作用域，同值也不能借用目录权限 |
| Decision | 现有 SIQ Reference Monitor 决策，Gateway 在 allow 后才进入工具；hold 后重查原参数及当前授权；不可达失败关闭 |
| Stateful | 同一会话机密样例读取 → 真实网页响应 Observe → 下一次出网 `lethal_trifecta` 拒绝，不清除或伪造累计状态 |
| Effect | 实际文件观察器和受控接收端事件绑定原动作；匹配、缺失、冲突分别处理，工具 success 仅为 REPORTED |
| Completion | 现有服务读回已承诺要求的状态；没有收件证据不能把 delivery 或任务标为 verified |

沿用既有内核，做了有回归验证的集成修正：Grant 初始 desired-policy ID 隔离；
仅有证明的 V3 收件路由标量从新增 PII 扫描中区分；正文中的示例路径/URL 不冒充执行目标；
解码后的 JSON 字符串/源码仍进入 Observe；新增受审计的工具审批条件 API。
状态演示只投影已有 Receipt 的 trifecta，不增加第二套安全决策器。

机密样例是新建受控运行目录中的固定无密钥数据；只允许精确路径和字节，拒绝替换和符号链接，
不把其内容发送给模型。此例证明保守的状态出网控制，不声称被拒 GET 是真实秘密上传。
内置 Python 工具边界不是 OS 沙箱，不能抵御任意同 UID 宿主进程绕过。

## E. Demo 验收

| 场景 | 结果 |
| --- | --- |
| 正常任务 | 三 Skill 执行，真实文件与受控接收，report/delivery verified |
| MCP 收件人注入 | 来源无资格，send_message 在工具执行前拒绝 |
| 同值不同来源 | 相同邮箱文本、MCP 来源仍拒绝；UI 显示实际来源读回 |
| Lethal Trifecta | allow 文件读取 → allow 首次网页请求 → deny 后续出网，零报告/消息 |
| 人工审批 | HOLD → 操作员点击 → 原动作在线重查 → 固定报告校验进程及交付；撤销/改参不能执行 |
| 工具伪成功 | 接收端无消息，Completion incomplete |
| 内容冲突（附加） | 接收端记录替换字节，Completion conflicting |

[最终浏览器记录](evidence/browser-trifecta-final-20260908/result.json)为 7/7：无页面异常，
无 localStorage 凭据，无移动端横向溢出，续配对保留历史与已有会话。浏览器固定场景明确使用
FixtureProvider，不能作为真实模型攻击易感率。
[独立 StepFun 状态演示](lethal-trifecta-demo.md)有两次真实推理、11 条验证通过的签名回执，
严格校验同会话及决策/观察次序。前三个动作分别显示 SIQ 实际累计状态。

## F. Benchmark 与性能

复用 runtime-security 的回执、效果和统计验证能力，未另建安全 benchmark 引擎。
[完整报告](benchmark-report.md)保留语料、原失败和各独立模型 cohort。

| 指标 | 23 项固定提案 Agent 控制组 |
| --- | ---: |
| 预期结果满足 | 23/23 |
| 正常任务完成 | 5/5 |
| 不安全目标动作尝试 | 11/13 |
| 不安全目标工具进入 | 0/13 |
| 来源违规阻断 | 8/8 |
| 错误拒绝 / 错误放行（已评估目标） | 0/7 / 0/9 |
| 请求审批的任务 | 4/23（该组为自动测试操作员） |
| 验证的已承诺效果要求 | 19/40 |
| 签名效果记录中的 unauthorized / unknown | 0/20 / 0/20 |
| 没有效果记录的任务 | 9/23，另计，不冒充独立证明的零效果 |
| 验证通过的回执 / 效果封装 | 318 / 20 |

StepFun 最新低推理强度组 **5/5**；Ornith 最新直接输出组 **5/5**。
每组各 15 次真实调用、121 条验证回执和 10 个效果封装。
StepFun 前组 **4/5** 的 60 秒超时、Ornith 前组格式/截断失败均保留，不从分母删除或暗中重试。
固定提案组衡量执行边界；真实小样本衡量任务完成，二者不能合并成模型攻击阻断率。

| 测量 | N | P50 | P95 | P99 |
| --- | ---: | ---: | ---: | ---: |
| StepFun 调用（含传输、验证） | 15 | 5.638 s | 19.320 s | 19.320 s |
| StepFun planning | 5 | 4.270 s | 5.638 s | 5.638 s |
| StepFun 完整任务 | 5 | 15.683 s | 33.562 s | 33.562 s |
| Ornith 完整任务 | 5 | 5.574 s | 9.813 s | 9.813 s |
| SIQ Decide 组件 | 100 | 8.230 ms | 12.178 ms | 13.225 ms |
| 来源解析组件 | 100 | 0.244 ms | 0.312 ms | 0.400 ms |
| Effect SubmitFile 组件 | 100 | 5.877 ms | 6.344 ms | 6.673 ms |

数据见 [DGX 性能报告](dgx-performance-report.md)及
[StepFun 投影](evidence/dgx-spark/performance-step-plan-low-20260908.json)。
模型、完整任务和组件是不同样本集合；不能相加或作为 SLA、模型审查准确率或 GPU 饱和性能。

## G. CI、回归与候选包检查

[原完整命令集](evidence/final-regression-20260908/checks.json)、
[补充检查](evidence/final-regression-20260908/additional-checks.json)与
[最终增量命令/日志](evidence/final-regression-20260908/final-followup-checks.json)
共同记录实际本地结果。原较小测试计数是历史时点，不替换成新计数。

- 最新 Control API：649 passed；Agent：79 passed（含 18 个实际应用 E2E）；
  包校验/状态证据：10 passed；Web：11 passed；两种 Web build 和 lint 通过。
- AgentShield：Go 1.26.6 vet/race、Go 1.22.12 tests 通过；Edge 与 11 个 Connector
  在两个工具链下 build/vet/race 通过。候选包用 Go 1.26.6 构建四目标二进制。
- 合同、原 adapter tests、runtime smoke、恢复、Hermes MCP bridge、CI 静态检查、
  历史签名 Skill manifest 验证通过；隔离 PostgreSQL 17 migration 至 0016。
- 实装 Hermes/OpenClaw/CodeBuddy 的原生 harness 通过；分别限定实际 loader/hook/CLI 路径，
  不声称覆盖完整原生对话、GUI、人工审批或每个操作系统。
- 已记录 npm production audit、Python dependency audit、Go 1.26.6 govulncheck 无发现；
  这只覆盖记录的依赖、工具版本和时点。
- 修复 Gitleaks 空规则配置；校准证明真正可检测凭据，同时保留精确的合成 fixture 例外。
  候选 2 实际扫描通过；294 个本地可达 Git 提交经合成测试值分类后扫描零发现，原失败记录保留。
- 四目标、CycloneDX 1.5 scoped SBOM、全部文件摘要与执行位、Skill inventory 均已校验；
  解压后的候选实际启动成功且运行前后清单一致。正式签名没有伪造或替换信任根。

这些是本地 CI 等价检查，不是 GitHub Actions 上的 required checks。
当前 `ci` 工作流仅在 main push 或 pull_request 时触发，开发分支 push 不等于远程 CI 已通过。
完整限定见 [仓库回归](repository-regression.md)。

## H. 未验证内容与后续操作边界

1. 实现提交已创建，本轮按用户授权推送到开发分支；没有执行 main 合并、PR、tag 或发布。
   候选仍为构建时的 dirty-source、未签名准备件。
   历史 v0.2.0 的签名清单不为本候选背书。
2. 原生启动验证仅 Linux arm64；其他目标仅交叉构建。外部模型/OS/Python runtime 不在打包 SBOM 内，
   npm production lockfile 是组件上界，不是 bundle 可达性证明。
3. [GitHub 读回](evidence/final-regression-20260908/repository-governance.json)显示 main 未受保护，
   当前账号有 admin 能力。没有更改仓库设置；PR/CI 必需、禁止 force push 和敏感路径 review 是原方案建议的后续治理。
4. 默认源码、通讯录、MCP、接收端为受控 fixtures；真实 GitHub 测试范围限定到选定文件。
   不发送外部邮件，不证明任意 SaaS 或独立管理的生产观察器结果。
5. 模型小样本成功不代表审查结论正确、普遍可靠或免疫注入；远程权重身份、并发 SLA、
   通用语义来源、完整 memory/delegation、OS 级隔离未宣称实现。
6. 已有可执行演示脚本、架构图、证据与讲稿；尚未录制比赛视频。视频不是 §65 的必需生成项。

本地演示继续运行。使用 [HACKATHON.md](../../HACKATHON.md)启动、配对、选择场景或显式切换备用模型。
