# Luke-zzZ-0 / Codex：macOS 真实环境实测与开发优化任务书

> 版本：1.0；时间：2026-09-13 20:23:55（Asia/Shanghai）。
> 负责人：Luke-zzZ-0；执行工具：Luke 本机 Codex；目标仓库：`maoyadongsh/siq-agent-security`。
> 编制基线：`0720730f821373b00bb8bfd5ec870fec147e5746`；执行时抓取最新上游，并固定每批代码候选。
> 当前设备版本、CPU、三个宿主安装情况未知。不得预设 Apple Silicon、Intel、macOS 最低版本或宿主支持能力。

> **2026-09-16 用户范围裁决**：本轮 Mac-P00–P05 只以本机 Apple Silicon / macOS arm64 原生组合为实机架构目标；用户明确放弃 Intel/amd64 实机及 Rosetta 验收，不再把它们列为本轮完成阻塞。既有 18 行材料合同中的 macOS/amd64 行仍保留 `not_run`，不得伪填 pass、删行或据此宣布 Intel 受支持；若未来重新纳入，另立真实 Intel 候选与证据。Go 四目标交叉编译仍是代码门禁，不等于 Intel macOS 实机验收。其他宿主能力、GUI、旧版恢复与独立审阅缺口不因本裁决自动关闭。

## 1. 目标、边界与首批交付

负责 OpenClaw、Hermes、WorkBuddy 在真实 macOS 上的本项目接入、实测、问题定位和适配修复，通过 PR 交付。复用已合入 main 的 Go 客户端、前端、LaunchAgent、配置备份、权限和状态协议，补齐真实桌面、宿主、升级恢复和完整用户旅程。

先读 [共享协作验收规则](personal-platform-collaboration-acceptance-20260913-202355.md)、[总任务书 v3.0](personal-experience-lan-team-next-development-taskbook-20260913-192253.md)、适用 AGENTS、[本地规格](agentshield-dev-spec-v1.md)、[N01 协议](n01-state-protocol-design-20260913.md)、[平台材料规格](personal-platform-validation-spec-v1.md)。本书是 N01/N04/N06/N07/N08/N09 的 macOS 子批次，不新开独立安全产品或 LAN 阶段。

第一批直接执行 **Mac-P00 环境盘点 + Mac-P01 原生构建和管理基线**。缺某宿主、登录会话或第二种架构，阻塞具体项并继续其他可执行项目。你负责修复 OS 问题；公共核心由 GLM 与平台负责人协调主修人，不能只把所有错误交回 GLM。

## 2. 已有代码与真实缺口

下表 `cmd/`、`internal/` 均位于 `apps/agentshield/`；路径是编制时核对的现有入口，不是实机验收结论。

| 能力 | 位置 | 本机需要证明的内容 |
| --- | --- | --- |
| LaunchAgent 配置 | `cmd/agentshield/launch_agent.go`、`launch_plist_reader.go`、`internal/state/launch_agent.go` | 规范绝对路径、实例 label、签名源与实际系统配置一致 |
| 注册/加载 | `launch_agent_register.go`、`launch_agent_presence.go`、`launch_agent_load.go` | 当前 GUI 用户域、精确登记、未知配置拒绝、加载与启动区分 |
| 运行/退出 | `launch_agent_start.go`、`launch_agent_status.go`、`launch_agent_stop.go`、`launch_agent_unregister.go` | 实际进程、健康身份、停止与 Writer、卸载归属 |
| 组合 setup | `cmd/agentshield/setup_launch_agent.go` 与 `main.go` | 用户域预检、注册/启动/打开 UI 的实际行为，不能只看单测 |
| 状态和文件保护 | `internal/stateformat/`、`statefs/`、`state/`、`fileopen/` | APFS/权限/链接/原子发布/实例绑定和 N01 原生恢复 |
| 发行/升级 | `internal/clientrelease/`、`skillmanifest/` 及 CLI | 实际制品摘要、签名兼容声明、副作用前预检与 macOS 升级组合 |
| 发现和接入 | `internal/inventory/`、`adapterinstall/`、`connectors/workbuddy/` | 多 profile、自定义路径、已有配置备份还原、WorkBuddy 独立验证 |
| 宿主桥 | `adapters/runtime/openclaw-agentshield/`、`adapters/runtime/hermes-agentshield/` | 真实宿主加载、pre/post、可信上下文、审批执行前重查 |
| 通知/管理 | `internal/notify/`、`pending/`、`server/`、`apps/web/src/local/` | macOS 默认通知基线未实现；真实投递/导航、配对恢复和隐私 |
| 实测材料 | `scripts/personal-experience/platform_acceptance.py` 及同目录 smoke 脚本 | 复用材料合同与场景，但先剔除 Linux 专属运行假设 |

