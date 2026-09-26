# 个人体验开发验证工具

本目录起源于 UX-003、UX-004、UX-005、UX-012，现还包含实例接入、Skill 生命周期、审批/隐私、客户端恢复及 Linux 双宿主验证。各脚本使用显式候选程序，验证本地管理与启动流程。需要 Python 3；浏览器验证另需 Playwright 和 Chromium。正式安装包的“无需开发工具”交付由 UX-014 承担。

## 先选择验证对象

- 当前任务、候选和未闭合项从[开发导航](../../docs/development/current.md)进入；已合入主线的范围与剩余门禁另见[主线整合](../../docs/development/main-branch-integration-20260926.md)和[全面验收](../../docs/development/enterprise-comprehensive-acceptance-review-20260926.md)，不把脚本存在或 CI 通过视为正式发行/原生验收。
- Linux 双宿主按 [LX00–LX10 任务书](../../docs/linux-dual-host-integration-development-taskbook-20260918-205119.md)选择脚本；第六代功能与第八代 UI 分开记账。
- 个人生命周期与浏览器场景查[工具索引](../../docs/development/tools.md)；正式包验签和原生启动改用[发行工具](../release/README.md)，自建候选不继承正式签名身份。

运行前读所选脚本的 `--help` 与任务书，确认独立状态/profile、宿主二进制和输出位置。涉及配置、注册或生命周期的脚本需满足其显式确认参数；只读诊断不能替代完整执行。证据应包含源码/程序/UI 摘要、宿主版本、实际调用与副作用，并保留失败和 partial/blocked。不要上传私密状态、token 或配对输出。

## 构建

在仓库根目录执行：

```bash
cd apps/web
npm ci
npm run build:local
cd ../agentshield
go build -o ../../.tmp/personal-experience/siq-agent-security ./cmd/agentshield
cd ../..
```

本地构建不等于已签名的发布制品。不要把来源不明的程序传给启动工具。

## 启动和配对

```bash
python3 scripts/personal-experience/start-local.py \
  --binary .tmp/personal-experience/siq-agent-security \
  --state-dir "$HOME/.local/state/siq-agent-security-personal-dev" \
  --port 47612 --open

SIQ_AGENT_SECURITY_STATE_DIR="$HOME/.local/state/siq-agent-security-personal-dev" \
  .tmp/personal-experience/siq-agent-security pair --port 47612
```

在 Windows 上使用 `python`、对应 `.exe`，并通过 `$env:SIQ_AGENT_SECURITY_STATE_DIR` 指定同一状态目录。Windows 的空闲回环端口可能约两秒后才返回明确的连接拒绝；启动工具为此最多等待五秒，只有明确拒绝才继续初始化。探测超时、权限错误或其他未知网络错误仍拒绝启动，也不创建状态。真实宿主和完整系统生命周期的验收独立记录。

服务启动后的就绪等待默认十五秒。若本机实测启动较慢，可显式传入 `--timeout 60` 延长本次等待；超时仍报告未就绪并保留自己启动的进程供诊断，不能据此认定健康或清除写锁。该选项不改变端口探测、初始化和单次健康检查的超时。

工具会先验证健康协议，直接解析子进程输出的 JSON 字节，不用 Windows 控制台代码页解码协议或诊断输出。端口上的其他应用或旧版服务不会被当作启动成功，也不会被终止；正常服务会复用。后台运行不会收集配对码日志。服务未就绪时保留诊断提示，不自动清除写锁。该入口没有安装系统服务或登录启动项，关闭系统会话后的行为按系统另行验收。

配对有效期内刷新页面和打开同源新标签页会恢复管理会话；“退出管理”使对应会话及恢复 Cookie 失效。服务重启后再次运行 `pair`，无需为了获取新配对码再次重启服务。

健康检查：

```bash
.tmp/personal-experience/siq-agent-security status --port 47612
```

`status` 只识别协议与可达性；不会证明同用户恶意进程无法伪装服务。健康服务的复用基于所选端口，调用者应保持启动与配对使用同一状态目录。

## 浏览器与启动回归

```bash
python3 -m pytest scripts/personal-experience/test_start_local.py -q
python3 scripts/personal-experience/session-browser-smoke.py \
  --binary .tmp/personal-experience/siq-agent-security \
  --out-dir .tmp/personal-experience/browser
```

