# CL-04 绑定证据前置（内部只读证据就绪度）交接

任务：`CL-04-BINDING-EVIDENCE-READINESS`（S4“绑定失效联动与共享影响确认收口”的**证据前置子项**）。
本子项**不关闭 S4/CL-04**，不声称已具备完整共享影响确认，不关闭整体项目。

## 1. 产出与所有权

新增（**只新增，未修改任何既有文件**）：

| 文件 | 内容 |
| --- | --- |
| `packages/contracts/enterprise-binding-evidence-readiness.v1.md` | 冻结的证据要求：五维度逐项清单（所需事实/现有权威来源/当前能否取得/不能取得的原因/安全引用/不能推导的结论）、固定状态词表、固定原因码、安全输出约束、未定事项与前置 |
| `apps/control-api/app/binding_evidence_readiness.py` | 内部只读检查模块 `assess_binding_evidence(session, identity, binding_id)` |
| `apps/control-api/app/tests/test_binding_evidence_readiness.py` | 9 个测试（含要求的 8 组场景 + 身份前置拒绝） |
| 本文件 | 交接说明 |

**不是 HTTP 接口**：没有新增路由、schema、字段、权限、审批、审计或迁移。
`grep -rl binding_evidence_readiness` 只命中本模块与它自己的测试与合同——**没有任何既有入口调用它**
（当前是待评审的、不可从外部触达的模块，见 §3）。

工作树状况（`git status`，任务开始时与结束时一致）：`models.py`、`schemas.py`、`routers/deployment_preview.py`
是**他人在途改动**（`models.py` 最后修改 09-26 00:39、`schemas.py` 09-25 14:46，均早于本任务），
`binding_identity.py`、`target_authority.py`、`routers/deployment_impact.py`、
`packages/contracts/enterprise-runtime-binding-identity.v1.md` 属未跟踪的既有成果。
本任务的四个文件均为新增（`??`），未触碰上述任何文件。

## 2. 本模块做了什么（只读，不造证据）

对**一个已登记绑定**，逐维度报告“现有已验证持久记录能核对到什么程度”，并为不能成立的情况给出固定原因码：

- `registered_identity`：复用 `app/binding_identity.py` 的 `snapshot_binding_identity` +
  `require_binding_identity_unchanged`（列级重读、绕 ORM identity map、重跑实例⨝资产来源核对）。
  **不复制第二套绑定判定**；409 拒绝码只映射为就绪度状态，不采用新值、不重试。
- `device_origin`：复用 `app/framework_source_view.py::project_framework_sources`
  （按 `discovery_scope` 关联设备+环境，要求唯一匹配的证据六元组）+ `app/discovery_identity.py`
  的设备证据谓词。只核对**资产**层的设备来源。
- `role_skill_version`：四个独立子事实。目录候选复用 `app/role_skill_roots.py::parse_role_skill_roots`
  校验已入库的候选记录；显式声明读 `role_skill_selection_observation`（本租户+资产+设备）；
  安装观察读 `skill_installation` + `skill_manifest_observation`；**实际运行加载无来源**。
  声明/安装/历史 revision 这三处是**租户（+设备）限定的直接只读查询**，不复制任何判定
  （既有 `inventory_query` 的投影面向游标分页列表，本层只需“最新一条 + 计数”，故未套用其输出形态）。
- `execution_identity`：历史 revision 读 `deployment`（只读 `receipt/verification` 的**存在性标志**，
  不载入正文）；当前读回、目标授权无来源；人工 attestation 只报“是否存在”。
- `shared_impact`：**恒为能力未建立**，只回同主体 `active` 登记数量（登记层事实）。

边界：只做租户限定的 `SELECT`；全部查询在 `session.no_autoflush` 内执行（不隐式刷新调用方会话的
待提交状态）；不写库、不审计、不发事件、不发网络探测、不读 `target_authority` 文件、不新增文件读取面；
输出不含 attestation 正文、签名、密钥、路径、名称列表、`locator_sha256`、其它租户对象；
`execution_confirmation_supported` 恒为 `false`，无任何可执行开关。

