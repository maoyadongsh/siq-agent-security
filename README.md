# siq-agent-security

智能体现在不只是聊天：它会自己装插件（Skill）、上网、读文件、跑命令。出事前，常见做法是「让模型先看看安不安全」——安全结论落在了最不该拍板的组件上。

本仓库做两件互补的事，规则和字段约定共用，运行时分开：

| | siq-agent-security（本机） | 企业控制面 |
| --- | --- | --- |
| 给谁 | 个人电脑上的智能体 | 多台机器、多个团队 |
| 干什么 | 装 Skill 前先审查，每次调用工具留签字据 | 资产台账、审批、采集、策略下发 |
| 怎么跑 | 一个本地程序，不用登录、不用数据库 | 控制台 + API + PostgreSQL，见 [`docs/control-plane.md`](./docs/control-plane.md) |

下面以 **siq-agent-security** 为主。为何落在 DGX Spark、本机如何适配，见 [为什么做在 NVIDIA DGX Spark 上](#为什么做在-nvidia-dgx-spark-上) 与 [在 DGX Spark 上的适配与实测](#在-dgx-spark-上的适配与实测)。命令与演示夹具见 [`AGENTSHIELD.md`](./AGENTSHIELD.md)。

当前代码在分支 [`cursor/agentshield-w0-contracts-8eff`](https://github.com/maoyadongsh/siq-agent-security/tree/cursor/agentshield-w0-contracts-8eff)，尚未合入 `main`。发布：[v0.2.0](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.2.0)（二进制与 Skill 已从旧名 AgentShield 更名；旧 tag `agentshield-v0.1.0` 仍可对照）。

---

# siq-agent-security

本机智能体的门禁。把它当成一个可安装的 Skill 放进 Hermes、OpenClaw、WorkBuddy / CodeBuddy 之后，对话里就能调用；真正做判断的是本机上的 `siq-agent-security` 程序，不是模型。对外名与仓库名相同，避免和其他已占用「AgentShield」的开源项目撞名。

一句话：**先看清本机有哪些智能体和 Skill，装之前给出结论，人批准最小权限，之后每次工具调用都留一张签过名的回执。**

模型只负责跑命令、把结果原样给你看。它不能宣布「这个 Skill 安全」，也不能代你点批准。

---

## 它解决什么问题

一个能干活的智能体，手里同时握着 Skill 目录、工具、网址、文件路径和密钥引用。来历不明的 Skill 一旦拷进目录，往往已经开始执行。

市场上相关能力通常是拆开的：扫描器只管安装前、网关只管工具、沙箱只管隔离、企业控制台又太重。本机这一条链缺的是：**发现 → 审查 → 人授权 → 调用时拦截 → 出事能核对**。

siq-agent-security 补的就是这一条。它不另做一套账号体系，不自己造沙箱，也不做 HTTPS 中间人。

日常会看到三种结论：

- **隔离**：欺骗、藏指令、偷凭据再外传、文件被篡改——停，不要装。
- **附条件准入**：声明了要上网、写文件、装软件——记下这些能力，等人签发，而不是一律当病毒。
- **通过**：能力声明干净。仍须人授权后，运行时才放行。

默认拒绝未授予的能力。例如没批准过上网，`web_fetch` 就会被挡住，并留下回执。

---

## 为什么做在 NVIDIA DGX Spark 上

SIQ 把一批面向企业的 AI 应用和系统放在 **NVIDIA DGX Spark** 上做本地开发与运行：助手与运行面（Hermes）、投研与分析（research-engine）、文档与流程、身份与网关等。共同前提是数据和模型尽量留在客户机房或专有环境里，而不是默认上公有云。

一旦智能体真正开始干活，安全要求会立刻高于「聊天机器人」。企业、政府部门要面对的是：Skill 和 MCP 从哪来、工具能不能出网、文件和凭据碰没碰、出事之后能不能拿出签字据。本地算力越强、助手越勤快，装错一个插件的后果就越大。

近一两年行业里已经不只是论文里的假设。公开披露过 MCP 工具描述投毒、安装后静默外传邮件、技能市场上规模化恶意 Skill，以及开发环境里的零点击提示注入。共同教训很清楚：**装上之后再让模型「看一眼安不安全」，等于把裁决权交给攻击者最容易影响的那一层。** 对要把智能体放进办公网、专网、政务网的机构来说，这不是可选的加分项，而是能不能上线的门槛。

siq-agent-security 就是补在同一台 Spark 上的本机门禁：不替代现有业务系统，不把流量拐去云上扫描，审查和拦截都在这台机器上完成。企业侧若要把多台 Spark、多个环境收成台账，再走同一仓库里的控制面。

---

## 使用说明

你装的是三样东西：Skill 目录（给对话当入口）、本机程序（做判断）、适配器（接到各产品的工具钩子）。Skill 自己拦不住工具，也不会替你批准权限。

目前从本仓库安装，尚未上架各平台 Skill 市场。需要 **Go 1.22+**（用来编译程序）和 **python3**（用来校验发布清单签名）。安装脚本**不会**从网上下载程序；找不到本机二进制就退出。

### 第一步：编译本机程序

```bash
git clone https://github.com/maoyadongsh/siq-agent-security.git
cd siq-agent-security
git fetch origin cursor/agentshield-w0-contracts-8eff
git checkout cursor/agentshield-w0-contracts-8eff

cd apps/agentshield
go test ./...
go build -trimpath -ldflags "-s -w -X main.Version=0.2.0" -o siq-agent-security ./cmd/agentshield
mkdir -p "$HOME/.local/bin"
install -m 0755 ./siq-agent-security "$HOME/.local/bin/siq-agent-security"
```

Windows 把生成的 `siq-agent-security.exe` 放到用户目录下的 `.local\bin`，或设置环境变量 `SIQ_AGENT_SECURITY_BIN`。本机编译的文件哈希通常和发布清单不完全一致，默认会告警但仍可启动；要强制与发布文件一致，设 `SIQ_AGENT_SECURITY_REQUIRE_PINNED=1`。

### 第二步：把 Skill 放进你的智能体

把仓库里的 `skills/siq-agent-security/` 整目录复制或链接过去，文件夹名保持 `siq-agent-security`。

| 你用的产品 | 放到这里 |
| --- | --- |
| Hermes | `~/.hermes/skills/siq-agent-security` |
| OpenClaw | `~/.openclaw/skills/siq-agent-security` 或 `~/.agents/skills/siq-agent-security` |
| WorkBuddy / CodeBuddy | `~/.codebuddy/skills/siq-agent-security` |
| Trae | `~/.trae/skills/siq-agent-security`（只能审查，拦不住运行中的工具） |

```bash
# 在仓库根目录。下面以 Hermes 为例，换成上表路径即可
mkdir -p "$HOME/.hermes/skills"
ln -sfn "$(pwd)/skills/siq-agent-security" "$HOME/.hermes/skills/siq-agent-security"
```

WorkBuddy 与 CodeBuddy 共用同一套工具钩子，命令里的平台名是 `codebuddy`，改的是 `~/.codebuddy/settings.json`。企业控制面另有只读的 `~/.workbuddy` 发现能力，那是台账采集，**拦不住**对话里的工具。

### 第三步：在对话里启用

打开智能体，直接说例如：「启用 siq-agent-security」「盘点本机有哪些 Skill」「先审查这个目录再决定能不能装」。

模型应按说明依次运行（你也可以自己在终端跑）：

```bash
skills/siq-agent-security/scripts/bootstrap.sh    # Windows: bootstrap.ps1
skills/siq-agent-security/scripts/adapter.sh      # Windows: adapter.ps1
```

前者校验清单和程序，必要时在本机 `http://127.0.0.1:47611` 打开控制台；后者给当前产品装钩子（先备份配置）。WorkBuddy 请重启一次客户端，钩子才会生效。

登录口令在本机状态目录的 `token` 文件里，**不要**贴进聊天或截图。

### 之后怎么用：管别人的 Skill

装上 siq-agent-security 的意义，是管**接下来要装的那些 Skill**。

1. 先问家里有什么：`siq-agent-security inventory`（只看配置，不启动联网服务、不读密钥正文）。
2. **先审查，再拷贝。** WorkBuddy 没有「安装前自动拦截」，文件夹一放进去往往就已经加载。  
   `siq-agent-security admit <候选目录>`  
   结论是隔离（退出码 3）就停止，不要改文件来「刷过」。
3. 审查通过后起草权限：  
   `siq-agent-security grant <审查编号> --platform hermes|openclaw|codebuddy --subject <这个智能体的名字>`
4. **你自己批准**（控制台点一下，或 `grant approve --approve-as 你的名字`），再部署。模型不得代批。
5. 之后每次工具调用都会问门禁：没批过的能力默认拒绝，并记账。
6. 想核对记录有没有被改：`siq-agent-security verify`。

Hermes 会多一个包装命令 `hermes-skills-install`：先审查再调用官方安装。OpenClaw 会在安装 Skill / 插件前询问门禁。WorkBuddy 没有这一层，务必遵守「先审查再复制」。

| 命令 | 人话 |
| --- | --- |
| `siq-agent-security inventory` | 看看本机有哪些智能体和 Skill |
| `siq-agent-security admit <目录>` | 装之前给结论；退出码 3 = 隔离 |
| `siq-agent-security grant …` | 按审查结果起草最小权限 |
| `siq-agent-security grant approve … --approve-as <人名>` | 只有人能批准 |
| `siq-agent-security serve` | 打开本机控制台和决策服务 |
| `siq-agent-security adapter install [平台]` | 给 Hermes / OpenClaw / WorkBuddy 挂钩子 |
| `siq-agent-security adapter uninstall` | 按备份还原 |
| `siq-agent-security verify` | 核对调用记录有没有断、有没有被改 |
| `siq-agent-security export --out <文件>` | 导出脱敏包，不含口令和私钥 |

卸掉钩子：`siq-agent-security adapter uninstall`。再删掉 skills 目录里的链接。状态目录里有密钥和历史记录，删了不可恢复。

更细的页面说明和演示目录见 [`AGENTSHIELD.md`](./AGENTSHIELD.md)。

---

## 商业价值

企业把智能体铺开时，安全团队要的是三句话：**看得见、管得住、查得到。** 下面每条都对应已经做出的能力，没有编造的节省数字。

**看得见。** 本机先盘点有哪些 Agent、Skill、配置；企业侧还能扫容器、进程、集群。第一次能回答「我们到底跑了多少智能体、谁负责」，这是后面所有治理的前提。

**管得住，且不误伤正经 Skill。** 恶意的隔离；正常声明了上网、写文件的，记下能力等人批，而不是一律当病毒——否则官方 Skill 也过不了门。默认拒绝未授权能力，降低「装上就全开」的暴露面。

**查得到。** 每次放行或拒绝都有签名回执，可以复核。企业侧结论还要能回到证据、审批、下发和读回。面对审计，从「事后凑材料」变成「导出即有据」。

**人说了算，模型不能偷步。** 批准权限必须留下操作者姓名。这降低了提示注入「让助手自己开权限」的业务风险，也让责任边界清楚：模型建议，人签字。

**先本机、再企业，语义不换一套。** 个人开发者和小团队不用上登录和数据库；公司要多环境、多租户时走控制面。字段和规则是同一份，避免买两套对不上的产品。

**不替换现有账号、网关和沙箱。** 接入成本是挂钩子，不是搬家。能力按平台真实钩子分档：没有钩子就写明「拦不住」，减少「买了以为拦住其实没拦」的合规事故。

**同一份资产两处用。** 控制面可不依赖特定业务平台单独部署；siq-agent-security 覆盖单台 Spark / 个人桌面。客户按规模选入口，安全语言一致。数据不必为了「扫一眼安不安全」离开本地主机。

---

## 创新点

**把「模型不能当裁判」做成机器拒绝，而不是写在说明书里。** Skill 正文禁止代批；数据约定拒绝非人类批准人；控制台必须填写操作者。被注入的模型就算想执行批准命令，这条链也对不上。

**审查、授权、运行时拦截在同一条本机链上。** 扫描器停在安装前，代理停在工具调用，沙箱停在隔离。用户在一个控制台里能看到：这个 Skill 该不该进门、批了什么、越权有没有被挡住。

**「会用工具」和「是恶意」分开。** 带工具清单的官方风格 Skill 走附条件准入；隔离留给欺骗和外传。少报能力就更新权限，而不是越严越好。

**「已经下发」不等于「沙箱里真的生效」。** 权限分声明、推测、观察到、真正生效、未知五种，不混在一起。没有读回证据，界面显示「已部署 · 未读回」。文件系统和进程策略在沙箱创建时锁定，签发不得把它们标成有效。

**能挡到哪一档，当成产品界面，不当内部备注。** 没有工具钩子就写「审计模式，无法阻断」。没有核验过的实机记录，就不把平台标成正式支持。当前能力表里还没有一行「已正式支持」，这是有意的。

**企业治理可以下沉到一个文件程序，不必把整套服务焊进笔记本。** 本地控制台和企业台账长得像，数据在本机目录。需要舰队管理时再上控制面。

---

## 技术难点

这些不是文案，是实现时必须对着做的硬约束。

**Skill 按行业规范没有执行权。** 它只是说明文档加脚本。拦截上网、改文件、跑进程，只能靠各产品自己的钩子和操作系统沙箱。所以形态只能是「Skill 当入口 + 本机程序当裁判 + 薄适配器当插头」，不能幻想「装一个 Skill 就全局变安全」。

**各产品能挂钩子的地方差很多。** OpenClaw 安装前就能拦；Hermes 主要靠运行时插件，安装要用包装命令补；WorkBuddy 只有全局工具钩子，拷文件进目录拦不住；Trae 没有工具钩子。同一套产品必须按真实能力说话，不能吹成同一档。

**检测必须少误杀。** 说明文档里的反面教材、代码块里的示例，不能当成正在发动的攻击。规则用静态分析，不执行、不导入被扫描内容。Go 侧按正则执行；Python 语法树那几条（例如危险系统调用）尚未迁到本机程序，对应文本规则仍在——这是标明的缺口，不是隐瞒。

**信任不能靠「请用户放心下载」。** Skill 要验程序，程序要验规则包，调用记录要能核验。私钥不出本机目录。安装脚本即使清单里写了下载地址，也仍然不下载；找不到本地程序就失败。本机程序只监听电脑内部地址。

**不能把别人的沙箱网关顺手启动。** 若要用网络隔离，只对接已经验明的 OpenShell，诊断而不代为开机。端口被别的产品占用时，明确说不是 OpenShell，避免把「碰巧有服务」当成隔离已生效。

**本机程序和企业服务两套实现，字段必须锁死。** 破坏性变更先升约定版本。本机程序只用 Go 标准库，便于单文件分发。

---

## 在 DGX Spark 上的适配与实测

以下均来自本仓库开发机：**NVIDIA DGX Spark**（硬件型号 `NVIDIA_DGX_Spark`，`aarch64`，Ubuntu 24.04，内核 `6.17.0-1014-nvidia`，GPU **NVIDIA GB10**，驱动 580.126.09，约 20 逻辑核 / 121 GiB 内存）。程序为原生 `linux/arm64` 构建（Go 1.22.12），`siq-agent-security 0.2.0`，约 13 MB 单文件，不依赖本机 Python 服务做裁决。安装脚本不从网上下载二进制——这在不能随意出网的政务 / 企业网上是硬条件，不是发布省事。

### 和 Spark 上已有系统怎么相处

门禁和业务系统**共栈、不抢控制权**：

- 只监听 `127.0.0.1`，本机控制台在 `:47611`；不改 Hermes 核心，不改 `siq-research-engine` 仓库。
- 不执行 `openshell gateway start`，不接管本机已在跑的 OpenClaw 网关。需要网络隔离时，用环境变量指向对方已有的 `env.sh`，先验明网关身份再握手。
- 适配器安装前备份，卸载还原。OpenClaw / WorkBuddy 的实机合同在**隔离 HOME** 里跑通，避免改操作者日常配置。
- 交叉编译清单含 `linux/arm64`，与 x86 发布物并列钉哈希。Spark 上用的就是这条 ARM 产物。

这台机器上同时存在着 SIQ 的本地 AI 应用（Hermes 助手、投研 OpenShell 等）和 siq-agent-security。产品形态按「企业把 Spark 当本地 AI 主机」来设计：一个文件程序、无登录、无数据库，和需要 PostgreSQL 的企业控制面分开。

### 2026-09-05 本机走过的路径

脱敏记录在 [`docs/evidence/agentshield/`](./docs/evidence/agentshield/README.md)。批准人均为人类 `--approve-as`，模型未代批。能力表**没有**改成「正式支持」——没有核验过的档位就不宣称。

| 接入面 | 在这台 Spark 上实际做了什么 | 明确没做 / 不宣称 |
| --- | --- | --- |
| **Hermes（本机插件）** | 恶意夹具隔离（退出码 3）；官方风格夹具附条件准入；人批准并部署后，未授予的 `web_fetch` 被拒；回执链 `verify` 通过；控制台 `GET /` 返回本地模式页面 | 未配置 OpenShell 时不宣称网络沙箱档 |
| **OpenClaw（隔离 HOME）** | 写入安装策略与插件后可还原；`policy-exec` 对恶意夹具 `block`、对官方风格 `warn`；授前授后越权均为 deny | **未**挂到本机正在跑的 OpenClaw 网关进程 |
| **WorkBuddy / CodeBuddy（隔离 HOME）** | 真实 `hook codebuddy` 读 PreToolUse、打本机决策接口；授前默认拒绝，授后未授予的 `WebFetch` 仍 deny | **未**驱动图形界面客户端；无网络沙箱档 |
| **OpenShell（投研隔离网关）** | 指向 research-engine 的 `env.sh` 后 `doctor` / `probe`：身份核验通过、握手网关名 `siq-openshell-dev`、**未**由 siq-agent-security 启动网关 | 当时没有活动的分析沙箱可做网络策略读回闭环，故不把该档标成正式支持 |
| **Trae** | 产品规定仅审计 | 任何阻断 |

现场还可核验：恶意目录 → 隔离；官方风格目录 → 附条件；签发后越权 → deny；`verify` 重算哈希链。控制台把已下发但没有沙箱读回的签发标成「已部署 · 未读回」，文件系统 / 进程权限不会显示成「真正生效」。

### 这对 Spark 上的业务意味着什么

把投研助手、办公助手、文档智能体放在同一台 GB10 上，并不自动等于安全。siq-agent-security 在这台机器上证明的是：**审查、人签最小权限、工具层拦截、可核验回执，可以和现有本地 AI 栈并排运行，而且不必把数据送出 Spark。** 机构若要把多台 Spark 收成企业台账，再用控制面；单台先把门禁跑起来。

四档能力仍按钩子说话：看清楚 → 装之前能拒 → 调用时能拒并记账 → 把网络策略交给已验明的 OpenShell。Windows 上的网络沙箱依赖 WSL2 或 Docker，当前发布不宣称。没有钩子就拦不住绕过工具层的直连访问。

要把某行改成正式支持，需要新的核验记录并重新签发清单。

---

## 想看实现细节

信任如何衔接、审查如何打分、签发如何变成各产品的工具名单、调用如何记账，写在 [`docs/agentshield-dev-spec-v1.md`](./docs/agentshield-dev-spec-v1.md)。形态为什么是三件套，见 [`docs/adr/0011-portable-skill-form.md`](./docs/adr/0011-portable-skill-form.md)。

```text
skills/siq-agent-security/          对话入口、安装脚本、演示用例、已签名清单
apps/agentshield/            本机程序：审查 / 签发 / 控制台 / 核验
apps/web/src/local/          本机控制台（打进程序里）
adapters/runtime/            接到 Hermes / OpenClaw / WorkBuddy 的插头
packages/contracts/          各组件共用的字段约定
docs/control-plane.md        企业控制面
```

```bash
cd apps/agentshield && gofmt -l . && go vet ./... && go test ./...
./siq-agent-security manifest-verify ../../skills/siq-agent-security/skill-manifest.json
SIQ_AGENT_SECURITY_STATE_DIR=$(mktemp -d) ./siq-agent-security admit ../../skills/siq-agent-security
# 期望附条件准入，不得隔离
```

改本机控制台后：`cd apps/web && npm run build:local`，并再跑 `npm run build`，避免企业台的构建产物被带偏。

| 主题 | 文档 |
| --- | --- |
| 本机操作与演示目录 | [`AGENTSHIELD.md`](./AGENTSHIELD.md) |
| DGX Spark 本机实测（脱敏） | [`docs/evidence/agentshield/`](./docs/evidence/agentshield/README.md) |
| 企业控制面 | [`docs/control-plane.md`](./docs/control-plane.md) |
| 检测规则基线 | [`docs/detection-baseline.md`](./docs/detection-baseline.md) |
| 本地台账与企业语义 | [`docs/agentshield-local-ledger-dev-plan-v1.md`](./docs/agentshield-local-ledger-dev-plan-v1.md) |
| 发布与重新签发 | [`docs/agentshield-release-checklist-v1.md`](./docs/agentshield-release-checklist-v1.md) |
| 仓库开发约定 | [`AGENTS.md`](./AGENTS.md) |
