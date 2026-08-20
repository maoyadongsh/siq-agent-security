# 第四轮评估：OpenShell 二次开发 + "扫描-发现-识别-检测-管控"闭环复核（2026-08-20 夜）

- **评估对象**：`/home/maoyd/siq/siq-agent-security`，评估**开始时**基线 HEAD `b80dd28`（另有 1 个未跟踪文件 `docs/agent-security-round3-20260820.md`）；评估**过程中**代码持续演进，最终定稿时 HEAD 已推进到 `d0cfd6b`（详见文首补记与 §2.1）。
- **与前三轮的关系**：本仓库当天已有三轮独立评估——`agent-security-audit-20260820-153735.md`（审计）、`agent-security-deep-assessment-20260820.md`（深度复核）、`agent-security-round3-20260820.md`（OpenShell 专项 + P0/P1 修复核验）。三轮结论高度一致且逐条有 file:line 证据，本轮**不重复其已完整覆盖的内容**，聚焦三件事：
  1. round3 基线（`06e7e24`）之后新增的 6 个提交逐项核验（质量判断，而非只读 commit message）；
  2. 三轮均标注"未核验"的 7 个新发现源 Connector（`systemd/kubernetes/process/mcp/piagent/workbuddy/dify`）深度审查——直接回应本次提问点名的 **openclaw / hermes / piagent / workbuddy / dify**；
  3. 把四轮累计的行动项去重合并为一份终版优先级清单，并给出本轮的管理层判断。
- **方法**：本人亲读 `06e7e24..b80dd28`（评估开始时基线）全部 diff（21 文件/1990 行）+ 威胁检测三件套（`threat_analysis.py`/`rulepack.py`/`threat.py`）全量重读 + 新增 P2 模块（`deployment_verify.py`/`ocsf.py`/`routers/export.py`/`openshell_compat_check.py`）全量精读 + 1 路只读子代理深度审查 7 个新 Connector（以 `hermes.go` 为质量基线、`docker.go` 已知缺陷为反面对照）+ 评估过程中追加亲读 `b80dd28..d0cfd6b`（19 文件/1024 行）全部 diff + 新增 `test_e2e_fresh_deploy.py` 全文通读 + 本机执行 `ruff check` 与全量 `pytest` 复核（均绿）+ 对关键改动点（R-8 阈值、B-1 覆盖逻辑、R-4b 归属校验）直接对当前 `HEAD` 做定向 `grep` 复核，避免依赖过时诊断。
- **边界声明**：仍未接入真实 OpenShell 网关 / K8s 集群 / systemd 主机做动态验证；Go 工具链本机不可用，新 Connector 的 build/vet/test 以子代理读码 + 既有 CI 脚本自证为准，未本机编译；本评估不构成安全认证。

> **重要补记（评估过程中实时发生，请优先阅读，已按最终状态定稿）**：本轮评估进行到约一半时，工作区出现了一批**未提交**的并发修改（10 个文件 `M`），代码注释里直接出现"R-1 修复""R-3 校验"字样——判断是另一方（很可能是同仓库下的另一个并行 Agent 会话）正在**实时消化 round3 报告并落地修复**。本人当时已重新核实其内容并更新过一版结论；**随后在本文撰写过程中，这批修改被正式提交**（`9bcc09b fix(core): 修复部署全链路闭环与威胁扫描管控安全加固` + `d0cfd6b docs: 更新 round4 安全评估与落地状态`，后者恰好是把本文档也一并提交了一版早期草稿），当前 `HEAD` 已推进到 `d0cfd6b`。本人已对新提交做完整逐文件 diff 核验（含此前未曾核实的 3 个文件：`routers/policies.py`、`adapters/openshell/cli_backend.py`、新增的 `tests/test_e2e_fresh_deploy.py`，以及 `connectors/{docker,systemd,kubernetes}.go`），**全文已按提交后的最终代码状态重写，不再是"工作区未提交"的口径**。核心结论：`9bcc09b` 一次提交扎实解决了 R-1/R-6/R-3/R-3b/R-4a（含真正的部署门禁，而不只是数据信号）/B4（CLI 环境变量白名单）/Go map 非确定性（docker/systemd/k8s 三个 Connector），并且**新增了一条高质量端到端测试 `test_e2e_fresh_deploy.py`（179 行，覆盖发现→确认→实例化→绑定→策略→审批→部署→威胁扫描→隔离→绑定吊销→部署二次拦截全链路，本机验证通过）**，同时修复了本文此前指出的 pytest 规则数断言问题。本机复核：`pytest` 全量恢复全绿（4 批次无 failed/error）。仍未触及的问题见第三节"仍未修复"列，清单已大幅收窄。

