# R05 Linux 宿主能力只读核验

核验时间：2026-09-14T20:02:18+08:00  
工作树：`kimi/personal-v4-r01-20260914`  
基线提交：`b303c6f92392f3a44c306d81ad7323c6291ef4f2`  
候选二进制 SHA256：`5ed4dc82bbb300b94155561f91322b818c32b8cc42109e068258162f42d8b961`

## 结论

本机是 Linux/aarch64，已安装 OpenClaw 与 Hermes CLI，并存在 SIQ 适配器文件；WorkBuddy CLI 和默认配置根均不存在。OpenShell CLI 存在，但所选 `nemoclaw` 网关当前拒绝连接，身份未验证，只能报告 L0。此次只读核验没有改写宿主配置、启动网关或模型，也没有执行任何宿主工具调用。

这些结果足以确认本机下一批可继续 OpenClaw/Hermes 原生接入验证，并明确 WorkBuddy 与 OpenShell 的阻断条件；不能据此声称宿主已经加载插件、工具调用已经受控、审批可以原生恢复，或 WorkBuddy 已受支持。R05/N04 保持 partial。

后续 [R04-C 最终本地候选复验](../r04c-final-candidate-integration-20260914/report.md)已经用真实 Hermes CLI 在隔离 `work` profile 完成插件配置启用、诊断和卸载读回，并确认默认 profile、未知文件及用户后续配置不受影响。该增量仍没有模型或工具调用，只把 Hermes 从“文件存在”推进到“隔离 profile 原生配置已验证”，运行时接入继续 partial。

[R05-B OpenClaw 运行时加载核验](../r05b-openclaw-runtime-load-20260914/report.md)随后用真实 OpenClaw `plugins inspect --runtime` 在隔离 HOME 成功导入并加载 SIQ 的 `before_tool_call`/`after_tool_call`，卸载读回也保留无关配置。这把 OpenClaw 推进到“真实宿主加载钩子”；没有 agent turn 或工具调用，最终限制能力仍未验。

最终以 SHA256 `f4b5c23c…7420c` 的同一候选完成 [R05-C 双宿主合同核验](../r05c-final-host-runtime-contract-20260914/report.md)：OpenClaw 运行时加载两个钩子，Hermes Plugin Doctor 对候选实际安装资产完成无警告导入和注册，二者卸载均保留所测无关配置。

## 主机与候选

| 项目 | 实际结果 | 能证明什么 |
| --- | --- | --- |
| 系统 | Linux `6.17.0-1014-nvidia`，`aarch64` | 当前核验主机与 CPU 架构 |
| 工作树基线 | HEAD、merge-base 与 `origin/main` 均为 `b303c6f…ef4f2` | 本工作树从当时主线分出；未提交改动另行存在 |
| 候选 | `/tmp/siq-r04-candidate/siq-agent-security`，SHA256 如上 | 本次命令使用的固定本地候选；不是发布制品 |

## 平台能力

### OpenClaw

- CLI：`/home/maoyd/.local/bin/openclaw`
- 版本：`OpenClaw 2026.5.12 (f066dd2)`
- 配置根：`~/.openclaw`，普通目录，模式 `0775`，不是符号链接。
- `adapter status openclaw`：发现 `~/.openclaw/plugins/agentshield`，状态 `installed`。
- 解释边界：只证明适配器入口文件存在。仍需在隔离 profile 中证明宿主实际加载、可信会话/调用上下文、允许与拒绝的工具副作用及重启失联行为。

### Hermes

- CLI：`/home/maoyd/.local/bin/hermes`
- 版本：`Hermes Agent v0.21.0 (2026.8.31)`；安装目录 `/home/maoyd/siq/hermes-agent`；Python `3.11.15`；OpenAI SDK `2.24.0`。
- 配置根：`~/.hermes`，普通目录，模式 `0700`，不是符号链接。
- `adapter status hermes`：发现 `~/.hermes/plugins/agentshield`，状态 `installed`。
- 解释边界：只证明适配器入口文件存在。R01/R02 已有服务级与组件证据，但仍需在 Hermes 原生插件进程中完成真实工具调用、SEC 归属和批准后精确重试验收。

### WorkBuddy

- `PATH` 中没有 `workbuddy` CLI；`~/.workbuddy` 不存在。
- 候选的安装器命令将 `adapter status workbuddy` 拒绝为未知安装平台；诊断层则把 WorkBuddy 明确标记为 `unsupported`、`runtime_state=unverified`，并要求桌面端独立实测。
- 解释边界：本机没有可用于正向原生验收的 WorkBuddy 上游运行时。CodeBuddy/Trae、目录 fixture 或交叉构建均不能替代 WorkBuddy 桌面实测。本格保持 blocked，解除条件是取得真实 WorkBuddy Linux 运行时及可复现工具调用入口；若上游不支持 Linux，应在支持矩阵中明确 OS 限制。

### OpenShell

- CLI：`/home/maoyd/.local/bin/openshell`。
- `openshell doctor` 发现所选网关 `nemoclaw`，但连接被拒绝；`probe_ok=false`、`identity_ok=false`、`tier=L0`。
- 候选没有自动启动或选择网关，`started_gateway=false`。解除条件是由维护者明确启动/选择测试网关后，再验证身份和 L1-L3 能力；本次未执行该外部状态变更。

## 下一原生验收顺序

1. 在隔离 OpenClaw profile 中核对插件实际加载，使用无破坏性的临时文件工具完成允许、拒绝、失联和重启恢复；绑定同一候选与完整调用证据。
2. 在隔离 Hermes profile 中以真实插件进程验证 SEC 不能跨会话、任务、调用或 Skill 复制，并验证批准后的唯一预留与宿主精确重试。
3. OpenShell 只在维护者显式启动测试网关后继续，先验证身份，再逐级记录 L1-L3；不得以 CLI 存在推导沙箱可用。
4. WorkBuddy 保持 blocked，等待真实运行时；不新增猜测式安装器或把 CodeBuddy 结果重命名为 WorkBuddy。

## 安全与诚实边界

- 所有命令均为版本、文件存在性、目录元数据、适配器状态与 OpenShell 诊断读取。
- 没有输出配置内容、令牌、认证头、完整私有 URL、模型输入或模型输出。
- 没有启动模型、网关、daemon 或平台进程，没有发送公网请求。
- 没有修改 `~/.openclaw`、`~/.hermes`、`~/.workbuddy` 或 OpenShell 配置。
- `installed` 不是 `configuration ready`，更不是 `runtime verified` 或 `enforcement verified`。
