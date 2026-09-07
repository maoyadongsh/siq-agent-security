# Trusted Intent V2：执行前本地审批门禁修复与原生验收

- 时间：2026-09-07 21:33，Asia/Shanghai。
- 工作基线：`78e740a01fa9c46cfb256fa2d84c2cf0739bdb2e` 上的未提交增量。
- 状态：已修复并通过本地及原生网关限定场景；尚未提交、推送或取得新代码对应 SHA 的 CI。

## 1. 问题与当前行为

[21:11 失败报告](trusted-intent-v2-native-approval-gap-20260907-211105.md) 已复现平台批准后、本地未批准或已拒绝的工具仍被调用。本轮将本地批准检查移到适配器返回平台 `requireApproval` 之前。顺序成为：

```text
SIQ 签名 hold
  → 按完整动作身份查询本地批准
  → pending 时有界等待
  → approved 且仍有效，才请求平台审批
  → 平台允许才调用工具
  → 原有强关联 Observe
```

双方允许仍可执行；本地 pending 超时、denied、expired、consumed、身份错误、服务不可达在 block 下均阻断。平台自己的拒绝和取消继续阻断。旧的失败归档保留，不改成通过。

## 2. 只读接口与权限边界

新增 `POST /v1/hold-status`，请求和响应合同分别为 [hold-status-request.v1](../packages/contracts/hold-status-request.v1.schema.json) 与 [hold-status.v1](../packages/contracts/hold-status.v1.schema.json)。

请求必须包括 platform、session_id、agent_id、tool、tool_call_id、action_id、decision_receipt_id 和原 params。服务端按 action_id 查询已有动作，再逐项比对身份和参数摘要。响应仅包括状态、原动作 ID、原决策回执 ID、有效期和 reason_code；不返回参数原文、管理主体或凭据。

此接口使用 capDecision，不能批准、签发、覆盖或续期。匿名与错误 token 返回 401，伪造批准字段、额外 JSON 文档、缺失/错误身份与参数返回 400。原 `POST /v1/hold/{receipt_id}` 继续仅允许管理会话；decision token 仍为 403。

内部只新增一个有界动作记录上的 `holdResolved` 标记，用于区分未处理与已拒绝。它与既有批准和 observation 状态均从已验签回执重建，不新增无界缓存或另一套签名算法。查询不追加回执、不改变 task_seq、不续期；原 hold 到期边界、已观察或当前 Grant/Intent/Session 权威不再匹配时不会返回 approved。

主要实现：[receipt/hold_status.go](../apps/agentshield/internal/receipt/hold_status.go)、[server/hold_status.go](../apps/agentshield/internal/server/hold_status.go)、[OpenClaw adapter](../adapters/runtime/openclaw-agentshield/index.ts)。内嵌安装资产已同步。

## 3. 等待预算与使用方式

`OPENCLAW_STATE_DIR/siq-agent-security.json`（未设置时为 `~/.openclaw/siq-agent-security.json`）新增 `holdWaitMs`，默认 10000，合法范围 100–10000ms。每次 HTTP 受既有 timeoutMs 和总剩余等待预算限制；从进入 hook 起最多使用 12 秒，给原生 15 秒门禁保留余量。取消监听与定时器在完成后清理。

管理操作者需在本地控制台中处理当前 hold，然后再处理平台审批。本地等待超时后，这次调用已阻断；迟到批准不会自动重新执行。平台审批超时使用原 hold 剩余有效期，并显式设置 timeoutBehavior=deny。

这是当前可工作的有界双重审批流程，仍需改进人类交互体验，不能将其描述为无期限等待审批。部署时必须同时更新 daemon 和适配器：重新构建本地二进制后，通过 `adapter install openclaw` 更新内嵌插件，再按平台方式加载更新。仅更新插件而保留旧 daemon 时，新增接口不可用，block 下会拒绝；本轮未操作实际安装或运行配置。

warn/audit_only 的正常响应仍由 daemon 产生 allow/advisory；没有把这些档位声明为强制阻断模式。此次原生验收使用 optional/block 的未绑定 exec；required/bound 下 opaque shell 的 unknown 副作用拒绝未被放宽。

## 4. 原生网关结果

