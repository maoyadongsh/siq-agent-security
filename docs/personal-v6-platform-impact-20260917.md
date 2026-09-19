# v6 集成对 Windows/macOS 实机线的影响与复测交接

日期：2026-09-17。适用候选：本地 `codex/personal-v6-integration-20260917` 工作树的阶段成果；截至编写时未提交或合入 main，**不是**要求协作者现在改用此工作树。正式复测须由维护者给出同一提交或制品 SHA 后执行，按[共享验收规则](personal-platform-collaboration-acceptance-20260913-202355.md)分别记 Windows、macOS 与宿主格。

sunbo 的 [Windows 任务书](personal-windows-sunbo-taskbook-20260913-202355.md) 和 Luke 的 [macOS 任务书](personal-macos-luke-taskbook-20260913-202355.md) 继续有效。[2026-09-17 产品范围决策](personal-platform-scope-decision-20260917.md)将本机 Linux 限定为 Hermes/OpenClaw，取消全平台 CodeBuddy 新适配，不改变 Windows/macOS 的 OpenClaw、Hermes、WorkBuddy 三宿主职责。Luke 已阶段性推送，WorkBuddy 阶段性完成；sunbo 仍在开发，已推送部分分支。二者均需按同候选实机证据独立复核。本文件只列公共核心 v6 变动的影响，不重分配平台职责，也不把 Linux 组件测试计入其原生验收。

| 公共变化 | 两端需要核实的原生事实 | 失败时的归属与证据 |
| --- | --- | --- |
| 新 `POST /v1/openshell/task-executions` 独立于旧 `policy_apply` | 同候选真实宿主中，审批的 argv、目标沙箱 UUID、会话、Grant、SEC、策略摘要与任务启动逐项对应；同名新沙箱及不含 UUID 的旧原型批准不能复用。Linux 只测 OpenClaw/Hermes；Windows/macOS 按各自三宿主计划 | 保存脱敏请求/状态、签名回执 ID、候选 SHA、实际宿主与 OS，公共绑定缺陷交公共核心处理 |
| 执行前加载确认 | 记录各 OS 的实际 CLI 与网关版本；`policy set --wait`、`policy get --full` 的 `Loaded` 标记格式、目标/修订/摘要一致性。只读匹配、no-op、缺标记、重启/失联均不得绕过确认 | 原始含敏感配置的日志留本机私有目录；公开证据只留脱敏字段。CLI 输出格式差异交适配层，不放宽安全门 |
| 生效网络范围不超本次 `network_targets` | 有额外 allow 端点的策略被拒；必要端点完全批准时可正常执行。binary 限制仍须单列观察，不能从端点匹配推断完整最小权限 | 记录读回规则摘要与拒绝码；不把被拒当宿主不支持 |
| 本地停止、状态与对账 | 区分本地 CLI 进程退出和远端任务结束；停止响应读取 `stop` 或 `status.stop`；断线/重启后状态可读、不自动重放。若平台有单任务远端停止协议，先独立验证身份绑定再提公共 PR | 保留真实进程/结果证据，不以 UI 或 HTTP 200 推断远端停止 |
| 持久证据签名与并发停止 | 同候选上，计划/发起/结果/停止文件缺签名或被改动须 503 拒绝投影；成功需匹配签名 observation。重复执行键不得启动第二条不可停止的运行；停止记录落盘失败不得取消本地句柄 | 旧试验性无签名任务记录不自动升级或重放；迁移/恢复问题归公共状态合同，不由平台侧放宽验证 |
| 控制台任务详情 | 原生浏览器检查批准前意图、失败/超时/截断后的对账提示、非零退出码的归属限定，以及重新配对后旧状态失效 | 浏览器版本、窗口尺寸、真实点击记录及截图脱敏；前端公共问题回主线 |

Windows/macOS 各按三宿主矩阵独立写 `passed`、`partial`、`blocked` 或 `unverified`，注明 `native`/`controlled_start`/仅组件级。Linux 只验 Hermes/OpenClaw，WorkBuddy 占位格仅可按产品决策标 `out_of_scope`，不得冒充通过。CodeBuddy 不属于新矩阵，不安排新接入或宿主验收；其历史钩子与授权仅供安全退出。缺宿主运行时或上游能力时给出可复核解除条件；不复制另一 OS、另一候选或模拟 fixture 的 `complete_acceptance`。

复测前维护者应提供：同一候选提交或制品 SHA、Go/前端合同版本、脱敏 D05/E01–E13 预期结果、专属隔离目标及恢复基线。协作者仅修改各自平台适配与测试，公共权限/合同变化先通过 PR 协调，以免和本地集成树并发覆盖。