基线 plist 的 `RunAtLoad=false`、`KeepAlive=false`，日志输出到 `/dev/null`。这是当前代码行为，不能据此宣称登录自启/崩溃自动重启已完成。需要新生命周期语义时先更新规格、签名/实际配置验证和用户确认，不直接改系统 plist 绕过程序归属。

已有 N01 仅达到代码与 Linux 最低门槛。Git 生产获取、自动检查、可信 Skill 归属和真实审批继续执行仍有接续工作；每批核对 GLM 已合入代码，未合并报告不能当作当前能力。

## 3. Mac-P00：环境、架构与隔离范围

**产物：** environment.md、三个宿主初表、测试目录/用户域/会话说明、工具版本、缺口与下一批。

1. 记录 macOS 产品版本/build、实际机器 CPU 架构、当前终端进程架构、Go 工具链架构；Apple Silicon、Intel、Rosetta 翻译执行分开。不要把 `uname -m` 一条命令当作硬件及所有进程架构的共同证明。
2. 记录文件系统/卷特性、大小写敏感性、源码/构建/状态/profile 目录；同步盘、外置卷和网络目录不自动当受支持状态目录。
3. 确认当前 GUI 登录会话、终端/SSH/Codex 运行方式、浏览器与通知权限，以及是否具备可安排的退出登录/重启验证窗口。SSH shell 可运行 CLI 不代表桌面通知或 GUI 用户域已验证。
4. 三宿主分别记录实际安装来源/版本、命令或应用入口、profile 和 Skill 路径、可观察钩子/扩展能力。仅从最新官方资料和本机行为得出支持结论，记录来源 URL 和日期；本文件不保证任意宿主版本支持原生 macOS。
5. 选择专用 OS 测试用户或明确独立的 profile/状态实例；声明哪些目录和服务 label 属于本次测试。日常 LaunchAgents、真实凭据、Keychain 内容和用户任务不在测试操作范围。
6. 记录 Go、Node/npm、Git、Python/uv 和浏览器版本；race 或本机编译器不可用单列，不自动运行 sudo 安装工具或改变全局安全策略。

只读盘点示例，未知 sysctl key/缺工具如实记录，不把缺 key 的错误改成架构证明：

```bash
sw_vers
uname -m
arch
sysctl -n hw.optional.arm64
sysctl -n sysctl.proc_translated
go version
go env GOHOSTOS GOHOSTARCH GOOS GOARCH CGO_ENABLED
node --version
npm --version
python3 --version
uv --version
```

不运行完整 system_profiler/Keychain 导出到公共证据；需要只读查询时仅采所需字段，脱敏主机名、用户名、路径、设备标识和账号。检查 Gatekeeper/隔离属性时保留真实信任提示，不用全局关闭、删全部 quarantine 或 ad-hoc 签名伪称正式发行通过。

**P00 退出：** 至少明确一个可测的原生组合；另一 CPU 架构和缺宿主的项保持未测。Rosetta 结果在报告单列，不能填成真实 Intel 机器的 native pass；现有合同不能表达的新组合先协调增量。

