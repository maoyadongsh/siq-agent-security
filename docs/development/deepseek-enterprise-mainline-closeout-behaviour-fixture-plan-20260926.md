# 行为 fixture 通道方案（A7 唯一缺口的书面方案，2026-09-26）

> **状态：方案，未实施。** 按任务书 §7「先提交方案再实施」，等使用者逐项答复后再动手。
> 本文件不产生任何事实，不含实测数字；其中的代码行号均为只读核对所得。

## 0. 本方案要回答的四问

任务书 §7 对 A7 剩余的这唯一一件事提出了四个必须回答的问题。本文件按此顺序展开：

| 问 | 在哪节回答 |
| --- | --- |
| 范围（改哪些、不改哪些） | §5、§6 |
| fixture 如何证明「强制点真的拦住」而不是「读回配置对得上」 | §3 |
| 如何不把 `enforcement_verified` 降级为夹具产物 | §4 |
| 需要什么许可、回收怎么做 | §6、§7 |

## 1. 现状：缺口的确切位置（只读核对）

`enforcement_verified` 是刻意保留值，当前**全后端无生产者**：

- `app/adapters/openshell/contracts.py:60-61` 定义两级：`readback_verified`（配置读回）/ `enforcement_verified`（行为 fixture），
  后者注释明写「当前无后端可产出」。
- `app/adapters/openshell/base.py:53-58`：`verify()` 合同要求「`enforcement_verified` 需要真实行为 fixture 证据」。
- `app/adapters/openshell/cli_backend.py:726-732`：CLI 后端 `verify()` **只比对读回**（revision + 网络允许集），
  「没有任何行为 fixture 通道，因此通过时 level 只能是 `readback_verified`」。
- `app/adapters/openshell/fake_backend.py` / `client.py:233-237`：同理，且无任何「在边界内观测」的能力。

**结构原因**：整个适配器层只有**控制面侧**的观测手段（`read_effective_policy` 读网关自报的配置）。
没有任何一条路径能观测「策略治理的那个进程真的做了什么」。因此这不是"忘了写"，是**缺一条通道**。

**反向约束（必须保持）**：`app/tests/test_openshell_adapter.py:190-203`、`test_openshell_client.py:258-279`、
`test_evidence_topology.py:169-173` 用测试钉死了「假后端 / HTTP 后端绝不产出 `enforcement_verified`」。
本方案**不得**让这些测试变绿或变红。

**写面只支持 allow（这条决定了 deny 臂怎么设计）**：`app/adapters/openshell/policy_safety.py:183-184`
对 `effect != "allow"` 直接 `UnsupportedCapability("openshell_network_effect_unsupported")`。
即产品策略是**纯允许清单**，「拒绝」= **不在允许集里**，不是一条显式 deny 规则。
`network_rules_to_gateway`（同文件 `:288-298`）把每条规则写成 `{endpoints:[…], binaries:[{path}]}`，
即**规则可以被 (endpoint, binary 路径) 二元组限定**。

**目标侧可用原语（只读 `--help` 实测，未执行任何一项）**：`sandbox exec`（在运行中的沙箱内执行命令，
**CLI 以远端命令的退出码退出**，输出实时流式）、`sandbox upload` / `download`、`policy get/set/list`、
`policy prove`（已知：静态推演，不是行为）。

## 2. 三条设计不变量（本方案的地基）

1. **观测必须在边界内发起。** 从控制面主机发起的 TCP 连接不受该策略治理——哪怕它失败了也只证明
   控制面到目标不通。可接受的观测原点只有「策略真正治理的那个进程」。
2. **判定不在夹具里。** 放进边界内的探针程序**只报告事实**（连上了 / 超时 / 拒绝 / 重置 / DNS 失败 + 耗时），
   **不做「是否符合预期」的判定**；判定由我方仓库里的工具按下面的差分结构做。夹具自己说"我被拦住了"
   **不是证据**。
