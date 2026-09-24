# 独立任务书：OpenShell 沙箱 Hermes 升级至 SIQ 0.21.0

| 项目 | 内容 |
| --- | --- |
| 任务编号 | HOS-UPG-001 |
| 日期 | 2026-09-21 |
| 状态 | **已完成（2026-09-21）**；`600519-贵州茅台` 已绑定到 v0.21 pool run `canary-0921c0ffee21` |
| 唯一目标 | 将 `siq_analysis` 的 OpenShell 沙箱运行时从 Hermes 0.13.0 迁移至现有 SIQ Hermes 0.21.0，在 DGX Spark 上证明业务与安全边界不退化，并完成可回滚的受控切换 |
| 目标源码基线 | `/home/maoyd/siq/hermes-agent`，commit `42f0c8179e30cf6ba4cba0a8f2852e609f717773` |
| 固定依赖 | OpenShell 保持现有项目专用 v0.0.83 工具链；不升级宿主 Hermes，不追升级 0.21.3 |
| 主实施仓库 | `/home/maoyd/siq-research-engine` |
| 配套仓库 | `siq/hermes-agent` 仅承载必要的宿主兼容补丁；`siq/siq-agent-security` 仅承担适配器兼容验证与必要修复 |
| 预计投入 | 一名熟悉项目的工程师约 5–8 个工作日，日历预留 1–2 周；完成第一阶段后重新评估 |
| 总体方案 | [DGX Spark 全链路优化方案](dgx-spark-hermes-openshell-flagship-optimization-20260921.md) |

执行报告：Hermes 0.21.0 沙箱迁移报告（本机路径：`/home/maoyd/siq-research-engine/docs/reports/hermes-sandbox-v0210-migration-20260921.md`）；操作手册：Hermes 0.21.0 OpenShell runbook（本机路径：`/home/maoyd/siq-research-engine/docs/runbooks/openshell/hermes-v0210-upgrade.md`）；机器可读证据：manifest.json（本机路径：`/home/maoyd/siq-research-engine/artifacts/openshell/hermes-v0210-upgrade-20260921/manifest.json`）。

## 1. 任务定义与成功标准

这是一项**现有业务运行时迁移任务**。交付结果必须是：原本在旧沙箱中运行的 `siq_analysis`，能够在固定 SIQ Hermes 0.21.0 候选中完成鉴权、创建任务、SSE 输出、工具调用、报告生成、停止、租约释放和恢复；只读输入、受限写入、凭据隔离、数据代理与既有网络控制不因迁移而放宽。

不能仅以修改版本字符串、镜像构建成功、`hermes --version` 或健康检查通过结案。最终应满足：

1. 运行容器的源码、补丁、依赖、配置和镜像身份可复核，确实属于 0.21.0 候选。
2. 现有业务合同兼容，代表性真实本地模型任务能够产出通过既有质量门的报告。
3. 停止后不再存在未经管理的写入者；未知执行结果不被标记为已停止或成功。
4. 新旧状态隔离，完成旧版本回退演练，业务输出不因回退丢失或被旧快照覆盖。
5. 通过门禁后，仅切换指定 `siq_analysis` OpenShell 范围；其他 profile 和运行面不被连带升级。

本任务不是企业全链路安全认证。迁移完成后仍需保留原有能力缺口与 formal readiness 状态，不能自动将它们标为通过。

## 2. 已核查基线

以下为 2026-09-21 的现场与源码事实。实施时重新采集，不把本表当成永不过期的运行身份。

