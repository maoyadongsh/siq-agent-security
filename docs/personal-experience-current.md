> **入口已迁移（2026-09-19）：请从[当前开发导航](development/current.md)选择仍有效的任务及平台台账。以下内容保留为各历史阶段交接，不再叠加新的当前执行指令。**

# 个人体验当前交接

> **当前执行入口：[personal-experience-lan-team-next-development-taskbook-20260914-112027.md](personal-experience-lan-team-next-development-taskbook-20260914-112027.md)（v4.0）。** PR #45 已合入 main `4464dfbc8e66c8ec1fb2590b286351595fcd9667`，最终 HEAD 的 38 项 CI 通过、3 项按配置跳过。后续从新 main 新建 GLM 工作树，优先 R01 可信归属和 R02 审批重试；原 GLM 目录保留，不整体导入。下方旧入口均为历史。

> 2026-09-14：GLM 未提交成果已完成选择性独立复核，接受与暂缓范围见 [报告](evidence/personal-experience/glm-stage-review-20260914/report.md) 和 [台账](personal-experience-closure-progress-20260913.md)。N05/N06 源实现未通过，N09 未完成；下方旧阶段表述保留为历史。合并后由新任务书固定后续执行基线。

# 个人体验当前交接（K002，2026-09-11）

> **当前执行入口：[后续开发任务书 v3.0](personal-experience-lan-team-next-development-taskbook-20260913-192253.md)。** N01 已经 PR #35 提交、推送并合入 main `0d4133f`，代码与 Linux 最低验收完成；N00 分支/旧树核查完成。下一批 N02 安全 Git 与 N04 平台能力，Windows/macOS 原生验收继续 N07/N09。见 [接续台账](personal-experience-closure-progress-20260913.md)。下方 v2 和未提交表述保留为历史。


> **2026-09-13 早前独立审查（历史）：当时 N01 仍为 doing。** Ornith 的自动迁移完成声明未通过验收，入口防护修复已落盘且通过组件/Linux 验证；完整迁移、旧程序拒写和跨 OS 验收继续待办。当前工作树 `/tmp/siq-personal-closure`，未提交或推送。执行接续见 [新台账](personal-experience-closure-progress-20260913.md)，详见 [审查报告](evidence/personal-experience/ornith-n01-review-fixes-20260913-182231/report.md)。

> 当前执行入口（2026-09-13）：[后续开发任务书 v2.0](personal-experience-lan-team-next-development-taskbook-20260913-160928.md)。全部已核查分支已通过 PR #32 合入 main `983b820`；后续从最新 `origin/main` 新建工作树，先个人闭环再 LAN。本文下方的旧基线、未提交/未合并表述和完成度数字均为各阶段历史记录，不代表当前状态。

> 2026-09-13 M132 审查修复：获取失败分类、请求/结果合同与个人检查入口已补齐；生产 Git 获取在具备完整安全传输前明确拒绝，HTTPS ZIP 新版检查可用。回归与浏览器验证见 [本批记录](evidence/personal-experience/stage-fixes-m132-20260913.md)。UX-010 保持 doing，自动定期检查、Git 安全传输和原生更新验收继续待办。

## 修复提交分支（2026-09-13）

用户已授权将修复提交到远端。本批使用独立分支 `codex/reviewed-stage-fixes-20260913`，以远端 main 的 `b6f186d` 为基线，保留原 README 更新，纳入修复依赖的已完成 M68–M130 基础和 M124–M130 审查修复；合同、基础实现、最新四项修复分别提交。M131 及之后代码不在本批范围，GLM 工作目录与分支保持原样，未合并 main。最终分支的验证与范围见 [提交验证记录](evidence/personal-experience/reviewed-fixes-publish-20260913.md)。

下文及原验收记录中的“未提交或推送”是各次审查完成时的历史状态；原证据摘要保留，不作为本次重新构建制品的摘要。缺失的真实 Windows/macOS、WorkBuddy、桌面通知和团队验收仍待完成。

## M129/M130 验收问题修复接续（2026-09-13）

独立验收复现的两项 P1（场景执行限制失效、场景切换被忽略）和两项 P2（通知重试过密、原始输出进日志）已修复，复验见 [本批记录](evidence/personal-experience/stage-fixes-m129-m130-20260913.md)。新增场景效果检查覆盖授权生成、草稿编辑、运行时工具集、托管会话包络及真实裁决；限制模板对无法识别的操作拒绝。无网络场景也禁用无法证明不出网的通用解释器；这是权限限制，不是 OS 沙箱。原有 pending/approved/deployed 授权遇不同场景返回 409，保留原授权和修订。

后续 GLM 开发请保留这些修复及回归测试；Git 来源导入仍按其独立阶段推进。缺少可信 Skill 执行来源和原生实机证据的项目继续保持未完成；本批未提交或推送。

## 2026-09-13 已完成阶段的审查修复