3. **不确定就不升级。** 任何一条臂缺失、矛盾、超时、或执行模式读回不是 `block`，结论只能是
   `inconclusive` → level 停在 `readback_verified`（或 `failed`），**绝不**因"看起来像"而升级。

## 3. 差分观测：为什么它能区分「真拦住」与「配置对得上」

核心思路：**让两次观测只差一个变量，且这个变量就是策略**。单点观测永远无法排除"其实是网线掉了"。

### 3.1 主方案（同 endpoint，只差 binary 路径）

| 臂 | 观测原点 | 目标 | 预期 | 它排除了什么 |
| --- | --- | --- | --- | --- |
| **A（允许臂）** | 边界内，二进制路径 `Pa` | `E:443` | **连上** | 排除「边界内网络整体不通」「目标本身已死」 |
| **D（拒绝臂）** | 边界内，二进制路径 `Pb`（**同一个 endpoint**） | `E:443` | **被拦**（非连上） | —— |
| **R（可达性对照）** | **边界外**（工具自身进程） | `E:443` | **连上** | 独立证明 `E:443` 在此刻是活的，与边界无关 |

允许清单里写一条 `(E:443, Pa)`。`Pb` **不在**允许集里，因此按 §1 的"纯允许清单"语义应被默认策略阻断。
`A` 与 `D` 只差**二进制路径**这一个变量 ⇒ 若 A 连上、D 被拦、R 也连上，
则「差别不可能来自网络可达性」，**只能来自策略按 binary 路径做了归因**。

`Pa` / `Pb` 是**同一份**探针脚本的两个副本（内容相同、绝对路径不同），
通过 `sandbox upload` 分别上传；两份的 sha256 都记入证据。

### 3.2 这个设计是对的，但它依赖一个**未测**的前提

主方案要求网关**真的按二进制路径做网络归因**。兼容矩阵
（`scripts/openshell_compat_matrix.json`）里 `interceptor: false`、网络 L3/L4 标记为
`dynamic_network_update: true`，**没有任何一条记录说"per-binary 归因已实测"**。
schema 里有 `binaries` 字段 ≠ 运行期真的按它判定。

因此**必须先做一次前置测量**（§7 的 P1-pre），确认归因是否成立：
在授权目标上写一条仅允许 `Pa` 的规则，然后分别用 `Pa`、`Pb` 访问同一 endpoint。

- 若 A 通 / D 拦 ⇒ 主方案成立，按 §3.1 出证据；
- 若 A 通 / D **也通** ⇒ **归因不成立**，此时**不得**升级（也**不得**把它当作"策略没生效"——
  它只说明"这条路无法用 binary 区分"，诚实结论是 `inconclusive` + 一条有价值的实测发现）。

### 3.3 退路（不同 endpoint + 双向可达性对照）

若 §3.2 判定归因不成立，退一步用**两个 endpoint**：`E1` 在允许集内、`E2` 不在。
两条都先做**边界外**可达性对照（R1、R2 都连上），证明二者此刻都是活的；
然后边界内观测须为「E1 通 / E2 拦」。此时变量是 endpoint（两个都已被独立证明可达），
差别同样只能归因于允许集。**退路的强度弱于主方案**（多了一个变量：两个不同目标端的网络路径可能不同），
证据里必须如实标注用的是哪一档。

### 3.4 「被拦住」必须是**签名**，不能是「没连上」

探针报告的失败形态必须落进固定词表并与"没连上"区分开：
`connected` / `timeout` / `connection_refused` / `connection_reset` / `dns_failure`。
判定规则：

- 拒绝臂出现 `timeout` 时**不能单独成立**——它也可能是路由黑洞；只有在同一 run 内
  允许臂与对照臂**都**按时 `connected` 时才接受（这就是 §3.1 三臂存在的意义）。
- 允许臂出现任何非 `connected` 形态 ⇒ 整轮 `inconclusive`。
- 两臂各重复 **3 次**，3 次结论必须一致，否则 `inconclusive`。

