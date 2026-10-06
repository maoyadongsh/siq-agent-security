# 40项产品功能与测评旅程对照

日期：2026-10-06。来源为功能层面源码/合同复核，功能存在不表示已通过测评；精确路径、摘要和合同候选见[机器表](../inventory/function-traceability-v2.json)。旅程定义见[执行方案](../plan/real-business-evaluation-v2.md)，机器任务见[18项任务清单](../plan/real-business-work-items-v2.json)。

| 功能 | 核对边界 | 新旅程 | 原产品组 | 源码入口 |
|---|---|---|---|---|
| F01 可信客户端发行、安装和升级 | 清单验签、私有暂存、准确历史程序、恢复日志；测试构建与发行身份分开 | RB16 | P05 | [源码](../../../apps/agentshield/internal/clientrelease/compatibility.go) |
| F02 浏览器连接与管理权限 | 5分钟连接请求、24小时管理会话；请求ID不能换取其他浏览器会话 | RB10 | P06 | [源码](../../../apps/agentshield/internal/server/authz.go) |
| F03 个人发现及框架角色Skill关系 | 声明/观察关系与受保护状态分开；范围、链接与秘密读取边界 | RB09 | P01 | [源码](../../../apps/agentshield/internal/inventory/connectors.go) |
| F04 静态准入与能力声明 | 能力需求、文档示例与欺骗/注入/完整性威胁分别处理；绝不执行扫描内容 | RB09 | P02 | [源码](../../../apps/agentshield/internal/admission/admission.go) |
| F05 本地/HTTPS固定Skill来源与Git生产门禁 | 本地目录/ZIP与受限HTTPS；Git组件存在但生产入口关闭；导入不代表发布者认证、批准或安装 | RB09 | P02, P03 | [源码](../../../apps/agentshield/internal/skillimport/download.go) |
| F06 Grant资源、审批挑战与五态事实 | 人工批准和部署不等于effective；挑战绑定scope/digest/revision/nonce | RB09, RB10 | R01, G04 | [源码](../../../apps/agentshield/internal/grant/challenge.go) |
| F07 适配器接入预览及事务卸载 | 实例预览确认、加载诊断、用户配置保留、冲突与中断恢复 | RB05, RB16 | P03, P05 | [源码](../../../apps/agentshield/internal/adapterinstall/diagnostics.go) |
| F08 受管实例、原生会话和按请求子身份 | 凭据不持有管理权；会话不可被新身份接管；子身份可撤销 | RB05, RB07, RB17 | R04, R07 | [源码](../../../apps/agentshield/internal/runtimeidentity/files.go) |
| F09 可信Skill执行上下文SEC | 安装内容、Grant摘要、实例会话任务实时复验；受管会话不自动等于SEC | RB05, RB15 | R04, P03 | [源码](../../../apps/agentshield/internal/skillcontext/context.go) |
| F10 Intent任务授权及版本边界 | v3来源/效果与v4/v5文件系统身份各绑定适用路径；版本号不表示所有特性累加 | RB01, RB04, RB15 | R01, R04 | [源码](../../../apps/agentshield/internal/intent/binding.go) |
| F11 参数来源、issuer与派生图 | 显式lineage、内容匹配、scope/撤销/最低父信任；不追踪模型隐式推理 | RB02 | R02, R03 | [源码](../../../apps/agentshield/internal/provenance/authority.go) |
| F12 可信上下文与最终调用绑定 | 参数、工具、tool_call、会话任务绑定；上下文不能扩大Grant | RB02, RB04 | R03, R04, R06 | [源码](../../../apps/agentshield/internal/trustedcontext/context.go) |
| F13 资源规范化、污点与脱敏 | 路径/端点权限、secret/PII、trifecta；redact后仍复验资源与审批 | RB05, RB08, RB15 | R01, R07 | [源码](../../../apps/agentshield/internal/receipt/engine.go) |
| F14 hold最终复验、单次预留和不确定恢复 | 批准不是执行许可；重放、丢响应、强杀、撤权窗口分别测 | RB04, RB15 | R05, R06, R08 | [源码](../../../apps/agentshield/internal/receipt/hold_execution.go) |
| F15 动作观察关联和签名回执链 | 观察来自适配器；签名保证记录完整性，不保证实际效果 | RB03, RB11 | E05, R04 | [源码](../../../apps/agentshield/internal/receipt/action_state.go) |
| F16 独立效果材料与Completion | host/external independent有信任边界；完整性/覆盖/结果分别评分 | RB03 | E01, E02, E03, E04 | [源码](../../../apps/agentshield/internal/completion/evaluate.go) |
| F17 任务活动、历史来源和脱敏导出 | 列表详情、历史授权/Skill、签名投影、外部锚和截断检查 | RB11 | E05, E06 | [源码](../../../apps/agentshield/internal/server/task_activity_completion.go) |
| F18 可选原文仓与保留清理 | 默认关闭；采集授权与保留两个时钟；跨任务拒绝，清理不删审计 | RB11 | P06, E05 | [源码](../../../apps/agentshield/internal/rawcontent/activation.go) |
| F19 Skill安装、权限换发、更新和移除 | 差异确认、旧权限不扩张、来源漂移、未知用户文件保留 | RB09, RB15 | P03, P04, P05 | [源码](../../../apps/agentshield/internal/skillinstall/inspection.go) |
| F20 后台服务和状态迁移恢复 | 准确实例/签名服务归属、停止排空、兼容屏障；跨OS单独验收 | RB16 | P05, E06 | [源码](../../../apps/agentshield/cmd/agentshield/client_install.go) |
| F21 原生Hermes/OpenClaw/WorkBuddy插件 | 真实宿主执行器及所有嵌套工具映射；原版/补丁、Windows原生/WSL分开 | RB05, RB07 | R04, R07 | [源码](../../../adapters/runtime/hermes-agentshield/README.md) |
| F22 OpenShell探测、部署和真正任务执行 | 配置读回、策略加载与行为证据分层；policy_apply不升级为命令执行 | RB06 | G04, R08 | [源码](../../../apps/agentshield/internal/openshell/bounded_command.go) |
| F23 模型连接、敏感性路由和无静默回退 | 应用PUBLIC/INTERNAL/CONFIDENTIAL/SECRET策略；管理连通检查非全局DLP | RB08 | R07 | [源码](../../../apps/secure-agent/secure_agent/routing.py) |
| F24 研究—报告—实际投递参考应用 | 原SkillRunner/Gateway/ToolAdapters链；合成业务但真实模型/文件/HTTP | RB01, RB02, RB03, RB04 | R01, R02, E01, E02 | [源码](../../../apps/secure-agent/secure_agent/application.py) |
| F25 企业OIDC/JWKS与租户对象RBAC | 生产模式PG/RS256；开发身份头禁用；测试issuer不冒充客户IdP | RB12 | G01, G02 | [源码](../../../apps/control-api/app/security.py) |
| F26 企业Edge可信接入、恢复、轮换与吊销 | 注册丢响应持久恢复、在线吊销、凭据哈希、设备签名；不产生业务授权 | RB12 | G03 | [源码](../../../edge/agent/registration_journal.go) |
| F27 安装范围和周期发现独立确认 | 待确认枚举不写业务状态；确认、tick、完成回执各有事实 | RB12 | P01, G03 | [源码](../../../edge/agent/confirm_schedule_linux.go) |
| F28 12类Connector有界采集协议 | 同批candidate引用evidence；legacy注册与setup实际探测能力分开 | RB09, RB12 | P01, G03 | [源码](../../../connectors/README.md) |
| F29 企业资产、框架角色Skill及权限投影 | 历史来源、安装观察和加载身份分开；缺关系明确unknown | RB13 | P01, G04 | [源码](../../../apps/control-api/app/routers/framework_inventory.py) |
| F30 风险、规则分类、发现处置和到期复核 | 模型辅助不写effective；风险接受需owner/reason/expiry；静态规则有漏报边界 | RB13 | P02, G02 | [源码](../../../apps/control-api/app/threat_analysis.py) |
| F31 企业策略草稿、职责分离和break-glass | 自批拒绝；break-glass单独权限且不绕职责分离；审计失败回滚 | RB14 | G02 | [源码](../../../apps/control-api/app/routers/policies.py) |
| F32 运行时绑定、独立目标授权和影响 | 登记不证明独占；独立目标清单限制控制面写；共享影响仍有明确缺口 | RB14 | G04 | [源码](../../../apps/control-api/app/routers/bindings.py) |
| F33 持久部署请求、批量提议和结果恢复 | 同键不重复执行；批量提议不代表批准；部分结果和unconfirmed保留 | RB14 | G02, G04 | [源码](../../../apps/control-api/app/routers/deployment_submission.py) |
| F34 OpenShell策略编译、漂移、行为与回滚 | 真实版本/指纹/revision；拒绝臂有独立可达对照；回滚复核当前授权 | RB06, RB14 | G04 | [源码](../../../apps/control-api/app/adapters/openshell/__init__.py) |
| F35 企业审计、outbox、精确查询与OCSF | 同事务审计、至少一次worker；导出Truncated=0不等于全量归档 | RB13, RB14 | G01, G02, E05 | [源码](../../../apps/control-api/app/routers/audit.py) |
| F36 业务API—Hermes—OpenShell跨仓链 | 业务授权归业务API；安全事件投影不含正文/凭据；E166等历史单列 | RB17 | G03, R04, R07 | [源码](../../../connectors/siq/README.md) |
| F37 平台能力、发行签名与承诺 | 源码、签名包、原生OS证据区分；desktop-same-uid非managed-linux | RB16 | P05 | [源码](../../../apps/agentshield/internal/skillmanifest/bootstrap.go) |
| F38 产品运行自检及诊断 | 短期专用启动身份；自检成功不等于日常全部业务路径均受保护 | RB05, RB16 | R04, R07 | [源码](../../../apps/agentshield/internal/runtimecheck/authority.go) |
| F39 本地批量撤权及逐项审计 | 最多50项、5分钟预览；逐项CAS和结果；非原子批次/进程终止 | RB10 | R05, P06 | [源码](../../../apps/agentshield/internal/server/grant_batch.go) |
| F40 性能、容量、降级和证据完整性预算 | P50/P95/P99、合法效用、缓存/截断/限额/坏状态；耗尽不得清污点后放行 | RB18 | E04, E06, R07 | [源码](../../../apps/agentshield/internal/perfbaseline/intent.go) |

来源能力最新修正见[专项复核](source-capability-review-001.md)。F05按四种来源分别验收，Git门禁测试通过不能提升为Git功能可用；公网HTTPS与私有传输夹具分列。
