# OPT-04 错误、输入和列表行为验证

日期：2026-10-07。分支：`codex/security-optimization-20261007`。

## 已实现

- 本地资产 confirm/dismiss 只接受一个非 null JSON 对象；畸形、第二个 JSON 和超过 64 KiB 请求在状态修改前拒绝。
- admission 读取失败使盘点明确失败，不再被解释为空列表。
- pending 补录最近结果和累积失败可在本地 status 诊断；队列保留，恢复后可重试，不改变线上权限决定。
- 控制面 policy、deployment、runtime-binding 列表统一既有截断规则：小于 1 使用 50、大于 200 截为 200，并返回机器可读列表元数据和下一页 cursor。响应主体仍为数组。
- OpenShell 初始化、编译和验证的异常采用固定类别及摘要，不返回私有路径、配置或后端异常原文；既有 request ID 中间件继续提供关联标识。

## 证据

所有本地原始记录位于 `var/optimization-20261007/`，不提交运行态目录。

| 验证 | 结果 | 记录 |
| --- | --- | --- |
| 控制面聚焦分页/绑定/错误测试 | 40 项通过 | `opt04-control-focused.log` |
| 控制面该批全量 | 2,346 通过、1 跳过，无失败 | `opt04-control-all.log` |
| PostgreSQL 临时数据库 | 19 项检查通过；包含限额/下一页/跨租户，部署、行锁及迁移保护 | `opt04-postgres-001/result.json` |
| 本地输入/盘点/pending race 聚焦 | 通过 | `opt04-local-race-focused.log` |
| 本地 Go 全量及 vet | 通过 | `opt04-go-all.log`、`opt04-go-vet.log` |
| Linux amd64/arm64、Darwin arm64、Windows amd64 | 四目标构建通过 | 本地 `bin/agentshield-*`，不作为原生平台验收 |
| 旧控制面负向对照 | 19 项失败，定位缺少限额元数据及异常明文 | `opt04-control-negative.log` |
| 旧本地实现负向对照 | 第二个 JSON 曾导致实际确认；超大请求状态不符；损坏 admission 曾被忽略 | `opt04-local-negative.log` |
| Ruff、gofmt 与差异检查 | 通过 | 终端检查；全量记录保留 |

数据库测试使用一次性 PostgreSQL 容器、合成身份及合成配置，结束后清理容器；未访问或修改真实业务数据库。PostgreSQL 使用开发身份以隔离分页/数据库语义，生产身份见独立 OIDC 验证。

## 边界

pending 诊断是重启即重置的进程状态，不证明历史回执完整，也不解决追加后游标丢失的幂等问题；后者由 OPT-06 单独处理。这里的全量数字属于本批候选，后续改动须以对应回归结果更新，不自动继承为最终发行通过。