最新审查覆盖 M124–M128，修复内容及本地验证见 [阶段修复记录](evidence/personal-experience/stage-review-fixes-20260913.md)。OpenClaw 不再注入不受支持的安装配置，托管凭据仅限 loopback 且失败硬拒绝；Hermes/OpenClaw 输出关联只能消费一次；Skill 元数据匹配保持 unknown，可信执行来源绑定仍待开发。后续应先解决可信绑定和真实审批恢复，再补跨 OS/WorkBuddy 验收；另一窗口正在开发的阶段另行审查。

下文为历史交接，不代表最新远端合并状态。本批保留当前分支、用户服务及另一窗口修改，只落盘修复，未提交或推送。

## 2026-09-12 持续开发接续

M38 已修复停止时 HTTP 尚未排空就释放写锁的窗口，验证见 [停止排空记录](evidence/personal-experience/stop-drain-20260912.md)。下一步继续系统后台注册与可恢复卸载；本增量不等同后台服务安装完成。

用户再次要求以更新后的原任务书持续开发；当前工作区在 `a195fab` 上保留 M35/M36，并新增 M37 原生 `start`。已创建持续目标，当前优先 UX-003/004；详见 [M35–M37 台账](personal-experience-development-progress-20260910.md) 和 [M37 验证](evidence/personal-experience/native-start-20260912.md)。初始化、目录健康绑定和前台启动已在 Linux arm64 验证；系统后台注册、桌面通知和安装包仍待实现，其他 OS 原生证据保持未完成。下文 K002 状态为该批历史交接，不能据其“只做本批”限制当前用户已授权的接续开发。

原始范围：[个人体验与局域网团队任务书](personal-experience-lan-team-development-taskbook-20260910-145507.md)，D01–D11、UX-000–015、LAN-001–006 保持不变。

## 已结束的基线修复

KIMI-001/R1/B1 经 PR #27 合并；main 基线 `1e20635843c0966e24d73d149e3d7bcd080f89c4`。合并后的 ci `34588402820`、runtime-security `34588402849`、research `34588402923`、pages `34588402834` 通过；nightly 条件跳过。原材料仍在 [M1–M34 台账](personal-experience-development-progress-20260910.md)及 K001 交接文件，历史状态与证据不改写。

## 当前批次：K002 平台验证基础与安装设计

分支 `codex/personal-k002-platform-readiness`，从上述 main 新建，不在已合并 K001 分支继续开发。

| 原任务 | 本批增量 | 未关闭条件 |
| --- | --- | --- |
| UX-000 | 建立本交接，明确 K001 已结束与 K002 范围 | 不是重新完成需求基线，不重复计算 M1–M34 |
| UX-001 | 离线平台材料校验器、两个 QA 合同、正负向测试与跨 OS 工具 CI | 真实 OS/宿主版本、正常/拒绝/审批/归属能力，待 Kimi 实机执行 |
| UX-002 | ADR-049 材料与支持声明分离；ADR-050 生命周期方案提案 | 各 OS 后台机制/权限、WorkBuddy 原生能力、具体安装合同尚需实测决策 |
| UX-003/014 | 复用现有 Go/状态协议/Web embed 的实现方向 | 尚未新增产品安装器、托盘或正式制品 |

工具通过只表示材料处理代码与输入规则通过，不表示18个目标已验证。尚不能宣布 M0/UX-001/UX-002 完整完成；缺系统不阻塞相互独立设计。当前不开始 LAN，不把 ADR-0048 的未实施变成需求放弃，原文存储继续关闭。

### 交付入口

- [平台材料规格](personal-platform-validation-spec-v1.md)与 [ADR-049](adr/0049-personal-platform-evidence-inventory.md)。
- [生命周期方向提案](adr/0050-personal-client-lifecycle-direction.md)。
- `scripts/personal-experience/platform_acceptance.py` 和 `scripts/personal-experience/tests/`。
- [Kimi 本批实机执行单](KIMI-002-native-platform-validation.md)。
- 本地验证：`docs/evidence/personal-experience/reviewer-k002-20260911/verification.json`；远端结果以 PR 的最终 HEAD 与 run 为准，不把提交前状态改写为 CI 已通过。

审阅方环境可执行新工具和测试，但 Git DNS 不可用，未取得完整克隆，未在这里重跑旧 Go/前端或目标宿主。完整仓库回归由本批 PR CI 实跑；原生桌面/真实智能体另行验证，不用 CI 的工具单测代替。

## 接下来只做本批未覆盖部分

Kimi 按同一分支交付真实平台材料与生命周期假设验证；审阅方在交接后不并行修改同组文件。完成后审阅本批 PR，再决定 UX-003 的首个可运行安装/生命周期增量；真实 Hermes 更新旅程继续保留为 UX-010 优先补验，其他原任务不丢弃、不一次下发。

