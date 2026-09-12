# 个人体验与局域网团队开发台账

- 开始时间：2026-09-10，Asia/Shanghai。
- 持续目标：[开发任务书](personal-experience-lan-team-development-taskbook-20260910-145507.md)。
- 基线：`a2f95c6fad1a04c776d57c4d4b9fd89b85c69b33`，当前 `main` 工作区。
- 用户授权：在本仓增量实现并验证；不自动提交、推送、发布。
- 既有改动：Vitest 4.1.11 的 `apps/web/package.json`、`package-lock.json`，以及原任务书，继续保留。

### 当前续开发基线（2026-09-12）

- 用户再次指定任务书为持续开发目标，目标已登记为 active；先个人 UX，再 LAN。
- 当前分支 `codex/personal-k002-platform-readiness`，HEAD `a195faba41d128d21222f819ebf96a766fb9cd01`。上方 main 和 Vitest 工作区描述为 2026-09-10 历史记录。
- 本轮开始仅任务书有未提交修改，保持原样；未合并 PR、切换分支、提交、推送或发布。在当前 K002 后继工作区先完成可审阅增量；任务书 §11.1 的主线合入步骤尚未执行。
- 最新批次 M36：状态目录健康绑定、配置初始化与稳定本地实例 ID 已实现并通过隔离 Linux arm64 实测；团队设备身份、安装包和三系统用户级后台仍待完成，UX-003 不标完成。

## 任务状态

`doing` 仅表示正在实施；没有真实平台证据时不得提升为完整验收。

| 任务 | 状态 | 当前结果/下一步 |
| --- | --- | --- |
| UX-000 | complete | [需求验收映射与基线](personal-experience-requirements-baseline-20260910.md)覆盖 D01–D11、实施位置、证据、未知项和阶段边界；具体功能状态继续逐任务跟踪 |
| UX-001 | doing / native subset verified | Linux arm64：OpenClaw 原生链路 14 项、Hermes 经实例安装后的原生链路 15 项检查通过；完整会话/审批、Windows/macOS 与 WorkBuddy 桌面仍待验收 |
| UX-002 | doing | ADR-019–047 覆盖会话、发现、诊断、接入变更、Hermes 实例、自检、资源编辑和固定授权选择；安装预览/提交/恢复合同已接通；可信 Skill 运行归属仍需完成 |
| UX-003 | doing | 状态目录匹配、本地重新配对、配置初始化与稳定实例 ID 已实现；M35/M36 隔离 Linux arm64 启动复用、错误目录拒绝、并发初始化和重启验证通过；完整安装器、系统后台生命周期和跨 OS 制品尚待实现 |
| UX-004 | implemented / Linux verified | 会话恢复、注销、到期重新配对、CLI 配对恢复及错误分类已落盘；Linux Chromium 11 项检查通过，跨 OS 运行验证归 UX-015 |
| UX-005 | doing / core implemented | 显式扫描、范围预览、手动目录、稳定安装身份和共享关系已实现；Hermes 自定义根与 profile 使用同一实例解析器。同名实例隔离通过；其他平台根、过滤优先级、全量覆盖与跨 OS 实机仍待验证 |
| UX-006 | doing / Hermes runtime check implemented | 接入预览、确认、恢复、卸载、Hermes 实例选择/原生启用及产品运行自检已落盘；Linux 独立 profile 的 UI/API/真实 CLI 通过。其他平台自检、自动重启和跨 OS 恢复仍待完成 |
| UX-007 | doing / managed Hermes activation verified | 已实现期限、资源边界、编辑、固定授权和实例凭据；Hermes 普通会话自动接入在隔离 profile 实测通过。权限起草/批准/实例接入和日常换发已在隔离 Hermes profile 验证；实际 Skill 版本归属、完整场景模板和跨 OS 验收仍待完成 |
| UX-008 | doing / Web inbox and notification logic verified | 统一待办、单次处理、长期授权定位和浏览器通知的开启/合并/跨窗口去重已落盘；Linux Chromium 测试替身验证通过。OS 实际投递、后台启动器、任务内授权与原生恢复执行仍待完成 |
| UX-009 | doing / Hermes installation UI verified in isolated profile | 本地目录/ZIP、HTTPS ZIP、固定副本审阅、来源绑定批准、安装预览、明确安装确认与失败恢复已接通；隔离 Linux Chromium 和目标文件操作验证通过。安装后实例权限准备、原生清单识别与实例范围的 CLI 保护已验证；Git 来源、浏览器文件选择、平台安装入口拦截、可信 Skill 归属与其他平台仍待完成 |
| UX-010 | doing / update UI verified in isolated Linux browser | 记录、内容检查、移除与恢复 UI/API 已验证；更新比较、独立副本准备、明确切换和中断恢复核心/API 已实现。差异/确认/恢复 UI 已在隔离 Linux 浏览器验证；新版检查、原生更新验收与通用旧状态写入拒绝仍待完成 |
| UX-011 | todo | 任务聚合与结果证据 |
| UX-012 | doing | 随 M1 改进连接与配对状态，后续继续整合页面 |
| UX-013 | todo | 隐私、保留期和独立原文存储 |
| UX-014 | todo | 三系统安装制品与升级 |
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

## 未关闭的验证限制

- `desktop-same-uid` 不构成恶意同 UID 隔离。恢复凭据不改善该残余风险，也不应扩大到网络管理入口。
- Vite 开发代理的 Origin 映射已做正负向测试；正式 embed 的会话旅程已实测。完整 Vite + 新 daemon 浏览器联合验证仍待补充，后端白名单没有扩大。
- 当前签名 Skill 的脚本参与内容哈希；旧包保持可验证。新后台启动入口先在开发工具中实现，待 UX-014 新制品发布准备时整合，不在旧清单上冒用签名。
- 原文记录仍维持关闭，待独立设计后实现；不直接修改既有脱敏审计。
- 任务书的完整目标保持进行中；本机可完成的实现持续推进，外部验证缺口保持明确状态。