| 对象 | 已核查事实 | 实施含义 |
| --- | --- | --- |
| 宿主 Hermes | `hermes --version` 为 `0.21.0 (2026.8.31)`；CLI 指向工作区安装 | 不需要再升级宿主 |
| 目标 SIQ 源码 | `42f0c8179e…`；`git describe` 为 `v2026.8.31-2-g42f0c8179e` | 按完整 commit 固定，不追踪浮动分支 |
| 目标 SIQ 补丁 | `4c47525e2a` 已恢复 runtime home、closed-world tool allowlist；`SIQ_PATCHES.md` 还规定显式 model/provider 禁用 fallback | 对代码及测试分别核验，不能只读说明 |
| 当前研究沙箱 | 内部 `/opt/hermes-agent/pyproject.toml` 为 0.13.0 | 宿主升级未传播到镜像 |
| 当前镜像 | `sha256:523904c19a4b886e87b8340d7d359e4400a1d2e58def479e351dddad8ff1ee72` | 作为旧候选本地身份保存，不冒充发行签名 |
| 旧 Hermes 基线 | `ddb8d8fa842283ef651a6e4514f8f561f736c72e`，构建脚本固定 | 需要改造版本选择及构建输入 |
| 研究仓检查基线 | `47c0eda39119662a8f230c7a3b3bea97216abab6`，已有用户未提交修改 | 不覆盖用户修改；基线证据需包含 dirty 状态及相关文件摘要 |
| 专用 OpenShell CLI | `var/openshell/toolchains/v0.0.83/bin/openshell` | 必须显式使用；PATH 上另有 0.0.13 |
| SIQ 安全插件 | 旧健康 canary 的 `plugins: []`，未发现 profile 中的 SIQ 插件 | 本任务不能宣称是在升级一条已完成 SIQ 全链路接入的沙箱 |
| 模型可用性 | 当次 8004/8007 未连通；8006 返回 Ornith，部分配置仍声明 Gemma | 正式业务验证前单独固定可用模型，避免将模型故障误归因于版本迁移 |

目标源码与旧补丁依据：

- SIQ 0.21.0 补丁说明（本机路径：`/home/maoyd/siq/hermes-agent/SIQ_PATCHES.md`）。
- 当前构建上下文脚本（本机路径：`/home/maoyd/siq-research-engine/scripts/openshell/prepare_siq_analysis_context.sh`）。
- 旧版三个集成补丁（本机路径：`/home/maoyd/siq-research-engine/infra/openshell/patches/hermes-0.13.0/`）。
- 沙箱 Dockerfile（本机路径：`/home/maoyd/siq-research-engine/infra/openshell/sandbox/Dockerfile`）。

## 3. 范围约束

### 3.1 纳入本任务

- 固定源码与补丁语义盘点，迁移所需的最小兼容改动。
- ARM64 候选镜像、构建输入、依赖锁与运行配置调整。
- 认证文件与 runtime home 隔离、API/SSE/停止及后台任务兼容。
- `siq_analysis` 当前工具、profile、provider placeholder、broker 与挂载合同回归。
- SIQ Hermes 适配器在目标版本真实分发器中的兼容验证；发现回归时最小修复。
- 新旧运行状态隔离、指定范围灰度、停止与回退演练、交付证据。

### 3.2 不纳入本任务

- OpenShell 版本升级、gateway 数据库迁移、NemoClaw 引入。
- Hermes 0.21.3 或其他上游版本追新。
- 升级 OpenClaw，改造其他研究/投委会 profile。
- 重写研究提示词、报告模板、财务算法或整套子智能体流程。
- 新建企业 IAM connector、企业数据范围体系、机密出域策略、独立业务 Publisher 或完整效果核验平台。
- 为接入真实沙箱而新建跨命名空间 SIQ 决策桥；该工作属于总体方案的 AS-01。
- 开启原本禁用的 memory、cron、动态 Skill 安装、browser 等能力。
- 批量清理现有容器、用户会话、历史证据、旧镜像或备份。

**插件兼容与沙箱安全接入分开验收。** 本任务应在隔离的原生 Hermes harness 中证明 adapter 与 0.21.0 兼容；旧业务沙箱没有 SIQ 插件/决策桥，因此本任务不以“上线全链路 SIQ 保护”为完成条件。测试工具不得把临时同进程/同 UID daemon 的成功结果当成生产隔离证明。如果要求生产沙箱必须立即具备 SIQ 逐工具保护，应另接 AS-01/HM-01 工作，不隐含吸收进本任务工期。

## 4. 责任与修改边界

