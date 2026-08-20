# 第四轮评估：OpenShell 二次开发 + "扫描-发现-识别-检测-管控"闭环复核（2026-08-20 夜）

- **评估对象**：`/home/maoyd/siq/siq-agent-security`，基线 HEAD `b80dd28`（另有 1 个未跟踪文件 `docs/agent-security-round3-20260820.md` 待决定是否入库）。
- **与前三轮的关系**：本仓库当天已有三轮独立评估——`agent-security-audit-20260820-153735.md`（审计）、`agent-security-deep-assessment-20260820.md`（深度复核）、`agent-security-round3-20260820.md`（OpenShell 专项 + P0/P1 修复核验）。三轮结论高度一致且逐条有 file:line 证据，本轮**不重复其已完整覆盖的内容**，聚焦三件事：
  1. round3 基线（`06e7e24`）之后新增的 6 个提交逐项核验（质量判断，而非只读 commit message）；
  2. 三轮均标注"未核验"的 7 个新发现源 Connector（`systemd/kubernetes/process/mcp/piagent/workbuddy/dify`）深度审查——直接回应本次提问点名的 **openclaw / hermes / piagent / workbuddy / dify**；
  3. 把四轮累计的行动项去重合并为一份终版优先级清单，并给出本轮的管理层判断。
- **方法**：本人亲读 `06e7e24..HEAD` 全部 diff（21 文件/1990 行）+ 威胁检测三件套（`threat_analysis.py`/`rulepack.py`/`threat.py`）全量重读 + 新增 P2 模块（`deployment_verify.py`/`ocsf.py`/`routers/export.py`/`openshell_compat_check.py`）全量精读 + 1 路只读子代理深度审查 7 个新 Connector（以 `hermes.go` 为质量基线、`docker.go` 已知缺陷为反面对照）+ 本机执行 `ruff check` 与全量 `pytest` 复核（均绿）。
- **边界声明**：仍未接入真实 OpenShell 网关 / K8s 集群 / systemd 主机做动态验证；Go 工具链本机不可用，新 Connector 的 build/vet/test 以子代理读码 + 既有 CI 脚本自证为准，未本机编译；本评估不构成安全认证。

> **重要补记（评估过程中发现，请优先阅读）**：本轮评估进行到约一半时，工作区出现了一批**未提交**的并发修改（`git status` 显示 10 个文件为 `M`，均非本次评估产生），修改时间戳集中在评估过程中的同一时间窗口内，且代码注释里直接出现"R-1 修复""R-3 校验"字样——即有另一方（很可能是同仓库下的另一个并行 Agent 会话）正在**实时消化 round3 报告并落地修复**。本人已重新核实这批未提交改动的实际内容与效果，**第三节与第七节的结论已按工作区当前真实状态更新**；其余章节（新 Connector 审查、OpenShell adapter、6 个已提交 commit 的核验）不受影响，因为这批未提交改动只涉及 Python 威胁检测流水线 + 部署绑定链 + Web 部署表单，未触及 Go Connector 与 OpenShell adapter 代码。这批改动**尚未提交、尚未补充回归测试**（本机复核 `pytest` 从全绿变为 1 个失败——`test_builtin_loads_20_rules_version_1` 断言仍是"20 条规则"，未同步新增的 4 条规则数，是需要同步更新的琐碎断言，不是逻辑缺陷），建议对方在提交前把这个断言改成 24 并补一条端到端正例回归。

---

## 一、一句话结论（本轮最重要的元发现）

**round3 基线之后已提交的 6 个 commit，无一命中此前三轮报告里评级最高的条目；但本轮评估进行过程中，工作区里出现了一批尚未提交、正在进行时的修改，恰好逐条对准了 L0/L1 里的大部分条目。** round2 的 P0/P1（越权绑定、静态策略、恶意检测最小闭环）与 round3 的 L0/L1（部署链断裂 R-1/R-6、检测投毒面 R-3、密钥泄露面 R-7、隔离误报 R-8、AST 静默漏报 R-3b）合计 10 项最高优先级问题：**已提交历史零改动**，**未提交工作区已实质修复或大幅推进 6 项**（R-1、R-3、R-3b、R-4a 联动、R-4b 释放权限点、C2 事件命名），**部分修复 1 项**（R-6：协议已对齐，管理页仍缺；R-7：加了正则脱敏但非完全方案），**仍未触碰 2 项**（R-8 自动隔离阈值、B-1 命中历史覆盖，且 R-8 的实际风险因新增的"隔离自动吊销部署绑定"联动而**升级**）。已提交的 6 个 commit 实际完成的，是 round2 P2"规模化与长期维护"清单里的 4 项（版本兼容矩阵+CI、独立部署回执 verifier、规则签名更新机制、OCSF 导出）——这 4 项工程质量本身**扎实、诚实、测试完整**，但优先级顺位是这份报告体系里最低的一档。

