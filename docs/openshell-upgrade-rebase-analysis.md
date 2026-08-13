# OpenShell 升级补丁 Rebase 深度分析（D1 spike 产物）

> 日期：2026-08-13  
> 候选：v0.0.104（最新 release）| 基线：v0.0.83（+2 个本地 patch）  
> 方法：补丁逐 hunk 对照 v0.0.104 上游源码（`/tmp/d1-eval-latest/src/openshell-v0.0.104/`）

## 核心结论

**两个 OpenShell patch 均已被上游完全吸收，升级后可以直接退役，rebase 成本 ≈ 0（但必须执行语义等价验证）。**

patch 报冲突的原因不是"上游改坏了代码"，而是 diff 格式的补丁试图在"已包含相同变更"的代码上再次 apply——上下文找不到旧形状。

## 逐项证据

### 0001-landlock-mask-file-access.patch（3/5 hunk 冲突 → 退役）

| 补丁内容 | v0.0.104 上游 | 结论 |
| --- | --- | --- |
| 为规则 access mask 按已打开 FD 的文件类型裁剪（`access_for_path_fd`） | `crates/openshell-supervisor-process/src/sandbox/linux/landlock.rs:297-400` 区域已内置：`Restrict a rule's access mask to rights valid for the opened path type`、`Tailor a rule's access mask to the inode referenced by its already-open FD` | 上游已实现等价语义，**删除补丁** |

### 0002-siq-strict-bind-mount-contract.patch（10/11+1/1 hunk 冲突 → 退役）

逐 hunk 对照（补丁位置 → v0.0.104 实际状态）：

| 补丁 hunk（旧行号） | 内容 | v0.0.104 位置 | 状态 |
| --- | --- | --- | --- |
| #1 @77 | `SIQ_ANALYSIS_BIND_MOUNT_CONTRACT`/`MOUNT_COUNT` 常量 | lib.rs:83-84 | ✅ 逐字存在 |
| #2 @140 | `DockerComputeConfig` 增加 `bind_mount_contract`/`bind_mount_project_root` | lib.rs:145+ | ✅ 存在 |
| #3 @159 | Default 实现补两字段 | lib.rs:170 | ✅ 存在 |
| #3b | `validated_bind_mount_project_root` 校验函数 | lib.rs:175-200+ | ✅ 逐字等价 |
| #4 @188 | `DockerDriverRuntimeConfig` 补两字段 | lib.rs:221+ | ✅ 存在 |
| #5 @307 | 构造函数调 `validated_bind_mount_project_root` | 上游对应构造路径 | ✅ 存在 |
| #6/#7 @371/431 | `validate_docker_driver_mounts` 调用点带 contract 参数 | lib.rs:493、1832 | ✅ 存在 |
| #8 @1708 | 测试助手 `docker_driver_config(runtime_config)` 签名 | lib.rs:1826-1840 | ✅ 逐字一致 |
| #9 @1841 | 新增校验函数群（`validate_siq_analysis_run_id`、`validate_siq_company_segment`、`is_siq_analysis_task_path`、`canonical_siq_bind_source`、`validate_siq_analysis_bind_mounts`） | lib.rs:1966-2253 | ✅ 全部存在（含全角括号 `（`/`）` 字符校验） |
| #10 @1905+ | mount 契约主体（7 挂载、wiki/hermes/runtime 目录校验） | lib.rs:2039+ | ✅（该 hunk 以 fuzz 2 应用，说明上下文与上游已有代码重合） |
| #11 @2248 | 契约尾部校验 | lib.rs:2125-2177 | ✅ 存在 |
| tests.rs @114 | `siq_analysis_mount_fixture` 测试夹具 | tests.rs:124-161 | ✅ 存在（含 `siq-research-engine` 项目根路径夹具） |

**结论：补丁的每一个逻辑单元都能在上游 v0.0.104 找到对应实现，包括 SIQ 专属常量（`siq_analysis_v2`）与测试夹具——上游已合并 SIQ 贡献（或经官方渠道合入）。**

## 必须执行的语义等价验证（构建环境）

退役补丁不等价于"什么都不做"。以下验证未完成前，不得在生产用 v0.0.104 声称替代 v0.0.83+patch：

| # | 验证项 | 方法 |
| --- | --- | --- |
| V1 | landlock mask 行为等价 | 用 78 项 control_tests 中的跨公司拒写/删除守卫用例对 v0.0.104 二进制重跑（补丁删除状态下） |
| V2 | bind-mount 契约全量等价 | 构造正样本（合法 7 挂载）+ 负样本（6/8 挂载、越界 root、`..`、symlink、SELinux label）分别断言接受/拒绝，与 v0.0.83+patch 行为对照 |
| V3 | 上游契约与 SIQ 配置兼容 | 现有 `build_policy.py` 输出的 mount plan 直接喂给 v0.0.104 验证通过（端到端 mount 合同） |
| V4 | 回归 | `cd siq-research-engine/scripts/openshell && pytest control_tests -q` 基线 78 passed 对照 |
| V5 | 能力探测 | 动态网络更新（新增→变更→回读 revision）；Gateway Interceptor 可用性——决定 Phase 3 MVP 范围 |

## 对 ADR 与治理的影响

- ADR-009：方案 A（升级）成本从"1-3 人日 rebase"修正为"**0 rebase + 等价验证**"；若 V1-V5 全过，升级风险大幅降低；
- ADR-005 patch 治理表更新：0001/0002 → `upstreamed` 状态（验证通过后归档），本地 patch 目录保留历史引用；
- `d1_upgrade_eval.sh` 的冲突判读需要注释本结论：**conflicted 可能是"已上游化"而非"需人工 rebase"**，判读顺序：先对照上游源码找等价实现，再评估 rebase。

## 遗留风险

- 上游吸收的版本是否与 SIQ 补丁**完全**一致（如 `validate_siq_company_segment` 的字符白名单细节）——V2 对照负样本可覆盖；
- v0.0.104 是否引入其他行为变化影响 78 项回归——V4 覆盖；
- 动态网络更新能力是否真的在 v0.0.104 可用——V5 是 MVP 范围的关键闸门。
