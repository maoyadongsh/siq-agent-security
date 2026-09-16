# 个人体验与局域网团队管理后续开发任务书 v5

生成时间：2026-09-15 23:21:55（Asia/Shanghai）。仓库：`maoyadongsh/siq-agent-security`。

**本轮代码基线：`53155b10c276fe41e71c47757e58e7e56d5d75d4`。** 这是当前本地工作树的已提交成果，不代表已推送或已合并到远端 main。文档提交在该基线之后，不改变代码候选。

本书汇总当前全部剩余工作，取代旧任务书的执行顺序、起点和当前状态；原 N/UX/J/O/T 编号、验收分母、安全约束与历史证据继续有效。B 编号仅用于本轮拆分交付，不能替换原目标。执行提示词见 [GLM 提示词](glm-personal-next-execution-prompt-20260915-232155.md)。

## 1. 本轮目标与已确认产品形态

先完成个人用户在 Linux、Windows、macOS 上管理 OpenClaw、Hermes、WorkBuddy 的真实闭环，再建设局域网多设备团队管理。产品定位为已有智能体与 Skill 的安全管理工具，不扩建聊天工作台。

- 自动发现，但首次检查后由用户确认权限再启用保护。
- 原生接入优先；必要时 SIQ 受控启动，用户继续用原平台界面。
- 权限增加经 SIQ 统一确认，通知只引导进入确认窗口，不能直接授予权限。
- 支持链接/本地目录的 Skill 安装，自动检查新版、展示差异、用户确认更新；平台安装拦截只声明已实测支持的范围。
- 默认本机保留操作、授权、脱敏参数、结果证据；原文单独按任务授权，秘密不进入日志或上报。
- 团队端复用现有企业控制面；个人管理 API 保持 loopback，不能为了跨设备访问开放个人管理端口。

## 2. 进入工作树与事实源

本机接续目录：`/home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914`。
分支：`kimi/personal-v4-r01-20260914`。本轮在这里继续，不切换原主工作树，不从旧远端 main 另起空树。

```bash
cd /home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914
git status --short
git rev-parse HEAD
git merge-base --is-ancestor 53155b10c276fe41e71c47757e58e7e56d5d75d4 HEAD
```

最后一条必须成功。HEAD 可以包含本书文档提交；有其他修改时先核对归属，保留它们，不 reset/clean/stash 覆盖。其他机器必须先获得包含该基线的 Git 提交，不能复制本机绝对路径或假定 origin/main 已包含它。

阅读次序：

1. 本书与 [独立复核报告](evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md)。
2. [闭环进度](personal-experience-closure-progress-20260913.md)、[当前候选矩阵](evidence/personal-experience/r06-r04-r07-review-20260915-223037/n09/report.md)。
3. 仓库及对应模块 AGENTS.md、[开发规格](agentshield-dev-spec-v1.md)、ADR-011 与相关 ADR、`packages/contracts/`。
4. [原总体任务书 v4.1](personal-experience-lan-team-next-development-taskbook-20260914-112027.md)中的原验收要求，尤其 R01/R02、J1–J11、O00–O06 与 T01–T06；它开头的旧 main/旧工作树起点不再用于本轮。
5. [协作规则](personal-platform-collaboration-acceptance-20260913-202355.md)、[Windows](personal-windows-sunbo-taskbook-20260913-202355.md)、[macOS](personal-macos-luke-taskbook-20260913-202355.md)原任务书。

旧 `SIQ_轻量化安全与OpenShell接入优化方案_20260914.md` 是设计来源，其采用部分已映射到总体 O 批次；不要再独立按旧方案并行重写架构。新发现未覆盖需求须补入本书映射并注明待决策。

## 3. 已接受基线：保留，不重新开发

