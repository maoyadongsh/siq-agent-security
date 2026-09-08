# ADR-015：Authority Hard Gate 与策略模式分离

- 状态：采纳，按 2026-09-08 用户 Provenance-Bound Effect V1 开发模板实施。
- 范围：本地 runtime；替换旧 V2 对无效 Authority 应用 audit/warn 放行的行为。

Authority invalid 与 Policy advisory 必须分开：签名、来源、绑定、主体、时效或撤销失效意味着缺少可信授权，不是可用审计模式旁路的风险提示。required 的缺绑定、previously-bound 的绑定移除/撤销与未知 resolver 失败，在所有模式拒绝。optional never-bound 保留 Grant-only；合法 Intent 内的工具、资源、效果、参数约束属于策略判断，保留既有 advisory 产品语义。

在现有 Engine 前置校验阶段分类 AuthorityResult，并由独立 runtimeauthz 模块决定模式是否可应用。无效 Authority 不运行后续 policy evaluator；通过门禁后再评估 Grant、Intent 约束和运行时状态。不增加第二个 Reference Monitor，不调用 LLM。

回执增加可选 authority_status / authority_reason_code / policy_action / effective_action。authority_status=invalid 时 action/effective_action 必须 deny，不得有 advisory_action；policy_action 缺省表示未执行策略评估。历史回执缺字段时仍按既有签名/哈希验证，不回填。Observe 只接受合法前置动作，不能把 hard deny 变为成功。

caller context.cwd 仅为观测数据，删除其自动授权工作区写入的路径。工作区范围必须来自受信 Grant/Intent；以后签名 ContextAssertion 的角色是验证环境绑定，不是绕过既有授权交集。

代价：之前 required+warn/audit 依赖无效 Intent 继续执行的客户端会收到 deny，这是用户要求的安全语义变更。断连且无法得知服务端 Authority 的适配器离线模式另按原合同，不以本 ADR 伪称离线客户端已经验证授权。

验证：三模式 × required/optional × 缺失/篡改/过期/撤销/身份错误；never-bound 兼容；合法 Authority 的 Policy advisory；伪造 cwd；拒绝后 Observe；字段篡改验签；历史签名向量。