| 责任 | 所属仓库及路径 | 修改原则 |
| --- | --- | --- |
| 镜像、配置、生命周期 | 研究仓 `infra/openshell/`、`scripts/openshell/` | 主改动面；新增版本化候选，不覆盖历史冻结资产 |
| 业务调用合同 | 研究仓 `apps/api/services/` 及对应 tests | 仅处理被实际证明的兼容差异，不改变业务授权逻辑 |
| Hermes 必要行为 | Hermes 仓或研究仓版本化 patch 集 | 每项修复选择唯一维护位置；已有补丁不得再次叠加 |
| SIQ adapter 兼容 | 安全仓 `adapters/runtime/hermes-agentshield/` 及其测试 | 保持薄映射，不增加规则与私钥；如变更内嵌资产，同步其 owning paths |
| 验收与证据 | 研究仓 `docs/reports/`、`docs/runbooks/openshell/`、脱敏 artifacts | 实际状态与样本数可追溯，不覆盖旧证据 |

实施前读取所有适用 `AGENTS.md`，尤其是 Hermes 仓的完整指南。当前正在被宿主进程使用的 Hermes checkout 不作直接试验场；候选采用隔离源码导出或 checkout。不要 reset、clean 或覆盖用户已有改动；也不要因本任务自动提交、推送或发布。

## 5. 补丁迁移判定表

每行必须产生 `保留 / 已被目标实现满足 / 最小重写 / 不再需要` 之一及证据；“patch 能应用”不是语义正确证明。

| 项目 | 旧行为 | 目标核查与验收 |
| --- | --- | --- |
| `0001-runtime-auth-file-override.patch` | `HERMES_AUTH_FILE` 指向独立 auth 文件 | 0.21.0 当前 auth 源码未检出此变量。梳理实际认证读写入口；选择最小兼容 patch 或版本化配置适配，证明不在只读 profile 写 auth、不回落到宿主真实凭据 |
| `0002-runtime-state-home-override.patch` | 将 DB、PID、lock、缓存与元数据移出 profile | 目标已带 SIQ runtime home 实现，优先复用。核对 `state.db`、`response_store.db`、`runs_idempotency.db`、process/pairing 等全部可写状态，不重复打旧 patch |
| `0003-api-run-stop-quiescence.patch` | 取消任务且等待真实执行者停止，避免提前释放 writer | 新版已有拆分后的 Runs/stop 逻辑。对照状态、后台子进程和写静默测试决定是否还需补丁，禁止直接将旧单文件 patch 打到新版结构 |
| 旧基础 SIQ patch 集 | 构建脚本还绑定旧 source/patch digest | 逐项对照 `SOURCE_BASELINE` 与目标 `SIQ_PATCHES.md`；上游已有 Runs、fallback、API key 启动检查的不重复移植 |
| Closed-world tool allowlist | 只允许明确列出的平台工具 | 保留目标 SIQ 行为；检查 profile 是否实际启用相应模式，不能因升级静默附加 MCP/plugin tools |
| 显式模型固定 | 同时提供 model/provider 时不启用 fallback | 验证 request → runtime →实际 endpoint 的一致性；无效固定模型要失败，不能换模型后伪装正常 |
| SIQ runtime hook 合同 | session/task/tool_call 关联、allow/deny/hold/observe | 用真实目标 dispatcher 验证；回调异常/缺失与 HTTP 失败分别测试并说明能力边界 |

若需要在目标 commit 上增加兼容 patch，记录“上游/SIQ 基线 SHA + 新 patch digest + 最终源码树 digest”。不要因为含有新 patch 就仍宣称产物与原始 commit 字节完全一致。

## 6. 实施步骤与阶段门禁

本节是单任务内部步骤，不另立平行项目。按依赖顺序推进；每步记录实际结果及证据。

### G0：冻结现场与回退基线（约 0.5 天）

1. 采集三仓 source SHA、工作树状态、相关文件摘要；不读取或导出秘密正文。
2. 记录旧镜像 ID、固定 Hermes/OpenShell 身份、policy revision/digest、mount/config/provider 引用、真实 API 转发与 scope 注册状态。
3. 确认仅操作本任务拥有的 sandbox、目录和端口；记录当前用户流量是否走 Host、canary 或 pool。
4. 对旧状态做可恢复备份。SQLite 使用在线备份机制，或在确认写入静默后备份；禁止只复制正在写入的 `.db` 而忽略 WAL。
5. 保留旧镜像、配置、状态和恢复入口。未经核验不能将旧环境作为可用回退承诺。

