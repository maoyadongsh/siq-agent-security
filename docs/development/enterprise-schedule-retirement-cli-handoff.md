# CL-02-SCHEDULE-RETIREMENT-CLI 交接说明

日期：2026-09-26。执行者：Edge 开发工程师。状态：周期归档/恢复命令子项完成；未提交、未推送、未部署；不关闭 CL-02，不声称新设备自动接入或正式安装包完成。

开始前快照：HEAD `ebaaf3b60cc554ae67f4553aa1cfd0575a5d7ec0`（main）。`edge/agent/main.go` 存在主线移交的在途修改（命令分发扩展），本任务只在其上追加一行分发与两行帮助，未改动既有行。`discovery_schedule_retirement_linux.go` 及其测试为未跟踪的主线成果，原样保留，未修改。

## 1. 命令（可复制示例，全部占位参数）

```
# 预览（默认；仅读本地状态，零网络、零文件变更）
edge-agent retire-discovery-schedule

# 交互确认（仅真实终端；默认取消，输入 yes 才继续）
edge-agent retire-discovery-schedule --interactive

# 显式摘要确认执行：先在组织管理端撤销旧计划，然后归档
edge-agent retire-discovery-schedule --confirm-retire-intent-sha256 <旧意图64位十六进制摘要>

# 恢复未决归档事务（同样需要上述任一确认方式）
edge-agent retire-discovery-schedule --resume --confirm-retire-intent-sha256 <同一旧意图摘要>
edge-agent retire-discovery-schedule --resume --interactive

edge-agent retire-discovery-schedule --help   # 成功返回，零业务操作
```

命令名核查：main.go 既有分发中无同名或相近入口；`confirm-discovery-schedule` 的确认参数不被本命令接受（摘要变量独立）。

## 2. 修改/新增文件

| 文件 | 变更 |
| --- | --- |
| edge/agent/discovery_schedule_retirement_cli_linux.go | 新增：CLI 语义（预览/确认/锁/prepare→finish/resume） |
| edge/agent/discovery_schedule_retirement_cli_other.go | 新增：非 Linux 不支持入口 |
| edge/agent/discovery_schedule_retirement_cli_linux_test.go | 新增：集中旅程测试 |
| edge/agent/main.go | 仅追加 `retire-discovery-schedule` 分发一行 + 帮助两行 |
| packages/contracts/enterprise-discovery-schedule-retirement.v1.md | 实施状态更新 + 新增"已实现的完成与恢复 CLI"章节（不放宽安全要求） |
| docs/development/enterprise-schedule-retirement-cli-handoff.md | 新增本文件 |

未修改：底层 `discovery_schedule_retirement_linux.go`（接入中未复现需要修复的问题，零改动）、后端、前端、Connector、安装器、其他合同与台账。

## 3. CLI 如何调用底层实现

- 预览：本地 `readRetirementPreview`（有未决标记→`readPendingScheduleRetirement` 校验归档/回执/基线，损坏即失败关闭）；无标记→`readScheduleJournal`。全程无网络。
- 执行（首次）：显式摘要或交互 yes 绑定 `journal.Request.IntentDigest` → `acquireTaskLock` → 既有 `prepareScheduleRetirement`（在线核对 revoked、独占写历史副本与未决标记）→ 既有 `finishScheduleRetirement`（再次在线核对、核验原件后迁移、写完成记录、释放标记）。
- 恢复（`--resume`）：无未决记录→如实报告并不发网络；有→同一摘要绑定→任务锁→`finishScheduleRetirement` 复用同一归档事务。缺一侧原件属合法崩溃点（底层语义），不当作从未配置。
- 摘要不匹配在构造 Client 与任何网络请求之前拒绝；确认后仍失败时 prepare 成功/finish 失败返回 `retirement_pending` 提示 `--resume`，不清理现场。

## 4. 完成与恢复各阶段

首次执行：预览确认 → GET revoked（prepare）→ 历史副本独占持久化+读回核验 → 未决标记发布 → GET revoked（finish）→ 原件迁移 → `discovery-schedule-retired-<摘要>.json` 持久化 → 未决标记移除。
恢复：未决标记预览 → 摘要确认+任务锁 → GET revoked 复核 → 缺失原件按崩溃点放行、存在原件须与归档逐字节一致 → 同一完成序列。历史与完成记录任何阶段不删除、不覆盖。

## 5. 测试命令及实际结果

构建与测试均显式 `-o`/`-c -o` 到 /tmp/retire-cli-check/，未覆盖仓库二进制；transport 注入注入点仅测试参数，无环境变量或 flag 控制。

