# 个人体验与局域网团队开发台账

> **最新执行入口：[任务书 v3.0](personal-experience-lan-team-next-development-taskbook-20260913-192253.md)；[接续台账](personal-experience-closure-progress-20260913.md)。** N00 已核查；N01 经 PR #35 合入 main `0d4133f`，达到代码/Linux 最低门槛。自动检查、生产 Git、可信 Skill 归属、真实审批恢复及跨 OS/团队仍待验收。下方为历史阶段记录。

> 当前执行入口（2026-09-13）：[后续开发任务书 v2.0](personal-experience-lan-team-next-development-taskbook-20260913-160928.md)。全部已核查分支已通过 PR #32 合入 main `983b820`；后续从最新 `origin/main` 新建工作树，先个人闭环再 LAN。本文下方的旧基线、未提交/未合并表述和完成度数字均为各阶段历史记录，不代表当前状态。

> 2026-09-13 M132 审查修复：获取失败分类、请求/结果合同与个人检查入口已补齐；生产 Git 获取在具备完整安全传输前明确拒绝，HTTPS ZIP 新版检查可用。回归与浏览器验证见 [本批记录](evidence/personal-experience/stage-fixes-m132-20260913.md)。UX-010 保持 doing，自动定期检查、Git 安全传输和原生更新验收继续待办。

> M129/M130 独立验收的四项缺陷已修复并通过组件复验，见 [修复复验记录](evidence/personal-experience/stage-fixes-m129-m130-20260913.md)。限制模板现按实际操作效果裁决，场景不匹配返回冲突，通知失败有独立退避且不记录子进程原始输出。该结果不提升跨 OS、WorkBuddy、真实通知投递或团队阶段的验收状态。

> 2026-09-13 阶段复核：M124–M128 的审查修复与验证见 [阶段修复记录](evidence/personal-experience/stage-review-fixes-20260913.md)。OpenClaw 安装兼容性已修复并重跑原生会话；Skill 元数据匹配不能证明执行来源，M128 的 verified 口径已收紧。另一窗口的后续开发不计入本次验收。

- 开始时间：2026-09-10，Asia/Shanghai。
- 持续目标：[开发任务书](personal-experience-lan-team-development-taskbook-20260910-145507.md)。
- 基线：`a2f95c6fad1a04c776d57c4d4b9fd89b85c69b33`，当前 `main` 工作区。
- 用户授权：在本仓增量实现并验证；不自动提交、推送、发布。
- 既有改动：Vitest 4.1.11 的 `apps/web/package.json`、`package-lock.json`，以及原任务书，继续保留。

### 历史续开发基线（2026-09-12，M36 时点）

- 用户再次指定任务书为持续开发目标，目标已登记为 active；先个人 UX，再 LAN。
- 当前分支 `codex/personal-k002-platform-readiness`，HEAD `a195faba41d128d21222f819ebf96a766fb9cd01`。上方 main 和 Vitest 工作区描述为 2026-09-10 历史记录。
- 本轮开始仅任务书有未提交修改，保持原样；未合并 PR、切换分支、提交、推送或发布。在当前 K002 后继工作区先完成可审阅增量；任务书 §11.1 的主线合入步骤尚未执行。
- 最新批次 M36：状态目录健康绑定、配置初始化与稳定本地实例 ID 已实现并通过隔离 Linux arm64 实测；团队设备身份、安装包和三系统用户级后台仍待完成，UX-003 不标完成。

### 历史落盘基线（2026-09-13，M116 时点）

- main 已合入 PR #28，合并提交 69d9c59，包含截至 M47 的验证增量。
- M48–M67 已提交为 5ceea0a、274ed97，已推送 PR #31 并快进合入本地 main；36 项远端 CI 通过、2 项跳过。远端 main 仍在 69d9c59，PR 需要代码所有者批准，管理员合并授权问题尚待回复。
- 当前后继分支 codex/personal-macos-stop-recovery，基于 274ed97；M68–M116 为本地未提交增量，不加入等待合并的 PR #31。
- Linux 生命周期已具备升级/恢复/回退、快照恢复、setup/ui/自启/teardown；其原生证据仅隔离 Linux arm64，正式发行安装与真实重新登录仍未闭环。
- macOS 已实现 plist/签名准备、注册、加载/启动、停止/注销与 setup/teardown 编排，已通过模拟测试，实机证据仍缺。Windows 已实现任务 XML、签名准备与只读系统查询入口；仅模拟与交叉编译验证，定点存在性查询已实现但脚本/COM 原生执行未验证，排他注册已实现并通过模拟编排，按需启动与目录健康已实现并模拟验证；正常退出和注销编排已通过模拟测试，setup/teardown 编排已实现，全部 Windows 原生验收仍待完成。

## 任务状态

`doing` 仅表示正在实施；没有真实平台证据时不得提升为完整验收。

| 任务 | 状态 | 当前结果/下一步 |
| --- | --- | --- |
| UX-000 | complete | [需求验收映射与基线](personal-experience-requirements-baseline-20260910.md)覆盖 D01–D11、实施位置、证据、未知项和阶段边界；具体功能状态继续逐任务跟踪 |
| UX-001 | doing / native subset verified | Linux arm64：M124 Hermes 原生完整会话已有证据；OpenClaw 安装配置修复后公共 CLI 会话 17 项检查通过。真实用户审批、Windows/macOS 与 WorkBuddy 桌面仍待验收 |
| UX-002 | doing | ADR-019–047 覆盖会话、发现、诊断、接入变更、Hermes 实例、自检、资源编辑和固定授权选择；安装预览/提交/恢复合同已接通；可信 Skill 运行归属仍需完成 |
| UX-003 | doing / Linux native subset verified | Linux 初始化、后台注册/控制、setup、ui、自启链接管理和 teardown 已实现，隔离 runtime 全链复用/恢复通过；macOS 注册/启停/注销及 setup 编排已落盘，实机、Windows 后台及正式安装器仍待完成 |
| UX-004 | implemented / Linux verified | 会话恢复、注销、到期重新配对、CLI 配对恢复及错误分类已落盘；Linux Chromium 11 项检查通过，跨 OS 运行验证归 UX-015 |
| UX-005 | doing / core implemented | 显式扫描、范围预览、手动目录、稳定安装身份和共享关系已实现；Hermes 自定义根与 profile 使用同一实例解析器。同名实例隔离通过；其他平台根、过滤优先级、全量覆盖与跨 OS 实机仍待验证 |
| UX-006 | doing / Hermes runtime check implemented | 接入预览、确认、恢复、卸载、Hermes 实例选择/原生启用及产品运行自检已落盘；Linux 独立 profile 的 UI/API/真实 CLI 通过。其他平台自检、自动重启和跨 OS 恢复仍待完成 |
| UX-007 | doing / managed instance integration verified | Hermes/OpenClaw 托管会话已在隔离 Linux arm64 验证。M128 已具备 Skill 元数据与门禁框架，但精确匹配仍为 unknown，可信执行来源绑定未完成；强制开关默认关闭。场景模板及其他窗口后继工作另行验收 |
| UX-008 | doing / Linux dual-host retry and notification transport verified | 统一待办、单次处理、长期授权定位和浏览器通知已落盘；签名执行预留、uncertain 人工结案、Linux/Hermes/OpenClaw 原生恢复及 GNOME session-bus 通知传输通过。Linux 视觉确认、Windows/macOS 通知、WorkBuddy 与跨系统仍待完成 |
| UX-009 | doing / Hermes installation UI verified in isolated profile | 本地目录/ZIP、HTTPS ZIP、固定副本审阅、来源绑定批准、安装预览、明确安装确认与失败恢复已接通；隔离 Linux Chromium 和目标文件操作验证通过。安装后实例权限准备、原生清单识别与实例范围的 CLI 保护已验证；Git 来源、浏览器文件选择、平台安装入口拦截、可信 Skill 归属与其他平台仍待完成 |
| UX-010 | doing / update UI verified in isolated Linux browser | 记录、内容检查、移除与恢复 UI/API 已验证；更新比较、独立副本准备、明确切换和中断恢复核心/API 已实现。差异/确认/恢复 UI 已在隔离 Linux 浏览器验证；新版检查、原生更新验收与通用旧状态写入拒绝仍待完成 |
| UX-011 | doing / local trace flow implemented | 已实现任务活动列表/详情/检索、结果证据与历史 Skill 来源查看，以及回执摘要和完整脱敏追溯包的 API/UI 下载流程；真实平台样例、保留期联动和最终验收待完成 |
| UX-012 | doing / raw-content status integrated | 本地顶栏已持续区分原文仓关闭、按任务授权启用、异常与不可用，并在焦点/设置变更时刷新；其余页面状态、安装与故障恢复整合继续推进 |
| UX-013 | doing / Hermes and OpenClaw native subset verified | 独立加密原文仓、显式任务授权、撤销、管理读取、默认导出隔离与清理已实现；Hermes/OpenClaw 原生参数和结果采集已有 Linux arm64 证据，输出关联已限制为单次消费。WorkBuddy 与跨系统验收仍待完成 |
| UX-014 | doing / Linux core implemented | 发行 v2 兼容验证、稳定路径暂存、升级/回退/快照恢复、清单复用与 client-install 已实现；正式发行安装成功路径、不同版本与跨 OS 制品验收仍待完成 |
| UX-015 | todo | 真实组合综合验收 |
| LAN-001–006 | todo | 个人阶段完成后推进，未创建额外团队服务 |

### 进度口径（2026-09-11，落盘记录更新至 M34）

按 M33 落盘范围与 M34 当前实现重新粗估：个人阶段约 45%–55%，包含团队增量的整体约 30%–40%。这是剩余工程范围的主观区间估计，未建立逐任务工时权重，不是正式验收比例或测试通过率。M34 更新页面及合同客户端已实现，47 项 Web 测试、个人/企业构建通过；首轮浏览器旅程的候选选择标签问题已修复，隔离 Linux Chromium 的 7 项更新流程检查重跑通过。M34 最终构建与证据已核验，不能据此提升跨 OS/平台验收状态。局域网团队增量尚未开始。

任务书含 16 个个人任务和 6 个团队任务；完整标为 complete 的只有 UX-000，UX-004 已实现并通过 Linux 验证。其他任务的部分实现与实测不折算为整个任务完成。下文 M1–M34 是落盘批次编号，不表示任务书同名阶段里程碑已经通过。

## 已确认的 M1 实现选择

1. 继续使用 Go 标准库及现有嵌入式前端，不为会话恢复引入数据库或桌面框架。
2. 管理 access token 仍只在浏览器内存；恢复凭据只在 HttpOnly、SameSite=Strict、限定路径的 Cookie 中。不会把 Cookie 直接作为通用管理 API 凭据。
3. Cookie 恢复接口要求专用请求头并保持 Host/Origin 校验；令牌不进入 URL、localStorage、通知或日志。
4. daemon 重启使旧内存会话失效。通过独立本机恢复凭据重新生成短期配对码；该凭据不能调用决策或通用管理端点，不能提供给适配器。
5. 新增只读身份/健康响应，区分不可达、错误服务、兼容性错误与正常运行。产品标识只是协议识别，不能证明恶意同 UID 进程无法伪装。
6. 保留 legacy `POST /v1/pair` 返回 bearer 的方式供已有客户端；新 UI 显式申请浏览器恢复能力。

## 验证与证据

- 初始环境探测保存至 `evidence/personal-experience/environment-20260910.json`，仅系统、工具可用性、版本及能力状态，不含配置正文、token、私钥和用户数据。
- M1 会话浏览器证据：[结果](evidence/personal-experience/session-browser-20260910/result.json)、[已连接页面](evidence/personal-experience/session-browser-20260910/connected.png)、[重试入口](evidence/personal-experience/session-browser-20260910/connection-retry.png)、[移动端配对](evidence/personal-experience/session-browser-20260910/pairing-mobile.png)。独立临时状态目录与真实 Chromium，11 项检查通过；不作为智能体平台集成证据。
- Go：`go vet ./...`、`go test ./...` 通过；会话、状态、CLI 包 `-race` 通过。新增测试覆盖 Cookie 作用域、固定时限、注销重放、重启、跨站/错误 Origin、凭据分权、审计失败不换码、健康协议与重定向拒绝。
- Web：20 项 Vitest 检查通过，`npm run build` 和 `npm run build:local` 通过；恢复凭据不进入 Web Storage，开发代理只改写与当前开发服务完全匹配的 Origin。
- 合同：Go 响应与 5 个固定脱敏样例一致，由 Control API 的 JSON Schema 测试校验；共 81 项合同回归通过，相关 Python lint 通过。
- 构建：linux/amd64、linux/arm64、darwin/arm64、windows/amd64 交叉构建通过；[制品哈希](evidence/personal-experience/cross-builds-20260910.json)已登记。开发制品在忽略目录 `.tmp/personal-experience/`，不是正式签名安装包。
- 启动入口：新增 `scripts/personal-experience/start-local.py`；4 项生命周期回归通过。[Linux 启动证据](evidence/personal-experience/launcher-20260910.json)记录真实二进制启动、重复复用和后台存活；端口拒绝案例明确标为测试探测桩，不冒充跨平台实测。

## 下一批实施顺序

1. 补齐 Vite 与新服务的完整联合会话验证、非默认端口的提示；把开发启动入口整合进新版本安装交付设计。
2. UX-005：Hermes 自定义根已接通发现与接入，继续补充其他平台根、扫描覆盖边界与真实平台配置兼容；不把配置关联当作运行归属。
3. UX-006、UX-007：Hermes 原生启用、profile 定位、自检和统一权限编辑已实现；继续其他平台接入验证与实例/Skill 的可信权限归属。WorkBuddy 保持独立验证项。
4. 后续按任务书完成审批、安装更新、追溯、隐私与跨系统打包。个人阶段未达到验收条件前，不启用团队服务。

## M2：首次发现与安装身份

- 规格：[ADR-020](adr/0020-personal-discovery-and-skill-identity.md)，`local-discovery.v1` 合同及 Go/Python 共用样例。
- 接口：管理会话访问 `GET /v1/discovery`、`POST /v1/discovery/preview`、`POST /v1/discovery/scan`。扫描为后台任务，显式重新构建投影；预览不保存目录，开始扫描后将新增范围写入 `discovery-roots/scope.<revision>.json`，重复范围不新增版本。
- 身份：Skill 安装 ID 使用目录定位摘要，内容哈希独立。旧台账 locator/ID 映射到新安装；相同内容保留原批准，实际内容变化继续触发复核/撤权。
- 关系：Hermes profile、OpenClaw 明确 workspace 与共享目录的关联保留为 inferred；详情展示关联名称与来源，不显示为实际调用或已生效权限。
- 安全：不执行发现内容；配置限 1 MiB；拒绝符号链接和特殊文件；扫描目录/深度有上限；部分失败明确提示。手动范围最多 16 个，独立于权限配置保存。
- [浏览器结果](evidence/personal-experience/discovery-browser-20260910/result.json)使用独立测试配置与真实 Chromium，覆盖重复/同名安装、共享消费者、更新后身份稳定、扫描刷新缓存、手动范围跨重启恢复、会话恢复和移动端导航。附 [桌面](evidence/personal-experience/discovery-browser-20260910/discovery.png) 与 [移动端](evidence/personal-experience/discovery-browser-20260910/discovery-mobile.png)；不是平台运行时验收。
- [当前主机只读证据](evidence/personal-experience/native-discovery-20260910.json)：794 个 Skill 安装、12 个 Hermes profile、9 个 OpenClaw 实例、1,330 条配置关联；ID 无重复，所检查配置文件未变化。100 处符号链接按规则跳过；只发布计数与类别，不发布用户资产名、路径和配置正文。
- 待补：扫描任务取消/超时管理、自定义环境根、用户移除扫描范围时的历史资产语义；当前版本只支持新增手动范围。WorkBuddy 仍独立列为待实测，不能从 `.codebuddy` 发现结果推定支持。
- 当前 Windows/macOS 原生测试与 WorkBuddy GUI 不可由 Linux 交叉构建代替。

### M2 验证记录（2026-09-10，Asia/Shanghai）

- Go `go vet ./...`、`go test ./...` 通过；`go test -race ./internal/inventory ./internal/ledger ./internal/server ./internal/state` 通过。最后增加扫描范围文件损坏、陈旧写入与 16 项组合上限回归后，重新通过 state/server 测试和 state 的 vet、race；修改文件 gofmt 无输出。
- 新范围文件读取不把 `null` 或损坏内容解释成空范围；不可变历史保留，陈旧 revision 更新失败。合同与实现均校验项目和 Skill 目录合计上限，不按各自 16 项放宽为 32 项。
- Web 20 项 Vitest、`npm run build:local`、`npm run build` 通过；嵌入式前端已重建。Go/Python 共用发现样例与状态合同由 `uv run pytest app/tests/test_schema_contracts.py -q` 验证，共 83 项通过，相关 `ruff check` 通过。
- 最终浏览器回归 19 项通过，移动端标题、菜单与退出操作可见，扫描范围长路径不造成页面横向溢出。本阶段四目标构建全部通过，独立记录 [M2 制品哈希](evidence/personal-experience/cross-builds-discovery-20260910.json)。Linux 浏览器证据绑定对应开发二进制哈希；历史 M1 证据保留原哈希。
- `git diff --check`、证据 JSON 解析、增量文档本地链接检查通过。
- 开发内容保留在当前工作区，未创建提交、分支、推送或发布。

## 接入诊断增量（UX-006，任务仍在进行）

- [ADR-021](adr/0021-adapter-configuration-diagnosis.md) 与 `local-adapter-diagnostics.v1` 定义只读配置诊断。新增管理接口 `GET /v1/adapter/diagnostics`；平台列表附 diagnosis。CLI 的 installed 保留文件存在语义，HTTP 不再根据该标记自动显示 L2。
- 设置与运行绑定页区分文件、宿主登记、连接配置和运行验证；OpenClaw 禁用、缺少登记、服务连接不匹配或文件变化会显示需处理。Hermes 原生启用仍需在对应 profile 执行，诊断不使用不完整 YAML 解析来冒充已加载。
- WorkBuddy 单独显示桌面接入待实测；没有借用 CodeBuddy 的安装操作。诊断限制文件大小，拒绝符号链接和特殊文件，不执行插件、不读取凭据正文、不写平台配置。
- [Hermes 原生证据](evidence/personal-experience/hermes-native-20260910.json) 和 [OpenClaw 原生证据](evidence/personal-experience/openclaw-native-20260910.json)各 14 项通过，均使用真实本机平台代码、临时配置、合成操作者。正常读取、执行前拒绝、失联、重启和回执链均覆盖；不代表当前用户会话或完整平台审批已验证。
- 最终浏览器回归 22 项通过，[浏览器证据](evidence/personal-experience/adapter-diagnostics-browser-20260910/result.json)及[诊断截图](evidence/personal-experience/adapter-diagnostics-browser-20260910/adapter-diagnostics.png)保存在独立目录，保留此前发现流程证据。
- `go vet ./...`、`go test ./...`、adapterinstall/server 的 `-race` 通过；Web 20 项 Vitest、类型检查、个人/企业构建通过；Go 输出固定合同样例，Python 合同共 84 项通过且 lint 通过。
- 四目标交叉构建全部通过，结果见[本批制品记录](evidence/personal-experience/cross-builds-adapter-diagnostics-20260910.json)。原生调用证据的二进制各有独立哈希，Hermes 验证与最终 UI 文案更新不同批次；不把交叉构建视为实机通过。
- 此批之后的变更预览与恢复进展见下节；Hermes 原生启用、跨实例与历史版本卸载兼容、每个实例可失效的运行自检记录仍待完成。当前诊断 runtime_state 固定 unverified。

## 接入变更与恢复增量（M4，UX-006 仍在进行）

- [ADR-022](adr/0022-adapter-change-plan-and-recovery.md) 与 `local-adapter-plan.v1` 定义安装/卸载的文件变更预览。`POST /v1/adapter/preview` 只读生成计划；既有 install/uninstall 要求同管理会话的计划 ID 和摘要，校验 5 分钟时限、动作、平台、服务模式、程序内容、安装版本和全部读取文件。
- 设置和运行绑定页共用变更对话框：查看涉及文件与用途、校验摘要、取消、确认应用；冲突时重新预览，提供显式恢复入口。取消不改平台配置，安装完成仍提示验证实际调用。
- 安装/卸载 CLI 与 HTTP 复用规划/应用引擎，删除旧的直接写文件实现。新增 `adapter preview <platform> [install|uninstall]` 与 `adapter recover <platform>`；CLI 预览也不初始化状态目录。
- 事务材料在本机 AES-GCM 加密保存，独立密钥 0600；不可变版本归属记录与进程写锁协调 CLI/daemon 操作。全部预检查、逐文件比对、最终读取验证、开始/完成审计及终态顺序共同约束成功结果。
- 中断后仅恢复本操作写入且仍匹配预期的文件；外部修改保留并阻止下一次接入，用户可在检查冲突后显式恢复。卸载只处理具体归属文件与本产品配置字段，保留未知文件、用户新增设置与原有插件配置，并恢复 POSIX 包装器权限。
- Hermes 包装器修正 shell 路径引用和状态目录传递；含引号、空格、`$()`、反引号的路径均按字面处理。准入未成功则不调用平台安装入口。
- 已通过：Go 全量测试、vet、adapterinstall/server 的 race；故障测试覆盖进程真实退出、文件写入中断、审计失败、陈旧预览、重复提交、密文损坏、活跃写锁、用户并发修改。OpenClaw 原生加载器对新安装流程产物的独立测试通过，不代表完整会话和审批验收。
- 最终浏览器 27 项通过，覆盖取消、陈旧计划、重新预览、安装/卸载确认、键盘摘要、移动端布局、保留用户文件及既有会话/发现流程：[结果](evidence/personal-experience/adapter-change-browser-20260910/result.json)、[桌面预览](evidence/personal-experience/adapter-change-browser-20260910/adapter-preview.png)、[移动端预览](evidence/personal-experience/adapter-change-browser-20260910/adapter-preview-mobile.png)。
- [验证记录与源码摘要](evidence/personal-experience/adapter-change-20260910/verification.json)及同目录 Go 日志保存本批检查范围。Web 20 项 Vitest、类型检查、个人/企业构建，85 项 Python 合同与相关 lint 通过。四目标构建通过：[制品哈希](evidence/personal-experience/cross-builds-adapter-change-20260910.json)。此前 M1–M3 证据保持独立。
- 范围限制：Windows/macOS 尚未实机验证本批文件操作与恢复；当前通用进程锁无法在 Windows 证明旧进程已退出，因此不会擅自清除该锁。旧安装记录缺少文件摘要、旧原始快照与当前配置不一致时保留现场并要求处理；后续需要完善迁移体验。原生启用、自动重启与运行权限验证不由配置事务代替。

## Hermes 实例与原生启用增量（M5，UX-005/006/012）

- [ADR-023](adr/0023-hermes-instance-integration.md)、`local-adapter-instances.v1`、`local-adapter-plan.v2` 与 Go/Python 共用样例已落盘。v2 明确实例和原生启用选择；既有 v1 预览保持兼容。管理 API 不接受客户端任意配置目录；目标 ID 必须来自当前目录解析，应用时再次解析并匹配预览。
- 新 `internal/hermeshome` 统一盘点与安装的默认目录、`HERMES_HOME` 和命名 profile 定位；Windows 原生根与旧目录分别枚举。目录 ID 与内容分离，旧默认/命名台账 ID 保持兼容，同名自定义根独立。拒绝相对/不安全活动根、符号链接、特殊文件与非法编码路径，每个根有 64 项列举预算。跨 OS 路径策略单测不代替实机验证。
- Hermes “管理实例”提供 profile 选择、安装/卸载操作、配置状态、诊断与原生启用选项。实例列表初次读取失败可以原地重试；切换选项会清除旧计划，确认绑定当前目标。配置诊断仍区分 ready 与 runtime unverified。
- 原生启用仅在隔离的临时 HOME/HERMES_HOME 处理副本，通过已安装 Hermes 的公开 `config` / `plugins enable` CLI 解析、修改和读回。不导入被扫描 Skill，不传宿主凭据环境；禁用项目插件，不授予内置工具覆盖权限。输入、输出和每条命令执行有预算，别名/显式标签/不可兼容 YAML 保守拒绝。其他配置语义变化拒绝进入计划，确认后才由文件事务落盘。
- 归属与恢复按实例分开；读取已提交归属也验证加密日志。卸载恢复原有 SIQ 启用/禁用状态与 override 设置，保留其他插件和用户后来新增的设置。默认实例从旧版全局包装器迁移后，卸载仍能恢复原脚本及权限；命名 profile 不处理全局包装器。
- [浏览器结果](evidence/personal-experience/hermes-instance-browser-20260910/result.json) 30 项通过，覆盖列表重试、选择实例、原生预览/确认、只修改目标 profile、卸载保留后续设置及原有会话/发现/移动端检查。附 [原生接入预览](evidence/personal-experience/hermes-instance-browser-20260910/hermes-native-preview.png)、[实例诊断](evidence/personal-experience/hermes-instance-browser-20260910/hermes-instance-diagnosis.png)。
- [Hermes 原生集成](evidence/personal-experience/hermes-instance-native-20260910.json)使用新实例 API 安装和原生启用的实际产物，经本机已安装的加载器与工具分发器完成 15 项检查，92 条签名回执复验通过；覆盖允许、越权、离线拒绝及重启。原生 CLI 正负向另覆盖新配置、非法 YAML/插件列表、预览不写宿主和精确卸载。合成操作者与调用，不是当前用户会话自检。
- [跨版本升级](evidence/personal-experience/hermes-instance-upgrade-20260910.json)使用真实 M4、M5 Linux arm64 二进制完成 5 项检查：旧加密记录读取、默认实例升级、保留另一 profile、原包装器内容/权限恢复及独立卸载。可用 `scripts/personal-experience/adapter-upgrade-smoke.py` 重复验证。
- [OpenClaw 回归](evidence/personal-experience/openclaw-instance-regression-20260910.json) 14 项、92 条回执通过，确认共享原生验证工具保持旧调用方式兼容。原 M1–M4 证据保持原样。
- Go 全量、vet、发现/实例/安装/服务 race、20 项 Vitest、个人与企业前端构建、86 项 Python 合同及相关 lint 通过。[本批验证日志与源码摘要](evidence/personal-experience/hermes-instance-20260910/verification.json)、[四目标构建摘要](evidence/personal-experience/cross-builds-hermes-instance-20260910.json)独立保存；制品仍是未签名开发构建。
- 剩余边界：每个真实用户实例的可失效运行自检尚未实现，当前诊断固定 runtime_state=unverified；尚未自动重启宿主或建立可信 Skill 调用归属。Hermes 原生配置兼容性只对当前安装版本验证，CLI 入口摘要不能代表完整 Python 依赖身份。Windows/macOS、WorkBuddy、跨 OS 崩溃锁恢复、特殊 YAML 和其他平台根仍需继续处理。