---

## 一、一句话结论（本轮最重要的元发现：从"零改动"到"当场提交修复"的完整过程）

**round3 基线之后、本轮评估开始时已提交的 6 个 commit，无一命中此前三轮报告里评级最高的条目——但就在本轮评估进行的过程中，第 7 个 commit（`9bcc09b`）落地，一次性提交修复了 10 项最高优先级问题中的 7 项，外加 2 项本文自己新发现的 Connector/CLI 缺陷，并补上了一条 179 行的端到端全链路测试。** round2 的 P0/P1 与 round3 的 L0/L1（部署链断裂 R-1/R-6、检测投毒面 R-3、密钥泄露面 R-7、隔离误报 R-8、AST 静默漏报 R-3b）合计 10 项最高优先级问题，**最终确认状态（基于当前 HEAD `d0cfd6b`）**：**7 项已修复并有测试覆盖**（R-1、R-3、R-3b、R-4a——且 R-4a 是真正在 `POST /deployments` 加了 `409 asset_under_quarantine` 硬门禁，不只是数据信号、R-4b 的释放权限点分离、C2 事件命名，以及 R-6 的协议契约对齐），**部分修复 1 项**（R-7：加了正则脱敏，E2E 测试验证 `sk-` 类密钥可被脱敏，但仍是黑名单方案非完全消除），**仍未触碰 2 项**（R-8 自动隔离阈值、B-1 命中历史覆盖）。此外，同一个提交顺带修复了本文本轮新发现的 2 个问题：`docker.go`/`systemd.go`/`kubernetes.go` 三个 Connector 的 Go map 遍历非确定性，以及 round2/3 点名过的 B4（OpenShell CLI 子进程环境变量未白名单化，此前会把宿主全部环境变量含密钥透传给子进程）。

这是四轮评估以来第一次看到"最高优先级清单"被真正大批量清空，且清空的方式是教科书级别的——**不是零散打补丁，而是一次提交里把功能改动、权限改动、Go 侧改动和一条覆盖全链路的正例回归测试一起提交**，代码注释里直接标注了 R-1/R-6/R-3/R-4/B4 等编号，说明这套跨轮次编号体系正在被当作真实可执行的工程待办使用。剩余敞口现在是一份很短的清单：**R-8 自动隔离阈值（且因 R-4a 门禁生效而变得更紧迫——一次误报现在会真的拦掉部署）、B-1 命中历史覆盖、R-7 从正则脱敏升级为完全方案、R-4b 扫描侧归属校验、bindings 管理页 UI、dify 的 `validateScopeOp` 逻辑错误、systemd 的结构性漏报（名称初筛顺序未变）、kubernetes 的 `NetworkAccess` 声明与超预算失败策略**。

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

**本机复核**：`ruff check app` 全绿；以上 6 个提交在其对应时点 `pytest`（`apps/control-api`）全量 4 批次全部通过（无 failed/error），工程纪律（lint/测试习惯）保持水准。

### 2.1 评估过程中新落地的第 7 / 8 个提交（追加核验）

