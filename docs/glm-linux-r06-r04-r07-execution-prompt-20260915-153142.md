# GLM 执行提示词：Linux 生命周期、OpenClaw 更新与完整旅程

生成时间：2026-09-15 15:31:42（Asia/Shanghai）。
用途：在本机 Claude Code 中交给 GLM 执行，以下正文可作为完整任务指令。
本文是总体任务书的本批执行细化，不替代原产品目标、N09 矩阵或协作者任务。

## 1. 角色、目标与交付方式

你是本项目的全栈开发与验收执行者。请直接开发、修复、测试并落盘，不只提出建议。
本批目标：在现有 SIQ Agent Security 上完成 Linux 用户可实际操作的生命周期，
补齐 Linux/OpenClaw Skill 原生更新旅程，再串联浏览器、daemon 与真实宿主的完整旅程。

按 **L0 基线 → L1 R06 → L2 R04 → L3 R07 → L4 最终回归** 顺序执行。
L 编号仅为本交接的工作包，不新增产品任务分母。某个实机条件受阻时先记录准确缺口，
继续其余不依赖该条件的开发；不能把受阻条件当成功，也不能因此结束整个批次。

每个工作包都应交付可运行代码或有明确覆盖的验收工具、正负向验证、脱敏证据和进度更新。
现有行为已经正确时优先补完整调用链证据，不为了增加改动量重写实现。
本次默认仅本地落盘；不要自行 commit、push、merge、发布或修改仓库治理。用户后续明确授权优先。

## 2. 固定基线、位置与开始前检查

- 仓库工作树：`/home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914`。
- 已验收提交：`efad8407c84b7b8f626cb06421287e7632c83a46`。
- 当前基线分支：`kimi/personal-v4-r01-20260914`。
- 该基线在交接时只完成本地提交，尚未推送或合并 main。
- 本提示词是基线提交后新建的文档，可以尚未提交；保留它，不把它当作需要清理的文件。

开始先执行只读检查：

```bash
cd /home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914
git status --short
git branch --show-current
git rev-parse HEAD
git merge-base --is-ancestor efad8407c84b7b8f626cb06421287e7632c83a46 HEAD
```

检查工作树已有修改和进程，确认没有其他窗口同时修改本批文件。
HEAD 等于基线可直接接续；若是其后继，先检查新增差异再继承，不能 reset。
如果基线不存在、祖先检查失败或发现他人并行修改同一核心文件，先报告具体差异，
继续独立只读盘点；不把旧 main 或旧 GLM 树当成已包含本批成果。
跨机器执行时必须先取得该提交，不能只从远端旧 main 开发并假定功能齐全。

需要隔离分支时，确认已存在修改归属后，从当前已核实 HEAD 建立新分支；
不能切到其他工作树覆盖文件。禁止 reset --hard、git clean、批量复制旧树及覆盖用户修改。

## 3. 阅读顺序与不能回退的成果

先读：

1. 仓库及 `apps/agentshield/AGENTS.md`，以及适用的上层工作区指南。
2. `docs/personal-experience-lan-team-next-development-taskbook-20260914-112027.md`：
   第 3、4、8、9、10、15 节，以及 R01/R02 的已完成证据和限制。
3. `docs/personal-experience-closure-progress-20260913.md` 顶部当前复核状态。
4. `docs/evidence/personal-experience/openshell-o04-review-20260915/report.md`。
5. `docs/agentshield-dev-spec-v1.md` 与本工作包实际涉及的 `packages/contracts/`。
6. `docs/personal-experience-n09-evidence-review-spec-v2.md` 和
   `docs/personal-platform-validation-spec-v1.md`。

按工作包再读关联源码，先用 rg 定位，不要一次读取所有历史台账或不断重复全仓扫描。
本批继承以下成果：

- R01 SEC 可信上下文；OpenClaw 当前证据主要为会话级，不能描述为任意调用的 Skill 因果证明。
- R02 最终参数复核、唯一 hold reservation、结果不确定及人工结案；批准不等于执行完成。
- R04 来源停用、签名比较、用户确认更新、旧权限失效及 Hermes 原生更新流程。
- O01/O02 策略保真和授权回滚；O03 有界子进程；O04 证据分层、缓存降级、目标只读诊断。
- 默认原生使用不依赖 OpenShell 或企业 Python 服务；前端 embed 可由 Go 单进程服务提供。