用户已授权本轮分支开发、提交与推送；不自动合并 main、发布、部署、删除分支或更改仓库保护。未来合并仍按已约定的单独授权流程。


## 2026-09-12 持续开发增量 M35–M41

按用户继续开发授权，已在本工作区推进实例健康绑定、原生初始化/start、停止排空、Linux unit 导出、原生 systemd 临时单位验证与签名配置准备。详见 [开发台账](personal-experience-development-progress-20260910.md)及 [M41 验证](evidence/personal-experience/service-prepare-20260912.md)。旧 K002 交接中的“再决定首个增量”已被本轮实现进展更新。

当前继续实现产品后台注册、状态与恢复/卸载；不将临时 systemd 验证或 service-prepare 计为安装器完成。三系统三平台验收、可信 Skill 归属、更新原生旅程、隐私/追溯及 LAN 仍按原目标推进。本轮修改尚未提交或推送。

M42 已接入产品 `service-register [--runtime]` 并通过真实 Linux 临时注册/重复注册/范围冲突拒绝及系统启停清理验证。后续继续产品启停/状态/卸载；完整安装器和跨 OS 原生验收仍未完成，见 [M42 证据](evidence/personal-experience/service-register-20260912.md)。

M43 已接入产品 service-start/status/stop，真实 Linux 启停与停止确认负向验证通过；停止后主锁释放。下一步继续卸载及迁移，不将该进展计作三系统安装器完成，见 [M43 证据](evidence/personal-experience/service-control-20260912.md)。

M44 已完成 Linux 产品服务注销入口及真实 runtime 注册/启停/注销旅程；数据保留和运行中拒绝已验证。后续继续升级迁移、安装交付及跨 OS 生命周期，见 [M44 证据](evidence/personal-experience/service-unregister-20260912.md)。

M45 已复用既有发行清单实现原生制品暂存；尚未切换运行版本。正向验证使用包内开发密钥夹具，Linux 实际 CLI 拒绝 unsigned 清单，见 [M45 证据](evidence/personal-experience/client-stage-20260912.md)。下一步继续升级兼容与恢复事务。

M46 已加入独立签名兼容声明与只读 client-upgrade-check；v1 仍可暂存但升级预检拒绝。切换/恢复仍待实现，见 [M46 证据](evidence/personal-experience/client-compatibility-20260912.md)。

M47 已完成服务配置成对切换事务及文件阶段恢复，serve 会拒绝未完成切换；上层候选升级/reload/健康流程继续待办，见 [M47 证据](evidence/personal-experience/service-switch-20260912.md)。

## 2026-09-12 主分支整合

用户已明确要求先提交并合并 main，本批整合 K002 既有六次提交及 M35–M47 已验证增量。完整个人/LAN 开发目标保持 active；本次合并不代表任务书全部完成。升级命令草稿尚未验证、未接入 CLI，已另存于工作区外 `/home/maoyd/siq/.siq-upgrade-draft-20260912/`，不纳入本次主分支代码；后续恢复该草稿时重新复核当前状态。实际提交和合并状态以 PR #28/Git 为准。

## 合并后的升级开发 M48

PR #28 已按用户授权合入 main `69d9c59`。当前新分支 codex/personal-client-upgrade-recovery 恢复并验证升级草稿，新增 service-upgrade 与同事务前滚恢复。见 [M48 证据](evidence/personal-experience/service-upgrade-20260912.md)；尚未验收真实跨发行版本/正式签名升级，失败回退和完整个人/LAN 目标继续待办。

M49 已修复目标启动失败时的恢复门槛，真实 Linux 端口占用→候选失败→释放端口→同事务恢复通过。活跃锁及未知进程状态仍拒绝，见 [M49 证据](evidence/personal-experience/upgrade-failed-start-20260912.md)。

M50 新增显式 service-rollback 并通过 Linux 源配置回退实测；旧程序与 v2 清单需保留，v1 日志不含历史二进制摘要，后续继续旧制品留存/身份绑定与安装交付，见 [M50 证据](evidence/personal-experience/service-rollback-20260912.md)。

M51 在首次升级停止前保留当前 CLI 程序本地副本，独立于发行制品目录。签名历史绑定和缺失原路径恢复仍待实现，见 [M51 证据](evidence/personal-experience/client-snapshot-20260912.md)。

M52 已落盘程序摘要签名切换 v2 合同与状态层：兼容 v1、拒绝摘要篡改、Go/Python 签名样例与四目标构建通过。CLI 的实际摘要校验和 v2 写入仍待接入，未提升 UX-003/014 验收状态。证据见 [M52](evidence/personal-experience/service-switch-binary-bindings-20260912.md)。

M53 已接通新升级 v2 程序摘要写入与回退历史内容校验；同路径替换负向、Go 全量/vet/race、四目标构建及隔离 Linux systemd 升级/故障恢复/回退通过。未验证正式不同发行版本，原路径缺失的快照恢复仍待实现；UX-003/014 保持未完成。[证据](evidence/personal-experience/service-binary-identity-20260912.md)。

