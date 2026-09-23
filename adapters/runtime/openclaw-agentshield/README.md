# openclaw-agentshield（OpenClaw 运行时适配器）

插件将 `before_tool_call` / `after_tool_call` 接到本机决策 API，不包含规则、判定或签名密钥。

2026-09-18 会话轮换修复（#77）：当前运行身份为 `openclaw-session/v1:<sha256>`，同时绑定宿主 hook context 的 `sessionKey` 与 `sessionId` UUID。旧文档中的 raw `sessionKey` 绑定仅作为历史证据保留，不再用于新版本授权。新插件不接受 event、工具参数、模型或配置提供的 epoch；宿主缺字段时所有模式拒绝，并提示更新宿主/适配器。旧绑定须以真实宿主元数据重新建立，不能猜测 UUID 或自动继承；managed 模式按已验证实例权限自动建立新 epoch 的独立 Intent。daemon 与插件须成对更新，详细编码和兼容边界见 [会话规格](../../../docs/openclaw-native-session-spec-v1.md)。实现与组件检查不代表原生 idle/reset 回归已通过。

## 当前接入与研究边界

Linux/macOS/Windows 的产品范围与实际证据见[平台矩阵](../../../platforms/support-matrix.md)。原生 Skill 安装策略、插件加载、会话授权和审批后检查点是四项独立能力。当前实际 CLI 为 OpenClaw 2026.9.5；库存档与带固定检查点补丁的受控副本分别记账。OC-01 的 20/20 来自“库存失败关闭 + 私有受控副本”，不证明上游原版已补齐审批后最终检查。

当前受控使用入口见[Linux 启动说明](../../../docs/openclaw-controlled-start-linux-20260919.md)和[补丁索引](../../../patches/openclaw/README.md)。旧 raw sessionKey 绑定、历史失败与后续修复在下文按日期保留，不能用旧会话例子签发新 epoch 权限。核心机制是把宿主真实会话、最终动作参数和唯一执行预留关联起来，防止批准被挪用于其他调用。

2026.9.5 的权威支持档位见[兼容清单](../../../patches/openclaw/compatibility.v1.json)：库存档允许普通 allow/deny/redact，但 hold 因缺少检查点协议 v1 而失败关闭；只有库存源码、受控源码、补丁和本适配器四个摘要全部匹配的私有副本可进入受控 hold 档。受控启动器会复核清单，不能通过用户配置或版本字符串伪造能力。

## Skill 安装检查

请通过 SIQ 的 Skill 导入、检查和确认安装流程安装 Skill。已验证的 OpenClaw 2026.5.12 不接受顶层 `security.installPolicy`；默认安装器仍不写入该字段。OpenClaw 2026.9.4 已支持 operator-owned `security.installPolicy`，可在确认目标实例版本后显式执行 `siq-agent-security adapter preview openclaw install --enable-install-policy`、审阅后执行 `adapter install openclaw --enable-install-policy`。此策略只覆盖原生 Skill 安装/更新，不覆盖 Plugin；未知既有策略不得覆盖。

`policy-exec` 使用 OpenClaw 协议 v1 的 `sourcePath`/`sourcePathKind` 和 `protocolVersion`，错误或持久化失败时阻断。历史本产品配置仅在归属记录和完整策略内容匹配后迁移；卸载剥离本产品精确策略，未知用户配置保留。本机 2026.9.4 的公开 `skills install` 已在隔离 HOME/profile 上实测恶意 Skill 安装前被拒、干净 Skill 安装成功及卸载还原；这不证明其他宿主或旧版支持。

## L2 运行时

```bash
siq-agent-security adapter install openclaw
# 默认只登记插件，不启用装前策略；旧版/未知版保持这个默认
```

| 决策 API `action` | 插件返回 |
| --- | --- |
| `allow` | 无决策 |
| `deny` | `{ block: true, blockReason }` |
| `hold` | 要求宿主检查点协议版本 1；本地批准、平台批准、最终参数重查后原子取得签名执行预留；缺能力、拒绝、过期、预留失败或响应丢失时阻断 |
| `redact` | `{ params }`（改写后的参数） |

`after_tool_call` 把结果截断 64 KiB 发 `/v1/observe`（服务端脱敏、更新污点）。普通调用绑定原决策；批准后的 hold 使用适配器派生的执行尝试 ID，并绑定签名 reservation 回执。预留已写但响应丢失时状态为 uncertain，不能盲目再执行。

插件目录包含 `openclaw.plugin.json` 和 package 的 `openclaw.extensions` 入口。安装器登记加载路径并启用本插件 entry；保留其他插件的配置，已有 allow 列表时追加本插件。全局插件禁用、本插件在 deny 列表或相关配置类型错误时拒绝安装。重装保留卸载归属；卸载删除本插件的运行时登记和自建文件。

适配器优先从 `OPENCLAW_STATE_DIR` 读取产品配置，未设置时使用 `~/.openclaw`。这支持原生平台的隔离测试实例；不是 OS 隔离保证。

## fail-closed