## 3. 逐维度：现在有什么真实来源，缺什么（合同 §3 的代码侧结论）

| 维度 | 现在能核对的真实来源 | 当前结论 |
| --- | --- | --- |
| 登记身份 A | `runtime_binding` + `binding_identity.py` 复验函数 | **能做**：同租户一致且 `active` → `verified_from_records`；吊销/漂移 → `records_inconsistent` |
| 设备与观察来源 B | `agent_asset.discovery_scope` → `edge_agent` + `environment` + 同设备 `evidence`（复用既有投影与谓词） | **只能到资产层**：绑定与实例**没有设备字段**，设备归属不得由资产反推 |
| 角色与 Skill 版本 C | 目录候选（资产属性记录）、显式声明（`role_skill_selection_observation`）、安装观察（`skill_installation`/`skill_manifest_observation`） | **三个子事实可核对**，但**实际运行加载无来源** ⇒ 维度永不 `verified_from_records` |
| 执行身份与沙箱 D | 历史 revision（`deployment` 行） | **只有历史记录**：当前读回需实时探测、目标授权需实时连接身份，本层都不做 |
| 共享影响与覆盖 E | 无独立运行时占用来源；只有登记唯一约束与会话内登记数 | **恒为能力未建立**：`shared_runtime_occupants` 保持 `unknown` |

必须补采集/存储合同才能推进的前置（不在本轮造字段、不伪造证据）：

1. **运行时实际加载**（Skill/角色）—— 需要独立加载观察来源。
2. **运行时占用与沙箱独占** —— 需要独立占用来源 + **业务判定的共享标准**。
3. **沙箱 revision 进入绑定身份** —— 属 S4 拥有者文件（`binding_identity.py` / `models.py`+迁移 / `bindings.py`），本任务不改。
4. **绑定/实例的设备绑定** —— 现无设备字段，需新登记字段与合同。
5. **人工 attestation 的独立核验** —— 需要服务端可独立核验的来源。

## 4. 未来接入点与接入前条件

- 生产者：`apps/control-api/app/binding_evidence_readiness.py`；
  接口：`assess_binding_evidence(session: Session, identity: Identity, binding_id: str) -> dict`。
- **建议的既有入口**：只读影响预检 `POST /api/v1/deployment-preview/impact`
  （`app/routers/deployment_impact.py::inspect_deployment_impact`）——在它已验收的
  `require_binding_identity_unchanged` 之后、`_snapshot`/digest 之前**附加**一次内部读取。
  该入口已经 `ensure_permission(identity, "agent:read")`；**本模块自身不做权限判定**，权限必须由调用入口执行。
- 接入前仍需：§3 的 5 项前置；是否投影到 wire 及 schema 的独立决策与合同升级；以及“不得据本结果
  开放执行按钮”的评审。
- **为什么不能开放执行**：本层只说明“记录能否核对”，不说明“允许执行”。执行链的
  `execute_deployment` 复验**必须保留**，不得被本层替代或弱化；本层恒不返回可执行结论。
- 本模块**不制造绕过真实证据要求的生产入口**：所有结论都读自持久记录，判据全部复用既有函数；
  测试中构造的是**记录**（任何测试都要造夹具），模块自身不生成、不推断、不缓存证据。

## 5. 最小验证（已执行）

工作目录 `apps/control-api`，使用 `uv run --no-sync`，未安装依赖、未跑全量后端/前端/Go：

| 命令 | 结果 |
| --- | --- |
| `pytest -o addopts='' -q app/tests/test_binding_evidence_readiness.py` | **9 passed**（新文件） |
| `pytest -o addopts='' -q app/tests/test_binding_evidence_readiness.py test_binding_source_identity.py test_binding_execution_recheck.py test_framework_source_view.py test_discovery_origin.py test_role_skill_roots.py test_skill_inventory.py test_role_skill_sources_view.py test_deployment_impact.py test_deployment_impact_consistency.py` | **116 passed**（复用目标与影响链既有回归） |
| `ruff check app/binding_evidence_readiness.py app/tests/test_binding_evidence_readiness.py` | All checks passed! |
| `git diff --check` | 退出码 0 |

