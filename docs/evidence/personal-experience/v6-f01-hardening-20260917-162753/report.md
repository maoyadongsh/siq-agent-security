# F01 加载确认收紧（2026-09-17，组件级）

## 结果

同一进程先前成功的 `policy set --wait` 确认不再无限期有效。`policy get --full` 的 `Status` 必须为 `Loaded` 或 `Active`，且已记录的确认距当前不超过 5 分钟；若读回出现 `Pending`、`Failed`、`Unknown`、空状态，或确认超时，则真实任务在 spawn 前拒绝，并清除进程内确认。即使下一次读回恢复旧状态/时间标记，也不能复活旧确认。原有修订、策略摘要、目标、调用配置指纹及网络端点核对保持有效。

修改：`internal/openshell/policy.go`、`policy_state.go` 和 `task_exec_test.go`，并同步 D01 设计与 v6 进度。新增两个负向回归覆盖旧 `Loaded` 时间标记伴随非已加载状态、确认过期及失效后恢复；通过注入的任务 runner 断言零 spawn。

## 验证

在 `apps/agentshield` 执行：

- `go test ./internal/openshell -count=1`：退出 0。
- `go test ./...`：退出 0。
- `go vet ./...`：退出 0。
- `go test -race ./internal/openshell ./internal/server`：退出 0。
- 四目标 `CGO_ENABLED=0 go build ./cmd/agentshield`：见 `builds.json`，不代表 OS 实机验收。
- 仓库根 `git diff --check`：见 `checks.json`。

## 边界

这是组件级防护。5 分钟有效期和 `Loaded` 时间标记都不是可信的唯一网关或沙箱运行实例身份。没有在专属真实网关证明策略加载、执行平面行为、失联与重启条件；F01/F04 仍为 partial/待验收。固定 `Status` 取值来自本仓 v0.0.83 `policy get --full` 夹具，后续同候选真实读回应验证版本兼容；未知值会保守拒绝。此批无 commit、push、merge、签名或发布，也没有连接或改动共享网关。