| 范围 | 已验证事实 | 不能推导的结论 |
| --- | --- | --- |
| N00/N01 | 历史成果核查；状态兼容、迁移/恢复及 Linux 最低门槛 | 全部 OS、全部写入口和正式发行升级均完成 |
| R01/N05 | SEC 与权限交集；Hermes controlled_task、OpenClaw controlled_session 的历史原生腿 | OpenClaw 能证明单个 Skill 的任务级因果归属 |
| R02/N06 | 可信预留/恢复组件及部分 Linux 原生/通知传输 | 原版 OpenClaw 一定支持可信 hold 恢复；通知人眼已见 |
| R04 | 新候选 OpenClaw 更新链 30 项；有效签名下暂存内容漂移拒绝 | UP05 并发、UP07 状态兼容、UP10 公网故障完整通过 |
| R06 | systemd 用户服务注册/重启/注销/保留状态重入 | 正式发行包升级、整机重启、安装实例串联旅程通过 |
| R07 | 25 项浏览器+daemon+真实 OpenClaw 检查，嵌套更新 30 项；原文授权/撤销/默认导出隔离 | 完整安装到卸载闭环、真实到期删除、任务级导出全生命周期通过 |
| Web | 四页面加载竞态、适配器同值选择已修；旧候选反例、新候选四页面通过；95 项测试 | 可以恢复“刷新直到成功”的脚本 |
| O01/O02/O03 | 策略保真、事务漂移保护、子进程输出与等待边界；历史组件及限定真实网关证据 | 后端原子 CAS、跨进程事务、完整进程树隔离 |
| O00/O04 | 诊断/缓存/RSS 修复，组件预算及 O04 增量 HTTP 对照 | 完整优化前 B0 或真实网关 B2/B3 已测 |
| N09 | 同候选两条腿的矩阵完整性与声明覆盖有效 | 任一格 complete_acceptance，或团队前置已关闭 |

本批参考候选摘要：`5361966882f7bbdcfe44dbd942bbef1876ae93e043c744ea76158c8bdc80d942`。它不是以后构建必须匹配的“通关常量”。源码、embed、构建参数变化均记录新身份，重跑受影响用例。

## 4. 总任务清单与顺序

| 批次 | 原目标 | 优先级/条件 | 执行责任 | 完成定义 |
| --- | --- | --- | --- | --- |
| B00 | 横切 | 首先 | GLM | 基线、环境、可用发行材料、源/候选摘要、资源归属清单落盘 |
| B01 | R06/N07/J1/J9/J10 | P0 | GLM | 安装及真实双版本生命周期证据；正式信任材料缺失时分层交付 |
| B02 | R06→R07/N08 | P0，依赖可用安装实例 | GLM | 同一安装实例的 systemd 服务承载完整浏览器/宿主旅程 |
| B03 | R04/UP05/UP07 | P1，可独立推进 | GLM | 并发更新/移除及旧/未来/损坏状态写入口拒绝 |
| B04 | R07/J11 | P1，可独立推进 | GLM | 真实到期清理与任务级导出生命周期隔离 |
| B05 | R02/R07/J5/J8/J9 | P1，可独立推进 | GLM | 同候选原生失联拒绝、副作用计数、恢复；桌面视觉有条件 |
| B06 | R03/UP10/N02 | 网络可用后 | GLM | 真实托管来源正负例及生产启用评审材料 |
| B07 | O00/O04 | 本机对照先做，真网项有条件 | GLM | 完整 B0/B1 或明确缺口；B2/B3 真网性能与能力证据 |
| B08 | O05 | 真实后端/固定驱动可用后 | GLM | 可选后端会话执行与可信链集成，required 失联不回退 |
| B09 | R05/跨平台 | 外部设备/运行时条件 | sunbo/Luke；GLM 负责公共支撑 | 九组合独立实机证据，不跨格继承 |
| B10 | R07/N09 | 各腿完成后逐批汇总 | GLM + 维护者复核 | 同候选逐行矩阵、用户手册、剩余项和发布就绪材料 |
| T01–T06 | LAN-001–006 | N09 原门槛关闭后 | 后续团队周期 | 两台真实设备的部署/加入/资产/任务/策略/退出闭环 |
| O06 | 可选 P3 | O05 后且需求确认 | 条件任务 | 凭据引用与指定目标出站，不计为本期强制关闭项 |

推荐执行：B00→B01→B02；B01 缺正式发行材料时，完成不依赖它的隔离服务驱动，然后 B03→B04→B05→B07。B06/B08 条件满足再执行；B09 同步外部进度；每批更新 B10。阻塞一个任务不应停止其他可执行任务。不要先把精力放到团队功能或新增 OpenShell 概念架构。

## 5. B00：冻结本轮执行条件

交付 `docs/evidence/personal-experience/closure-b00-<timestamp>/report.md` 与 `environment.json`。

- 记录 Git HEAD、未提交文件清单、OS/架构、Go/Node/Python/Playwright/systemd/宿主实际版本。运行真实 `--version`/doctor；旧报告只能提供线索。
- 检查现有候选、测试环境、隔离 HOME/state、systemd --user 和端口可用性；不要输出环境变量全集、完整用户配置或凭据。
- 清点能否获得经过现有信任根验证的本地发行清单与两个可追溯版本。只有测试签名材料时登记 test_release，不称正式发行签名。
- 冻结脚本运行参数、预期状态码/错误码、样本和证据字段。建独立私有运行目录，记录哪些单位、端口和临时文件归本批拥有。
- 编写本批 checklist，每项有 owner、prerequisite、status、evidence_ref、解除条件。环境未知不写为通过。

