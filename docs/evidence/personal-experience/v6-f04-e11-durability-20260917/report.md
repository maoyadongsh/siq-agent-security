# F04 / E11：任务结果持久化失败的组件级补证（2026-09-17）

## 判定

仅 **组件级通过**，E11 和 F04 整体仍为 `partial`。本次故障注入走生产 `POST /v1/openshell/task-executions` handler、签名预留及状态存储；只有 OpenShell 子进程运行器由测试替身替换。未在真实 OpenShell 网关/沙箱、浏览器或跨系统环境注入存储故障。没有复用先前 D05 的二进制摘要宣称本次修复已完成真实服务验收。

## 缺陷与修复

原 handler 对已启动任务的成功结果写盘失败返回 503 `execution_evidence_incomplete`，但非零退出及本地边界触发时，尽管结果证据或审计可能未写入，仍返回普通的 `task_failed` / `execution_uncertain`。这会掩盖独立的持久性失效。现在任务启动后只要结果证据或审计写入失败，统一返回 503 `execution_evidence_incomplete`，同时给出实际 `task_executed` 三态与必要的 `execution_uncertain`；不自动对账、不重放、响应不包含原始 stdout/stderr。没有改变未启动任务的预留前拒绝语义。

## 实际验证

| 命令或注入 | 结果 | 级别 |
| --- | --- | --- |
| `go test ./internal/server -run 'TestOpenShellTaskExec(UncertainEvidenceFailureIsExplicit|AuditFailureIsExplicit|EvidenceFailureNeverReportsSuccess|NonZeroExitStaysUncertain|LocalBoundIsUncertain)' -count=1` | exit 0 | 组件级 |
| 结果目录在子进程替身返回时改为不可写；非零退出、超时各一腿 | 均 503，`binding_evidence_persisted=false`，`task_executed=unknown`，`execution_uncertain=true`，单次启动，原文不泄漏 | 组件级 |
| 审计文件改为不可写；非零退出一腿 | 503，结果记录仍已持久化，审计失败明确暴露，单次启动，原文不泄漏 | 组件级 |
| `go test ./...`、`go vet ./...`（`apps/agentshield`） | 均 exit 0 | 全量 Go 回归 |
| `go test -race ./internal/server -run 'TestOpenShellTaskExec(UncertainEvidenceFailureIsExplicit|AuditFailureIsExplicit|EvidenceFailureNeverReportsSuccess|NonZeroExitStaysUncertain|LocalBoundIsUncertain)' -count=1` | exit 0 | 定向 race |
| `gofmt`、`git diff --check` | 无格式/空白错误 | 构建卫生 |

源码文件 SHA256：`openshell_task_exec.go` 为 `ee4677a177776fbc41835464b418571f26d3a4b9622c622718eec57ac357b813`；测试文件为 `4edb216625049e2eb2c5471135c50b41d6c89421e874e99aa09342f30669c749`。工具链：`go1.26.5 linux/arm64`。

## 尚未关闭

先前 Linux 范围候选 `ac447ac9…` 生成在这次源码修复之前。本次没有构建或运行新的最终候选，也没有真实服务的磁盘故障注入；E11 对畸形结果、远端/本地超时归因的整套同候选验收仍需单独核对。D05/E12 与 F05 性能应在新候选、匹配版本 CLI、隔离网关凭据和独占测量环境中重跑，不能继承旧候选成绩。