## M6：授权期限与公开 CLI 会话验证

- [ADR-024](adr/0024-native-runtime-check.md)细化自动运行自检的临时 Grant/Intent、真实会话绑定、清理与证据失效边界。当前已完成授权期限前置和公开 CLI 可行性验证，用户实例的一键自检控制器、接口和界面仍待实现。
- 新增 `grant-expiry-edit/v1` 合同、`POST /v1/grants/{id}/expiry` 与签发页期限编辑。仅 pending_approval 可按服务器时间修改；精确 revision 防止旧页面覆盖，变更重新绑定批准挑战。批准、部署、effective 转换、决策与 hold 执行前查询均检查期限；不直接延长已批准 Grant，不产生 effective。
- 签名 Grant 仍保留旧 null 无期限兼容；到期采用半开区间，非法期限不当作无限期。到期后新决策拒绝，等待中的已批准操作不能继续；原回执与已发生结果仍可追溯。普通 policy 在 warn/audit_only 下保留 advisory 语义，自动自检仍必须另有短期 Intent Authority。
- [期限浏览器结果](evidence/personal-experience/grant-expiry-browser-20260910/result.json)覆盖服务器期限、取消期限、并发冲突、人工批准、禁止延期、部署状态与移动端；截图见同目录。不是智能体平台验收。长授权编号与主体名称在小屏自动换行，内容区裁切有独立检查。
- [Hermes 公开 CLI 原生会话结果](evidence/personal-experience/hermes-cli-runtime-expiry-20260910.json)：合成操作者、隔离 profile、loopback 模型；真实 `hermes chat --oneshot` 会话通过 6 项检查，5 条回执验签/链验证通过。测试观察插件取得宿主生成的 session_id；没有通过内部 registry 直接执行来替代生命周期钩子。配置摘要保持一致；不保证宿主没有写缓存/历史，不声称网络隔离。
- 验证：Go 全量、vet、grant/receipt/server 的 race、state/receipt 补充 race；20 项 Vitest、个人/企业构建、87 项 Python 合同及相关 lint 通过。四目标开发构建摘要与验证记录见 [M6 记录](evidence/personal-experience/grant-lifetime-20260910/verification.json)。安全测试覆盖到期精确边界、旧 challenge、非法期限、决策凭据越权、审计失败、历史观测兼容和不得回退旧 Grant。
- 本批没有完成 UX-006、UX-007，也没有推进团队服务。下一步实现当前目标实例的短期授权、自检会话绑定、取消/清理、漂移失效和可审阅状态；再推进完整权限编辑与统一批准。

## M7：Hermes 产品运行自检（UX-006 仍在进行）

- 设置和运行绑定页新增“运行自检”。用户选择已接入的实例、检查影响并确认后，服务才启动该实例真实配置下的新 Hermes 公开 CLI 会话。页面预览和轮询不启动进程，不创建授权；关闭窗口后任务继续，重新打开能恢复最近状态，取消另有明确按钮。
- 固定测试范围为 120 秒、独立身份和 SIQ 生成的两份只读文件。通过原有 Grant 人工批准状态机及 Intent/绑定签发临时权限，实际调用仍经普通决策引擎；真实 pre_tool_call 用独立启动凭据绑定宿主 session，管理凭据不交给宿主或模型。缺失、过期、重放或会话替换均拒绝。
- 完整链路为正常读取、执行前拒绝写入、再次读取；必须核对结果内容、拒绝目标不存在、两组 decision/observation 关联、临时 Grant/Intent 身份及完整回执签名链。宿主退出成功或模型声称成功都不能单独使自检通过。测试结果按这五项证据顺序展示。
- 结束、取消和失败均撤权并清理材料；审计失败不启动或不报告通过。清理失败阻止新检查并提供重试入口；重启恢复不会继续旧任务，按原 Intent 找回已发布但尚未记入自检日志的绑定并撤销。重启恢复与故障窗口目前为存储/控制器单测证据，未冒充多 OS 进程崩溃实测。
- 结果绑定配置、适配器、CLI 入口、SIQ 程序及服务身份；后续漂移使旧结果失效，恢复旧配置也不会自动恢复通过。配置未完成接入核对时，不允许重新启动检查。摘要不覆盖完整 Python 环境，不证明恶意同 UID 隔离、可信 Skill 归属或已有会话永远受保护。
- [产品原生 API 结果](evidence/personal-experience/runtime-check-native-20260910.json)：6 项检查、5 条关联回执，通过真实公开 Hermes CLI，使用独立测试 profile 和合成操作者。[浏览器结果](evidence/personal-experience/runtime-check-browser-20260910/result.json)：13 项通过，包括明确确认、关闭后恢复、无重复启动、配置漂移、取消撤权、移动端操作可达和键盘焦点。附 [通过页](evidence/personal-experience/runtime-check-browser-20260910/runtime-check-passed.png) 与 [移动端操作](evidence/personal-experience/runtime-check-browser-20260910/runtime-check-mobile-actions.png)。未操作用户日常 profile。
- 新 `local-runtime-check.v1` 合同及 5 份 Go 输出样例由 Python 共同验证；共 93 项合同回归通过。Go 全量测试/vet、runtimecheck/server/adapterinstall 竞态检查通过，含接口凭据分权、人工确认、跨会话、重复启动、严格 JSON、审计失败、证据篡改、孤立绑定恢复、清理重试负向。真实 CLI 安装目标核验另验证默认 HOME 与配置/程序变化。
- Hermes 适配器 74 项测试通过；Web 20 项测试、个人/企业构建通过；四目标交叉构建通过。完整命令、源码摘要、制品和证据关联见 [本批验证记录](evidence/personal-experience/runtime-check-20260910/verification.json)。M1–M6 历史记录保留原身份。
- [既有 Hermes 原生回归](evidence/personal-experience/hermes-runtime-check-regression-20260910.json) 15 项、412 条回执通过，覆盖普通会话、越权、离线、重启、并发重放及 optional 兼容。该脚本自行构建的二进制具有独立哈希；其宿主加载器夹具回归与上方产品公开 CLI 自检证据分别记录。
- 本批完成的是 Hermes 的产品自检增量。OpenClaw/WorkBuddy 同等自检、宿主后台生命周期、Windows/macOS 实机、完整权限编辑及后续个人任务仍未完成；整体进度继续采用上文保守估算，不将落盘批次 M7 当成任务书里程碑完成。

## M8：权限资源边界（UX-007 仍在进行）

- [ADR-025](adr/0025-explicit-grant-resource-boundaries.md) 明确权限编辑前的执行前提。修正文件检查：读取也须有明确范围；只读不授予写入/删除，读写范围包含读取；规范化路径匹配目录边界，多个目标逐个校验，未知/缺失目标拒绝。凭据路径限制先于通用目录 allow，文件 deny 优先。
- 网络检查按结构化请求的真实主机和端口，不再只匹配域名而忽略端口；支持明确子域模式和 IPv6 端点。deny 优先；缺失目标、不支持的模式、非法端口及不能执行的 deny 约束失败关闭，不能从请求正文里的 URL 补充权限。
- 脱敏替换参数重新经过 Grant 检查；只有完整 policy 为 allow 且授权身份一致时才生成可执行替换，不再因检测到 secret 而绕过资源或人批要求。普通 warn/audit_only 保持拒绝建议；无效必需 Authority 仍在所有模式拒绝。
- [旧行为复现](evidence/personal-experience/grant-resource-old-bypass-20260910.json)：同一隔离夹具中，M7 二进制在只读 Grant 与允许写入的 Intent 下产生写入。这是旧问题复现成功，**不是保护验收通过**。[修复后原生证据](evidence/personal-experience/grant-resource-native-20260910.json) 7 项通过：正常公开 Hermes CLI、宿主真实 session、读取/拒绝写入/再次读取、链验签，以及拒绝确实来自 Grant 而非 Intent。测试只使用生成的目录和合成操作者。
- [Hermes 产品自检回归](evidence/personal-experience/runtime-check-resource-regression-20260910.json) 6 项通过；普通 [Hermes](evidence/personal-experience/hermes-resource-regression-20260910.json) 和 [OpenClaw](evidence/personal-experience/openclaw-resource-regression-20260910.json) 原生夹具回归分别保留真实结果及独立构建哈希。没有重写旧批次证据来冒充本次验证。
- Go 全量、vet、receipt/runtimecheck/server 竞态检查及四目标构建通过；93 项 Python 合同回归、增量脚本 lint 通过。[本批源码摘要、命令和制品记录](evidence/personal-experience/grant-resource-boundaries-20260910/verification.json)已落盘。没有前端源代码改动，沿用 M7 嵌入式前端；后续权限编辑界面仍需单独验收。
- 兼容影响：缺少文件范围的旧工具授权不再默认允许任意读取，需要重新起草明确范围；旧签名文件不自动改写或扩权。Windows/macOS 实机、通用符号链接防绕过、OS 隔离、可信 Skill 归属均未因此完成。下一步是完整权限编辑与可信绑定，不将本批安全修正折算成 UX-007 整项完成。

## M9：统一权限编辑（UX-007/012 增量，Linux 已验证）

- [ADR-026](adr/0026-personal-permission-editor.md) 和 `grant-resource-edit/v1` 先定义完整替换语义，再接入既有 Grant 签名、精确版本比对和审计提交。资产详情与签发页复用同一个编辑窗口，显示当前工具、只读/读写目录、网络允许/拒绝和模型声明；保存仍需人工批准，不产生 effective。
- 空列表明确清空，不再用空输入表示不修改；目录逐行处理，保留内部空格和逗号。保留文件/模型 deny、凭据/进程保护及仍授予工具的人批条件；被拒绝工具不能经另一条 allow 或 hold 再执行；旧 OpenClaw 仅存于平台策略中的拒绝和人批条件也会保留。提供“目录全部改为只读”和“清空允许范围”，均只改草稿。
- 冲突保留输入，显式重新读取才替换；读取失败禁用保存。浏览器实测发现并修复修改人清空后被默认值拼接的问题；修改人先在编辑窗口独立保存，提交成功后更新会话。长表单独立滚动，标题和操作区保持可见。
- 新增 Go 测试覆盖 32/33 项边界、缺省/null/未知字段、64 KiB 请求上限、身份与期限保持、签名、旧 challenge 失效、拒绝优先、原人批条件、审计失败不发布，以及编辑→批准→部署→正常/越权决策链路。最终前端重建后，Go 全量、vet、grant/receipt/server race 通过。94 项 Python 合同检查、相关 lint、20 项 Web 测试和个人/企业构建通过，四目标交叉构建通过。
- [浏览器结果](evidence/personal-experience/permission-editor-20260910/browser/result.json) 14 项通过，覆盖预填、修改人输入焦点、条件可见、取消、只读转换、冲突保留、显式重读、重读失败、清空、已批准禁改和移动端按钮。已查看 [桌面](evidence/personal-experience/permission-editor-20260910/browser/grant-resources.png) 与 [移动端](evidence/personal-experience/permission-editor-20260910/browser/grant-resources-mobile.png)。该浏览器旅程从签发页进入；资产详情入口共用组件并通过构建，未单独声称整条资产旅程验收。
- 最终 Linux 候选二进制的 [Hermes 只读 Grant 回归](evidence/personal-experience/permission-editor-20260910/grant-resource-native.json) 7 项和 [产品运行自检](evidence/personal-experience/permission-editor-20260910/runtime-check-native.json) 6 项通过；[OpenClaw 原生回归](evidence/personal-experience/permission-editor-20260910/openclaw-native.json) 14 项通过，使用独立构建并保留其原哈希。[源码、命令与制品对应记录](evidence/personal-experience/permission-editor-20260910/verification.json)统一引用本批证据。
- 尚未完成：可信实例/Skill 运行绑定、同 Skill 跨智能体独立权限的完整旅程、Windows/macOS 原生权限路径与实机验证、WorkBuddy 运行接入；模型/进程声明不等于宿主已执行限制。下一批继续 UX-007 的可信绑定，不将权限编辑完成折算为整项验收。

## M10：会话固定授权选择（UX-007 后端与自检增量）

- [ADR-027](adr/0027-session-grant-selection.md)、`intent-grant-bind/v1` 请求与 `intent-grant-binding.v1` 输出合同已落盘。管理端按精确 Grant 版本建立既有 Intent Binding，绑定记录增加签名 grant_ref；旧记录没有新字段时保持原签名与接口兼容。缺省与显式 null 选择字段分开处理，不能把无效新请求解释成旧绑定。
- 每次解析绑定重新读取并验证所选 Grant 的签名、主体、已部署状态、期限和权限摘要。所选 Grant 失效时所有模式拒绝，不能借用另一份较新/较宽权限或回退旧授权。正常后端读回的证据属性变化不改变权限摘要；工具可执行状态、资源、条件、主体、准入、期限、批准和策略版本变化会改变摘要。
- 既有 Grant∩Intent 决策、脱敏和 hold 状态查询都使用该选择。人工批准前重查绑定；已批准调用在授权撤销后不再返回可执行状态。测试证明两个会话可选择同智能体的不同授权，同一准入版本在两个智能体可使用不同范围，伪造 params.skill_id 不改变选择。
- Hermes 产品自检通过现有独立启动凭据取得真实 session 后，自动固定到本次临时 Grant；用户无需手填会话标识。[真实 CLI 自检](evidence/personal-experience/session-grant-selection-20260910/selection-native.json) 7 项通过，并确认签名绑定所选 Grant/准入与本次控制器一致，清理后授权已撤销。该自检仍只有合成任务与隔离 profile，不等于日常全部 Skill 已接入。
- [旧 Hermes 调用回归](evidence/personal-experience/session-grant-selection-20260910/legacy-hermes-native.json) 7 项通过；[OpenClaw 原生回归](evidence/personal-experience/session-grant-selection-20260910/openclaw-native.json) 14 项通过，后者保留独立构建哈希。旧签名绑定向量、权限摘要、重放/降级、读取失败、错误主体、重启、readback 稳定性、精确版本和批准后撤销均有 Go 回归。
- Go 全量、vet、grant/intent/receipt/server/runtimecheck/state 的 race、96 项 Python 合同、增量 Python lint、四目标构建通过。[本批代码/日志/候选证据记录](evidence/personal-experience/session-grant-selection-20260910/verification.json)已落盘。Go 输出样例只规范化签发时钟及其签名，实际返回记录另验签；未修改旧历史签名样例。本批无 Web 源码变化，沿用 M9 前端，不重复声称新的普通任务浏览器旅程通过。
- 未完成：普通用户任务自动选择与绑定、平台实例独立可信凭据、宿主实际加载的 Skill 版本与内容变化检测、多 Skill 归属以及跨 OS/WorkBuddy 验证。旧无选择绑定仍走原隐式 Grant 查找，未整体迁移前不能声称旧路径的回退风险已消除。下一批继续普通任务接入与可信加载归属，UX-007 保持 doing。

## M11：实例凭据与自动会话核心（UX-007 增量，尚未接通产品入口）

- [ADR-028](adr/0028-personal-runtime-identities.md) 的身份发行/撤销合同与核心包 `internal/runtimeidentity` 已实现；接口路由、适配器消费和前端启用仍未接通。不能把本批核心完成解释为日常任务已自动保护。
- 发行仅接受解析器确认的实例及精确版本的已部署、已验签 Grant。每个实例只允许一个未撤销身份，独立随机凭据仅保存于本机 0600 文件；签名发行记录保存哈希，签名撤销追加。中断后只有秘密文件而没有完整发行记录时不能认证。全部元数据读取有大小/数量预算，并拒绝软链接、损坏、重复键、字段别名及不安全权限。
- 自动会话核心从身份与原生 session 派生独立 Intent/task，固定到已确认的 Grant 摘要；身份、授权或绑定失效时拒绝，重试不延长期限。中断恢复只接受完全匹配且仍有效的原权限包络；新身份不能接管旧会话。包络明确表示实例权限，不保存任务提示词，也不声称掌握真实 Skill 归属。具体工具/资源裁决仍复用既有 Grant∩Intent 链路。
- 核心测试覆盖同名会话跨实例隔离、错误主体/平台、并发签发和接入、重启、换发、撤销、有效期上限、签名变化、过期、中断、文件完整性和拒绝优先。四个 Go 共享合同样例新增 Python 校验，累计 100 项合同测试通过；Go 全量、vet、runtimeidentity/intent/grant/receipt 的 race、Python lint、gofmt 和 diff 检查通过。四目标交叉构建通过，仍不代表 Windows/macOS 实机支持。
- [本批核心证据记录](evidence/personal-experience/runtime-identity-core-20260910/verification.json)区分核心单测与旧产品自检回归。下一步将该核心连接到管理/决策 HTTP 边界和 Hermes 原生钩子，再整合既有安装预览、事务与 UI；UX-007 继续 doing，任务书整体进度估算未上调。

## M12：实例身份 HTTP 与 Hermes 原生自动接入（UX-007 增量）

- 新管理 API 支持身份发行、查询与撤销，只返回摘要和客户端凭据路径，不返回秘密或 credential_hash；issued 状态仍为 runtime unverified。新登记 API 仅接受实例凭据与真实 session ID，服务从签名身份派生平台、主体和固定授权。新请求严格拒绝缺省/null、重复/未知字段、大小写别名及过大正文。
- 六类决策端点统一验证凭据与已绑定会话；全局凭据不能冒用 hri-/rca- 主体，实例凭据不能调用管理端点或访问其他会话。自检的原有短期启动凭据现在也用于决定/观察请求，限定已附着的活动会话，取消与到期后失效。与撤销后 hold 等原有 Authority 校验共同约束执行；普通 Grant 的 warn/audit_only 建议语义不变。
- Hermes 钩子自动登记真实 session，无需脚本观察器、手填会话或手动创建 Intent。新配置锁定实例主体，拒绝环境覆盖；身份登记或服务认证失败时所有模式阻止执行。凭据传输禁用代理/重定向，localhost 固定到回环 IP。源码与二进制内置适配器保持一致。
- [真实公开 CLI 验证](evidence/personal-experience/runtime-identity-http-20260910/identity-native.json)共 10 项通过：配置使用独立实例凭据，自动创建唯一权限包络与绑定，允许读、拒绝写、拒绝后仍可读，5 条签名回执验证通过；撤销后再次启动的新原生会话三次调用全部阻止，并保存 3 条明确未签名的 pending 拒绝。两轮均由本地合成模型驱动，既有宿主配置未被运行过程改写。
- [产品自检回归](evidence/personal-experience/runtime-identity-http-20260910/selfcheck-native.json) 7 项、[旧 Hermes 只读授权回归](evidence/personal-experience/runtime-identity-http-20260910/legacy-hermes-native.json) 7 项在最终候选通过；[OpenClaw 原生回归](evidence/personal-experience/runtime-identity-http-20260910/openclaw-native.json) 14 项通过，后者为独立构建，保留原制品身份。
- Go 全量、vet、六个相关包 race、103 项适配器测试、105 项合同测试、Python lint 和四目标交叉构建通过。[代码、命令与制品记录](evidence/personal-experience/runtime-identity-http-20260910/verification.json)绑定本批证据。本批没有 Web 源码变化，不声称新增前端旅程已验证。
- 剩余：正式安装预览/事务、配置诊断与前端启用/恢复仍需接入该身份；脚本只在隔离 profile 写入测试配置，不能代替普通用户安装体验。真实任务目的、实际 Skill 版本归属、原生 MCP 全链路、Windows/macOS/WorkBuddy 均未因此完成。下一批继续把这条已验证的 API/原生链路接入现有安装和管理界面，UX-007 保持 doing。

## M13：实例权限与正式安装流程整合（UX-006、007、012 增量）

- 设置/运行绑定页的“管理实例”新增默认权限接入流程：参考已有检查结果起草、共用编辑器、核对当前版本并批准、选择 1/8/24 小时会话期限、发行实例身份、预览和确认安装。关闭预览可重用已发行身份；未确认不改宿主文件。权限摘要区分只读/读写，安装期间禁止切换目标、同时撤权或关闭。
- 安装计划 `local-adapter-plan/v3` 固定实例身份；归属记录保存引用，修复不降级到全局 token。元数据和撤销状态加入不可变预览输入，凭据正文不读取、不复制到恢复日志。应用前服务重新验证签名身份及固定 Grant；诊断明确核对所属实例、主体和引用，仍不声称运行通过。
- 停用和卸载会撤销身份。卸载遇到外部文件变更时先停用权限、保留外部修改并给出恢复说明，不复活凭据。直接 CLI 卸载需先撤销并明确实例；完整 CLI 身份管理尚待整合。原生卸载恢复登记语义并保留其他配置，不要求 Hermes 重新序列化后的 YAML 与原文件逐字一致。
- [浏览器结果](evidence/personal-experience/managed-instance-20260910/browser/result.json) 12 项通过，覆盖从起草到批准/安装/撤销/卸载、并发版本冲突、取消与重开、单一焦点窗口、安装中冲突操作禁用、移动端按钮和无横向溢出。已检查 [桌面](evidence/personal-experience/managed-instance-20260910/browser/managed-preview.png) 与 [移动端](evidence/personal-experience/managed-instance-20260910/browser/managed-mobile.png)。使用真实临时 daemon 与公开 Hermes 原生启用 CLI；合成 Skill 和操作者，不操作用户日常配置。
- [Hermes 原生结果](evidence/personal-experience/managed-instance-20260910/managed-native.json) 15 项通过：使用正式安装 API 的产物启动公开 CLI，自动绑定普通会话、读允许/写拒绝/继续读取；同一已管理 profile 的产品自检使用独立临时权限并正常清理，普通身份保留。撤销后新会话三个工具调用全部被阻止。共 10 条服务签名回执与 3 条明确未签名的拒绝记录。[OpenClaw 回归](evidence/personal-experience/managed-instance-20260910/openclaw-native.json) 14 项通过，保留其独立构建身份。
- Go 全量/vet、安装/服务/身份/自检 race、106 项合同、20 项 Web 测试、类型检查及个人/企业构建通过；四目标交叉构建通过。新计划 Go 输出样例回灌 Python Schema，负向覆盖缺失身份、错误平台、凭据泄露字段与不能声称 runtime verified。命令、源码摘要、制品和证据见 [本批验证记录](evidence/personal-experience/managed-instance-20260910/verification.json)。
- 下一步继续 UX-007 的权限变更/换发体验、实际加载 Skill 归属与其他平台可信接入，并推进 UX-008 统一确认。Windows/macOS 原生路径与实机、WorkBuddy、后续个人任务和团队功能仍未完成；整体目标保持 active，未提交、推送或发布。

## M14：日常权限修订与实例换发（UX-007、012 增量）

