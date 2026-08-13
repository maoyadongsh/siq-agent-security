# D1 Spike：OpenShell 升级评估执行计划

> 对应开发计划 D1（决策 #5 的输入）与 ADR-009（版本路径决策）。
> 状态：执行脚本已交付（`siq-research-engine/scripts/openshell/d1_upgrade_eval.sh`），待执行。

## 目标

回答一个问题：**升级到新版 OpenShell（rebase 5 个本地 patch）的可行性与成本**，从而在 ADR-009 三个方案（A 升级 / B 冻结 / C 升级+上游化）中做出决策。

## 执行步骤

1. **补丁 rebase 评估**（脚本已自动化）：
   ```bash
   # 默认评估最新 release tag；先跑基线自检（应全 applied）
   siq-research-engine/scripts/openshell/d1_upgrade_eval.sh --candidate v0.0.83
   # 真实评估候选版本
   siq-research-engine/scripts/openshell/d1_upgrade_eval.sh --candidate <候选tag>
   ```
   产出 `<out-dir>/report.json`：每个 patch 的 applied/conflicted 状态与 .rej 冲突上下文。

2. **构建**（脚本 report.json 已生成精确命令）：用 `infra/openshell/patches/v0.0.83/Dockerfile.gateway-builder` 对候选版本构建 patched gateway/supervisor 二进制。

3. **回归**：`cd siq-research-engine/scripts/openshell && pytest control_tests -q`（基线 78 项）以候选二进制跑通；对照基线结果统计新增失败。

4. **能力探测**（ADR-005/009 关键输入）：
   - **动态网络更新**：对候选 Gateway 发起 network_policies 更新并回读 revision（v0.0.83 为编译期固定集合，不支持）；
   - **Gateway Interceptor**：候选版本是否提供（v0.0.83 未验证）；
   - **Provider 凭据注入 / Providers v2**：候选版本能力。

5. **决策**：按 ADR-009 矩阵输出结论——rebase 成本 ≤ 2 周且回归通过 → 方案 A；否则方案 B（MVP 按设计文档 §29.1 降级条款执行）。

## 验收标准

| 项 | 标准 |
| --- | --- |
| 补丁 rebase | 5/5 applied 或每个 conflict 有 .rej + 修复工作量估计 |
| 回归 | 对照基线（78 passed）新增失败清单 + 归因 |
| 能力探测 | 动态网络更新 / Interceptor 实测结果（是/否 + 证据） |
| 决策输出 | ADR-009 定稿（方案 A/B/C + 理由） |

## 边界

- 评估器只在 /tmp 目录工作，不修改生产状态（不 source env.sh、不写 var/、不动既有构建脚本）；
- 构建/回归在具备 Rust/Docker 的环境执行；本机（无 Docker/Rust 链验证）只做补丁 rebase 评估；
- 结论写入 ADR-009 后，Phase 3 进入条件解除。