| Commit | 提交信息 | 本轮质量判定 | 判定 |
| --- | --- | --- | --- |
| `9bcc09b` | fix(core): 修复部署全链路闭环与威胁扫描管控安全加固 | 一次提交横跨 14 个 Python/TS 文件 + 3 个 Go 文件 + 1 个新测试文件（179 行），逐文件读码确认：`inventory.py`/`environments.py`/`schemas.py` 落地 R-1；`client.ts`/`types.ts`/`ChangesPage.tsx` 落地 R-6 协议对齐；`threat.py`/`threat_analysis.py`/`data/threat_rules.v1.json` 落地 R-3/R-3b；`security.py` 落地 R-4b 释放权限点分离；**`routers/policies.py` 新增 `QuarantineCase` 查询，`create_deployment` 对隔离中资产返回 `409 asset_under_quarantine`**——这是真正的部署门禁，不是数据层面信号；`adapters/openshell/cli_backend.py` 把子进程 `env={**os.environ,...}` 全量透传改成显式白名单（`PATH/HOME/LANG/LC_ALL/TMPDIR/USER/TERM` + `SIQ_AS_*`/`OPENSHELL_*` 前缀），修复 B4；`connectors/{docker,systemd,kubernetes}.go` 把 `knownFrameworks` 从 `map[string]string` 改成有序 `[]struct{keyword,framework string}`，消除三处已知的 Go map 遍历非确定性。新增的 `test_e2e_fresh_deploy.py` 是全仓第一条覆盖"发现→确认→自动实例化→绑定→策略→审批→部署→威胁扫描→隔离→绑定自动吊销→部署二次拦截"完整链路的测试，本机验证通过。**唯一的质量瑕疵**：`test_threat_rulepack.py` 的规则数断言从 `== 20` 改成了 `>= 20`（能过但不够精确，理想应为 `== 24` 或动态读取规则文件长度）。 | ✅ 本轮最重要的一次提交 |
| `d0cfd6b` | docs: 更新 round4 安全评估与落地状态 | 把本文档（`agent-security-round4-20260820.md`）当时的草稿版本一并提交（含 `agent-security-round3-20260820.md` 由未跟踪转为已跟踪）。属评估文档的版本快照，不涉及产品代码。 | ℹ️ 文档快照 |

**结论**：把 §2 主表的 6 个提交与这里的 2 个追加提交放在一起看，`06e7e24..d0cfd6b` 这 8 个提交呈现出一个健康的模式——**先做完 P2 规模化能力，再回头一次性清空最高优先级技术债，且清空时不忘补测试**。这与许多团队"先做门面工程、债务无限拖延"的反模式相反，是本轮评估四轮以来观察到的最积极信号。

---

## 三、关键遗留问题状态复核（L0/L1：round3 提出时 vs. 当前 HEAD `d0cfd6b` 最终状态）

以下问题均由 round2/round3 提出。下表左列是本轮开始时基于 `b80dd28` 的确认结果（零改动），右列是 `9bcc09b`/`d0cfd6b` 落地后、经逐文件 diff 复核 + `test_e2e_fresh_deploy.py` 实测验证的最终状态：