| 场景 | `block` | `audit_only` / `warn` |
| --- | --- | --- |
| 非托管服务不可达 / 超时 / 401 / 非法 JSON / 无 token | `block: true` | 放行 + `console.warn` |
| 托管身份验证或决策失败 / 非法配置 / 非本机地址 | `block: true` | `block: true` |
| 缺失/非法宿主 sessionKey 或 sessionId；后端旧 raw key | 拒绝 | 拒绝 |
| OpenClaw 钩子 15 s 超时 | OpenClaw 自身 fail-closed | 同左 |

## 卸载

`siq-agent-security adapter uninstall openclaw` 按安装记录移除本插件注册与自建文件，保留其他用户配置；首次备份供人工恢复参考。

## 验证记录（按候选与时间区分）

- `policy-exec`：Go 单测 + linux 隔离 HOME 证据（隐藏注释 Skill → block；官方风格 Skill → warn）。见 [`docs/evidence/agentshield/openclaw-linux-2026-09-05/`](../../../docs/evidence/agentshield/openclaw-linux-2026-09-05/)。
- 插件 TS：按 OpenClaw 2026-09 `before_tool_call` 合同编写（`block` 终止、`requireApproval` 首个生效、`params` 改写）。同一证据目录用插件会发出的 `/v1/decide` 请求体做了授前/授后 deny；该 2026-09-05 记录**未**把插件加载进网关进程；后续原生记录见下文，不回写早期范围。

V2：pre/post 传递 tool_call_id、action_id/decision_receipt_id；缓存最多 2048 项、TTL 300 秒，重复 ID 冲突不绑定旧动作。hold 的 execution observation 必须绑定本地批准后生成的签名 reservation；平台自身弹窗不创建本地批准。`node scripts/test-openclaw-adapter.cjs` 提供隔离 hook 回归，原生宿主验收见本节后续记录。

2026-09-21 OC-01 当前验收：实际 `OpenClaw 2026.9.5 (ec9c1a1)` 的库存业务 hold 安全拒绝；固定受控副本完成 20 个原生场景，覆盖普通审批、平台取消、本地失联、平台等待期间撤权、回调抛错/拒绝/非法返回/超时/取消、最终参数变化，以及与 Hermes BU-01 同名的报告发布工具。46 条回执链验签，四条允许路径各有唯一 reservation/observation，其余零执行。适配器原生场景 50 项和业务合同 harness 通过。该结果使用合成 operator 与本地效果，详见 [OC-01 证据](../../../docs/evidence/flagship-optimization-20260921/oc-01-openclaw-parity.json)。

2026-09-07 21:11 的[原生失败证据](../../../docs/trusted-intent-v2-native-approval-gap-20260907-211105.md) 保留为历史基线。21:33 的[修复验收](../../../docs/trusted-intent-v2-approval-gate-validation-20260907-213332.md) 已通过六个原生场景：当前插件在进入平台审批前按完整动作身份和原参数确认本地批准，未批准或已拒绝时工具不执行。

本地批准等待默认 10 秒，可在本插件独立配置文件中设置 `holdWaitMs`（100–10000ms），整个 hook 最多使用 12 秒。管理操作者需先在本地控制台处理当前 hold，再处理平台审批；本地等待超时后本次调用阻断，迟到批准不会自动重试。平台审批仍受原 hold 剩余有效期限制。需要同时更新 daemon 与插件；旧 daemon 缺少状态接口时 block 下拒绝。该查询是执行前快照，完整真人流程和平台等待期间授权变化仍待验收。

2026-09-07 增量：[原生加载器及工具链验收](../../../docs/trusted-intent-v2-openclaw-validation-20260907-192539.md) 已在 OpenClaw 2026.5.12 / linux/arm64 的临时实例通过，包括 V2 关联、目录/工具拒绝、失联与重启。真实前置包装器和后置 relay 使用夹具提供的调用 ID，不等于完整网关/LLM 会话与平台审批验收；综合状态仍为 unverified。

20:16 增量：[完整 CLI 会话验收](../../../docs/trusted-intent-v2-openclaw-conversation-20260907-201600.md) 从真实 `agent --local` 入口驱动本地合成模型，验证原生 pre/post、跨进程续聊与显式新会话不继承权限。该旧候选创建 Intent Binding 时，`session_id` 使用 hook 提供的原生 `sessionKey`（如 `agent:<id>:main`），并非 transcript UUID。模型历史可能规范化调用 ID，SIQ 回执仍严格按真实 pre/post 执行 ID 关联。网关审批和同 key reset 生命周期尚未验收。

20:36 增量：[空闲重置实测](../../../docs/trusted-intent-v2-openclaw-idle-reset-20260907-203600.md) 确认同 key 下 UUID 轮换不解除 SIQ 绑定或清除污点；但本机 OpenClaw 2026.5.12 仍将旧 transcript 发送给模型，整体重置测试失败。不能以 UUID 变化宣称上下文已清空。

