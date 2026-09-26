# CL-02-SCHEDULE-POLL-CLOSEOUT 交接记录（周期轮询取消与重试状态收口）

- 日期：2026-09-26
- 任务书：CL-02-SCHEDULE-POLL-CLOSEOUT
- 状态：**未提交、未部署，待主开发者复核。仅完成该取消/轮询子任务，不代表 CL-02、CL-07 或整个目标完成。**

## 1. 实际修改文件

- `edge/agent/discovery_schedule_poll_linux.go`（仅 `scheduleHeartbeatLoop` 内 3 行）
- `edge/agent/discovery_schedule_poll_linux_test.go`（新增 1 个集中参数化测试）

两文件在任务开始前为未跟踪状态（主开发者并行成果），本次未覆盖其他内容；未改 confirm_schedule*、serve.go、合同及其他任何文件。

## 2. 旧行为复现与最小修复

- 复现（先写测试、先跑失败）：新增 `TestSchedulePollTickCancellationPreemptsState`，合成 tick 回调在返回前取消 ctx，分别返回错误 / `active=true` / `active=false`。旧实现三种情形均返回 `nil`（取消被吞）：错误路径落入独立退避（`retryAt`/`delay` 被改并输出 "bounded retry scheduled" 日志），`active=false` 路径把本地 `stopped` 置 true。测试运行输出确认了该旧行为（`canceled tick returned <nil>` ×3 + 重试日志）。
- 修复：在 `scheduleHeartbeatLoop` 中 `tick(ctx)` 返回后、进入错误退避或 `stopped = !active` 之前，先检查 `ctx.Err() != nil` 并原样返回（`context.Canceled`）。取消不修改 `stopped`/`retryAt`/`delay`，不输出普通失败重试日志，也不被当成业务成功或非 active 停用。
- 与既有约定一致：heartbeat 之后已有同样的 `ctx.Err()` 检查；`initial_scan.go` 的回调后取消检查模式相同。合同（`enterprise-discovery-schedule.v1.md`）"返回非 active 状态后本次服务生命周期停止轮询"的语义未被放宽——被取消的 tick 不构成非 active 判定。

## 3. 保持不变的行为

- heartbeat 先行；窗口控制（start 前 / end 后不发）；30 秒起步、15 分钟上限指数退避；成功重置退避；非 active 停止本次生命周期。
- 未取消时的 tick 网络失败仍独立退避、不抑制心跳、不永久停止。
- tick 请求/响应 JSON、认证头、8192 字节上限、重定向拒绝、严格字段校验、固定错误文案均未动。
- 无自动重放、补扫、自动确认、后台 goroutine；任务 ID 仍只由原任务循环领取/验签/执行。

## 4. 测试与校验命令、结果

```
cd edge/agent
go test -race -count=1 -run 'TestSchedulePollTickCancellationPreemptsState' .   # 修复前 FAIL（复现），修复后 PASS
go test -race -count=1 -run 'TestSchedule' .                                    # PASS（含既有 3 个用例 + 新增参数化 3 个子用例）
go vet ./...                                                                    # 通过
gofmt -l discovery_schedule_poll_linux.go discovery_schedule_poll_linux_test.go # 无输出
git diff --check                                                                # 通过（含交接文档空白检查）
```

`TestSchedule` 前缀实际覆盖本文件全部用例及 confirm/transport 相关用例，无需更换正则。

## 5. 未运行事项与证据边界

- 未运行全项目/全模块测试、跨平台编译；未运行 systemctl、未访问真实设备、未启动服务。
- 证据边界：本修复由注入时钟/回调的合成测试证明；**不构成真实 serve 进程退出、原生服务安装或实机周期旅程验收**。第二次"新 context + 同一注入时刻"调用仅是测试闭包无副作用的手段，不是生产自动恢复策略，生产代码未新增任何恢复路径。

## 6. 范围外发现

无新发现。

## 7. 主开发者复核（2026-09-26）

核对 tick 返回后的取消检查确实位于错误退避及 stopped 更新之前；集中测试覆盖错误/active=true/active=false，且第二次调用验证闭包未残留停止或退避。独立执行 `go test -race -count=1 -run '^TestSchedulePollTickCancellationPreemptsState$' .` 通过。本次未重复修改实现或调用真实 systemctl。

接受该子任务。第 2 节关于 initial_scan.go 的类比仅对其错误返回分支成立；其成功返回后的取消尚需单独核对，已分配 CL-02-INITIAL-SCAN-CANCEL，不修改本任务边界。未提交、未部署，不关闭 CL-02/07。