| 编号 | 问题 | 评估开始时（`b80dd28`） | **当前 HEAD（`d0cfd6b`）最终状态** |
| --- | --- | --- | --- |
| **R-1** | `AgentInstance` 全仓库零生产写入方，`binding → AgentInstance` 断链，干净库上部署恒 404 | ❌ 成立 | ✅ **已修复并有 E2E 测试覆盖**：`confirm_candidate` 确认资产时自动创建 `AgentInstance`；新增 `POST /assets/{id}/instances`、`PATCH /environments/{id}/mode`；`test_e2e_fresh_deploy.py` 第 50-65 行实测"确认资产→查询到自动生成的实例→`runtime` 字段正确取自 `framework`" |
| **R-6** | Web 控制台仍发 `target` 自由字符串，部署按钮恒 422；bindings 管理无 UI | ❌ 成立 | ⚠️ **协议层已修复，管理页仍缺**：`client.ts`/`ChangesPage.tsx` 已用 `binding_id` 契约，E2E 测试第 116-129 行验证 `binding_id` 服务端正确解析出 `target`；**但**仍无独立的 bindings 登记/列表/吊销管理页——`createRuntimeBinding`/`revokeRuntimeBinding` 客户端方法已写好但无页面调用 |
| **R-3** | `threat-scan` 的 `content` 裸传，从不与 `asset.artifact_digest` 比对 | ❌ 成立 | ✅ **已修复并有 E2E 测试覆盖**：新增 sha256 绑定校验，不符返回 `422 content_not_bound`；E2E 测试第 131-140 行实测校验生效 |
| **R-7** | `excerpt` 只截断不脱敏，可携带密钥明文前 40 字符 | ❌ 成立 | ⚠️ **部分修复，`sk-` 类密钥已测试验证脱敏**：新增 `_redact_excerpt` 正则脱敏，E2E 测试第 158-161 行实测断言 `sk-proj-secret...` 不出现在 `excerpt` 里；仍是黑名单方案，非 round3 建议的"只存 sha256、零明文"完全方案，未覆盖格式仍可能残留 |
| **R-8** | 单条 `high` 命中即自动隔离，无置信度二次门槛 | ❌ 成立 | ❌ **仍未修复，风险因 R-4a 门禁生效而实质升高**：`threat.py:36` `_SEVERE = ("critical", "high")` 与触发逻辑（`:154`）逐字未变——本人在当前 `HEAD` 上直接 `grep` 复核确认。现在隔离会触发**真实的部署 API 级拦截**（见 R-4a 行），一次误报的代价从"标记"变成"生产部署被 409 拦下" |
| **R-3b** | AST 规则无文本正则兄弟规则；语法错误静默放行 | ❌ 成立 | ✅ **已修复并有测试覆盖**：语法解析失败时产出 medium 级 finding；规则包新增 4 条文本正则，规则总数 20→24 |
| **B-1** | 重扫命中覆盖历史，`matches` 恒为单条记录 | ❌ 成立 | ❌ **仍未修复**：当前 `HEAD` 上 `threat.py:103` `existing.matches = [record]` 逐字未变，本人已直接 grep 复核 |
| **R-4a** | Enforce 徽标只判断 `deployment.status`，不校验 binding 有效性/撤销传播 | ❌ 成立 | ✅ **已修复，且比原诉求更进一步**：不仅隔离时自动吊销该资产所有 active `RuntimeBinding`（`threat.py`），`routers/policies.py` 的 `create_deployment` 还新增查询 `QuarantineCase`，**隔离中的资产直接在部署创建 API 层被拒（`409 asset_under_quarantine`）**——这是真正的运行时强制门禁，不是数据层面的软信号；E2E 测试第 163-179 行完整验证"隔离→绑定吊销→再次部署被拦"闭环。唯一未确认点：`inventory.py` 里给人看的 Enforce UI 徽标本身是否已经联动读取 binding/quarantine 状态（非阻断性，UI 展示问题，不影响实际管控已经生效） |
| **R-4b** | 隔离创建与释放同用 `finding:manage`；扫描无 asset 归属校验 | ❌ 成立 | ⚠️ **释放侧已修复，扫描侧仍缺**：`security.py` 新增 `quarantine:release` 权限点，`release_quarantine_case` 已用其做 SoD 分离；**扫描侧**当前 `HEAD` 上 `threat.py` 内 grep `owner_user_id`/`agent:manage` 仍是零命中，任何具备 `finding:manage` 的身份仍可对任意资产发起扫描 |
| **C2** | `threat-scan` 产出 Finding 未走通用 `agent.finding.opened.v1` 事件通道 | round3 附带项 | ✅ **已修复**：新建 Finding 分支已补发该事件 |

