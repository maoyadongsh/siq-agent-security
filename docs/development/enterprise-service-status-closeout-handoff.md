# CL-02-SERVICE-STATUS-CLOSEOUT 交接记录（Edge 服务状态命令收口）

- 日期：2026-09-26
- 任务书：CL-02-SERVICE-STATUS-CLOSEOUT
- 状态：**未提交、未部署；仅此命令收口，不代表 CL-02/07 或整体项目完成。**

## 1. 实际修改文件

- `edge/agent/user_service_status_linux.go`
- `edge/agent/user_service_status_linux_test.go`

未改动 main.go、serve.go、合同、非 Linux 实现及其他任何文件。

## 2. 逐项问题：复现、仲裁与最小修复

### A. 取消后仍返回成功 —— 成立，已修复

- 复现：ctx 在 runner 执行期间取消，runner 仍返回合法三属性行（`LoadState=loaded / ActiveState=active / UnitFileState=enabled`）；原实现只在调用 runner 前查 `ctx.Err()`，返回后直接解析成功。
- 仲裁：违反"已经取消的查询不能被当作成功状态"。
- 修复：`readUserServiceStatus` 在 runner 返回后、解析前增加 `ctx.Err() != nil` 检查（`user_service_status_linux.go:46`）。未改全局超时/上下文架构。
- 回归：`TestUserServiceStatusCancelAfterRunnerReturns`。

### B. 帮助入口 —— 成立，已修复

- 复现：`-h` / `--help` 经 `flag.ContinueOnError` 返回 `flag.ErrHelp`，原代码将其与未知参数一律归入 `errUserServiceStatus`（业务诊断失败、退出码 1），且无任何说明文本。
- 仲裁：任务书 B 明确不能把 `flag.ErrHelp` 当成业务诊断失败。
- 修复：仅在本命令内——`runUserServiceStatus` 对 `flag.ErrHelp` 输出一段固定说明（只读、固定用户服务 `siq-edge-discovery.service`、active 仅为服务管理器状态不证明联网/扫描/保护）并返回 nil，不调用 systemctl。正常状态查询的 stdout 仍只输出一行 JSON，不混入说明文本。未知参数与位置参数仍返回 `errUserServiceStatus`，未新增功能选项。处理方式与仓内 `serve.go` / `confirm_schedule_linux.go` 既有 `ErrHelp` 约定一致。
- 回归：`TestUserServiceStatusHelpDoesNotRunSystemctl`（断言 0 次 runner 调用及说明要点）。

### C. 输出失败与执行失败 —— 无缺陷，补验证

- 核对结果：manager 不可达、非零退出、超 4096 字节、结构错误/重复/缺属性均返回固定 `errUserServiceStatus`，不生成伪 inactive JSON、不回显原始输出或环境值；编码失败经 `json.NewEncoder(...).Encode` 返回值正常传播（main 以 `log.Printf("error: %v")` 记录固定错误后退出 1）。错误信息为固定常量，无泄漏面。
- 按任务书允许提取内部函数 `runUserServiceStatus(ctx, args, stdout, run)` 注入 writer/runner 验证真实命令路径；`cmdUserServiceStatus` 保持原签名与真实 `/usr/bin/systemctl` runner。
- 回归：`TestUserServiceStatusJSONOnlyOnStdoutAndEncodeFailure`（stdout 纯 JSON 前缀 + writer 失败传播）；既有 `TestUserServiceStatusRejectsIncompleteOrLeakingOutput` 继续覆盖泄漏/截断/重复属性。

## 3. 保持不变的边界

- 只查询当前用户固定 `siq-edge-discovery.service`；固定 `/usr/bin/systemctl --user show --no-pager --property=LoadState,ActiveState,UnitFileState`；无 shell/sudo/PATH 查找；无任何生命周期操作。
- 总超时 20 秒、stdout 上限 4096 字节、stderr 丢弃均未变。
- 精确三属性解析、重复/缺失/额外/错误结构失败、未知值归一 `unknown` 不回显原值，均未变。
- JSON v1 合同字段未动；`heartbeat_verified` / `discovery_verified` / `protection_verified` 仍恒为 false（既有测试继续断言）；active 的证据边界说明不变。
- 不读取身份、设备状态、确认日志、令牌、安装目录；无新增网络请求、命令、全局可变替身或环境变量后门。

## 4. 测试命令与结果

```
cd edge/agent
go test -race -count=1 -run 'TestUserServiceStatus' .   # PASS，7 个用例（4 既有 + 3 新增），0 失败
go vet ./...                                             # 通过
gofmt -l user_service_status_linux.go user_service_status_linux_test.go  # 无输出
git diff --check                                         # 通过
```

未运行：全项目/全模块测试、跨平台编译、任何真实 systemctl 调用（全部行为使用注入 runner）、浏览器或整机验收——按任务书预算省略。

## 5. 范围外发现（未顺手修复）

- 无新发现。CL-02 主体缺口（周期调度闭环、安装交互、实机旅程）与主开发者并行线一致，不在此重复。

## 6. 交付边界

未提交、未部署；仅此命令收口，不代表 CL-02/07 或整体项目完成。

## 7. 主开发者复核（2026-09-26）

已检查当前实现与七个测试。取消后 runner 即便返回合法输出仍拒绝，帮助通过独立 writer 输出且不调用 runner，未知参数保持拒绝；固定 unit/命令、输出上限、超时与三项 verified=false 未放宽。未发现需要追加代码修复的问题。

独立重跑 `go test -race -count=1 -run '^TestUserServiceStatus' .` 通过；同轮 `go vet ./...`、`git diff --check` 通过。未调用真实 systemctl，不把注入 runner 的测试当作实机服务验收。仅接受此子任务，不关闭 CL-02/07；未提交、未部署。
