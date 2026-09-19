# OpenClaw 原生会话身份 v1（#77）

OpenClaw 2026.9.4 的 `sessionKey` 是可跨会话轮换复用的路由键。真实 idle rollover 证据证明同一 key 的 `sessionId` UUID 变化后，旧插件仍沿用旧 Intent。因此权限、审批、执行关联与观察必须绑定 key **及**原生 UUID，不能仅绑定路由键。

## 身份编码与事实来源

新编码合同为 `openclaw-session/v1:<sha256>`。摘要原像精确为 UTF-8 字节：`openclaw-native-session/v1`、一个 NUL、原始 `sessionKey`、一个 NUL、原始 `sessionId`。key 必须非空、最多 256 UTF-8 字节、无 C0/DEL 控制字符且为有效 Unicode；UUID 必须为小写标准 8-4-4-4-12 十六进制。不得 trim、大小写折叠、截断或接受替代字段。

插件只读取宿主传给 before/after hook 的 `ctx.sessionKey` 和 `ctx.sessionId`。不读取 event/params/model output/config/environment 中的同名字段，不补默认 key/epoch；缺失或非法时所有模式直接拒绝执行，并输出类别诊断 `native session epoch unavailable; update the adapter/host`。这些字段由宿主 hook context 构造，威胁边界仍是未被攻陷的宿主进程及实例凭据；摘要是防混淆标识，不是宿主签名或独立 Authority。

before、审批最终执行复核、after、实例登记、decide、raw capture 均使用该同一编码。审批回调须再次验证捕获的原生 context 未变化。变化/缺失的 after context 不得附着旧 action 或发送成功 observation。不同 UUID 必须得到不同身份，相同 key+UUID 跨进程得到相同身份。

## 后端绑定与兼容

现有 HTTP `session_id` 是不透明字符串，保留请求/响应 v1 形状与长度；其 OpenClaw 值使用独立版本化编码合同。`intent.Bind`、`ResolveBinding`、runtime identity enrollment、decision 与 observation 对 OpenClaw 强制验证编码。旧 raw key、默认值、错误版本/摘要均拒绝，不能回落旧绑定；decision 生成 Authority hard-deny，不被 warn/audit_only 放宽。

签名 Binding 的现有 platform/session_id/agent_id 已覆盖完整新身份，因此不增加可被剥离的可选 epoch 字段、不改旧签名字节。历史 binding 仍可按 ID 读取、列出、撤销，但旧 raw key 不能用于运行解析。升级不自动迁移或给旧绑定猜测 epoch：管理者必须用真实 CLI 完成元数据（sessionKey/sessionId/workspace/source 交叉验证）或受信宿主 context 派生的新身份创建新的绑定。普通管理绑定仍要求管理鉴权；模型或调用参数不能创建绑定。知道一个摘要不授予任何权限。

Managed 模式每个新身份仍经过实例凭据认证及当前 Grant 验签；为该身份创建独立 Intent/Binding，沿用实例权限限定及原期限。不会继承上个 epoch 的任务 Intent、审批或执行预留。同 epoch 重试保持幂等；撤销后不可重新登记以复活权限。

旧适配器与新 daemon 的 raw key 调用明确拒绝；新适配器与旧 daemon 不得作为修复已验收的组合。此修复不将旧 daemon 的历史签名格式升级为安全能力，回滚二进制和适配器会恢复旧缺陷，必须用新候选成对交付及回归。其他宿主 session 身份规则保持不变。

## 验证收尾

实现后集中验证：同 epoch 续聊、新 key、新 epoch、缺失/伪造 event epoch、错误编码、普通与 managed 正向、旧 raw 绑定拒绝、跨 epoch pre/post/hold 不混用；真实宿主原生 idle/reset 回归必须证明实际副作用被正确允许或拒绝。组件结果不能替代真实宿主证据。
