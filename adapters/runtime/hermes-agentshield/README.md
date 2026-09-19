# hermes-agentshield（Hermes 运行时适配器）

把 Hermes 的 `pre_tool_call` / `post_tool_call` 钩子接到本机 `siq-agent-security serve` 的决策 API。只做 HTTP 映射，不含规则、判定或密钥（`apps/agentshield/AGENTS.md` 硬性规则）。

## 当前定位与实现边界

Hermes 在 Linux、macOS、Windows 均属于当前接入范围，实际通过情况逐候选登记于[平台矩阵](../../../platforms/support-matrix.md)。组件桥接、公开 CLI 合成模型会话与真实用户任务分别验证；不能用某个 OS 的插件单测代替全部原生验收。

本适配器的重点是将真实实例/会话、参数来源和执行前授权连接起来。实例凭据不能调用管理 API；MCP 来源上报保持 untrusted；Skill 名称不自动证明执行归属，verified SEC 必须由 daemon 复验安装与授权。对应实现见[本地运行时](../../../apps/agentshield/README.md)，审批恢复见[适配器总览](../README.md)。

## 安装

在本地管理页的设置中选择 **Hermes → 管理实例**，选择目标 profile，再预览并确认接入。安装前先展示文件清单；取消不改平台配置。

```bash
siq-agent-security adapter instances hermes
siq-agent-security adapter preview hermes install --instance <返回的实例ID> --enable-native
siq-agent-security adapter install hermes --instance <返回的实例ID> --enable-native
```

实例目录解析覆盖 `HERMES_HOME`、默认目录和命名 profile。CLI 中的 `<返回的实例ID>` 需替换为第一条命令给出的 ID。非 Windows 系统的新实例包装器放在 `<profile>/bin/hermes-skills-install`，固定该 profile 的 `HERMES_HOME`；不会覆盖其他实例的包装器。Windows 不安装该 shell 包装器，使用本地管理页的受控 Skill 安装入口，或显式先 `admit` 再调用原生命令；原生命令本身不受装前门禁接管。CLI `install` 是直接授权动作，会重新准备并应用计划；浏览器确认则严格绑定先前预览的 ID 和摘要。

选择原生启用时，安装器调用已安装 Hermes 的公开 CLI，在私有临时副本上执行启用并验证其他配置未变，再由文件事务应用已确认的内容。Hermes 会规范化 YAML 格式；不授予内置工具覆盖权限。CLI 不在 PATH 时，可在启动 SIQ 前将 `SIQ_AGENT_SECURITY_HERMES_CLI` 设置为可信 Hermes CLI 的绝对路径。该路径仅用于定位已安装程序，不能指向 Skill 脚本。

