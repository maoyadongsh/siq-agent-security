# ADR-009：OpenShell 版本路径与 patch 治理（草案，含 D1 spike 实测）

- 状态：**草案，D1 实测已出阶段性结论，待构建/回归验证后定稿**
- 日期：2026-08-13（spike 实测更新）
- 对应开发计划决策 #5 / #8

## 背景

SIQ 冻结 OpenShell v0.0.83（上游 commit e3d26dd3），带 2 个本地 patch；其网络策略为编译期固定集合，动态更新需升级版本或采用 Providers v2。设计文档 §29.1 已把 MVP 动态网络策略设为版本依赖项。

## D1 spike 实测（2026-08-13，评估器 `siq-research-engine/scripts/openshell/d1_upgrade_eval.sh`）

候选：**v0.0.104**（当前最新 release tag，v0.0.83→v0.0.104 跨越 21 个版本）

| 项 | 实测结果 |
| --- | --- |
| 0001-landlock-mask-file-access.patch | **3/5 hunk 冲突**；但上游 v0.0.104 的 landlock.rs 已内置 access-mask 语义（`Restrict a rule's access mask to rights valid for the opened path type` / `Tailor a rule's access mask to the inode...`，landlock.rs:297-400 区域）——**倾向结论：该 patch 已上游化，可退役，需回归验证 mask 行为与 SIQ 语义等价** |
| 0002-siq-strict-bind-mount-contract.patch | **10/11 + 1/1 hunk 冲突**（crates/openshell-driver-docker/src/lib.rs 与 tests.rs 上游重构，偏移数百行）——需人工 rebase，估计 **1-3 人日**，且需重审 bind-mount 契约在新版 driver 架构中的落点 |

Hermes 3 个 patch（hermes-0.13.0 目录）不受 OpenShell 升级影响（Hermes 版本独立固定 0.13.0），不在本 ADR 范围。

## 待完成项（构建环境）

本机无 Rust/Docker 链，以下步骤由 spike report.json 的命令清单在构建环境执行：
1. 构建 patched gateway/supervisor（Dockerfile.gateway-builder，`--build-arg OPENSHELL_REF=v0.0.104`）；
2. 78 项 control_tests 回归对照（基线 78 passed）；
3. 能力探测：动态网络更新（新增→变更→回读 revision）、Gateway Interceptor 可用性。

## 待选方案（更新）

| 方案 | 成本（实测修正） | 收益 | 风险 |
| --- | --- | --- | --- |
| A. 升级 v0.0.104 | patch2 人工 rebase 1-3 人日 + 回归 + 探测（patch1 大概率退役） | 动态网络策略能力待探测确认；进入上游演进线 | driver-docker 重构面大；动态更新与 Interceptor 能力未经探测 |
| B. 维持 v0.0.83 | 无 | 现状稳定 | MVP 降级为静态 generation 计划；长期漂移 |
| C. 升级 + patch2 上游化 | A + 上游 PR 流程 | 消除全部 Fork 债务 | 上游合并节奏不可控 |

## 阶段性推荐

**倾向方案 A**：patch1 已上游化（删除），实际 rebase 债务只剩 patch2（1-3 人日），成本低于 ADR-009 原估的 2 周门槛。最终决策待构建/回归/能力探测三步完成后定稿（动态网络更新能力的实测结果仍是关键输入——若 v0.0.104 支持，Phase 3 的 MVP 动态策略发布可解锁）。

## 后果

- 定稿后：`apps/control-api` 的 OpenShell client（`adapters/openshell/client.py`）按探测到的能力矩阵实现；
- patch 治理表（ADR-005）同步：0001 → 待退役（回归验证后），0002 → 人工 rebase。