M54 已接通明确 --restore-missing-binary 的历史程序恢复，校验签名原路径、摘要与发行清单后排他发布。Go 全量/vet/race、四目标构建及隔离 Linux 删除旧程序后恢复回退实测通过；正式不同发行版本仍待验收。[证据](evidence/personal-experience/service-snapshot-restore-20260912.md)。

M55 已支持回退复用唯一匹配的本机已留存发行清单，新升级可指定 --source-manifest 保存原发行材料；所有使用均重新校验发行信任和历史程序内容。Go 全量/vet/race 与四目标构建通过；正式发行/跨 OS 验收保持待办。[证据](evidence/personal-experience/retained-release-manifest-20260912.md)。

M56 已新增 Linux setup --confirm-setup，将初始化/后台注册/启动检查整合为一条命令；重复执行保持同进程与配置。Go 全量/vet/race、四目标构建及完整 CLI 隔离实测通过。尚非正式安装包，不提升跨 OS 后台支持声明。[证据](evidence/personal-experience/setup-entry-20260912.md)。

M57 已增加 ui / ui --print 与 setup --open-ui，核对目录健康后访问本机管理页面。Go 全量/vet/race、四目标构建及隔离 Linux CLI 地址验证通过；实际桌面浏览器与跨 OS 验收保持待办。[证据](evidence/personal-experience/local-ui-entry-20260912.md)。

M58 已实现 Linux client-install 的发行校验、稳定路径留存与后台 setup 串联，启动后复验运行版本/目录/签名归属。Go 全量/vet/race、四目标构建通过；正式发行安装正向和跨 OS 安装验收仍待完成。[证据](evidence/personal-experience/client-install-entry-20260912.md)。

M59 已实现明确启用/关闭用户启动入口与 enabled 状态的归属校验。Go 全量/vet/race、四目标构建及隔离 Linux runtime CLI 实测通过，保持运行进程/配置。尚无真实重新登录或跨 OS 证据。[证据](evidence/personal-experience/service-login-startup-20260912.md)。

M60 已新增 teardown --confirm-teardown 整合后台退出，数据保留与再次 setup 通过隔离 Linux 完整 CLI 验证；Go 全量/vet/race、四目标构建通过。跨 OS 与正式制品验收仍未闭环。[证据](evidence/personal-experience/teardown-entry-20260912.md)。

M61 开始 macOS LaunchAgent：只读 plist 导出与共享路径预检已落盘；Go/Python 交叉解析、158 项合同、Go 全量/vet/race、四目标构建及 Linux 生命周期回归通过。macOS 尚未注册/启动或实机验收。[证据](evidence/personal-experience/launch-agent-plist-20260912.md)。

M62 已完成 macOS plist 签名归属与状态目录内准备/恢复。Go 全量/vet/race、159 项合同与四目标构建通过；尚未系统注册或原生启动。开发台账首页已更新 main M47、本地 M48–M62 及 UX-003/014 的真实部分实现状态。[证据](evidence/personal-experience/launch-agent-ownership-20260912.md)。

M63 已接通 macOS 用户配置目录的排他链接发布，签名源与路径归属前后复验。Go 全量/vet/race、四目标构建及临时 home 文件层测试通过；尚未 launchctl 加载/启动或 macOS 实机验收。[证据](evidence/personal-experience/launch-agent-registration-20260912.md)。

M64 已新增 macOS 只读已加载配置核对，严格 XML 和当前用户域验证；Go 全量/vet/race、四目标构建和模拟正负向通过。list -x 当前系统兼容性、加载和启动仍待实测/实施，不计为 macOS 原生支持。[证据](evidence/personal-experience/launch-agent-loaded-status-20260912.md)。

M65 已补齐只读未加载判定：完整用户域列表确认缺席与查询失败分离，存在仍需 XML 归属核对。Go 全量/vet/race、四目标构建及 33 项模拟场景通过；macOS 实机与加载/启动仍待完成。[证据](evidence/personal-experience/launch-agent-presence-20260912.md)。

M66 已实现 macOS 显式加载及完整配置读回；已加载复用、未知配置拒绝、失败保留现场。Go 全量/vet/race、四目标构建和模拟场景通过；macOS 实机、启动与退出仍待完成。[证据](evidence/personal-experience/launch-agent-load-20260912.md)。

M67 已接通 macOS 显式启动与目录健康验证，已有进程不强制重启，失败保留现场；Go/合同/构建验证通过，原生 macOS 验收仍缺。用户已要求先提交合并当前已实现的 M48–M67，实际合入状态见 Git/PR。[证据](evidence/personal-experience/launch-agent-start-20260912.md)。