覆盖的场景（对应任务第六节要求）：

1. 登记身份一致：`verified_from_records`，且**不使**其它维度自动可核对（记录自洽 ≠ 证据齐全）。
2. 同名跨租户/跨设备不串联：跨租户结果与“不存在”逐维度完全相同、不泄漏对方标识；
   另一设备上的声明与安装观察不进入本资产；同一资产出现**其它设备**的声明 → `records_inconsistent`
   /`declaration_device_mismatch`（不合并归属）。
3. 来源损坏或悬挂引用：指向不存在设备的 `discovery_scope`、其它租户的设备、已吊销设备、
   设备与环境不一致、非法框架来源 JSON、完全无来源记录 —— 全部 fail-closed，且
   `no_device_evidence_must_not_select_any_device` 明确禁止“从环境里任选一台”。
4. 只有 `active`/attestation 不能通过运行归属：`active` 只使登记身份可核对；
   attestation 存在 → `source_unavailable`/`attestation_not_independently_verified`，**正文不外泄**。
5. 有安装观察不等于真实加载：观察来自**真实签名上传路径**（复用 `test_skill_upload.upload_case` 夹具），
   子事实可核对，但 `runtime_load` 恒为 `capability_not_established`，且名称不外泄。
6. 只有一条绑定不等于独占：登记数 1 与 2 的共享影响状态、原因、不得推导集**完全一致**（登记数不是独占判据）。
7. 无证据不返回可执行：所有场景 `execution_confirmation_supported is False`，
   唯一含执行语义的键就是它本身（按关键字遍历断言）。
8. 读取前后计数无写入（15 张相关表逐一比对）+ 输出不含合成秘密 canary
   （attestation 载荷、技能名称、`discovery_scope`、他租户全部标识）。

合同与实现逐项对照（脚本核对，非人工目测）：`REASON_CODES` 与合同 §4 代码块**集合完全相等**
（双向无差集）；五个维度的 `must_not_infer` 常量全部出现在合同文本中；状态词表、维度名、
`schema_version` 均一致；实现中不含 `session.add/commit/flush/merge/delete` 等写调用。

## 6. 未解决边界（必须随结论一起阅读）

- **SQLite 不证明 PostgreSQL**：并发隔离级别与真实锁行为未验证。
- **不是原子快照**：结论由多条独立只读查询顺序得出，查询之间或之后发生的并发提交不在覆盖范围内
  （无锁、无租约、不做 TOCTOU 消除）。登记身份复验只表示“复验时可见的漂移会被拒绝”。
- **设备来源只到资产层**：绑定与实例没有设备字段；资产设备关联**不构成**绑定的设备归属，
  也不证明运行时占用。跨租户与悬挂的设备引用在本层**无法区分**（不做跨租户读取，故统一按“来源不可核对”）。
- **角色/Skill 三子事实**只说明相关记录可核对；`manifest_sha256` 只标识完整 `SKILL.md`，
  不是技能包版本；声明名称不是安装归属；`runtime_load` 无来源。
- **目标授权与当前 revision** 需要实时连接身份/探测，本层不读授权文件、不发探测；历史记录**不得**
  替代当前状态。
- **人工 attestation 仍是租户提交的登记佐证**，未升格为独立核验。
- **共享影响**：登记唯一约束使“查不到第二条绑定”恒真，因此单条绑定**不构成**独占证据；
  完整影响确认不能由用户勾选替代证据；`shared_runtime_occupants` 保持 `unknown`。