- 新增 `POST /v1/grants/{id}/draft` 与独立 `grant-draft-create/created.v1` 合同，按源授权精确版本、操作者和请求标识创建新的待批准 Grant/策略。重试与并发请求复用同一草稿并读回后续编辑结果，不覆盖。源检查与新发布共用 commit 锁，审计失败不显示可用，源 Grant 不修改。
- 草稿保留范围、拒绝、逐次人批条件和期限，清除批准、生效读回与后端修订证明；到期授权也必须显式修改期限再批准。界面新增“调整当前权限”、已有授权选择和有效期编辑；新权限准备期间旧身份继续工作。切换须明确停用旧身份，再发行和确认配置；新身份不能接管旧会话，历史权限仍可查询。
- 修复既有准入签名问题：存储和 CLI 导出不再在签名后补写卡片路径。卡片仍保存于既有同名位置；旧记录只对精确本机派生路径还原原 null 后验原签名，其他字段和错误密钥不放宽。新 API 要求源准入非 quarantine 且可验证；不重写旧记录。Go 测试复现旧错误并验证新存储、CLI 导出和严格兼容负向。
- [浏览器流程](evidence/personal-experience/permission-revision-20260910/browser/result.json) 16 项通过：旧流程回归、新草稿预填、编辑不改旧授权、并发版本冲突、显式期限、批准后仍等待撤权、新身份拒绝旧会话和较宽目录、保留历史与卸载。浏览器换发后的裁决探针为真实 HTTP 请求；公开 CLI 的会话证明另见原生脚本。截图包含 [当前权限](evidence/personal-experience/permission-revision-20260910/browser/replacement-ready.png) 与 [准备替换的权限](evidence/personal-experience/permission-revision-20260910/browser/replacement-new-permissions.png)。
- [Hermes 原生换发](evidence/personal-experience/permission-revision-20260910/revision-native.json) 20 项通过，使用公开 CLI、正式安装产物和隔离 profile。旧身份撤销后拒绝，新身份的新原生会话固定到新 Grant，允许目录继续读取、已移出范围目录在执行前拒绝；旧 Grant 保持原样。回执按 14 条实际调用/自检关联记录与 pending 拒绝补记分开登记，补记只表示接收本机拒绝报告，不证明服务曾批准调用。[OpenClaw 回归](evidence/personal-experience/permission-revision-20260910/openclaw-native.json) 14 项通过，保留独立构建摘要。
- Go 全量/vet、grant/state/server/runtimeidentity/runtimecheck/CLI race、107 项合同、20 项 Web 测试、类型检查及个人/企业构建通过；四目标开发构建通过。[本批命令与候选记录](evidence/personal-experience/permission-revision-20260910/verification.json)保存代码、日志、制品与证据对应关系。最后的 Web 状态文案调整单独重建，并使用最终候选完成浏览器/原生流程。
- 接下来推进 UX-008 的统一确认待办和操作详情，同时保留 UX-007 的 Skill 实际加载归属、多 Skill 边界与平台矩阵缺口。尚无 Windows/macOS 实机、WorkBuddy、安装包和团队验收；个人整体任务未完成，未提交、推送或发布。

## M15：统一确认待办与请求单次处理（UX-008、012 增量）

- [ADR-031](adr/0031-local-confirmation-inbox.md) 与两个新合同定义 `/v1/confirmations` 管理列表、`/v1/confirmations/{action_id}/resolve` 单次处理。只读状态来自既有已签名 action，窗口为 24 小时、上限 8192；只提供既有脱敏 excerpt，不重建或保存参数原文。
- 处理在同一引擎锁内核对 action、原回执 ID/hash、参数摘要和未处理状态，写入唯一签名 hold_resolution。所有新入口重放均为 409；旧 hold 入口的同意图幂等保留。修复旧入口恰好截止时仍可批准的边界，两个入口都采用半开有效期。
- 个人导航新增“确认待办”：查看具体请求、明确审阅后批准或直接拒绝；断连暂停操作，并发处理后读取最新状态；长期授权定位到指定 Grant。回执页历史 hold 不再直接放行，改为查看确认状态。已批准只表示有审批记录，不代表执行完成；完整参数与当前权限仍由平台执行前核对。
- [浏览器证据](evidence/personal-experience/confirmation-inbox-20260910/browser/result.json) 13 项通过：打开不批准、审阅后单次批准、重放冲突、拒绝读回、并发冲突刷新、断连恢复、390px 窄屏、长期授权定位、回执链接、通知权限拒绝、客户端到期禁用及签名记录数量。测试使用隔离真实 daemon 与合成 OpenClaw HTTP 调用，未执行原生工具；客户端到期场景使用浏览器虚拟时钟，服务端精确截止由 Go 负向测试覆盖。
- Go 全量/vet、receipt/server race、109 项合同、20 项 Web 测试、类型检查、个人/企业构建和四目标开发构建通过。[Hermes 原生权限流程回归](evidence/personal-experience/confirmation-inbox-20260910/hermes-native.json) 20 项、[OpenClaw 原生链路回归](evidence/personal-experience/confirmation-inbox-20260910/openclaw-native.json) 14 项通过，三组验证对应同一 Linux arm64 候选。[验证清单](evidence/personal-experience/confirmation-inbox-20260910/verification.json)保存源码、候选和命令日志摘要。
- 待完成：通知发送与合并、后台启动器、Hermes 等平台批准后恢复执行、任务内授权及三系统实机。浏览器拒绝通知权限仍可操作，不等于通知投递已实现。实例凭据撤销仍在每次决策请求鉴权中校验，待办投影不替代执行授权。UX-007 的真实 Skill 归属等缺口继续保留，团队阶段尚未开始，整体目标保持 active；未提交、推送或发布。

## M16：浏览器待办提醒与 Hermes 继续执行能力核实（UX-008、012 增量）

- [ADR-032](adr/0032-personal-notification-delivery.md)明确浏览器通知默认关闭、由人工开启、只显示数量、点击只导航；无需新增管理或决策 API。个人外壳共用待办数据源，页面与导航计数复用每 5 秒读回，确认写入后更新同一份状态。
- 浏览器通知 500ms 合并、同源每 15 秒至多一次；Web Locks 协调多窗口，localStorage 只保存启用偏好、按本机公钥区分的请求 ID 摘要和发送时刻，摘要上限 512，超量改汇总通知。失败/断连/权限拒绝不改变批准结果；跨窗口关闭同步。此处是浏览器页面生命周期内提醒，不等于后台系统启动器。
- [浏览器证据](evidence/personal-experience/confirmation-notifications-20260910/browser/result.json) 23 项通过，包含 M15 审批旅程回归，以及人工开启、通知隐私、点击无写操作、多窗口去重、限流合并、元数据不含凭据/原始请求标识和关闭同步，另覆盖构造失败重试、单请求精确定位及退出后异步准备取消。Notification API 使用可审计替身，底层 daemon 为隔离真实服务；不声称 OS 已弹出通知。原生系统展示与操作系统投递异常的完整实机覆盖仍需后续验证。
- 24 项 Web 测试、类型检查、个人/企业构建、Go 全量/vet 和四目标开发构建通过。[验证清单](evidence/personal-experience/confirmation-notifications-20260910/verification.json)对应新候选；本批未改变后端裁决和适配器代码，未重复宣称原生平台回归覆盖新通知功能。
- [Hermes 当前扩展点核实](evidence/personal-experience/hermes-approval-capability-20260910.json)仅为已安装源码的只读检查：当前回调默认 30 秒上限，后续回调可合并修改参数，但 SIQ 当前接入没有最终参数的执行前复核。因此没有直接等待人批后返回允许；安全继续执行需补齐原生扩展或独立验收受控启动。未修改 Hermes 仓库，也未将这个缺口标为完成。
- 继续推进个人阶段的 Skill 安全导入/安装，同时跟踪 UX-008 原生继续执行、通知后台化和任务内授权；UX-007 的真实 Skill 版本归属、三系统/WorkBuddy 与综合验收保持未完成。整体目标 active，未提交、推送或发布。

## M17：Skill 固定导入、CLI 与管理 API（UX-009 增量）

- [ADR-033](adr/0033-skill-import-snapshots.md) 和三个 `local-skill-import*.v1` 合同已落盘。本地目录/ZIP 在私有状态目录复制为独立普通文件，完整清单覆盖目录、全部文件字节及执行位；固定副本准入后，最后排他发布签名导入审计，绑定完整载荷和分析摘要。该结果不产生批准或平台安装权限。
- 新增 CLI `import-skill --path … --actor … [--kind local_dir|local_zip] [--id si-…]`；取得既有 state writer 锁，不能与同状态的 daemon 并发写。管理会话可使用 `POST /v1/skill-imports` 和 `GET /v1/skill-imports/{id}`；严格请求、绝对来源路径、每 daemon 单并发、60 秒处理预算和独立响应写期限。返回固定错误类别，不暴露源绝对路径、凭据或文件正文。
- 同 ID/来源/操作者重试验签读回既有副本，不重读后来变化的源；不相同输入冲突。重新读取时验签、重算完整载荷与分析摘要，不能只依赖既有准入哈希。拒绝路径穿越、符号链接、设备名/ADS、重复和大小写冲突、ZIP 元数据欺骗/CRC 错误、加密、ZIP64 与容量超限；排除 `.git`，不运行脚本或钩子。取消、等待写锁、最终发布失败不产生可用候选；响应丢失后仍需以原 ID 查询发布结果。
- [隔离实际二进制验证](evidence/personal-experience/skill-import-20260910/smoke/result.json) 12 项通过，覆盖 CLI/HTTP、管理凭据分权、独立 Python 验签和清单重算、ZIP/目录载荷一致、原源变化、重试/操作者冲突、服务重启、危险 ZIP、副本替换、单次签名审计及没有执行/批准/安装。脚本只复用既有测试工具的隔离 daemon 生命周期，不调用 Hermes 原生 worker，不作为平台运行接入证据。
- Go 全量测试、vet、skillimport/server/CLI 的 race、112 项 Python 合同与增量 lint、四目标交叉构建通过。[本批验证清单](evidence/personal-experience/skill-import-20260910/verification.json)记录源码、命令日志和同一 Linux 候选的验证身份。Go 的合同样例只规范化时钟、来源路径摘要及未随 DTO 导出的分析摘要并重新签名；实际服务验证另核对真实分析摘要。本批没有修改 Web 源码，沿用 M16 嵌入前端。
- 待完成：HTTPS/Git 来源、前端导入/检查/权限审阅、安装事务及目标内容读回；Skill 更新移除、真实运行归属与三系统/WorkBuddy 验收仍属完整任务目标。HTTP 同步等待不是后台任务队列；候选最多 64 个，后续需加入审阅后的清理生命周期。M17 不标记 UX-009 完整完成，也不提高整体约 25% 的粗估口径；团队阶段未开始。未提交、推送或发布。

## M18：个人 Skill 导入审阅与历史恢复（2026-09-11，UX-009/012 增量）

- [ADR-034](adr/0034-skill-import-review.md)、`local-skill-import-list.v1` 和 Go/Python 共用样例已落盘。管理 GET `/v1/skill-imports` 最多返回 64 条签名元数据，明确 payload_status=unchecked；损坏记录保留编号及不可用状态，未经验证字段不展示。只有打开详情才重算完整副本；历史列表不代表当前载荷有效，读取不发布新记录。
- 个人治理导航和资产页新增“导入 Skill”，独立页面按需加载。填写本机目录/ZIP 的绝对路径和操作者后，先创建随机请求 ID，再显示准入结论、声明需求、发现摘录、文件清单及摘要。页面明确“尚未安装”“尚未批准”，不调用 Grant、平台配置或安装入口。本批是本机路径输入，尚无浏览器文件上传/目录选择和 URL 获取。
- URL 只保存导入 ID，来源路径不进入 URL 或 Web Storage。响应丢失后可显式查询，或以完全相同的原请求重试；刷新通过签名历史恢复。重复提交受内存锁限制；离开、退出或切换查询时取消旧请求并忽略迟到结果；断连和篡改后撤下旧的完整校验结果。前端导入相关请求使用 70 秒预算，其余调用保留原时限。
- 固定导入的 source.locator 是不透明编号，过去被当作目录名参与信息级名称比较，导致正常包产生无效提示。新增内部 SourceIsOpaque，仅固定导入显式跳过这项比较；原有路径来源仍检查名称，其他准入/威胁判定保留。正负向测试证明隔离规则未放宽；已有准入记录不回写。
- [浏览器验证](evidence/personal-experience/skill-import-review-20260911/browser/result.json) 16 项通过，覆盖实际目录/ZIP、重复提交、历史刷新、原请求重试、篡改/损坏记录、恶意 HTML 作为文本、离开/退出时的迟到响应、断连恢复及 390px 窄屏。[桌面](evidence/personal-experience/skill-import-review-20260911/browser/import-desktop.png)、[移动端](evidence/personal-experience/skill-import-review-20260911/browser/import-mobile.png)、[隔离内容文本展示](evidence/personal-experience/skill-import-review-20260911/browser/quarantine-text.png)已经检查。使用隔离真实 daemon/Chromium；响应丢失、延迟和断连为明确的浏览器故障注入，未替代平台执行。
- 同一 Linux arm64 候选的 [CLI/HTTP 回归](evidence/personal-experience/skill-import-review-20260911/cli-http/result.json) 12 项通过，独立验签与完整清单重算通过。Go 全量/vet、skillimport/server/admission race、113 项 Python 合同、29 项 Web 测试、类型检查、个人/企业构建、四目标交叉构建及增量 lint 通过。[源码/制品/日志清单](evidence/personal-experience/skill-import-review-20260911/verification.json)保留本批证据；没有修改已运行的用户 daemon 或任何真实平台配置。
- UX-009 继续 doing。下一步是 HTTPS/Git 来源获取、权限准备与批准、安装事务和目标内容读回；更新移除、隐私、任务聚合、三系统/WorkBuddy 验证和团队阶段仍未完成。总体约 25% 是粗估，整份任务书仍按数周级工程范围规划，尚无可靠交付日期；跨 OS、WorkBuddy 和局域网双设备实机证据是完整交付的必要条件。未提交、推送或发布，持续目标保持 active。

## M19：HTTPS ZIP Skill 下载导入（2026-09-11，UX-009/012 增量）

- [ADR-035](adr/0035-https-skill-import.md)、remote-create/v1、记录/结果 v2 与混合列表 v2 已落盘。本地 v1 保持兼容；HTTPS 候选记录绑定原始归档摘要、字节数、所选目录、可选预期 SHA256 和来源摘要，不保存 URL/查询参数。详情复验选中载荷与分析，原归档不持久保存，下载时 SHA256 不冒充当前完整归档读回。
- 下载仅接受公网 HTTPS/443。每次连接解析并检查全部 DNS 结果，固定为字面 IP 连接；混合公网/私有结果拒绝，三次重定向上限且每跳重新检查。正常 TLS 证书链/主机名校验、禁用代理/Cookie/Referer、45 秒下载及 32 MiB 实际字节预算；可选摘要先比对再解包。选取目录前检查整个 ZIP，失败不发布记录并清理自建暂存。
- 管理 `POST /v1/skill-imports/remote` 和 CLI `import-skill --url ... --archive-path ... --sha256 ... --actor ...` 已接通。严格请求、管理分权、单并发与取消沿用现有导入入口；同 ID 原请求重试只复验已保存副本，不重新联网，变更来源/所选目录/摘要/操作者会冲突。
- 个人“导入 Skill”页新增 HTTPS ZIP 来源、可选归档内目录和预期摘要；显示下载证据，继续明确尚未批准/安装。前端区分 v1/v2 响应并拒绝版本错配，响应丢失后显式按原请求重试；URL 不进入位置栏和 Web Storage。
- Go 全量、vet、skillimport/server/CLI race、117 项 Python 合同、31 项 Web 测试、个人/企业构建、四目标交叉构建与增量 lint 通过。下载层受控 TLS 正负向覆盖证书、重定向、DNS 重绑定/混合结果、代理/头部禁发、32 MiB 边界、响应编码、DNS/响应取消；完整下载到签名副本的集成测试覆盖子目录、摘要、隐私、重试、失败清理与降级拒绝。
- 同一个 Linux arm64 候选：[本地浏览器回归](evidence/personal-experience/skill-import-https-20260911/local-browser/result.json) 16 项、[CLI/HTTP 独立验签回归](evidence/personal-experience/skill-import-https-20260911/cli-http/result.json) 12 项、[HTTPS 前端验证](evidence/personal-experience/skill-import-https-20260911/remote-browser/result.json) 7 项通过。HTTPS 前端负向走真实 daemon，成功显示和重试使用明确的 Go DTO 响应夹具；没有将其当作公网下载或平台安装实证。[桌面输入](evidence/personal-experience/skill-import-https-20260911/remote-browser/remote-form-desktop.png)、[移动输入](evidence/personal-experience/skill-import-https-20260911/remote-browser/remote-form-mobile.png)、[夹具结果](evidence/personal-experience/skill-import-https-20260911/remote-browser/remote-result-fixture.png)已目视检查。
- [本批验证清单](evidence/personal-experience/skill-import-https-20260911/verification.json)保存来源、制品和日志摘要。UX-009 仍为 doing：Git 仓库入口、权限准备/批准、平台安装及目标读回尚未完成，之后继续更新移除、任务聚合、隐私与发布准备。三系统/WorkBuddy 和两设备验收缺口不变，团队阶段未开始；整体约 25% 仍为粗估。未提交、推送或发布，没有修改用户现有 daemon 或真实平台配置，持续目标保持 active。

## M20：导入候选的权限准备与人工批准（2026-09-11，UX-007/009/012 增量）

- [ADR-036](adr/0036-import-permission-preparation.md)与三个权限准备合同已落盘。`internal/importsource` 以导入 ID、完整 artifact_digest、analysis_sha256 的规范化对象派生独立 adm-si- 全 SHA256 身份；保留原扫描结论与时钟，证据独立命名并重新签署。原始导入记录/分析不改写，派生 admission、卡片和证据用同目录排他发布和严格同值重试，避免旧内容哈希前缀或兼容写入混淆来源。
- 新 Grant ID 绑定上述来源、平台/主体、操作者和明确请求 ID，初始仍为 pending_approval/default-deny。复用现有 Grant 签名、权限/期限编辑、revision CAS、challenge/approve 与审计；没有第二套审批。管理 POST `/v1/skill-imports/{id}/permissions` 解析实际存在的 Hermes 实例并派生 hri 主体，首次 201、原请求重试 200，保留已有批准或终态，不复活权限。
- 普通 HTTP/CLI 从 admission 创建权限不能绕过新准备入口。服务器 challenge/approve/draft 与离线 CLI challenge/approve 重新验证完整候选和派生签名；更换内容或来源时拒绝。拒绝/撤销不依赖完整候选仍可用。安装事务尚未接通，核心 MarkDeployed/MarkEffective 明确阻止导入权限提前激活；当前不能以这种批准签发运行身份，也不宣称 Skill 调用归属已经可信。
- 前端非隔离候选新增目标实例和操作者选择，准备后进入已有签发页审阅。来源摘要与候选链接可查看；响应丢失提供原请求重试，离开组件取消并忽略迟到响应。通用“标记已部署”对这种权限禁用，服务核心仍独立拒绝。暂时仅 Hermes 目标解析接通；OpenClaw、WorkBuddy 与三系统实测范围没有缩减为已完成。
- Go 全量、vet、skillimport/server/grant/state/CLI race、120 项 Python 合同与增量 lint、33 项 Web 测试、个人/企业构建和四目标编译通过。Python 独立重算来源 admission ID 和请求 Grant ID，Go 测试覆盖同内容不同导入、完整清单变化、严格写入冲突、来源篡改、审批后不得提前部署、原请求保持批准和单次审计；离线 CLI 不能绕过来源校验。
- 同一 Linux arm64 候选：[权限流程浏览器](evidence/personal-experience/skill-import-permissions-20260911/browser/result.json) 8 项、[本地导入回归](evidence/personal-experience/skill-import-permissions-20260911/local-browser/result.json) 16 项、[HTTPS 前端回归](evidence/personal-experience/skill-import-permissions-20260911/remote-browser/result.json) 7 项、[CLI/HTTP 回归](evidence/personal-experience/skill-import-permissions-20260911/cli-http/result.json) 12 项通过。权限流程使用真实隔离 daemon 和浏览器，响应丢失发生在真实提交之后，内容替换发生在 challenge 与 approve 之间；Hermes 目标是隔离配置夹具，没有运行宿主或安装 Skill。HTTPS 成功展示仍是明确 DTO 夹具，未扩大 M19 的证据声明。
- [批准页桌面](evidence/personal-experience/skill-import-permissions-20260911/browser/permission-approved-desktop.png)、[窄屏来源摘要](evidence/personal-experience/skill-import-permissions-20260911/browser/permission-source-mobile.png)已检查；旧导入浏览器长卡片截图定位改为滚动标题，保留视口/溢出检查。[源码/制品/日志清单](evidence/personal-experience/skill-import-permissions-20260911/verification.json)记录本批身份。下一步继续安装预览、批准摘要绑定、目标写入与恢复读回；UX-007/009 仍未整项完成，旧版本降级保护、Git 来源、其他个人任务和全部团队任务仍在完整目标中。未提交、推送或发布，用户 daemon 与真实平台配置未改动。

## M21：Skill 安装计划的私有暂存核心（2026-09-11，UX-009 增量）

- [ADR-037](adr/0037-skill-install-staging.md)、stage-create/v1 与 plan/v1 合同先行，新增 skillinstall 暂存库及 skillimport 的受限复制入口。计划绑定完整来源、已批准 Grant 的版本/签名/权限摘要、Hermes 实例、单层目录名、操作者和目标位置摘要；五分钟有效，原请求复验重用不续期，同请求不能悄悄更换目标。
- 只向 SIQ 私有状态目录复制独立文件，完整核对原候选及暂存清单，最后排他发布签名计划。拒绝已有目标及大小写别名、链接、不匹配或失效授权、内容变化、损坏计划。复制后重新核对批准状态和目标缺失；失败只清理本次创建的暂存，孤立目录不接管；64 个容量包含孤立目录。
- Load 重新校验形状、签名、计划身份、期限、来源、权限、目标和完整副本；暂存不批准、不部署、不签发运行身份。合同样例由 Go 输出，Python 独立重算 plan_id 和有效期，并覆盖缺省/null/未知字段及容量边界。
- 本批范围为核心库，尚无安装预览 API/UI，也未实际安装或进行平台识别验证。[验证清单](evidence/personal-experience/skill-install-staging-20260911/verification.json)记录 Go 全量/vet、核心竞态与正负向测试、122 项 Python 合同及 lint、四目标所有包编译；没有以尚未接入 CLI 的核心包冒充用户可用功能。
- 下一步接入安装预览与明确确认，继续实际目标写入、创建归属、失败恢复与完整读回；UX-009 仍为 doing。全部个人任务和 LAN-001–006 的范围保持不变，目标 active，未提交、推送或发布，用户 daemon 和日常平台配置未改动。

## M22：安装预览的管理 API 与个人界面（2026-09-11，UX-009/012 增量）

- [ADR-038](adr/0038-skill-install-preview-ui.md)与 plan-created/v1 合同先行。管理 POST `/v1/skill-installations/plans` 接通 M21 核心暂存，首次 201、原请求复验重用 200；GET 单份计划完整复验。目标只由现有 Hermes 实例解析器解析，与导入共享单并发工作锁及 60/65 秒处理/写出预算。决策凭据不能访问，严格输入拒绝客户端目标路径。
- 来源绑定的 Hermes 授权批准后，签发页提供目录名预填与编辑、显式生成预览、原请求重试、刷新复验和重新准备。计划显示目标位置、文件数/大小、内容与权限摘要及到期时间；候选损坏或撤权时撤下旧预览。重新起草的授权按实际身份匹配，未被错误限定为初始编号前缀。切换表格授权同步位置栏 ID，避免刷新回到另一份授权。
- Go 全量/vet、server/skillinstall/skillimport race、123 项 Python 合同及相关 lint、36 项 Web 测试、个人/企业构建与四目标二进制构建通过。HTTP 测试覆盖导入→批准→暂存→重试→读取→撤销、管理分权、严格输入、旧版本、竞争、取消和源篡改；确认没有平台安装或运行权限变更。
- 同一 Linux arm64 候选的 [安装预览浏览器](evidence/personal-experience/skill-install-preview-20260911/browser/result.json) 7 项和 [既有权限批准回归](evidence/personal-experience/skill-install-preview-20260911/permission-browser/result.json) 8 项通过。预览测试真实提交后丢弃响应，原请求重试只保留一份计划；刷新不发送新 POST，暂存篡改和撤销使预览失效。目标与配置保持不变，无新运行身份。前者的人工批准是隔离 API 夹具，后者通过浏览器批准，没有将两种证据混称。
- 已检查 [桌面预览](evidence/personal-experience/skill-install-preview-20260911/browser/preview-desktop.png)、[移动端内容](evidence/personal-experience/skill-install-preview-20260911/browser/preview-mobile.png)和 [移动端操作](evidence/personal-experience/skill-install-preview-20260911/browser/preview-mobile-actions.png)。截图脚本等待侧栏收起完成，检查主内容宽度和操作区可见，避免把动画中间帧当作完成状态。[验证清单](evidence/personal-experience/skill-install-preview-20260911/verification.json)记录本批源码和制品身份；M20/M21 历史记录不改写。
- 下一步继续明确安装确认、目标写入归属、失败恢复与目标内容读回，再做平台识别与实际运行验证。UX-009 仍在进行，全部个人任务和局域网团队目标保持 active；三系统/WorkBuddy 和两设备验收缺口不变。未提交、推送、发布或重启用户现有 daemon。

## M23：安装事务开发中的固定清单读取（2026-09-11，UX-009 仍在进行）

- [ADR-039](adr/0039-skill-install-publication-recovery.md)明确下一步文件发布与恢复方案：不使用可覆盖目录的重命名冒充 no-replace，按独占目录、排他文件发布和归属证据推进；目标完整读回与保护验证分别登记。创建目录到记录归属之间的崩溃窗口需显式处理，归属不明时不猜测删除，用户修改的文件保留。
- 已实现 skillimport.InstallationSnapshot：打开时完整校验候选并固定签名清单，按准确相对路径读取清单成员，每个文件检查目录/类型、摘要、字节数与执行位，Metadata 返回独立副本；批次结束 Verify 重新验证全部内容、分析和原记录签名。避免安装器每读取一个文件就重新扫描整个候选；单文件读取不代表全量验证或运行授权。
- 测试覆盖清单返回值修改、读取缓冲区修改、原始来源后来变化、清单外/大小写不同路径、辅助文件替换、符号链接、执行位变化、取消和最终分析/签名失效。Go 全量、vet、skillimport/skillinstall race 与四目标所有包编译通过，[验证记录](evidence/personal-experience/skill-install-snapshot-20260911/verification.json)绑定本批代码和日志。HTTP/JSON 输出未变化，本批没有前端改动，沿用 M22 前端证据。
- 本批仅完成实际安装所需的固定读取接口和恢复设计，目标文件发布、签名操作日志、安装确认、跨重启恢复与平台识别仍未完成；没有将底层接口计为 UX-009 完成。下一步实现对应的排他发布及归属记录。完整个人与团队目标保持 active，未提交、推送、发布或改动用户现有服务与平台目录。