## 4. Mac-P01：源码、原生构建与首次使用

### 4.1 独立分支与受测候选

在 Luke 自己机器的 repo 执行，不使用维护者的 Linux 绝对路径。`origin` 若是 fork，下方最新 main 要替换成指向官方仓库的上游远端。工作区有改动先隔离保留，不 reset/clean。

```bash
SiqRepo="$(git rev-parse --show-toplevel)"
cd "$SiqRepo"
git status --short --branch
git fetch origin --prune
# 检查 fetch 成功及上游归属后执行：
SiqStamp="$(date +%Y%m%d-%H%M%S)"
git switch -c "codex/macos-luke-p01-$SiqStamp" origin/main
git rev-parse HEAD
```

不要自动接入其他开发者的未提交目录。每批固定上游/实现 SHA；文件变化后建立新候选并重测受影响部分，不能把旧日志 candidate 改成新值。正式 18 行材料在干净代码候选构建/执行后生成。

### 4.2 构建现有产品

当前本地模式构建使用已有 npm 锁文件与 Go 标准库；开发工具不是最终用户必须安装的产品依赖。以下命令在失败时停止，避免误用旧产物：

```bash
(
  set -eu
  cd "$SiqRepo/apps/web"
  npm ci
  npm run build:local
)
# 上一步成功且 embed 变动已审阅后继续：
SiqBuildDir="$SiqRepo/.tmp/personal-macos-$SiqStamp"
mkdir -p "$SiqBuildDir"
SiqBinary="$SiqBuildDir/siq-agent-security"
(
  set -eu
  cd "$SiqRepo/apps/agentshield"
  env -u GOOS -u GOARCH CGO_ENABLED=0 go build -trimpath -o "$SiqBinary" ./cmd/agentshield
)
file "$SiqBinary"
shasum -a 256 "$SiqBinary"
```

执行前确认 GOHOSTOS=darwin，记录宿主工具链/进程架构。Apple Silicon 上翻译执行的 amd64 Go 构建要标对应方式；`file` 输出和真实运行都核对，不能仅按机器商品名填写 arm64。Intel Mac 要生成/执行 darwin amd64 候选，现有 darwin arm64 交叉构建不覆盖它。

正式材料绑定 embed 实际内容。若 npm 构建改变 tracked 资产，审阅、纳入代码候选后再采证；不得测旧 UI。若上一段失败不执行下一段，也不使用同路径残存二进制。构建脚本后续自动化时用单一失败传播流程和独立输出，不能把手动分步说明变成忽略退出码的脚本。

### 4.3 私有状态、启动与配对

先设定 `SiqState` 为 P00 核实的隔离私有目录，不指向日常 SIQ 状态；核对权限/ACL，记录恢复原环境变量的方法。下例端口仅为候选，发现占用不得终止未知进程。

```bash
# 必须先由执行者把 SiqState 设为自己已确认的测试目录。
export SIQ_AGENT_SECURITY_STATE_DIR="$SiqState"
python3 scripts/personal-experience/start-local.py \
  --binary "$SiqBinary" --state-dir "$SiqState" --port 47612 --open
# 确認启动成功后检查实际实例：
"$SiqBinary" status --port 47612
"$SiqBinary" state-status
```

配对使用真实 UI 或已有 `pair --port 47612`，不把配对码/管理员 token 写入证据。验证默认浏览器打开、刷新/新标签页恢复、退出管理、重启后重新配对、错误服务/认证/实例的诊断。Safari 与其他浏览器按本机可用情况记录；只测一个浏览器不宣称全部兼容。

基线首次打开仍是 Go 客户端 + 系统浏览器，不另起 Electron/Tauri 产品。若 OS 阻止本地开发构建，记录构建来源、具体提示和受控解决路径，不关闭 Gatekeeper/SIP 或改用户全局策略。源码构建可以被验证，正式签名/notarization 留作不同证据项。