M68 已新增 macOS 显式停止、正常退出和 Writer 读回；Go 全量/vet/race、四目标构建与模拟场景通过，macOS 实机仍待验收。M48–M67 已提交/推送 PR #31（36 通过、2 跳过）并合入本地 main，远端因代码所有者审查未合入；M68 在独立后继分支本地落盘。[证据](evidence/personal-experience/launch-agent-stop-20260912.md)。

M69 已补齐 macOS 精确配置注销与重复重试，保留状态/历史且不接管未知任务。Go 全量/vet/race、四目标构建及模拟场景通过；真实 macOS 注销/重装仍待验收。后继 M68–M69 尚未提交。[证据](evidence/personal-experience/launch-agent-unregister-20260912.md)。

M70 已接通 macOS setup 编排、复用与失败短路，Go 全量/vet/race、四目标构建及最终 Linux 原生回归通过；macOS 实机仍待验收。下一步整合 teardown，后续继续 Windows。[证据](evidence/personal-experience/setup-macos-20260912.md)。

M71 已整合 macOS teardown 停止/注销与重复恢复；Go 全量/vet/race、四目标构建和 Linux 原生回归通过。8 项模拟集成场景检查原状态数据保留；macOS 实机仍待验收。后续优先补 Windows 生命周期。[证据](evidence/personal-experience/teardown-macos-20260912.md)。

M72 已新增 serve 显式状态目录绑定，为 Windows 后台避免依赖缓存环境变量做准备。Go 全量/vet/race、四目标构建与 Linux 原生错环境目录隔离通过；Windows 任务注册与原生生命周期尚未完成。[证据](evidence/personal-experience/serve-explicit-directory-20260912.md)。

M73 新增 Windows task-xml 只读配置导出与当前用户绑定，Go 全量/vet/race、160 项合同/样例及四目标构建通过。Windows 系统注册与原生运行仍未实现/验收。[证据](evidence/personal-experience/windows-task-xml-20260912.md)。

M74 已完成 Windows 任务签名准备、归属核验与缺失 XML 恢复；Go/合同/构建验证通过，续开发时已复验定向测试、161 项合同与实际构建摘要。Windows 系统查询/注册/启动与实机验收仍待完成，UX-003 不标完成。[证据](evidence/personal-experience/windows-task-ownership-20260912.md)。中英文 README 已补齐个人源码入口和当前支持边界；后继增量仍本地未提交。

M75 完成 Windows 任务完整配置核对核心，Go 全量/vet/race、四目标构建与追加解析边界定向测试通过。系统查询、编码传输与 CLI 接入仍待实现，没有 Windows 原生读回证据。[记录](evidence/personal-experience/windows-task-readback-20260912.md)。README 已在独立文档分支推送为 b6f186d；功能增量保持本地。

M76 已接通 Windows `task-query`，核对系统返回配置与本地签名源，查询失败不判定缺席。Go 全量/vet/race、四目标构建及模拟查询/编码测试通过；没有 Windows 原生证据。[记录](evidence/personal-experience/windows-task-query-20260912.md)。下一步缺席判定与排他注册，功能仍仅本地落盘。

M77 已接通 Windows `task-presence` 与失败分类、存在时完整归属复验。Go 全量/vet/race、四目标构建和模拟编排通过；PowerShell/COM 原生运行未验证。[记录](evidence/personal-experience/windows-task-presence-20260912.md)。下一步以系统排他创建实现注册，不将查询缺席等同于覆盖授权。

M78 已接通 Windows `task-register --confirm-register` 排他注册与创建后完整读回；九项模拟编排、Go 全量/vet/race 和四目标构建通过。未原生执行 PowerShell/COM 注册，Windows 启停与综合验收待完成。[记录](evidence/personal-experience/windows-task-registration-20260912.md)。本批仅本地落盘。

M79 已接通 Windows `task-start --confirm-start` 与目录健康检查；八项模拟编排、Go 全量/vet/race 和四目标构建通过。新增动作模板路径拒绝；Windows 原生 Run、退出和注销待验收/实施。[记录](evidence/personal-experience/windows-task-start-20260912.md)。未提交或推送功能增量。

M80 已补 `task-runtime` 的运行/排队/空闲状态和返回码读回；六项模拟编排、协议边界及 Go 全量/vet/race、四目标构建通过。下一步当前运行绑定的正常退出请求，不用历史零结果替代本次退出证明。[记录](evidence/personal-experience/windows-task-runtime-20260912.md)。Windows 原生验收仍待完成。

M81 完成当前运行绑定的退出授权核心与两份签名合同；Go 全量/vet/race、163 项合同及四目标全包编译通过。尚未接 HTTP/CLI 和实际排空，正常退出继续待实现。[记录](evidence/personal-experience/service-stop-authority-20260912.md)。目标与本地后继开发保持进行中。