## 6. B01：Linux 安装、升级、恢复与保留状态重入

### 6.1 代码路径

复用 `apps/agentshield/cmd/agentshield/client_install.go`、`client_stage.go`、`service_upgrade.go`、`setup.go`、`teardown.go`，以及 `internal/clientrelease/`、`internal/state/`、`internal/stateformat/`、`internal/statefs/`、`internal/signing/`、`internal/skillmanifest/`。
已有测试：`client_install_test.go`、`service_upgrade_native_test.go`、`scripts/personal-experience/test_systemd_user_service.py`。

先读 CLI 参数和 `--help` 再调用，不凭任务书猜测升级/回滚 flags。已有 native upgrade 测试把同一个程序复制到两个路径，只能证明服务切换，不能原样重命名为真实双版本升级。

### 6.2 开发路径

1. 建立可重跑的生命周期 runner，记录 CLI 退出码、受限错误类别、配置/历史/回执摘要、服务 PID/FragmentPath/ExecStart 归属；失败结果也归档。
2. 用独立 archive/checkout 构建旧版和当前候选，记录两个具体 commit、tree、编译参数和摘要，以及差异为什么能用于本次升级/兼容验证。不得 reset 活动工作树、只改版本字符串或修改签名文档制造差异。
3. 经现有 client-install 入口进入状态目录内制品位置，然后由产品 setup/service 生命周期接口启动实例；禁止复制二进制后直接 serve 冒充安装。
4. 通过现有事务升级/中断恢复/精确历史路径回滚；从 API 和系统管理器交叉确认当前程序、身份、版本及历史，没有旧服务并存或端口错连。
5. 在撤权后升级/重启/回退，验证旧 Grant/SEC/身份不能复活；删除安装与状态清理必须遵守现有用户确认边界。
6. teardown 保留数据后，不删除 state，不重新生成身份；通过受支持入口重新安装/启动并验证原历史保留、已撤权限仍无效。

### 6.3 LC 验收表（编号继承原任务）

| 用例 | 必须观察的结果 |
| --- | --- |
| LC01 安装预检 | 错误签名/摘要/平台/不兼容状态/缺确认拒绝；拒绝前后文件与现有服务不变 |
| LC02 首启配对 | 无效、过期、重放配对码拒绝；管理凭据不能混用决策凭据；管理页来自安装制品 |
| LC03 特殊路径/端口 | 中文/空格/% 路径实际运行；端口占用保留真实失败证据，不停止占用者 |
| LC04 后台与重启 | 精确用户单位运行、重复启动无第二进程；撤权重启仍拒绝；真实登录/整机重启未测则单列 |
| LC05 故障恢复 | 只向确认归属的实例注入故障；恢复使用记录，损坏/缺失状态不被盲写 |
| LC06 双版本升级 | 两个可追溯制品，签名/摘要通过现有边界；服务实际换到新程序，历史可读取 |
| LC07 中断/回滚 | 中断点可识别；精确历史源恢复，错路径/漂移拒绝；撤销权限不复活 |
| LC08 未知对象保护 | 无关文件、未知单位/链接和用户修改不被覆盖删除；负例前后摘要一致 |
| LC09 保留退出/重入 | 同一状态退出→重入，身份/配置/历史保留，撤销仍有效；不将全新安装当重入 |

**信任材料缺失时：** 可完成 runner、组件验证和 test-only 隔离实机层，但 release-trust leg 保持 blocked，写清需要的已签发行清单/兼容制品。不得读取未授权发布私钥、放宽信任根、增加生产 bypass 环境变量或把测试签名声明为正式发布。正式发行包验收与公开发布是两件事，本任务不授权发布。

## 7. B02：安装实例承载完整用户旅程

### 7.1 实施路径

复用 `scripts/personal-experience/r07-linux-user-journey-smoke.py`、`r04-openclaw-native-update-smoke.py` 和 B01 runner。优先抽取最小可测试的运行驱动接口，让 direct_process 与 installed_user_service 显式分开；沿用原直接进程回归，不大规模重写测试框架。