原生二进制测试通过 `SIQ_TEST_BINARY` 显式指定本机自建程序；在已观察到慢启动的机器上，可为这组测试设置 `SIQ_TEST_START_TIMEOUT=60`。这只调整原生测试的就绪等待，不跳过身份复验和错误端口拒绝。正常生命周期测试使用 `stop --confirm-stop` 完成服务排空，再检查重新启动，不用 Windows 强制终止代替正常停止。

浏览器脚本自行启动独立状态目录和端口，最后清理它启动的服务。输出只含检查结果、制品哈希和无凭据截图。该结果验证管理会话，不代表 OpenClaw/Hermes/WorkBuddy 真实运行时接入通过。

加上 `--discovery` 可验证分类目录、同名安装区分、共享多消费者、显式重扫更新版本、手动目录预览与重启后恢复，以及移动端导航与扫描页面。还会在临时 Home 安装测试适配器，验证文件存在不宣称运行保护、OpenClaw 禁用后的诊断及 WorkBuddy 独立待验证状态；不读取或修改用户平台配置。

设计依据：[ADR-019](../../docs/adr/0019-local-session-recovery.md)。开发状态：[持续台账](../../docs/personal-experience-development-progress-20260910.md)。

## 安装后权限准备与实例接入（M27）

```bash
python3 scripts/personal-experience/installed-permission-browser-smoke.py \
  --binary .tmp/personal-experience/m27-linux-arm64 \
  --out-dir .tmp/personal-experience/installed-permission-browser
```

需要已安装 Playwright 和 Chromium 的 Python 环境。脚本使用隔离 daemon、合成操作者和临时 Hermes profile，覆盖明确确认、提交响应丢失、重复点击、刷新只读恢复、实例与 Grant 锁定、旧身份明确停用、签发新身份及接入配置、自检目标预选与内容变化失效。自检入口不会自动执行，运行侧另用 `installed-skill-runtime-native-smoke.py` 的公开 Hermes CLI 验证；浏览器截图不代表原生运行或跨 OS 验收。参见 [ADR-042](../../docs/adr/0042-installed-permission-readiness.md)。

## 已安装 Skill 内容检查（M28）

```bash
python3 scripts/personal-experience/installed-skill-inspection-browser-smoke.py \
  --binary .tmp/personal-experience/m28-linux-arm64 \
  --out-dir .tmp/personal-experience/installed-skill-inspection
```

脚本通过真实浏览器完成安装后进入记录页，实际等待 30 秒检查周期，验证修改/缺失/未知目录、请求失败后撤下旧状态、历史记录与原操作跳转、窄屏展示。页面隐藏/恢复通过受控 visibility 事件夹具验证，不能视为所有浏览器或 OS 标签页行为验收。所有改动仅发生于临时安装与状态；不会执行未知内容、更新或卸载用户 Skill。实现边界见 [ADR-043](../../docs/adr/0043-installed-skill-inspection.md)。

## 明确移除的原生权限验证（M29）

```bash
python3 scripts/personal-experience/installed-skill-runtime-native-smoke.py \
  --binary .tmp/personal-experience/m29-linux-arm64 \
  --hermes-cli /path/to/hermes \
  --remove-installed-skill \
  --out .tmp/personal-experience/native-removal.json
```

脚本使用公开 Hermes CLI、隔离 profile、合成模型与临时 daemon。先验证正常读、越权写拒绝和独立自检，再通过正式管理 API 移除刚安装的测试 Skill。它确认实例身份此前 issued，未调用身份撤销接口，移除后 Grant 已撤销、身份变为 grant_unavailable、目标不存在，再由新的原生会话验证三个工具调用全部拒绝。输出中 authority_withdrawal 区分 Skill 移除与原有身份撤销回归；省略该开关继续执行原身份撤销流程。旧证据不改写。

Go 测试另行覆盖五个独立子进程退出点、原请求重试、未知用户内容保留、共享 Grant 保留、待撤销权限不能接到另一安装和完成后的路径复用。目录归属标记丢失时保留现场，需要用户核对空目录后再重试。该脚本不验证移除前端，也不代表跨系统或可信 Skill 调用归属验收。见 [ADR-044](../../docs/adr/0044-explicit-skill-removal.md)。

## 个人版移除确认与恢复（M30）