**退出条件：**基线清单完整；用户改动清晰；旧环境恢复材料可读、摘要正确；未修改在役流量。

### G1：差异分析与隔离构建预检（累计约 1–2 天）

1. 按第 5 节完成补丁矩阵；核查新版依赖/Python/Node/系统库与 ARM64 wheel。
2. 对比 `/v1/runs` 请求、响应、SSE 事件、鉴权、错误码、停止及 capability 结构；建立字段/语义映射表。
3. 枚举运行状态路径、认证入口、插件加载位置、默认工具面和默认 provider 行为。
4. 确认现有构建/lifecycle 脚本是否支持独立候选。若硬编码共享 state/profile/端口，先添加受限候选参数与路径检查。
5. 固定一个可用的本地模型与同一数据 fixture，优先用显式 model/provider 固定测试请求。模型 ID 不匹配时先解决测试前提，不同时大改模型部署。
6. 更新剩余工作量；若需要改变 OpenShell 版本、大改认证体系或业务协议，标明超出估算的原因和最小替代路径。

**退出条件：**补丁去留、API 差异、状态迁移方案和候选隔离方案可审阅；没有“先关鉴权/放宽只读再跑通”的未解决项。

### G2：产出可复现的 0.21.0 候选镜像（约 1–2 天）

1. 从固定目标源码构建；仅加入已判定必需的兼容 patch。
2. 改造 `prepare_siq_analysis_context.sh` 的 source/patch 锁定方式，保留旧版构建与回退信息；新增 0.21.0 baseline 文件，不篡改旧记录。
3. 更新 Dockerfile 所需依赖与 entrypoint 检查。优先保持现有基础镜像及 Python/Node，只有证据说明不兼容才变更，并记录原因。
4. runtime config 由实际物化 profile 编译；保存 source/compiled digest 和语义 diff。模型路由、Prompt、工具面或安全字段出现非预期变化必须拒绝。
5. 验证 auth placeholder、无内联 secret、启动时认证必需、runtime home 写入完整；禁止真实凭据写入镜像层。
6. 使用独立镜像 tag 和内容摘要。禁止覆盖旧 tag 后仍引用旧证据。

**退出条件：**ARM64 构建通过；容器内确认版本/源码/patch 身份；入口在只读 profile 下启动；缺少必要认证时失败关闭。

### G3：原生合同与安全回归（约 1–2 天）

1. 在独立候选 sandbox 中测试 run 创建、查询、SSE、错误路径、幂等与模型固定。
2. 测试所有当前启用的工具类型和 provider placeholder/data broker 调用；工具集合与基线一致。
3. 做取消、断连、重复 stop、API/worker 重启与后台进程写入测试；以宿主观察确认写静默，不仅看事件文本。
4. 验证 immutable 输入、代码/profile 配置拒写及任务工作区可写；不通过扩大 mount/网络范围消除回归。
5. 在独立原生 harness 验证 SIQ adapter 的 allow/deny、真实 session/task/tool_call 关联、服务失联、撤权与安全重试语义。
6. 所有测试使用临时数据与受控接收器；不要在在用 canary 上进行破坏性探针。

**退出条件：**第 8 节必需用例通过；缺失/失败/skip 如实保留；不能用 mock 通过替代标记为原生的验收。

### G4：业务回归、灰度与回退演练（约 1–2 天）

1. 使用固定模型和授权测试快照，在 0.21.0 候选完成至少三类业务任务，见第 8 节。
2. 记录报告产物、数值/引用质量、模型实际身份、耗时及资源变化。模型输出无需字节相同，业务合同和事实质量必须达标。
3. 对迁移前后差异归因：框架、配置、模型、数据或已有失败；不得把旧有模型不可达当升级回归，也不能以旧有失败豁免新回归。
4. 演练从新候选返回旧 sandbox 路由与旧状态副本；检查无双 writer、无旧凭据跨代际复用、新产物仍保留。
5. 所有门禁通过后，在已有实施授权覆盖的窗口执行指定范围切换；若切换尚未获授权，交付具体切换包并标记 `ready_for_cutover`，不写“已完成”。