- installed 驱动记录并校验 state_directory_id、签名公钥、制品摘要、端口、unit_name、PID 和加载源；浏览器、API、宿主适配器及升级步骤必须指向该实例。
- 适配 `start/restart/stop/pair/verify`：R04 嵌套腿中也不能偷偷回落到 `subprocess.Popen(binary serve)`。新驱动不从 daemon 原文日志取码并公开保存；通过受支持配对入口在内存内使用。
- 清理只有 ownership 复验后才执行；先 teardown 成功，再处理临时制品。注销未成功不删运行中的状态目录。
- 如 shared harness 需要新参数，只接受明确的测试输入；对非 loopback、错误实例、非本批状态拒绝附着，不连接用户日常服务。

### 7.2 必须连成一条证据链

安装→后台服务→浏览器错误码重试与配对→真实实例发现→用户确认权限→原生允许/拒绝及回执→更新比较与取消→确认 V2→旧权限/身份失效→V2 重新确认→同一页面经历重启与重配对→原文授权/撤销与导出→适配器卸载→产品保留退出→同一状态重入。

- 每阶段固定实例身份和候选关联；版本切换后显式记录新候选，而不是把旧腿改写成同摘要。
- 页面一次导航；不得重试到成功。过期会话验证必须保留原浏览器文档，不先刷新丢掉 token 再声称失效。
- 宿主真实工具触发必须有独立副作用/结果证据，局部 API 请求只记 HTTP 级。
- 桌面/390px 视口检查可见性、焦点、可操作性和溢出；真实 UI 错误应修产品并重建 embed。
- 宿主提示词、名称、安装摘要或模型声明不提升为可信归属；沿用现有 SEC/Authority 和证据等级。

B02 通过必须具备机器可读 installed-service 腿，能复查整个旅程没有第二个直接启动 daemon。若只闭合 test-release 实例，明确该层，正式发行信任腿仍未关闭。

## 8. B03：更新并发与不兼容状态写入拒绝

路径：`internal/skillinstall/`、`internal/skillimport/`、`internal/state/`、`internal/stateformat/`、`internal/server/skill_install.go` 及来源调度模块；先用 rg 定位当前调度实现。沿用单 Writer、排他发布、签名计划、撤权和恢复机制。

### UP05 并发

- 两个有效管理员会话：同时 commit 同计划、不同计划更新同安装、更新与移除交错、停用来源与后台检查交错。
- 组件层用显式 barrier/事件控制交错，不能用 sleep 碰运气；服务级用真正并发请求。每次请求都记录状态码、稳定错误码和对应操作记录。
- 只能出现合同允许的唯一成功、幂等重用或冲突；未知文件不被删除，不能重复撤权、重复产生副作用或留无归属工件。
- 观察安装树、Grant revision、SEC/身份、操作/回执签名及必要审计；不能只数 HTTP 200。

### UP07 状态兼容

1. 从路由与 CLI 注册枚举相关写入口：更新暂存/提交/取消/恢复、安装/移除、来源启停/修改/调度迟到写入、Grant/身份相关写操作。产出 `write-entrypoints.json`，标明组件/HTTP/CLI 覆盖及遗漏。
2. 对未来格式、破损签名、陈旧 revision/绑定分别测试；状态格式失败不得创建目录、迁移、隔离锁、改写历史或将其“修复”为当前版本。
3. 旧/新程序真实双二进制拒写与组件故障注入分别标记。仅测试错误 artifact_digest 不再记为 UP07 完成。
4. 只在隔离负例 fixture 篡改内容；不手改生产/验收成功状态，不注入可由运行配置开启的测试缝。

保留本基线：外部原目录消失不等于导入快照失效；暂存候选内容漂移与伪造签名必须各自命中明确的拒绝分支。401/404/500、超时与意外 201 不是完整性负例通过。

## 9. B04：隐私与任务级导出完整生命周期

路径：`internal/rawcontent/`、`internal/server/raw_task_content.go`、`task_activity_export.go`、`task_activity_trace_export.go`，以及 Web 原文/任务详情模块。

- 沿真实任务：默认零采集→明确按任务授权→原生参数/输出采集→授权到期或撤销→停止新采集→密文保留到保留期限→到期清理。授权期限和保留期限不能混淆。
- 不缩短生产最低保留期或修改系统时钟凑验收。真实到期腿先创建合成任务记录，保存私有恢复定位信息和自然到期时间，再推进其他批次；到时验证。来不及达到期限则保留 pending，组件时钟测试另列。
- 至少两个任务，分别拥有到期、未到期和授权已撤记录；清理只删满足期限的密文，不删未到期内容，不改 Grant、回执、活动或审计事实。
- 测试任务级 export/trace-export：快照绑定、任务归属、跨任务错误 ID、撤权/删除后合同规定的可见性、非管理员请求、旧快照和并发变化。
- 任务原文的读取/导出权限以现有合同为准；撤销“继续采集”不自动等同删除历史原文。需求不一致先改版本化规格，不凭直觉改语义。
- 用合成 canary 扫描默认导出、任务导出、错误和日志，检查不含原文、密文载荷、token/私钥；不保存真实秘密作为 canary。
- JSON 断言、文件摘要与真实 API 结果共同取证。UI 成功提示只证明展示，不证明数据隔离。