M82 完成退出接受记录的排他发布与幂等恢复；Go 全量/vet/race、164 项合同及四目标全包构建通过。记录不代表已退出，尚待接服务端请求与排空。[记录](evidence/personal-experience/service-stop-acceptance-20260912.md)。功能继续本地保留。

M83 已接本机签名退出 HTTP、接受记录与排空通知，隔离 Linux 真实进程正常退出、记录留存和 Writer 释放通过；Go 全量/vet/race、四目标构建通过。尚缺停止 CLI 与 Windows 原生任务退出验证。[记录](evidence/personal-experience/service-stop-http-20260912.md)。功能增量本地保留。

M84 已实现 stop-request CLI 与接受记录核对/响应丢失恢复；Go 全量/vet/race、四目标构建和隔离 Linux 真实 CLI/HTTP 停止通过。命令仍只报告接受，最终排空结果与 Windows 停止闭环待补。[记录](evidence/personal-experience/service-stop-request-cli-20260912.md)。功能仅本地保留。

M85 已接本次排空签名结果与后台收尾等待；Go 全量/vet/race、165 项合同、四目标构建和隔离 Linux 最终候选退出/结果/Writer 验证通过。停止完成客户端及 Windows 原生任务确认继续待办。[记录](evidence/personal-experience/service-stop-result-20260912.md)。

M86 完成 stop 与 --recover 的签名结果/Writer 联合核对，Go 全量/vet/race、四目标构建及隔离 Linux 三条退出与恢复 CLI 通过。下一步 Windows task-stop 与注销编排，原生跨 OS 验收仍待完成。[记录](evidence/personal-experience/service-stop-completion-cli-20260912.md)。

M87 已实现 Windows task-stop，10 项模拟场景、Go 全量/vet/race 与四目标构建通过。真实签名状态记录与写锁用于模拟编排，未执行 Windows 系统任务，不计原生验收。下一步注销及 setup/teardown。[证据](evidence/personal-experience/windows-task-stop-20260912.md)。

M88 已接 Windows task-unregister，10 项模拟场景、Go 全量/vet/race 与四目标构建通过；注销后保留源配置和历史。PowerShell/COM 原生执行仍待验收，下一步 Windows setup/teardown。[证据](evidence/personal-experience/windows-task-unregister-20260912.md)。

M89 已接 Windows setup，复用用户后台编排与健康检查，Windows/macOS 共 22 项模拟场景和 Go 全量/vet/race、四目标构建通过。Windows 原生完整旅程待验收，下一步 teardown。[证据](evidence/personal-experience/setup-windows-20260912.md)。

M90 已接 Windows teardown，停止失败阻断注销，删除响应丢失后可重试恢复。7 项模拟场景、Go 全量/vet/race、四目标构建通过；Windows 原生完整生命周期仍待验收。[证据](evidence/personal-experience/teardown-windows-20260912.md)。UX-003 和总体目标继续进行中。

M90 补充完成运行实例正常排空到注销的串联验证，以及 drain_failed 阻断删除，退出编排累计 9 项模拟场景。生产候选未改变，Windows 原生证据仍缺。

M91 开始 UX-011：已落盘任务活动只读聚合核心，严格隔离主体、会话和意图版本；缺失绑定进入未归属，不把链验签当作效果核验。API、详情与结果证据关联仍待接入。[证据](evidence/personal-experience/task-activity-projection-20260912.md)。

M92 已补任务结果核验的完整主体范围，不借用其他会话/智能体/意图版本的成功效果证据；现有结果核验判定复用。当前仅内部核心，API 与任务详情继续待办。[证据](evidence/personal-experience/task-completion-subject-20260912.md)。

M93 已接管理鉴权的任务活动列表与未归属视图 API，支持快照分页、完整性范围报告及读取失败区分；Go/Python 合同与检查通过。前端和结果详情仍待开发。[证据](evidence/personal-experience/task-activities-api-20260912.md)。

M94 任务活动已接个人前端，双视图、分页和刷新错误状态通过浏览器验证；49 项 Web 测试与两种构建通过。当前仍是活动列表，详情和结果证据未接，不标完整追溯完成。[证据](evidence/personal-experience/task-activities-ui-20260912.md)。

M95 已接活动详情回执 API，快照分页与交错会话隔离验证通过，未归属活动可单条查看；不返回参数摘录。Go/Python 合同与构建检查通过，详情前端和结果核验继续待办。[证据](evidence/personal-experience/task-activity-detail-api-20260912.md)。

M96 活动详情已接前端与列表跳转，响应范围校验、失效提示、返回路径及桌面/移动布局验证通过；50 项 Web 测试和两种构建通过。结果核验与 Skill 版本仍待接入。[证据](evidence/personal-experience/task-activity-detail-ui-20260912.md)。