## 4. 不把 `enforcement_verified` 降级为「夹具产物」的机械保障

这是本方案最容易被做坏的地方。用**机制**而不是措辞来防：

1. **级别只能由一份结构化证据升级。** `verify()` 只有在收到通过校验的
   `EnforcementProbeEvidence` 时才可能把 level 置为 `enforcement_verified`；
   **默认入参为 `None` ⇒ 一切现有调用路径行为逐字不变**（仍是 `readback_verified`）。
2. **原点白名单，且是"拒绝"而非"不建议"。** 证据必须携带 `probe_origin`，
   只接受 `sandbox_exec`（= 真实边界内的命令执行）。`fixture` / `simulated` /
   `self_report` / `config_readback` **在校验器里被显式拒绝**，不是靠代码风格约束。
3. **后端的通道是能力，不是约定。** 在能力文档里新增一个能力域
   `CAP_ENFORCEMENT_PROBE = "enforcement_probe"`；`FakeOpenShellBackend` 与 HTTP 客户端
   **报 `unsupported`**（它们的 `capability()` 对未报告项本就 fail-closed 返回 `unknown`），
   因此**结构上不可能**走到升级分支——§1 列的那三条既有测试会原样保持绿。
4. **证据绑定、且会过期。** 证据必须绑定：目标沙箱 `endpoint_fingerprint`、本次 `policy set`
   的 `revision` + `applied_policy_digest`、探针脚本两份副本的 sha256、
   读回的 `enforcement_mode`、观测时间窗。
   任一项不匹配 ⇒ 校验失败 ⇒ 不升级。**过期即失效**（与 D-4「不设 TTL、以绑定对象为准」一致：
   绑定对象是 revision + digest + 指纹，对象一变证据即失效）。

   > **实施期更正（2026-09-26，P0 实现时自查发现，比上面这句更宽松也更有依据）**：
   > 本节初稿写的是「`enforcement_mode` **必须是 `block`**」——**照那样写这道门在真实路径上
   > 永远打不开**。原因：CLI 路径的 `read_effective_policy` 刻意**恒填 `unknown`**
   > （`cli_backend.py:542-544`，P1-11：`policy get --full` 的输出里根本没有模式字段）。
   > 修正规则为**矛盾时从严**：读回**明确**是 `warn` / `audit_only` ⇒ 一律拒绝
   > （行为观测与配置自述冲突，从严）；`unknown` ⇒ **不作为否决理由**——
   > 因为"边界内拒绝臂真的被拦住"本身就是**比读回更强的直接事实**，此时再要求一份
   > 读不到的自述，正是本仓库反复拒绝的「纸面门禁」。`unknown` 会如实保留在证据里。
5. **测试钉死负例。** 新测试必须包含：伪造 origin 被拒、缺任一臂被拒、两臂矛盾被拒、
   `enforcement_mode != block` 被拒、证据与 revision 不匹配被拒、
   以及"假后端即便喂进一份完美证据也仍然只能 `readback_verified`"。
6. **不接线。** 该通道不进任何门禁、不自动运行、无 `--enable-*` 默认开启；
   只能由算子对**显式指定的目标**、带显式确认开关跑一次。

> **诚实的边界（写进证据，不藏）**：探针脚本是我方受审源码 + 摘要固定 + 由我方上传，
> **在原理上**它仍可能撒谎（例如伪造 `timeout`）。本方案不假装能靠逻辑排除这一点；
> 能做的是把"撒谎"的成本提到最高（脚本只报事实、三臂结构、允许臂必须真的连上、
> 对照臂在边界外独立成立、摘要入证据），并**明确声明**："不信任夹具自述"这一条
> 只到"夹具是我方固定摘要的受审代码"为止。

## 5. 拟改动清单（逐条；**全部为新增，除标注外不动既有行为**）