**退出条件：**指定范围真实切换及观察通过、回退已演练，才进入 `completed`。没有正式切换只记技术准备完成。

## 7. 候选运行隔离与数据处理

### 7.1 保持 OpenShell 不变

复用研究项目现有专用 OpenShell gateway，但为候选使用唯一 sandbox 名称/UUID、独立运行目录和未占用转发端口。先确认工具支持此模式；不得为新建候选改写共享 gateway 默认配置或现有 provider 凭据。

本任务不创建新的 OpenShell 版本，不执行安装器/就地升级脚本，不迁移 gateway 数据库，不操作其他 gateway。策略如因新版实际可写路径变化需要调整，只能对本候选作最小显式改动并重新做边界测试；不允许整个项目根变可写。

### 7.2 新旧状态不共写

- 两代 sandbox 不共用可写 `state.db`、sessions、checkpoints、memory、process registry、幂等库或报告工作目录。
- 首选全新 0.21.0 运行状态验证；旧会话保留，长任务在切换前排空。
- 历史会话迁移不是默认前提。确需迁移时，对副本运行、记录 schema/读写结果，并验证恢复；不能让新版打开旧正式库后再交给旧版。
- 可以共享经批准的只读证据快照；候选输出进入独立 leaf，不覆盖已发布报告。
- 保持相同的容器内业务路径合同，通过独立宿主源目录实现隔离；不能仅改路径字符串而遗漏 guard、mount plan、observer、lease 的消费者。

### 7.3 切换身份

新 sandbox 使用新 UUID/generation 和新鲜 lease、broker/runtime 身份。旧授权预留、一次性凭据或沙箱签名绑定不得复用。状态恢复不能恢复已撤销的权限。

## 8. 必需验收矩阵

| 编号 | 用例 | 通过条件 | 证据类型 |
| --- | --- | --- | --- |
| V01 | 版本与制品 | 容器内 0.21.0，baseline/patch/tree/image/config 摘要一致 | 实际容器+构建清单 |
| V02 | 无凭据启动/错误鉴权 | 必需认证缺失拒启；无效 Bearer 不获业务执行 | 真实 HTTP，零业务副作用 |
| V03 | auth/runtime 隔离 | auth 路由符合既定隔离；全部可写元数据落入指定 runtime home | 路径与文件前后观测 |
| V04 | API/SSE | 创建、事件序列、run ID、查询与终态符合消费方合同 | 原生确定性 run |
| V05 | 工具集合 | 当前 file/terminal/code_execution/web 的正常路径可用；未批准工具不自动加入 | 实际工具清单与调用 |
| V06 | 模型固定 | 显式 model/provider 命中指定模型；故障不静默换模型 | 受控模型接收计数+路由记录 |
| V07 | stop 前后 | 运行前/运行中/重复 stop；不提前报告已静默，后台写入确实停止后释放 writer | 独立写入计数/进程观察 |
| V08 | 断连/重启 | SSE 断开与 API/worker 重启后无重复高影响执行、无失管 writer | 恢复记录+副作用观察 |
| V09 | 文件边界 | 固化输入/代码/config 拒写，任务 leaf 可写，跨公司写入仍拒绝 | 临时 sentinel+宿主复核 |
| V10 | 网络与 broker | 既有 provider/broker 正常；既有拒绝路径仍拒绝，重定向/私网拒绝不退化 | 原生受控网络测试 |
| V11 | SIQ adapter 兼容 | 原生 dispatcher 中 allow/deny/observe 关联正确；block 模式失联拒绝，hold 重试不复用错误参数 | 隔离原生 harness+daemon |
| V12 | 插件异常/缺失能力 | 测出真实宿主行为并保存；新引入的安全回归必须修复，已有未提供的强制接入能力不冒充通过 | 故障注入+无/有副作用事实 |
| V13 | 业务计算与引用 | 单公司指标分析、包含财务计算与引用的报告通过已有质量门 | 本地真实模型+报告产物 |
| V14 | 完整报告 | research packs →章节→MD/JSON/HTML；相同对象/期间，schema 与引用/数值门通过 | 本地真实模型+质量报告 |
| V15 | 缺证据/工具拒绝业务 | 资料不足或工具被拒时保留缺口，不能伪报已完成 | 真实业务负向+产物检查 |
| V16 | 状态与资源 | 重启恢复、租约与 TTL 行为正确；资源限额有效，无不明孤儿进程 | 真机运行与资源记录 |
| V17 | 回退 | 恢复旧版本路由与相配状态；无双 writer、无数据丢失、正常任务恢复 | 实际演练 |
| V18 | 定向切换 | 仅指定 scope 使用新 image；Host/其他 profile/OpenShell 版本未被连带更改 | 切换前后清单 |

