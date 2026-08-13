# ADR-010：身份双轨：产品角色与 SIQ IAM 的关系（草案）

- 状态：**草案，待 SIQ IAM 侧评审**
- 日期：2026-08-13
- 对应开发计划决策 #9

## 背景

SIQ 工作区不变量："IAM 是用户、角色、权限、数据范围的唯一权威"（`/home/maoyd/siq/AGENTS.md`）。本产品自带 Tenant/Security Admin 等角色（设计文档 §19.2），在 SIQ 环境部署时若自建平行角色体系，将违反平台不变量。

## 决策方向

1. 产品在 SIQ 环境不使用自建 IdP：OIDC 直接接 SIQ IAM 的 RS256/JWKS；
2. 产品角色不成为权限事实源：向 SIQ IAM 注册产品权限点（如 `agentsecurity:policy:approve`、`agentsecurity:agent:confirm`），由 IAM 完成用户→角色→权限点判定；
3. 产品内置角色表仅用于**非 SIQ 部署**（自托管/Managed）与本地默认策略；
4. 委托维度直接复用 IAM `/auth/delegated-token`（当前 audience 硬编码 `siq-memory`，需泛化——开发计划 D6）。

## 待确认

- IAM 权限点注册流程与命名规范；
- 产品权限点在 SIQ IAM 中的管理归属（哪个团队维护）。

## 后果

- 正：单身份事实源，SIQ 部署合规。
- 负：产品权限点注册是 SIQ 侧跨仓工作，Phase 3 审批流联调依赖其完成。
