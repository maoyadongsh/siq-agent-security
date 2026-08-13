# ADR-005：OpenShell Adapter 与不 Fork 原则（含 patch 治理例外）

- 状态：**已采纳（暂行）**
- 日期：2026-08-13

## 决策

- OpenShell 作为首个 Enforcement Adapter，不把长期 Fork 作为默认路线；
- **现实例外**：SIQ 已维护 OpenShell v0.0.83 ×2 + Hermes 0.13.0 ×3 共 5 个本地 patch。每个 patch 必须登记：owner、上游 issue、升级 rebase 步骤；每次 OpenShell 升级 = rebase + 78 项回归重跑 + bind-mount 契约重审；
- 能力一律探测（`probe`）而非版本号假设：v0.0.83 网络策略为编译期固定集合，**动态更新需升级版本或 Providers v2**（对应 MVP 降级条款，设计文档 §29.1）；
- Gateway Interceptor 在 v0.0.83 上未验证，不进 MVP 承诺（§15.4）。

## 后果

- 正：能力矩阵可信，版本风险显式化。
- 负：Phase 3 依赖版本路径决策（开发计划决策 #5）。