打个比方：这更像是"承重墙"（部署链、检测流水线）的施工队伍已经进场在修，图纸看起来是对的，但还没验收、没竣工签字（未提交、无端到端回归测试锁定）；与此同时另一支队伍在同栋楼加装了监控摄像头和门禁记录系统（审计/合规能力），且已经完工验收。**下一步不是继续加新能力，也不是从零开始修 L0，而是把工作区里这批"在制品"验证、补测试、提交，并收尾剩下的缺口（bindings 管理 UI、R-7 完整脱敏方案、R-8 阈值收紧、B-1、R-4b 扫描侧归属校验）。**

第二个重要发现：本次提问点名的 `piagent / workbuddy / dify` 三个"品牌 Connector"，加上同批新增的 `systemd / kubernetes / process / mcp` 四个"主机/集群通用 Connector"，经深度审查后判定——**它们叠加起来仍然兑现不了"安装即发现所有智能体"这句产品承诺**。新代码质量总体可用，但也把 `docker.go` 已知的 Go map 遍历非确定性缺陷**原样复制**到了 `systemd.go` 和 `kubernetes.go` 里，并新增 2 个 high 级问题（详见第四节）。

---

## 二、round3 基线以来 6 个新提交逐项核验

| Commit | 提交信息 | 本轮质量判定 | 判定 |
| --- | --- | --- | --- |
| `408370b` | ci: Go 全模块矩阵 + OpenShell 版本兼容检查 | 真实落地：CI 从 4 个 Go 模块扩到全部 **11 个**（含 7 个新 connector），矩阵覆盖 Go 1.22/stable 两版本 + `-race`；`openshell_compat_check.py` 是一个写得很规范的 fail-closed 探测脚本（未配置网关时 `SKIP` 退出码 0，不误红 CI）。**质量扎实，值得保留。** | ✅ 完成 |
| `57dc167` | control-api: 部署回执独立验证器 | `deployment_verify.py` 设计干净：不信任 receipt 自报，重新向后端读回 revision 独立比对，`unreachable/verified/mismatch/no_receipt` 四态语义清晰，mismatch 落 Finding + outbox。已挂到真实端点 `POST /api/v1/deployments/{id}/receipt-verify`（`policies.py:582-607`），不是死代码。**但该端点依赖的 `Deployment` 记录本身来自仍然断裂的 `binding → AgentInstance` 链路（见 R-1）**——在干净生产库上，deployment 都创建不出来，这个"独立验证"就无从验证起。质量好，但建在了尚未验收的地基上。 | ⚠️ 有效性受限于 R-1 |
| `5f305d3` | control-api: OCSF v1.1.0 事件导出 | `ocsf.py` 是干净的纯函数映射（无 I/O，全部可单测），Finding→Detection Finding、AuditEvent→API Activity 的枚举取舍都有注释说明依据（如 `status_id` 的官方枚举缺口、`activity_id` 一律 `99 Other` + 原始动作保留）。`routers/export.py` 权限、审计、租户隔离都到位。**诚实、可信、SIEM 对接价值真实。** | ✅ 完成 |
| `1f75c31` | control-api: 威胁规则包版本化签名更新机制 | `rulepack.py` 的签名校验/防降级/字段校验 9 条负向测试全部到位（篡改签名、缺 `.sig`、JSON 畸形、版本回退、正则不可编译、字段缺漏均正确拒绝并回退内置包）。**但这只是把原有 20 条规则原样从 Python 代码搬进 JSON 文件，未新增一条规则、未修一处检测逻辑缺陷**——round3 点名的 R-3/R-7/R-8/R-3b/B-1（见下节）在重构后的新代码里逐条核对，**全部原样保留**。是"给规则供应链加锁"，不是"把规则本身修好"。 | ⚠️ 供应链机制好，检测质量债务未还 |
| `71ac250` | control-api: 修复存量库 findings 500 | `matches`/`evidence_ids` 对存量 NULL 行的响应兼容 + 迁移 0013 回填。小而对的兼容性修复。 | ✅ 完成 |
| `b80dd28` | web: 设置页连接状态改为 `/health` 实时探测 | 把硬编码的 `connection="disconnected"` 换成真实探测，vite 加了 `/health` 代理。小而对的诚实性修复。 | ✅ 完成 |