## M24：安装提交、目标读回与恢复核心（2026-09-11，UX-009 增量）

- [ADR-039](adr/0039-skill-install-publication-recovery.md)补齐 apply/claim/owner/operation 四份 v1 合同；按当前任务书限定了确认目标及同 profile 私有操作目录的写入例外。Apply 必须匹配预览 ID、签名、操作者和显式确认，写入前再次复验权限、期限、候选与暂存；签名操作声明先于外部目录写入。
- 独占创建新目标，操作文件先以不透明名称写入并同步，再通过 os.Link 排他发布；所有入口文档延后，根 SKILL.md 最后发布。每个自建目录保存签名归属标记，目标完整读回检查清单、类型、摘要、执行位、归属与未知对象。完成记录为 installed_unverified，不改变 Grant 批准版本，不签发运行身份或宣称已保护；当前目标变化后拒绝返回仍有效的安装读回。
- 原请求重试只读取已记录结果，过期后不重新安装或续权。失败可回滚未被修改且归属可证的对象；用户新增/修改内容保留并报告 recovery_required。初次失败与后续恢复分别排他记录。恢复可在原候选损坏、授权已撤销或过期后执行，不恢复运行权限；当前进程能清理其自建空目录，跨进程归属不明的目录保持原状。
- 已通过正常/失败/撤权/取消、大小写冲突、操作副本篡改、用户内容保留、嵌套文件与入口发布顺序、保留元数据名、64 个操作容量及原请求重用测试。四个真实 Go 子进程退出窗口重新打开状态后完成预期恢复或准确报告归属不明。Go 全量/vet、skillinstall/skillimport/server race、127 项 Python 合同及 lint、四目标所有包编译通过；Python 独立重算清单并验证声明/归属/结果签名。
- [源码与验证记录](evidence/personal-experience/skill-install-publication-20260911/verification.json)绑定本批证据。这里验证的是临时目录中的核心文件操作，不是原生平台识别、运行保护或三系统文件系统验收；无新增前端，管理 API/安装确认按钮/恢复界面仍待接通。UX-009 保持 doing，完整个人与团队目标 active，未提交、推送、发布或重启用户服务。

## M25：安装确认、结果查询与失败恢复界面（2026-09-11，UX-009/012 增量）

- [ADR-040](adr/0040-skill-install-management.md)与 recover/view v1 合同先行。管理 apply、单操作读取与 recover 接通 M24 核心；复用管理会话、严格正文、共享互斥和处理预算。签名 claim 提供历史计划，避免成功安装后误用“目标必须不存在”的预览读取；结果缺失仅投影 recovery_required，不伪造签名记录。
- 预览增加明确勾选与确认按钮，绑定计划签名和原操作者。提交前保存不透明 install_id，完成或响应丢失后查询原记录，刷新不重发安装。结果卡片独立于当前授权/来源，支持撤权或源损坏后的恢复；目标变化撤下旧成功状态。恢复单独确认，未知/修改内容保留，不能借失败恢复卸载成功安装。
- 窄屏确认框尺寸已修正，长来源/授权证据收进可展开详情，默认显示状态、目标和可操作的恢复入口。已检查 [桌面结果](evidence/personal-experience/skill-install-management-20260911/browser/installed-desktop.png)、[窄屏安装确认](evidence/personal-experience/skill-install-management-20260911/browser/confirm-mobile.png)及 [窄屏恢复](evidence/personal-experience/skill-install-management-20260911/browser/recovery-mobile.png)。
- Go 全量/vet、server/skillinstall/skillimport race、129 项 Python 合同及增量 lint、37 项 Web 测试、个人/企业构建和四目标二进制构建通过。[安装管理浏览器](evidence/personal-experience/skill-install-management-20260911/browser/result.json) 9 项及 [原安装预览回归](evidence/personal-experience/skill-install-management-20260911/preview-browser/result.json) 7 项通过，使用同一 Linux arm64 候选；恢复中断状态由测试夹具构造，真实跨进程退出由 M24 核心测试覆盖。
- [源码/制品/验证清单](evidence/personal-experience/skill-install-management-20260911/verification.json)绑定本批证据。已经能在隔离 Hermes profile 完成确认安装与恢复，但未运行原生宿主或候选代码，未证明 Skill 可信运行归属或保护，不提升 Grant/运行身份。下一步继续平台识别与保护接入，UX-009 和完整个人/团队目标保持 active；未提交、推送、发布或重启用户 daemon。

## M26：安装内容绑定的实例权限与 Hermes 原生验证（2026-09-11，UX-007/009 增量）

- [ADR-041](adr/0041-installed-instance-permission-binding.md)、activate/runtime-binding/activated v1 合同先行。新增安装器专属管理准备入口：显式确认实例权限范围，完整复核已安装目标、原候选、批准版本和权限摘要，排他发布签名绑定，再通过原 GrantCommit/CAS 与审计追加批准版本。原计划安装期限不当作运行授权期限，Grant 自身期限始终校验；重复请求保持原绑定、版本与时间。
- 旧 Grant 状态保持 approved，普通 deploy/effective 继续拒绝。只有显式配置的固定授权读取路径可选择带完整验证绑定的批准版本；默认 Intent 原始读取、未注册验证器和隐式 Grant 查找不能启用。全量内容复验单并发、服务端五秒预算，每次发行/认证/会话登记/固定授权使用均重新检查；目标、源、绑定、实例或权限变化即拒绝。失败审计、只落绑定未提交权限、中断后重试均有负向测试。
- [公开 Hermes 清单识别](evidence/personal-experience/installed-instance-permissions-20260911/native-recognition/result.json) 4 项通过：实际 SIQ 安装后，公开 skills list 的 all/local enabled-only 均列出该 Skill，目标/配置/权限未被清单查询修改。[公开 CLI 运行](evidence/personal-experience/installed-instance-permissions-20260911/native-runtime.json) 17 项通过：完整导入、资源配置、人工批准、安装和权限绑定后，沿用产品身份/适配器入口与正常 Hermes Agent 循环，读取通过、越权写入不执行、拒绝后仍可读取，自检使用独立权限，撤销后新会话三次调用均被阻止，10 条签名回执链通过验证。
- [旧 M25 二进制兼容探测](evidence/personal-experience/installed-instance-permissions-20260911/legacy-reader.json) 3 项通过：在临时状态中读取未撤销的新实例身份时显示 grant_unavailable，拒绝会话登记且未创建 Intent。这验证新安装权限不会通过旧批准状态被启用，不代表 UX-010 的所有状态格式降级问题已经解决。
- Go 全量/vet、六包 race、132 项 Python 合同与增量 lint、四目标构建通过，[源码/制品/证据记录](evidence/personal-experience/installed-instance-permissions-20260911/verification.json)绑定本批。沿用 M25 前端，本批管理 API 尚无新的个人按钮；下一步把实例权限准备接入安装结果和现有管理实例界面。运行验证针对 Linux 隔离 profile 与合成模型，实际 Skill 调用归属、Windows/macOS、WorkBuddy、完整生命周期与全部团队任务仍待完成。未提交、推送、发布或重启用户 daemon。

## M27：安装后的权限确认与实例接入界面（2026-09-11，UX-007/009/012 增量）

- [ADR-042](adr/0042-installed-permission-readiness.md)与 runtime-readiness/v1 合同先行。新增按安装或已签名 Grant 绑定查询的管理 GET，完整复核安装目标、来源、批准内容、版本和期限，区分尚未准备、提交中断、已准备和无可运行工具；不创建绑定、签发身份或重发写请求。空工具权限在绑定/凭据发布前明确拒绝，旧版本已发布的空工具绑定也不能运行。
- 安装结果页展示权限、有效期和实例范围，必须明确勾选才准备权限。写响应丢失后只读查询原操作，刷新保留真实准备状态；中断操作显示原操作者并显式重试。来源、目标、权限或绑定变化撤下旧状态与接入按钮。“权限已准备”不宣称运行保护或 Skill 调用归属。
- 串联既有管理实例和自检弹窗，锁定安装对应的实例及 Grant；目标不存在时不回退其他 profile。导入授权按安装绑定查询，不能误走通用 deploy。旧身份对应另一份权限时必须明确停用后才能签发新身份；重复点击通过同步提交锁只发一次。通用权限起草列表不再提供不能经该入口创建的导入准入。
- [安装后权限浏览器验证](evidence/personal-experience/installed-permission-ui-20260911/browser/result.json) 12 项通过，覆盖安装、权限准备的响应丢失和刷新、锁定实例/授权、明确撤销旧身份、签发新身份、配置应用、自检目标预选与目标内容变化。自检只验证入口，不自动启动宿主。[既有管理实例浏览器回归](evidence/personal-experience/installed-permission-ui-20260911/managed-browser/result.json) 12 项通过，使用公开 CLI 在临时 profile 启用原生插件。已查看桌面与窄屏准备页、窄屏接入弹窗。
- 同一 Linux arm64 候选的 [Hermes 原生运行回归](evidence/personal-experience/installed-permission-ui-20260911/native-runtime.json) 17 项通过：读取、越权写入阻止、拒绝后读取、自检独立权限及撤销后阻止，10 条签名回执链通过。Go 全量/vet、六包 race、133 项 Python 合同、增量 lint、40 项 Web 测试、个人/企业构建和四目标交叉构建已执行；最终状态由[验证清单](evidence/personal-experience/installed-permission-ui-20260911/verification.json)登记。
- 该批完善 Linux/Hermes 安装后的个人操作流程，不代表 UX-007/009 整项或个人版验收完成。Git 仓库与平台安装拦截、可信 Skill 归属、完整更新/移除、追溯隐私与三系统/WorkBuddy 验证仍待推进，团队阶段未开始。下一步补齐现有安装的内容变化与生命周期处理，继续任务书完整范围；目标 active，未提交、推送、发布或重启用户服务。

## M28：已安装记录与当前内容变化检查（2026-09-11，UX-010/012 增量）

- [ADR-043](adr/0043-installed-skill-inspection.md)和 record/catalog/inspection 三份 v1 合同先行。新增管理只读列表，从签名计划、声明与历史结果恢复安装入口，明确 recorded_status 不是当前内容或权限状态。损坏及孤立记录计入 issues；64 个操作/256 个状态目录项上限拒绝溢出，不从未核验正文取名称和路径。
- 按原签名清单比较当前目标，报告新增、缺失、内容或执行位变化、类型变化和归属变化。未知目录作为一个新增对象，不递归、不读取未知文件、不执行内容；原文件检查大小、摘要、执行位和硬链接归属。总目录项预算 8192，最多显示 200 条变化并保留观察总数；未完成明确 unavailable，目标整体缺失不当作卸载成功。历史记录读取独立于来源是否仍可用，原 ReadView 和运行时目标校验仍严格拒绝变化。
- 个人导航、导入页和安装结果增加“已安装 Skill / 查看内容变化”入口。页面支持记录选择、深链刷新、检查时间与差异展示，并回到原安装/权限操作。可见时每 30 秒只读复查所选目标，隐藏后暂停，重新显示即复查；开始检查或请求失败撤下旧当前状态。
- 同一 Linux arm64 候选的 [内容检查浏览器](evidence/personal-experience/installed-skill-inspection-20260911/browser/result.json) 14 项通过，包含实际等待的自动检查、受控 visibility 事件、修改/缺失/未知目录与转义名称、读取失败、目标整体移动、原候选损坏和原操作跳转。已查看 [桌面](evidence/personal-experience/installed-skill-inspection-20260911/browser/inspection-desktop.png)及 [窄屏](evidence/personal-experience/installed-skill-inspection-20260911/browser/inspection-mobile.png)；修正差异行排版后重新构建并复验。
- [既有安装后权限浏览器](evidence/personal-experience/installed-skill-inspection-20260911/permission-browser/result.json) 12 项和 [Hermes 原生运行](evidence/personal-experience/installed-skill-inspection-20260911/native-runtime.json) 17 项通过，后者保持 10 条签名回执链及撤销后阻止。Go 全量/vet、skillinstall/server race、136 项 Python 合同、相关 lint、42 项 Web 测试、个人/企业构建与四目标交叉构建通过。[源码/候选/证据清单](evidence/personal-experience/installed-skill-inspection-20260911/verification.json)绑定本批。
- UX-010 由 todo 转为 doing，仅内容检查及记录入口完成。远端新版检查、内容/权限更新差异、确认切换、移除与共享关系处理、兼容状态写入拒绝仍未完成；来源和宿主运行有效性不由 matched 推导。下一步继续明确移除与恢复流程，再衔接受控更新；全部个人和团队目标保持 active，未提交、推送、发布或重启用户服务。

## M29：明确移除与恢复核心/API（2026-09-11，UX-010 增量）

- [ADR-044](adr/0044-explicit-skill-removal.md)及 remove/removal-claim/removal-result/removal-view 四份 v1 合同已落盘。管理 GET 只读展示当前范围；POST 必须确认并固定原安装签名、Grant 版本、运行绑定与操作者。移除声明签名排他发布，重试只接受原确认内容；完成后返回历史结果，不再触碰同路径后来出现的用户对象。
- 先完成 Grant 撤销及审计，再清理可证明归属的原目标；运行验证遇到移除声明立即拒绝，待撤销权限不能接到另一份安装。Grant 已绑定另一安装时保留该权限与另一目标，并记录保留关联。未知、修改或归属不明内容停止整个清理；来源损坏不阻止撤权。中断状态区分 revocation_pending 与 cleanup_pending，不复活权限、不重建文件。
- 五个实际子进程退出点覆盖声明发布、撤权后、SKILL.md 清理后、目录标记删除后和最终结果前；新进程读取并以原请求恢复。无归属标记的空目录保留，夹具模拟用户核对并移除空目录后才能完成。Go/API 另覆盖三种模式的旧/新会话拒绝、管理/决策凭据分权、严格正文、no-store、版本冲突、审计缺失、用户内容保留、共享 Grant、路径复用及 256/257 枚举边界。
- 同一 Linux arm64 候选的 [真实 Hermes 移除验证](evidence/personal-experience/installed-skill-removal-20260911/native-removal.json) 17 项通过：原实例身份在移除前 issued，未调用身份撤销接口，正式移除使 Grant revoked、身份 grant_unavailable、目标不存在；新的原生会话三个工具调用全部阻止，10 条既有签名回执链验证通过，3 条拒绝明确为未签名 pending 记录。[原身份撤销运行回归](evidence/personal-experience/installed-skill-removal-20260911/native-runtime.json)同样 17 项通过。均使用隔离 profile 与合成任务，不能推定实际 Skill 归属或 OS 隔离。
- Go 全量/vet/gofmt、六包 race、140 项 Python 合同、相关 lint、四目标交叉构建通过；额外权限迁移/枚举边界测试单独保存命令日志。本批未改 Web 源码，沿用 M28 嵌入页面，不声称新增浏览器旅程通过。[源码/制品/验证记录](evidence/personal-experience/installed-skill-removal-20260911/verification.json)绑定本批证据。
- 下一批接入个人版移除确认、响应丢失只读恢复和清理待办，再推进受控更新。UX-010 仍 doing；三系统/三平台、安装器、追溯隐私和 LAN 完整目标继续 active，未提交、推送、发布或重启用户服务。

## M30：个人版移除确认、恢复与历史展示（2026-09-11，UX-010/012 增量）

- 按 [ADR-044](adr/0044-explicit-skill-removal.md) 将已有移除合同接入前端，严格校验记录、声明、结果和当前授权关系。已安装页顺序读取移除状态与内容检查，完成后显示历史结果，避免把目标缺失误报为移除；已开始移除的记录直接跳转授权历史，不进入要求目标仍存在的安装结果入口。
- 确认窗口展示具体副本、权限撤销或保留范围、操作者和内容保留说明；打开后冻结背景检查及列表切换。勾选后才允许提交，同步锁阻止重复写入。响应丢失只查询原移除操作；查询失败撤下旧执行状态，重新查询不自动 POST。恢复须再次确认，重用原声明的操作者、版本和范围；成功后仅提供历史记录，无再次清理按钮。
- 最终候选的 [移除浏览器验证](evidence/personal-experience/skill-removal-ui-20260911/browser/result.json) 10 项通过，包括取消、双击、写响应和查询失败、刷新恢复、用户文件保留、原请求继续、完成后路径复用与授权历史跳转。已查看 [桌面](evidence/personal-experience/skill-removal-ui-20260911/browser/removal-desktop.png)和 [窄屏恢复窗口](evidence/personal-experience/skill-removal-ui-20260911/browser/removal-mobile.png)。测试中的用户笔记由夹具操作者明确移出目标后再重试，不是产品自动移走用户文件。
- 同一候选的 [原内容检查浏览器回归](evidence/personal-experience/skill-removal-ui-20260911/inspection-browser/result.json) 14 项与 [Hermes 原生移除回归](evidence/personal-experience/skill-removal-ui-20260911/native-removal.json) 17 项通过，后者保留 10 条签名回执链和 3 条未签名的撤权后拒绝记录。44 项 Web 测试、个人/企业构建、Go 全量/vet/gofmt、脚本 lint 和四目标交叉构建通过。[验证清单](evidence/personal-experience/skill-removal-ui-20260911/verification.json)绑定最终源码和制品；本批合同未变化，Python 合同校验沿用 M29 独立证据，不重复声称本批重跑。
- UX-010 保持 doing，下一步实现新版内容/权限差异与明确更新切换。个人安装器、追溯隐私、可信 Skill 归属、三系统三平台综合验收及 LAN 仍未完成；持续目标 active，未提交、推送、发布或重启用户服务。

## M31：固定候选的更新内容与权限比较（2026-09-11，UX-010 增量）

- [ADR-045](adr/0045-skill-update-review.md)、compare/comparison 两份 v1 合同及管理 POST update-comparison 已落盘。请求固定原成功安装的操作签名与候选 Grant 版本；候选须签名有效、同平台/实例、期限有效，准入对应完整导入副本。允许未批准候选作审阅，旧批准不迁移；比较不批准、不续权、不创建移除声明或平台文件。
- 原签名清单与候选完整清单比较新增、缺失、文件/目录类型、摘要、字节数和执行位；不拿用户修改后的目标替换基线。权限规则去除 ID/证据来源后比较资源、效果、条件、状态，重复相同规则去重，另列默认效果、执行模式、有效期与工具策略变化；不自动判断宽窄。内容/规则各最多展示 200 项并保留完整计数/截断标识。
- 结束前重验新候选及双方 Grant 版本/签名、期限与移除状态。测试覆盖未批准候选、原源损坏和当前目标修改、候选内容替换、计算期间撤权、错误主体/版本、过期/拒绝/无效签名、旧权限变化、已移除与取消；也覆盖只读性、管理/决策凭据分权、正文严格性、no-store、文件类型/执行位和规则条件/执行模式差异。
- Go 全量/vet/gofmt、skillinstall/server race、142 项 Python 合同、增量 lint 与四目标交叉构建通过。Go 实际输出生成两份规范化合同样例，Python 校验内嵌 Grant、计划与操作签名及相互引用；样例的安装声明签名为不透明固定引用，不冒充真实安装声明证据。[验证记录](evidence/personal-experience/skill-update-comparison-20260911/verification.json)绑定本批源码、日志与候选。M31 未改前端，不声称新增浏览器或原生平台验收。
- 下一步准备绑定旧安装的新副本，接通明确更新确认、撤旧权、排他切换和异常恢复，再整合差异界面与远端检查。UX-010 仍 doing，完整个人及 LAN 目标 active；未提交、推送、发布或重启用户服务。

## M32：保留旧版本的更新准备与读取（2026-09-11，UX-010 增量）

- [ADR-046](adr/0046-skill-update-preparation.md)与 stage-create/plan/plan-created 三份 v1 合同已落盘。管理 POST 创建、GET 复验签名更新计划；请求固定原操作、双方 Grant 版本、原绑定和操作者。只允许已批准的新权限与完整来源；复制前后重查旧目标归属、新来源及两份权限，读取也重新校验，准备不撤权、不移除旧版本、不签发身份。
- 更新副本和计划独立存于 update-stages/update-plans，普通安装接口不能消费。复用受限复制底层，保持源与暂存文件独立；复制 API 拒绝外部目录及错误命名空间。相同 request ID 复用原签名与 5 分钟期限，改变范围/操作者拒绝；64 份暂存和 128 项计划枚举边界已验证。绑定另一安装的旧权限保留，并固定保留关联。
- 两个真实子进程退出点覆盖复制后和计划发布后。重启时未发布副本保留并拒绝隐式接管；已发布计划可重新核验及幂等重试，不续期。旧安装及旧 Grant 均保留。测试还覆盖目标/来源/暂存变化、未批准、版本/绑定/操作者错误、取消、检查末尾撤权、签名损坏、过期、管理/决策凭据分权、严格正文、no-store 与私有复制范围。
- Go 全量/vet/gofmt、skillimport/skillinstall/server race、145 项 Python 合同、增量 lint 和四目标交叉构建通过。Python 校验 Go 样例的更新 ID、计划签名、新 Grant 批准后的签名和来源/原安装引用。[最终候选的既有 Hermes 原生回归](evidence/personal-experience/skill-update-preparation-20260911/native-removal.json) 17 项通过，含 10 条签名回执及 3 条未签名拒绝；它验证共享复制函数变化未破坏安装/运行/移除链路，不代表已执行更新切换。[验证记录](evidence/personal-experience/skill-update-preparation-20260911/verification.json)绑定本批源码、制品与日志。
- 本批无前端变化，不宣称新增浏览器旅程或更新完成。下一步实现明确确认后的更新事务、撤旧权限、排他发布及中断恢复，再接通产品差异/确认界面。UX-010 与完整个人/LAN 目标继续 active；未提交、推送、发布或重启用户服务。

## M33：明确更新事务、恢复与管理 API（2026-09-11，UX-010 增量）

- [ADR-047](adr/0047-confirmed-skill-update-transaction.md)及 commit/recover/claim/result/view 五份 v1 合同已落盘。首次提交完整复验原更新计划并签名排他发布声明，固定新安装计划与原五分钟期限；同一旧安装不能同时开始两个更新。先复验新副本，再按原范围撤旧权限/清理旧目标，最后发布新版；复用既有安装/移除的归属、安全写入和审计，不自动激活新权限或签发身份。
- 新普通安装计划只在原移除完成后发布；签名更新声明另作为持久保留记录，普通 apply 不能重新执行该计划，包括更新终止后。终态记录引用实际移除与安装签名，读取表示历史事实，不以当前路径后来出现的内容替换历史。成功安装后最终响应丢失，即使计划过期也仅补记原成功结果，不续期或重装。
- 明确恢复固定原声明签名和操作者：尚未开始移除可终止且保留旧版本；已开始则完成撤权与归属清理，失败新副本只恢复可证归属内容。未知用户文件保留，测试由夹具操作者明确移出后再重试；不复活旧 Grant，不自动重新安装。容量、篡改、取消、过期、错签名/操作者、重复请求、同路径后续文件与历史结果均有负向检查。
- 管理 POST updates、GET updates/{sup-id}、POST updates/{sup-id}/recover 已接通。无身份/决策凭据分别拒绝，严格请求及路径/正文一致，读取 no-store；写出错只返回稳定错误，另行 GET 查询实际持久进度。API 测试覆盖正常确认、重试、成功后的恢复、容量失败后的查询/终止及普通安装重放拒绝。
- 六个真实子进程退出点覆盖更新声明、移除声明、旧副本移除后、新计划发布后、新引用文件发布后及更新最终结果前；重启后继续或明确清理均验证。Go 全量/vet/gofmt、skillinstall/server race、150 项 Python 合同、相关 lint 和四目标交叉构建通过。Go 规范化样例与 Python 校验声明、新计划及结果签名和引用，不冒充真实平台记录。
- 同一候选的 [既有 Hermes 原生回归](evidence/personal-experience/skill-update-transaction-20260911/native-removal.json) 17 项通过，包含 10 条签名回执及 3 条未签名拒绝；它验证原安装/运行/移除链路，没有执行新更新旅程。本批无 Web 改动，沿用 M30 嵌入页面。[源码/制品/证据清单](evidence/personal-experience/skill-update-transaction-20260911/verification.json)绑定本批。
- 下一步接通更新差异、明确确认、响应丢失查询和恢复 UI，再验证真实 Hermes 更新旅程。远端自动新版检查、三系统/三平台、可信 Skill 归属、安装器、任务追溯/隐私及 LAN 仍未完成；完整目标保持 active，未提交、推送、发布或重启用户服务。

## M34：个人版更新审阅、确认与恢复界面（2026-09-11，UX-010/012 增量）