M97 已接活动范围结果核验 API，签名意图/主体范围/效果证据联合验证，末尾复验链快照。真实文件材料 verified/conflicting 与未知边界通过测试；168 项合同和 Go 检查通过。结果前端及 Skill 版本继续待开发。[证据](evidence/personal-experience/task-activity-completion-api-20260912.md)。

M98 活动详情已展示独立效果核验、要求与证据引用；同快照/绑定校验和失败去除旧成功状态通过浏览器验证，52 项 Web 测试及两种构建通过。Skill 版本、证据详情和导出仍待完成。[证据](evidence/personal-experience/task-activity-completion-ui-20260912.md)。

M99 已接证据引用的按需元数据查看，复用服务端签名校验并检查任务/证据 ID。54 项 Web 测试、两种构建和浏览器错误/焦点旅程通过；证据详情不展示原文或自行提升任务结果。[证据](evidence/personal-experience/effect-evidence-detail-ui-20260912.md)。

M100：单活动脱敏导出核心已落盘并通过 Go 全量、vet、race 和四目标构建。下载 API/签名封装/UI 尚待接入；本批未提交或推送，不提升原生平台支持声明。

M101：任务活动的管理下载接口和独立签名合同已实现，固定 Go 样例通过 Python 合同/验签；支持当前快照内的整组脱敏摘要导出，前端入口待接。未提升原生支持声明，未提交推送。

M102：个人活动详情已接整组摘要下载，56 项前端测试、两种构建和隔离浏览器下载/冲突验证通过；未将浏览器 fixture 计为真实平台证据。效果材料/Skill 版本仍待补齐。

M103：历史授权来源关联核心已落盘，范围/签名/撤销/缺失选择验证通过。只证明历史授权来源；Skill 内容版本、执行归属及 API/UI 继续待开发。

M104：历史授权引用的 Skill 内容来源核验核心已落盘，普通/导入准入分别保留声明版本与各自摘要；服务端查询及界面仍待接入，不提升原生支持或执行证明声明。

M105：历史准入磁盘读取已增加 8 MiB 限额、文件/目录链接和身份检查、严格 JSON 与文档 ID 核对。查询 API/UI 仍待接入，未提交推送。

M106：活动历史 Skill 来源查询 API 和共享合同已落盘，可返回签名授权引用的声明版本与内容摘要；来源核验不等于实际执行证明。前端来源面板继续待接，未提交推送。

M107：活动详情已接按需历史 Skill 来源面板，59 项 Web 测试及两种构建、隔离浏览器验证通过。声明版本不等于执行证明；未提交推送。

M108：活动 search API 已提供全快照的精确条件与标识关键词筛选，先筛选再分页。未归属事实保持原状态，前端查询入口待接；未提交推送。

M109：任务活动页已接标识筛选与 URL 状态恢复，61 项 Web 测试、两种构建和隔离浏览器旅程通过；筛选不搜索参数原文或 Skill 内容。本批未提交推送。

M110：完整脱敏追溯包核心与 `local-task-trace-export/v1` 合同已落盘，组合回执摘要、历史 Skill 来源、完成结论及实际引用的效果证据元数据。固定 Go 样例通过 Python 合同/Ed25519 互验，Go 全量/vet/race 和四目标构建通过；来源或结论缺失明确标记 incomplete。API/UI 和真实平台样例仍待完成，未提交推送。[证据](evidence/personal-experience/task-trace-export-core-20260913.md)。

M111：管理端完整追溯包下载 API 已接通，服务端组合已验签回执、历史 Skill 来源、主体范围完成结论和签名效果记录，签名后复验回执快照及效果集合。Go 全量/vet/race、174 项合同/Ruff和四目标构建通过；前端入口与真实平台样例待完成，未提交推送。[证据](evidence/personal-experience/task-trace-export-api-20260913.md)。

M112：活动详情已增加完整脱敏追溯包下载并与回执摘要区分，前端验证活动/快照、来源、完成状态、incomplete 及证据引用关系。63 项 Web 测试、两种构建和隔离 embed 浏览器旅程通过；浏览器不声称完成签名验真，真实平台样例仍待补，未提交推送。[证据](evidence/personal-experience/task-trace-export-ui-20260913.md)。

M113：默认关闭的独立 AES-256-GCM 原文仓核心已落盘，使用独立密钥、任务摘要、AAD、24 小时/64 MiB 默认限制及整项凭据过滤；删除/过期清理不修改事实链。Go 定向/race/vet和 175 项合同/Ruff通过；任务授权与 API/UI 待接，未提交推送。[证据](evidence/personal-experience/raw-task-content-store-20260913.md)。

M114：逐任务原文采集授权与撤销核心已落盘，新增签名 Grant/Revocation 合同，绑定任务/操作者摘要、种类、窗口、保留期和大小；存储写入口已收紧，初始化仓不能绕过授权。撤销以授权签名作 CAS 并与采集串行，既有密文保持独立。Go 定向/race/vet、178 项合同/Ruff和四目标构建通过；管理 API/UI 待接，默认仍不采集原文，未提交推送。[证据](evidence/personal-experience/raw-task-content-authority-20260913.md)。