旧验收报告记载的“未提交”和旧 binary_sha256 是当时事实，不能改写成新候选的身份。

## 4. 本批边界

### 可以直接实施

- Linux 生命周期 CLI、用户服务归属校验、重启/恢复、升级事务、保留数据退出的增量修复。
- OpenClaw 对应适配器、Skill 安装/更新/移除、授权失效和浏览器管理流程的必要修复。
- 共享核心、合同和 UI 的必要小范围改动；先说明关联问题，先规格/合同再代码。
- 新建隔离测试目录、专属临时 profile、随机可用 loopback 端口和明确归属的测试实例。
- 在已核实支持的环境中，注册/启动/停止本批专属 runtime-only systemd 用户单元。
  先保留产品预览与确认步骤，测试执行器可以充当明确标注的合成操作者。
- 运行真实已安装 OpenClaw、受控的本地确定性模型端点和无害测试工具。

### 本批不实施

- sunbo 的 Windows 和 Luke 的 macOS 专属开发；不能改他们的任务状态为完成。
- WorkBuddy 缺真实运行时时的模拟“已支持”；也不拿 OpenClaw 证据填 WorkBuddy。
- O05/O06 新会话后端、凭据代理、沙箱创建、模型聊天工作台、T01–T06 团队产品功能。
- 绕过 R03 的公网地址/DNS/TLS 校验，直接打开生产 Git 来源。
- 降低 stateformat、签名、Grant/Authority、身份、SEC、参数摘要或确认边界。
- 改系统级服务、修改常用 profile、读取或迁移用户真实私钥、覆盖日常配置。
- 未经明确授权调用付费模型或生产业务端点；原生宿主流程优先使用已有本地模型 fixture。
- 为测试修改日常宿主源码、加入运行时安全旁路，或只在测试配置中跳过安全检查。

### 环境操作约束

不要在当前 shell 全局重设 HOME、PATH、XDG_RUNTIME_DIR 或系统选项。
隔离 HOME/profile 环境只传给测试子进程。真实 systemd 用户总线仍属于当前登录用户，
仅设置临时 HOME 并不能隔离该总线；必须以实际单元名称、FragmentPath、ExecStart、
状态目录及实例签名判断归属，且检查原单元不存在。

不使用 pkill/killall 或根据端口批量杀进程。只停止本批创建且身份确认的 PID/单元，
结束后验证端口与进程状态，保留不确定现场。不得自行启用 linger 或重启整机。
真实注销/登录或重启若无法自动完成，报告待人工验收，不能用服务重启替代。

## 5. L0：基线盘点与测试隔离

输出一份精简 inventory，至少包括：

- 当前提交、未提交路径及摘要、OS/CPU、Go/Node/Python/OpenClaw 版本。
- OpenClaw 可执行文件/安装根的真实解析结果；私有绝对路径只保留在本机临时记录，
  可提交报告使用相对路径、逻辑标识或脱敏值。
- 当前用户 systemd manager 与会话总线是否可用，图形会话/通知展示是否可观察。
- 现有服务/端口/profile 的只读摘要及“本批不得触碰”清单。
- 各工作包依赖表：可执行、需要先修复、外部条件受阻、解除条件。
- 新候选输出目录、隔离状态与 profile、各测试实例的创建/回收责任。

候选构建先使用当前平台，输出至本批临时目录；真实宿主测试始终引用明确的绝对二进制路径。
每次代码或 embed 改动后重新构建并记录摘要，重跑受影响的证据腿。

不要因为所有单测已通过，就认为 L1–L3 真实旅程无需执行。

## 6. L1：R06 Linux 产品生命周期

### 6.1 实际代码入口

- `apps/agentshield/cmd/agentshield/`：
  `client_install.go`、`client_stage.go`、`client_upgrade_check.go`、
  `setup.go`、`service_prepare.go`、`service_register.go`、`service_control.go`、
  `service_login.go`、`service_upgrade.go`、`service_rollback.go`、
  `service_unregister.go`、`teardown.go` 及对应测试。
- `apps/agentshield/internal/clientrelease/`、
  `internal/state/` 中的 user_service、service_switch、service_stop 相关实现。
- `apps/agentshield/internal/server/service_control.go` 及测试。
- `scripts/personal-experience/test_systemd_user_service.py`。
- `apps/agentshield/cmd/agentshield/service_upgrade_native_test.go`。
- `docs/adr/0050-personal-client-lifecycle-direction.md`。

