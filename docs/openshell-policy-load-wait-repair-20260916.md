# OpenShell 策略加载等待修复与复测（2026-09-16）

## 1. 结论与根因

已修复上一批 L01 严格行为测试失败项：Go 策略应用和授权回滚等待沙箱加载确认后才返回成功，且继续核对完整 revision/digest。真实独占测试沙箱共 3 轮均为 HTTP 403、违规接收计数 0，两个精确目标均先通过允许正控，每轮恢复原策略并复核摘要。新候选 rc.6 真实 HTTP 策略旅程 57/57 通过。

原实现的 `policy set` 只确认提交，后续 `policy get` 只能证明配置读回，执行平面仍可能暂用旧策略。此前 rc.5 的 `arrived arrivals=1` 失败保留在原证据目录；修复的是缺少加载确认，未改变拒绝判据，也未通过延迟/重试禁止请求规避失败。当前 CLI 0.0.83 提供 `--wait --timeout`；[NVIDIA 策略文档](https://docs.nvidia.com/openshell/sandboxes/policies) 明确等待沙箱确认加载。

## 2. 代码与安全边界

- Go：`internal/openshell/policy.go` 共用 `setPolicyAndWait`，覆盖 ApplyNetwork 与 RollbackAuthorized。等待秒数为现有 Timeout 的整数秒减 2，最少 1；原 Runner 外层超时仍为硬上限。授权、写前漂移检查、锁、写后摘要验证继续保留。
- Python：`app/adapters/openshell/cli_backend.py` 的应用和回滚同步使用 `--wait --timeout 28`，已有进程上限显式绑定 30 秒。
- 不支持等待选项、命令失败、加载超时一律报错，不能回退为无等待写入；提交后超时可能已产生副作用。Go HTTP 测试证实返回 502 / execution_uncertain=true，状态为 uncertain，重放 409，只有一次写入。
- no_op 继续只表示未写入；CLI 确认、配置读回不自动产出 enforcement_verified。此次行为证据只覆盖受测网关、Linux 跨边界 HTTP 路径和对应源码，不推广为全部环境能力。
- 新回归覆盖 Go 成功应用/恢复及不支持/超时，Python 成功应用/恢复及两个阶段的不支持/超时。状态型 fixture 接受新增参数，但不放宽实际行为断言。

## 3. 验证与候选

| 验证 | 结果 | 范围 |
|---|---|---|
| gofmt / go vet ./... / go test ./... | exit 0 | Go 全模块 |
| go test -race openshell/server/receipt | exit 0 | 相关并发路径 |
| Python OpenShell 全组 + policy_flow + schema_contracts | 342 passed，1 项既有依赖弃用 warning | 组件/合同 |
| Ruff 修改的 Python 实现及测试 | 通过 | 静态检查 |
| CGO_ENABLED=0 四目标构建 | 4/4 | Linux amd64/arm64、macOS arm64、Windows amd64；非跨 OS 实机 |
| TestO05LiveCrossBoundaryEnforcement | 1 轮 + 预定追加 2 轮，3/3 | 真实沙箱与独立接收端，未更改测试源码/断言 |
| rc.6 HTTP 策略旅程 | 57/57 | 真实二进制、daemon、HTTP、网关；scope=policy_apply_http_journey |

未签名候选 `dist/siq-agent-security-0.3.0-rc.6/` 基于 HEAD 052c816 加工作区修改。原候选未覆盖。1116 个 Go 源码/内嵌资源/测试文件及摘要、源码归档、编译参数、工具链与四工件 SHA 见 builds.json。Go 源码摘要 `edbd7011b2ccedf3e42cfe07164d4e2184f1c8c5d860883cced91b6d3fdcfcbe`；linux/arm64 二进制 SHA256 `7fd9ca0469b3fcf57d76579e6e96db79db6846041a3d4735c4dcfb2f3076870f`。Python 不包含在 Go 二进制中；其本轮源码哈希另存 source-bindings.json，不借用 Go 活体验收结论。

此次没有性能计时协议；真实行为测试的墙钟耗时不是性能验收，新增等待带来的延迟必须在后续独占性能批次重新测量。未继承旧 rc.3/rc.5 性能结论。

## 4. 证据、重测与资源

本批证据：[policy-load-wait-20260916-231213](evidence/personal-experience/policy-load-wait-20260916-231213/)。live-result.json 保存第一轮，live-repeat-result.json 保存预先固定的追加两轮；全部成功/失败尝试记录保留。三轮结果分别耗时约 40.57、32.55、39.62 秒，均完整恢复策略。policy-journey/l03-journey.json 绑定 rc.6 实际版本与完整二进制哈希。checks.json、日志、candidate-builds.json、source-bindings.json、resources.json 和 SHA256SUMS 供复核。

新建目标 `siq-loadwait-231213` 的 create/delete 均 exit 0，删除后 get exit 1 且明确 not found，已确认缺席。测试接收端由测试清理，旅程 daemon 由 runner finally 停止并等待退出。未重启共享网关，未处置旧 GLM 沙箱/归属不明 PID。CLI 原始输出仅留 Git 忽略的 runtime-private/，目录 0700、文件 0600。

本轮早期 Go server 回归因旧 fixture 只接受 5 个参数失败；更新为要求 `--wait --timeout` 的 8 参数后全量通过。该 fixture 修正不是生产回退。修复后真实行为测试三轮一次性通过，未重跑挑优。

## 5. 仍未关闭的任务

- L01 这一跨边界拦截失败已解除；L02/O05 完整任务执行、停止/恢复和 UI 闭环仍待开发验收。当前 HTTP 接口仍 `scope=policy_apply`、`task_executed=false`。
- 新候选 B2/B3/B07 性能需要重新冻结协议测量；本批未测。
- Python 企业后端只做组件/合同验证，未另开企业服务实机验证。
- Windows/macOS 协作者、WorkBuddy、真实源网络条件、正式签名/发布仍按各自前提推进，不能因为本次 Linux 测试通过统一置绿。N09 总体状态不改变。

## 6. 落盘状态

本批没有 commit、push、merge、签名或发布。保留此前全部工作区修改。撤销本轮补丁需保留历史授权修复、身份保护及证据，不应直接 reset 工作树；已运行新二进制后回退旧代码会重新暴露本次加载竞态。
