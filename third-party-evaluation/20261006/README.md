# 2026-10-06 测评交付

当前用户指定的 DGX/Research Agent 与 Skill 权限测评已收口。先读 [最终报告](reports/research-permissions-final-report.md)、[复现说明](README-PERMISSIONS.md)和 [远端交付范围](PUBLICATION.md)。以下为历史阶段导航，不代表当前待办。

# 2026-10-06 测评批次

当前状态：RG01–09 已按用户限定范围完成，见[最终权限报告](reports/research-permissions-final-report.md)；10 个主证据批次、67 条签名和 20 项文件检查通过。Agent 日常入口与 Skill 专属验收入口分列，跨候选和失败边界保留。Windows／WorkBuddy 仅引用历史；原通用20任务与无关扩量延期。以下旧阶段导航用于追溯，不是当前待办清单。

最新：[ZIP准入、安装与原生工具实测](reports/native-zip-onboarding-report.md)。首试34/34检查，正常读写完成、私有读取被SIQ拒绝且无读取事件；归档、批准、安装、SEC和真实调用已关联。公网 HTTPS 后续另有[003实测](reports/remote-source-import-report.md)；其他广义旅程不由此关闭。

最新实测：[来源导入管理与完整性](reports/source-import-management-report.md)。002完成23次真实HTTP、123/123检查、6份签名；001初始化遗漏失败保留。本批 Git 获取关闭；公网成功与 ZIP 原生安装后来分别由上述专项补充，不回填本批结果。

当前方案修订入口：[基于真实功能的测评修订](plan/product-grounded-evaluation-revision-001.md)。统一六条产品链的对照与结束条件，新增16项来源实施规格；[来源复核](reports/source-capability-review-001.md)保存当时 Git 生产门禁与 HTTPS 公网证据缺口；公网后续结果见上述003报告。本次是功能/方案复核与组件检查，没有新增业务或模型成绩。

最新：[自检快照与业务授权状态实测](reports/native-runtime-snapshot-report.md)。8个快照/授权变体、16次真实产品自检完成，336/336检查符合修订预期。插件或模式变化使旧结果invalidated，恢复不复活；业务Skill漂移使实例授权暂不可用，明确撤销使授权持续不可用，但独立自检仍可passed。两类状态必须分开，不能把自检通过提升为全部业务已保护。

先读[项目功能与测评设计总览](reports/product-evaluation-overview.md)，再看[当前模式专项报告](reports/native-auth-modes-report.md)。三模式×正常/身份撤销/后端不可达的九格003实测完成，270/270项检查、54条签名。正常读写均有实际效果；故障后12个后续工具均拒绝，独立文件事件未见目标读写。认证拒绝实际位于会话登记401，断连为ECONNREFUSED；不以同一工具错误文案混同原因。0真实模型推理，沿既有任务块，不增加自然攻击或S4分母。

前序：[首读后的撤权、取消与恢复](reports/bound-runtime-faults-report.md)。原生会话首读后的撤权、取消与恢复首试61/61项符合预期。两次注入均在running且已有首读决定/观察、最终读取未获准的时点；撤权后host_failed、取消后cancelled，同实例随后正常自检passed，权限与材料均清理。

前序：[真实自检超时、撤权与恢复](reports/native-runtime-faults-report.md)。同实例自检故障批次002完成54/54检查：真实Hermes暂停后约120.85秒由产品自行timeout，attach前撤销临时Grant后约3.31秒host_failed，随后正常自检约4.30秒passed。三个临时Grant均撤销、材料清理，原业务Grant不变。

前序：[真实浏览器接入、自检与审计](reports/personal-runtime-browser-report.md)。真实浏览器已完成同候选接入、自检、活动关联、配置失效、取消及卸载，003完整批次36/36项符合预期。001未展开导航、002等待过时文案的原中断均保留unknown；三批只有一个既有任务块，不增加S4分母。

前序：[同实例产品运行自检](reports/native-personal-runtime-check-report.md)。同实例接入后的产品运行自检已完成，首试48/48检查符合预期。实际产品Hermes会话使用独立临时身份，自检通过后撤销临时Grant并清理材料，原业务Grant保持不变。配置变化使旧结果invalidated，恢复原配置也不复活旧pass；hook_load从pass转unknown，配置runtime_state按设计仍unverified。

前序批次：[同候选个人接入实测](reports/native-personal-onboarding-report.md)。本次同候选个人接入已实际串联发现→准入→审批→安装→原生工具：恶意包隔离且权限创建409，正常包批准安装后公开读写完成、私有读取grant_scope_violation。首批25/27测量检查失败保留；修正安装归属文件和原生读回格式后另冻新批27/27。这是一个开发任务块的两次运行，0真实模型推理，无新增B0，不计算自然攻击增益。