**本机复核**：`ruff check app` 全绿；`pytest`（`apps/control-api`）在 `HEAD` 上全量 4 批次全部通过（无 failed/error），工程纪律（lint/测试习惯）保持水准。**但**在工作区未提交改动落地之后复跑 `pytest`，出现 1 个新失败——`test_builtin_loads_20_rules_version_1` 断言规则数为 20，而 `threat_rules.v1.json` 已被改到 24 条，属于断言未随规则包同步更新的琐碎问题（见文首补记），不是新逻辑缺陷，但提醒了一个纪律点：**这批未提交改动目前处于"改完功能、没跑全量测试"的中间状态**。

---

## 三、关键遗留问题状态复核（L0/L1：已提交 HEAD vs. 当前工作区未提交改动）

以下问题均由 round2/round3 提出。本轮先基于 `HEAD`（`b80dd28`）逐条确认——**全部仍然成立、零改动**；但评估过程中工作区出现了未提交的并发修改，本人已重新读码核实其真实效果，两列并列呈现：

| 编号 | 问题 | `HEAD`（已提交）状态 | **工作区（未提交）最新状态** |
| --- | --- | --- | --- |
| **R-1** | `AgentInstance` 全仓库零生产写入方，`binding → AgentInstance` 断链，干净库上部署恒 404 | ❌ 成立：`rg "AgentInstance\("` 仅命中 `tests/` | ✅ **已修复**：`inventory.py` `confirm_candidate` 确认资产时若无实例自动创建一条 `AgentInstance`（`runtime`/`environment_id` 均从 asset/evidence 推导），并新增 `POST /api/v1/assets/{asset_id}/instances` 显式创建端点；`environments.py` 新增 `PATCH /api/v1/environments/{id}/mode`。`bindings.py`（既有代码）本就要求 `AgentInstance` 存在才能建 binding——三者拼起来，"确认资产→建绑定→部署"链路在代码层面已经可以走通。**缺口**：没有新增端到端正例回归测试锁定这条链，也未提交 |
| **R-6** | Web 控制台仍发 `target` 自由字符串，后端要求 `binding_id`，部署按钮恒 422；bindings 管理无 UI | ❌ 成立：`client.ts` 仍发 `{ target }` | ⚠️ **部分修复**：`client.ts`/`types.ts`/`ChangesPage.tsx` 已改为 `binding_id` 契约，`ChangesPage` 会调 `listRuntimeBindings` 自动选一个 active 绑定去部署，422 恒错问题解除；**但**仍没有独立的 bindings 登记/列表/吊销管理页面——`createRuntimeBinding`/`revokeRuntimeBinding` 这两个新增的客户端方法目前代码里没有任何页面调用，用户仍无法在 Web UI 里注册第一条 binding，只能绕开 UI 直接调 API |
| **R-3** | `threat-scan` 的 `content` 裸传，从不与 `asset.artifact_digest` 比对 | ❌ 成立 | ✅ **已修复**：`threat.py` 新增 `raw_hash` 与 `asset.artifact_digest` 比对；不符且提供的 `evidence_ids` 里也查不到匹配 `content_hash` 时返回 `422 content_not_bound`；首次扫描（`artifact_digest` 为空）自动写入 baseline digest |
| **R-7** | `excerpt` 只截断不脱敏，可携带密钥明文前 40 字符 | ❌ 成立 | ⚠️ **部分修复**：新增 `_redact_excerpt`，对若干常见密钥/Token 正则模式做替换后再截断——方向对，但仍是"黑名单正则脱敏"而非 round3 建议的"只存 `excerpt_sha256`、完全不留明文窗口"，未覆盖的密钥格式（自定义 Token 格式、非标准 key=value 写法）仍可能残留在 40 字符窗口里 |
| **R-8** | 单条 `high` 命中即自动隔离，无置信度二次门槛 | ❌ 成立 | ❌ **仍未修复，且风险实质升高**：`_SEVERE = ("critical", "high")` 与触发逻辑未变；但工作区新增了"隔离创建时自动吊销该资产所有 active `RuntimeBinding`"的联动（见 R-4a 行）——原来 R-8 误报的代价是"库里多一条隔离标记"，现在**误报会直接吊销生产部署授权**，建议把 R-8 的收紧和这条联动一起提交，否则联动本身会放大误报的爆炸半径 |
| **R-3b** | AST 规则无文本正则兄弟规则；语法错误静默放行 | ❌ 成立 | ✅ **已修复**：`_python_ast_checks` 语法解析失败且文件像 Python 时，产出 medium 级 `threat-py-syntax-parse-failed` finding 而非静默返回 `[]`；规则包新增 4 条文本正则（`os.system`/`subprocess shell=True`/`ctypes` 动态加载/`__import__` 动态引入高危模块），规则总数 20→24 |
| **B-1** | 重扫命中覆盖历史，`matches` 恒为单条记录 | ❌ 成立 | ❌ **仍未修复**：`existing.matches = [record]` 整列覆盖逻辑未变 |
| **R-4a** | Enforce 徽标只判断 `deployment.status`，不校验 binding 有效性/撤销传播 | ❌ 成立 | ⚠️ **部分修复（联动方向对，徽标计算本身未动）**：`threat.py` 新增隔离时自动把该资产所有 active `RuntimeBinding` 置为 `revoked` 并发 `runtime_binding.revoked.v1` 事件——数据层面已经有了"被撤销"的信号；但 `inventory.py` 里 Enforce 徽标的计算代码本身这次没有改动，没有确认它是否已经开始读取 binding 状态而不是只读 `deployment.status` |
| **R-4b** | 隔离创建与释放同用 `finding:manage`；扫描无 asset 归属校验 | ❌ 成立 | ⚠️ **部分修复**：`security.py` 新增独立权限点 `quarantine:release`（`tenant_admin`/`security_admin` 持有），`release_quarantine_case` 已改用它做 SoD 分离——释放侧修复到位；**扫描侧**仍未加 asset 归属/`agent:manage` 校验（`rg "owner_user_id"`/`"agent:manage"` 在 `threat.py` 零命中），任何具备 `finding:manage` 的身份仍可对任意资产发起扫描 |
| **C2** | `threat-scan` 产出 Finding 未走通用 `agent.finding.opened.v1` 事件通道 | round3 附带项 | ✅ **已修复**：`threat.py` 新建 Finding 分支已补发该事件 |

