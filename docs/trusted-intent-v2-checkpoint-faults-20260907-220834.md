# Trusted Intent V2：审批后检查点故障与最终参数验收

- 时间：2026-09-07 22:08，Asia/Shanghai。
- 仓库基线：`87fd1ce` 加当前未提交测试与文档增量。
- 候选：固定指纹的 OpenClaw 2026.5.12 宿主补丁与配套 SIQ 适配器补丁，内容与 [22:00 撤销验收](trusted-intent-v2-approval-revocation-20260907-220037.md) 相同。
- 结论：新增九个原生场景全部通过，19 条回执恢复验签通过。验证范围是临时副本，默认产品组合仍未采用候选。

## 1. 本轮验证的问题

上一轮已证明候选阻断“Grant 撤销完成后，平台才批准”的执行顺序。本轮补充检查点本身失败时的行为，确认正常路径仍调用实际授权接口，错误路径不会以非布尔真值、异常、超时或取消绕过否决，同时确认平台最终参数进入原参数摘要校验。

实际启动原生网关，使用真实插件加载器、hook runner、前置包装器和 operator WebSocket。每个场景首先经真实 SIQ daemon 签发 hold，由合成管理员通过管理接口批准，收到原生平台审批事件后才回复 `allow-once`。工具执行器只写临时标记文件；进入执行器就记录调用，不以断言提前抛错来伪装“没有执行”。

## 2. 故障注入边界

[原生 worker](../scripts/openclaw-approval-checkpoint-fault-worker.mjs) 在临时进程中包装实际加载的 SIQ `before_tool_call` handler；先执行原 handler，取得真实本地批准及候选 `beforeExecute` 回调，再按场景注入错误。这没有修改实际宿主安装或签名 Grant，也没有替换原生审批管理器、执行包装器或 HTTP 授权服务。

- 异常、拒绝、非法返回、挂起与取消场景替换该次检查点回调，验证宿主执行否决语义。这些场景不能被描述为真实生产网络故障。
- 参数场景保留真实适配器检查点，在 hook 返回值中提供不同的 `params`，由原生 hook 合并逻辑交给执行包装器。测试明确检查最终参数已变化，且实际 SIQ HTTP 返回 `400 / hold_identity_mismatch`。它证明此合并入口的最终参数绑定，不证明所有恶意插件或任意执行后变参路径。
- 失联场景保留真实回调。在平台审批请求已出现后、发送平台允许之前强杀临时 SIQ daemon，确保模拟的是审批后的重查失联。调用结束后重启 daemon 验证回执链。
- HTTP 观测位于已有测试 I/O guard 之后，只保存状态码、reason code 和是否发生传输错误；不归档 token、参数正文或原生日志。

## 3. 原生测试结果

| 场景 | 检查点证据 | 工具执行 | observation |
| --- | --- | --- | --- |
| 正常批准 | 实际 HTTP `200 / hold_approved`；回调执行一次 | 1 | 1 |
| 同步抛异常 | 回调执行一次并抛出合成错误 | 0 | 0 |
| Promise 拒绝 | 回调执行一次并返回 rejected Promise | 0 | 0 |
| 返回 undefined | 不满足严格 `true` | 0 | 0 |
| 返回真值字符串 | 返回 `"approved"`，不满足严格 `true` | 0 | 0 |
| 回调永不完成 | 宿主五秒预算触发，回调收到 aborted signal | 0 | 0 |
| 回调期间取消 | 外部取消传播；即使回调随后返回 true，也不得执行 | 0 | 0 |
| 最终参数被改写 | 实际 HTTP `400 / hold_identity_mismatch` | 0 | 0 |
| 平台等待后强杀 daemon | 真实回调发生传输失败 | 0 | 0 |

九个场景均严格检查候选回调只执行一次；只有正常批准进入工具执行器。超时断言为实际耗时至少 4.8 秒且小于 10 秒，用于识别五秒计时器是否生效并容纳调度误差，不是产品 SLA。取消场景验证取消与返回 true 的竞争，不声称永不响应取消的任意回调会在五秒预算之前立即结束。

合计 19 条签名回执，包含九个 Decision、九个管理批准记录及一个正常 Observation。daemon 强杀恢复后，HTTP 读取及离线 CLI `verify` 均通过。最终入口退出码 0，`passed=true`、`installed_source_unchanged=true`、`shipping_adapter_unchanged=true`。

完整归档：[native-openclaw-checkpoint-faults-20260907.json](evidence/intent-v2/native-openclaw-checkpoint-faults-20260907.json)。记录每个场景的回调次数、耗时、HTTP 摘要、取消状态、执行与 observation 数量，并区分基线源文件和实际加载的候选适配器指纹。

## 4. 复现与产物

| 文件 | 用途 |
| --- | --- |
| [validate-openclaw-checkpoint-fault-patch.py](../scripts/validate-openclaw-checkpoint-fault-patch.py) | 核对双侧源指纹和补丁指纹，在独立临时副本应用配套补丁并运行验收 |
| [validate-intent-v2-openclaw-checkpoint-faults.py](../scripts/validate-intent-v2-openclaw-checkpoint-faults.py) | 实际管理 API、平台事件同步、审批后 daemon 强杀及回执恢复验证 |
| [openclaw-approval-checkpoint-fault-worker.mjs](../scripts/openclaw-approval-checkpoint-fault-worker.mjs) | 原生组件执行、明确的故障注入和无敏感正文的 HTTP 观测 |

从仓库根目录运行，需要 Go、Python、Node、Git 和兼容原生安装：

```bash
python3 scripts/validate-openclaw-checkpoint-fault-patch.py \
  --openclaw-root /path/to/node_modules/openclaw \
  --node /path/to/node \
  --out /tmp/openclaw-checkpoint-faults.json
```

外层入口负责应用两个候选补丁；直接运行内层脚本而未提供配套候选会明确失败。原版撤销失败、上一轮候选八场景通过和本轮九场景故障验收分别归档，不互相覆盖。本轮没有修改上轮候选补丁或重跑其未变化的八个已通过场景。

## 5. 剩余边界

本轮关闭候选检查点的这些故障注入待测项，不能将局部测试外推为默认安装已修复、正式 SDK 兼容、恶意同 UID 隔离或与外部工具副作用原子提交的执行租约。仍需处理宿主能力协商与配套升级、检查点之后的并发状态变化，以及目标报告中列出的真实用户、消息渠道、旧版本兼容、CodeBuddy 实机和独立复核。

新脚本的 Ruff、JavaScript 语法、证据指纹、JSON、文档链接及诚实性检查通过。本轮新增文件尚未提交；`87fd1ce` 的绿色 CI 不包含这些新增脚本。