已有命令包括 client-install、setup、service-prepare/register/status/start/stop、
service-upgrade/rollback、service-login、teardown。参数必须查实际 FlagSet 和测试后再执行，
不能自行假设存在 install/uninstall 等通用命令或遗漏确认参数。

### 6.2 实施路径

1. 检查已存在的发布清单验签、版本/平台校验、暂存和旧状态拒写路径，复用现有机制。
2. 从“尚无本产品测试状态”的环境进入安装流程，而不是直接启动 serve 后宣布安装成功。
3. 启动产品、通过实际配对入口打开 embed 管理页面；凭据不出现在 URL、公开日志和截图。
4. 验证退出浏览器不停止后台；停止/启动、服务崩溃恢复时实例身份和授权边界正确。
5. 覆盖用户明确确认后的升级与失败回滚，核对实际运行 PID、ExecStart、二进制摘要及状态。
6. 验证保留数据的 teardown 与适配器安全卸载；重新进入流程不会静默创建冲突身份或复活撤销权限。
7. 修复可复现的问题，并为破坏性误操作、签名或状态边界问题增加针对性负向测试。

### 6.3 必须通过的验收

| ID | 场景 | 必须观察与断言 |
| --- | --- | --- |
| LC01 | 安装前校验 | 合法测试制品按信任边界进入下一步；错误签名/摘要/平台/未来不兼容状态拒绝，原文件和服务不被替换 |
| LC02 | 首次启动与配对 | 实际管理页打开；无凭据/错误配对被拒；合法配对生效；重复/失效凭据按现行合同处理 |
| LC03 | 路径与端口 | 中文、空格及 systemd 特殊字符路径真实可用；占用端口安全报错或遵守既有端口选择规则，不停止占用者 |
| LC04 | 后台与重启 | 浏览器关闭后服务继续；用户服务重启后身份/状态正确，撤销 Grant 不复活；未完成操作恢复遵守事务状态 |
| LC05 | 故障恢复 | 只向自有测试进程注入故障；记录丢响应、超时或切换失败后的可诊断状态，不误报成功，不盲重放副作用 |
| LC06 | 升级 | 运行制品与声明版本/摘要一致；有真实不同版本时验状态兼容，失败时按现有安全机制恢复或保留诊断现场 |
| LC07 | 未知对象保护 | 单元/程序/链接被外部替换，或存在未知文件时拒绝覆盖/删除；重复操作幂等或明确拒绝 |
| LC08 | 保留数据退出 | 后台入口移除、服务停止、状态与历史保留；残留钩子在 block 模式按合同拒绝，不误称保护仍在线 |
| LC09 | 完整移除与再次进入 | 按既有接口单独卸载接入，保留无关宿主配置；程序、状态、后台入口、钩子分别列清，不混称“一键彻底卸载” |

重要事实：

- teardown 当前语义会保留程序、身份、配置、历史及智能体钩子，必须解释这一点。
- 现有 TestNativeUserServiceUpgrade 把同一可信二进制复制到两个路径。
  它证明进程/配置切换，不证明不同版本兼容或正式发布验签，不能直接拿它关闭 LC06 全范围。
- runtime-only 单元测试不证明登录自启动或机器重启。缺图形/登录条件单独保留缺口。
- 正式签名密钥不可用时，保留 production 验签拒绝；使用原有测试签名/测试缝的范围必须标为测试层。
  不注入新的生产可配置信任旁路，不伪造 release 已获信任。

## 7. L2：R04 Linux/OpenClaw 原生 Skill 更新

### 7.1 可复用入口

- `apps/agentshield/internal/skillimport/`、`internal/skillinstall/`、
  `internal/skillcontext/`、`internal/runtimeidentity/`。
- `apps/agentshield/internal/server/skill_install.go` 与相关 API 测试。
- `apps/agentshield/internal/adapterinstall/openclaw_config.go`、
  `internal/adapterinstall/assets/openclaw/`。
- `apps/web/src/local/pages/InstalledSkillsPage.tsx`、
  `SkillUpdatesPage.tsx`、`SkillImportsPage.tsx` 及其使用的 API/组件。
- `scripts/personal-experience/r04-hermes-native-update-smoke.py`：
  借鉴事务顺序和断言，不能把 Hermes 名称替换后称为 OpenClaw 原生验证。