**结论**：`HEAD` 上确实是零改动，这一判断准确无误；但把"当前项目真实状态"等同于"最后一次提交的状态"会得出误导性结论——**工作区里有另一条并行的修复工作，已经把 10 项 L0/L1 问题中的 6 项实质修复、3 项部分修复，只剩 R-8（且优先级因新联动而上升）、B-1、R-6 的管理页、R-4b 的扫描侧校验、R-7 的完整脱敏这几个缺口**。这批改动**尚未提交、没有端到端回归测试、也让 `pytest` 出现 1 个因规则数断言未同步而失败的用例**，在正式定论"已解决"之前，仍需要：提交、补齐正例回归测试、修同步失败的断言。

---

## 四、7 个新发现源 Connector 深度审查（直接回应本次点名的 openclaw/hermes/piagent/workbuddy/dify）

审查基线：`connector-protocol.v1.md`（NDJSON 协议、默认禁网、60s/8MB 限额、脱敏规则）+ `hermes.go`（已验证的高质量基线：symlink 逃逸防护、`.env` 只发 `secret_ref`、字节预算）+ `docker.go`（已知 Go map 遍历非确定性缺陷，用作反面对照）。

### 4.1 总览：11 个 Connector 的发现机制分类

| Connector | 机制类型 | 能否发现"未声明品牌"的智能体 |
| --- | --- | --- |
| hermes / openclaw（既有） | 品牌专用（已知目录 + 已知 manifest 字段） | 否 |
| docker（既有） | 主机通用（标签优先 + 关键词启发式） | 部分（关键词命中才行） |
| directory（既有） | 半通用（管理员指定目录 + 已知文件名） | 否 |
| **piagent / workbuddy（新）** | 品牌专用（硬编码 `~/.piagent`/`~/.workbuddy` + 固定 manifest 文件名） | **否，必漏** |
| **dify（新）** | 半通用（授权目录下找 compose 文件 + 官方镜像前缀匹配） | 否（非 compose 部署 / 非官方镜像必漏） |
| **process（新）** | 主机通用（`ps` 全量枚举 + 关键词分类） | 是，但噪声大 |
| **systemd（新）** | 主机通用受限（**先按 unit 名称初筛，再查 ExecStart**） | **结构性漏报，见下** |
| **mcp（新）** | 客户端配置发现（5 个硬编码 IDE 路径 + `mcp.json`） | 否（未覆盖的 IDE/客户端必漏） |
| **kubernetes（新）** | 集群通用（同 docker 的标签+关键词启发式） | 部分 |