V11/V12 的隔离 harness 不等于生产沙箱接入已完成。若 V12 发现目标版本不满足未来 required security plugin 的强制语义，应提供明确结论与独立后续任务；在该缺口关闭前，不得宣称此候选具备该保护。反之，若发现升级破坏了原本存在的安全控制，则属于本任务阻塞项，不能外移后通过验收。

最低业务覆盖：V13、V14、V15 各至少一项，记录全部尝试、失败与重试。这只是升级 smoke 与回归门槛，不替代研究项目已有正式 A/B 的样本量或生产质量认证。优先用公开资料与合成 fixture；不为迁移测试调用付费云模型或发送真实外部通知。

性能只做同条件回归观察：记录冷启动、首事件、任务耗时、峰值内存和 stop 到静默时间。固定 timeout 内无法完成、OOM、资源无限增长或持续后台写入均不能通过；新的性能 SLA 不在本任务内凭空设定。

## 9. 测试入口与执行纪律

### 9.1 复用的现有测试

研究仓优先回归：

```text
scripts/openshell/tests/test_build_siq_analysis_runtime_config.py
scripts/openshell/tests/test_build_siq_analysis_mount_plan.py
scripts/openshell/tests/test_snapshot_siq_analysis_runtime.py
scripts/openshell/tests/test_runtime_state_lifecycle_smoke.py
scripts/openshell/tests/test_siq_analysis_lifecycle.py
scripts/openshell/tests/test_siq_analysis_canary.py
scripts/openshell/tests/test_siq_analysis_pool_lifecycle.py
scripts/openshell/tests/test_probe_siq_analysis_sandbox.py
scripts/openshell/tests/test_formal_runtime_contract.py
scripts/openshell/tests/test_switch_siq_analysis_runtime.py
```

补充本次实际修改涉及的 broker、egress、mount safety、入口与 API 消费方测试。Hermes SIQ 补丁测试入口见 `SIQ_PATCHES.md`；SIQ adapter 测试在安全仓 `adapters/runtime/hermes-agentshield/tests/`。

### 9.2 新增测试应针对真实差异

- auth 路径覆盖/非法路径/只读 profile，不依赖宿主个人 HOME。
- 新版新增的 runtime DB/lock 写入位置。
- `/v1/runs` 事件字段与现有消费方映射。
- 停止期间子进程仍写入、重复 stop、停止与完成竞争。
- 候选路径参数拒绝共享状态、符号链接或越界目标。
- 新旧状态副本恢复与 rollback 失败保留现场。

不批量改期望值让测试变绿；先说明是合法上游合同变化、SIQ 兼容适配还是安全回归。合同有破坏性变化时同步 producer/consumer 并版本化。

### 9.3 命令约束

本任务书不假定现有脚本已经支持 `--candidate` 等参数，不提供未经验证的在役启动命令。G1 完成后形成可执行 runbook，注明每条命令的 cwd、解释器、固定二进制、目标 sandbox 和可写目录。

本机研究 API venv 在前次检查中缺少 pytest。实施时建立隔离、锁定的开发测试环境；不要在生产运行 venv 中临时安装测试依赖，也不要把跨仓借用解释器固化为长期依赖。

## 10. 受控切换与回滚