历史阶段状态：合并方案 v1.3 实施期间保留 v1.1 原范围及全部冻结成绩，阶段台账见 `implementation-progress.json`；当前交付范围以本页开头的 RG01–09 收口说明为准。

本次按用户要求先复核功能、再完善方案：[功能与执行收口](plan/product-acceptance-execution-order.md)明确六条产品链、18旅程的证据复用与缺口、后续有限批次和16个路由验收条件。原应用与直接构造Router的默认策略不同，正式测评须区分入口。该次功能收口本身只包含方案和来源复核；后续新增实测按下列报告各自的候选与协议解释。

新增[原生业务语义校准](reports/native-semantic-report.md)：发布、故障、库存、费用四种业务，分别核对答案值、实际资料读取、计算依据和引文原文。实测发现模型计算/JSON问题，也发现原引用集合评分过严；原主结果、事后复核与新v2控制分开保留。具体规则和后续门槛见[方案第14节](plan/real-business-evaluation-v2.md)，不把四个开发任务块算成S4二十块。

最新[原生文件/终端实际效果对照](reports/native-effects-report.md)：授权读写正常；固定提议下越界文件读/写与普通终端读在B0实际执行、B2拒绝。内核事件与进程标记另行取证，Hermes自身阻断不计SIQ收益。两批保留3项宿主基线预期失败，补充核验器修正Go参数摘要转义，原分数不变。见[方案第13节](plan/real-business-evaluation-v2.md)及[接入索引003](inventory/native-business-integration-003.json)。

最新接续入口：[全面功能核对](reports/project-function-understanding.md) → [40项功能追踪](inventory/function-traceability-v2.json) → [18条真实业务旅程方案](plan/real-business-evaluation-v2.md)。梳理后已完成[原应用12个机制控制](reports/business-chain-controls-001-report.md)及[Qwen/Step 5共20个真实模型校准](reports/business-chain-model-calibration-report.md)，均有独立文件/接收观察和离线验证。来源消融已见实际差异；恶意MCP后的会话污染也暴露合法发送损失。后续已补齐[24个B0三臂控制](reports/business-comparison-controls-report.md)与[36个真实模型三臂对照](reports/business-comparison-models-report.md)，并完成[PII文本归因](reports/business-taint-attribution-report.md)和[实际观察器故障校准](reports/business-observer-calibration-report.md)。该阶段后续事项中，原生业务与安全恢复已由 RG01–09 指定范围补充；研究语义评分及其余通用旅程不属于本次收口。

从[阶段报告](reports/progress-report.md)查看实测结论，从[复核与复跑说明](REPRODUCE.md)直接执行离线复核。当前材料均为作者侧运行，尚无独立第三方认证。

最新[原生Hermes简报校准](reports/native-business-briefing-report.md)完成固定提议4单元及Qwen/Step各4单元：受控越界读取B0实际泄露合成标记、B2拒绝且简报继续完成；自然模型未提出该目标读取，Step正常B2有一次效用失败。新增[真实功能验收门槛](plan/feature-acceptance-gates-v2.md)，进一步明确12类能力的证据要求，以及相对路径、安装说明权限和工具覆盖的后续任务。

关于“SIQ 有没有发挥作用、为什么模型组结果相近”，见[证据结论说明](reports/siq-effectiveness-assessment.md)：组件来源消融与新增删除动作复放已观察到阻断差异，原 240 单元模型试点尚未证明额外收益。

最新[路径与业务配置校准](reports/native-path-and-recovery-report.md)：绝对/相对/别名路径在真实宿主逐项对照；最小说明文件授权经真实审批及独立验签；Qwen/Step新配置8个任务全部完成。原路径探针缓存失败、宿主工作目录失败和Step正常任务失败保留。新配置成功不代表相对路径已修复，也未产生自然攻击阻断增益。

| 路径 | 内容 |
| --- | --- |
| `plan/` | 原方案及任务书快照，保持原文与摘要 |
| `protocols/` | 按 cohort 冻结的协议与分配清单 |
| `inventory/` | 候选身份、环境、接口绑定与适用性 |
| `reports/` | 可审阅报告、发现和限制 |
| `data/` | 白名单导出的测评数据和验证材料 |
| `private/` | 权限 0700 的候选、原始执行和独立状态 |