## 10. B05：服务失联、原生副作用和通知

路径：现有 `adapters/runtime/openclaw-agentshield/`、Hermes 适配器，`internal/receipt/`、`internal/skillcontext/`、`internal/runtimeidentity/`，R02 原生及通知脚本。

- 在相同最终候选、真实已接入宿主上证明正常工具可触发，然后停止本批 SIQ 服务再触发原生必要调用：block/required 路径拒绝、独立副作用计数不增加。
- 不能用“HTTP 端点不通”代替“宿主工具未执行”。文件写入用专属标记；网络操作用隔离 loopback 接收端；读操作用不会在拒绝时到达模型的合成内容。不得借用外部业务端点。
- 恢复后旧会话/Grant/SEC/审批按实际合同复核；未知已发操作记 uncertain，不自动重放。批准、预留、执行观测、人工结案分开取证。
- 如原版宿主不支持可信 hold 消费，保持安全拒绝；只完成支持能力探测与说明，不修改宿主或把直接 /decide 调用冒充原生。
- 通知先测发送、点击路由和过期状态；桌面不可见时保留 external_manual，记录所需人工步骤。不能替 sunbo/Luke 声称系统通知验收。

## 11. B06：真实托管来源与生产入口

路径：`internal/importsource/`、`internal/skillimport/`、`internal/skillinstall/`、[ADR-0051](adr/0051-controlled-hosted-git-source.md)、`personal-experience-n03-update-source-spec.md`。

- 重测 DNS、TLS、重定向和网络条件；既有 198.18/15 阻塞只是历史观察，不能不检测就沿用，也不能通过改 hosts、取消 SSRF 或信任代理绕过。
- 使用固定 commit 的真实 HTTPS 来源，子目录、内容摘要、重定向/私网/用户信息/超限/中断/源漂移各有明确正负例；生产入口开关仍按评审程序启用。
- UP10 覆盖上游中断后无半安装、原版本/授权不被替换，恢复后需重新比较确认；旧外部 local_dir 消失测试仅证明快照独立性。
- 网络不可用时交付探测和未完成条件，继续其他任务；不得跑同一失败请求无上限重试。

## 12. B07/B08：保留轻量化与 OpenShell 剩余目标

### B07（O00/O04）

复用 `scripts/personal-experience/openshell-o04-http-comparison.py`、`openshell-o04-perf-protocol.py`、Go `internal/openshell/` 与 Python `app/adapters/openshell/`。

- 核实真正优化前的 B0 与当前 B1 源码，不把 O01–O03 之后的 `6e34f3a` 再冒充完整 B0；找不到可比较历史时给出可证明的对照范围。
- 固定硬件、配置、并发、预热、样本、轮次交错和预算；最近邻秩百分位、不剔除失败、完整留样，缺指标 not_measured。
- 未启用时零后端进程/请求需观测证明；观测授权/撤销后的真实请求，禁止缓存失效权限以提速。
- B2/B3 必须在同一真实网关/驱动环境；记录服务级、宿主级、用户级时间，CPU/RSS/磁盘/请求/进程等；RSS 不可得为 null，不伪造 0。
- 能力事实不得从 CLI 文档、版本提升、gateway info 成功自动提升为实际执行保护；过期、端点/文件漂移、失败刷新回归不能丢。

### B08（O05）

条件是存在已核实归属、版本、驱动和可用 API 的真实后端。历史 O01/O02 的真网报告不证明当前后端仍在线。

复用现有配置与 SEC、Authority、hold reservation；先落规格/合同，再实施已配置实例的会话预览/确认、最终参数/策略修订/实例身份绑定、停止和失联恢复。required 失联不得回落 native；可选 native 路径不因后端缺席而退化。

必须有真实允许与拒绝、独立副作用证据、跨会话/目标复用拒绝、策略变化/撤权重验及 uncertain 恢复。后端无原子 CAS 不宣称跨进程原子事务；无当前后端则 blocked。O06 凭据/指定目标出站保持 conditional，不自动拉入首发强制范围。