- `r01-sec-openclaw-native-smoke.py`、`openclaw-managed-native-smoke.py`：
  复用真实 OpenClaw 进程、钩子和隔离模型端点。
- `skill-update-browser-smoke.py`：现有测试使用隔离 Hermes fixture；
  保留旧覆盖，另补 OpenClaw 真实链路，不改名称伪装覆盖。

可以新增 `scripts/personal-experience/r04-openclaw-native-update-smoke.py`，
其接口和异常清理遵循现有脚本；新文件属于计划新增，不应假定已经存在。

### 7.2 需要完成的实际旅程

1. 准备无害 V1/V2 本地 Skill，声明明确的最小读权限；设置允许文件和禁止访问的合成 canary。
2. 在专属 OpenClaw profile 经产品导入、比较、确认和安装 V1，确认权限后接入。
3. 由真实 OpenClaw 工具路径读取 V1 对应数据，关联实际调用、Grant、安装内容摘要、SEC 与回执。
4. 导入 V2 候选并展示内容与权限差异；取消更新后证明仍运行 V1，权限没有变化。
5. 再次比较、确认更新，证明 V1 对应旧 Grant/身份/上下文失效，V2 未经新的必要确认不自动获得权限。
6. 按既有合同重新授权/绑定 V2，在真实宿主加载 V2 后再次执行，证明实际加载内容与新摘要一致。
7. 安全移除后验证目标文件、授权、身份及宿主配置的最终状态；未知用户文件必须保留。

OpenClaw 已有会话级归属限制要继续标注。需要重建会话/重新加载目录才能切换 Skill 时，
必须将步骤和原因写入 UI/证据，不允许通过手工替换生产状态让旧会话“看起来已更新”。
若原生接口无法支持某一步，开发安全拒绝和清晰诊断，保留该项 blocked/partial。

### 7.3 负向与并发验收

| ID | 场景 | 预期 |
| --- | --- | --- |
| UP01 | 检查发现 V2 | 只产生检查/调度数据，不自动安装、提升权限或确认 |
| UP02 | 取消、重复点击、丢响应 | V1 不变；重复请求不造成二次更新；通过操作查询识别真实结果 |
| UP03 | 比较/确认后候选变化 | 在最终写入前发现摘要或绑定漂移并拒绝，不落入 TOCTOU 放行 |
| UP04 | 内容/权限增加 | 明确展示；差异截断必须提示；旧确认不能批准新增权限 |
| UP05 | 检查、更新、移除交错 | 不覆盖较新状态，不恢复已撤销 Grant，不删除未知文件 |
| UP06 | 用户修改安装目标 | 按合同拒绝或进入显式冲突恢复，不静默覆盖/归咎于升级成功 |
| UP07 | 未来/损坏/陈旧签名状态 | 所有相关写操作拒绝；停用等操作也不能覆盖不兼容状态 |
| UP08 | 重启/中断 | 恢复步骤依据真实事务记录；未确定是否生效时不直接重试写入 |
| UP09 | 复用旧上下文 | 旧版本 Grant、会话绑定或 SEC 不能授权新版本；拒绝需证明无相应工具副作用 |
| UP10 | 来源关闭与不可达 | 保留既有来源签名校验和停用语义；失效来源不改安装与权限 |

本批可先用本地目录完成“真实宿主＋本地来源”的更新链。
生产 Git 仍服从 R03；本地候选导入不能证明公网自动检查，也不能单独关闭完整 J6。
目录中的未知候选代码不能在扫描/导入阶段执行；原生测试只执行明确自建无害素材。

## 8. L3：R07 浏览器到真实宿主的完整旅程

### 8.1 原则

复用 L1 的最终候选与隔离实例，真实浏览器连接实际 daemon，
再由真实 OpenClaw 工具调用产生结果。不要把几组各自通过、使用不同 binary/profile 的脚本拼成一条完整旅程。
可以用 Playwright 合成操作者点击；必须区分“自动化操作者”与真人体验验收。

复用 `session-browser-smoke.py`、`confirmation-inbox-browser-smoke.py`、
`confirmation-notifications-browser-smoke.py`、`raw-content-settings-browser-smoke.py`、
`raw-content-task-browser-smoke.py` 和 `r02-linux-desktop-notify-smoke.py`。
先识别其中 API route fixture 与真实后端覆盖：被测端点不能 mock 后再声称真实服务已通过。

### 8.2 最低旅程