| # | 路径 | 新增/修改 | 作用 |
| --- | --- | --- | --- |
| 1 | `apps/control-api/app/adapters/openshell/enforcement_probe.py` | 新增 | `EnforcementProbeEvidence` 数据结构 + `validate_enforcement_probe_evidence(...)` 校验器（§4 全部规则）+ 失败词表 + 原点白名单。纯逻辑、无 IO |
| 2 | `apps/control-api/app/adapters/openshell/probe_channel.py` | 新增 | `sandbox exec` 通道：把三臂**原样观测**取回来（`run_bounded`、白名单环境、输出上限、超时）；**不做判定**、不转发凭据 |
| 3 | `apps/control-api/app/adapters/openshell/contracts.py` | 修改（**追加**） | 增加 `CAP_ENFORCEMENT_PROBE`；`VerificationReport` 增加选填字段 `probe_evidence=None`（默认值 ⇒ 既有构造点不受影响） |
| 4 | `apps/control-api/app/adapters/openshell/cli_backend.py` | 修改（**最小**） | `verify()` 增加可选 `probe_evidence` 参数；**只有在**校验器通过时才置 `enforcement_verified`。无该参数时逐字保持现状（`:726-732` 的语义与提示语一并更新为"可产出但需证据"） |
| 5 | `scripts/enterprise-experience/openshell-enforcement-probe.py` | 新增 | 算子显式 opt-in 的一次性工具：`--target` + `--confirm-behaviour-probe` + 算子授权目录；编排三臂、跑校验器、写证据文件；**退出码 0 只在差分完整成立时出现**；屏幕与报告都打印天花板 |
| 6 | `scripts/enterprise-experience/probe/enforcement_probe_agent.py` | 新增 | 上传进沙箱的探针（**只报事实**，§2 不变量 2）。同一份内容上传两次得到 `Pa` / `Pb` |
| 7 | `apps/control-api/app/tests/test_enforcement_probe.py` | 新增 | §4.5 全部负例 + 一个**本地假强制点**（真会按规则阻断的回环服务）证明"检测器能区分被拦 / 目标已死 / 夹具撒谎" |
| 8 | `scripts/enterprise-experience/test_openshell_enforcement_probe.py` | 新增 | 工具层合成用例（不启真服务、不发真实网络、不碰真网关） |
| 9 | `docs/contracts/…-enforcement-probe.v1.md` + 证据文件 | 新增 | 证据格式合同 + 逐字留痕 |

**明确不改**：`policy_safety.py` 的纯 allow 语义、`apply_dynamic` 的整段替换语义、
任何 Vault/审批/审计路径、`fake_backend.py` / `client.py` 的现有分级行为、
兄弟仓任何源码配置、`execution_confirmation_supported`（R04 硬约束）。

## 6. 阶段、许可与回收

### P0 —— 本轮可做，**不需要新许可**（隔离合成，零真实资源）

只做上表 1、2、4、7、8 的**合成部分** + 3 的字段追加：校验器、探针通道的**接口与合成替身**、
工具骨架、全部测试。验收标准：

- `pytest` 新用例全绿，且 §1 列的三条既有"绝不产出 enforcement_verified"测试**逐字未变**；
- 一个**本地假强制点**（回环进程，真的按规则放行/阻断）上跑完整差分 → 工具正确判出 `discriminated`；
- 三个反例必须被正确判负：① 目标端口关掉（三臂结构应判 `inconclusive` 而非"拦住了"）；
  ② 夹具撒谎报 `timeout`（对照臂连上时应被识破）；③ `enforcement_mode != block` 时不得升级；
- ruff 仓库口径零告警。
- **P0 的结论档只能是「隔离验证通过」，且工具在 P0 里拒绝连任何真实网关**
  （无 `--gateway` 即报错退出，防止误用）。

### P1-pre —— 需要**单独一次许可**（真实目标，前置测量）