### 10.1 切换前检查

- V01–V17 所需证据完整，失败/skip 没有被隐藏；版本升级验收与更广泛安全缺口分别登记。
- 当前用户请求已排空或处于明确的维护窗口；无 active/waiting/orphan writer 未处理。
- 新旧可写状态独立，镜像/配置/provider 引用/路由备份均可恢复。
- 最终候选与已测候选完全同一摘要；任何变化使相关门禁重新失效。
- 明确只切换哪个 scope、API 路由或注册绑定，并确认对 Host 基线无意外影响。

### 10.2 切换步骤

1. 暂停目标范围新任务准入，排空在途任务；不能仅断 SSE 后认为任务结束。
2. 确认旧 writer 停止/静默，保存最终旧状态与路由快照。
3. 将指定绑定指向新 generation 和经验证的候选，不整体替换所有 profile。
4. 核对真实 image、policy、mount、broker 身份与认证；执行一条正常业务及一条边界拒绝 smoke。
5. 观察首批任务的错误、质量、资源与 stop/lease；观察窗口和样本量在切换包中明确。
6. 记录最终 active binding 和 evidence，满足全部条件才结案。

### 10.3 回滚触发条件

认证绕过或关键凭据暴露、只读边界放宽、报告质量回归、连续关键 API 错误、模型静默切换、失管后台写入、状态损坏、资源异常，均触发停止新准入并评估回滚。

### 10.4 回滚步骤

1. 阻止新候选接受任务，撤销其任务/broker 能力；确认真实执行者停止后再切换 writer。
2. 保留新候选状态、日志摘要和产物。新版期间产生的业务成果单独保全，不以旧备份整体覆盖。
3. 恢复旧 image 与旧配置/路由，使用旧版兼容的原状态或经验证备份。
4. 不将 0.21.0 已迁移的数据库交给 0.13.0；不恢复已撤销凭据或已消费预留。
5. 重新建立正确代际身份，执行旧版鉴权、正常任务、停止与边界拒绝检查。
6. 回退不能安全完成时保持目标范围暂停并保存证据，不能悄悄退到无隔离 Host。

回滚完成后状态是 `rolled_back`，不是 `completed`。保留失败原因并重新形成候选。

## 11. 交付物

下列路径为建议新增位置，具体文件名可按仓库规范调整；其中候选运行材料不能进入公开 Git。

| 交付物 | 建议位置 | 最低内容 |
| --- | --- | --- |
| 迁移决策与补丁矩阵 | 研究仓 `docs/reports/hermes-sandbox-v0210-migration-<date>.md` | 每项旧 patch 去留、API/状态差异、风险与依据 |
| 版本锁与补丁 | 研究仓 `infra/openshell/` 下版本化文件 | base SHA、必要 patch digest、tree digest、依赖身份与许可 |
| ARM64 候选镜像 | 本地或已授权制品仓 | 新 tag、image/digest、可复现构建输入；不覆盖旧制品 |
| 操作与回退手册 | 研究仓 `docs/runbooks/openshell/hermes-v0210-upgrade.md` | 真实命令、隔离目录、切换/回退步骤、故障判断 |
| 验收证据清单 | 研究仓脱敏 `artifacts/openshell/` 受审放行范围 | V01–V18 结果、命令、环境、样本数、时间和摘要 |
| 私有运行材料 | 研究仓忽略的 `var/openshell/` 独立任务目录 | 私有 auth、备份、原始日志、实例映射；遵守最小权限 |
| 最终报告 | 同一任务报告与台账 | 实际 active 版本、完成/未完成、回滚演练、剩余缺口 |

证据清单至少包含：task ID、各仓 SHA/dirty 摘要、Hermes base/patch/tree、OpenShell 三二进制身份、镜像与配置、数据/模型身份、sandbox generation、测试结果、失败与 skip、回滚结果。只保存 secret 引用或摘要；日志/报告不得含 API key、token、用户正文或原始私有业务资料。

## 12. 状态、工期与风险控制

任务状态建议为：

```text
planned → assessing → candidate_built → validating → ready_for_cutover
        → canary → completed
                     ↘ rolled_back
```

