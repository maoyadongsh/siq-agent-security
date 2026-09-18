# R02（N06）可信重试组件批次复核记录

- 日期：2026-09-14
- 工作树：`/home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914`
- 基线：`b303c6f92392f3a44c306d81ad7323c6291ef4f2`
- 状态：规格、合同、实现与组件证据已落盘；未提交、未推送、未合并、未发布
- 结论：**partial（可信预留与安全恢复组件通过，原生宿主恢复门槛未完成）**

## 1. 本批行为

原有实现把 `hold_resolution(allow)` 直接当成可观察执行权。审批后的两个并发请求都可能越过本地状态，
且服务端无法区分“工具尚未执行”和“工具已执行但结果未落盘”。本批改为：

1. 首次调用仍产生签名 hold decision，SIQ 管理窗口只写签名 resolution。
2. Hermes 不能暂停原钩子，因此用户在同一 session/task 下重试相同工具和参数；适配器重呈原调用
   身份并绑定新的 `tool_call_id`。
3. `/v1/hold-executions/reserve` 在同一引擎互斥区重验当前 Authority、Grant、SEC、安装内容、参数和
   期限，先写签名 `hold_reservation`，再向该请求返回 `reserved`。
4. 同一 hold 的第二次或并发预留返回冲突。`Observe` 必须引用 reservation receipt，直接引用原 hold
   receipt 继续拒绝。
5. 任意后续状态读取在没有 observation 时返回 `uncertain`；相同会话、工具和参数不能重新进入审批
   循环。只有补交已发生调用的结果后状态变为 `completed`。
6. 确认窗口合同升级到 `local-confirmations/v2`，展示 task、规范动作/效果、脱敏资源指纹、仅一次范围、
   平台恢复模式和 reserved/completed/uncertain 状态。
7. 管理员在外部核对后可以通过 `hold-execution-reconcile/v1` 签名记录 occurred/not_occurred；确认页
   绑定 reservation ID/hash 并明确该动作不调用工具。相同结论幂等、相反结论和错引用冲突。

## 2. 负向与恢复证据

Go 测试覆盖完整身份篡改、参数变化、未批准预留、当前 Grant 撤销、重复预留、16 路并发预留、直接用
原 hold 观察、重复/冲突结果、链恢复和只读状态查询。并发场景中只有取得唯一 reservation 的调用方
以 `O_CREATE|O_EXCL` 写入隔离临时文件，测试读取内容确认真实可观察副作用只发生一次。随后模拟“副作用
已发生、结果未落盘”并重启引擎：状态为 uncertain、新 task/call 仍不能生成新审批；人工核对临时文件后
补交原结果，状态转为 completed。人工结案测试另覆盖审批期限经过仍保持 uncertain、两种结论、错哈希、
重启恢复、迟到结果冲突以及旧预留不可复用。签名链可为 decision → hold_resolution → hold_reservation →
observation，或以 hold_reconciliation 结案。

Hermes 适配器测试覆盖 pending 轮询、批准后的唯一预留、post-hook 使用 reservation receipt、预留响应
丢失时移除内存提示并拒绝盲目执行。安装资产与仓库适配器逐字节一致。

接续独立复核又发现并修复一个过期边界：通用动作缓存原先会在 24 小时后删除未结案 reservation，重启恢复也会跳过其旧 decision，使可能已发生的副作用重新进入审批。当前实现先从完整签名链识别未结案 reservation，跨 24 小时恢复并保留 `uncertain`；它继续占用受限容量、出现在管理核对列表并阻断相同副作用，直到 observation 或管理员绑定原 reservation ID/hash 结案。新增测试同时覆盖运行中、越过窗口、重启、再次决策和过窗人工结案。

## 3. 本批验证

| 范围 | 结果 |
| --- | --- |
| Go 静态检查与全仓测试 | `gofmt -l .` 无输出；`go vet ./...`、`go test ./...` pass |
| 关键状态并发检查 | `go test -race` 覆盖 skillcontext/receipt/state/skillinstall/runtimeidentity/server，pass |
| R01 整合回归 | 重建候选后本地服务级活体 57/57 pass；证据 101/101 SHA256 pass且凭据扫描无匹配 |
| Hermes adapter `pytest` | 最终复跑 111 passed |
| adapter Ruff 与镜像一致性 | pass |
| Control API | 全量 `pytest -q` pass；只有既有 Starlette/httpx 弃用警告 |
| Web Vitest | 最终复跑 24 文件、93 项 pass |
| Web 构建 | 企业版与本地版 pass，embed 产物已同步 |
| 仓库级校验 | 平台验收 40 项、N09 证据 7 项、站点/Actions/Mermaid 与 `git diff --check` pass |

修复过期边界后的四目标 `CGO_ENABLED=0` 交叉构建通过：linux/amd64
`430679fa431e30a916e9319efd082d518a07e1b343f598531dcbf5826505226f`、linux/arm64
`f4b5c23cfff4f89608b1e113b36858c2938d6f8e06630b6e9031c7665c77420c`、darwin/arm64
`61e96f91b84b750ccbd6a7844e39fb1ab0c63adcf0da41267bb41199cf1739e0`、windows/amd64
`13641bcbe0de536c1341af586cc98078c7a24521368fe110af9140a3fbeee7a4`。交叉构建不替代系统实机验收。

最终 Linux/aarch64 候选与上述交叉构建为同一摘要 `f4b5c23c…7420c`；[R04-D 复验](r04d-final-candidate-20260914/report.md)又以该候选通过 R01 57/57、更新 7/7、会话与发现 30/30，并用真实 Hermes CLI 验证隔离 profile 的原生配置生命周期及无警告插件合同。它没有执行模型或宿主工具调用。

## 4. 未完成门槛

- 未在真实 Hermes 模型/插件进程中执行“hold → SIQ 批准 → 用户重试 → 真实工具 → post-hook”链路；
  当前适配器证据是 HTTP fixture，临时文件副作用是 Go 组件验收。
- OpenClaw 原生暂停/恢复、WorkBuddy、Windows/macOS 桌面通知与身份切换仍待对应平台批次。
- 同 Agent 两个真实 Skill 的跨权限原生重试仍依赖 R01 原生门槛。

因此 N06/R02 不能标记完成，也不能作为关闭 N09 或启动 T01–T06 的依据。