**结论**：10 项最高优先级问题里，**7 项已修复（其中 5 项有自动化 E2E/单测覆盖，R-4a 的门禁效果被完整测试验证）**，**1 项部分修复但已测试覆盖常见场景**（R-7），**仍有 2 项完全未触碰**（R-8、B-1，均已通过直接读当前 `HEAD` 代码复核确认，不是过时结论）。相比本轮评估开始时的"零改动"，这是一次实质性的、有测试兜底的清仓式修复。剩余的 R-8/B-1/R-7 完整方案/R-4b 扫描侧校验/R-6 管理页 5 项，每项改动量都不大，是下一步最值得投入的地方（见第七节）。

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
| **dify** | 🔴 high（新发现，**仍未修复**） | `validateScopeOp` 逻辑错误，**永远返回 `Valid: true`**，只把错误塞进 `Errors` 字段；如果 Edge 侧只看 `Valid` 布尔值做门禁，非法 scope 会被静默放行。评估过程中落地的 `9bcc09b` 未触及 `dify.go` | `dify.go:181-182` |
| **systemd** | 🔴 high（新发现，**仍未修复**） | **结构性漏报**：`classifyName` 先按 unit **名称**关键词初筛（`systemd.go:229-233`），只有命中才会去查 `ExecStart` 内容（`:349-370`）。也就是说，如果运维把 hermes/piagent 的 systemd unit 命名为中性名字（如 `runner.service`），即便 `ExecStart=/opt/hermes/bin/hermes`，这个 Connector **永远不会检查它**——这不是误报/漏报的概率问题，是设计上的结构性盲区。`9bcc09b` 修的是同一文件里的另一个问题（map 非确定性，见下行），这条初筛顺序未动 | `systemd.go:229-233,349-370` |
| ~~systemd / kubernetes~~ | ~~🟡 medium~~ | ✅ **已修复**（评估过程中，`9bcc09b`）：`knownFrameworks` 从 `map[string]string` 改成有序 `[]struct{keyword, framework string}`，`classifyName`/`reconfirm`/`classifyContainer` 改遍历切片，`docker.go` 同款问题一并修复——三个 Connector 的 Go map 遍历非确定性缺陷**已在当前 HEAD 上核实修复**，本人已读最终 diff 确认写法正确（有序切片、无遗漏调用点） | `systemd.go:315-360`；`kubernetes.go:357-392`；`docker.go:277-320` |
| **kubernetes** | 🟡 medium（新发现，**仍未修复**） | 协议声明 `NetworkAccess: false`，但采集手段是 `kubectl get pods -A`，**必然要连 Kubernetes API Server**——声明与真实网络行为不符，"默认禁网"在这个 Connector 上只是一句没有兜底的宣称。`9bcc09b` 未触及这部分代码 | `kubernetes.go:193,237` |
| **kubernetes** | 🟡 medium | 输出超预算时**整批失败**而非部分保留结果，大集群可能完全采集失败（对比 directory/process 的"截断继续"策略） | `kubernetes.go:253-254` |
| **dify** | 🟡 medium | `filepath.WalkDir` 无深度上限，只跳过 `.`/`node_modules`/`vendor`，大授权目录可能长时间扫描，无超时兜底（除主循环外） | `dify.go:318-327` |
| **workbuddy** | 🟡 medium | 畸形 `buddies.json` **静默跳过**（fail-open），与 piagent/mcp 对同类错误**报错拒绝**（fail-closed）行为不一致，产品行为不可预期 | `workbuddy.go:328-331` |
| **workbuddy** | 🟡 medium | 声明不读 `.env`，但没有像 hermes/piagent 一样产出 `secret_ref` 证据条目，凭据面的"存在性"本身未被记录 | `workbuddy.go:15` |
| **process** | 🟡 medium | 关键词过宽（`uvicorn`/`agent` 等），任意含这些词的普通 Python Web 服务会被打上智能体候选标签，噪声面大 | `process.go:262-287` |
| **piagent** | 🟢 low | 任意目录只要放一个形如 PiAgent manifest 的 `agents.json` 即被判定为 PiAgent，confidence 直接 1.0 | `piagent.go:408-415` |
| **mcp** | 🟢 low | 硬编码 5 个已知 IDE 路径（Cursor/Claude/Windsurf/Codeium），VS Code/Continue/Zed 等未覆盖 | `mcp.go:57-63` |

> **追加说明**：上表中 systemd/kubernetes/docker 的 Go map 遍历非确定性问题，已在本轮评估进行过程中被 `9bcc09b` 修复（详见 §2.1），是本文唯一被验证"评估期间由代码方修复"的 Connector 层问题；`dify` 的 `validateScopeOp` 恒真、`systemd` 的结构性漏报、`kubernetes` 的 `NetworkAccess` 声明与超预算失败策略，在同一个提交里均未被触及，仍然成立。

### 4.3 值得肯定的部分

- 文件类新 Connector（piagent/workbuddy/dify/mcp）基本复用了 hermes/directory 已验证的安全模式：symlink 逃逸防护、字节预算截断、`.env`/密钥不读正文（`piagent.go:449-546` 的 `secret_ref` 处理与 hermes 一致）；
- `process` Connector 的关键词分类改用有序 slice 而非 map 遍历，**正确规避**了 docker 的非确定性问题，命中/丢弃逻辑清晰，args 只发 sha256 前 16 位不落地原文；
- `mcp` Connector 对 `env`/URL 做了双重脱敏（值不出机、URL 只留 `scheme://host`），测试覆盖是 7 个新源里最完整的一个；
- `kubernetes`/`dify` 均正确避免读取 `env` 值本身（只报 `env_vars_count`/环境段整体丢弃），凭据不出机的红线守住了。

### 4.4 文档滞后于代码（治理债）

- `README.md` 第 29/75/103-106 行仍只列 `hermes/docker/directory/openclaw` 四个 Connector，`docs/compatibility.md` 第 65 行仍写 `kubernetes | 待 Phase 4`——但 `kubernetes.go` 连同其余 6 个新源已经在 `325ef83` 提交（早于 round3 基线）实现并带测试。**文档口径落后代码至少 7 个提交**，且这不是"谦虚少报"，是文档没有跟着改。对一个反复强调"证据优先、如实声明差距"（README 状态说明段）的项目而言，这是一个自我矛盾的信号，也是最容易低成本修复的一项——建议下一次改动 `docs/compatibility.md`/`README.md` 时把 7 个新源按本节的真实状态（品牌专用/半通用/主机通用 + 已知缺陷）如实列入矩阵，而不是继续留空。