- 个人版从已安装记录进入 `/skill-updates`，选择同实例独立导入授权，展示原签名基线与候选的内容、权限规则和设置变化。未批准候选只可审阅；批准后重新比较才能准备。准备与确认分离，初次准备保留本次匹配的审阅结果；刷新先 GET 原事务，尚无事务才复验计划，再要求人工重新核对差异。
- 新客户端验证比较/计划/声明/结果的字段、实例、来源、版本、签名引用和状态关系，不宣称前端密码学验签。勾选后才提交，使用同步请求锁拒绝双击；响应丢失只 GET 查询，查询失败撤下执行状态并保留原深链。恢复另行勾选，重用原声明和操作者；完成只展示历史，并链接新版安装结果与单独实例权限准备。
- [最终更新浏览器验证](evidence/personal-experience/skill-update-ui-20260911/browser/result.json) 7 项通过：未批准审阅、准备刷新不写入、桌面/移动确认、提交与查询同时丢失、单次提交后恢复成功、完成历史与权限链接、容量失败后的明确终止。标签关联问题已修复；人工检查 [桌面](evidence/personal-experience/skill-update-ui-20260911/browser/review-desktop.png)与 [移动确认](evidence/personal-experience/skill-update-ui-20260911/browser/confirm-mobile.png)，修正移动复选框排版及页顶标题后重新构建和验证。
- [原移除浏览器回归](evidence/personal-experience/skill-update-ui-20260911/removal-browser/result.json) 10 项通过。首轮在关闭后复查期间重开窗口失败，测试显式等待内容区 aria-busy=false 和按钮可用后重跑通过，未取消原功能断言。[既有 Hermes 原生回归](evidence/personal-experience/skill-update-ui-20260911/native-removal.json) 17 项通过，10 条签名回执与 3 条未签名撤权后拒绝。原生回归不代表执行过新更新旅程。
- 47 项 Web 测试、个人/企业构建、Go 全量/vet/gofmt、相关脚本 lint 与四目标交叉构建通过。[源码/制品/证据清单](evidence/personal-experience/skill-update-ui-20260911/verification.json)绑定最终候选；合同无变化，本批未重复运行 Python 合同及 Go race，M33 历史证据保留。
- 下一步验证真实 Hermes 更新后旧会话撤权与新版本显式启用，再补充远端新版检查及更新历史入口。三系统/三平台、可信 Skill 归属、任务追溯/隐私、安装器与 LAN 仍未完成。持续目标 active，未提交、推送、发布或重启用户服务。

## M35：状态目录健康绑定与误复用拒绝（2026-09-12，UX-003/004 增量）

- 先更新规格 §3.11 和独立 `local-service-instance-health.v1` 合同，复用现有 Go state/server/CLI 与开发启动器。保留旧健康接口及管理/决策分权。
- 新接口返回启动时固定的规范化目录摘要；CLI 只读核对后才输出 ready 或发起配对。不同目录、缺失身份、旧协议、HTML、重定向与异常响应均不复用。目录别名可匹配，不输出目录原文；摘要不是认证或永久设备 ID。
- [验证记录](evidence/personal-experience/instance-health-20260912.md)：Go 全量、vet、相关 race、合同及启动器 157 项检查、Ruff、四目标构建通过。隔离 Linux arm64 真实二进制完成启动、重复复用、别名复用、错目录拒绝、正确目录配对；测试创建的子进程已回收，没有重启用户服务。
- 本批未改变 UI/适配器，不重复记为浏览器或真实智能体平台验收；Windows/macOS 仍仅交叉编译。接下来补安装初始化、稳定实例身份和用户级后台生命周期，再推进任务书 §11.2 其余任务。整体目标保持 active。

## M36：客户端初始化与稳定实例记录（2026-09-12，UX-003 增量）

- 增加 `init [--port N]` 和 `local-client-initialization.v1` 合同；先回写规格 §3.11.1，复用 state 的单写者与排他发布，不增加第三方依赖。默认 block 配置、稳定随机实例 ID 均仅在缺失时创建；已有配置字节、额外字段和原 ID 保留。初始化不发授权、不扫描或接入平台、不启动服务、不生成管理/决策凭据。
- 64 KiB 文件预算、普通文件和严格实例版本/字段校验；损坏/null/超限/符号链接均拒绝，不覆盖错误文件。显式端口与既有配置冲突拒绝；Writer 的目录、PID 与 nonce 均复验，活跃锁和释放后的句柄不能写入。部分元数据存在时重试只补缺失文件。
- 裸 `serve` 提示先运行 `init`，不先产生状态目录/密钥。开发启动器确认端口空闲后初始化，再启动；匹配的运行实例直接复用。失败不启动新 daemon；重复调用不改变实例身份。
- [验证与制品](evidence/personal-experience/initialization-20260912.md)：Go 全量/vet、state/server/CLI race、153 项合同、8 项启动器检查、Ruff 及四目标构建通过。真实 Linux arm64 从空目录启动、运行中初始化拒绝、停止重启保留身份、两个子进程并发初始化均通过；测试进程已回收。部分元数据恢复为文件故障夹具，未冒充断电恢复实测。
- 安装包校验/分发、系统用户级后台注册、升级/卸载、Windows/macOS 原生运行仍待实施或验证；稳定本地 ID 不是可信团队设备身份。下一批继续 ADR-050 的系统生命周期方案与可运行入口。整体目标 active，无提交、推送、发布或用户服务重启。

## M37：原生单命令启动入口（UX-003）

- 新增 `start [--port N]`，复用初始化和 serve，普通用户不需要 Python 启动脚本。默认读配置端口，首次初始化默认 block；匹配实例只读返回既有健康合同。其他目录、错误服务、无效参数、端口冲突和活跃 writer 均拒绝，不终止已有进程或删除锁。
- 新启动为前台服务，终端输出沿用 serve 的配对流程；已有服务复用不换配对码，可另行 pair。没有后台保活、系统注册、浏览器自动打开或安装包交付声明。
- 验证与边界见 [M37 原生启动验证](evidence/personal-experience/native-start-20260912.md)。保留工作区 M35/M36 增量。后续继续用户级后台注册与可恢复卸载；完整目标保持 active。

## M38：停止时排空请求并保留写锁（UX-003）

- 修复原 serve 在监听退出后先返回、Shutdown 尚在其他 goroutine 排空请求的窗口。停止后拒绝新业务请求，等待既有 HTTP handler 完成才退出；连接宽限期结束会取消连接，但不以此推定状态写入结束。退出前取消并等待定时刷新，撤销信号注册。
- 先更新规格 §3.11.3；新增停止/排空测试覆盖新请求 503、不进入业务层、连接关闭后 handler 仍未结束时不能返回、无请求正常停止。没有更改授权、回执或数据合同。
- Go 全量、vet、相关 race、停止专项 race ×10、Linux 原生启动器 9 项及四目标构建通过，见 [M38 验证](evidence/personal-experience/stop-drain-20260912.md)。实际宿主运行、系统后台注册与其他 OS 原生停止仍待验收。完整目标 active。

## M39：Linux 用户服务配置导出（UX-003）

- 已新增 `service-unit`，只读已初始化状态并固定当前可执行文件和目录。配置使用 serve 主进程、私有 umask、显式停止期限，关闭 stdout/stderr 防止配对码进入 journal。路径中百分号/引号/空格正确转义，非法控制字符与有替换歧义的二进制路径拒绝。其他 OS 明确拒绝执行 Linux 导出。
- Go 全量/vet、CLI race、四目标构建通过；Linux 实际二进制导出含空格/百分号目录的配置，经 `systemd-analyze --user verify` exit 0。未注册或启动任何系统服务，没有修改用户已有配置。
- [M39 验证](evidence/personal-experience/service-unit-20260912.md)记录候选与构建；下一步在此基础上实现独立安装记录、归属检查、显式启停与失败恢复，随后补跨 OS 后台路径。配置导出不计为后台安装完成，完整目标保持 active。

## M40：Linux 用户服务真实运行与路径边界修复

- 新增 opt-in `test_systemd_user_service.py`，测试生成随机单位并仅 runtime link，真实执行 start、重复 start、restart、pair、stop、disable 和 reload；验证 MainPID、健康、身份/配置保留、writer 释放及链接清除。
- 实测发现 systemd 拒绝双引号可执行路径，导出提前拒绝该路径及反斜杠；状态目录中的引号、美元符号和百分号仍正常处理。首轮 FragmentPath 返回运行时链接而非源路径，测试改为解析并核对目标身份，原临时链接已清除。
- Go 全量/vet/CLI race、四目标构建、Ruff 及最终候选原生 systemd 测试通过。[M40 验证](evidence/personal-experience/systemd-native-20260912.md)记录候选与失败修复。无残留测试单位、无登录自启或生产服务改动。下一步仍为产品自动安装归属、失败恢复和卸载；完整个人/LAN 目标 active。

## M41：用户服务配置归属与中断恢复（UX-003）

- 新增 `service-prepare` 与 `local-user-service-record.v1` 合同；单写者下先发布签名意图，再排他发布实例专属 unit。重复执行复验实例、目录、配置摘要与签名；缺失文件可恢复，未知文件及漂移拒绝覆盖。
- Go 全量/vet/race、154 项 Python 合同、Ruff、四目标构建和 Linux 实际 CLI 验证通过，见 [M41 证据](evidence/personal-experience/service-prepare-20260912.md)。没有调用 systemd 或改变用户服务。
- 该记录只表示配置发布意图；系统注册/启停/升级迁移/卸载仍待接入。跨 OS 原生证据与完整个人/LAN 目标保持未完成，持续目标 active。

## M42：产品 Linux 用户服务注册（UX-003）

- 新增 `service-register [--runtime]`，共享签名配置准备并持锁完成 manager 归属检查、link、reload 与读回。拒绝未知单位/drop-in/范围变化，不启动服务或开启登录自启；失败可复验重试。
- Go 全量/vet/race、四目标构建及 Linux 实际产品命令注册/重复注册/范围冲突拒绝、随后系统启停清理通过。[M42 证据](evidence/personal-experience/service-register-20260912.md)区分 runtime 原生测试与未实测持久路径。
- 下一步接入产品服务启停、状态、卸载与迁移。完整任务书目标 active，本批未提交或推送。

## M43：产品服务启停与只读状态（UX-003）

- 新增 service-start、service-status、service-stop --confirm-stop，复验签名配置、manager 归属与真实 API 就绪。只读查询不生成身份/修复文件，停止需显式确认并核对主锁释放。
- 分离生命周期操作锁与 daemon Writer，避免运行时停止被主锁阻塞。Go 全量/vet/race、四目标构建和真实 Linux 产品启停/确认拒绝/状态/清理通过，见 [M43 证据](evidence/personal-experience/service-control-20260912.md)。
- 继续产品卸载、升级迁移及个人任务书其余项目；不将 Linux CLI 增量计为完整安装器或跨 OS 验收。完整目标 active。

## M44：产品服务注销与数据保留（UX-003）

- 新增 `service-unregister --confirm-unregister`，要求停止并核验签名配置与系统归属，仅删除同名注册链接；保留状态与未知别名。链接删除后中断可重载复验，重复注销可用。
- Go 全量/vet/CLI race、四目标构建和 Linux 实际完整注册/启停/注销旅程通过；运行中注销拒绝、注销后关键文件字节不变，见 [M44 证据](evidence/personal-experience/service-unregister-20260912.md)。
- 应用升级、完整卸载/安装交付和跨 OS 生命周期继续待办；不是完成全部 UX-003。完整目标 active，未提交/推送。

## M45：复用发行清单的原生候选暂存（UX-003/014）

- 新增 `client-stage --manifest FILE --binary FILE`；内置发行根验签、平台唯一 pin、限流摘要校验、私有独立版本目录排他发布。候选不执行，不切换服务；主 daemon 运行时仍可准备。
- Go 全量/vet/相关 race、四目标构建及 Linux unsigned 清单拒绝验证通过；正向为包内开发签名夹具，不冒充发行验收，见 [M45 证据](evidence/personal-experience/client-stage-20260912.md)。
- 下一步继续状态兼容及升级停止/恢复事务，完整安装交付/跨 OS 原生验收仍未完成。目标 active，无提交/推送/发布。

## M46：发行签名兼容声明与原生升级预检（UX-003/014）

- 独立 skill-manifest.v2 签入精确状态格式族/服务协议/无迁移声明，旧 v1 合同与发布快照保留。新增 client-upgrade-check，只读验证来源、兼容声明和候选 pin；v1 只能暂存，不能通过升级预检。
- Go 全量/vet/相关 race、155 项 Python 合同、独立跨语言验签、Ruff 与四目标构建通过，见 [M46 证据](evidence/personal-experience/client-compatibility-20260912.md)。没有正式发行签名新制品或真实切换声明。
- 继续升级停止/切换/恢复事务与完整个人目标；兼容声明不能冒充旧写者隔离，完整目标 active。

## M47：配置切换日志与部分写入恢复（UX-003/014）

- 新增签名 local-service-switch.v1 和 state 成对切换事务；日志/pending/完成标记与源/目标绑定，未知内容不覆盖，恢复只完成已签名目标。serve 在主 Writer 下检查 pending 并拒绝不一致启动。
- Go 全量/vet/state/CLI race、156 项 Python 合同、Ruff、四目标构建和实际 Linux pending 启动拒绝通过，见 [M47 证据](evidence/personal-experience/service-switch-20260912.md)。故障为文件阶段夹具，不冒充断电验收。
- 下一步将该事务与发行验签、manager 停止/reload/启动健康组合为产品升级命令；本批没有开放任意 unit 写入入口。完整目标 active。

## M48：Linux 产品升级命令与前滚恢复（UX-003/014）

- PR #28 已合并到 main `69d9c59`，新分支恢复升级草稿并接入 service-upgrade：先验签/暂存，再停止、事务切换、重载、目标启动和版本/目录健康确认；失败保留 ID，同目标恢复及已运行复用可用。
- Go 全量/vet/race、四目标构建、真实 Linux 配置/进程切换与开发发行者拒绝通过，见 [M48 证据](evidence/personal-experience/service-upgrade-20260912.md)。原生正向使用同构建路径副本，不冒充跨发行版本验收。
- 下一步继续失败回退与跨 OS/安装交付边界，其他个人任务及 LAN 原目标保留。本批未提交或推送，完整目标 active。

## M49：修复候选启动失败后无法恢复（UX-003/014）

- 回归证明原 Result=success 条件阻断 failed/MainPID=0 的候选恢复；修复为同事务下先验证无 manager 主进程，再由主 Writer 校验写入归属。正常停止口径不放宽，未知 PID/过渡状态/活跃锁拒绝。
- Go 全量/vet/race、四目标构建及两项真实 Linux 正常切换/端口冲突失败后恢复通过，见 [M49 证据](evidence/personal-experience/upgrade-failed-start-20260912.md)。没有扩大为跨发行版本支持声明。
- 继续失败回退与安装交付、跨 OS 验收；完整目标 active。

## M50：显式源配置回退（UX-003/014）

- 新增 service-rollback，验证旧候选发行声明及原事务源配置绑定，复用切换事务恢复原服务配置；失败候选无主进程时可处理，未知目标不操作，授权台账不回滚。
- Go 全量/vet/race、四目标构建、两项真实 Linux 切换/故障恢复后回退通过，见 [M50 证据](evidence/personal-experience/service-rollback-20260912.md)。保留历史构建摘要缺失和原路径要求的边界，不声明正式跨版本验收完成。
- 下一步补齐旧制品留存与安装交付，跨 OS/其他个人项目/LAN 目标保留，整体 active。

## M51：升级前保留本地程序副本（UX-003/014）

- 初次升级停止服务前复制当前 CLI 可执行文件至独立摘要目录，限流/源二次一致性校验/私有排他发布；恢复已有事务不重新取旧版本。副本不成为可信发行制品。
- Go 全量/vet/race、四目标构建、实际测试程序副本及源删除后保留/漂移拒绝验证通过，见 [M51 证据](evidence/personal-experience/client-snapshot-20260912.md)。
- 下一步将原程序摘要绑定签名历史并实现原路径恢复，避免把本地副本误作完整历史回退能力；整体目标 active。

## 未关闭的验证限制

- `desktop-same-uid` 不构成恶意同 UID 隔离。恢复凭据不改善该残余风险，也不应扩大到网络管理入口。
- Vite 开发代理的 Origin 映射已做正负向测试；正式 embed 的会话旅程已实测。完整 Vite + 新 daemon 浏览器联合验证仍待补充，后端白名单没有扩大。
- 当前签名 Skill 的脚本参与内容哈希；旧包保持可验证。新后台启动入口先在开发工具中实现，待 UX-014 新制品发布准备时整合，不在旧清单上冒用签名。
- 原文记录仍维持关闭，待独立设计后实现；不直接修改既有脱敏审计。
- 任务书的完整目标保持进行中；本机可完成的实现持续推进，外部验证缺口保持明确状态。

## M52：程序摘要签名切换合同（UX-003/014 仍未闭环）

- 增加 local-service-switch/v2 和 PrepareServiceSwitchWithBinaries，源/目标摘要纳入规范化签名；v1 原签名与历史日志保持兼容，不补写虚构历史身份。
- v2 创建、读取、重复应用与摘要篡改负向通过；Go 固定样例由 Python 校验合同/签名，157 项合同通过，四目标交叉构建通过。
- [本批证据](evidence/personal-experience/service-switch-binary-bindings-20260912.md)。CLI 仍写 v1，下一步接入实际程序摘要核对、v2 写入与回退历史摘要绑定。本批不计作升级回退完整验收。

## M53：升级/回退命令接通历史程序摘要（UX-003/014）

- 新升级写 v2，持锁停止前、事务准备前和 start 前核对内容；回退候选必须匹配原 source 摘要，反向日志保留交换绑定。旧 v1 只保留前滚恢复能力，产品回退拒绝无历史摘要的日志。
- 源/目标同路径替换、停止后漂移和恢复改绑定负向通过；损坏新程序回退正向通过。Go 全量/vet、CLI/clientrelease race、四目标构建及两项隔离 Linux systemd 原生升级/恢复/回退通过。
- [M53 证据](evidence/personal-experience/service-binary-identity-20260912.md)。同构建双路径测试不代表正式跨版本升级；原路径缺失恢复、安装器与跨 OS 验收仍待完成。

## M54：明确恢复缺失的历史程序（UX-003/014）

- 回退增加 --restore-missing-binary，原路径/历史摘要/发行清单双重验证后，在生命周期锁内排他恢复缺失程序；已有内容、符号链接、缺失父目录均拒绝覆盖/创建。
- Go 全量/vet、CLI/clientrelease race、四目标构建通过；隔离 Linux systemd 故障恢复后删除旧程序，再从合成测试快照恢复并回退启动通过。
- [证据](evidence/personal-experience/service-snapshot-restore-20260912.md)。测试 pin 不是发行信任，尚未正式跨版本验收；后续继续发行清单留存与安装交付。

## M55：回退复用发行清单与源材料留存（UX-003/014）

- 回退可省略 --manifest，从原摘要对应的本机目录有界查找并重新验签唯一兼容清单；多个匹配不猜测，无匹配要求提供。新升级可用 --source-manifest 保存首次源发行材料。
- 唯一选择、v1 不可升级、测试发行根拒绝、清单/程序漂移、符号链接、枚举预算与多清单歧义测试通过；Go 全量/vet/race、四目标构建通过。
- [M55 证据](evidence/personal-experience/retained-release-manifest-20260912.md)。没有新原生或正式跨发行版本证据。下一步整合安装与首次启动入口，个人生命周期仍未完成。

## M56：首次后台启动整合入口（UX-003/004）

- 新 setup --confirm-setup 合并初始化、用户服务注册、启动健康检查；支持初始端口和 runtime 注册。重复调用签名/健康/manager/scope 核对后复用，不重启或改配置。成功显示管理 URL 与独立配对提示。
- Go 全量/vet/race、四目标构建通过；完整 Linux CLI 的隔离首次 setup、重复同 PID/同配置和错误 scope 拒绝实测通过。
- [证据](evidence/personal-experience/setup-entry-20260912.md)。尚非安装包，不自动登录自启/打开浏览器，Windows/macOS 后台入口仍待完成。

## M57：打开本机管理页面（UX-003/004/012）

- 新 ui / ui --print 先验证当前实例健康再打开或输出管理 URL；setup --open-ui 复用入口。固定 loopback 地址不带凭据、不自动配对，浏览器失败可手动访问。
- Go 全量/vet/race、四目标构建通过；隔离真实 Linux 服务与 CLI 的 ui --print 通过。浏览器调用采用测试回调，未计为三系统桌面原生证据。
- [证据](evidence/personal-experience/local-ui-entry-20260912.md)。安装包、登录自启、Windows/macOS 后台仍待完成。

## M58：稳定路径客户端安装入口（UX-003/014）

- 新 client-install 串联发行/v2 校验、Stage 留存、稳定路径二次校验、子进程 setup 和运行版本/目录/服务归属复验，明确确认后执行，不修改 PATH/自启/智能体权限。
- Go 全量/vet/race、四目标构建通过；无确认/无效候选拒绝且不创建状态，准备阶段多种漂移/失败拒绝、子进程状态目录固定测试通过。
- [证据](evidence/personal-experience/client-install-entry-20260912.md)。尚无正式发行候选完成安装正向验证，不将测试回调或既有 setup 原生结果计为完整安装验收。

## M59：用户登录自启入口（UX-003）

- service-login --enable --confirm-enable / --disable 精确管理当前已签名实例的 default.target.wants 链接，保留未知对象，不重启/停止服务。生命周期校验支持 enabled scope 且复核链接；注销先关闭自启。
- Go 全量/vet/race、四目标构建、链接恢复/未知对象负向通过；隔离 Linux runtime 完整 CLI 启用/状态/重复 setup/关闭均保持同 PID 和配置。
- [证据](evidence/personal-experience/service-login-startup-20260912.md)。真实退出登录后再登录未验收；Windows/macOS 自启与后台仍待完成。

## M60：后台退出与重装复用（UX-003）

- teardown --confirm-teardown 统一关闭自启、正常停止、精确注销，持生命周期锁及最终主 Writer，保留程序/配置/身份/历史。已退出可复用，中断注销支持只读回恢复。
- Go 全量/vet/race、四目标构建通过；负向覆盖未确认、外来 source、活动 Writer；删除注册后 reload 故障恢复测试通过。隔离 Linux 完整 setup/自启/teardown/重复/再次 setup 链通过。
- [证据](evidence/personal-experience/teardown-entry-20260912.md)。并非清除数据或卸载平台钩子，正式跨 OS 安装验收保持待办。

## M61：macOS LaunchAgent 配置基础（UX-003）

- 新 launch-agent-plist 只读导出当前实例配置，标签/argv/状态目录绑定，XML 正确转义，不隐式 RunAtLoad/KeepAlive。复用 Linux 原配置预检，不更改其模板语义。
- Go/Python plist 样例交叉解析、路径与 ID 负向通过；Go 全量/vet/race、158 项合同及四目标构建通过。共用代码提取后 Linux 完整生命周期回归通过。
- [证据](evidence/personal-experience/launch-agent-plist-20260912.md)。仅配置导出，macOS 注册/启动/恢复与真实运行证据尚未完成，下一步推进专属签名归属和发布。

## M62：macOS 签名配置准备（UX-003）

- 新 local-launch-agent-record/v1 与 launch-agent-prepare，绑定实例/目录/label/plist 摘要，先签名意图后排他发布。重复准备和缺失文件恢复可复验，未知内容/漂移/克隆目录/签名篡改拒绝。
- Go 全量/vet、state/CLI race、159 项 Python 合同/签名/样例检查及四目标构建通过。
- [证据](evidence/personal-experience/launch-agent-ownership-20260912.md)。只有状态目录内准备，未注册到 Library/LaunchAgents 或运行 launchctl；macOS 原生验收保持待办。

## M63：macOS 用户目录配置注册发布（UX-003）

- launch-agent-register 在签名准备和双锁内向 Library/LaunchAgents 排他发布精确实例源链接，重复复验，不覆盖未知文件/异目标/相对别名，不跟随两级目录重定向。
- Go 全量/vet/race、四目标构建、隔离临时 home 正负向文件层测试通过。
- [证据](evidence/personal-experience/launch-agent-registration-20260912.md)。尚未调用 launchctl 或进行 macOS 实机加载/启动；下一步补用户域加载与同 label 归属读回。

## M64：macOS 已加载配置只读核对（UX-003）

- 新 launch-agent-status 使用 manageruid/managername 和 list -x XML，验证当前 GUI 用户域、全部签名源字段与有限运行元数据；有正 PID 才继续目录 API 健康检查。解析有大小/深度/节点预算，拒绝重复字段与额外配置。
- Go 全量/vet/race、四目标构建与模拟查询/解析正负向通过。[证据](evidence/personal-experience/launch-agent-loaded-status-20260912.md)。
- 兼容入口依据 Apple 历史开源实现，当前 macOS 支持情况未实测，失败不当作任务不存在；尚未实现 bootstrap/kickstart 或原生启动验收。

## M65：macOS 区分未加载与查询未确认（UX-003）

- launch-agent-status 接通当前 GUI 域完整任务枚举：精确标签缺席才报告已注册但未加载；存在则继续 XML 归属和健康核对。拒绝截断/重复/污染输出，查询间消失保持错误，不推断不存在。
- Go 全量/vet/CLI race、四目标构建通过；24 项列表解析及 9 项查询流程场景覆盖正负向与输出预算边界。[证据](evidence/personal-experience/launch-agent-presence-20260912.md)。
- 没有 macOS 实机，不声明兼容验收；加载、启动、退出和恢复仍待实施。本批只读，不改变系统任务；目标保持进行中，M48–M65 尚未提交合并。