## 13. B09：外部协作与 Linux 剩余宿主

sunbo 负责 Windows；Luke-zzZ-0 负责 macOS。职责仍为实测、定位、系统适配修复并通过 PR 交付。GLM 不覆盖他们的分支，不代发消息、不代提交、合并或修改仓库保护规则。

- 设备版本/架构未知项继续待确认；Windows 原生、WSL2、容器分别登记，macOS Apple Silicon 与 Intel 不相互代替。
- 每台设备按原任务书完成三宿主发现/接入/权限/更新/通知/生命周期与安全负例；交叉编译不能关实机格。
- 公共 API/状态变更，GLM 提供迁移说明、兼容样例、组件测试和建议复测清单，交由维护者协调。
- Linux WorkBuddy 先核实上游运行时和可支持接入点，缺运行时就记录真实原因。检测到目录不代表平台已受控。
- 接收外部证据时检查源码/候选/宿主版本/报告哈希，旧候选结果不自动纳入新的统一矩阵。

## 14. B10：总验收与交付

每个 B 批次完成后更新进度，不等全部结束才一次性编造报告。

- 沿用 `personal-acceptance-baseline/v2`、九格 × J1–J11、现有 validator；未测的 coverage 不引用，不能缩分母、改编号或把 blocked 写成通过。
- 新候选改变后重跑受影响腿；旧候选有价值但只作历史证据。其他格不能直接复用 Linux/OpenClaw 的检查。
- 更新本书状态与闭环进度、支持矩阵、README 中确实变化的安装/运行说明；先保存旧证据，不改旧 hash。
- 补个人用户操作手册：安装入口、启动/配对、确认权限、版本检查/更新/回退、原文与导出、保留卸载/重入、失败恢复和真实保护边界。
- 只有原要求全部具备证据，或用户明确调整范围后，N09 才能关闭。维护者复核后再做提交/合并/发布决定；本提示词不授权 GLM 发布。

## 15. 团队后续路线（保留全部任务，当前不开工）

只有 N09 原门槛关闭才推进产品实现；本机部分完成、Win/mac 等待、O04 性能通过都不能替代该门槛。

| 任务 | 复用范围与交付 | 最低验收 |
| --- | --- | --- |
| T01/LAN-001 | 企业 control-api/Worker/PostgreSQL，TLS、管理员、迁移、备份恢复、设备主动出站 | 第二台真实设备安全连接；错误证书/身份拒绝，生产无 SQLite/开发身份头/自动建表 |
| T02/LAN-002 | 确认加入、单次限时码、注册/心跳、凭据哈希、轮换/撤销/退出/重装 | 并发重放、过期、跨团队拒绝；离线撤销期限明确，不复活旧授权 |
| T03/LAN-003 | tenant/device/instance/安装身份分层资产、增量/删除/失联、最少上报与角色可见性 | 同名设备资产不覆盖；乱序重连不复活删除项；默认不上传秘密、原文或完整私人路径 |
| T04/LAN-004 | 固定目标快照、定向/批量父子任务、lease/claim/ack、幂等/取消/部分失败 | 错设备领取拒绝，断网和重复回执可恢复；投递去重不宣称执行 exactly-once |
| T05/LAN-005 | 策略发布者、目标、版本、期限、签名及个人/组织权限交集 | published/received/applied/verified 分开；旧/篡改/错目标拒绝，两设备实际阻止越权 |
| T06/LAN-006 | 两设备加入→资产→任务→策略→断连→吊销退出、运维手册 | 至少两台真实设备，优先不同 OS；模拟压力单列，不代替实机 |

租户从验证身份派生；权限变化与审计/outbox 同事务；凭据吊销在线即时生效；离线不能假称即时撤销。不得导入兄弟仓库内部代码/数据库，不新增独立控制平面重复已有模块。团队阶段启动时先重新核实这些模块现状并细化各自协议与迁移，不照历史草案直接实现。

## 16. 不得改变的工程边界

- 发现真实缺陷允许直接修改本仓库产品源码；先复现与负向测试，必要规格/版本化合同先行，重建并复测，不以“只写脚本”为由放过缺陷。
- 仅在隔离测试状态操作；不修改日常 HOME/profile、生产服务、系统时钟、网络全局配置、宿主源码或兄弟仓库。
- Go 仅 stdlib，不引入 syscall/fcntl；状态复用签名、Writer、statefs 和不可变发布，不改 canonical 算法、不绕过 SEC/Authority。
- 无 secret 原文日志、环境变量全集、配对码截图、私钥或原文仓外泄。临时目录 0700、敏感临时文件 0600，诊断只记允许的类别与有限字段。
- 不全局 pkill/killall；不启用 linger、不重启整机。清理先确认归属，不能通过停掉其他服务抢端口。
- 不添加生产 bypass 开关或测试入口，不放宽 assertion、阈值、超时预算以让失败通过，不把任何异常都判作负例成功。
- 不提交、推送、合并、发布或更改远端治理。交付仅落盘，由用户/维护者检查；本次维护者的基线提交授权不延伸为 GLM 的提交授权。