---

## 五、OpenShell 二次开发：本轮增量结论

**Adapter 十方法的契约语义本身零改动**——`policy_compiler.py`/`contracts.py` 全程未出现在 diff 里；`cli_backend.py` 有一处改动，但只是 `9bcc09b` 里 B4 修复触及的 `_subprocess_runner` 环境变量白名单化（见 §2.1/§3），不改变任何方法对外暴露的能力或语义。因此 round2 §4.2 与 round3 §2 的十方法契约现状表**继续原样成立**，此处不重复，只更新两点新增耦合关系：

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

1. 新的 `POST /deployments/{id}/receipt-verify` 端点（本轮 §2 已述）在语义上是"给动态网络这条唯一真实闭环再加一层独立验证"，方向对。评估开始时因为 `Deployment` 记录的产生依赖 R-1/R-6 未修的绑定链路，这个新端点在干净安装环境里同样摸不到；**评估过程中 `9bcc09b` 落地后，这条绑定链路已经打通并有 `test_e2e_fresh_deploy.py` 实测验证**（见 §3），`receipt-verify` 现在具备了被真实调用到的前提条件——但该测试本身尚未覆盖 `receipt-verify` 这一步，建议补充一条断言，让"创建部署→独立验证回执"也纳入同一条 E2E 链路。
2. `openshell_compat_check.py` 提供的版本漂移检测是一个**旁路 CI 脚本**（每周一定时或手动触发），不是 round3 B5 建议的"运行时 advisory finding"（即探测到版本与能力文档基线不一致时自动进风险中心）。方向部分吻合但落点不同：前者要人去看 CI 结果，后者是产品自己在风险中心告诉客户"我的能力基线可能过时了"。建议下一步把 compat 脚本的探测结果接一条 advisory finding 写入库，而不只是 CI 日志。

---

## 六、六阶段成熟度评分更新（对标杀毒范式，0-5 分；已按当前 HEAD `d0cfd6b` 最终代码状态定稿）

| 阶段 | round2 评分 | 本轮评分 | 变化原因 |
| --- | --- | --- | --- |
| 扫描 Scan | 2.0 | **2.5** | Connector 从 4 个增至 11 个，广度提升；Go map 非确定性已修（`9bcc09b`），但零内容特征匹配、brand-list 模式未变，`dify`/`systemd` 各遗留 1 个 high 级缺陷 |
| 发现 Discover | 3.0 | **4.0** | round3 确认任务原子领取（lease）已修复；本轮 `AgentInstance` 死路径已修复并有 E2E 测试锁定（R-1），此前的天花板问题解除 |
| 识别 Classify | 2.0 | **2.5** | `framework` 信号已参与分类（round3 P1-10）；置信度仍是拍值，未校准 |
| 风险 Risk | 2.0 | 2.0 | `rules.py` 本窗口未动，仍是纯治理状态检查，无内容/行为维度 |
| 恶意检测 Detect | 0.5 | **2.5** | 静态规则流水线（24 条规则 + AST + 签名供应链）+ R-3 内容绑定校验 + R-3b 语法失败告警均已修复并有测试覆盖；R-7 常见密钥格式已验证脱敏。**天花板仍在**：R-8 无置信度二次门槛、B-1 命中历史覆盖，未到"能信"的程度 |
| 权限管控 Control | 2.0 | **3.0** | R-1/R-6 打通后，"发现→确认→绑定→审批→部署"链路首次有 E2E 测试证明可在干净库上走通；R-4a 新增部署 API 级隔离门禁（`409 asset_under_quarantine`），是本轮唯一从"声明"变成"运行时强制"的控制点。上限仍受限于 `create_generation` 四域不可部署 + R-4b 扫描侧无归属校验 |
| 行为管控 Behavior | 1.0 | 1.0 | 无变化，`stream_events` 仍是假事件流 |
| 审计治理 Audit | 3.5 | **4.0** | OCSF 导出 + 独立部署回执验证器进一步增厚证据链，是 round3→round4 之间最扎实的净增量 |
| 跨平台 Any OS | 1.0 | **1.5** | Linux 主机覆盖深度提升（systemd/process/k8s），但零 Windows/macOS，"任意系统"仍是未兑现的表述 |