## M66：macOS 显式加载与配置读回（UX-003）

- 新 launch-agent-load --confirm-load：要求既有签名源和精确注册链接，在生命周期锁与当前 GUI 域状态复验后加载单个实例。重复已加载任务不占主 Writer、不重启；缺席加载持主 Writer，成功后核对完整 XML，失败保留现场。
- Go 全量/vet/CLI race、四目标构建通过；12 个模拟加载场景和确认参数负向通过。[证据](evidence/personal-experience/launch-agent-load-20260912.md)。
- 没有真实 macOS 加载证据；本命令未请求启动，后续 kickstart、健康、退出和恢复仍待实现/验收。目标保持进行中，未提交或合并远端。

## M67：macOS 显式启动与当前批次合入准备（UX-003）

- 新 launch-agent-start --confirm-start，复用加载和生命周期锁、签名/链接/XML 归属，释放主 Writer 后只对未报告 PID 的任务 kickstart；已有进程不重启，正 PID 与目录 API 健康一致才成功。
- Go 全量/vet、CLI/state/clientrelease race、159 项 Python 合同、Ruff 和四目标构建通过。8 项启动场景及确认参数负向通过。[证据](evidence/personal-experience/launch-agent-start-20260912.md)。
- macOS 实机、退出/恢复及其他个人任务仍待完成。用户要求先将已开发内容提交并合入 main，本轮按此授权收拢 M48–M67，不扩展到其他窗口的独立远端 PR。

## M68：macOS 停止与退出复验（UX-003）

- 新 launch-agent-stop --confirm-stop，当前 GUI 域/签名源/精确注册链接/完整 XML 归属核对后，仅对正 PID 实例发 stop。保留配置，主动停止须无 PID、正常退出状态和 Writer 可用才成功；缺席与已闲置状态不编造退出事实。
- Go 全量/vet/CLI race、四目标构建通过；10 项模拟停止场景及确认参数负向覆盖成功、复用、异配置、失联、异常退出、超时与锁冲突。[证据](evidence/personal-experience/launch-agent-stop-20260912.md)。
- 没有 macOS 实机，不将测试计为原生停止/排空验收。退出后系统注销、恢复整合及 Windows 生命周期仍待完成。PR #31 保持原提交，后继开发不修改其待批准内容。

## M69：macOS 配置注销与重复恢复（UX-003）

- 新 launch-agent-unregister --confirm-unregister：完整归属核对、无 PID 且双锁下复验后 bootout 精确实例；完整枚举确认缺席后才移除精确用户注册链接。源配置/密钥/历史保留；运行进程、未知文件、链接缺失但仍加载均拒绝。
- Go 全量/vet/CLI race、四目标构建通过；12 项模拟注销/恢复场景及确认参数负向通过。[证据](evidence/personal-experience/launch-agent-unregister-20260912.md)。
- 当前无 macOS 实机，仍不标原生注销/重装通过。后续整合 macOS setup/teardown 与运行恢复，再推进 Windows 生命周期；PR #31 未更改，个人/LAN 目标保持进行中。

## M70：macOS setup 与首次入口整合（UX-003）

- setup 在 macOS 先验证 GUI 用户域，再串联 init/注册/加载启动/目录健康；健康实例复用，显式端口冲突拒绝。阶段失败停止后续调用，浏览器仅在最终健康后打开，--runtime 保留 Linux 专属语义。
- Go 全量/vet/CLI race、四目标构建通过；11 项模拟编排场景通过。最终候选 Linux setup/复用/ui/自启管理/teardown 原生隔离回归通过（2.84 秒）。[证据](evidence/personal-experience/setup-macos-20260912.md)。
- Mac 编排测试不代替 GUI 用户域/系统目录/launchctl 原生旅程；macOS teardown 整合、安装制品、跨 OS 实机与 Windows 生命周期继续待办。未修改 PR #31，后继增量本地保留。

## M71：macOS teardown 编排与数据保留（UX-003）

- teardown 在 macOS 持同一生命周期锁串联正常停止和精确注销；停止失败不卸载，注销中断可重复恢复，已移除链接走缺席复验而不重新注册。pending 配置切换拒绝。
- Go 全量/vet/CLI race、四目标构建通过；8 项带真实临时状态/签名/链接的模拟集成场景验证阶段顺序、Writer 释放与原状态逐字节保留。最终 Linux 原生 setup/teardown 回归通过（2.92 秒）。[证据](evidence/personal-experience/teardown-macos-20260912.md)。
- macOS setup→退出→重新使用已有编排实现，仍缺实机证据；不能标 UX-003 完成。后续优先 Windows 用户级后台生命周期，再补正式制品与真实平台验收。PR #31 保持不变，本地后继增量未提交。

## M72：Windows 后台前置——serve 显式目录绑定（UX-003）

- serve --state-dir 直接绑定本次服务的 Store/Writer/密钥/健康目录，优先环境变量但不修改环境；空值/相对路径/非规范/符号链接/不存在目录和多余位置参数在写入前拒绝。
- Go 全量/vet/CLI race、四目标构建通过；真实 Linux 子进程在环境指向另一不存在目录时，按显式实例成功健康并正常退出，另一目录未创建（0.07 秒）。[证据](evidence/personal-experience/serve-explicit-directory-20260912.md)。
- 这是 Windows Task Scheduler Exec 的必要前置，不是 Windows 生命周期已完成；下一步任务 XML、用户身份与归属配置。后继增量仍本地未提交，PR #31 不变。

## M73：Windows 用户任务 XML 导出（UX-003）

- 新 task-xml 只读导出当前用户 SID/实例 ID/程序/显式目录绑定的 Task Scheduler 1.3 配置；InteractiveToken、LeastPrivilege、无触发器、拒绝强制终止，参数不经 shell 或环境展开。
- Go 全量/vet/CLI race、160 项 Python 合同/样例及 Ruff、四目标构建通过。共用 XML 检查身份、Exec、设置与转义；路径/SID/实例和长度边界负向通过。[证据](evidence/personal-experience/windows-task-xml-20260912.md)。
- 尚未注册/启动计划任务，没有 Windows 实机证据；下一步签名任务归属与配置准备，再系统读回/注册/启停。未改变 PR #31，本批仍本地未提交。

## M74：Windows 任务签名归属与准备恢复（UX-003）

- 新 `task-prepare` 与 `local-windows-task-record/v1`，绑定 SID/实例/目录/任务名/XML 摘要；持双锁先签名意图后排他发布 XML，允许原签名内容缺失恢复，拒绝未知文件、漂移、克隆和签名篡改。
- Go 全量/vet/CLI 与状态 race、161 项 Python 合同及 Ruff、四目标构建通过；续开发时重跑 Windows 定向和合同测试、重新核对构建摘要。[证据](evidence/personal-experience/windows-task-ownership-20260912.md)。
- 尚无 Windows 系统注册/原生运行证据。下一步只读任务查询与完整配置核对，再推进注册/启停；UX-003 与整体目标保持进行中。README 中英文已同步个人入口、分支/发行差异及真实支持边界。

## M75：Windows 任务配置读回核对核心（UX-003）

- 新增完整 XML 结构核对，拒绝身份、参数、权限与设置变化及未知字段；有限额严格解析，允许不改变配置语义的格式与顺序差异。
- Go 全量/vet/CLI race、四目标构建通过；补充命名空间/编码与三类限额边界后，Windows 定向测试通过。[证据](evidence/personal-experience/windows-task-readback-20260912.md)。
- 尚未接入系统查询/CLI，不能将模拟 XML 输入计为 Windows 任务实际读回。下一步接系统查询传输、编码与失败分类，再注册/启停；UX-003 保持进行中。
- 中英文 README 已单独推送文档分支 `codex/readme-personal-status-20260912`（`b6f186d`），功能增量仍留本地。

## M76：Windows 系统任务只读查询（UX-003）

- `task-query` 已接入 CLI：系统目录定位 schtasks、精确任务只读查询、有界输出/超时、严格 UTF-8/UTF-16 转换、完整配置与查询后本地签名复验。失败不推断缺席，不产生成功输出。
- Windows 定向、Go 全量/vet/CLI race 与四目标构建通过；六项临时状态/签名模拟查询及编码正负向通过。[证据](evidence/personal-experience/windows-task-query-20260912.md)。
- 未执行真实 Windows 系统查询；配置兼容与原生验收保持待办。下一步任务缺席判定、排他注册、启停与健康闭环，不改变远端 PR 或其他窗口工作。

## M77：Windows 定点存在性查询（UX-003）

- `task-presence` 使用固定系统 PowerShell/COM 查询，限定 GetTask 的文件不存在错误分支；当前 SID、本地签名、存在时完整配置与最终源复验串联，失败不推断缺席。
- 七项模拟编排、内部响应负向及编码向量通过；Go 全量/vet/race、四目标构建通过。[证据](evidence/personal-experience/windows-task-presence-20260912.md)。
- 当前没有 Windows 或 pwsh，脚本未原生解析/运行，不计为 Windows 支持验收。下一步排他 TASK_CREATE 注册和读回；存在性观察不能授权覆盖。所有功能增量继续本地保留。

## M78：Windows 用户任务排他注册（UX-003）

- `task-register --confirm-register` 接通双锁准备、归属/存在性查询、TASK_CREATE 创建与独立配置读回；已有匹配仅复用，竞争失败不覆盖，不自动启动或清理现场。
- 九项模拟编排和确认负向、Go 全量/vet/race、四目标构建通过。[证据](evidence/personal-experience/windows-task-registration-20260912.md)。
- PowerShell/COM 注册未原生验证，账户/ACL/序列化/真实竞争与恢复旅程保持待办。下一步 Windows 按需启动、健康和正常退出，再注销与 setup/teardown 编排；UX-003 不提升为完成。

## M79：Windows 按需启动与目录健康（UX-003）

- `task-start --confirm-start` 接通生命周期锁、完整归属复验、Writer 可用检查与释放、Run(null)、健康轮询与最终配置复验；健康实例复用，失败保留任务与状态。
- 八项模拟编排、确认和任务动作模板路径负向、Go 全量/vet/race 与四目标构建通过。[证据](evidence/personal-experience/windows-task-start-20260912.md)。
- 没有原生 Windows/PowerShell 执行证据；成功输出不声称任务引擎 PID 等于服务 PID。下一步正常退出、运行状态与注销，再 setup/teardown，UX-003 保持 doing。

## M80：Windows 运行状态读回（UX-003）

- `task-runtime` 接通当前用户任务 State、可见实例数和上次结果，完整归属前后复验；严格解析并拒绝明显矛盾快照，不把历史返回码当本次退出证明。
- 六项模拟读回与协议边界、Go 全量/vet/race、四目标构建通过。[证据](evidence/personal-experience/windows-task-runtime-20260912.md)。
- 现有 serve 正常退出依赖信号，Windows 后台还需本次运行绑定的退出请求，再核对 Writer/任务与退出结果；PowerShell/COM 原生旅程仍待验收，UX-003 不提升为完成。

## M81：当前运行绑定的退出授权核心（UX-003）

- 新 localcontrol 挑战/stop 签名域、随机 boot_id、目录/30 秒时限、单次接受状态机；必要记录回调失败不消费，16 并发只接受一次。
- Go 全量/vet/控制与 CLI race、163 项 Python 合同/Ruff、四目标全包编译通过。[证据](evidence/personal-experience/service-stop-authority-20260912.md)。
- 核心尚未接入 HTTP/CLI，不是退出功能已完成。下一步接受记录、受限本机端点与现有排空流程，再 Windows 停止/注销闭环；不提升原生验收状态。

## M82：退出请求接受记录（UX-003）

- 新签名接受记录绑定完整请求摘要、boot/目录和首次时间，持主 Writer 排他发布；同请求幂等，跨目录复制、冲突与未知文件拒绝。
- Go 全量/vet/控制与状态 race、164 项合同/Ruff、四目标全包构建通过。[证据](evidence/personal-experience/service-stop-acceptance-20260912.md)。
- 尚未接入 HTTP/CLI，仅接受记录落盘能力，不代表服务已退出。下一步服务端验签、记录成功后通知排空，再核对退出结果与 Writer；UX-003 保持 doing。

## M83：本机退出 HTTP 与排空联动（UX-003）

- 服务端 challenge/stop、严格请求边界、签名接受与主 Writer 记录联动；只有记录成功才通知既有排空流程，202 不冒充退出完成。
- HTTP 安全/记录失败重试测试、Go 全量/vet/server 与 CLI race、四目标构建通过。隔离 Linux 最终候选真实 HTTP 退出、记录留存与 Writer 释放验证通过（0.104 秒）。[证据](evidence/personal-experience/service-stop-http-20260912.md)。
- 仍缺停止 CLI、Windows task-stop/注销和原生后台验证；下一步客户端验签、请求与最终退出确认。UX-003 不提升为完成，未修改远端。

## M84：本机签名退出请求 CLI（UX-003）

- `stop-request --confirm-stop` 接通目录健康、挑战验签、签署退出请求及响应/本地接受记录核对；响应丢失时核验原请求记录，不重发，输出仅表示接受。
- 六项 HTTP 模拟与响应/确认边界、Go 全量/vet/race、四目标构建通过。隔离 Linux 真实 CLI 及 HTTP 两条停止路径正常退出、记录留存和 Writer 释放通过（合计 0.197 秒）。[证据](evidence/personal-experience/service-stop-request-cli-20260912.md)。
- 下一步排空结果记录与最终停止确认、Windows 任务停止/注销；当前请求 CLI 不承诺完成退出，跨 OS 原生验收不提升。

## M85：本次排空结果与后台收尾（UX-003）

- 新签名排空结果绑定接受记录，待 HTTP/刷新/运行检查收尾后持 Writer 排他写入；超时保留失败且继续等待后台结束，不能提前释放 Writer。
- Go 全量/vet/控制/状态/CLI race、165 项合同/Ruff、四目标构建通过；隔离 Linux 两条真实退出旅程新增结果核验通过（0.219 秒）。[证据](evidence/personal-experience/service-stop-result-20260912.md)。
- 下一步停止完成客户端将结果与 Writer/Windows 任务状态结合；drained 不单独证明进程退出，跨 OS 原生验收保持待办。

## M86：停止完成确认与恢复 CLI（UX-003）

- `stop --confirm-stop` 结合本次签名结果与 Writer，持锁复验后完成；`--recover` 只核对原接受记录，不发送新请求，超时保留恢复身份。
- 六项完成状态/确认负向、Go 全量/vet/race、四目标构建通过。隔离 Linux 三条真实退出及停机后完整恢复 CLI 通过（0.415 秒）。[证据](evidence/personal-experience/service-stop-completion-cli-20260912.md)。
- Windows task-stop 需继续任务运行状态前后复验、注销及 setup/teardown；跨 OS 原生验收未提升，UX-003 保持 doing。

## M87：Windows 任务正常停止编排（UX-003）

已接 task-stop --confirm-stop：运行时要求本次签名 drained、写锁释放和任务 ready/零返回码；原本空闲只确认空闲，不借历史结果宣称本次退出。排队拒绝，最终持主锁复验配置、运行状态及退出记录。10 项模拟场景、确认参数负向、Go 全量/vet/CLI race 和四目标构建通过。Windows 原生停止未验收，注销与 setup/teardown 继续待开发。

证据：[windows-task-stop-20260912.md](evidence/personal-experience/windows-task-stop-20260912.md)。功能仍本地未提交。

## M88：Windows 任务注销（UX-003）

已接 task-unregister --confirm-unregister，双锁与签名归属、完整配置、空闲状态校验后删除精确任务并读回缺席。保留本地配置和数据；已缺席幂等，查询/删除失败不伪报成功。10 项模拟场景、参数负向、Go 全量/vet/race 与四目标构建通过。固定 PowerShell 删除脚本未在 Windows 解析或执行；条件删除非事务的并发边界已登记。下一步 setup/teardown；UX-003 仍未完成。

证据：[windows-task-unregister-20260912.md](evidence/personal-experience/windows-task-unregister-20260912.md)。功能仅本地落盘。

## M89：Windows 一步初始化（UX-003）

setup 已复用用户后台阶段编排，新增 Windows 当前用户 Task Scheduler 只读预检，再串联初始化、注册、启动和最终健康。健康实例复用仍核对任务归属；--runtime 拒绝，浏览器按需打开。Windows/macOS 各 11 项模拟编排、Go 全量/vet/race 与四目标构建通过；Windows 原生 COM/浏览器未验收。下一步 teardown。

证据：[setup-windows-20260912.md](evidence/personal-experience/setup-windows-20260912.md)。本批未提交或推送。

## M90：Windows 保留数据退出（UX-003）

teardown 已接 Windows 正常停止和注销，生命周期锁贯穿两阶段，停止未确认不会注销；已缺席可幂等恢复，主 Writer 忙拒绝。7 项模拟场景覆盖空闲、已缺席、查询失败、停止失败、删除响应丢失恢复及两类锁忙，验证重复调用、删除次数和锁释放。Go 全量/vet/race、四目标构建通过。Windows 原生完整生命周期仍缺，UX-003 不标完成。

证据：[teardown-windows-20260912.md](evidence/personal-experience/teardown-windows-20260912.md)。功能继续本地保留。

M90 补充：teardown 已增加运行成功与排空失败的串联测试，累计 9 项。用真实签名状态记录和 Writer 验证停止完成先于注销；排空失败禁止删除。联合定向 race 通过，系统任务仍为模拟回调，不增加原生支持范围。

## M91：任务活动聚合核心（UX-011）

已在 receipt 复用链校验报告实现只读聚合，以链/平台/会话/主体/任务/意图/意图摘要为复合键；缺少绑定保留未归属，前缀验签失败不产可信分组。只返回原快照索引，不新增参数持久化，不从 allow 推导结果核验。尚未接用户 API、详情、可信 Skill 版本与效果证据，UX-011 仅进入 doing。

证据：[task-activity-projection-20260912.md](evidence/personal-experience/task-activity-projection-20260912.md)。

## M92：任务结果核验的主体隔离（UX-011）

新增内部 EvaluateForSubject，先验签候选证据、拒绝重复/矛盾引用，经可信历史行动按平台、会话、主体、任务与意图版本筛选，再复用 completion.Evaluate。其他分组成功证据不补足本组缺失；不改变已有 API 范围。10 项范围测试覆盖匹配、跨平台/会话/主体/意图/摘要、行动引用错误、篡改、重复和空主体。任务 API/页面及 Skill 版本仍待接入。

证据：[task-completion-subject-20260912.md](evidence/personal-experience/task-completion-subject-20260912.md)。

## M93：任务活动列表 API（UX-011）

新增管理鉴权 /v1/task-activities，tasks/unassigned 双视图，稳定活动身份及快照分页。Engine 锁内限额读取并核对链头，校验失败/超限不返回部分可信列表；独立输出前缀、历史完整性和新鲜度。新增版本合同及 Go API 固定样例，166 项 Python 合同、Ruff、Go 全量/vet/定向 race 和四目标全包构建通过。结果证据详情、Skill 版本与前端仍待接入。

证据：[task-activities-api-20260912.md](evidence/personal-experience/task-activities-api-20260912.md)。功能仅本地落盘。

## M94：个人任务活动页面（UX-011/012）

新增 /activities 和任务活动导航，保留回执入口，任务/未归属双视图、快照分页与 URL 状态恢复。响应按请求范围验证，取消旧请求并隐藏过时内容，错误不伪装为空列表。Web 49 项测试、企业和本地构建通过；隔离 Linux Go embed + Chromium 完成真实配对/空列表及模拟内容、未知归属、刷新、快照失效、读取错误验证，桌面/移动截图已检查。任务详情、结果证据和 Skill 版本继续待开发。

证据：[task-activities-ui-20260912.md](evidence/personal-experience/task-activities-ui-20260912.md)。

## M95：任务活动详情回执 API（UX-011）

新增活动详情 API 与版本合同，按活动身份和快照分页，只返回该组回执的裁决/工具/授权引用等摘要。交错会话隔离、未归属详情、鉴权、未知活动、错误视图及快照冲突测试通过；参数原文和摘录不进入响应。Go 全量/vet/定向 race、167 项合同/Ruff 和四目标全包构建通过。前端详情与结果核验联动仍待完成。

证据：[task-activity-detail-api-20260912.md](evidence/personal-experience/task-activity-detail-api-20260912.md)。

## M96：个人任务活动详情页面（UX-011/012）

列表已可进入 /activities/:id，展示本组回执的裁决、工具、原因与授权引用，支持分页、快照、刷新和返回列表。响应核对活动 ID/范围、回执主体/会话/平台、序号和参数字段，错误隐藏旧内容。50 项 Web 测试、企业/本地构建及隔离 embed 浏览器旅程通过，桌面和移动详情截图已检查。实际结果核验及 Skill 版本仍待接入。

证据：[task-activity-detail-ui-20260912.md](evidence/personal-experience/task-activity-detail-ui-20260912.md)。

## M97：活动范围结果核验 API（UX-011）

新增 /v1/task-activities/:id/completion 与合同，按活动绑定读取签名意图和效果证据，复用完整主体范围核验；结果返回前复验链快照。未知归属/缺少意图返回明确原因和空结果，无要求保持 unknown。真实文件观测覆盖 verified/conflicting，Go 全量/vet/定向 race、168 项合同/Ruff 和四目标构建通过。前端结果展示与 Skill 版本仍待接入。

证据：[task-activity-completion-api-20260912.md](evidence/personal-experience/task-activity-completion-api-20260912.md)。

## M98：活动详情实际效果核验展示（UX-011）

前端独立结果面板已接同活动/快照的 completion API，展示要求、状态、证据引用及核验时间。验证完整绑定、非空 verified 证据与无冲突，不从放行推导实际效果。52 项 Web 测试、两种构建和 embed 浏览器旅程通过；效果接口失败移除旧成功结论并保留回执详情。浏览器效果内容是明确 fixture，真实材料核验见 M97。Skill 版本与导出仍待开发。

证据：[task-activity-completion-ui-20260912.md](evidence/personal-experience/task-activity-completion-ui-20260912.md)。

## M99：效果证据元数据详情（UX-011）

核验面板已可按需查看证据，复用现有服务端验签接口，核对证据 ID/任务后仅展示元数据；不展示原始文件/网络材料，不从单份 completed 推导任务完成。54 项 Web 测试、两种构建与 embed 浏览器验证通过，包括无点击不请求、来源可见、失败提示与关闭焦点返回。Skill 版本与脱敏导出仍待完成。

证据：[effect-evidence-detail-ui-20260912.md](evidence/personal-experience/effect-evidence-detail-ui-20260912.md)。

## M100：单活动脱敏导出核心（UX-011）

新增内部导出投影，完整验签后按七字段绑定选择，限额不足拒绝部分输出。标识/工具用摘要，原因与参数不复制，非法时间和裁决不透传。交错会话隔离、隐私、预算、缺失活动和组外篡改测试通过；Go 全量/vet、导出 race 和四目标全包构建通过。尚未接下载合同/API、独立签名封装与前端入口，不计为完整导出功能。

证据：[task-activity-export-core-20260912.md](evidence/personal-experience/task-activity-export-core-20260912.md)。

## M101：单活动签名下载 API（UX-011）

新增 local-task-activity-export/v1 合同和管理下载 API，强制指定快照、整组脱敏、10000 行上限与签名后快照复验。独立签名只证明摘要投影，不复制原回执签名或声称效果完成。跨会话隔离、敏感文本、鉴权、签名篡改、过期快照及磁盘回执篡改测试通过；固定 Go 样例由 Python 校验合同并验签。170 项 Python 测试、Ruff、Go 全量/vet/定向 race 与四目标全包构建通过。前端下载入口、结果材料和 Skill 版本仍待开发。

证据：[task-activity-export-api-20260912.md](evidence/personal-experience/task-activity-export-api-20260912.md)。本批仅本地落盘。

## M102：个人活动摘要下载入口（UX-011/012）

已归属活动详情可下载整组脱敏回执摘要，按活动/快照校验白名单、行数和顺序后保存签名文档。提供超限/冲突/错误提示，详情变化取消旧请求。56 项 Web 测试及企业/本地构建通过；隔离 Go embed 浏览器验证真实配对和模拟导出下载、文件名/内容及快照冲突，桌面/移动截图已检查。浏览器只做格式校验；服务端签名与跨语言验签证据见 M101。效果材料、Skill 版本及筛选仍待推进。

证据：[task-activity-export-ui-20260912.md](evidence/personal-experience/task-activity-export-ui-20260912.md)。

## M103：历史授权来源关联核心（UX-011）

新增 intent 内部历史 GrantReference 读取，按完整回执主体/任务/意图/Authority revision 与 matched Grant 对齐签名 Binding 和 Intent，不查询当前 Grant、不恢复权限。缺少选择或关联错误保持不可用；绑定撤销后历史仍可读，运行时依然拒绝。该关联只证明授权来源，尚不能证明具体 Skill 实际执行版本；后续继续核验历史准入/安装内容及接 API/UI。

证据：[task-activity-historical-grant-20260912.md](evidence/personal-experience/task-activity-historical-grant-20260912.md)。

## M104：历史 Skill 内容来源核验核心（UX-011）