首轮对象是提交 `5470ab3780f2228d77b0dd856553ea9e666de815` 的独立克隆，不包含源工作区未提交变更。后续修复候选单独赋予身份，原始失败保留。用户已授权本地模型与 Step Plan 套餐下的 `step-5-preview`；每批保留调用、token、时限和独立失败记录，接口未返回的 Credit 费用保持未知。

实施阶段和产品结果分别记录。未执行的模型、原生设备与第三方盲测不得写为通过。

最新 P01 资产发现批次：2 条旅程、5 次扫描、52/52 检查通过；范围与限制见[专项报告](reports/discovery-report.md)。本轮仅覆盖 Linux 配置发现与受控文件打开观察，原生宿主仍待测；资产 UI 已另建[真实浏览器专项](reports/discovery-browser-report.md)，最新 36/36，首批未完成材料保留。

新增 [Hermes 原生更新卸载专项](reports/native-lifecycle-report.md)：最新 18/18 独立检查、3 次真实 CLI，使用确定性本地模型；旧夹具失败保留，后续[扩权、卸载冲突与 SIGKILL 专项](reports/lifecycle-attacks-report.md)完成正常重启 27/27、强杀后重启 28/28、来源完整性扩展 34/34、[同内容来源身份绑定](reports/source-identity-report.md) 42/42；活动 hook、真实来源替换等矩阵继续实施。

新增[活动插件与原生断连恢复](reports/native-resilience-report.md)：活动插件 22/22、停服后新鲜读取恢复 29/29；首批缓存导致的未完成结果保留。

新增[适配器整体卸载专项](reports/adapter-removal-report.md)：33/33，旧预览因配置变化被拒，重新确认后仅移除 SIQ 归属文件，活动插件和用户配置保留。

- [Required Intent 下的并发预留及丢响应](reports/hold-bound-concurrency-report.md)：新批 14/14；两批准备错误各 14 不确定单独保留。

- [批准重放、SIGKILL 与观察回复丢失](reports/hold-recovery-report.md)：扩展批 12/12、190/190；真实效果与 completed/uncertain 分开核对。

- [效果能否被后到批准追认](reports/effect-authorization-time-report.md)：8/8 检测单元通过；四次提前投递仍保留 harm=true，不能算拦截成功。

- [Observer 撤销与崩溃接管](reports/observer-recovery-report.md)：修正批 6/6、101/101，8 次 SIGKILL；原批两项状态码预期失败保留。

- [Grant 撤销与派发边界](reports/revocation-boundary-report.md)：8 单元完成；预留前撤销被拒，预留后写入前撤销仍出现一次真实效果（harm=true），不计为拦截成功。

- [Intent/会话绑定撤销派发边界](reports/intent-revocation-boundary-report.md)：修正批16单元、248项检查；两次预留后撤销的实际写入保留为 harm，签名撤销幂等且历史授权不变。

- [原生 Hermes SEC／身份撤销](reports/native-revocation-report.md)：两组真实正常/撤销对照各28项检查；用内核读取事件确认新路径正常可读、撤销后未读。首个身份批夹具末尾异常保留，修正批完整通过。

- [原生 Hermes 审批写入与撤销时序](reports/native-hold-boundary-report.md)：四组对照、八条完整旅程各30项检查；预留前撤销无文件，预留成功后撤销仍有一次真实写入，保留 harm=true。四条原始失败独立留档。

- [原生 SEC／运行时身份的审批重试](reports/native-held-authority-report.md)：新增16条旅程各30项检查；预留前撤销阻止写入，预留后撤销各留下一个真实文件效果，两个 harm 保留。SEC与身份的校验入口、观察接收结果分别报告。

- [原生 Intent／会话绑定审批重试](reports/native-held-intent-report.md)：另16条旅程各30项检查，预留后撤销的两个真实文件效果保留；签名撤销重试和读回一致。中文Intent签名验证器错误已修正，原数据未改。

- [五类授权事前合同绑定与40条原生复跑](reports/native-contract-binding-report.md)：每条36项检查；五次预留后写入保留harm，完整框架288项通过。

- [原生预留请求／回复丢失测评](reports/native-delivery-report.md)：新批4条各30项，丢失时无文件，随后重试重新审批；原始不完整批和错误预期保留。

- [原生daemon崩溃恢复](reports/native-crash-report.md)：四位置SIGKILL及正常重启对照，最终8条各38项；重启内核事件窗口、持久签名历史和未批准重试分别核对。

- [PII污染后的原应用新任务恢复](reports/business-pii-recovery-report.md)：旧风险保留、新干净任务真实交付、新污染任务仍拒绝；主批3旅程127条签名，首批中断与unknown单列。对应[执行细则第15节](plan/real-business-evaluation-v2.md)。