```bash
python3 scripts/personal-experience/skill-removal-browser-smoke.py \
  --binary .tmp/personal-experience/m30-linux-arm64 \
  --out-dir .tmp/personal-experience/skill-removal-browser
```

脚本从真实浏览器安装流程进入已安装记录，验证打开/取消不写入、明确确认、冻结背景操作、双击去重、写响应与后续查询同时丢失、重新查询和刷新恢复、未知用户内容保留、原请求重试、完成后仅查看历史及同路径新文件保留。截图覆盖桌面确认和窄屏恢复窗口。夹具模拟操作者把新增笔记移出安装目录后再确认恢复；SIQ 不自动处理用户内容。运行时撤权另由 M29 原生脚本验证，浏览器不声称三系统或原生 Skill 归属通过。

## 明确更新事务验证（M33）

在 `apps/agentshield` 中运行：

```bash
go test ./internal/skillinstall ./internal/server -run 'TestConfirmedUpdate|TestUpdateCommit|TestUpdateRecovery|TestUpdateFailure|TestUpdateSuccessful|TestUpdateTransaction|TestUpdateInterrupted|TestUpdateChanged|TestSkillUpdateTransaction' -count=1
```

测试使用临时状态/平台目录，覆盖明确确认后的旧权限撤销与新文件发布、失败清理、未知用户文件保留、历史结果、普通安装重放拒绝及管理 API 分权。六个子进程以退出码 77 模拟实际进程中断，新进程重新打开状态再继续或恢复，不把内存异常当作进程重启验证。合同样例以固定签名准备计划规范化，Python 另验签和检查引用。既有原生脚本在 M33 候选上仅回归安装/运行/移除；前端及真实平台更新旅程尚待接入。见 [ADR-047](../../docs/adr/0047-confirmed-skill-update-transaction.md)。

## 个人版 Skill 更新页面（M34）

```bash
python3 scripts/personal-experience/skill-update-browser-smoke.py \
  --binary .tmp/personal-experience/m34-linux-arm64 \
  --out-dir .tmp/personal-experience/skill-update-browser
```

使用真实 Chromium、临时 daemon/profile 和合成 Skill，检查候选差异、未批准禁止准备、刷新只读、明确确认与双击去重、提交和查询响应丢失、恢复历史及容量失败后的终止。脚本在临时私有暂存目录制造容量限制；不修改用户平台。截图检查桌面和移动确认入口。此脚本不执行原生智能体更新后的工具调用，不代表跨 OS 或可信 Skill 归属验收。原移除浏览器回归在关闭触发内容检查后等待 aria-busy=false，再重新打开窗口。

## Linux/Hermes 原生 Skill 更新（R04-E）

```bash
python3 scripts/personal-experience/r04-hermes-native-update-smoke.py \
  --binary .tmp/personal-experience/siq-agent-security \
  --hermes-cli /path/to/hermes \
  --out .tmp/personal-experience/r04-hermes-native-update.json
```

脚本在隔离 profile 中经产品入口安装并明确预载 V1，执行真实文件读取；随后验证 pending 候选比较和取消零写入、V2 批准/复比/确认更新、旧 Grant 与身份失效、新 Grant 激活与新身份/SEC、V2 明确预载后的真实读取及最终安全移除。模型为本机确定性夹具。V2 是明确导入的本地目录，该结果不代表公网更新源、其他平台或其他 OS 已验收。

## 草稿在途提交 HTTP 门控回归与变异复跑（KIMI-001-R1-B1）

`apps/agentshield` 的 `TestGrantDraftHTTPInflightWriterConverges` 经真实 HTTP handler 覆盖草稿创建的在途提交窗口（grant 已发布、done 未发布）：窗口内第二请求必须等待并收敛到同一草稿。该测试随 `go test ./...` 与 CI 常规回归执行。

同一测试对旧行为（handler 对 ErrIncompleteCommit 立即 409）必须确定性失败的变异检查，在隔离 worktree 中复跑：

```bash
python3 scripts/personal-experience/grant-draft-inflight-mutation.py
```

脚本只在 HEAD 的临时 worktree 内精确恢复旧分支片段（基线片段缺失或非唯一即拒绝），核对旧代码失败签名为预期的 409/幂等断言（而非编译失败、超时或其他错误），恢复后验证通过；不修改用户工作区，不提交任何恢复旧行为的代码。输出为含命令与退出码的 JSON 摘要。