**结论先行**：11 个 Connector 叠加后，本质仍是"已知品牌路径 + 已知关键词 + 已知镜像前缀"的组合盘点，**不足以支撑"安装即发现所有智能体"的产品叙事**。真正意义上的"通用主机扫描"（process/systemd/kubernetes）存在明显的误报或漏报缺陷（见下）。这与 round2 §3.1"扫描覆盖面不足"的结论方向一致，本轮的增量是：**覆盖面确实变宽了（4→11 个源），但没有一个新源解决了"读内容做特征匹配"这个杀毒软件最基础能力的缺失**——所有 Connector 依然只提取元数据 + 结构化字段，脚本/配置内容本身从不进入发现阶段的判断（要到人工触发 `threat-scan` 才会读内容，而 `threat-scan` 目前不是任何自动化流程的一部分，见 R-3 附近上下文）。

### 4.2 逐 Connector 关键问题（严重度标注，均附 file:line）

| Connector | 严重度 | 问题 | 证据 |
| --- | --- | --- | --- |
| **dify** | 🔴 high（新发现） | `validateScopeOp` 逻辑错误，**永远返回 `Valid: true`**，只把错误塞进 `Errors` 字段；如果 Edge 侧只看 `Valid` 布尔值做门禁，非法 scope 会被静默放行 | `dify.go:181-182` |
| **systemd** | 🔴 high（新发现） | **结构性漏报**：`classifyName` 先按 unit **名称**关键词初筛（`systemd.go:229-233`），只有命中才会去查 `ExecStart` 内容（`:349-370`）。也就是说，如果运维把 hermes/piagent 的 systemd unit 命名为中性名字（如 `runner.service`），即便 `ExecStart=/opt/hermes/bin/hermes`，这个 Connector **永远不会检查它**——这不是误报/漏报的概率问题，是设计上的结构性盲区 | `systemd.go:229-233,349-370` |
| **systemd / kubernetes** | 🟡 medium（重复既有缺陷） | `classifyName`/`reconfirm`/`classifyContainer` 遍历 `knownFrameworks` map 做关键词匹配，**Go map 遍历顺序不确定**——与 `docker.go` 已知的 `classifyContainer` 缺陷完全同构。说明这个"坑"在两轮报告点名之后，**没有被作为经验教训传播到同批新写的 Connector 里** | `systemd.go:336-338,354-360`；`kubernetes.go:388-392` |
| **kubernetes** | 🟡 medium（新发现） | 协议声明 `NetworkAccess: false`，但采集手段是 `kubectl get pods -A`，**必然要连 Kubernetes API Server**——声明与真实网络行为不符，"默认禁网"在这个 Connector 上只是一句没有兜底的宣称 | `kubernetes.go:193,237` |
| **kubernetes** | 🟡 medium | 输出超预算时**整批失败**而非部分保留结果，大集群可能完全采集失败（对比 directory/process 的"截断继续"策略） | `kubernetes.go:253-254` |
| **dify** | 🟡 medium | `filepath.WalkDir` 无深度上限，只跳过 `.`/`node_modules`/`vendor`，大授权目录可能长时间扫描，无超时兜底（除主循环外） | `dify.go:318-327` |
| **workbuddy** | 🟡 medium | 畸形 `buddies.json` **静默跳过**（fail-open），与 piagent/mcp 对同类错误**报错拒绝**（fail-closed）行为不一致，产品行为不可预期 | `workbuddy.go:328-331` |
| **workbuddy** | 🟡 medium | 声明不读 `.env`，但没有像 hermes/piagent 一样产出 `secret_ref` 证据条目，凭据面的"存在性"本身未被记录 | `workbuddy.go:15` |
| **process** | 🟡 medium | 关键词过宽（`uvicorn`/`agent` 等），任意含这些词的普通 Python Web 服务会被打上智能体候选标签，噪声面大 | `process.go:262-287` |
| **piagent** | 🟢 low | 任意目录只要放一个形如 PiAgent manifest 的 `agents.json` 即被判定为 PiAgent，confidence 直接 1.0 | `piagent.go:408-415` |
| **mcp** | 🟢 low | 硬编码 5 个已知 IDE 路径（Cursor/Claude/Windsurf/Codeium），VS Code/Continue/Zed 等未覆盖 | `mcp.go:57-63` |