## 17. 验证与证据格式

按改动选择验证；必要门禁必须完整记录退出码，不用最后一条命令成功掩盖前面失败。不要为凑数字重复不相关测试。

| 修改 | 必要验证 |
| --- | --- |
| Go/安全状态 | gofmt、go vet、go test 全量；受影响包 race；四目标 CGO=0 build；对应安全正负例 |
| Web | npm test、npm run build、npm run build:local；真实浏览器受影响旅程；同步 embed |
| Python 脚本 | 对应 pytest/unittest 和 Ruff；失败/超时/意外状态/资源清理负例 |
| Python 业务 API/合同 | control-api 相关测试与必要全量、schema 对等；迁移可回放 |
| 运行时适配器 | 对应真实宿主允许/拒绝/撤权/失联/卸载；副作用独立取证 |
| 文档/矩阵 | 路径链接、逐项 coverage、摘要、git diff --check（包括新增文件） |

根目录可重跑的基线例子：

```bash
apps/control-api/.venv/bin/python -m pytest -q scripts/personal-experience/test_review_journey_harness.py
SIQ_TEST_SYSTEMD=1 SIQ_TEST_BINARY=<新候选绝对路径> apps/control-api/.venv/bin/python -m pytest -q scripts/personal-experience/test_systemd_user_service.py
python3 scripts/personal-experience/r07-linux-user-journey-smoke.py --guard-only --openclaw-root <真实宿主根> --node <实际node> --binary <新候选> --out <全新文件>
python3 scripts/personal-experience/n09-baseline-check.py --matrix <新矩阵路径>
```

尖括号均为待填参数，不要原样运行。Python 环境先验证依赖；本机已有系统 Python 的 Playwright，control-api venv 未安装它。不为方便随意更新锁文件。

新证据放 `docs/evidence/personal-experience/closure-bXX-<timestamp>/`，至少包含：

- `report.md`：完成范围、证据层级、命令/退出码、问题修复、限制、资源清理和下一步。
- `checks.json`：用例 ID、原目标/J 映射、预期/实际状态码及结果、前后摘要、status、可复查 evidence_ref。失败也落盘。
- `environment.json`、源码/候选/宿主/脚本摘要；升级腿记录切换前后的不同候选，不伪造“同一候选”。
- 脱敏的必要原始结果和日志；旧日志保持字节，不手改哈希配合内容。保留失败尝试索引和失败分类。
- `SHA256SUMS`：覆盖本批可发布证据；从 Git 跟踪清单复核引用文件齐全，注意 `*.out` 可能被 ignore。新证据跨 OS checkout 不可改换行；必要时精确加 Git 属性。
- 资源清单：本批单位/端口/进程/文件的创建、归属、清理状态；无需原始私密参数。

完整源码/测试通过≠实机验收通过≠正式发布。统一使用 done、partial、blocked、external_manual、conditional 并填写理由；计数不能代替覆盖率，不给没有计算依据的总完成百分比。

## 18. 工作节奏与交接

先简述 B00 核查结果和第一个执行子任务，然后直接开发。遇到可修代码问题自主完成；涉及外部前置时写清阻塞、继续其他独立项。禁止把整份文档又变成一份不执行的新计划。

每 1–2 分钟提供简短进展；长运行脚本输出不敏感的阶段标记。自然到期等长等待期间推进独立任务，不长时间静默，也不无限重试同一故障。

每个子批次结束更新台账，最终报告写清：完成项；组件/HTTP/宿主/OS/发行证据分别是什么；剩余缺口与解除条件；实际命令/退出码；文件路径/摘要；资源和 Git 状态。额度不足时落盘当前进度、可安全重跑的下一条命令与阻塞条件，不能只依赖会话记忆。

## 19. 初始状态

维护者已提交基线；B00–B10 为本书后续执行任务，尚未因本文生成而完成。B09 外部开发状态由各协作者实际交付决定。O06 conditional，T01–T06 等待 N09。GLM 从 B00 开始，优先交付 B01/B02 的最小可复查闭环，随后继续其余具备条件的任务。

