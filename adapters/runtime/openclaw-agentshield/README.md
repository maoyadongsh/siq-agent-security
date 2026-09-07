# openclaw-agentshield（OpenClaw 适配器：L1 安装门禁 + L2 运行时）

两半：**安装门禁**由 OpenClaw 的 `security.installPolicy` 调用 `siq-agent-security policy-exec`（Go，在本仓 `apps/agentshield`）；**运行时**由本目录的插件把 `before_tool_call` / `after_tool_call` 接到决策 API。两半都不含规则、判定或密钥。

## L1 安装门禁

`~/.openclaw/openclaw.json`：

```json5
{
  security: {
    installPolicy: {
      enabled: true,
      targets: ["skill"],
      exec: {
        source: "exec",
        command: "/usr/local/bin/siq-agent-security",   // 绝对路径
        args: ["policy-exec"],
        timeoutMs: 10000,
        trustedDirs: ["/usr/local/bin"],
        passEnv: ["SIQ_AGENT_SECURITY_STATE_DIR", "HOME", "PATH"]
      }
    }
  }
}
```

`policy-exec` 读 stdin 的安装请求，对 `stagedPath` 跑 `siq-agent-security admit`，输出：

| admission verdict | decision | 说明 |
| --- | --- | --- |
| `quarantine` | `block` | reason 列出隔离类别 |
| `admit_with_conditions` | `warn` | 提示安装后 `siq-agent-security grant <admission_id>` |
| `admit` | `allow` | |
| 请求畸形 / 无路径 / 分析失败 | `block` | fail-closed（OpenClaw 在 exec 失败时同样 fail-closed）|
| `targetType != skill` | `warn` | 插件安装不在本策略范围 |

准入结论与 Skill Card 同时写入本机状态目录，控制台可见。

## L2 运行时

```bash
siq-agent-security adapter install openclaw
# writes plugin assets/manifest, registers plugins.load.paths + entry, and merges installPolicy (backup first)
```

| 决策 API `action` | 插件返回 |
| --- | --- |
| `allow` | 无决策 |
| `deny` | `{ block: true, blockReason }` |
| `hold` | 要求宿主检查点协议版本 1；先取得本地批准，再进入平台审批，执行前按最终参数重查授权；缺能力、拒绝、过期或失败在 block 下阻断 |
| `redact` | `{ params }`（改写后的参数） |

`after_tool_call` 把结果截断 64 KiB 发 `/v1/observe`（服务端脱敏、更新污点）。

插件目录包含 `openclaw.plugin.json` 和 package 的 `openclaw.extensions` 入口。安装器登记加载路径并启用本插件 entry；保留其他插件的配置，已有 allow 列表时追加本插件。全局插件禁用、本插件在 deny 列表或相关配置类型错误时拒绝安装。重装保留卸载归属；卸载删除本插件的运行时登记和自建文件。

适配器优先从 `OPENCLAW_STATE_DIR` 读取产品配置，未设置时使用 `~/.openclaw`。这支持原生平台的隔离测试实例；不是 OS 隔离保证。

## fail-closed

| 场景 | `block` | `audit_only` / `warn` |
| --- | --- | --- |
| 服务不可达 / 超时 / 401 / 非法 JSON / 无 token | `block: true` | 放行 + `console.warn` |
| OpenClaw 钩子 15 s 超时 | OpenClaw 自身 fail-closed | 同左 |

## 卸载

`siq-agent-security adapter uninstall openclaw` 从 `<state>/backups/adapters/` 还原 `openclaw.json` 并删除本插件目录。

## 验证状态

- `policy-exec`：Go 单测 + linux 隔离 HOME 证据（隐藏注释 Skill → block；官方风格 Skill → warn）。见 [`docs/evidence/agentshield/openclaw-linux-2026-09-05/`](../../../docs/evidence/agentshield/openclaw-linux-2026-09-05/)。
- 插件 TS：按 OpenClaw 2026-09 `before_tool_call` 合同编写（`block` 终止、`requireApproval` 首个生效、`params` 改写）。同一证据目录用插件会发出的 `/v1/decide` 请求体做了授前/授后 deny；**仍未**把插件加载进本机正在跑的 OpenClaw 网关进程。矩阵不标 `supported`。

V2：pre/post 传递 tool_call_id、action_id/decision_receipt_id；缓存最多 2048 项、TTL 300 秒，重复 ID 冲突不绑定旧动作。hold 的 execution observation 还必须有本地管理面批准记录；平台自身弹窗不自动创建本地批准。`node scripts/test-openclaw-adapter.cjs` 提供隔离的 mock hook 回归，真实平台 V2 归档仍为 unverified。