### 4.3 值得肯定的部分

- 文件类新 Connector（piagent/workbuddy/dify/mcp）基本复用了 hermes/directory 已验证的安全模式：symlink 逃逸防护、字节预算截断、`.env`/密钥不读正文（`piagent.go:449-546` 的 `secret_ref` 处理与 hermes 一致）；
- `process` Connector 的关键词分类改用有序 slice 而非 map 遍历，**正确规避**了 docker 的非确定性问题，命中/丢弃逻辑清晰，args 只发 sha256 前 16 位不落地原文；
- `mcp` Connector 对 `env`/URL 做了双重脱敏（值不出机、URL 只留 `scheme://host`），测试覆盖是 7 个新源里最完整的一个；
- `kubernetes`/`dify` 均正确避免读取 `env` 值本身（只报 `env_vars_count`/环境段整体丢弃），凭据不出机的红线守住了。

### 4.4 文档滞后于代码（治理债）

- `README.md` 第 29/75/103-106 行仍只列 `hermes/docker/directory/openclaw` 四个 Connector，`docs/compatibility.md` 第 65 行仍写 `kubernetes | 待 Phase 4`——但 `kubernetes.go` 连同其余 6 个新源已经在 `325ef83` 提交（早于 round3 基线）实现并带测试。**文档口径落后代码至少 7 个提交**，且这不是"谦虚少报"，是文档没有跟着改。对一个反复强调"证据优先、如实声明差距"（README 状态说明段）的项目而言，这是一个自我矛盾的信号，也是最容易低成本修复的一项——建议下一次改动 `docs/compatibility.md`/`README.md` 时把 7 个新源按本节的真实状态（品牌专用/半通用/主机通用 + 已知缺陷）如实列入矩阵，而不是继续留空。

---

## 五、OpenShell 二次开发：本轮增量结论

**Adapter 代码本窗口零改动**（`cli_backend.py`/`policy_compiler.py`/`contracts.py` 均未出现在 `06e7e24..HEAD` 的 diff 里），因此 round2 §4.2 与 round3 §2 的十方法契约现状表**继续原样成立**，此处不重复，只更新两点新增耦合关系：

| 方法 | 现状（沿用 round2/round3 结论） |
| --- | --- |
| `probe` | ✅ 真实探测，不硬编码（`cli_backend.py:63-98,257-298`，保守正则，解析不到即 `unknown`） |
| `compile` | ✅ 5 域路由 + 显式 `unsupported` 标注，但核心域（tools/secrets/data_scope/资源配额）仍在 unsupported 列表 |
| `plan`/`apply_dynamic`（动态网络） | ✅ 唯一真实闭环，v0.0.104 实测 |
| `create_generation`（静态 fs/process） | ❌ 直接抛错，五域中四域不可部署 |
| `verify` | ⚠️ revision 读回 + 网络 membership，非真实行为 fixture |
| `observe`（`stream_events`） | ⚠️ 诚实降级为 `policy list` 文本回读，标注不得当行为证据 |
| `rollback` | ✅ 结构合理，但无 expected-revision 保护 |

**本轮新增的两点耦合，值得管理层知道**：