## 5. Mac-P02：三个真实宿主的发现、接入和权限

按共享 A02–A08，先选择 P00 中已可运行的宿主做一条完整链路，再逐个扩展。不得为赶进度减少 WorkBuddy 范围或复用其他系统证据。

### OpenClaw

- 阅读适配器 `README.md`、`index.ts`、安装器与对应测试，核对当前实际宿主版本和插件钩子；历史 Linux 文档的行为不能直接当 macOS 支持声明。
- 通过已有 `OPENCLAW_STATE_DIR` 设置独立实例并读回实际配置位置；发现→权限预览→确认→配置备份→接入→真实宿主加载→自检，全部绑定同一实例。
- 保护其他插件/profile，拒绝陈旧计划和未知配置；不得注入未经支持的 `security.installPolicy`。安装识别不等于原生安装入口可拦截。
- 用实际宿主工具调用证明允许/越权/失联；hold 若缺可信执行前检查点则阻断并登记。不能在用户配置填能力版本来伪装 `beforeExecute` 已存在。
- 安装后在真正运行入口复测，不只在当前 Terminal 成功：GUI/后台进程的环境、PATH、工作目录可能不同，需要观察并修复本产品适配。

### Hermes

- 核对实际 CLI/Python 环境/profile 与钩子加载，用隔离 profile，经现有 managed-instance 与 `hermes_native.go` 接入。系统 Python、虚拟环境和 GUI/后台启动方式分别记录，不能依赖某开发终端激活的环境偶然成功。
- 按真实宿主语义备份/恢复配置，保留其他设置；签名路径/配置不能用 shell 字符串拼接造成参数解释差异。
- 检查真实 pre/post、session/call ID、身份失效、单次结果关联；扫描或文件匹配不足以建立可信 Skill 归属。
- 宿主回调等待时间和继续执行能力需要本机测；批准后的重试、参数变动、撤销和响应丢失不能绕过最终检查。不能仅延长 HTTP timeout 或让模型口头确认。

### WorkBuddy

- 从真实 macOS 应用/官方资料核对版本、支持 CPU、安装路径、扩展机制、配置和 Skill 来源；需要 GUI 的测试必须在实际桌面交互，不能只执行 CLI 或浏览器 fixture。
- Connector 只能辅助发现。分别证明资产可见、实际工具调用前能拒绝、可信 Skill 归属、安装前拦截；前一个成功不推导后一个。
- 若缺运行前钩子，保留 host_capability_missing/unverified 并形成受控启动/替代设计，与共享负责人协调；不编辑未知闭源内部文件或冒用 CodeBuddy 接口。
- 需要用户权限弹窗时测试允许/拒绝及恢复体验，不能要求用户打开不必要的“完全磁盘访问”来替代限定权限设计。受控测试目录之外的内容不用于试验。

**P02 退出：** 三平台分别有真实环境或明确阻塞，已测平台完成发现/接入/允许/越权/失联/还原；未实现审批/归属/安装拦截保持缺口。无副作用证明必须检查哨兵或受控接收端，不能只看 SIQ 返回 deny。

## 6. Mac-P03：LaunchAgent、文件系统与 N01

### 6.1 当前 GUI 用户域生命周期

入口清单如下；不是无条件自动执行脚本。各命令的实际选项与前提以当前 `main.go`、规格和实现为准。不写未提供的 --force，不强制 kickstart/广泛 bootout。

| 阶段 | 已有入口 | 实机断言 |
| --- | --- | --- |
| 导出/准备 | `launch-agent-plist`、`launch-agent-prepare` | 导出不注册/加载，源配置签名与实例/路径绑定 |
| 注册 | `launch-agent-register` | 仅发布本用户实例精确归属链接，未知同名/外来文件拒绝 |
| 加载 | `launch-agent-load --confirm-load` | 当前 GUI 用户域加载正确源，不能把写文件当加载成功 |
| 启动/检查 | `launch-agent-start --confirm-start`、`launch-agent-status` | 正确进程、配置和本地身份/健康读回，非只看 label 存在 |
| 停止 | `launch-agent-stop --confirm-stop` | 正确实例退出、Writer 可获得、配置保留 |
| 注销 | `launch-agent-unregister --confirm-unregister` | 停止后完整归属校验、系统读回缺席，仅删本产品精确注册链接 |
| 组合安装 | `setup_launch_agent.go` 与当前 setup CLI | 完整失败提示和幂等；不得误报已启用保护/登录自启 |