**加权判断更新**：本轮是四轮评估里唯一一次看到"权限管控"与"恶意检测"两个此前长期停滞的维度同时实质性跃升——原因是评估过程中真实发生的一次高质量提交（`9bcc09b`），而非本文自身的建议直接生效。产品目前已经从"声明性控制面"往"部分运行时强制"迈出关键一步（R-4a 的部署级隔离门禁）；**"恶意脚本检测能达到可信水平"与"任意系统全量发现"仍是两个最大缺口**——前者只差 R-8 阈值收紧与 B-1 两个小改动，后者需要 Windows/macOS 覆盖与 dify/systemd 的 Connector 级缺陷修复。

---

## 七、终版优先级清单（四轮合并去重，已按当前 HEAD `d0cfd6b` 最终状态调整）

### 已完成（截至当前 HEAD，值得认可，不需要再排期）

- **R-1**：`AgentInstance` 自动实例化 + 显式创建端点 + 环境 mode 翻转端点（`9bcc09b`，E2E 测试覆盖）
- **R-3**：`threat-scan` 内容哈希与 `asset.artifact_digest` 绑定校验（`9bcc09b`，E2E 测试覆盖）
- **R-3b**：AST 语法失败产出 finding + 4 条新文本正则规则（`9bcc09b`）
- **R-4a**：隔离→绑定自动吊销 + `POST /deployments` 隔离资产 `409` 硬门禁（`9bcc09b`，E2E 测试覆盖，实际管控效果强于原始诉求）
- **R-4b（释放侧）**：独立权限点 `quarantine:release`，release/scan 不再共用同一权限（`9bcc09b`）
- **R-6（协议层）**：Web 端 `createDeployment` 迁移到 `binding_id` 契约（`9bcc09b`，E2E 测试覆盖）
- **C2**：`threat-scan` 产出 Finding 补发 `agent.finding.opened.v1` 事件（`9bcc09b`）
- **B4**：OpenShell CLI 子进程环境变量白名单化，不再透传宿主全部环境变量（`9bcc09b`）
- **Go map 非确定性**：`docker.go`/`systemd.go`/`kubernetes.go` 三处 `knownFrameworks` 改有序切片（`9bcc09b`）
- 新增 `test_e2e_fresh_deploy.py`：全仓第一条端到端全链路正例回归测试（`9bcc09b`）
- OpenShell 版本兼容矩阵 + 周期性 CI 探测、威胁规则包签名与版本化供应链机制、OCSF v1.1.0 事件导出、部署回执独立验证器、Findings 存量 NULL 兼容修复、Web 设置页真实健康探测、Go CI 矩阵覆盖全部 11 个 Connector、任务原子领取（lease）、分类信号扩展（framework 参与）

### L1 — 检测流水线与管控最后的敞口（五条，均可独立小批量修复）

1. **R-8（优先级最高，因 R-4a 门禁已生效而更紧迫）**：`threat.py:36` `_SEVERE = ("critical", "high")` 收紧为 critical-only 或加置信度二次门槛；补"正常运维大全"负向测试集（`systemctl enable`、诊断脚本读 `/etc/shadow`、cron 备份等）。现在一次误报会通过 R-4a 的硬门禁直接拦掉生产部署，收紧阈值的紧迫性高于此前任何一轮报告。
2. **B-1**：`threat.py:103` `existing.matches = [record]` 改为 append + cap（如 50 条），而非整列覆盖，否则重复扫描会丢失历史命中证据。
3. **R-7 完整方案**：现有 `_redact_excerpt` 正则脱敏已被 E2E 测试验证对 `sk-` 类密钥有效，仍建议按 round3 原议扩展成可配置规则表 + 覆盖率测试，或改成只存 `excerpt_sha256` 的零明文方案。
4. **R-4b 扫描侧归属校验**：`threat_scan` 增加 asset 归属（`owner_user_id`）或 `agent:manage` 校验，与已修复的释放侧权限分离对齐。
5. **R-6 收尾：bindings 管理页**：`createRuntimeBinding`/`revokeRuntimeBinding` 客户端方法已写好但无页面调用，补一个登记/列表/吊销的管理页。

### L1 附带修复建议