- [Hermes宿主崩溃与原会话恢复](reports/native-host-resume-report.md)：主批8条各34项，真实`--resume`保持会话/Intent，持久未观察预留拒绝重做；两条初始夹具未完成批保留。

- [引用支持v2真实模型报告](reports/native-semantic-support-model-report.md)：32单元完整，Qwen8/16、Step13/16完整业务效用；86条签名验证。明确区分计算、引用依赖和行号格式失败，无新增自然攻击阻断结论。

- [原生批量审批与宿主去重](reports/native-batch-approval-report.md)：七条各35项；85个模型重试提议经Hermes去重后仅7个进入SIQ。丢预留回复无目标打开或结果，宿主去重不计SIQ并发防护收益；原观察器及夹具失败保留。

- [terminal显式授权边界](reports/native-terminal-authorization-report.md)：工具许可存在仍因未知效果全拒绝；合法terminal效用B0为2/2、B2为0/2。8单元、20条签名，file回退与终端效用分列。

- [同Intent多会话绑定撤销隔离](reports/binding-isolation-report.md)：8个组件单元、208项检查、4次SIGKILL；选择性撤销保留另一个会话的合法操作，全局撤销拒绝两者，原签名历史不变。

- [外部签发者导入权限边界](reports/issuer-ingress-report.md)：五组API配对10/10、120/120，正常真实投递5次、攻击0次；首批理由码预期错误5/10保留。外部有效签名与注册权限、调用凭据分开核验，未关闭完整PB03。

- [18条业务旅程证据复用核对](reports/journey-evidence-reuse-report.md)：113个历史批次重新核对，111个原核验可复算，1个不完整及1个原事件错误各自保留；逐旅程登记候选和缺口，不新增产品成绩或关闭旅程。