原生命令缺失或配置不兼容时可以仅安装文件，再在目标 profile 中通过 `hermes plugins enable siq-agent-security --no-allow-tool-override` 启用并开启新会话。未带 `--instance` 的旧 `adapter install hermes` 保留原有默认目录和仅文件安装行为。参见 [Hermes 官方插件说明](https://hermes-agent.nousresearch.com/docs/user-guide/features/built-in-plugins)。

插件文件存在不证明宿主已加载。设置页的“接入诊断”会分别显示文件、连接配置和运行验证状态；CLI `adapter status` 的 installed 仅表示发现安装文件。完成目标实例正常调用与执行前拒绝验证后，才可声明相应工具层保护。Grant 与运行时阻断仍复用原有引擎，不由诊断产生权限。

Windows 新接入配置的 HTTP 等待为每请求 20 秒，其他系统为 5 秒；旧配置需经预览、确认重新接入才更新。安装内容仍逐次复验，更短专项超时仍生效，超时拒绝且不自动重试。有 allow 回执不等于工具实际执行，须结合 observation 和文件结果确认。

## 行为映射

| 决策 API `action` | 插件返回 | 说明 |
| --- | --- | --- |
| `allow` | `None` | 放行 |
| `deny` | `{"action":"block","message":...}` | Hermes 把 message 作为工具错误返回给模型 |
| `hold` | 首次 block + 控制台 URL | 控制台批准后，同会话、工具和参数的重试先取得唯一执行预留，再允许执行；不会自动恢复原调用。|
| `redact` | block + 提示移除密钥 | `pre_tool_call` 不能改参 |

`post_tool_call` 把结果（截断 64 KiB）发到 `/v1/observe`，服务端脱敏并更新会话污点。

## fail-closed

| 场景 | `block` | `audit_only` / `warn` |
| --- | --- | --- |
| 服务不可达 / 超时 / 401 / 非法 JSON / 无 token | **block** | allow + stderr 警告 |

## 卸载

```bash
siq-agent-security adapter preview hermes uninstall --instance <返回的实例ID>
siq-agent-security adapter uninstall hermes --instance <返回的实例ID>
```

也可在“管理实例”中选择卸载。只移除本实例拥有的文件与登记，原生启用过的实例恢复接入前启用状态，并保留后来新增的其他设置。记录不足、文件被外部修改或原生 CLI 不兼容时停止并保留现场；中断操作可通过 `adapter recover hermes --instance <返回的实例ID>` 恢复。旧默认目录安装可继续使用不带实例参数的卸载命令。

## 已知限制

- L1 安装门禁：Hermes 无装前钩子；用 `siq-agent-security admit <src>` 后再 `hermes skills install`，或让 `siq-agent-security serve` 周期盘点 `~/.hermes/skills` 标出未准入 Skill。
- `agent_id` 默认取 `HERMES_PROFILE` 或 `default`，需与 grant 的 `subject.id` 一致。

V2：有 tool_call_id 时保存服务端 action_id/receipt_id（最多 2048 项、TTL 300 秒）并在 post 回传；重复 ID 冲突不覆盖旧关联，产生无关联的拒绝路径。无 ID 时由服务端用相同参数唯一匹配，歧义拒绝。除 hook 单测外，已有 [Hermes 原生分发器与真实 HTTP 集成证据](../../../docs/trusted-intent-v2-native-validation-20260907-191006.md)，覆盖合成工具调用的允许/拒绝、关联、失联及重启。新增 [原生 Agent 完整会话证据](../../../docs/trusted-intent-v2-conversation-validation-20260907-200400.md)，通过本地合成模型的 SSE 响应驱动实际会话循环，覆盖生成会话 ID、跨轮固定授权和动作链。hold/审批恢复已有 N06/R02 实现：适配器查询原 hold 状态并请求持久执行预留，预留响应丢失或结果不确定时不盲目重放；内存关联过期或宿主进程退出后不能凭旧提示恢复。实现存在不替代真实平台 V2 综合验收，该综合验收仍为 unverified。

## 显式MCP来源采集（组件集成）

可在插件config.json中指定精确工具名与服务器身份映射：

```json
{"mcp_sources": {"mcp__reports__lookup": "https://reports.example.invalid/mcp"}}
```

示例域名仅作配置说明。映射应由部署者根据实际注册工具填写，不能从工具结果取得；不按名称前缀拆分服务器名。匹配的post_tool_call会将实际result提交本地daemon的受限报告API，来源始终MCP/untrusted，服务器身份+工具名仅提交摘要。需已有有效Intent绑定、稳定tool_call_id、decision凭据和daemon服务；报告失败不生成可用引用。

宿主可通过`provenance_reference(session_id, tool_name, tool_call_id)`取回引用，并在后续pre_tool_call传入`parameter_provenance`或`context_assertion_id`。这只是显式桥接，不能直接把原结果引用绑定到变换后的参数；选择/派生必须经过daemon的对应API生成内容摘要匹配的引用。插件不推断模型隐式lineage，不签发可信声明，也不把自称USER的工具结果提升权威。

内存引用缓存最多2048条、5分钟到期，满时不驱逐既有引用来假装干净；不持久化原结果或token。结果预算预留JSON编码空间，超限不截断后当完整来源。默认映射为空，原版Hermes自动配置/传播和真实原生MCP链路仍需单独验证；现有测试只证明钩子映射、受限上报及缓存边界。


真实daemon组件桥接复现：

```bash
python3 scripts/validate-mcp-provenance.py --hermes-bridge --out /tmp/hermes-mcp-bridge.json
```

脚本执行真实loopback MCP initialize/tools-call，将实际结果交给本适配器post hook自动上报，经daemon确定性select后通过pre hook提交参数来源；MCP路径阻断，admin签发USER的相同路径允许。最后复验daemon回执链。此模式直接调用钩子，不包含原生Hermes MCP注册/调度器，不等同原生端到端支持；不会操作真实用户配置。

## 个人实例会话接入（ADR-028、ADR-029）

新配置可引用由本机管理 API 发行的独立实例身份：`runtime_identity_id`、固定 `agent_id` 和 `token_path`。凭据只在本机文件保存，发行响应提供路径，不返回秘密正文。`pre_tool_call` 使用 Hermes 的真实 `session_id` 调用 `/v1/runtime-sessions`；服务根据身份自动创建权限包络并固定已批准 Grant，适配器不自行生成或签发权限。没有原生 session 时不会用任务 ID 或默认值替代。

如果用户在 SIQ 隐私设置启用独立原文仓，并为该会话对应任务明确创建唯一的参数或输出 Grant，已管理插件会调用运行时身份专用的 `/v1/raw-task-content/native-captures`。pre hook 仅在工具获准后提交最终参数；post hook 还须以真实 tool_call_id 关联同一允许裁决，宿主为阻断调用触发的 post hook 不采集阻断文本。适配器不持有 task_id、原文 Grant、签名许可或管理凭据。嵌套 JSON 展开为 JSON Pointer 字段，服务端继续整项排除 secret/凭据键和值。不可表示、超限、未授权、重叠授权、不可达或仓异常会放弃本次辅助采集，不改变工具裁决和结果；请求本机等待上限 250ms。该功能默认关闭，也不适用于产品运行自检和旧全局决策凭据。

已管理实例在登记、认证、授权读取失败时，所有模式均阻止调用；正常资源策略仍保留 warn/audit_only 的建议语义。环境不能替换已配置的实例主体。管理 API、其他实例/会话不能共用该凭据；撤销后新旧会话均失去访问能力。连接失败的本机 pending 记录明确为未签名拒绝，不能当作服务端回执或结果证据。

产品运行自检的决定/观察请求改用该次自检的短期启动凭据，只能访问已绑定的真实会话；不读取全局或个人实例凭据来代替它。所有普通 API 请求也限制为明确端口的 loopback HTTP，禁用代理和重定向转发。`localhost` 固定连接到 `127.0.0.1`；IPv6 使用显式 `[::1]` 地址。

旧的全局凭据配置保持兼容。设置页“管理实例”现在可以从已有检查结果起草权限、编辑范围、人工批准、选择会话期限，再预览和确认实例接入。配置计划 v3 绑定已发行身份，修复保留凭据引用；配置变化、授权撤销或过期后不能继续应用旧计划。诊断核对身份所属实例，但配置成功仍不代表运行验证通过。

停用权限会撤销实例身份。卸载经管理界面先撤权，再执行可恢复文件事务；卸载失败不恢复旧授权。直接 CLI 卸载已管理实例必须先在管理界面或 API 撤销身份，再带明确 `--instance` 操作；CLI 暂不提供完整身份发行流程。Hermes 原生命令会规范化 YAML，卸载恢复本产品原有登记语义并保留其他设置，不承诺原文件格式逐字恢复。

`scripts/personal-experience/managed-instance-native-smoke.py` 在隔离 profile 中通过正式安装 API 与公开 Hermes CLI 验证自动会话、只读范围、撤销和独立产品自检；`managed-instance-browser-smoke.py` 验证从起草到接入/撤销/卸载的界面流程。具体证据见 [M13 开发记录](../../../docs/evidence/personal-experience/managed-instance-20260910/verification.json)。实际 Skill 加载归属、用户已有会话迁移、跨 OS 和其他平台仍需独立验收。


### 调整已接入实例的权限

“管理实例 → 调整当前权限”会创建独立待批准草稿，保留原范围、拒绝、逐次审批条件和到期时间；编辑与批准期间仍使用旧身份。可在同一窗口显式保存新有效期。准备完成后确认停用旧身份，再使用新授权并确认接入；切换期间工具调用会被阻止，应重新开启原平台会话。新身份不能接管旧会话，切换失败不会复活旧凭据。原 Grant、策略和回执保留可追溯。

接口和幂等/并发边界见 [ADR-030](../../../docs/adr/0030-permission-revision-drafts.md)。[权限换发验证](../../../docs/evidence/personal-experience/permission-revision-20260910/verification.json)分别记录浏览器流程、真实 Hermes CLI 新会话及 HTTP 负向；不能据此推定实际 Skill 版本归属已可信。