- **无证据有效期合同**：本层不引入 TTL、不设 24 小时等默认值；未确认即未确认。
- **本轮不做**：不新增运行时占用来源、不新增探测/后台扫描/写库/审计/任务、不改执行权限或审批、
  不改 `binding_identity.py` / `models.py` / 迁移 / 公开权限或审计、不改已验收的预览/影响/执行链、
  不接前端/Edge/Connector、不动公开台账与依赖。契约变更须先改 `packages/contracts/` 并升版。

## 7. 需要用户（业务）决策 vs 纯开发工作

**需要用户/业务决策**：

1. **共享沙箱独占性的判定标准**（S4 既有决策点）—— 标准不由模型设定；没有它，E 维度只能保持未建立。
2. **证据有效期**：是否需要、以什么期限为准。仓库内没有任何既定期限合同，本层不自行设定。
3. **证据就绪度是否对用户可见**，以何种措辞与粒度（避免被读成“可以执行”）。
4. **是否给绑定/实例增加设备登记字段**（新增登记字段属产品与合同决策，本任务不造字段）。

**纯开发工作（决策后可直接排期）**：

1. 在 §4 的建议接入点加一次调用 + 面向调用方的测试（若仅内部使用，无 wire 变更）。
2. 若需投影到 wire：先升版合同、定 schema，再实现只读投影与相应负例。
3. 前置 1–5 的采集/存储合同与迁移实现（依赖 1–4 的决策）。
4. 为新增来源补对应的“不得推导”码与测试，保持原因码集合有限且与合同一致。

**状态**：仅声明本内部证据前置子项完成。**不关闭 S4/CL-04，不声称已具备完整共享影响确认，
不声明整体项目或正式发行完成。未提交、未推送、未部署。**

## 8. 主开发者验收修复（2026-09-26）

发现并修复两类过强判定：声明持久行存在即 verified（损坏结构也通过），以及目录候选
只校验结构而未校验所属框架。先增加负例，原实现实跑 **4 failed / 10 passed**：
非对象、空对象、非法状态的声明，以及 Hermes 资产上 OpenClaw v1 目录结构分别失败。
未替换共享工作树文件、未删除原测试。

最小修复：声明复用 `RoleSkillSelection.model_validate`，非法值不回显；声明仅适用于
OpenClaw 资产。目录复用 `validate_role_skill_roots` 配对框架/来源版本，沿用
`layout_candidate_invalid`。新增 `declaration_record_invalid` 原因码，遵守原合同的
升版要求，新增 `enterprise-binding-evidence-readiness.v2.md`，保留 v1 正文并加版本导航。
无公开 wire、权限、执行链或数据库结构改动。

最终验证（`apps/control-api`）：

```bash
uv run --no-sync pytest -o addopts='' -q \
  app/tests/test_binding_evidence_readiness.py \
  app/tests/test_binding_source_identity.py \
  app/tests/test_binding_execution_recheck.py \
  app/tests/test_role_skill_roots.py app/tests/test_role_skill_selection.py \
  app/tests/test_deployment_impact.py app/tests/test_deployment_impact_consistency.py
uv run --no-sync ruff check app/binding_evidence_readiness.py app/tests/test_binding_evidence_readiness.py
```

结果：**97 passed**（其中就绪度文件 15 项，原 9 项保留）；Ruff、`git diff --check`
通过。仅既有 Starlette/httpx 弃用警告，未安装依赖。不是全量或生产验收。

代码搜索确认无测试以外的既有调用入口。只读保证是当前调用链与 no_autoflush 的边界，
不是对任意未来辅助函数的结构性写入禁止；非空 tenant_id 也不是身份认证。
设备级历史安装观察不得解释为本角色安装集合；字段校验不构成签名重新验证、记录全链
抗篡改核验或运行时归属证明。人工合成的声明夹具不证明真实 OpenClaw 采集旅程。
完整 S4 证据来源与共享影响确认仍未具备，执行确认恒 false。

本轮修改模块、原测试和交接记录，新增 v2 合同，仅为 v1 增加导航；其它开发线文件不动。
**验收结论：本内部子项修复后通过上述定向验证；未提交、未部署，不关闭 S4/CL-04。**