在历史 GrantReference 基础上只读选中准入，验证 ID/签名与内容摘要；普通准入保留 content_hash，导入准入另核对规范来源，分别输出 artifact_digest 与 analysis_sha256。声明版本缺失保持未知，名称/版本限长并拒绝控制字符；不返回路径/原文，不查询当前 Grant 或安装文件。尚未接服务端查询/UI，不能把历史授权来源当成实际 Skill 执行证明。

证据：[task-activity-historical-skill-20260912.md](evidence/personal-experience/task-activity-historical-skill-20260912.md)。

## M105：历史准入受限磁盘读取（UX-011）

新增独立历史读取入口，复用既有文件身份/8 MiB 读取限制；检查 admissions 目录身份和链接，严格解析文档并核对 ID。缺失保持明确错误，不初始化或修改状态。限额恰好边界与超限、文件/目录链接、异常类型、未知字段、错误 ID 与尾随内容已验证。历史查询 API 将组合此入口与 M103/M104 签名核验，不改变既有 GetAdmission。

证据：[task-activity-historical-admission-read-20260912.md](evidence/personal-experience/task-activity-historical-admission-read-20260912.md)。

## M106：活动历史 Skill 来源查询 API（UX-011）

新增管理 sources API 与 local-task-activity-sources/v1 合同，按活动快照分页关联历史 Binding/Intent/准入。明确 verified_source/unavailable/unattributed，缺失/篡改不返回可信元数据；缓存同关联键，每请求最多 8 个不同键。签名撤销不抹去历史来源，查询不恢复权限。定向验证正常版本/摘要、跨会话分页、缺失/篡改/撤销、鉴权、快照及预算边界；前端来源展示待接。

证据：[task-activity-sources-api-20260912.md](evidence/personal-experience/task-activity-sources-api-20260912.md)。

## M107：个人活动历史 Skill 来源面板（UX-011/012）

活动详情已可按需展开本页历史来源，展示声明版本、准入/制品/分析摘要并说明其与实际执行的区别。逐行核对回执 hash/seq/Grant，错误清除旧内容；刷新/分页/活动变化取消请求。59 项 Web 测试、企业/本地构建与隔离 embed 浏览器来源展示/读取失败验证通过，桌面和移动截图已检查。筛选检索、效果与来源导出，以及真实平台样例继续待完成。

证据：[task-activity-sources-ui-20260912.md](evidence/personal-experience/task-activity-sources-ui-20260912.md)。

## M108：全快照活动检索 API（UX-011）

新增管理 search API 与版本合同，支持平台/主体/会话/任务精确筛选及标识关键词，全部条件 AND。完整验签快照先筛选再分页，保留活动/源快照身份；未归属筛选不补造绑定。中文/大小写关键词、后续页命中、条件组合、参数边界/非法输入、鉴权、源快照失效与链损坏验证已补齐。前端筛选表单和状态恢复待接。

证据：[task-activity-search-api-20260912.md](evidence/personal-experience/task-activity-search-api-20260912.md)。

## M109：个人活动筛选与 URL 状态（UX-011/012）

任务活动页已接关键词和平台/主体/会话/任务筛选；草稿只在明确提交后请求，切换视图、翻页、刷新、进入详情和返回均保留条件及正确快照范围。筛选响应核对服务端条件回显，读取错误与无匹配结果分别展示。61 项 Web 测试、企业/本地构建和隔离 Go embed 浏览器旅程通过；桌面/移动筛选布局已检查。Skill/效果内容仍不进入关键词搜索，效果与来源的完整导出及真实平台样例继续待完成。

证据：[task-activity-search-ui-20260912.md](evidence/personal-experience/task-activity-search-ui-20260912.md)。

## M110：完整脱敏追溯包核心（UX-011/013）

新增 `local-task-trace-export/v1` 独立签名文档，将同一活动快照的回执摘要、逐回执历史 Skill 来源、任务范围效果结论和被结论实际引用的效果证据元数据组合为一份脱敏投影。构建前复验活动摘要签名、来源 seq/hash、完成结论主体和全部证据签名；缺失引用、重复材料、跨任务材料和虚假 verified 均拒绝签名。任务、Skill、授权、准入、要求和证据等原始标识仅输出摘要引用，原始参数、原因文本、观察材料与私钥不进入文档。来源不可用或结论未核验时明确 `incomplete=true`。

固定 Go 样例通过 Draft 7 合同和 Python Ed25519 互验；Python 合同测试、Ruff、Go 全量/vet/定向 race 与 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 四目标构建通过。签名范围仅为 `redacted_trace_projection_only`，不证明公钥自身可信、完整历史、当前权限、实际 Skill 执行或任务成功。服务端快照编排、下载 API 和前端入口继续待办。

证据：[task-trace-export-core-20260913.md](evidence/personal-experience/task-trace-export-core-20260913.md)。本批仅本地落盘。

## M111：完整追溯包下载 API（UX-011/013）

新增管理 `GET /v1/task-activities/{id}/trace-export`，要求已归属任务及明确回执快照。服务端从完整验签链投影回执，逐条解析历史 Skill 来源，按同一任务和主体范围计算完成结论，从签名存储读取效果记录后调用 M110 核心生成独立签名文档；调用方不能提交关联材料。响应前再次核对回执快照和效果记录 ID/签名集合，变化返回 409 且不附下载头。不同历史来源读取限为 8 个，超限返回 413；缺失历史来源保留 unavailable/incomplete。

接口验证覆盖管理鉴权、决策令牌越权、方法/参数/视图/活动/快照错误、来源隐私、来源缺失、签名验签、附件头和读取预算。Go 全量/vet、服务端定向 race、174 项 Python 合同/Ruff及四目标构建通过。当前没有前端下载入口或真实平台活动样例，不提升 UX-011 或跨系统验收状态。

证据：[task-trace-export-api-20260913.md](evidence/personal-experience/task-trace-export-api-20260913.md)。本批仅本地落盘。

## M112：完整追溯包前端入口（UX-011/012/013）

活动详情新增独立“下载完整脱敏追溯包”入口，与既有回执摘要下载明确区分。前端验证完整白名单、活动/快照、回执和来源关联、完成状态、incomplete 语义及证据引用集合，验证失败不保存；成功后显示材料完整性状态。界面明确浏览器仅检查格式与关联，签名仍需外部可信公钥验证。409、413 与通用错误分别提示，详情变化会卸载并取消旧请求。

新增 2 项固定 Go 样例前端验证，共 19 个文件、63 项 Vitest 通过；企业/个人构建通过。隔离 Go embed + Chromium 完成真实管理配对，并以明确 fixture 验证点击前无请求、完整包文件名/内容、incomplete 提示、快照冲突、导出区唯一节点及桌面/390 px 移动布局，无 page error。浏览器 fixture 不作为真实智能体平台或密码学验签证据。

证据：[task-trace-export-ui-20260913.md](evidence/personal-experience/task-trace-export-ui-20260913.md)。本批仅本地落盘。

## M113：默认关闭的独立加密原文仓（UX-013）

新增 `internal/rawcontent` 和 `local-raw-task-content-envelope/v1`。只读打开不会创建密钥或目录；显式初始化生成独立随机密钥，AES-256-GCM 以封套元数据为 AAD，任务仅保留摘要引用。结构化字段在加密前整项移除明确 secret、凭据字段名及内置凭据值形态；全部被移除、无法分类、重复/非法路径、控制字符、超限和预算不足均拒绝。默认保留 24 小时/64 MiB，配置范围 1 小时至 30 天、1 MiB 至 1 GiB，单条 1 MiB。

读取核对任务、期限、密文认证和明文摘要；用户删除及过期批量清理只触及独立密文目录。定向测试覆盖默认无副作用、磁盘无原文、跨任务、过期、AAD 篡改、密钥损坏、凭据过滤、清理不触碰模拟事实链及合同固定样例。Go 定向/race/vet与 175 项 Python 合同/Ruff通过；任务授权、采集 API/UI 尚未接入，因此默认运行行为仍是不采集原文。

证据：[raw-task-content-store-20260913.md](evidence/personal-experience/raw-task-content-store-20260913.md)。本批仅本地落盘。

## M114：逐任务原文采集授权与撤销核心（UX-013）

新增 `local-raw-task-content-grant/v1` 和 `local-raw-task-content-revocation/v1`，以本机 Ed25519 身份签名不可变授权及终态撤销。授权只保存任务/操作者摘要，固定内容种类、1 分钟至 24 小时采集窗口、1 小时至仓上限的密文保留期和单条上限；每次采集重新验签并检查任务、种类、窗口、大小及撤销。原 `Store.Write` 已收紧为包内方法，生产写入只能经授权入口；仅初始化仓不能采集。

撤销绑定完整授权签名并使用预期签名作 CAS，相同请求幂等，错误前置条件冲突；撤销与采集串行，返回后不能再写入，但不删除既有密文或更改事实链。定向测试覆盖默认无副作用、跨状态目录、跨任务、未授权种类、大小限制、未生效/过期、篡改、撤销幂等及撤销后既有密文可读。固定 Go Grant/Revocation 样例已通过 Python Draft 7 合同和独立 Ed25519 验签；管理 API/UI 尚未接入，默认仍不采集原文。

证据：[raw-task-content-authority-20260913.md](evidence/personal-experience/raw-task-content-authority-20260913.md)。本批仅本地落盘。

## M115：原文仓签名启用状态与管理 API（UX-013）

新增不可变 `local-raw-task-content-activation/v1`，签名绑定操作者摘要、启用时间、保留期、磁盘预算和独立加密密钥指纹，作为重启恢复限制的唯一事实源。只有密钥/目录的部分初始化保持 disabled；签名、字段或密钥绑定损坏显示 error 且不自动覆盖。相同限制重试返回原记录，不同限制冲突；启用本身不产生任务 Grant，默认采集始终为 false。

管理端新增 status 与 activation GET/POST，要求配对后的管理会话并拒绝决策凭据。启用正文严格拒绝缺失、null、重复、未知、尾随、非整数和越界；GET 每次从磁盘复验签名及密钥。定向测试覆盖默认读取无副作用、非法请求不初始化、首次/幂等/冲突、重启打开、错误签名身份、部分状态、磁盘篡改和错误状态不泄漏限制。固定 Go Activation、Activate 请求和 Status 样例已通过 Python 合同及 Ed25519 互验；前端及逐任务管理/采集 API 尚未接入。

证据：[raw-task-content-activation-api-20260913.md](evidence/personal-experience/raw-task-content-activation-api-20260913.md)。本批仅本地落盘。

## M116：逐任务 Grant/Revoke 管理 API（UX-013）

新增管理会话专用 Grant 集合、单项和撤销入口。创建严格绑定原始任务请求到磁盘任务摘要，固定内容种类、采集窗口、保留期和单条上限；响应及磁盘不回显任务/操作者。单项和集合使用 verified view 区分 active/expired/revoked，撤销携带签名墓碑；集合稳定排序且在任一授权/墓碑/Activation 异常时整体失败，不返回部分可信数据。

定向 HTTP 测试覆盖未启用、管理鉴权、决策凭据越权、严格请求、范围边界、创建、单项、列表、不存在、错误 CAS、撤销、幂等重试和磁盘隐私。新增 GrantCreate/Revoke/View/List 合同及固定 Go 样例，Python Draft 7 递归解析并与 M114 签名向量交叉验证。运行时采集正文接口仍未开放，管理会话和通用决策令牌均不构成采集凭据。

证据：[raw-task-content-grant-api-20260913.md](evidence/personal-experience/raw-task-content-grant-api-20260913.md)。本批仅本地落盘。

## M117：运行时会话绑定的短时原文采集许可与 API（UX-013）

新增不落盘的签名 `local-raw-task-content-capture-permit/v1`。许可最长 5 分钟，保存随机许可 ID、原文 Grant 及其完整签名，并只以 sha256 引用绑定 Runtime Identity、原生会话、签名 Binding 和服务端任务；实际期限由请求、Grant 和运行时会话最早到期点截断。签发与采集分别通过 `/v1/raw-task-content/capture-permits` 和 `/v1/raw-task-content/captures`，均要求同一实例凭据重新认证当前签名会话，管理会话、通用决策令牌、自检凭据及跨实例/会话/任务借用不能替代。

每次写入重新读取 Activation/密钥、许可、原文 Grant/撤销及运行时身份/Binding。采集正文只接受 path/value/secret 精确结构，递归拒绝重复/未知/null 字段，进入 AES-256-GCM 仓前整项移除 secret 与内置凭据模式；响应只返回密文记录元数据，不返回明文、nonce 或 ciphertext。Runtime Identity、会话/Intent/权限 Grant 或原文 Grant 任一撤销/到期均失败关闭，且不创建部分密文。

Go 全量/vet、rawcontent/runtimeidentity/server 定向 race、188 项 Python Draft 7 合同与独立 Ed25519 验签、Ruff及 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 四目标编译通过。接口尚未接入 Hermes/OpenClaw/WorkBuddy 原生适配器，不能据此声明真实平台已采集；原文清单、读取/删除和持续前端提示继续待办。

证据：[raw-task-content-runtime-capture-20260913.md](evidence/personal-experience/raw-task-content-runtime-capture-20260913.md)。本批仅本地落盘。

## M118：原文记录管理读取、删除与过期清理 API（UX-013）

新增管理会话专用的记录 search/read/delete 与 purge-expired 入口。清单使用请求正文中的任务 ID 计算摘要，响应只返回 active/expired 元数据；在返回前对整个有界内容目录逐条执行结构、密钥和 AES-GCM 认证，任何任务的记录损坏均整体失败，不返回部分列表。显式 read 只读取匹配任务且仍 active 的记录，响应标记 `contains_plaintext=true` 并返回已过滤的 path/value，不返回 nonce 或 ciphertext。

删除要求正文 task_id 与路径记录匹配，并以 confirm_record_id 精确确认；删除前同样完成 AEAD 认证。过期清理要求 `confirm_expired_only=true`，先认证所有记录，再删除达到半开到期边界的密文。两种删除均不写回原文 Grant、回执、效果证据或追溯包。缺失、过期、跨任务、篡改、严格正文和管理/决策鉴权已覆盖。

新增 Record、Records、Read Content、Delete 与 Purge 的九份合同和八份管理固定样例；Go 全量/vet、rawcontent/server 定向 race、196 项 Python Draft 7 合同/Ruff及四目标编译通过。明文管理 UI、持续开启提示、诊断包排除检查和原生适配器采集仍待完成。

证据：[raw-task-content-management-api-20260913.md](evidence/personal-experience/raw-task-content-management-api-20260913.md)。本批仅本地落盘。

## M119：原文仓持续状态与隐私设置界面（UX-012/013）

个人控制台顶栏已持续显示原文仓关闭、按任务授权启用、异常或不可用状态，并在 30 秒轮询、窗口重新聚焦和设置变更时刷新。设置页新增显式启用流程，可确认 1 小时至 30 天保留期、16 MiB 至 1 GiB 上限和当前人工身份；启用后展示服务端复验的固定 Activation 摘要，且明确默认采集仍关闭。

到期清理要求独立勾选确认，只删除达到期限的密文。前端对 Status、Activation 和 Purge 响应实施精确字段、数值范围与字段关系校验；无效响应撤下旧 ready 状态，浏览器不保存这些权限状态。隔离真实 daemon/Go embed 浏览器旅程验证新安装关闭、显式启用、顶栏即时同步、清理、刷新恢复、伪造默认采集响应失败关闭和移动端布局。

20 个 Web 测试文件共 66 项通过，个人/企业两种构建通过；Go 全量/vet、rawcontent/server/ui race、196 项合同/Ruff、四目标构建及 7 项浏览器检查通过。任务级 Grant/记录/明文管理 UI、自动清理、诊断包排除检查和原生平台采集继续待办。

证据：[raw-task-content-settings-ui-20260913.md](evidence/personal-experience/raw-task-content-settings-ui-20260913.md)。本批仅本地落盘。

## M120：任务详情原文授权与二次查看界面（UX-013）

有可信 Binding 的任务活动详情已增加原文面板；未归属活动不开放。创建 Grant 要求内容种类、有效期、受 Activation 限制的保留期、单条上限、人工身份和明确任务范围确认；active Grant 可使用当前签名经独立确认终态撤销。前端计算任务摘要并只展示匹配当前任务的授权和记录。

记录默认只显示元数据，选择 active 记录不会读取明文；用户二次勾选后才读取一次，响应必须精确匹配所选记录与任务，关闭/刷新/切换/失败均撤下 DOM 中的明文。删除要求完整 record_id 确认并在成功后重新读取清单。所有操作互斥，原文和授权不进浏览器存储、下载或剪贴板。

新增 4 项前端固定合同测试，Web 共 70 项；个人/企业构建、Go 全量/vet/race、196 项合同/Ruff、四目标构建通过。浏览器实际调用签名 Activation/Grant/Revoke，记录界面以固定合同替身验证 9 项二次动作及失败关闭。原生适配器采集、自动清理、诊断包排除和真实平台端到端仍待完成。

证据：[raw-task-content-task-ui-20260913.md](evidence/personal-experience/raw-task-content-task-ui-20260913.md)。本批仅本地落盘。

## M121：默认导出与原文仓隔离回归（UX-013）

CLI 全局导出、管理 HTTP 全局导出、任务回执摘要和完整脱敏追溯包已增加原文目录磁盘哨兵。测试在 `raw-task-content/content/` 放置唯一可识别内容，要求四种结构化白名单投影均不出现内容或目录标记，也不因无效原文文件而失败。

四项普通/race 定向测试、Go 全量和 vet 通过，格式与 diff 检查无输出。仓库目前没有通用诊断包；未来新增诊断、崩溃或日志收集入口时仍须增加独立排除测试。原生适配器采集、自动到期清理和真实平台原文端到端继续待办。

证据：[raw-task-content-export-isolation-20260913.md](evidence/personal-experience/raw-task-content-export-isolation-20260913.md)。本批仅本地落盘。

## M122：服务生命周期内的原文自动到期清理（UX-013）

`serve` 维护协程已接入原文仓 expired-only 清理：启动后立即执行，此后每 15 分钟执行，退出时随维护上下文取消并等待结束。禁用原文仓时不创建任何可选状态；启用后每次重新验证签名 Activation、独立密钥绑定和完整密文目录，再删除到期封套。

定向测试验证到期/未到期记录分离、Grant 与回执链不变、篡改时整次失败且默认健康入口继续可用；维护回调失败不会结束循环。Go 全量/vet、server/CLI 定向 race、gofmt/diff 检查及 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 四目标构建通过。原生适配器采集和三平台真实原文端到端继续待办。

证据：[raw-task-content-automatic-cleanup-20260913.md](evidence/personal-experience/raw-task-content-automatic-cleanup-20260913.md)。本批仅本地落盘。

## M123：Hermes 原文采集运行时桥（UX-013）

新增 Runtime Identity 专用 native-captures 协议。薄适配器只提交原生 session、实例和内容字段，服务端从签名 Binding 恢复任务，并只在任务/kind 唯一匹配 active Grant 时内部签发 10 秒许可后立即采集；无授权拒绝，重叠授权冲突，适配器不持有 task ID、Grant、许可或管理凭据。

Hermes 已管理插件在允许后采集参数、观察后采集结果，嵌套 JSON 展开为有界 JSON Pointer 字段供服务端 secret 过滤。250ms 辅助调用失败不改变裁决、结果或脱敏观察；旧全局凭据与产品自检不触发。105 项适配器测试、Go 全量/vet/race、合同总集/Ruff和四目标构建通过。真实 Hermes CLI 完整会话以及 OpenClaw/WorkBuddy 独立接入仍待完成。

证据：[hermes-raw-content-bridge-20260913.md](evidence/personal-experience/hermes-raw-content-bridge-20260913.md)。本批仅本地落盘。

## M124：真实 Hermes CLI 原生完整会话的原文采集端到端（UX-013）

补上 M123 遗留验证：以公开 `hermes chat --oneshot`（Hermes Agent v0.21.0，入口 sha256 4e623fce…）驱动真实 Agent 循环与插件生命周期，隔离 HOME/HERMES_HOME 由产品安装器配置托管 profile，合成模型仅作对话驱动。运行 `managed-instance-native-smoke.py`（含 M123 原文增量，脚本 sha256 8e586e70…），17 项检查全部通过。

核心结果：真实原生会话的签名 Binding 自动恢复任务，Grant 创建后的允许调用经 native-captures 产生恰好 2 条 parameters/output 密文记录，管理端读回明文与实际执行的路径及文件内容逐字段一致；Grant 之前的首个允许调用正确未采集（默认关闭负向证据）；产品自检用独立 Grant/Binding；撤销 Runtime Identity 后新会话 3 次调用全部产生未签名 deny，回执链 verify 通过（共 10 条签名回执）。Go 全量/vet、gofmt/diff 检查及四目标交叉编译通过。

登记边界：仅覆盖 Linux arm64 宿主上的 Hermes；macOS/Windows 实机、真实 LLM 供应商与浏览器原文面板为独立验证线。OpenClaw 尚无 Runtime Identity/managed 接入，WorkBuddy 仍缺公开阻断钩子与可用测试环境，不能借用 Hermes 结果提升支持。

证据：[hermes-native-e2e-raw-content-20260913.md](evidence/personal-experience/hermes-native-e2e-raw-content-20260913.md) 及同名 JSON 报告。本批仅本地落盘。

## M125：OpenClaw Runtime Identity 与 managed 接入（服务端/适配器安装层）

将 Runtime Identity 与托管安装计划从 Hermes 延伸到 OpenClaw：`supportedIdentityPlatforms` 封闭集合加入 openclaw，Record/Summary 携带平台字段并进入签名；Grant 以 `grant.Options{Platform:"openclaw"}` 平台锁定，enroll 经 `AuthorizeSessionContext` 一次读锁完成身份+绑定+平台校验；实例 ID 内容派生，服务端按 Hermes→OpenClaw 根目录探测解析平台，不信任客户端上报。

托管连接字段按宿主约定区分：Hermes snake_case 写 `plugins/siq-agent-security/config.json`，OpenClaw camelCase（`runtimeIdentityId`/`tokenPath`/`agentId`）写 `<root>/siq-agent-security.json`。计划钉定校验身份元数据平台一致（拒绝跨平台身份钉入），静默降级被 `ErrPlanChanged` 拒绝，卸载仍要求先撤销身份（tombstone）。`/v1/adapter/instances` OpenClaw 行顶层 `native_available:false`（原生捕获未验证前不申报），跨平台预览 409，安装后裁决面平台内 allow/valid、跨平台凭据 401，诊断四项 pass。

修复真实缺陷：`adapter_http.go` `validateManagedSelection` 硬编码 Hermes 平台导致 managed OpenClaw 经 HTTP 安装必然 409；已改为由计划视图透传平台。另修复 `skillinstall` 两处测试桩未跟随 `ResolveInstance` 签名扩展。

验证：`runtimeidentity`/`adapterinstall`/`server` 三层新增 OpenClaw 定向测试（含端到端 `TestOpenClawManagedInstallDecisionsAndRevocation`：预览/安装/字段断言/裁决/跨平台拒绝/诊断/卸载重放）全部通过；Go 全量/vet/gofmt/diff 检查、CGO_ENABLED=0 四目标构建（SHA256 见证据文档）、Python 合同 197 passed + Ruff 通过。OpenClaw 原生捕获与插件运行时桥为 M126 待办，`native_available` 保持 false；仅覆盖本机 Linux arm64 宿主。

证据：[openclaw-managed-runtime-identity-20260913.md](evidence/personal-experience/openclaw-managed-runtime-identity-20260913.md)。本批仅本地落盘。

## M126：OpenClaw 插件运行时托管桥（managed Runtime Identity + 原生原文捕获）

补上 M125 遗留的插件侧运行时行为（插件 v0.2.0 → v0.3.0），对齐 Hermes 托管桥合同：托管配置（camelCase `runtimeIdentityId`/`agentId`/`tokenPath`）下凭据必须匹配 `ri-<32hex>.<64hex>` 且拒绝符号链接/超长/旧全局 token；每次 `before_tool_call` 先经 `/v1/runtime-sessions` 注册并严格校验 8 字段响应（platform 必须 `openclaw`），失败在 block 模式 fail-closed 且不进入 decide；allow 后按 JSON pointer（≤32 层/≤256 路径/≤1024 字段/≤1MiB 单值）捕获参数、observe 带决策引用后捕获结果，POST `/v1/raw-task-content/native-captures`（期望 201，250ms best effort 预算，超界整体放弃）。非托管路径行为不变。

验证：新增 Node 场景测试（resolution hook 替换 SDK 入口 + mock 本地服务驱动真实 hook handler，8 场景：legacy 不注册不捕获、托管 allow 注册+参数捕获、注册失败/异平台/旧 token fail-closed、observe 引用+输出捕获、捕获超时 best effort、托管 deny 带回执）全部通过；Go 全量 36 包/vet/gofmt/diff 检查、CGO_ENABLED=0 四目标构建（SHA256 见证据文档）、Python 合同 197 passed + Ruff 通过。该测试不是真实 OpenClaw 网关验收，`native_available` 在实机原生捕获验证前保持 false；支持矩阵不因此标注 supported。

证据：[openclaw-managed-plugin-bridge-20260913.md](evidence/personal-experience/openclaw-managed-plugin-bridge-20260913.md)。本批仅本地落盘。

## M127：OpenClaw 托管接入真机原生冒烟（2026.5.12 实机 17 检查全过）