## 20. 执行状态回写（GLM，2026-09-16）

逐批状态（详细边界见 `personal-experience-closure-progress-20260913.md` v5 节与 `personal-v5-takeover-review-20260916.md`；证据在 `docs/evidence/personal-experience/`）：

| 批次 | 状态 | 说明 |
| --- | --- | --- |
| B00 | done | closure-b00-20260915-233905 |
| B01 | partial | test_release 生命周期复核 35/35（closure-b01-review-20260916，含真实消费码、301 秒自然过期、撤销 Grant 保留重入）及显式崩溃恢复 8/8；正式发行信任腿未关闭 |
| B02 | partial | 实例 HOME 隔离已实现并完成 Linux test_release 实测（closure-b02-scoped-home-20260916-r3：批次 15/15、安装服务旅程 26/26、直接进程 25/25）；复核修正见 closure-b02-home-validation-20260916。正式发行信任腿仍未关闭，旧共享 manager HOME 方案仍不采纳 |
| B03 | partial | 双 CLI 合成未来/损坏状态拒写 44/44；独立管理员配对、loopback HTTP 并发与签名 409 是另行 Go 回归，不能混称 44 项实机覆盖 |
| B04 | partial | 真实墙钟到期 19/19；两个独立 HTTP export 复核各 192/192。合成捕获不冒充宿主原生采集，保留证据等级边界 |
| B05 | partial | 当前指定候选 53619668…，共享 harness 修复后 r3 16/16；已修复忽略 --binary 而重建 HEAD 的问题。通知视觉及其他 OS/宿主未关闭 |
| B06 | conditional | DNS 重查仍 198.18/15，未绕过 SSRF |
| B07 | partial | 原声称干净的 022051 B1 实与 Go race 重叠，022225 对比已标 INVALID；最终对照 closure-b07-final-review-20260916：绝对预算全过，仅 diagnose_unconfigured 的相对 +15.79% 超 10%，其余等工作量项通过。C 工作量变化、E 无 B0，不计等工作量通过；B2/B3 仍待真实后端，fsync 占比不能证明回退由噪声造成 |
| B08 | conditional | 真实后端/固定驱动不可用 |
| B09 | external_manual | sunbo（Windows）/Luke（macOS） |
| B10 | partial | 本机文档/负向回归/矩阵更新；不代表 B02、N09 或正式发布验收关闭，最终矩阵 closure-b10-final-review-20260916 使用 B05 r3；脚本回归 33/33；复核以 personal-v5-takeover-review-20260916.md 为准 |

本批未 commit/push/merge/publish。

## 20. 2026-09-16 接管复核增量

本次由 Codex 接续中断执行。当前复核、验证结果及未关闭项统一见
[接管复核](personal-v5-takeover-review-20260916.md)和[收尾台账](personal-experience-closure-progress-20260913.md#v5-执行批次2026-09-1516进行中)。原验收分母与 sunbo/Luke 职责不变。

- `not_exercised` 不得记 PASS；进程退出 0 仅表明已执行步骤未失败，不表示任务书全部完成。
- B01 的配对重放须使用真实已消费码；重入须验证真正已撤 Grant 的签名、revision 和部署拒绝。隔离 Linux 实测用 `--runtime` 注册；不得向真实用户配置目录写固定名称“未知 unit”测试文件。
- B02 禁止修改共享 `systemctl --user` manager 的 HOME，包括设置后立即还原。现有签名 unit 拒绝未知 drop-in，不能绕过该归属校验。缺少受支持的实例 HOME 或专用用户管理器时保留 blocked。
- B03 的不同管理员会话必须分别配对取得凭据；HTTP 测试应清楚标记 loopback 测试服务器与安装 daemon 的区别。
- B04 的未知 activity ID 404 只证明不存在；真正隔离需两个有效任务的回执集合互斥、raw record 错误 task 拒绝，以及 export/trace-export 的撤销/删除/旧快照行为。当前 raw-record 错配 task 的合同错误是 503 `raw_task_content_unavailable`，不得随意改为 404 以适配测试。
- B07 冻结输入原样保留；继承注释的错误用新复核报告纠正。B0 D 无新版管道排空上界；三轮 3×(3+60)×30 秒约 94.5 分钟。C 冷探测跨版本工作量不同，E 没有 B0 实现，分别登记，不计算为等工作量门槛通过。
- CLI 原文只在调用内存中处理，证据日志仅输出类别与字节计数。测试签名种子通过 stdin 传递，不进入进程 argv 或公开证据。