M115：原文仓不可变签名 Activation 及 status/activation 管理 API 已落盘，绑定操作者摘要、限制和独立密钥指纹；重启从磁盘恢复，部分状态保持 disabled，篡改显示 error 且不覆盖。管理会话与决策凭据隔离，严格请求和默认不采集已验证。Go 全量/vet/race、181 项合同/Ruff和四目标构建通过；逐任务 Grant/Revoke、采集与前端待接，未提交推送。[证据](evidence/personal-experience/raw-task-content-activation-api-20260913.md)。

M116：逐任务 Grant/Revoke 管理 API 已落盘，提供严格创建、完整验签列表/单项和 CAS 撤销；只返回任务/操作者摘要，稳定区分 active/expired/revoked，损坏不返回部分列表。管理鉴权、决策凭据越权、幂等撤销和磁盘隐私已验证。Go 全量/vet/race、184 项合同/Ruff和四目标构建通过；运行时采集凭据/API及前端待接，未提交推送。[证据](evidence/personal-experience/raw-task-content-grant-api-20260913.md)。

M117：原文仓已增加与 Runtime Identity、原生会话、签名 Binding、服务端任务和原文 Grant 同时绑定的短时签名许可，以及许可签发/结构化采集 API。每次采集复验两套权限与撤销，secret 整项过滤，响应不含明文或密文载荷。Go 全量/vet/race、188 项合同/Ruff和四目标构建通过；尚未接原生适配器及原文管理 UI，不提升平台支持声明，未提交推送。[证据](evidence/personal-experience/raw-task-content-runtime-capture-20260913.md)。

M118：原文记录管理 search/read/delete 与过期清理 API 已落盘。列表在返回前认证完整密文目录，显式读取才返回已过滤明文并标记 contains_plaintext；删除要求记录 ID 确认且不改事实链。Go 全量/vet/race、196 项合同/Ruff和四目标构建通过；管理 UI、持续提示、诊断包检查与真实平台采集仍待接，未提交推送。[证据](evidence/personal-experience/raw-task-content-management-api-20260913.md)。

M119：个人控制台已接原文仓持续顶栏状态和设置页显式启用/到期清理；ready 明确保持按任务授权、默认不采集。精确响应校验、设置后即时同步、刷新恢复、异常撤下旧状态和浏览器不持久化已由真实隔离 daemon/embed 旅程验证。66 项 Web、Go 全量/vet/race、196 项合同/Ruff及四目标构建通过；任务级授权/明文管理 UI、自动清理、诊断包检查与原生平台采集仍待完成，未提交推送。[证据](evidence/personal-experience/raw-task-content-settings-ui-20260913.md)。

M120：可信任务详情已接逐任务 Grant 创建/撤销、原文元数据、二次确认读取和完整 ID 删除。前端核对 task_ref 与所选记录关系，切换、关闭、刷新或错误撤下明文，且不写浏览器存储。70 项 Web、Go 全量/vet/race、196 项合同/Ruff、四目标构建及 9 项实际 Grant/Revoke 与记录 UI 旅程通过；原生适配器采集、自动清理、诊断包排除和真实平台端到端仍待完成，未提交推送。[证据](evidence/personal-experience/raw-task-content-task-ui-20260913.md)。

M121：CLI/HTTP 全局导出、任务回执摘要和完整脱敏追溯包已增加原文目录哨兵回归，四条白名单投影均不读取、泄漏或引用 `raw-task-content`。Go 全量/vet及定向 race 通过。仓库当前没有通用诊断包，未来新增收集入口仍需独立排除测试；原生适配器采集和自动清理待完成，未提交推送。[证据](evidence/personal-experience/raw-task-content-export-isolation-20260913.md)。

M122：`serve` 已接原文到期自动清理，启动即执行并每 15 分钟重试，退出随维护协程收尾。禁用不创建状态，启用时完整认证后只删到期密文；篡改使清理失败但不阻断默认服务。Go 全量/vet/race和四目标构建通过；原生适配器采集与真实平台端到端待完成，未提交推送。[证据](evidence/personal-experience/raw-task-content-automatic-cleanup-20260913.md)。

M123：新增 Runtime Identity 专用原文采集桥，服务端从签名 Binding 恢复任务并只接受唯一 active Grant；Hermes 已管理插件在允许后提交参数、观察后提交结果，嵌套 JSON 以有界指针字段供 secret 过滤，250ms 辅助失败不影响执行。105 项适配器测试、Go 全量/vet/race、合同/Ruff和四目标构建通过；真实 Hermes 会话及 OpenClaw/WorkBuddy 接入待完成，未提交推送。[证据](evidence/personal-experience/hermes-raw-content-bridge-20260913.md)。