6. **`test_threat_rulepack.py` 断言精确化**：`9bcc09b` 把 `assert len(rules) == 20` 改成了 `>= 20`，能过但不够精确，建议改成动态读取规则文件长度断言，避免未来规则数变化时测试形同虚设。

### L2 — Connector 层遗留问题（成本低、建议随手改）

7. **dify**：修复 `validateScopeOp` 恒 `true` 的逻辑错误（`9bcc09b` 未触及此文件）。
8. **systemd**：把"名称初筛"改为"ExecStart 内容优先、名称仅做提示"，消除结构性漏报（`9bcc09b` 只修了同文件的 map 非确定性，未改初筛顺序）。
9. **kubernetes**：`NetworkAccess` 声明与 `kubectl` 真实网络行为对齐；输出超预算时避免整批失败。
10. **README.md / docs/compatibility.md**：连接器矩阵按本报告 §4.1/4.4 更新，去掉过时的"kubernetes 待 Phase 4"表述。
11. `docs/detection-baseline.md` 首版（≥20 恶意样本，按类别统计召回/误报，接入 CI 回归）。

### L3 — 能力解锁（依赖外部协作，下一阶段）

12. `create_generation` 路径解锁（需 OpenShell 上游修 SandboxResponse 解码或 CLI 补建箱动作），解锁后必须实弹验证 fs/process 段真的 block。
13. 行为事件通道（OpenShell Interceptor `observe` 实测 或 eBPF/auditd Host Sensor 兜底）——双轨架构里"Host Sensor 管宿主机直跑 agent"这条腿至今没有任何代码。
14. 评测基准升级（恶意样本召回 ≥95%、置信度校准替代拍值常数）。

---

## 八、给管理层的判断

**这是四轮评估以来第一次可以说"团队把最高优先级的技术债真正还清了一大半"，而且是本文亲眼见证发生的。** 评估开始时（`b80dd28`），连续三轮报告点名的 10 项最高优先级问题一项没动；评估进行到一半，工作区出现了直接对准这些问题编号的在制品修改；评估收尾前，这批修改被正式提交为 `9bcc09b`，一次性修复 7 项、部分修复 1 项，还顺带修了本文本轮新发现的 2 个问题（Go map 非确定性、CLI 环境变量白名单），并补上了全仓第一条端到端正例回归测试。工程团队的执行力和代码质量始终没有问题——**这次真正稀缺、也最值得表扬的是排期判断力的转变**：从"优先做验收清晰的合规/供应链能力"变成"一次提交清空最高优先级技术债"。代码注释里直接写着 R-1/R-6/R-4 等编号，说明这套跨轮次评估建立的问题编号体系，正在被当作真实可执行的工程待办使用——这是持续评估机制本身价值的最好证明。

真正需要管理层关注的，是剩下这份**已经很短**的清单，建议按顺序处理，不安排任何新能力：

1. **优先级最高、也最紧迫**：R-8 自动隔离阈值收紧（`_SEVERE` 加置信度二次门槛或收窄到 critical-only）。这条紧迫性在本轮评估中被动上升——因为 R-4a 现在会把隔离直接转化为 `409` 部署硬拦截，阈值不收紧，一次误报现在能真正拦掉一次生产部署，而不再只是"日志里多一条记录"；
2. **随后**：B-1（命中历史覆盖）、R-7（把正则脱敏升级为完整方案）、R-4b（扫描侧补归属校验）、R-6 收尾（bindings 登记/列表/吊销管理页）——四项均为几十行以内的独立小改动；
3. **可并行安排给另一条线**：Go Connector 层 2 个 high 级问题——`dify` 的 `validateScopeOp` 恒真、`systemd` 的结构性漏报（名称初筛顺序），这两项与上面的 Python 侧修复完全独立。

对外表述现在可以更进一步：**"智能体资产发现、治理状态风险评估、受管沙箱策略控制与部署门禁平台（OpenShell 动态网络域已闭环，核心部署链路已有端到端测试验证）"**——比 round3 时"部署入口待打通"的表述更进一步，但仍不是完整的"扫描发现所有智能体、识别风险高低、发现恶意脚本、精准管控权限行为"杀毒软件叙事，因为 R-8/B-1 未消，恶意检测流水线还没到"能信"的门槛，`dify`/`systemd` 两个 Connector 级缺陷仍会导致"安装即发现所有智能体"打折扣，双轨架构里的 Host Sensor 行为管控腿也仍完全空缺。