在授权目标（= 已指定的智能分析助手网关，canary 沙箱）上测量 §3.2 的前提：
一次真实 `policy set`（只写 1 条允许规则：同一 endpoint、只许 `Pa`）→ 用 `Pa` 与 `Pb` 各 exec 一次 → 回滚。
需要的边界说明（§3.2 要求的那套）：

- **隔离**：只用既有 canary 沙箱，不新建/不删除沙箱；只动 `network_policies` 段；
- **目标**：`siq-analysis-canary-27d1289f98fa`（或使用者另指定）；
- **回收**：沿用 R09.15 已验证的 authorizer + 回滚 + 回滚后 digest 复读（**该能力已实测存在**）；
- **新增动作类**：`sandbox upload` 与 `sandbox exec` —— 这是**本轮从未做过**的两类动作，
  即便只在 canary 内，也必须单列说明并单独取得许可。

> **R09.14/R09.15 的教训要用上**：写面是**整段替换**，所以 P1-pre 的写入窗口内该沙箱会**只剩这一条**
> 允许规则（现有网络规则中，本目标实测为 **4 条规则 / 7 个 endpoint**，R09.19 更正了原写的"8 条"口径；
> 全部消失）。若该沙箱此刻正被分析助手使用，其内部服务调用会被一并阻断。
> 执行前必须确认该 canary **当前无人使用**，并把"整段替换"写在许可申请里，不能只写"加一条规则"。

### P1 —— 在 P1-pre 结论成立后，才谈真实档证据

只有 P1-pre 判出「按 binary 归因成立」，才轮得到"真实目标上的 `enforcement_verified`"。
若 P1-pre 判出不成立，退路是 §3.3，且退路证据必须标注强度弱一档。

### 永远不做

生产目标、真实用户身份、未授权沙箱、新建沙箱、把该通道接进任何门禁或默认路径。

## 7. 待裁决的四个点（请逐项答复，不必打包）

| # | 选择 | 选项与影响 |
| --- | --- | --- |
| **F-1** | 是否按本方案实施 P0（隔离合成） | **(A) 批准 P0**（新增 9 条路径、零真实资源、不动任何既有行为）／(B) 先只审方案不动代码／(C) 缩小范围（只做校验器 + 测试，不做通道与工具） |
| **F-2** | 是否申请 P1-pre（真实前置测量） | **(A) 批准**（需 `policy set` 写入窗口 + `upload`/`exec` 两类新动作，仅 canary，含回收方案）／(B) 暂不，先要 P0 结果再议／(C) 不批准真实测量，只保留退路设计 |
| **F-3** | 探针脚本的部署方式 | **(A) 由我方仓库固定摘要上传**（本方案默认）／(B) 目标侧已有等价探针、复用它（需你指出路径）／(C) 不部署脚本，只用既有工具能表达的动作（**会显著削弱差分强度，可能直接导致不可行**） |
| **F-4** | 主/退路的判定权 | **(A) 由 P1-pre 实测结论自动选择**（本方案默认）／(B) 无论实测如何都只用退路（更保守，但证据强度弱一档） |

## 8. 本方案**不**证明什么（先写下来，避免事后夸大）

- 不证明**产品的策略编译器**是对的：证据的作用域是「这一次观测里的
  (endpoint, binary, revision, digest) 四元组被边界区别对待了」，不是"策略意图等于实际效果"。
- 不证明边界的**完备性**：三臂只能证明"该拦的拦了、该放的放了"这一对样本，
  不能证明没有旁路（例如其它协议、其它路径、IPC）。
- 不证明**拒绝原因**：观测到的是"没连上 + 失败形态"，不是网关内部为何拒绝。
- 不解除 §1 的纯 allow 语义限制：本方案**不新增 deny 规则能力**。
- **P0 本身不产生 `enforcement_verified`**（无真实边界）；P0 只证明"检测器是对的"。
- 一次通过 ≠ 长期有效：证据绑定 revision/digest/指纹，**任一变化即失效**，需重跑（与 D-4 一致）。