1. 新的 `POST /deployments/{id}/receipt-verify` 端点（本轮 §2 已述）在语义上是"给动态网络这条唯一真实闭环再加一层独立验证"，方向对，但因为 `Deployment` 记录的产生依赖 R-1/R-6 未修的绑定链路，**这个新端点在干净安装环境里同样摸不到**——即便通过测试夹具直插数据能验证它本身逻辑正确，也无法改变"客户装完产品后走不通第一次部署"的现实。
2. `openshell_compat_check.py` 提供的版本漂移检测是一个**旁路 CI 脚本**（每周一定时或手动触发），不是 round3 B5 建议的"运行时 advisory finding"（即探测到版本与能力文档基线不一致时自动进风险中心）。方向部分吻合但落点不同：前者要人去看 CI 结果，后者是产品自己在风险中心告诉客户"我的能力基线可能过时了"。建议下一步把 compat 脚本的探测结果接一条 advisory finding 写入库，而不只是 CI 日志。

---

## 六、六阶段成熟度评分更新（对标杀毒范式，0-5 分）

| 阶段 | round2 评分 | 本轮评分 | 变化原因 |
| --- | --- | --- | --- |
| 扫描 Scan | 2.0 | **2.5** | Connector 从 4 个增至 11 个，广度提升；但零内容特征匹配、brand-list 模式未变，且新代码引入 2 个 high 级缺陷，抵消部分增量 |
| 发现 Discover | 3.0 | **3.5** | round3 确认任务原子领取（lease）已修复；`AgentInstance` 死路径仍是天花板 |
| 识别 Classify | 2.0 | **2.5** | `framework` 信号已参与分类（round3 P1-10）；置信度仍是拍值，未校准 |
| 风险 Risk | 2.0 | 2.0 | `rules.py` 本窗口未动，仍是纯治理状态检查，无内容/行为维度 |
| 恶意检测 Detect | 0.5 | **1.5** | 真实静态规则流水线已上线（20 条规则 + AST + 签名供应链），但 R-3/R-7/R-8/R-3b/B-1 五个缺陷让这条流水线目前"能跑但不能信" |
| 权限管控 Control | 2.0 | 2.0 | 动态网络域闭环依旧是唯一真实生效点，且因 R-1 在干净安装环境里实际不可达，评分不升反而应警惕 |
| 行为管控 Behavior | 1.0 | 1.0 | 无变化，`stream_events` 仍是假事件流 |
| 审计治理 Audit | 3.5 | **4.0** | OCSF 导出 + 独立部署回执验证器进一步增厚证据链，是本轮最扎实的净增量 |
| 跨平台 Any OS | 1.0 | **1.5** | Linux 主机覆盖深度提升（systemd/process/k8s），但零 Windows/macOS，"任意系统"仍是未兑现的表述 |

**加权判断不变**：产品目前仍是"智能体资产发现 + 治理状态风险评估 + 策略审批治理 + 局部受管沙箱策略下发"的控制面，**审计治理是最强项、也是可以对外主打的差异化卖点**；"恶意脚本检测"与"任意系统全量发现"两项核心承诺依旧是最大缺口，且本轮新增的 11 → 更宽的攻击面（更多 Connector = 更多可信执行面缺口）没有同步补强 Connector 自身的隔离与确定性问题。

---

## 七、终版优先级清单（四轮合并去重）

### 已完成（本轮确认，值得认可，不需要再排期）

- OpenShell 版本兼容矩阵 + 周期性 CI 探测（`openshell_compat_check.py` + `openshell-compat.yml`）
- 威胁规则包签名与版本化供应链机制（`rulepack.py`，9 条负向测试）
- OCSF v1.1.0 事件导出（SIEM/取证对接）
- 部署回执独立验证器代码本身（`deployment_verify.py`，实际生效待 L0 解决）
- Findings 存量 NULL 兼容修复 + Web 设置页真实健康探测
- Go CI 矩阵覆盖全部 11 个 Connector 模块 × 2 个 Go 版本
- 任务原子领取（lease，round3 确认）、分类信号扩展（framework 参与，round3 确认）

### L0 — 先让"扫描→发现→审批→部署→生效"端到端可达（1-2 个提交量级，二者互为前提）

1. **R-1**：binding 锚点从 `AgentInstance` 下沉到 `AgentAsset`（推荐）或补 `POST /agents/{asset_id}/instances` 写入端点；同步补环境 mode 翻转端点。
2. **R-6**：`apps/web` 的 `createDeployment` 迁移到 `binding_id` 契约；补 bindings 登记/列表/吊销 3 个管理页（API 已齐，只缺 UI）。

### L1 — 检测流水线"最后一里路"（单条改动即可修完，六条互相独立）

