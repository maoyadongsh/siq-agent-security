# AgentShield：本地授权与效果证据运行时

此 Go 模块构建 `siq-agent-security`。它在宿主工具调用前检查独立授权，在调用后关联签名回执和效果证据，并提供本机浏览器控制台。个人模式无需企业数据库、远端控制面或模型服务；模型与适配器均不持有签名私钥。

[使用手册](../../AGENTSHIELD.md) · [开发规格](../../docs/agentshield-dev-spec-v1.md) · [版本化合同](../../packages/contracts/README.md) · [平台矩阵](../../platforms/support-matrix.md)

## 核心链路

```text
候选 Skill → 静态准入 / 内容摘要 → 人工确认 Grant
宿主实例 + 原生会话 → Runtime Identity / Intent Binding
工具调用 + 参数来源 → Authority 与资源复验 → allow / deny / hold / redact
hold 获批 → 最终参数复验 → 持久签名预留 → 单次执行尝试
调用后观察 → 签名动作链 → 独立效果材料 → Completion
```

研究价值在于把“可做什么”“参数为何可信”“实际做了什么”分别建模并绑定，而不是只分析输入文本。来源约束检查同值参数背后的声明与派生关系；SEC 将 Skill 归属绑定到已验证安装、实例、会话和任务；审批后预留处理撤权、并发重试和崩溃窗口。上述机制都有明确的信任前提，尚不提供任意模型推理的语义来源证明。

## 源码地图

| 代码 | 负责什么 | 关键约束 |
| --- | --- | --- |
| [inventory](internal/inventory/)、[admission](internal/admission/)、[threat](internal/threat/) | 盘点、静态准入与能力提取 | 不执行被扫描内容；声明能力不自动变成生效权限 |
| [grant](internal/grant/)、[provenance](internal/provenance/) | 权限编译、来源声明和图验证 | 人工批准；来源与作用域、内容摘要相符；不信任工具自称 USER |
| [skillcontext](internal/skillcontext/) | Skill Execution Context 签发、复验、撤销 | 名称或路径不能独自证明 Skill 归属，决策时复验安装与授权 |
| [receipt](internal/receipt/)、[server](internal/server/) | 决策、审批预留、HTTP 权限分离与签名链 | 无效必需 Authority 始终拒绝；已预留而无结果只能记 uncertain |
| [completion](internal/completion/) | 按任务要求核对实际效果 | 工具成功、观察记录和完成结论分层；证据不足不能升级为完成 |
| [statefs](internal/statefs/)、[privatefs](internal/privatefs/) | 私密状态、兼容屏障与文件发布 | 保留历史和未知用户对象；跨 OS 语义由专属实现与测试约束 |
| [adapterinstall](internal/adapterinstall/)、[openshell](internal/openshell/) | 宿主接入事务与执行后端协调 | 安装、加载、策略读回、实际拦截分别验证 |
| [ui](internal/ui/README.md)、[命令入口](cmd/agentshield/) | 本地 UI 嵌入与 CLI | UI 只展示/请求服务端操作，不决定权限或效果真实性 |

批准不等于执行。预留写入后响应丢失或进程中断，不自动重放外部副作用；人工结案只追加事实，不重启旧预留，也不承诺 exactly-once。普通策略的 warn/audit_only 建议语义不能放宽必需 Authority。

## 从源码构建与检查

在仓库根目录执行，工具链按 [go.mod](go.mod) 与 CI 固定版本选择：

```bash
mkdir -p .tmp/bin
go -C apps/agentshield build -o "$PWD/.tmp/bin/siq-agent-security" ./cmd/agentshield
go -C apps/agentshield vet ./...
go -C apps/agentshield test ./...
```

现有 UI 资产随源码提供；修改 Web 后须先按 [Web 构建说明](../web/README.md)运行本地构建、复核嵌入资产，再构建 Go。仅运行 Go 测试不验证新 Web 源码。当前源码个人端默认进入 `/agents`，可通过 SIQ Skill 辅助确认浏览器连接，也保留手动配对；连接请求有效 5 分钟，管理会话固定 24 小时且刷新不续期。管理会话只允许操作本地控制台，不授予智能体业务权限。开发启动、配对和独立状态目录按[本机操作指南](../../AGENTSHIELD.md)操作，不复用日常实例做破坏性实验。

`skills/siq-agent-security/` 是开发源码，缺少发行清单时 bootstrap 拒绝启动。从源码构建成功不产生官方发行身份；正式安装使用[签名资产](../../docs/signed-release-packaging.md)。

## 验证与适用范围

共享合同由 Go 输出、Python schema 校验及规范化/签名固定向量交叉验证；运行时对照见 [runtime-security](../../benchmarks/runtime-security/README.md)，端到端研究应用见 [Secure Agent](../secure-agent/README.md)。[四目标源码检查](../../docs/evidence/repository-reorganization-final-20260919/README.md)覆盖隔离构建与基础启动，不覆盖所有系统服务和宿主旅程。

工具钩子只保护已接入路径；同用户恶意进程、宿主绕过、观察器可信度和原文采集授权有各自边界。Linux 当前接入 OpenClaw/Hermes，macOS/Windows 接入范围另含 WorkBuddy；实现存在、组件测试和正式版原生验收分别见[平台入口](../../platforms/README.md)。