| 命令 | 结果 |
| --- | --- |
| `go test -c -o /tmp/retire-cli-check/edge-agent.test .` + 运行 `TestRetireScheduleCLI*` 与 `TestScheduleRetirement*` | 全部 PASS（CLI 24 子用例 + 底层既有 3 组负例/恢复用例不回归） |
| `go test -race -c -o ...` + 运行 `TestRetireScheduleCLI*` | PASS |
| `go test -o /tmp/retire-cli-check/edge-agent-full.test .`（全包回归） | `ok siq-agent-security/edge/agent 2.870s` |
| `go vet ./...` / `gofmt -l .` / `git diff --check` | 通过/无输出/干净 |

旅程覆盖对应任务 A–E：
- A 预览/帮助/取消：help 零 HTTP 零文件变更；预览（有材料/无材料/未决）零 HTTP 零变更；非终端 `--interactive` 拒绝；`--resume` 无未决时诚实报告零网络。
- B 正常完成：摘要确认 → 2 次 GET revoked → 原件释放、历史字节不变、完成记录存在、标记解除、输出无凭据。
- C 中断恢复：both-present / ack-moved / both-moved 均以同一归档身份完成（不新建历史），各 1 次 GET。
- D 拒绝：锁冲突（固定报错、零 HTTP、零变更）、错误摘要（网络前拒绝）、active、取消/过期 ctx、损坏 marker、归档被替换、原件符号链接——均失败关闭、不覆盖现场、不误报成功。
- E 新确认边界：未决期间 `prepareScheduleJournal`、`scheduledHeartbeat`、`confirm-discovery-schedule --resume` 全部拒绝；CLI 恢复完成后槽位释放且不产生任何新确认。

## 6. 非 Linux 行为与未验证平台

`discovery_schedule_retirement_cli_other.go` 使 `retire-discovery-schedule` 在非 Linux 返回 `discovery_schedule_unconfirmed`（与既有 `confirm_schedule_other.go` 模式一致）。`GOOS=windows` 与 `GOOS=darwin arm64` 交叉编译通过（产物在 /tmp）；这是编译检查，不冒充该平台原生验收——未在任何真实 Windows/macOS 运行。

## 7. 剩余安装闭环缺口

- 合同"当前限制"保留：历史副本已写但标记未发布的中断场景仍拒绝再次准备，需显式人工处置；本 CLI 不自动处理该状态（失败关闭）。
- 原生安装旅程、真实设备与真实控制面的端到端验收未做（不连接真实服务/设备）。
- 完成后新计划的独立确认走既有 `confirm-discovery-schedule`，其未决事项不在本任务范围。
- 归档 CLI 未改变：不自动撤销远端计划、不自动确认新计划、不停止服务；锁冲突由用户按现有流程处理。

禁令遵守：未读取真实 .env、admin-password.private、令牌、私钥、设备种子；未注册、未扫描、未启停服务、未提交推送发布。仅声明周期归档/恢复命令子项完成。

## 8. 主开发者验收与修复（2026-09-26）

本节修正上文历史交付结论，底层 prepare/finish 保持未改。

实际新增负例后，默认预览四个子场景全部失败：损坏日志、孤立回执及符号链接
被返回成功并报告无材料；损坏回执被当作可预览的正常材料。该问题不证明执行路径
绕过在线撤销验证，但违反预览的失败关闭与诚实诊断要求。

CLI 改为复用已固定目录的安全读取与既有日志/回执校验：仅两份材料都确实不存在
才报告无材料；异常或孤立材料返回固定错误，零网络、原文件不变。
新增四个负例验证文件集合与摘要保持不变；没有修改底层归档事务。

另纠正合同及 §7 的过时描述：底层 `writeScheduleRetirementFile` 已支持完整、字节相同的
历史副本安全复用。新增一个 CLI 旅程，模拟完整历史存在而标记尚未发布，重新明确
确认后经两次撤销 GET 完成，历史字节不变且完成记录存在。残缺或不可核对副本
仍然失败关闭；无标记的 `--resume` 不执行重新准备。

实跑验证（edge/agent）：

```bash
go test -count=1 -run '^TestRetireScheduleCLIPreviewRejectsDamagedMaterial$' .
# 修复前：四个子场景均失败。
go test -race -count=1 -run 'TestRetireSchedule|TestScheduleRetirement|TestConfirmSchedule|TestScheduleHeartbeat|TestInstallUserService' .
go vet ./...
gofmt -l discovery_schedule_retirement_cli_linux.go discovery_schedule_retirement_cli_linux_test.go
```

修复后定向 race 检查通过，vet 通过；未重跑无关全量、未重做 Windows/macOS
交叉编译，不把原交付的编译结果当成本轮重新执行结果。全部是临时状态目录与
注入传输的合成测试，无真实网络、systemctl 或生产状态操作。

本轮只改 CLI Linux 实现及其测试、合同与本交接记录。未改 main.go、底层事务、
非 Linux 文件或其他开发线成果。未提交、未部署；仅接受该 CLI 子项，CL-02 保持开放。
