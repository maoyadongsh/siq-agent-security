# Trusted Intent V2：宿主能力识别与审批检查点集成

- 时间：2026-09-07 22:18，Asia/Shanghai。
- 工作基线：`87fd1ce` 上的未提交增量。
- 状态：审批后检查已进入适配器源码及内嵌安装资产；配套宿主补丁 v2 在隔离副本验证通过，真实安装未更新。

## 1. 本轮解决的集成问题

此前候选适配器向 `requireApproval` 添加 `beforeExecute`，但原版 OpenClaw 会忽略未知回调。因此，只分发适配器候选不能保证检查点实际执行。当前适配器先检查**本次原生 hook context** 是否提供整数 `approvalExecutionRecheckVersion: 1`，再决定能否进入 hold 审批。

配套宿主补丁 v2 由实际执行包装器生成该字段，并保留上一版候选的可等待、可否决检查点。适配器不从工具参数、event、配置或环境变量采信宿主能力。缺失、未知版本、字符串和布尔值均视为不支持。

| 组合 | block 模式下的 hold 行为 |
| --- | --- |
| 当前适配器 + 原版宿主 | 明确阻断，提示 `native approval execution recheck unsupported`，不进入平台审批 |
| 当前适配器 + 旧候选宿主 v1 | 没有能力标记，按不支持处理 |
| 当前适配器 + 配套宿主 v2 | 本地批准 → 平台批准 → 对最终参数和现有授权再次检查 → 允许才执行 |

正常 allow/deny/redact 的映射保持原有行为；warn/audit_only 的失效处理仍为允许并记录 advisory。宿主能力字段是受信执行边界内的协议声明，不是密码证明，也不能防止恶意同进程插件伪造上下文或直接执行工具。

这是一项明确的 hold 兼容性要求。不能把原版宿主上的阻断描述为完整审批可用，也不能据此关闭所有旧版本兼容验收。

## 2. 默认适配器中的执行顺序

```text
SIQ /v1/decide 产生 signed hold
  → 检查原生 context 的检查点协议版本
  → 有界等待本地管理员批准
  → 请求平台审批，期限不超过原 hold 有效期
  → 宿主等待 beforeExecute(finalParams, signal)
  → 适配器以原动作身份和最终参数重查 /v1/hold-status
  → 严格 approved 且未取消才返回 true
  → 宿主允许调用工具
  → 原有 action/decision 强关联 Observe
```

本地首次等待仍默认十秒、整个前置 hook 预算十二秒；新增审批后查询预算一秒，宿主检查点上限五秒。接口不签发、不批准或续期，不需要管理 token。原 hold 到期、被消费、Grant 撤销、最终参数不匹配、取消和失联都不能通过重查。

主要文件为 [适配器源码](../adapters/runtime/openclaw-agentshield/index.ts) 和 [内嵌安装资产](../apps/agentshield/internal/adapterinstall/assets/openclaw/index.ts)，两者逐字节一致。配套宿主变更位于 [v2 补丁](../patches/openclaw/2026.5.12-approval-execution-recheck-v2.patch) 与 [固定指纹清单](../patches/openclaw/2026.5.12-approval-execution-recheck-v2.json)。上一版配套适配器补丁保留为历史实验产物，当前源码不再需要应用它。

## 3. 原生验收

[统一验收入口](../scripts/validate-openclaw-approval-integration.py) 直接使用当前源码适配器，不对适配器再打候选补丁。先在未修改的原生运行时验证不支持时的拒绝，再将运行时独立复制到临时目录，检查版本/源文件/补丁指纹、应用 v2 宿主补丁并验证实际工具路径。验收结束后，原安装及当前适配器源码指纹不变。

| 独立验收组 | 场景数 | 结果 | 回执 |
| --- | --- | --- | --- |
| 原版宿主 | 1 | 不支持的 hold 不进入平台审批，不执行工具 | 1 条，通过验签 |
| 普通审批 | 6 | 双方批准执行；两侧拒绝、本地超时、平台取消、失联均阻断 | 12 条，通过恢复验签 |
| 等待期间撤销 | 2 | 正常对照执行；Grant 撤销完成后平台再批准也不执行 | 5 条，通过验签 |
| 检查点故障 | 9 | 异常、非法返回、超时、取消、最终参数改写、审批后失联均不执行，正常批准执行 | 19 条，通过恢复验签 |

合计 18 个场景通过，入口退出码 0。上述四组使用各自独立的临时状态和回执链，不是一条合并签名链。最终参数改写仍由真实 SIQ HTTP 返回 `400 / hold_identity_mismatch`；失联在原生平台审批事件出现之后注入。故障场景包装真实回调的测试边界沿用 [九场景验收说明](trusted-intent-v2-checkpoint-faults-20260907-220834.md)。

证据：[native-openclaw-approval-integration-20260907.json](evidence/intent-v2/native-openclaw-approval-integration-20260907.json)，包含各组实际适配器、原生运行时、脚本和二进制指纹，并明确区分 stock 与临时 checkpoint-v2 副本。

## 4. 使用与升级边界

复测当前源码的推荐入口：

```bash
python3 scripts/validate-openclaw-approval-integration.py \
  --openclaw-root /path/to/node_modules/openclaw \
  --node /path/to/node \
  --out /tmp/openclaw-approval-integration.json
```

要求 Go、Python、Node、Git 和兼容版本的原生安装。该命令在临时副本验收，不升级本机安装，也不保留可直接切换的常驻实例。

部署当前适配器时，daemon、适配器与宿主能力需匹配：daemon 提供强关联 hold-status，适配器含本次能力检查与执行回调，宿主提供协议版本 1 及真正等待回调的执行路径。更新 SIQ 二进制及运行 `adapter install openclaw` 只更新插件，不会自动修改 OpenClaw 包。若宿主仍为原版，应预期 hold 明确阻断；不能通过添加用户配置字段来解除。

真实宿主的升级、回退和运行中的会话切换尚待交付验收。v2 补丁限定 OpenClaw 2026.5.12 的原始文件指纹，不能对未知版本或部分修改的文件模糊应用。它是本地候选协议扩展，尚非官方 SDK 能力。

旧的 v1 候选 runner 保留作为历史入口，其适配器指纹属于此前基线；在当前源码上失败退出是预期的版本保护。复核历史实验需使用归档所指向的旧源码，不能修改历史哈希或把当前结果覆盖到旧失败证据上。

## 5. 本地门禁与剩余工作

- OpenClaw mock 测试通过：缺失/错误宿主版本、event/params 伪造能力、真实回调存在、批准后状态变化、失联与取消，以及 warn/audit_only 的失效处理。
- `apps/agentshield` 的 `go test -race ./...`、`go vet ./...` 通过；linux/amd64、linux/arm64、darwin/arm64、windows/amd64 构建通过。
- 新增及修改 Python 脚本 Ruff、JavaScript 语法、源指纹、JSON、链接和诚实性检查通过。未改变 HTTP/JSON Schema 合同，未重复执行无关 Python/Web 全量测试。

当前源码已避免在缺少可靠检查点的宿主上继续执行 hold；配套宿主保留正常审批功能并通过上述负向验收。实际安装未升级、协议未上游采纳、检查点后的竞态和真实副作用原子性未证明。消息渠道生命周期、CodeBuddy 实机、完整旧版本兼容和独立复核仍按目标报告跟踪，本轮不能关闭总目标。

本轮改动尚未提交或取得对应 CI；已推送 `87fd1ce` 的绿色 CI 仅作为此前基线证据。