21:51 增量：[原生网关重置验收](../../../docs/trusted-intent-v2-gateway-reset-and-ci-20260907-215104.md) 通过 `sessions.reset` → 本地 CLI 路径：只读客户端拒绝、旧 transcript 完整归档、新 Session header 和下一次模型请求均无旧工具历史；同一 routing key 的 SIQ 绑定及污点保持。活动文件可以复用原路径，重置是否成功应检查实际内容和模型请求。此结果不覆盖消息渠道，也不改变上述空闲重置失败结论。

22:00 增量：[平台等待期间 Grant 撤销](../../../docs/trusted-intent-v2-approval-revocation-20260907-220037.md) 已复现执行缺口：当时默认插件的本地预检通过后，等待平台审批时撤销 Grant 仍可能执行。宿主和适配器配套候选在独立副本通过八个场景，但未进入默认安装；原版没有可等待、可否决的审批后回调，不能仅添加异步 `onResolution` 就宣称修复。

22:08 增量：[候选检查点故障验收](../../../docs/trusted-intent-v2-checkpoint-faults-20260907-220834.md) 新增九个通过场景，覆盖超时、取消、异常、非法返回、最终参数篡改和审批后失联。实际原版组合未更新，该结果只属于配套候选的临时实例。

22:18 当前集成：[宿主能力识别及 18 场景验收](../../../docs/trusted-intent-v2-approval-integration-20260907-221813.md)。适配器源码与内嵌资产已包含 `beforeExecute` 重查，并要求原生 hook context 的 `approvalExecutionRecheckVersion: 1`；原版或旧候选 v1 缺少该能力时 block 下拒绝 hold，不会进入平台审批。此标记不能由用户配置或工具参数补齐。配套 v2 宿主在隔离副本保留正常执行并阻断撤销、参数篡改和故障；真实安装未自动升级，重新安装插件也不会替宿主打补丁。当前复测使用 `scripts/validate-openclaw-approval-integration.py`，旧候选脚本仅供旧指纹基线复核。

22:36 配套交付：[宿主升级、回退和恢复说明](../../../docs/trusted-intent-v2-checkpoint-upgrade-20260907-223635.md)。`scripts/openclaw-checkpoint-compat.py` 提供只读 inspect 和显式 apply/restore，使用固定指纹、私有原始备份与 POSIX 文件锁；完成修改后需重新启动目标运行时。已在完整临时副本验证升级后的批准/撤销及回退后拒绝，未修改本机安装；回退宿主不会使当前适配器在原版上自动恢复 hold 支持。

## 托管 Runtime Identity 模式（2026-09-13，v0.3.0）

Managed 安装器写入 camelCase 配置 `runtimeIdentityId` / `agentId` / `tokenPath` 后，插件进入托管模式，行为对齐 Hermes 托管桥（`adapters/runtime/hermes-agentshield/__init__.py`）：

- **凭据校验**：托管 token 文件必须是 `ri-<32hex>.<64hex>` 且前缀匹配 `runtimeIdentityId`；符号链接拒绝（`lstat`），超过 512 字符拒绝。旧的全局 token 不能充当托管身份。
- **逐调用注册**：每次 `before_tool_call` 先向 `/v1/runtime-sessions` 发 `local-runtime-session-enroll/v1`，严格校验 8 字段响应（platform 必须是 `openclaw`、identity/agent/session 一致、`bind-*` / `int-ri-*` 格式）；注册失败或响应异常在 block 模式 fail-closed，且不会进入 `/v1/decide`。
- **原生原文捕获（best effort，250ms 预算）**：allow 后把参数按 JSON pointer 展平（`/tool/name` + `/tool/arguments/...`），observe 带决策引用时把结果按 `/tool/result/...` 捕获，POST `/v1/raw-task-content/native-captures`（期望 201）。层级 ≤32、路径 ≤256、字段 ≤1024、单值 ≤1MiB，超界即放弃本次捕获。daemon 拥有原文采集策略与 secret 过滤，适配器不读原文开关。
- 非托管（legacy）路径行为不变：不注册、不捕获。

验证：`node --experimental-strip-types --test tests/managed-bridge.test.mjs`（覆盖 legacy/托管注册、身份与 URL 边界、三种模式、参数/输出捕获、hold 相关性、签名预留拒绝/畸形响应/响应丢失及重复回调）。测试通过 resolution hook 替换 OpenClaw SDK 入口并用 mock 本地服务驱动真实 hook handler，**不是**真实 OpenClaw 网关验收；原生范围另见对应证据报告。

凭据仅发送至显式端口的 HTTP loopback，localhost 固定为 127.0.0.1，不跟随重定向。托管模式要求真实会话、有效身份凭据及带 action/receipt 的允许裁决。输出原文仅在允许执行或 hold 最终复验通过后按精确调用关联采集一次；重复调用保持失效至关联过期。

macOS Homebrew OpenClaw 2026.9.4 的默认会话仓是 `agents/<id>/agent/openclaw-agent.sqlite`（`session_nodes.session_key`），不再写 `sessions/sessions.json`。该段记录历史版本行为；当前插件使用 hook 提供的 `sessionKey` 与 `sessionId`，不读取宿主会话文件，具体以本文开头的会话轮换说明为准。实测夹具若要对账原生会话身份，必须读当前版本实际存储，不能假定 2026.5.12 的 JSON 路径。