1. 安装/启动、配对进入 UI，发现默认及非默认位置的 Agent/Skill。
2. 用户确认目标实例及权限后接入；取消接入不改配置。
3. 真实宿主执行允许动作；执行越权动作时 UI 和回执一致且无禁止副作用。
4. 合同支持的额外审批进入 SIQ；确认后最终参数/版本/撤权再检查；重复审批或旧结果不得再执行。
5. 复用 L2 的 V1→取消→V2 确认更新，显示真实版本、权限状态和操作进度。
6. 中断服务或会话，页面给出可操作重连说明；受控调用按合同拒绝；恢复不复活撤销授权。
7. 跟踪任务与回执：显示真实证据等级，不能把接收、批准、工具返回或 readback 合并为已完成效果。
8. 原文默认关闭；显式授权开启后使用合成数据测试范围、到期、撤销和导出隔离。
9. 停止/退出及接入卸载，检查保留的数据和无关配置；重新进入管理流程行为明确。
10. 桌面宽度与移动宽度、键盘操作、取消/重试、切换对象、注销跨标签页和迟到请求隔离。

OpenClaw 原版宿主当前若不能可信恢复 hold，必须保留安全拒绝；
不能自动引入测试检查点到生产适配器并宣称原版宿主支持。
需修改宿主的方案只能作为明确列出的可选待评审方案，不修改现有日常安装。

通知证据至少分两层：总线接受、实际可见。只有总线回执时不能标为视觉通过；
headless Chromium 截图只能证明网页状态，不能证明 OS 通知弹窗。

隐私到期测试：组件层可注入受控时钟；真实 daemon 用受支持的短期授权等待实际到期，
不改整机时钟，不直接编辑已签名状态制造结果。秘密 canary 不得出现在禁止的 UI、日志或导出。

## 9. L4：验证命令与最终候选

先按修复模块跑聚焦正负向测试；工作包稳定后再跑必要全量，不每改一行就重复所有重测试。
使用现有锁文件与环境，缺依赖明确记录，不擅自升级依赖以处理无关问题。

```bash
# Go 模块；gofmt 只修改本批改动文件，提交前要求检查无输出
cd apps/agentshield
go vet ./...
go test ./...
# 竞态检查覆盖实际改动的并发包；例如 state / skillinstall / server，
# 不为凑数量跑与本批无关的性能重测。

# Python 应用
cd ../control-api
uv run ruff check app
uv run pytest -q

# Web；最终 Go 候选必须在 build:local 之后重建
cd ../web
npm test
npm run build
npm run build:local

# 仓库根目录
git diff --check
```

脚本测试按现有 Python/Playwright 环境运行，先查 --help 确认参数。
已有真实用户服务测试的开关为：

- `SIQ_TEST_SYSTEMD=1` 与 `SIQ_TEST_BINARY=<绝对可信候选路径>`：
  `scripts/personal-experience/test_systemd_user_service.py`。
- `SIQ_TEST_UPGRADE_SYSTEMD=1` 与 `SIQ_TEST_BINARY=<绝对可信候选路径>`：
  Go `TestNativeUserServiceUpgrade` 和 `TestNativeUserServiceUpgradeTransientFailure`。

只有完成 L0 归属/环境检查后，才能通过子进程 env 启用这些测试。
测试被 skip 不等于实机通过；共享用户 manager 的测试必须串行，防止生命周期竞争。

Go 最终候选四目标构建：
`CGO_ENABLED=0`，`linux/amd64`、`linux/arm64`、`darwin/arm64`、`windows/amd64`。
输出到本批临时目录，记录 Go 版本、命令和每个摘要。交叉构建不填 Win/mac 实机验收。

若源码、生成嵌入资产或宿主补丁改变，旧最终候选证据不能直接套用。
受影响旅程必须重新执行；未影响的历史证据只能按规则注明继承与差异评估。

## 10. 证据、矩阵和清理

建议每个工作包新建独立目录：

- `docs/evidence/personal-experience/r06-linux-lifecycle-<timestamp>/`
- `docs/evidence/personal-experience/r04-openclaw-native-update-<timestamp>/`
- `docs/evidence/personal-experience/r07-linux-user-journey-<timestamp>/`

每批至少有 report.md、结构化逐项结果、环境/源码/二进制身份、
命令及退出码摘要、脱敏前后状态证据、必要截图和 SHA256SUMS。
这些是建议文件布局；N09 的 leg/matrix 必须使用已有 schema 字段，
不要把建议的文件名当成新的机器协议。

