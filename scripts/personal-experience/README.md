# 个人体验开发验证工具

本目录对应 UX-003、UX-004、UX-005、UX-012。它使用当前仓库开发二进制，验证本地管理与启动流程。需要 Python 3；浏览器验证另需 Playwright 和 Chromium。正式安装包的“无需开发工具”交付由 UX-014 承担。

## 构建

在仓库根目录执行：

```bash
cd apps/web
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

在 Windows 上使用 `python`、对应 `.exe`，并通过 `$env:SIQ_AGENT_SECURITY_STATE_DIR` 指定同一状态目录。此路径尚需 Windows 实机验收。

工具会先验证健康协议。端口上的其他应用或旧版服务不会被当作启动成功，也不会被终止；正常服务会复用。后台运行不会收集配对码日志。服务未就绪时保留诊断提示，不自动清除写锁。该入口没有安装系统服务或登录启动项，关闭系统会话后的行为按系统另行验收。

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
python3 scripts/personal-experience/hermes-approval-gap-native-smoke.py --hermes-cli /path/to/hermes --binary .tmp/personal-experience/siq-agent-security --out .tmp/personal-experience/hermes-approval-gap.json
```

发现探针在隔离 HOME 中构造两个不同名 Hermes profile（含同名不同版本合成 Skill）与 OpenClaw 状态目录，驱动候选 daemon 真实扫描：实例身份与 Skill 安装分开、归属正确、正文与私人目录内容不进入响应。批准缺口探针用公开 Hermes CLI 与真实 daemon 验证：需批准工具在 Hermes 保持 hold→block（不执行）、控制台批准后无原生恢复路径、拒绝后重试仍不执行；它记录当前缺口，不代表批准恢复已实现。两者均用合成操作者与临时状态，不读取用户配置、不调用真实模型。
