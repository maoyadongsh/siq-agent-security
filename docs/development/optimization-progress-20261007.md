# 安全优化实施进度（2026-10-07）

状态源：[optimization-tasks-20261007.json](optimization-tasks-20261007.json)。本文件为其阅读视图，更新状态先修改 JSON，再刷新本视图。

方案：[优化开发方案](SIQ_Agent_Security_优化开发方案_20261007-102651.md)。

基线：`c41347579ebe67c7f732d0e523722e489f831039`。分支：`codex/security-optimization-20261007`。

| 任务 | 内容 | 状态 | 旧任务映射 |
| --- | --- | --- | --- |
| OPT-00 | 基线与既有任务去重 | done | 本批新增／现有流程复用 |
| OPT-01 | 回执链并发一致性 | done | 本批新增／现有流程复用 |
| OPT-02 | 生产构建与身份边界 | done | 本批新增／现有流程复用 |
| OPT-03 | 扫描资源预算与限流 | done | SEC-F08 |
| OPT-04 | 错误输入与分页 | done | 待结合对应模块继续核对 |
| OPT-05 | OpenShell持久化回滚与后端绑定 | done | 待结合对应模块继续核对 |
| OPT-06 | pending提升幂等 | done | SEC-F05 |
| OPT-07 | 策略语义与部署入口 | done | 待结合对应模块继续核对 |
| OPT-08 | 日常Skill上下文 | implementing | 待结合对应模块继续核对 |
| OPT-09 | OpenShell行为证据 | planned | 待结合对应模块继续核对 |
| OPT-10 | 同候选业务回归 | planned | 待结合对应模块继续核对 |
| OPT-11 | 连接器可信执行 | planned | 待结合对应模块继续核对 |
| OPT-12 | 钩子完整性 | planned | 待结合对应模块继续核对 |
| OPT-13 | 交付安全头 | planned | 待结合对应模块继续核对 |
| OPT-14 | 扫描进程隔离 | implementing | SEC-F08 |
| OPT-15 | 跨平台验收与有界清理 | planned | SEC-F06 |

## 当前验证

OPT-01 首批组件与 OPT-02 生产身份边界已完成本批回归，见[首批验证](optimization-opt01-opt02-validation-20261007.md)及[消费者回归](optimization-opt02-consumers-validation-20261007.md)。前端 1,031 项通过；30 组浏览器脚本均有通过记录（首轮 28 组、修复复跑 2 组）。[OPT-04 验证](optimization-opt04-validation-20261007.md)包括控制面 2,346 项通过、1 跳过，PostgreSQL 19 项检查、本地 Go 全量与四目标构建。

[OPT-03 / OPT-14 验证](optimization-opt03-opt14-validation-20261007.md)：控制面 2,372 通过、1 个既有条件跳过；进程配额与原生 Linux worker 故障边界通过。默认 Docker 阻止 namespace 创建，OPT-14 保持 implementing；[OPT-06](optimization-opt06-validation-20261007.md) 来源事件幂等、v2 重启恢复及全套相关 race 已通过。[OPT-05 A](optimization-opt05-backend-validation-20261007.md) 原部署后端绑定已验证：控制面 2,383 通过、1 跳过，PostgreSQL 22 项检查；[B 批基础组件](optimization-opt05-journal-validation-20261007.md)已通过定向与 PostgreSQL 29 项检查，[在线持久恢复](optimization-opt05-online-validation-20261007.md)已完成：控制面全量 2,475 通过、1 条条件跳过，PostgreSQL 31 项检查、真实 OpenShell 14 项检查通过，包括新 API 进程精确回滚。未推送或完成主线 CI，不作最终发行或全部任务完成结论。

[OPT-07 验证](optimization-opt07-validation-20261007.md)：新增 15 条共享语义向量，四入口 32 项矩阵独立通过；Python 全量 2,486 通过、1 条条件跳过，PostgreSQL 31 项检查，Go 44 个测试包及 grant/server race、四目标构建通过。本地网络替换接口明确区分缺省/null 与空数组。

OPT-08 保持 implementing。[A 合同](optimization-opt08-context-validation-20261007.md)、[B1 持久上下文](optimization-opt08-store-validation-20261007.md)、[B2 精确调用](optimization-opt08-call-validation-20261007.md)、[C1 决策交集](optimization-opt08-engine-validation-20261007.md)、[C2a 审批重试](optimization-opt08-hold-validation-20261007.md)、[C2b 版本兼容](optimization-opt08-compat-validation-20261007.md)、[C2c 消费者兼容](optimization-opt08-consumers-validation-20261007.md)、[D1 签名身份策略](optimization-opt08-enrollment-validation-20261007.md) 已完成各自组件验证。前端 1,062 项及页面 HTTP 夹具验证通过；D1 最新 Go 全量、身份/调用/回退定向 race、四目标构建和 340 项 Python 合同测试通过。身份固定的必需策略已连接精确调用校验，未配置原生查询的 HTTP 明确拒绝新身份。原 v1 追踪投影明确标记无法表达的原生 Skill 来源 unavailable，完整证明保留在 v3 回执。真实宿主事实来源、管理读回、serve 接线和日常业务效果验收仍未完成；新身份的 HTTP 创建入口保持关闭。

## 边界

既有 SEC-F01–F04/F07/F09 不因本方案自动插入；与实际修改相关时按原合同处理。RES-01 与 SEC-F10 的 Host Sensor 方向关联，但不自动纳入风险评分或强制执行实现。Windows/macOS 原生验收环境需在相应任务启动时核实，不以 Linux 构建替代。

## 交付安排

用户已于本轮明确要求：完成后提交到远端。继续按功能批次本地提交，全部适用任务及门禁完成后推送远端分支；不纳入历史原始采集、临时制品和无关工作树改动。当前未推送，不宣称远端 CI 或主线合并已完成。
