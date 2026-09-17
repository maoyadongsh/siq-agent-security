# siq-agent-security

本地单文件门禁官：盘点 Agent 资产、准入未知 Skill、签发最小权限、给每次工具调用签回执。

**模型不判断 Skill 是否安全。** 裁决只由 `siq-agent-security` 二进制产出。产品说明见根 [`README.md`](./README.md)；本文件是本机操作与夹具步骤。企业控制面见 [`docs/control-plane.md`](./docs/control-plane.md)。本地模式只需 `serve`，不必启动 PostgreSQL / `:8600`。

仓库：[`maoyadongsh/siq-agent-security`](https://github.com/maoyadongsh/siq-agent-security)  
分支：`main`（本地产品与 Trusted Intent V2 核心已合入）。研究演示与发布入口见根 README；本地源码构建及 Skill 接入步骤见下文。

Linux 个人体验开发版可在构建后使用 `./siq-agent-security setup --confirm-setup` 一次完成初始化、用户后台注册和启动；加 `--open-ui` 可在就绪后请求打开浏览器。再执行 `./siq-agent-security pair` 获取配对码，打开输出的管理地址。可选 `--port N` 指定初始端口；重复执行复用同一健康服务。需要 systemd 用户会话，尚不启用登录自启；Windows/macOS 的开发中 setup 入口见文末，尚待实机验收；也可使用下面的前台 `start`。

## 三步（本机复现）

需要 Go 1.22+；从当前前端源码构建完整本地控制台使用 Node.js 22 / npm。Skill 引导脚本另需 Python 3 和 OpenSSL 3。

```bash
git clone https://github.com/maoyadongsh/siq-agent-security.git
cd siq-agent-security
git switch main

npm --prefix apps/web ci
npm --prefix apps/web run build:local

cd apps/agentshield
go test ./...
go build -trimpath -ldflags "-s -w" -o siq-agent-security ./cmd/agentshield
export SIQ_AGENT_SECURITY_STATE_DIR="${SIQ_AGENT_SECURITY_STATE_DIR:-$(pwd)/.state}"
./siq-agent-security start --port 47611
```

浏览器打开 `http://127.0.0.1:47611`，在页面输入终端打印的**管理配对码**（5 分钟内单次有效）。适配器决策 token 在 `$SIQ_AGENT_SECURITY_STATE_DIR/token`（0600），不要贴进聊天或截图。当前是同 UID 桌面模式：不能防止同一用户下的 Agent 直接跑 CLI。

以下是已构建本地二进制后，将 Skill 接入 Hermes / OpenClaw / WorkBuddy 的步骤。在仓库根目录执行，并保持与 `serve` 相同的状态目录环境变量：

个人体验开发版的 `start` 将初始化和启动合为一步，无需 Python。新状态默认 block；已有配置保留原有模式与端口。已有匹配服务时返回健康 JSON 并退出，可用 `pair` 生成新配对码；不同状态目录或错误服务占用端口时拒绝启动。新服务在前台运行，保持终端打开，Ctrl+C 正常停止；尚不代表后台注册或注销保活完成。智能体仍需用户确认接入与权限。

需要分开执行时使用 `init --port 47611` 后运行 `serve`；已有端口不同会报错，初始化不修改已有配置或实例身份。服务运行期间不要重新初始化，可用 `status` 检查。历史发布二进制可能没有 `init`/`start`，以上命令对应当前源码开发版，不改变历史制品身份。

```bash
export SIQ_AGENT_SECURITY_BIN="$(pwd)/apps/agentshield/siq-agent-security"
export SIQ_AGENT_SECURITY_STAGE_DIR="$HOME/.cache/siq-agent-security-stage"
skills/siq-agent-security/scripts/bootstrap.sh   # Windows: bootstrap.ps1
skills/siq-agent-security/scripts/adapter.sh hermes  # 按实际平台替换；Windows: adapter.ps1
```

bootstrap 会用内置公钥校验 `skill-manifest.json` 签名。本地 `go build` 的二进制哈希通常与清单里的发布钉不一致，默认只告警；要强制钉死则设 `SIQ_AGENT_SECURITY_REQUIRE_PINNED=1`。

清单里的 `binary.artifacts[].url` 指向 GitHub Release `siq-agent-security-v0.2.0`。bootstrap **默认不下载**；找不到本地二进制且显式设置 `SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD=1` 时，才下载并校验清单制品。该 Release 早于 V2 增量；体验当前代码应按上面的步骤从 main 构建，默认显示 `0.0.0-dev`。

## 档位（诚实）

Linux 开发版可在初始化后运行 `siq-agent-security service-unit` 导出 systemd 用户服务配置。先将二进制放在长期保留的位置，再导出；配置固定当前二进制和状态目录。可以将输出保存到新的暂存 `.service` 文件，用 `systemd-analyze --user verify <文件>` 检查。导出命令不注册、启动或覆盖已有服务。自动安装和可恢复卸载仍在开发，现阶段不要把配置导出当作后台已启用。

配置关闭 stdout/stderr 的 journal 输出，配对使用相同状态目录的 `pair` 命令。默认不自动重启；30 秒停止超时可能触发系统强杀，须区分正常停止和需要状态恢复的退出。是否注销后继续运行取决于用户服务管理器/linger 配置，本命令不修改该设置。

机器可读事实源：[`skills/siq-agent-security/skill-manifest.json`](./skills/siq-agent-security/skill-manifest.json) 的 `support_matrix`。当前**没有任何一行 `supported`**。2026-09-05 已在 DGX Spark（linux/arm64）归档：Hermes 实机插件 L0–L2（[`hermes-linux-2026-09-05/`](./docs/evidence/agentshield/hermes-linux-2026-09-05/)）、OpenClaw 隔离 HOME 的 `policy-exec` + 插件形态 decide（[`openclaw-linux-2026-09-05/`](./docs/evidence/agentshield/openclaw-linux-2026-09-05/)）、CodeBuddy 隔离 HOME 的真实 `hook codebuddy`（[`codebuddy-linux-2026-09-05/`](./docs/evidence/agentshield/codebuddy-linux-2026-09-05/)）。grant 均由人类 `--approve-as maoyd` 批准并 deploy，授后越权为 deny，`verify` 通过。L3 需验明的 OpenShell 网关，可选、不宣称。OpenShell 由 PATH 或 `SIQ_AS_OPENSHELL_ENV_SH` 发现 CLI，但默认不得把未验明的网关（常见：端口被 OpenClaw 占用）当成 L3；矩阵在重签前不改 `supported`。

| 平台 | Linux | macOS | Windows | 说明 |
| --- | --- | --- | --- | --- |
| Hermes | L0–L3 experimental | L0–L2 experimental | L0–L2 experimental | Linux L0–L2 有 Spark 证据；L3 可选未宣称 |
| OpenClaw | L0–L3 experimental | L0–L2 experimental | L0–L2 experimental | Linux arm64 公共 CLI 托管会话已验证；`policy-exec` 组件证据不证明原生安装拦截，顶层 installPolicy 不受支持；其他 OS 原生验收待完成 |
| CodeBuddy | L0–L2 experimental | L0–L2 experimental | L0–L2 experimental | linux `hook codebuddy` 证据已归档；非 GUI 客户端；无 L3；矩阵不改 |
| Trae | L0 audit_only | L0 audit_only | L0 audit_only | 无工具钩子，不能阻断 |
| Claude Code / Codex | L0 experimental | L0 experimental | L0 experimental | 非本轮 |

L0 审计 · L1 安装门禁 · L2 运行时回执与阻断 · L3 OpenShell 网络策略下发。

## 已知限制

- filesystem / process 策略不能热更新，grant 不得把这两域标成 `effective`
- Trae 只能审计，控制台必须显示无法阻断
- OpenShell `verify` 只到 `readback_verified`，不到 `enforcement_verified`
- siq-agent-security 会发现 PATH 上的 `openshell`，但**不会**执行 `openshell gateway start`，也不会猜测端口或改别人的网关
- 接入已有 OpenShell（例如 research-engine 的 `siq-openshell-dev`）时设 `SIQ_AS_OPENSHELL_ENV_SH` 指向其 `scripts/openshell/env.sh`；不要改对方仓库。siq-agent-security 不 `gateway start`
- Windows L3 需要 WSL2 / Docker；本快照不宣称
- GitHub Release tag `siq-agent-security-v0.2.0`；当前 V2 复现以 main 源码构建为准。bootstrap 下载需显式开启。操作清单：[`docs/agentshield-release-checklist-v1.md`](./docs/agentshield-release-checklist-v1.md)
- 批准 grant 由操作者完成；离线 CLI 需要 `grant challenge` 产生的一次性挑战及 `--approve-as`，服务运行时使用控制台 / 管理 API。SKILL.md 禁止模型批准；该流程不构成同 UID 隔离
- 控制台管理入口需要 `serve` 终端里的一次性配对码；`/ui-config.json` 不含凭据；适配器决策 token 不能调用管理接口
- 当前桌面模式是 `desktop-same-uid`：同 OS 用户下的 Agent 仍可读状态目录并执行 CLI，**不**宣称“无法自批”

## 演示（评委路径）

在已 `serve` 的前提下：

```bash
# 1. 恶意 Skill → 隔离
./siq-agent-security admit ../../skills/siq-agent-security/evals/fixtures/toxic-finreport-enhancer
# 期望 verdict=quarantine，退出码 3

# 2. 干净 / 官方风格 Skill → 附条件准入
./siq-agent-security admit ../../skills/siq-agent-security/evals/fixtures/official-like
# 期望 admit_with_conditions

# 3. 服务运行时，在本地控制台起草、批准并部署 grant。
# 平台设为 hermes，subject 与实际 Agent ID 一致；本段合成请求使用 demo。
# 若使用离线 CLI，先停止 serve；挑战与批准的完整命令见 README 快速开始。

# 4. 越权工具调用应 deny（Hermes 插件会 POST 同一请求体；不要把 token 贴进聊天）
TOKEN=$(cat "$SIQ_AGENT_SECURITY_STATE_DIR/token")
curl -sS http://127.0.0.1:47611/v1/decide \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"platform":"hermes","session_id":"judge-demo","agent_id":"demo","tool":"web_fetch","params":{"url":"https://evil.example/"}}'
unset TOKEN
# 期望 action=deny（未部署 grant 时是 default deny；已部署且未授 web_fetch 时是 tool not granted）

# 5. 回执链
./siq-agent-security verify
```

脱敏回执见 [`docs/evidence/agentshield/`](./docs/evidence/agentshield/README.md)。即使已有 linux 证据，矩阵行在重签前仍保持 `experimental`。

## 台账演示（加分主界面，非前置依赖）

三步对抗之后，打开 `http://127.0.0.1:47611`（无需登录、不必起 PostgreSQL / `:8600`）：

1. **智能体资产** `/agents`：本机平台、Hermes profile / OpenClaw agent、Skill；详情可确认/驳回，准入后起草签发，批准前可改五域。
2. **权限视图** `/permissions`：五态分色。无 OpenShell 时「有效」列应为空；`deployed` grant 仍是声明态。filesystem / process 永不标有效。有 L3 时可跑漂移检测。
3. **风险中心** `/findings`：准入与漂移 finding；接受须原因和到期。
4. **回执** `/receipts`：越权调用的 deny 高亮，并可验签。
5. **设置**：下载脱敏导出包（无私钥、无 token）。也可用 `siq-agent-security export --out ./siq-agent-security-export.json`。`sync --control-api` 不是现场步骤。

顶栏保持「本地模式 · 单用户」。旧书签 `/inventory`、`/admissions` 会转到 `/agents`。

## 十日谈（十条）

1. 用户拿到一份来历不明的 Skill。
2. 模型被要求「先看看安不安全」——它不得自己判断。
3. `siq-agent-security admit` 给出 quarantine 或附条件准入。
4. 隔离则停止安装，不改候选来「刷过」。
5. 附条件准入列出 declared 能力，写成 Skill Card。
6. 操作者经控制台或离线挑战流程批准 grant；模型不得代批。
7. 适配器把工具调用转到 `/v1/decide`。
8. 越权出网或读凭据 → deny，回执入链。
9. `verify` 重算哈希链；断链即失败。
10. OpenShell 若在：先 `openshell doctor` 验明正身再下发网络段并读回；fs/process 仍非 effective。siq-agent-security 不 `gateway start`。

## 仓库地图

| 路径 | 作用 |
| --- | --- |
| `apps/agentshield/` | Go 单文件二进制（仅标准库） |
| `skills/siq-agent-security/` | SKILL.md、bootstrap、evals、签名清单 |
| `adapters/runtime/` | Hermes / OpenClaw / CodeBuddy 薄适配器 |
| `packages/contracts/` | admission / grant / receipt / skill-manifest schema |
| `apps/web/src/local/` | 本地控制台；`npm run build:local` 嵌入二进制 |
| `apps/control-api/` | 企业控制面（评委不必跑） |

## 验证命令

```bash
cd apps/agentshield && gofmt -l . && go vet ./... && go test ./...
./siq-agent-security manifest-verify ../../skills/siq-agent-security/skill-manifest.json
SIQ_AGENT_SECURITY_STATE_DIR=$(mktemp -d) ./siq-agent-security admit ../../skills/siq-agent-security
# 期望 admit_with_conditions，不得 quarantine
```


### Linux 用户服务配置准备（开发中）

执行 `siq-agent-security init` 后，可执行 `siq-agent-security service-prepare`，在状态目录生成签名归属记录 `user-service.json` 和实例专属 `.service` 文件。重复执行会复验已有记录；中断后可补齐缺失文件。未知目标、内容漂移或二进制位置变化会明确失败，不自动覆盖。

此命令仅准备配置，尚不注册或启动系统服务；记录不是运行状态。已有服务持有写锁时需先完成正常停止。当前原生单命令运行入口仍为 `siq-agent-security start`（前台）；后台安装与生命周期入口继续开发。


执行 `siq-agent-security service-register` 可注册 Linux 当前用户服务，`--runtime` 仅临时注册。命令会核对签名配置与系统加载来源；注册后尚未启动，也未启用登录自启。失败时保留配置供修复后重试，不手工删除未知服务或记录。完整程序卸载仍在开发；不同注册范围或程序位置变化暂不自动迁移。


Linux 已注册服务可用 `siq-agent-security service-start` 启动，`siq-agent-security service-status` 查询本实例服务与 API 状态。停止保护请显式执行 `siq-agent-security service-stop --confirm-stop`；停止后 block 模式下智能体的后续受控操作将被拒绝。查询不补发缺失配置，异常锁/身份/单位归属需先诊断，不自动覆盖或清除。


停止后可执行 `siq-agent-security service-unregister --confirm-unregister` 注销后台服务入口。命令仅删除已验证归属的注册链接，保留本地配置、密钥、授权和历史；运行中拒绝注销。注销后仍可重新注册，程序升级或数据删除不属于该命令。


### 原生制品暂存（升级准备）

`siq-agent-security client-stage --manifest FILE --binary FILE` 仅接受既有发行根签名清单，并校验当前系统对应二进制的大小与摘要。验证后暂存到状态目录独立版本目录；不会执行候选、停止保护或切换版本。没有绕过验签的开发参数；升级兼容性检查与切换恢复仍在开发。


升级前可执行 `siq-agent-security client-upgrade-check --manifest FILE --binary FILE`。它要求发行方签名的 v2 无迁移兼容声明并检查候选内容；v1 仍可暂存，但不能通过该预检。成功不代表已批准或切换版本。发行准备工具只有显式 `release-manifest --client-compatible` 才生成 v2；旧 Skill 引导脚本与冻结 v1 包保持原协议。


Linux 已注册服务与 macOS 已注册 LaunchAgent 可执行 `siq-agent-security service-upgrade --manifest FILE --binary FILE --confirm-upgrade`。候选必须通过 v2 发行签名/兼容预检；确认后会短暂停止保护，block 模式下受控操作暂时拒绝。失败输出的事务 ID 可配合同一候选及 `--recover ID` 前滚恢复；不得替换目标。该流程不回滚台账。显式 `service-rollback` 可把已完成切换恢复到原事务源配置。macOS 使用独立的 `local-launch-agent-switch/v1` 日志切换 `<label>.plist` 与 `launch-agent.json`，随后对同一注册链接 `bootout`→`bootstrap`→`kickstart` 使 launchd 读到新程序。

若候选因端口冲突等原因启动失败，先排除冲突，再使用同一候选和事务 ID 执行 `service-upgrade ... --confirm-upgrade --recover ID`。只有已停止/失败且无主进程的单位可恢复；活跃写锁或无法确认的进程状态会被拒绝，勿手工删除锁。


显式恢复原升级事务的源配置可使用 `siq-agent-security service-rollback --transaction ID --manifest OLD --binary OLD --confirm-rollback`。原升级事务必须含 v2 程序摘要绑定；旧程序必须在原路径、匹配原 source 摘要并通过 v2 发行校验；失败时保留原参数并使用回退输出的新事务 ID 加 `--recover ID`。此操作不回滚授权或台账，也不下载历史程序。

首次升级会在停止服务前把当前 CLI 程序复制到状态目录的 `client-snapshots/<sha256>/`。这是本地观测副本，不是发行信任证明；回退仍需已验证的旧清单；若原程序缺失，可在回退命令上明确加 `--restore-missing-binary`，从匹配历史摘要的本地快照恢复原路径。已有文件不覆盖，父目录必须存在；快照或发行校验失败时不恢复。

新升级事务记录源快照与目标程序的签名摘要，停止前与启动前核对实际文件。旧 v1 切换日志可继续前滚恢复，但缺少历史程序摘要，不能用于新的产品回退。

回退时可省略 `--manifest`：程序会在本机已留存的历史版本目录中寻找唯一匹配的发行清单，并重新验证发行签名、兼容声明与程序摘要。找不到或有多份匹配时会提示显式提供清单。首次从外部程序路径升级时，可加 `--source-manifest OLD.json` 保存当前程序的发行清单与副本，供后续回退使用；该选项不适用于 `--recover`。

日常可运行 `siq-agent-security ui` 打开当前实例的管理页面，或 `ui --print` 仅输出地址。两者都会先验证服务身份和状态目录，不生成配对码；首次连接仍需单独执行 `pair`。浏览器无法打开时可手动访问输出地址，服务继续运行。

Linux 正式发行安装入口为 `siq-agent-security client-install --manifest RELEASE.json --binary DOWNLOADED --confirm-install`，可加 `--port N`、`--open-ui`。它先校验发行签名与兼容声明，再保存到状态目录的稳定程序路径，由该程序执行后台 setup；安装成功显示后续管理应使用的程序路径。已有其他版本请走 `service-upgrade`，此入口不替换未知服务、不修改 PATH 或启用登录自启。当前为源码开发能力，正式签名制品安装验收仍待完成。

Linux 可用 `service-login --enable --confirm-enable` 明确启用当前实例的用户登录自启，`service-login --disable` 关闭。操作不启动/停止当前进程；默认 setup 的持久注册可用于后续登录，`--runtime` 注册只在本登录会话有效。注销前先关闭自启，再正常停止并注销服务；未知启动入口不会被覆盖或删除。

需要退出本机后台运行时，可执行 `teardown --confirm-teardown`，一次关闭当前实例自启、正常停止并注销后台入口。配置、身份、程序和历史数据保留，之后可重新 `setup`。该命令不会卸载智能体钩子；服务停止后，block 模式下的受控操作会拒绝。重复执行会复验已退出状态。

macOS 开发版新增 `launch-agent-plist`，只读导出当前已初始化实例的 LaunchAgent 配置。当前仅完成导出与跨解析器校验，尚未接通自动注册、启动或 macOS 实机验收；不要将此命令视为后台安装成功。

macOS `launch-agent-prepare` 可在状态目录中准备签名归属记录与 plist，重复执行复验内容，并恢复签名记录存在但 plist 缺失的中断。尚不写入 Library/LaunchAgents 或加载任务，不能据此认为后台服务已启动。

macOS `launch-agent-register` 会复验/准备签名配置，并向当前用户 `Library/LaunchAgents` 排他发布实例链接。只复用同一源的精确链接，不覆盖未知文件或跟随被重定向的目录。当前尚不执行 launchctl，不代表已经加载或启动；实机验收待完成。

macOS `launch-agent-status` 只读核对当前 GUI 用户域：先用 `launchctl list` 判定本实例是否出现，再用 `launchctl print gui/<uid>/<label>` 核对已加载源路径、程序参数、状态目录环境和 umask。当前 Darwin 没有 `list -x` XML 开关；命令或格式不支持时返回未确认，不会自动加载或替换任务。

`launch-agent-status` 现在会先核对当前 GUI 用户域的完整任务列表；明确缺席时提示“已注册，当前用户域未加载”。查询失败、格式不支持或查询中任务变化均保持“未确认”，不会自动加载或重装。此查询只反映当时的当前用户域，不证明全系统没有服务。

macOS 可在 `launch-agent-register` 后运行 `launch-agent-load --confirm-load`，将已签名的当前实例配置加载到当前 GUI 用户域。重复执行会核对并复用已加载配置；失败时先运行 `launch-agent-status` 检查再重试。该命令不请求启动，不能仅凭加载成功判断保护就绪。当前仍缺 macOS 实机验收。

macOS `launch-agent-start --confirm-start` 会复用上述加载流程，启动当前实例并检查目录健康；已有进程时仅验证，不强制重启。失败后保留现场，请使用 `launch-agent-status` 检查。当前属于待实机验收的开发能力。

macOS `launch-agent-stop --confirm-stop` 停止当前归属实例并保留配置、密钥和历史；再次运行 `launch-agent-start --confirm-start` 可复用配置。停止超时、异常退出或台账仍被占用时返回未确认，不能据此判断安全排空完成。此命令仍待 macOS 实机验收。

macOS 停止服务后，可执行 `launch-agent-unregister --confirm-unregister` 移除当前用户域注册。命令保留程序、配置、密钥和历史；再次使用先 `launch-agent-register`，再 `launch-agent-start --confirm-start`。注销失败保留现场，可检查状态后重试；不会自动终止仍在运行的实例。完整流程仍待 macOS 实机验证。

macOS 开发入口现可使用 `setup --confirm-setup [--port N] [--open-ui]` 串联初始化、注册和启动。须在非 root 的 GUI 用户会话中运行；`--runtime` 仅适用于 Linux。健康的已归属实例会复用；任一步失败保留现场，排查后可重试。此编排尚待 macOS 实机验收，不代表已提供正式安装包或登录自启。

macOS 现可执行 `teardown --confirm-teardown` 串联停止与注销，并保留程序、配置、密钥和历史。停止未确认会阻止后续注销；已停止但注销中断可重试。退出后智能体钩子仍在，block 模式请求会拒绝；再次使用可运行 `setup --confirm-setup`。此完整旅程仍待 macOS 实机验收。

后台启动器可使用 `serve --state-dir /absolute/canonical/path` 显式绑定已初始化实例；该参数优先于新旧状态目录环境变量，不修改环境。路径必须已存在且规范，不接受相对路径或符号链接别名；不指定则保留既有默认行为。Windows 计划任务接入将使用此入口，任务注册尚未实现。

Windows 开发入口 `task-xml` 只读导出当前用户计划任务配置：绑定当前用户 SID、当前程序与实例目录，最低权限、无自动触发器。路径暂限本地盘符规范路径，不支持 UNC/设备路径或百分号环境展开。导出不会注册或启动任务；签名归属、任务生命周期及 Windows 实机验收尚待完成。

Windows `task-prepare` 会在状态目录内准备任务 XML 与签名归属记录，绑定当前用户 SID、实例、目录和内容摘要。重复准备只接受原配置；XML 缺失可按签名恢复，未知内容不会覆盖。该命令不注册或启动系统计划任务，原生验收仍待完成。

Windows `task-query` 只读查询已经准备且已在系统中注册的实例任务，完整核对当前用户、签名源和系统返回的 XML 后输出配置。查询失败不会当作任务不存在，也不会注册、覆盖或启动任务；成功不代表进程健康。当前只有模拟查询与跨平台编译证据，尚待 Windows 实机验收。

Windows `task-presence` 只读检查已签名准备实例的系统任务，成功输出 `present` 或 `absent`；存在时还必须通过完整配置核对。依赖系统 Windows PowerShell 与 Task Scheduler，任何无法确认的查询均报错，不触发创建或覆盖。当前原生脚本与系统兼容仍待 Windows 验收。

Windows `task-register --confirm-register` 准备签名配置并排他注册当前用户的实例任务。已有任务只在完整配置匹配时复用；创建后读回失败保留现场，再次执行须重新核对。命令不启动任务、不更新同名异配置。依赖系统 Windows PowerShell / Task Scheduler；当前仅模拟与交叉编译通过，原生注册验收仍待完成。

Windows `task-start --confirm-start` 对已注册且配置匹配的任务请求按需启动，成功前检查本机 API 的实例目录健康；已有健康实例复用。请先运行 `task-register --confirm-register`。健康失败保留任务和状态，不强制重启或删除。此路径尚待 Windows 实机验收，正常退出和注销命令见下文。

Windows `task-runtime` 只读显示已核对任务的 `state`、可见 `instances` 与 `last_result`。它会拒绝矛盾状态；`last_result=0` 不表示当前服务已正常退出。原生运行状态与正常退出通道仍待 Windows 验收。

服务端现已支持本机签名退出协议（规格 §3.11.45）：先获取当前运行挑战，再签署退出请求，接受记录持久化成功后进入排空。配对/适配器/恢复 token 不能替代签名；HTTP 202 仅表示请求已接受。对应退出请求 CLI 见下文；完整链路仅有隔离 Linux 子进程证据，Windows 后台退出待验收。

`siq-agent-security stop-request --confirm-stop` 使用当前状态目录和配置端口请求正常退出，输出签名接受记录。命令会验签当前运行挑战和本机记录；响应丢失但匹配记录已落盘时可确认接受，不自动重发。**该命令只确认接受，不等待或宣称服务已经退出。** 最终确认可使用下方 stop 命令；Windows 任务停止命令见下文。

签名退出请求进入排空后，服务会保留 `service-stop-<boot_id>.result.json`，记录 `drained` 或 `drain_failed` 并绑定接受记录。它表示收尾结果，写入时仍持 Writer，不能单凭文件存在判断进程已退出。停止完成确认使用下方 stop 命令。

`siq-agent-security stop --confirm-stop` 请求退出并等待本次签名排空结果与主 Writer 释放，成功输出结果 JSON。超时后可用 `stop --confirm-stop --recover <boot_id>` 继续核对原请求；恢复检查不会发送新的停止请求，也不会停止后来启动的实例。此命令不注销或禁用系统任务，不能阻止管理器之后重新启动。完整 CLI 已在隔离 Linux 验证，Windows/macOS 原生验收仍待完成。

Windows `task-stop --confirm-stop` 对签名绑定的已注册实例请求正常退出，核对本次排空记录、任务空闲状态和主 Writer 释放；原本空闲时仅确认空闲。排队、归属变化、排空失败或非零退出结果会报错并保留现场。命令不强制终止、不注销或禁用任务；仅通过模拟测试和交叉编译，尚待 Windows 实机验收。

Windows `task-unregister --confirm-unregister` 注销已签名且空闲的当前实例任务，成功前重新确认缺席；运行或排队时拒绝，请先完成正常停止。本地源配置、密钥和历史保留；失败保留现场，可检查后重试。该命令仅有模拟编排与交叉编译证据，PowerShell/COM 删除仍待 Windows 实机验收。

Windows 开发入口 `setup --confirm-setup [--port N] [--open-ui]` 先只读预检当前用户 Task Scheduler，再串联初始化、排他注册、启动和目录健康检查。已有健康实例仍核对系统任务归属；失败保留现场。`--runtime` 不支持，不自动配置登录触发器。PowerShell/COM 和浏览器完整旅程仍待 Windows 实机验收。

Windows `teardown --confirm-teardown` 串联正常停止与任务注销，保留程序、配置、密钥和历史。停止未确认不会继续注销；注销已完成但响应中断可重试确认缺席。智能体钩子不会卸载，服务停止后 block 模式受控操作会拒绝。该旅程仍待 Windows 实机验收。