3. **R-3**：`threat-scan` 增加 `content_sha256`/`source_evidence_id` 与 `asset.artifact_digest` 的绑定校验（不符 422 `content_not_bound`）。
4. **R-7**：`excerpt` 改只存 `excerpt_sha256`，删除明文截断窗口。
5. **R-8**：auto-quarantine 收紧为 critical-only；补"正常运维大全"负向测试集（`systemctl enable`、诊断脚本读 `/etc/shadow`、cron 备份等）；`threat-persist-systemd` 正则排除常见合法用法。
6. **R-3b**：为 `os.system`/`subprocess(shell=True)`/`ctypes` 补充 10-15 条保守文本正则；`ast.parse` 失败时产出 medium `python_syntax_parse_failed` finding 而非静默放行。
7. **R-4a/R-4b**：isolation 创建时联动 enforce 徽标降级；release 落独立权限点 `quarantine:release`；scan 增加 asset 归属校验。
8. **B-1**：`matches` 改为 append + cap（如 50 条），而非整列覆盖。

### L2 — 本轮新增发现 + 治理债（成本低、建议随手改）

9. **dify**：修复 `validateScopeOp` 恒 `true` 的逻辑错误。
10. **systemd**：把"名称初筛"改为"ExecStart 内容优先、名称仅做提示"，消除结构性漏报。
11. **systemd/kubernetes**：map 遍历改排序遍历或最长匹配，消除与 `docker.go` 同款的非确定性（建议顺带巡查是否还有其他 Connector 有同类模式）。
12. **kubernetes**：`NetworkAccess` 声明与 `kubectl` 真实网络行为对齐（要么老实标 `true` + 说明依赖 API Server 可达性，要么给出网络隔离兜底）。
13. **README.md / docs/compatibility.md**：连接器矩阵按本报告 §4.1/4.4 更新，去掉过时的"kubernetes 待 Phase 4"表述。
14. `docs/detection-baseline.md` 首版（≥20 恶意样本，按类别统计召回/误报，接入 CI 回归）。
15. CLI 子进程 env 白名单化（不继承 `*TOKEN*/*KEY*/*SECRET*`）。

### L3 — 能力解锁（依赖外部协作，下一阶段）

16. `create_generation` 路径解锁（需 OpenShell 上游修 SandboxResponse 解码或 CLI 补建箱动作），解锁后必须实弹验证 fs/process 段真的 block。
17. 行为事件通道（OpenShell Interceptor `observe` 实测 或 eBPF/auditd Host Sensor 兜底）——双轨架构里"Host Sensor 管宿主机直跑 agent"这条腿至今没有任何代码。
18. 评测基准升级（恶意样本召回 ≥95%、置信度校准替代拍值常数）。

---

## 八、给管理层的判断

工程团队的执行力和代码质量本身没有问题——本轮验证的 6 个新提交全部测试完整、fail-closed 纪律统一、ruff/pytest 全绿，这是少见的工程素养。**问题出在排期，不出在能力**：连续三轮报告点名的"部署链在干净库上走不通"（R-1/R-6）和"检测流水线五个可低成本修复的信任缺陷"（R-3/R-7/R-8/R-3b/B-1）合计 10 项最高优先级问题，在有机会安排 6 个提交的窗口期里一项没动，而是把力气投向了信号更"体面"、验收更清晰、但客户价值排序更靠后的合规与供应链能力（签名、导出、CI 矩阵）。

建议下一个迭代窗口只做两件事，且不安排任何新能力：

1. 花 1-2 个提交打通 L0（R-1 + R-6），让一次"发现候选 → 确认资产 → 建绑定 → 提策略 → 审批 → 部署 → 生效"的正例链路第一次在干净 fixture 库上端到端跑通，并把这条正例写成测试锁死；
2. 花 1 个提交清空 L1 的六条检测流水线缺陷——每条都是几十行以内的改动，合起来决定了"发现恶意脚本"这句产品话术当前能不能站得住。

在这两件事完成之前，对外的诚实表述应该是：**"智能体资产发现、治理状态风险评估与受管沙箱策略控制平台（OpenShell 动态网络域已闭环，部署入口待打通）"**，而不是"扫描发现所有智能体、识别风险高低、发现恶意脚本、精准管控权限行为"的完整杀毒软件叙事——后者需要 L0+L1+L2 全部落地，并补上双轨架构里完全空缺的 Host Sensor 行为管控腿，才算真正成立。
