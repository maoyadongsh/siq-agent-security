# L01/L02 复核修复增量（2026-09-16）

本文为当前未发布 L02 原型的安全收紧，继承 agentshield-dev-spec-v1 与 hold 合同。

- L01：未知/超时/传输错误不能视为阻断。拒绝断言要求显式 HTTP 403、接收端零到达，且同一违规目标先在放行策略下证明可达。传播等待只对明确 403 允许有限等待，记录时间；不能吞掉未知错误。成功/失败清理均走当前操作回执、授权器、漂移检测和精确摘要读回；不直接 policy set 覆盖现场。恢复失败即测试失败。
- L02 当前仅为 policy_apply 控制面操作，不执行命令、不完成 O05/B3。保留未发布路由但响应必须标 scope=policy_apply、task_executed=false。
- 输入必须与已批准 hold 的 params 全量绑定：固定 command=siq-openshell-policy-apply，openshell_policy 对象包含 target、endpoints、binary_paths、expected_revision、grant_id、grant_digest、endpoint_fingerprint。顶层 authorization_urls 必须严格等于 endpoints 按顺序生成的 https://host:port 描述，只供既有 exec 资源解析器检查全部授权目标，不发送 HTTP 请求，不声明后端协议。不能由调用者另选 URL。对解析器无法识别的目标保留拒绝。
- 不允许把任意已批准 exec 的参数用于另一个策略操作。此 command 仅作协议标记，从不交给 shell。
- 以签名决策的 matched_grant_id 选择唯一 Grant，重新验签、状态、有效期、platform/subject，匹配 permission digest；禁止合并同 target 的其他 Grant。目标必须等于当前 agent/Grant subject；尚无可信异名映射时拒绝，不猜测绑定。
- 二进制路径至少一条，绝对、规范、无控制字符；端点严格 host:port。所有额外字段/变更在消费预留前拒绝。后端配置指纹必须非空且与批准一致。
- 预留后、实际策略写入前重新验证 Grant/批准参数及会话授权；策略写前授权器只是本进程检查，不宣称与网关跨进程原子事务。
- 写后证据或审计/observation 失败不能返回 ok=true。已发生的副作用不得伪称取消，保留 reservation 和未知/待记录状态，不自动重试。
- 回滚须重验签名链、操作绑定、当前 Grant 及恢复网络规则权限范围。回滚记录写入失败返回非成功并保留实际恢复事实。原始证据不改写，旧 L01 PASS 暂不能作为修复后验收。
