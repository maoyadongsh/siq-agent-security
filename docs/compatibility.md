# 兼容矩阵（Phase 0 基线）

> 设计文档 §15.1/§16 要求：固定版本、能力协商、不按版本号假设。D1 spike 完成后用实测数据替换本文"待探测"项。

## OpenShell 兼容矩阵（首个 Enforcement Adapter）

| 能力 | v0.0.83（SIQ 冻结） | 最新版（待 D1 spike 实测） |
| --- | --- | --- |
| Gateway 控制面 / Sandbox 生命周期 | ✅ 已实现（research-engine） | 待探测 |
| filesystem_policy 静态边界 | ✅ 编译期锁定，重建生效 | 待探测 |
| Landlock | ✅ 带本地 patch（mask-file-access） | 待探测（rebase 后回归） |
| process / seccomp 静态边界 | ✅ | 待探测 |
| **network_policies 动态更新** | ✅ **实测支持**（2026-08-13：活沙箱 `policy set` 网络段 → version 2 提交成功并读回生效；静态段修改被拒绝）。SIQ 自研编译器的固定规则限制 ≠ 网关能力限制 | ✅ 已探测 |
| Provider 凭据隔离 | ✅ credential placeholder + 网关注入 | 待探测（Providers v2 动态能力） |
| Gateway Interceptor | ❓ v0.0.83 上未使用/未验证 | 待探测 |
| revision / 有效策略回读 | ✅ | 待探测 |

**MVP 影响（实测修正）**：动态网络策略发布**在 v0.0.83 上即可实现**（policy set + revision 读回）；§29.1 降级条款保留为风险预案。已知问题：网关 SandboxResponse 的 Protobuf 解码错误（list/create/get 响应），policy 类命令不受影响，升级 v0.0.104 预期修复。

## 本地 patch 清单（ADR-005）

| patch | 目标 | 上游状态 |
| --- | --- | --- |
| 0001-landlock-mask-file-access | OpenShell v0.0.83 | 待上游化评估 |
| 0002-siq-strict-bind-mount-contract | OpenShell v0.0.83 | 待上游化评估 |
| 0001-runtime-auth-file-override | Hermes 0.13.0 | 待上游化评估 |
| 0002-runtime-state-home-override | Hermes 0.13.0 | 待上游化评估 |
| 0003-api-run-stop-quiescence | Hermes 0.13.0 | 待上游化评估 |

## Hermes 现实边界（L1-L3 评级依据，ADR 结论同步自设计文档 v0.2 §16.3）

| 项 | 现实 | 评级影响 |
| --- | --- | --- |
| Profile | 数据目录（config.yaml/SOUL.md + 状态），无权限声明 | L1 发现合同按"profile 目录 + 全局 platform_toolsets + Hub sandbox 字段"三源合一设计 |
| Runs API | 内存态（60s TTL），无持久台账 | L2 可观测性按 Hub RunLedger 现状下调 |
| 审批门 | cooperative-mode 启发式，非安全边界 | 只作为 observed 证据 |
| 运行形态 | SIQ 生产中为 hub 容器内子进程 | Agent Instance 模型含 embedded 运行时 |

## OpenShell Enforcement Adapter 合同状态（Phase 3 前置，2026-08-13）

- 合同类型与十方法（§15.3）：`apps/control-api/app/adapters/openshell/`（contracts/base/policy_compiler/fake_backend/client）
- FakeBackend 契约测试 9 项：能力探测/revision 冲突/静态 generation/正负验证/回滚/unsupported 显式标记
- 真实 client fail-closed 占位：D1（版本路径）+ D2（SIQ 基座部署）后接入
- 部署流已接线：`SIQ_AS_ENFORCEMENT_BACKEND=fake` 时编译制品入任务 payload，未知语义 422 拒绝

## Connector 兼容

| Connector | 状态 | 负向测试 |
| --- | --- | --- |
| hermes（Go） | 已实现（build/vet/test 全绿） | scope 校验/符号链接逃逸/.env 拒绝/截断 |
| docker（Go） | 已实现（build/vet 通过，测试待补） | 环境变量值不出机（struct 无 Env 字段） |
| kubernetes | 待 Phase 4 | — |
| siq | 待 Phase 1（依赖 Export Contract D3-D5） | — |