每条结果包含或可追溯到：

- 稳定检查 ID、预期、实际结果、pass/fail/blocked/unverified、证据级别。
- 真实执行过的路径、声明能证明什么，以及不能证明什么。
- 同一次运行的源码/二进制/OS/CPU/宿主版本/profile 类型。
- 拒绝是否真的零副作用，事务是否恢复，清理是否完成。

复用 `scripts/personal-experience/n09_evidence.py`、
`n09-baseline-check.py`、`platform_acceptance.py` 及其测试。
注意 `n09-current-candidate-matrix.py` 当前有固定旧 leg 路径和默认输出目录：
先检查实现，不能原样运行覆盖旧矩阵。可以小范围改为显式新输入/输出，并加相应负向验证。

最终运行：

```bash
python3 scripts/personal-experience/n09-baseline-check.py --matrix <本批新矩阵路径>
```

J1–J11 编号、九组合和完成条件保持不变。schema valid 只代表结构与引用有效；
本机 Linux 成果不能升级 Windows/macOS、WorkBuddy 或未经完整验收的 J 行。
证据分层可写单测/组件、真实子进程、服务 HTTP、真实宿主＋模型替身、
真实用户服务、浏览器＋真实服务、人工视觉确认；模型替身不能伪装成真实外部模型。

脱敏检查覆盖 token、配对码、私钥、认证头、完整私人 URL、原始敏感输出和私人路径。
截图必须在配对码消失或遮蔽后采集；报告不粘贴原始凭据命令行。
测试失败同样保留脱敏结果；不删失败样本再把同一轮记全绿。

结束时逐项列出本批创建和停止的进程/端口/单元/profile，验证无遗留监听，
且预先记录的日常服务、配置和无关文件未改变。只清理明确归属的临时对象；
无法证明可安全回收时保留现场并记录。

## 11. 完成条件与停走规则

本批“本机阶段可验收”的条件：

1. L1–L3 每个要求有明确状态，已执行部分有真实链路证据；
   仍需登录/重启、正式签名、公网、GUI 或宿主能力的部分准确列出解除条件。
2. 可在当前环境修复的实现问题已修复，安全负向证明旧行为被拒绝；
   不靠跳过、放宽断言、修改既有失败状态来通过。
3. 最终候选通过相应验证，证据和源码摘要一致；新的 N09 行只引用本次真正覆盖的检查。
4. 更新总体任务书第 8/9/10/15 节的相关状态和 closure-progress；
   外部缺口未关闭时整体仍为 partial/doing。
5. 无无关配置、密钥、宿主源码或日常服务改动；无未经授权提交/推送/发布。

发现以下问题先停止该条有副作用的测试，完成复现和修复后才能恢复：
权限绕过、旧凭据/版本复活、用户未知文件被覆盖或删除、密钥外泄、
未获确认的自动更新、无法确认归属的服务控制。
这是停止危险路径，不是停止所有开发；继续不依赖该路径的只读检查、测试和修复。

外部受阻不能用“后续建议”替代本机可完成实现。也不能无限重试同一受阻环境：
记录一次可复现证据和解除条件，转入可执行工作包。

## 12. 沟通与最终报告

收到提示词后先在一条简短回复中说明实际 HEAD、工作树、拟先做的检查；
不要沉默十分钟后才一次性输出。持续工作时约每分钟给出简短进度，
说明已证实什么、正在排查什么及接下来验证什么。长测试后台运行并按阶段汇报。

最终报告必须包含：

1. 完成项：按 L1/R06、L2/R04、L3/R07 分开列代码改动和解决的问题。
2. 实际验证：命令、退出码、测试结果、真实证据等级；不能只说“全部验证通过”。
3. 仍有缺口：逐项外部条件、产品限制、能否继续推进及解除条件。
4. 证据路径：新报告、原始脱敏数据、矩阵、截图和摘要文件。
5. 影响与恢复：数据/服务改动范围、清理结果、潜在兼容限制。
6. Git 状态：基线 HEAD、修改清单、是否提交/推送/合并/发布，分别如实报告。

现在从 L0 开始执行，随后持续推进可执行的 L1、L2、L3 和最终验证。
不要只回复计划，不要重做已验收 O04，也不要提前切入团队或 OpenShell 新功能。