逐项验证重复调用、无 GUI 用户域、同名未知任务、来源链接/配置替换、程序丢失、错误端口、配置漂移、权限拒绝、健康检查失败。不能从 root/system 域成功反推当前普通 GUI 用户可用。

真实关闭终端、注销/登录、重启、休眠/唤醒和崩溃恢复由操作者安排在测试会话执行。当前 RunAtLoad/KeepAlive 为 false，若产品旅程要求登录启动/自动恢复，必须先设计精确的用户确认、签名源及 manager 读回规则，再实现；不能直接编辑 Library 下 plist 使测试通过。新方案保留默认不擅自自启的选择。

### 6.2 macOS 文件系统与安全边界

- 路径包含空格/中文、Unicode 规范化差异、大小写敏感/不敏感卷、同名不同实例；绝对规范路径、实例绑定和签名摘要一致，不能悄悄指向另一个对象。
- symlink/硬链接、父目录替换、程序/配置链接漂移；不跟随到测试实例外，不以“macOS 常用链接”放弃归属验证。
- POSIX mode、ACL、继承权限与 xattr 分开；有 chmod 不代表全部安全属性恢复。N01 未承诺复制 ACL/xattr，测试报告如实写清，产品依赖新增语义时与核心协调。
- link/rename 排他发布、只读目标、权限不足、跨卷/外置或同步目录、容量不足、被其他进程占用时保持不覆盖未知对象、不暴露半写签名文件。优先在受控小容量测试资源模拟，不填满用户磁盘。
- Gatekeeper/quarantine/notarization 等发行信任与运行时安全独立；不删除所有扩展属性、关闭 SIP/系统防护或把 ad-hoc 签名当正式签名。若交付需要系统信任能力，单列发行流程和凭据阻塞。

### 6.3 N01 本机升级、拒写与恢复

复用 `stateformat/statefs`、`internal/state/migration.go`、`clientrelease` 的合同与测试；测试临时目录，真实备份中有密钥，不能上传。重点完成：

1. 新 init 发布 v2，旧已识别目录不绕过显式迁移。未来读写版本、重复键/非法 JSON、错误目录/实例、嵌套屏障应在副作用前拒绝。`state-status` 看 compatible/status JSON，不以命令退出 0 推定兼容。
2. 从可追溯真实兼容感知 v1 源码/制品建立旧状态和已撤销授权，新候选 `state-migrate --confirm`；核对递归备份、业务摘要/模式、撤销 revision、重复迁移与只读诊断。
3. 每类既有检查点中断/恢复在原实例目录验证，源/备份/计划漂移保留现场拒绝；不移走目录再修改 identity，不删除标记、不回放旧 Grant 来“修复”。
4. 真实旧程序在新状态拒写，前后文件清单/摘要不变。缺 macOS 旧程序且无法从确切支持源码复建时记 blocked；不能改新程序版本号或复制 Linux 二进制冒充。
5. v3 签名发行兼容声明、实际二进制摘要、未知/旧制品、状态不兼容、切换前检查和恢复。Linux `service-upgrade/service-rollback` 不是现成 macOS 原生升级；沿现有 LaunchAgent 与 clientrelease 扩展所需组合并实测。
6. 未进行真实断电实验就不声称断电耐久性；进程中断、测试注入、文件系统错误分别记录。候选只支持明确版本窗口，不宣称任意历史程序都不能写。