## 平台发现与 Hermes 批准边界原生探针（K002）

```bash
python3 scripts/personal-experience/discovery-native-smoke.py --binary .tmp/personal-experience/siq-agent-security --out .tmp/personal-experience/discovery-native.json
python3 scripts/personal-experience/hermes-approval-gap-native-smoke.py --hermes-cli /path/to/hermes --binary .tmp/personal-experience/siq-agent-security --out .tmp/personal-experience/hermes-approved-retry.json
```

发现探针在隔离 HOME 中构造两个不同名 Hermes profile（含同名不同版本合成 Skill）与 OpenClaw 状态目录，驱动候选 daemon 真实扫描：实例身份与 Skill 安装分开、归属正确、正文与私人目录内容不进入响应。批准缺口探针用公开 Hermes CLI 与真实 daemon 验证：需批准工具在 Hermes 保持 hold→block（不执行）、控制台批准后无原生恢复路径、拒绝后重试仍不执行；它记录当前缺口，不代表批准恢复已实现。两者均用合成操作者与临时状态，不读取用户配置、不调用真实模型。

## OpenClaw 可信 Skill 上下文原生验证（R01）

```bash
python3 scripts/personal-experience/r01-sec-openclaw-native-smoke.py \
  --openclaw-root /path/to/openclaw/source \
  --node /path/to/node \
  --binary .tmp/personal-experience/siq-agent-security \
  --out .tmp/personal-experience/r01-sec-openclaw-native.json
```

脚本使用隔离 HOME、公开 `openclaw agent --local` 入口、本机确定性模型夹具和真实文件工具，依次走产品导入、权限、安装、激活、适配器身份和原生会话。它验证无 SEC 拒绝、session 级签名 SEC 放行、调用绑定、撤销后同会话拒绝，并用 `openclaw skills list --json` 确认独立发布的 Skill 可被原生加载器发现。该目录发现不能单独证明某次模型调用由指定 Skill 因果触发；不调用外部或付费模型，也不代替 Windows、macOS 与 WorkBuddy 验收。

## Linux 桌面通知总线验证（R02-G）

```bash
python3 scripts/personal-experience/r02-linux-desktop-notify-smoke.py \
  --out .tmp/personal-experience/r02-linux-desktop-notify.json
```

脚本启动隔离候选 daemon，创建真实签名 pending hold，并用 `dbus-monitor` 验证产品 count-only 通知经 `notify-send` 到达当前 GNOME session bus。它断言总线消息不含工具调用、action、receipt 或参数，随后明确拒绝 hold 并验签。需要 Linux、`notify-send`、`dbus-monitor` 和可用的 session D-Bus；总线接受不等于能从远程终端证明屏幕渲染或用户注意。

## 当前候选 N09 逐行矩阵

```bash
python3 scripts/personal-experience/n09-current-candidate-matrix.py
python3 scripts/personal-experience/n09-baseline-check.py \
  --repo . \
  --matrix docs/evidence/personal-experience/n09-current-candidate-20260915/matrix.json \
  --summary docs/evidence/personal-experience/n09-current-candidate-20260915/summary.json
```

生成器要求六条输入报告全部通过且使用同一个候选二进制，再按报告实际检查项生成 9 格 × J1–J11 coverage。输出没有 `complete_acceptance` 行；校验通过只证明证据摘要、同候选绑定及声明范围有效，不表示 N09 或发行验收完成。
# Linux 用户服务原生验证

在已有 Linux 用户 systemd 管理器的隔离测试环境，从 `apps/control-api` 执行：

```bash
SIQ_TEST_SYSTEMD=1 SIQ_TEST_BINARY=/absolute/trusted/siq-agent-security uv run pytest ../../scripts/personal-experience/test_systemd_user_service.py -q -o addopts=''
```

该显式测试创建随机名 runtime-only 用户服务链接，真实启动、复用、重启、配对和停止，再校验归属后清除链接。不 enable 登录自启动、不操作已有单位；需要可用的用户服务管理器。缺少任一显式环境变量时跳过，不计入原生验收。此测试不替代产品自动安装、强杀恢复、注销/重启主机、其他 OS 或智能体平台验证。