任一阶段可标记 blocked，并写明证据、阻塞原因及可继续的独立工作。不得把“构建成功”“测试准备完成”写成升级已上线。

| 工作包 | 估算 | 主要不确定性 |
| --- | --- | --- |
| G0/G1 基线与差异 | 1–2 天 | 旧补丁语义、当前用户修改、模型测试前提 |
| G2 候选构建与必要适配 | 1–2 天 | ARM64 依赖、认证路径、可写状态目录 |
| G3 原生合同与安全回归 | 1–2 天 | 停止后台进程、SSE 消费兼容、adapter 调度 |
| G4 业务验证与回退/切换 | 1–2 天 | 真实模型任务耗时、业务观察与窗口 |

总投入初估 5–8 个工作日，日历预留 1–2 周；分项低值不构成更短工期承诺。若模型环境不可用或缺切换窗口，分别记外部等待，不混写成迁移代码开发时间。G1 结束后提交修正估算。

最大技术风险是“新版 API 名称相同但停止/状态语义不同”，其次是“只读 profile 下遗漏新元数据写入点”与“让新版直接升级旧状态库导致无法回退”。为降低风险，候选必须先使用独立状态，优先验证上述路径。

## 13. 完成定义与执行交接

仅当以下各项成立，HOS-UPG-001 才记为完成：

- [x] 固定 SIQ 0.21.0 候选已在 DGX Spark 的 OpenShell 沙箱真实运行。
- [x] OpenShell 仍为原版本，其他 profile/Host 运行面未被连带升级。
- [x] 补丁矩阵及最终源码/配置/镜像身份齐全。
- [x] 必需原生/API/安全/业务用例通过，未把 mock 或 skip 算作实际通过。
- [x] 无新引入的认证、文件、网络、工具或停止语义回归。
- [x] 新旧状态隔离，实际回滚演练通过。
- [x] 指定范围切换和观察完成。
- [x] 脱敏证据、真实操作手册及剩余安全缺口可审阅。

可直接用于后续实施的任务指令：

> 执行 HOS-UPG-001：以 SIQ Hermes commit `42f0c8179e30cf6ba4cba0a8f2852e609f717773` 为固定基线，将 `siq_analysis` 的 OpenShell 沙箱从 0.13.0 迁移至 0.21.0。保持 OpenShell 与宿主版本不变；先按 G0/G1 冻结基线并建立隔离候选，再按本任务书完成必要适配、原生回归、业务验证和回滚准备。保留用户改动及旧环境，不扩大到企业安全新功能。每一阶段提交真实证据，当前授权未涵盖的在役切换应以完整切换包作为最后审批对象；如已有明确切换授权则按其范围执行，不重复请求。最终按完成定义报告，不将构建成功或健康检查通过当成全任务完成。

## 14. 实际执行结论

最终候选固定为 Hermes commit `42f0c8179e30cf6ba4cba0a8f2852e609f717773`、集成 patch SHA-256 `4d1b3cffdee9ea107f221845f270e5b4f394aa996bc4d424b31266bb183b2e2a`、image ID `sha256:52c265e9329151e64e418f62e816d474940b2cd92b0ee0ba89d773c7111e3991`。OpenShell 仍为 `0.0.83`。`600519-贵州茅台` 已定向绑定到 `canary-0921c0ffee21`（`127.0.0.1:28653`），SIQ 路由后的真实模型 run 已完成；独立验证 generation `hos-v0210-20260921i` 已正常停止，旧 0.13.0 canary 与 Host 均保持健康。该 binding 保持 `NOT_PRODUCTION_CANARY` / `readiness_effect=none`，不扩展为生产正式放行声明。

V01–V18 的实际结果、首次失败与重试、干净回滚 `hos-v0210-20260921h`、AgentShield 原生 dispatcher 证据和已知限制均收录在执行报告与脱敏 manifest。业务沙箱未安装 SIQ AgentShield；该边界与第 3 节一致，不能据此扩展声称“企业安全全链路接入已经完成”。本任务没有调用付费云模型、发布外部制品或提交/推送仓库。
