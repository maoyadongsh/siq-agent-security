# WorkBuddy 受管审批恢复 v1

本增量沿用 Hermes `_remember_hold` / `_approved_retry` 的信任边界：首次真实 pre 的服务端 hold、用户在 SIQ 的独立批准、后续真实 pre 的同实例/会话/tool/精确参数匹配及后端唯一 reservation 共同构成恢复条件。新 call 本身、模型自报、generation_id、宿主 ask 都不是批准。原 call 重放始终拒绝；新 call 只表示新的宿主调用。宿主原权限门禁继续有效。

## 能力证据与边界

安装源 `resources/app.asar.unpacked/cli/dist/codebuddy.js` SHA256 为 `eb018e35d80673db02ebdaa7547b72f43d130d660c9c907c338d35e2f7b42ff7`；以下偏移为解码后零起始 UTF-16 单元：12661700 构造 pre/post 外层 session/call/input，8814059 command 去掉内部 session 后 JSON 序列化，8832740 执行 input processors。GenerationContext（8866118）和 ClientInfo（8867700）只增加描述性字段。未执行安装源、读取会话数据库或使用模型；这些是静态能力证据，不能替代桌面实测。

PermissionDenied 的 retry 返回值未被其 dispatcher（12678228）消费，不采用此路线。宿主可能缓存 pre，实际执行前亦可能变换参数；本实现只能对 hook 提供的参数裁决，post 必须逐字节规范化摘要匹配。不能宣称宿主后续内部变换已被最终原生门禁覆盖；保留原生验收项。

## 私有追加关联

新增 `workbuddy-hook-correlation/v1`，由 hook 在 N01 statefs 屏障内写入 `<state>/workbuddy-hooks/<scope digest>/`；仅配置 identity_id/instance_id/agent_id 的域分离摘要选择 scope，宿主 cwd/model/version 不参与。记录仅含派生 session/call、tool、参数摘要、服务端 action/decision/reservation 引用、可信响应 task 字段和时限；不存工具参数、结果、凭据、私钥。记录是不可信提示，任何允许仍由在线服务决定。

每个 scope 最多 2048 个目录项，每个 effect 最多 64 次调用历史；单记录最多 16 KiB，JSON 深度最多 64，闭合字段、重复键/别名/非法类型/未知版本拒绝。effect 摘要绑定 scope/session/tool/参数摘要。只新建记录，pre claim 持久化后才请求裁决。scope 内的短暂排他锁同时保护跨 effect 的容量准入；竞争立即拒绝，不排队延长预算。锁只由持有者核对文件身份后移除，崩溃遗留锁不自动回收。读取恢复提示时也核对其他关联记录与 scope call guard 是否缺失对应 pre；孤儿记录不能被当成无历史。容量耗尽、损坏、缺失关联显式拒绝，不回落新 allow，不自动删除历史。

scope 内原 call 的全局 claim 阻止重复 pre，即使同一 call 改 tool 或参数也不能再次执行。成功裁决保存 decision；缺 decision 的 claim 表示请求结果不确定。allow/reserved 在对应 post 确认之前阻止同 effect 的新执行。hold 保存原服务端引用；本地窗口最多 300 秒且不超过服务端 hold timeout，不能续期。后续相同 effect 调用读取原 hold-status，pending/denied/expired/consumed 或响应异常均拒绝本次。只有 approved 才先持久化原 hold 唯一 consume，再发 reserve；只有首次 201 reserved 且所有引用/时限严格匹配才允许。reserve 响应丢失、预留后本地写入失败、输出丢失、宿主未执行或无 post 均保留 uncertain，禁止再执行原预留。

post 必须匹配已保存允许的 pre、当前派生 call 和参数摘要，发送明确 action_id/decision_receipt_id（恢复时为 reservation receipt）及原 task 身份。post 在发送前建立唯一 claim，响应确认后追加完成记录；缺失/重复/错误参数或丢失响应不能伪造成功。已知 denied/expired 可在后续新的 pre 重新裁决，但不能消费旧批准。

## HTTP 与预算

复用 hold-status/v1、hold-execution-reserve/v1（成功 201）、hold-execution-status/v1；不新增审批权限或管理 token 用途。WorkBuddy 专属 credential 每次经过身份/会话在线复验；hold 相关入口同样严格校验派生 call 格式和精确字段名，reserve 的原 call 与新 call 必须不同。后端原有 current Authority、Intent/Grant 版本、目录事实、撤销和唯一 reservation 检查保持。

登记、关联操作、hold-status 和 reserve 使用同一次 20 秒上下文（宿主同步 hook 等待 30 秒），不续时、不自动重试 HTTP；超时没有允许。到期/撤销/Grant 或 Intent 变化即拒绝，描述性客户端 version 不作为授权版本。

## 验证

组件覆盖新 client 实例读取私有记录、原 call 重复、相同 effect 排他并发、批准→reserve→post、pending/deny/expired、改参/跨会话/实例、坏记录/缺记录/错误类型/容量、网络丢响应及观测丢响应。后端测试覆盖 WorkBuddy 各 hold 路径原/新 call 的格式、重复、别名与冲突。2026-09-19 按主开发规格及受管接入规格，将此前 4 秒预算更新为完整链共用 20 秒；不续时、不重试及唯一预留约束保持。完整 Windows 桌面与模型验收单独执行；组件不能记为原生通过。
