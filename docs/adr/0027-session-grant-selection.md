# ADR-027：会话固定授权选择

- 日期：2026-09-10；状态：后端与 Hermes 产品自检已实现并通过 Linux 验证，普通任务接入与可信 Skill 归属未完成；对应 UX-007。

当前按 platform/agent 选最新 deployed/effective Grant，无法区分同一智能体的不同 Skill 授权；撤销后还可能回退到旧 Grant。个人会话应由管理端明确选择授权，不能由工具参数、模型提供的 skill_id 或“最新一份”推断选择。

在现有 Intent Binding 上增量加入 signed grant_ref，不建立第二套决策引擎。管理请求使用 `intent-grant-bind/v1`，提供既有绑定身份、grant_id 与 expected_grant_revision。服务读取并验证当前 Grant 的签名、主体、平台、已部署状态、期限和精确版本，再生成权限摘要。绑定仍为原来的不可变 session/platform/agent 唯一记录，同一会话不能替换授权，也不能用旧无选择请求把它降级。旧绑定无新字段时保持原签名字节和调用兼容。

grant_ref 保存 Grant ID、admission ID 与权限摘要。摘要覆盖主体、平台、准入、权限事实、条件、平台 allow/deny/人批策略、期限、批准人与策略版本；不把 effective 读回的证据属性变化当作扩权。工具事实的 declared/effective 均规范化为可用于决策；其他状态不因此提升。绑定有效期不超过 Intent 或 Grant 的期限。

每次解析绑定均重新读取、验签和检查所选 Grant；撤销、缺失、摘要改变、主体不符或失效为独立 Authority 错误，所有模式拒绝。不能回退到按智能体查找的另一份 Grant。通过验证后，既有 Grant∩Intent、资源、污点、脱敏及人工确认逻辑只使用被选中的 Grant；hold 查询与最终批准亦重新解析。未绑定选择的旧流程保持原兼容语义，迁移前不能声称已解决其隐式选择限制。

这只证明管理者为会话选择了哪份权限，不证明宿主实际加载了该 admission 对应的 Skill。可信实例凭据、真实加载的 Skill 版本、磁盘内容变化与多 Skill 调用归属仍需原生宿主证据或受控运行接入；界面不得将本绑定显示为“Skill 已验证”。最终目标仍是明确实例/Skill 版本权限及防借用验收，本增量是其必需的会话约束。

产品 Hermes 运行自检首先使用该机制：原生宿主通过既有独立启动凭据附着真实 session 后，控制器只选择本次已签发的短期 Grant。用户不需要手填 session 或 Grant ID。普通任务的自动会话接入与选择界面仍待后续实现，不用新增管理 API 冒充完整个人旅程。

验证要求：不同会话各选不同 Grant；同 Skill 在不同主体独立授权；存在更新、更宽 Grant 时不借用；撤销/替换/过期/错误主体/无 resolver 全模式拒绝；旧绑定固定向量不变；绑定重放不能换 Grant 或降级；hold 和脱敏不能切换授权。API 管理鉴权、固定合同样例、Go/合同回归及 Linux 原生链路分别记录，不以单测冒充宿主 Skill 归属验证。