补上 M126 遗留的真机验收：以真实 OpenClaw 2026.5.12 公共 CLI（`openclaw agent --local`，真实插件 hook 生命周期，隔离 HOME，合成模型/工具夹具）驱动 `openclaw-managed-native-smoke.py`，17 项检查全部通过。覆盖：catalog 原生未验收仍报 `native_available:false`、managed 预览不动宿主、安装使用签发身份且资产与适配器源一致、原生会话自动 enroll、环境变量不能覆盖 managed agent、write 在执行前被拒、显式 Grant 后 parameters/output 各产生 1 条原文密文记录（明文经管理端读回逐字段一致，grant rawgrant-09b5…）、回执链 verify（3 条）、撤销身份后新原生调用全部被阻断。

真机发现并处理五项：(1) 安装器顶层写 `security.installPolicy`，OpenClaw 2026.5.12 严格校验判为 Unrecognized key 拒绝启动——记入 compat_finding，仅夹具移键规避，产品侧待改（`native_available` 保持 false）；(2) 产品缺陷已修复：插件把 `ctx.agentId` 当 `agent_id` 上报导致 managed 绑定 401 failClosed，新增 `reportedAgentId(ctx)` 托管恒用配置 agent；(3) 产品缺陷已修复：after_tool_call result 载体自带的 undefined 可枚举键（details/terminate）使 `rawContentFields` 遍历整体中止、输出捕获静默失败，改为跳过 undefined/function/symbol 叶子，新增回归场景；(4) 宿主回放转录时剥除 tool-call id 非字母数字并对重复 id 追加 8 位 hex 消歧，夹具三态配对；(5) 宿主每请求回放全量转录，role=tool 计数跨轮累计。

验证：插件 Node 场景套件 10/10（含新增 undefined-leaf 回归）；`go test ./internal/adapterinstall/`（资产一致性 `TestEmbeddedAssetsMatchRuntimeTree`：adapters/runtime 为规范源，插件改动必须同步 `adapterinstall/assets` go:embed 副本）；gofmt/diff 检查无输出；CGO_ENABLED=0 四目标构建（SHA256 见证据文档）；Python 合同 197 passed + Ruff 通过。

登记边界：仅覆盖 Linux arm64 宿主上的 OpenClaw 2026.5.12；`security.installPolicy` 兼容性解决前 `native_available` 维持 false，支持矩阵不因此标注 supported；无真实用户审批、Skill 归属、OS/网络隔离宣称。

证据：[openclaw-managed-native-smoke-20260913.md](evidence/personal-experience/openclaw-managed-native-smoke-20260913.md) 及 `/tmp/openclaw-managed-native-smoke-final.json`。本批仅本地落盘，未提交、未推送、未发布，未重启用户 daemon。

## M128：Skill 运行时归属与权限绑定（UX-007 核心批 / Q05）

> 后续审查修正：以下保留 M128 当时的实现记录。仅匹配调用方提供的 Skill ID/摘要/版本不足以证明执行来源，当前 Store 对精确匹配返回 unknown；不得只给适配器增加自报字段就开启 verified 强制门禁。详见 [修复证据](evidence/personal-experience/stage-review-fixes-20260913.md)。

将 Skill 权限从"授予时一次性绑定"推进到"运行时可验证绑定"。授予侧：admission.Admit 推导的 Skill 版本身份（`source:type:name@hash12` + version + 64hex content_hash）经 grant.Build 固化为 `Grant.Skill` 并纳入签名 canon；运行侧：`receipt.Request.Skill` 作为**不可信声明**，引擎经可插拔 `state.Store.SkillAttribution`（受信 grant 记录）裁决为 `verified|mismatch|unknown` 并签入 receipt 新增 `skill_attribution` 字段（verified 仅由 skill_id+content_hash+版本对受信状态精确匹配得出，模型自报永不视为 verified；unclaimed 调用该字段缺省）；决策侧：skill 范围 grant 仅在归属 verified 时可行使，伪造标识/切换版本/借用其他智能体身份/未声明 → 默认拒绝，reason_code `skill_attribution_mismatch`。

分阶段强制：新增 `SkillAttributionEnforced` 引擎选项与 `skill_attribution_enforcement` 配置（默认关）。直接无条件强制会拒绝所有真实 skill 派生 grant 的每次运行时调用（实测破坏 runtimecheck 探针与 server 流程），因平台适配器尚未附加运行时 Skill 声明。关闭期间声明仍被解析、裁决并签入 receipt（诚实遥测），但 skill 范围 grant 暂按基线行使；任何调用不因声明显示 verified，除非 lookup 确认。端到端强制依赖适配器侧运行时声明附加，记为后续批次前置工作。

测试：grant 层 3（身份进 grant/签名验证/缺身份基线 + skillRefOf 直接单测覆盖空 hash 空 ID）；receipt 层 10（verified 放行；unclaimed 拒绝且 receipt 无 skill_attribution；伪造未知身份拒绝；版本切换拒绝；跨智能体借用拒绝且记 unknown；基线 grant 不受声明影响；5 种畸形声明保持 unknown 且不回显损坏身份；nil lookup 全 unknown；lookup 返回非法状态值按拒绝；生命周期链归属随决策追加）；state 层 6（精确匹配；内容漂移/换版/缺 hash/缺 version mismatch；无关 Skill unknown；跨智能体/跨平台 unknown；过期/非 live unknown；基线 grant 永不 verified）。合同样本按机制再生 6 个（grant canon 新增 skill 字段导致签名/ID 连锁变化，逐个核对 diff 仅预期变化）；receipt/grant schema 新增字段（additionalProperties:false，verified 条件必填约束）。

验证：`go test ./...` 36 包 ok 0 失败；gofmt -l/git diff --check 无输出；go vet 通过；CGO_ENABLED=0 四目标构建（linux/amd64、linux/arm64、darwin/arm64、windows/amd64，SHA256 见证据文档）；Python 合同 197 passed + Ruff 通过。

登记边界：强制默认关（`skill_attribution_enforcement` 未开启前 skill 范围 grant 按基线行使）；UX-007 整体仍为 doing（场景模板、多 Skill 边界、跨 OS 行为未覆盖）；仅本地落盘，未提交、未推送、未发布，未重启用户 daemon。

证据：[skill-runtime-attribution-20260913.md](evidence/personal-experience/skill-runtime-attribution-20260913.md)。

## M129：场景模板与多 Skill 调用边界（UX-007 后半 / 2026-09-13）

范围：apps/agentshield、packages/contracts/grant.schema.json。

实现：
- 场景模板（UX-007）：`internal/grant/scenario.go` 封闭目录 3 个只减不加预设（no-network@1 移除网络；no-exec@1 移除进程执行与包安装；sandboxed@1 移除网络/执行/包安装/fs.write，仅留工具与模型 + 隐式只读）。`Build` 在派生任何投影前用 `ApplyScenario` 过滤 DeclaredFacts（hermes allowlist、OpenClaw 工具策略、网络/文件系统规则天然一致收缩）；模板身份 `ScenarioRef{ID,Version}` 签入 Grant；`Build` 失败关闭（目录外/版本不符 → `ErrScenarioInvalid`）；`Grant.Scenario` 为 omitempty，旧签名 grant 兼容，`DraftFrom` 自动保留场景。
- HTTP：`GET /v1/grant-scenarios`（只读目录，无敏感字段）；`POST /v1/grants` 接受 `scenario_id`，未知场景 400。
- 多 Skill 调用边界：state lookup 层每个 live Skill grant 按 skill_id+content_hash+版本独立精确匹配，混合身份（A 的 id + B 的 hash）mismatch；引擎层（enforcement on）live grant A 只服务归属 A 的调用，claim B 即使对 B verified 也不得经由 A 授权，拒绝码 `skill_attribution_mismatch`。
- 合约：grant.schema.json 新增可选 `scenario` 属性；签发样本零变更（omitempty，197 合同测试持平）。

测试：新增 11 个正负向测试（场景 7：no-network/no-exec/sandboxed 收缩正确、永不放宽超出准入、未知场景/目录外对象失败关闭、目录封闭恰 3 项、DraftFrom 保留场景；HTTP 2：目录只读无敏感字段+405、签发绑定与基线无 scenario 字段；多 Skill 2：lookup 层双 grant 精确匹配+混合身份 mismatch、引擎层跨 Skill 拒绝/匹配允许）。

诚实记录（宿主能力缺口，阻塞项复核）：适配器侧运行时 Skill claim 挂载确认阻塞于宿主钩子能力——OpenClaw 2026.5.12 `before_tool_call` 上下文仅 `{toolName, agentId, sessionKey, sessionId, runId, toolCallId}`（~/.openclaw/node_modules/openclaw/dist/reply-BCcP6j4h.js ~L33932）；Hermes `pre_tool_call` 仅 `(tool_name, args, task_id, session_id, tool_call_id, turn_id, api_request_id, middleware_trace)`（~/.hermes/hermes-agent/hermes_cli/plugins.py:6831）。两者均不暴露 Skill 身份，适配器无法提供可验证声明；M128 分阶段强制设计与本结论一致，宿主上游加入 skill 来源字段前保持阻塞，不伪造。

验证：`go test ./...` 全部 ok 0 失败；gofmt -l/git diff --check 无输出；go vet 通过；合约样本零变更；Python 合同 197 passed + Ruff 通过；CGO_ENABLED=0 四目标构建（linux/amd64、linux/arm64、darwin/arm64、windows/amd64，SHA256 见证据文档）。

登记边界：UX-007 整体仍为 doing（跨 OS 行为、适配器 claim 挂载[宿主能力阻塞]未闭环）；场景目录为封闭集合，新增属代码变更；同 agent 多 live Skill grant 并存策略留待 UX-009/010；仅本地落盘，未提交、未推送、未发布，未重启用户 daemon。

证据：[scenario-templates-multi-skill-20260913.md](evidence/personal-experience/scenario-templates-multi-skill-20260913.md)。

## M130：UX-008 后台启动器通知层（daemon 侧桌面通知 / 2026-09-13）

范围：apps/agentshield（internal/state、internal/notify[新包]、cmd/agentshield）。

实现：
- 配置（opt-in）：`desktop_notify`（默认关）、`desktop_notify_command`（平台默认通知器 override），均 omitempty，旧 config.json 零变化；校验在加载侧（decodeConfig 拒绝空白命令），`SaveConfig` 维持纯写盘语义（config.json 不承载安全决策）。
- `internal/notify`：`CommandNotifier`（argv 经 strings.Fields 切分、exec.CommandContext 直接执行、不经 shell、5s 超时）；`DefaultCommand`（仅 linux 且 notify-send 在 PATH；windows/darwin 报告不支持）；`Dispatcher`（轮询 5s、合并窗口 15s，对齐 M15/M16 节奏）——仅在 pending 数相对已报告值增加时投递，窗口内抑制但不吞增量，归零重置窗口，投递失败记日志且有界重试（不盖 lastNotify 戳），独立 goroutine，永不阻塞决策路径或确认收件箱。
- 隐私：通知体 count-only（`有 %d 项待确认操作，请在本地控制台处理`），不含工具名/action_id/session/agent 标识/参数摘要/grant 与 receipt 标识（桌面通知可被同机其他应用读取，与 ADR-032 同一隐私规则；泄漏面有逐项否定断言测试）。
- 接线：cmdServe 启动 `startDesktopNotify`（配置优先→平台默认→nil；不支持平台 + 无 override → nil notifier + 显式日志"收件箱完全可用"，绝不伪造投递）；`pendingConfirmations` 复用 `Engine.Confirmations()` 只读投影、只数 Status=="pending"。引擎热路径零改动。

测试：新增 14 个测试全部通过（notify 8：增量投递/窗口合并不吞增量/归零重置/失败重试/count-only 泄漏面否定断言/argv 无 shell/平台默认仅 linux+二进制/ctx 取消退出；cmd 6：配置 argv 覆盖/不支持平台 nil/默认关闭与无通知器不启动+如实日志/真实引擎 hold→计数 1→resolve 后归 0/空白命令加载拒绝+合法往返/pending 闭包绑定引擎计数）。1 项在本机按设计 SKIP（本机存在 notify-send）。

验证：`go test ./...` 全部 ok 0 失败；gofmt -l/git diff --check 无输出；go vet 通过；Python 合同 197 passed + Ruff 通过（M130 未触碰合同 schema/样例）；CGO_ENABLED=0 四目标构建（linux/amd64、linux/arm64、darwin/arm64、windows/amd64，SHA256 见证据文档）。

登记边界（诚实记录）：OS 实机投递未验收——调度/投递层已实现并以测试替身+真实引擎测试，但"桌面真实弹出"需实机证据，UX-008 三系统实机验收项保持未完成；windows/darwin 无平台默认通知器（osascript/Toast 未实现），仅可显式配置 `desktop_notify_command`；原生恢复执行仍阻塞于 Hermes 30s 回调上限（M16 已验证）；任务内授权（task-scoped authorization）留待后续批次；仅本地落盘，未提交、未推送、未发布，未重启用户 daemon。

证据：[desktop-notify-background-launcher-20260913.md](evidence/personal-experience/desktop-notify-background-launcher-20260913.md)。

## M131：UX-009 增量 —— Git 来源 Skill 导入（/v1/skill-imports/git / 2026-09-13）

范围：apps/agentshield（internal/skillimport、internal/server）。

实现：
- 新增 `POST /v1/skill-imports/git`（管理员能力，路由置于 `/v1/skill-imports/` 通配之前），合同 `local-skill-import-git-create/v1`：ImportID/URL/Ref/SubDir/ExpectedCommit(可选)/ActorID 全部必填键，严格平铺 JSON，槽位 TryLock 429，60s 上下文。
- URL 复用 https_zip 下载校验（https 公网主机、443/缺省、拒 userinfo/fragment/反斜杠/控制字符）；Ref 白名单正则 + 拒 ".."、尾 "/" "."、空/点开头/.lock 分量、40 位十六进制（提交固定用 ExpectedCommit）；SubDir 复用归档路径校验并拒 git 元数据路径。
- git CLI 硬编码：无 shell、净化环境（GIT_CONFIG_NOSYSTEM/空全局配置临时 HOME/GIT_TERMINAL_PROMPT=0/GIT_ASKPASS=echo/隔离 HOME+TMPDIR/LC_ALL=C）、`-c core.hooksPath=<空目录>`（恶意 Git 钩子在 clone/checkout 不执行）、fsmonitor=false、gc.auto=0、protocol.file.allow=never、GIT_ALLOW_PROTOCOL=https、`clone --depth 1 --single-branch` 后 `rev-parse --verify HEAD^{commit}`（stdout 模式校验 40 hex，stderr 刻意丢弃，远端文本不入日志/错误）。50s 克隆预算。
- 准入沿用既有管线：目录树限额（2000 文件/目录、深度 16、单文件 8MiB、总量 64MiB）、.git 元数据排除、准入后摘要复查（检查后替换拒绝）、ExpectedCommit 不匹配 → ErrArchiveMismatch；同 ImportID 不同参数 → ErrConflict；重复请求 reused/200。
- 记录 schema v2 新增 `git` 元数据（URL/Ref/SubDir/ExpectedCommit/CommitSHA）；recordVersionValid 三分支互斥（v1 与 https_zip 拒 git 字段，git 拒 remote 字段），gitValid 复验 URL 往返与 commit 40 hex。

测试：新增 6 个测试全部通过（store 5：真实 git fixture 端到端克隆含恶意 post-checkout 钩子不执行断言/Exec bit 保留/签名验证/Load 全链路/reused+conflict+wrong-pin+缺 SubDir 负向、SubDir 子树选择、23 例请求校验表、gitRefValid、记录校验与版本互斥；server 1：401/403 边界、私有主机 400 url_blocked、GET 405、严格体循环全 400 无错误回显、持锁 429、records 保持为空）。既有 zip/remote/skillimport 测试零回归。

诚实记录（边界）：测试经 `file://` 传输走真实硬编码克隆——`protocol.file.allow`/`GIT_ALLOW_PROTOCOL` 是测试缝参数，生产入口 fetchGitCLI 恒 https-only 且 file 传输 never；服务端测试无法注入未导出 gitFetch 缝，HTTP 层仅覆盖失败路径（与 remote 一致），正向 201 流程在 store 层覆盖。DNS 解绑残余风险：URL 校验在请求时解析主机名，克隆时实际连接未做 IP 钉扎。未在真实 git 托管服务联测，无 OS 实机验证；git 二进制缺失 → 503 skill_import_unavailable（本机 git 2.43.0）。UX-009 整体仍为 doing（浏览器文件选择、平台安装入口拦截、可信 Skill 归属[宿主能力阻塞]未闭环）。

验证：`go test ./...` 全部 ok 0 失败；gofmt -l/git diff --check 无输出；go vet 通过；Python 合同 197 passed + Ruff 通过；CGO_ENABLED=0 四目标构建（linux/amd64、linux/arm64、darwin/arm64、windows/amd64，SHA256 见证据文档）。仅本地落盘，未提交、未推送、未发布，未重启用户 daemon。

证据：[git-skill-import-20260913.md](evidence/personal-experience/git-skill-import-20260913.md)。

## M132：UX-010 增量 —— 已安装 Skill 新版检查（只读远端快照 / 2026-09-13）

范围：apps/agentshield（internal/skillimport、internal/skillinstall、internal/server）。

实现：
- skillimport：`CheckUpstream(ctx, importID, remoteURL)` 在一次性 `upstream-*` 暂存（0700，结束即 RemoveAll）中重取上游，产出 `UpstreamSnapshot`（来源类型/URL/Ref/SubDir/CommitSHA 或 ArchiveSHA256/ArchiveBytes + 目录/文件清单 + .git 排除标记）。git 按记录 URL/Ref/SubDir 重克隆（ExpectedCommit 空即不固定），快照携带当前 HEAD——上游前进如实反映，记录不动。zip 调用方 URL 以 `sum(canon.Marshal{url, archive_path, expected_sha256})` 复算定位摘要与 `SourceLocatorDigest` 绑定：他 URL → ErrChanged，非 https → ErrURLBlocked。local_dir/未知 schema/未知来源 → ErrInvalid。`ReadRecord` 导出包装支持已清理暂存后的读取。
- skillinstall：`CheckUpdate`（合同 `local-skill-update-check/v1`，结果 schema `local-skill-update-check-result/v1`）纯只读——不创建/修改/固定记录、不授予权限、不写状态。前提：RecordedStatus=installed_unverified 且 Operation 存在、无进行中移除、导入 ArtifactDigest/AnalysisSHA256 与 Plan.Source 绑定一致。git 来源拒绝调用方 URL（上游位置以记录为准），zip 来源要求非空 URL 交定位摘要绑定。内容差异复用共享 `compareContentDelta`（与更新比较同一 200 项截断预算），Total>0 → new_version + requires_confirmation=true；权限差异显式 `deferred_to_update_comparison`。结果产出前重读记录核签名、复查移除、检查 ctx；边界事件 update_checked。
- server：`POST /v1/skill-installations/operations/{id}/update-check`，严格平铺 JSON（schema_version/remote_url/actor_id），管理员能力 401/403、GET 405、槽位 TryLock 429、60s 上下文，错误沿用 skillInstallError 映射。
- 更新比较重构：`compareContents` 抽出共享 `compareContentDelta/contentDelta`，更新比较与只读检查同一路径报告，无行为变化。

测试：新增 7 个测试全部通过（skillimport 3：git 快照见前进 HEAD+新文件且记录/暂存不动、zip 定位摘要绑定 URL 拒绝他源、local/未知/不存在三向拒绝；skillinstall 3：up_to_date/new_version 全字段断言+零状态写入[路径清单前后对比]+grant revision 不变、210 项差异 200 截断、守卫表[schema/actor/未知 id/local/git 拒 URL/zip 拒空 URL/摘要篡改 ErrChanged/revoke+Remove 后 ErrRemovalPending，缝未被调用断言]；server 1：凭据边界/405/严格体/本地 400/未知 404/移除与 grant 状态不变）。git/zip 记录由测试共享密钥重签落盘维持安装绑定。既有测试零回归。

诚实记录（边界）：skillinstall 层测试的上游重取经 `upstream` 缝以快照替身完成（跨包行为、无网络；缝为测试专用，注释明确 Never set from runtime configuration），真实获取路径由 skillimport 层本地 git fixture 与直接 download 缝覆盖。未在真实 git 托管服务或归档 CDN 联测；无 OS 实机验证。权限差异比较、确认切换 UI、原生更新验收与通用旧状态写入拒绝仍属 UX-010 后续；UX-010 保持 doing。

验证：`go vet ./... && go test ./...` 37 包全部 ok 0 失败；gofmt -l/git diff --check 无输出；Python 合同 197 passed + Ruff 通过（未触碰合同 schema/样本）；CGO_ENABLED=0 四目标构建（linux/amd64、linux/arm64、darwin/arm64、windows/amd64，SHA256 见证据文档）。仅本地落盘，未提交、未推送、未发布，未重启用户 daemon。

证据：[skill-update-check-20260913.md](evidence/personal-experience/skill-update-check-20260913.md)。

## R04-E：Linux/Hermes 原生 Skill 更新闭环（2026-09-14）

基于 v4 任务书补充 `r04-hermes-native-update-smoke.py`，使用公开 Hermes CLI、真实插件钩子/文件工具、隔离 HOME/profile/state 和本机确定性模型，完成 V1 安装/激活/明确预载/读取，pending V2 比较后取消零写入，V2 批准、复比、签名计划、明确更新，旧权限与身份退出，新权限激活、换身份和 SEC，V2 明确预载/读取、内容摘要切换、回执链验证及安全移除，共 15 项通过。

复核同时修复原 R01 runner 的加载假阳性：Skill 由 Hermes `--skills` 明确预载，断言只搜索宿主生成的 system/developer/tool 材料，不再搜索包含用户提示词的整份请求。收紧后 R01 Linux/Hermes 原生 SEC 仍为 11/11。V2 来源是明确导入的本地目录；公网调度取数、其他平台和 Windows/macOS 仍未由本批覆盖。代码与证据仅本地落盘，未提交、未推送、未发布。

证据：[R04-E 报告](evidence/personal-experience/r04e-hermes-native-update-20260914/report.md)。

## R02-F：Linux/OpenClaw 审批后签名预留（2026-09-15）

OpenClaw shipping adapter 在平台批准后的受信 `beforeExecute` 检查点中新增 R02 一次性签名预留：最终参数重查通过后调用 `/v1/hold-executions/reserve`，只有严格匹配的 201 `reserved` 才允许工具；适配器派生独立执行尝试 ID，并让 after-hook observation 绑定 reservation receipt 与预留参数快照。预留拒绝、畸形响应、响应丢失、重复回调均拒绝执行；响应丢失保持 uncertain，不能盲目重试。

真实 OpenClaw 2026.5.12 gateway、审批管理器和临时补丁宿主共 18/18 场景通过，覆盖双方批准、两侧拒绝、等待期撤销、最终参数变化、异常返回、超时、取消及 daemon 失联；三个正向各产生一条 reservation 和一条绑定 observation。原版宿主未修改并按设计拒绝 hold。工具与操作者为确定性夹具，未证明真人审批、桌面通知或真实外部副作用；宿主检查点尚未上游，UX-008/N06 保持 doing/partial。代码与证据仅本地落盘，未提交、未推送、未发布。

证据：[R02-F 报告](evidence/personal-experience/r02f-openclaw-approved-retry-20260915/report.md)。

## R02-G：Linux 桌面通知总线传输（2026-09-15）

真实候选 daemon 启用 `desktop_notify` 后，一条签名 pending hold 经产品 dispatcher 调用系统 `notify-send`，GNOME session bus 实际接收 `org.freedesktop.Notifications.Notify`。标题和正文严格为产品名与待确认数量；总线记录中无工具调用、action、receipt 或参数标识。测试结束明确拒绝 hold 并验证回执链。远程 TTY 无法证明屏幕渲染或用户注意，因此只提升 Linux 通知传输，不关闭整体通知体验。代码与证据仅本地落盘，未提交、未推送、未发布。

证据：[R02-G 报告](evidence/personal-experience/r02g-linux-desktop-notify-20260915/report.md)。

## R07：同一当前候选的 N09 逐行证据矩阵（2026-09-15）

将 R01 Linux/Hermes SEC、R02 Linux/Hermes 批准重试、R04-E Linux/Hermes 更新、R01 Linux/OpenClaw SEC、R02-F Linux/OpenClaw 批准重试和 R02-G Linux 通知六条腿统一重跑/归档到候选二进制 SHA256 `b6e7650f9ab35f6b259cbd64fe9be5a19347b3689ed3dab0be38874d4bda6708`。新增可重复生成器，读取每份通过报告的明确检查项、验证同一候选并生成 3 平台 × 3 系统 × J1–J11 矩阵；v2 校验器对报告摘要、平台归属和逐行 coverage 全部通过。

矩阵没有 `complete_acceptance` 行。Linux/Hermes 的任务级归属、批准重试、本地来源更新和部分卸载，以及 Linux/OpenClaw 的会话级归属、配套检查点批准重试、失败关闭和通知总线传输只记为 `controlled_start`；OpenClaw 临时宿主检查点、合成执行器/操作者及远程通知的限制均保留。WorkBuddy 缺运行时，生产 Git 受当前非公网解析阻断，Windows/macOS 需协作者实机，完整产品安装/卸载、隐私与恢复行仍未完成。因此 R07/N09 维持 partial，T01–T06 不启动。所有成果仍仅本地落盘，未提交、未推送、未发布。

证据：[N09 当前候选矩阵](evidence/personal-experience/n09-current-candidate-20260915/report.md)。