后续拟实施项目见[独立时间戳方案](../../docs/research/SIQ_后续第三方测评实施方案_20261006-200416.md)；SafeClawBench、Skill 供应链扩展与独立隐藏集目前只有方案，未来应另建活动目录。本批[公开交付范围](https://github.com/maoyadongsh/siq-agent-security/blob/9d6e02ead7bb6f564a05caa953027c01faf7cb5d/third-party-evaluation/20261006/PUBLICATION.md)界定公开包；历史归档路径不保证都在公开仓内，精确复跑须核对实际可用材料。

## 原应用模型路由实测

[RB08报告](reports/business-model-routing-report.md)已完成14控制、保留5次原规划失败，并在另冻json_schema配置下完成5条真实Step/Qwen业务。原应用入口、实际请求、源文件和交付均可复核；不是全局DLP或自然攻击防御率。来源分级传播组件缺口/修复候选另列，默认产品接入未修改。

- [来源级别在后续模型上下文中的延续](reports/routing-source-scope-report.md)：原组件批7/8并观察到一次远端客户端越界请求，独立修复候选8/8；真实HTTP终点为本机，非公网外传。原应用112项、测评框架395项测试通过，原失败和候选补丁分别保留。

- [规划别名替换](reports/business-alias-report.md)：来源修复候选上8单元、7符合断言，仓库／范围／路径替换均拒绝；问题改写虽交付成功仍计语义失败。123条签名可复核，完整框架407项通过。

## 修复候选同版本业务回归（2026-10-06）

来源分级修复候选已补14项原应用控制（13符合预期、1故意漏观未知）及5/5真实Step/Qwen业务；共316条签名回执通过核验。详见[报告](reports/business-model-routing-fixed-candidate-report.md)及[逐条件结果](inventory/business-model-routing-fixed-candidate-integration-001.json)。这是显式json_schema配置的业务回归，混合来源修复效果仍由组件对照支撑，默认客户端及全旅程状态未改变。

- [来源修复候选真实模型业务](reports/business-routing-sourcefix-live-report.md)：5条件中4条完成，1条研究摘要空白被原解析器拒绝；Step8次／Qwen6次、92条签名。独立候选及原失败保留，不将旧批5/5回填。

- [路由剩余策略与TCP故障](reports/business-routing-edges-report.md)：4个控制均符合预期，3条真实交付；实际TCP失败无远端正文回退，70条签名、420项框架测试。Q3接续见[原生委派入口边界](plan/native-delegation-entry-001.md)。

## 路由剩余边界实测（2026-10-06）

新增[6项原应用边界控制](reports/business-model-routing-boundaries-report.md)：两项合法业务完成，仓库/范围/报告别名三项替换被真实SIQ provenance_missing拒绝且未派发，TCP拒连后没有远端正文回退。61签名核验、8类封套篡改拒绝；真实provider调用0。不是自然攻击防护率，完整产品目标继续。

- [原生委派入口](reports/native-delegation-entry-report.md)：B0真实子会话完成读写，B2明确授权仍被unknown效果门禁拒绝。合法效用1／0，不能称子级隔离通过；唯一签名决定与父身份核对，432项框架测试通过。


## 原生委派完整生命周期反馈（2026-10-06）

真实原生委派新增两批各4单元：首批父提前结束，2项B0未知且保留1项已知伤害；另冻等待协议后4项均符合预期，B0公开/私有子任务实际读写并completed，B2两项均在父级runtime_effect_unknown拒绝。合法委派效用B0为1/1、B2为0/1；父文件回退4/4，不能替代子任务效用。两批20条签名、53次受控协议请求、0真实模型推理；七类证据篡改均拒绝。与既有F055对应，原unknown、补充核验失败和另一入口批次分别保留。 详见[委派读写报告](reports/native-delegation-controls-report.md)。

后续先核对真实网络工具/显式来源桥的当前实现及公共接入，再冻结同候选合法/越界配对。委派当前路径记为不可用，不再仅替换恶意子任务文本重复全拒绝；未来支持委派时，须先验证合法子任务、真实父子身份及授权边界，再测子内越界和撤销。不关闭required Intent或另发宽权限SEC来制造通过。RB07/Q3全项、Q4–Q6、TP及S4仍未完成。


## 原生 MCP 来源入口反馈（2026-10-06）

新增实际Hermes MCP注册/分发测评：首批缺SDK、第二批控制器漏处理默认延迟工具界面，各3项unknown保留；另冻公共tool_call接续后3项完整并符合预期。B0实际lookup及报告完成，两个B2在明确许可后以runtime_effect_unknown拒绝；显式mcp_sources映射不改变效果分类。文件回退3/3，所测MCP业务B0为1/1、B2为0/2，不能合成能力通过率。10条签名和6份授权文件分列，六类篡改拒绝；三批共27次受控协议请求，0真实模型推理。 详见[原生MCP报告](reports/native-mcp-entry-report.md)。

来源捕获、select/derive与原生参数传递未到达，不宣称端到端来源保护。后续先选产品已存在效果合同的真实MCP工具，冻结对应原生协议；任意工具不可通过改名、关闭required Intent或伪造引用取得通过。其他Q3/Q4–Q6、TP及S4要求继续保留。


## 原业务 MCP 读回与来源捕获（2026-10-06）

已按现有精确效果合同接入原研究业务 `research_verify_published_report`，真实目录为 `/sandbox/siq-business`。原宿主批4项完整、1项符合预期、3项业务失败：SDK 2只读属性兼容问题导致宿主误拒绝，正确资源的SIQ决定实际为allow。隔离Hermes兼容修复候选另跑4项均符合预期：三个合法配置实际读回并写摘要；错误目录以grant_scope_violation被拒绝、服务未收到调用。两个候选各11条签名、16次受控协议请求，0真实模型推理，仍只是一块开发业务。

显式映射组的低信任来源已与真实post结果、报告摘要、作用域及签名逐一绑定；默认配置未自动产生该来源引用。初批来源绑定宿主错误字符串，不能算业务读回成功。来源捕获与后续select/derive、原生参数引用传递分开验收。原失败保留、活动宿主未修改、通用未知MCP/委派的既有边界不因此改变。详见[实测报告](reports/native-business-mcp-report.md)。


## 原生来源字段选择及默认参数入口反馈（2026-10-06）

原业务MCP来源后续已实际探测：初批误用管理凭据，四项选择401且保留批次失败；另冻同一已安装实例凭据的新批后，原字符串选择字段返回provenance_missing，解析为对象或改字符串返回provenance_content_mismatch。父来源正常解析200；真实读回和摘要两批均成功。默认pre hook没有parameter_provenance/context_assertion_id，实际Intent为v2。选定参数能力不可用，不能将诊断符合预期当作端到端来源链通过。

两批各一个既有业务单元、四次受控协议请求、四条签名；合计十项显式API诊断、0真实模型推理。六类离线篡改拒绝，测评框架561项及118子检查通过。本断点不重复扩量，后续按Q4补固定候选个人发现→准入→审批→安装→真实执行；Q3显式来源桥及其他未完成要求继续保留。详见[字段选择报告](reports/native-business-mcp-selection-report.md)。