**P03 退出：** 本机已有生命周期和 N01 的正负向及恢复材料完整；缺旧制品、登录/重启窗口或架构时该子项不通过，其他修复 PR 可单独交付。

## 7. Mac-P04：通知、审批、安装更新及追溯

### 系统通知与继续执行

先与 GLM/sunbo 确定共享 `Notifier` 的接口、导航与敏感信息边界，再做 macOS 实现。当前 `DefaultCommand` 没有 macOS 默认路径，配置一个能退出 0 的脚本不等于真实投递。

验证实际 GUI 投递、通知被拒、无 GUI、免打扰/后台等本机可复现场景、点击导航到正确 SIQ 待办、重复/失败退避和重启恢复。通知只提供必要计数/概要，不携带 token、原命令或直接批准能力；选择的 OS 投递方案如果不能可靠点击导航，应明确缺口并实现后续方案，不能伪称完成。脚本/原生调用不经用户内容 shell 拼接，子进程原始输出不落日志。

真实审批测试涵盖：未响应不执行、允许本次仅一个实际结果、拒绝/过期/换参/换 Skill/撤销后不执行；平台重试、daemon 重启、迟到批准、重复通知和断网不重复副作用。无法安全透明继续时提示返回原平台重试，并单列该体验与最终目标的差距，不自动重放写操作。

### Skill 与隐私闭环

使用已有本地/HTTPS ZIP 路径验证暂存→检查→权限/内容预览→确认安装→宿主识别→允许/拒绝→检查更新→确认切换→移除恢复。GLM 的安全 Git/自动调度候选通过后再接入本机，不能删除生产拒绝或放宽 URL/文件边界。

测试大小写/Unicode 文件名冲突、候选变化、更新期间文件占用/权限错误、撤销并发、原文采集开关/TTL、损坏密文、导出脱敏、系统休眠与时钟变化。原文默认关闭；活动应准确区分允许、观察到执行、结果已核验、结果未知，不能有回执就写成功。可信归属仍未知时显示 unknown，不以相同文件摘要补造宿主来源。

浏览器体验覆盖键盘/焦点、缩放、中文错误、管理会话、空/加载/失败恢复、通知回到本地页面。至少使用实际后端和真实宿主链，fixture 浏览器另行标注。提出用户步骤优化必须有前后实测，不默认引入新桌面框架。

## 8. Mac-P05：测试材料、完整验收与 PR

### 8.1 开发检查

命令在对应目录执行，依赖使用仓库锁文件；失败即停止该验证链，保留原输出的脱敏版本：

```bash
# apps/agentshield
gofmt -l .
go vet ./...
go test ./...
# 并发/状态/授权改动另跑相关包 race；无工具链时明确未运行并交 CI 补证。

# apps/web
npm test
npm run build
npm run build:local

# apps/control-api：至少合同相关改动
uv sync --dev --locked
uv run pytest app/tests/test_schema_contracts.py
```

gofmt 输出应为空；保存每条退出码，不能只看最后一条命令成功。修改适配器补已有组件测试及真实宿主负向；修改共享规则/服务端按 AGENTS 扩大检查。保留四目标交叉构建，并在 Intel/Apple Silicon 实际拥有的架构上原生运行；CI 的 macOS evidence-tool 不是本机宿主验收。

### 8.2 材料校验与阶段交付

受测源码干净、candidate 为实际 40 位 SHA。先在 repo 外创建本机私有且稳定的证据根 `SiqEvidenceRoot`，只放可提交的脱敏文件；批次 raw/private 状态另放，不能混入 manifest 引用。