2026-09-07 21:11 的[原生失败证据](../../../docs/trusted-intent-v2-native-approval-gap-20260907-211105.md) 保留为历史基线。21:33 的[修复验收](../../../docs/trusted-intent-v2-approval-gate-validation-20260907-213332.md) 已通过六个原生场景：当前插件在进入平台审批前按完整动作身份和原参数确认本地批准，未批准或已拒绝时工具不执行。

本地批准等待默认 10 秒，可在本插件独立配置文件中设置 `holdWaitMs`（100–10000ms），整个 hook 最多使用 12 秒。管理操作者需先在本地控制台处理当前 hold，再处理平台审批；本地等待超时后本次调用阻断，迟到批准不会自动重试。平台审批仍受原 hold 剩余有效期限制。需要同时更新 daemon 与插件；旧 daemon 缺少状态接口时 block 下拒绝。该查询是执行前快照，完整真人流程和平台等待期间授权变化仍待验收。

2026-09-07 增量：[原生加载器及工具链验收](../../../docs/trusted-intent-v2-openclaw-validation-20260907-192539.md) 已在 OpenClaw 2026.5.12 / linux/arm64 的临时实例通过，包括 V2 关联、目录/工具拒绝、失联与重启。真实前置包装器和后置 relay 使用夹具提供的调用 ID，不等于完整网关/LLM 会话与平台审批验收；综合状态仍为 unverified。

20:16 增量：[完整 CLI 会话验收](../../../docs/trusted-intent-v2-openclaw-conversation-20260907-201600.md) 从真实 `agent --local` 入口驱动本地合成模型，验证原生 pre/post、跨进程续聊与显式新会话不继承权限。创建 Intent Binding 时，`session_id` 使用 hook 提供的原生 `sessionKey`（如 `agent:<id>:main`），并非 transcript UUID。模型历史可能规范化调用 ID，SIQ 回执仍严格按真实 pre/post 执行 ID 关联。网关审批和同 key reset 生命周期尚未验收。

20:36 增量：[空闲重置实测](../../../docs/trusted-intent-v2-openclaw-idle-reset-20260907-203600.md) 确认同 key 下 UUID 轮换不解除 SIQ 绑定或清除污点；但本机 OpenClaw 2026.5.12 仍将旧 transcript 发送给模型，整体重置测试失败。不能以 UUID 变化宣称上下文已清空。

21:51 增量：[原生网关重置验收](../../../docs/trusted-intent-v2-gateway-reset-and-ci-20260907-215104.md) 通过 `sessions.reset` → 本地 CLI 路径：只读客户端拒绝、旧 transcript 完整归档、新 Session header 和下一次模型请求均无旧工具历史；同一 routing key 的 SIQ 绑定及污点保持。活动文件可以复用原路径，重置是否成功应检查实际内容和模型请求。此结果不覆盖消息渠道，也不改变上述空闲重置失败结论。

22:00 增量：[平台等待期间 Grant 撤销](../../../docs/trusted-intent-v2-approval-revocation-20260907-220037.md) 已复现执行缺口：当前默认插件的本地预检通过后，等待平台审批时撤销 Grant 仍可能执行。宿主和适配器配套候选在独立副本通过八个场景，但未进入默认安装；原版没有可等待、可否决的审批后回调，不能仅添加异步 `onResolution` 就宣称修复。

22:08 增量：[候选检查点故障验收](../../../docs/trusted-intent-v2-checkpoint-faults-20260907-220834.md) 新增九个通过场景，覆盖超时、取消、异常、非法返回、最终参数篡改和审批后失联。实际原版组合未更新，该结果只属于配套候选的临时实例。

22:18 当前集成：[宿主能力识别及 18 场景验收](../../../docs/trusted-intent-v2-approval-integration-20260907-221813.md)。适配器源码与内嵌资产已包含 `beforeExecute` 重查，并要求原生 hook context 的 `approvalExecutionRecheckVersion: 1`；原版或旧候选 v1 缺少该能力时 block 下拒绝 hold，不会进入平台审批。此标记不能由用户配置或工具参数补齐。配套 v2 宿主在隔离副本保留正常执行并阻断撤销、参数篡改和故障；真实安装未自动升级，重新安装插件也不会替宿主打补丁。当前复测使用 `scripts/validate-openclaw-approval-integration.py`，旧候选脚本仅供旧指纹基线复核。

22:36 配套交付：[宿主升级、回退和恢复说明](../../../docs/trusted-intent-v2-checkpoint-upgrade-20260907-223635.md)。`scripts/openclaw-checkpoint-compat.py` 提供只读 inspect 和显式 apply/restore，使用固定指纹、私有原始备份与 POSIX 文件锁；完成修改后需重新启动目标运行时。已在完整临时副本验证升级后的批准/撤销及回退后拒绝，未修改本机安装；回退宿主不会使当前适配器在原版上自动恢复 hold 支持。