使用本机 OpenClaw 2026.5.12 的真实插件加载器、网关、operator WebSocket、审批处理和前置包装器。操作者与工具执行器为合成夹具，工具只写临时标记，不执行 shell 字符串或调用模型。

| 场景 | 本地状态/处理 | 平台结果 | 工具执行 | 正常 observation |
| --- | --- | --- | --- | --- |
| platform-deny | 批准 | deny | 否 | 0 |
| both-approve | 批准 | allow-once | 是 | 1 |
| local-missing | 始终 pending，等到本地预算耗尽 | 未进入平台审批 | 否 | 0 |
| local-reject | 拒绝 | 未进入平台审批 | 否 | 0 |
| platform-cancel | 批准 | 等待平台期间取消 | 否 | 0 |
| local-offline | pending 时强杀 daemon | 未进入平台审批 | 否 | 0 |

六场景全部通过，最终退出码 0，12 条回执在 daemon 重启后通过 HTTP 与离线验签。原生夹具将本地等待预算设为 1500ms，以测试实际超时；产品默认仍为 10000ms。

取消场景有一项明确的夹具清理步骤：原生取消已返回且确认工具未执行后，合成 operator 将仍 pending 的网关请求置为 deny，避免该请求的等待 RPC 一直存活到 TTL。不能据此宣称平台自身已自动清理所有取消请求。after relay 仍由夹具调用，不是完整模型会话。

原始摘要：[native-openclaw-approval-gate-20260907.json](evidence/intent-v2/native-openclaw-approval-gate-20260907.json)。记录当前 SIQ 二进制、生产源文件、脚本、适配器和相关 OpenClaw 源文件指纹；不是完整回执导出包或整个模块加载追踪。测试源码与归档指纹已逐项核对。

复测命令（仓库根目录）：

```bash
python3 scripts/validate-intent-v2-openclaw-approval-gate.py \
  --openclaw-root /home/maoyd/.nvm/versions/node/v22.22.1/lib/node_modules/openclaw \
  --node /home/maoyd/.nvm/versions/node/v22.22.1/bin/node \
  --out /tmp/siq-openclaw-approval-gate.json
```

旧 `validate-intent-v2-openclaw-approval.py` 保存的是平台先行的缺陷复现流程，供旧基线使用。当前代码应使用新的 gate 验证脚本；不能把旧流程等不到平台请求的超时当作新实现的正确验收。

## 5. 回归与门禁

| 检查 | 结果 |
| --- | --- |
| HoldStatus 身份/参数篡改、只读、批准/拒绝恢复、并发查询、到期边界、已观察、Grant 撤销 | 通过 |
| HTTP 原始 bearer 分权、伪造 approve、额外 JSON 文档、恢复后状态 | 通过 |
| Go 返回值合同样例与 Python schema：合法、必填、未知属性、非法日期、状态/reason 不一致 | 通过 |
| `node scripts/test-openclaw-adapter.cjs`：等待后批准、拒绝、过期、重复消费、错动作、非法时间、超时、断连、取消 | 通过 |
| `apps/agentshield`: `go test -race ./...`、`go vet ./...` | 全模块通过 |
| linux/amd64、linux/arm64、darwin/arm64、windows/amd64 构建 | 通过，制品在临时目录 |
| Control API：`test_intent_v2_contracts.py` 与 `test_schema_contracts.py` | 117 通过，一个既有依赖弃用警告 |
| 新增 Python 脚本 Ruff、JavaScript 语法、来源指纹与文档链接 | 通过 |

## 6. 尚未关闭的验收

本轮已关闭所复现的“本地未批准/拒绝而平台允许执行”路径，但本地状态查询仍是一个执行前快照，不是外部工具执行租约。平台审批等待期间的授权变化、完整真人流程及其他插件参与改参的执行边界仍需独立验证，不能将本轮结果外推为所有平台路径的持续授权保证。

CodeBuddy 实机、旧适配器完整兼容、OpenClaw 网关 reset 与原版重置修复采纳、独立安全复核仍待完成。当前工作树增量未取得新 SHA 的远端 CI，不能复用 `78e740a` 的绿色结果。能力矩阵保持综合 unverified，V2 总目标继续进行中。