```bash
SiqCandidate="$(git rev-parse HEAD)"
# SiqEvidenceRoot 必须事先设为已存在的新批次证据目录。
python3 scripts/personal-experience/platform_acceptance.py init \
  --candidate "$SiqCandidate" --out "$SiqEvidenceRoot/matrix.json"
# 依据真实测试填写本人负责行，其他行保持未测，再执行：
python3 scripts/personal-experience/platform_acceptance.py verify "$SiqEvidenceRoot/matrix.json" \
  --evidence-root "$SiqEvidenceRoot" --candidate "$SiqCandidate" \
  --out "$SiqEvidenceRoot/structure-report.json"
# 上一步必须退出 0；以下仍有组合缺口时退出 3 是预期，不能删除其他行。
python3 scripts/personal-experience/platform_acceptance.py verify "$SiqEvidenceRoot/matrix.json" \
  --evidence-root "$SiqEvidenceRoot" --candidate "$SiqCandidate" --require-native \
  --out "$SiqEvidenceRoot/native-report.json"
SiqNativeExit=$?
# 保存该原始退出码：0 为全部候选 ready_for_review，3 为缺原生覆盖，2 为非法材料。
```

这些是分步命令，不能把 require-native 的预期 3 隐藏或转成全通过。`--out` 排他创建，重复运行另取输出名；父目录先创建。18 行必须全部存在；只测 arm64 的 Mac 不填 amd64/Linux/Windows pass。WorkBuddy 使用真实 native_desktop；录屏可私有保留，合同引用只接受受限 json/txt/log/png，Markdown 报告另存。

脱敏材料归档 `docs/evidence/personal-experience/macos-luke/<batch>-<timestamp>/`；报告包括环境、源码/制品身份、Axx/Nxx、实际命令/步骤、断言、副作用、恢复、未运行、已知限制和清理结果。状态私钥、迁移备份、账号信息和原文不提交；仅按摘要验证的日志仍需人工检查真实性。

首批 PR 推荐 P00/P01 结果和一个真实适配问题修复（若观察到），再按宿主、LaunchAgent、文件/迁移、通知拆分。没有缺陷时交准确基线与待办，不制造无关重构。实现提交先固定候选，证据后续提交；最终 PR head 行为有变化必须重测相关场景。

你可以按本角色授权提交、推送自己的分支并创建 PR；维护者审阅后合并。不直接写 main、不绕过保护、不发布正式安装包或签名标签。缺签名/notarization 环境单列阻塞，不以测试签名代替发行验收。

**平台完成标准：** 当前用户要求的真实 macOS/宿主组合（按 2026-09-16 裁决仅 macOS arm64 原生）及完整 A01–A12 旅程均有可审查证据，关键安全/恢复失败已修复，独立审阅确认。宿主不支持或 GUI 测试缺失继续保留缺口；不在范围内的 Intel/amd64 保持未测、不当作已支持或完成阻塞。单个子批通过不关闭 macOS 总体或 N09。

## 9. 可直接交给 macOS Codex 的启动指令

> 你是 Luke-zzZ-0 的 macOS 平台开发助手。在本仓库最新上游 main 建立独立分支，先读共享协作规则、本任务书、AGENTS、本地规格、N01 与平台证据合同。先完成 Mac-P00 环境盘点和 Mac-P01 本机构建/管理验证，查明 OS/硬件/进程架构、实际 GUI 会话和三个宿主版本，不预设设备。之后逐批实测并修复 OpenClaw、Hermes、WorkBuddy 接入，LaunchAgent 用户域/登录重启、文件安全、N01 迁移/升级恢复、通知/审批、安装更新与隐私追溯问题。复用已有实现，公共模块与 GLM/sunbo 协调主修人；保持权限 hard deny、未知 Skill 归属、一次性调用、状态屏障和签名发布规则。Apple Silicon/Intel/Rosetta 证据区分，WorkBuddy 不能用 CodeBuddy 代替；没有 GUI 或宿主能力的项如实 blocked，继续独立任务。不操作日常实例、不关闭系统防护、不默认 root/付费调用。每批固定干净候选、记录真实副作用和恢复、脱敏落盘，再提交分支/PR 供维护者审阅；不自行合并、发布或改治理。按共享报告模板说明每条结果与未完成项。
