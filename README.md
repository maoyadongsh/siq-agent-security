# siq-agent-security

智能体现在不只是聊天：它会自己装插件（Skill）、上网、读文件、跑命令。出事前，常见做法是「让模型先看看安不安全」——安全结论落在了最不该拍板的组件上。

本仓库做两件互补的事，规则和字段约定共用，运行时分开：

| | AgentShield（本机） | 企业控制面 |
| --- | --- | --- |
| 给谁 | 个人电脑上的智能体 | 多台机器、多个团队 |
| 干什么 | 装 Skill 前先审查，每次调用工具留签字据 | 资产台账、审批、采集、策略下发 |
| 怎么跑 | 一个本地程序，不用登录、不用数据库 | 控制台 + API + PostgreSQL，见 [`docs/control-plane.md`](./docs/control-plane.md) |

下面以 **AgentShield** 为主。命令与演示夹具见 [`AGENTSHIELD.md`](./AGENTSHIELD.md)。

当前代码在分支 [`cursor/agentshield-w0-contracts-8eff`](https://github.com/maoyadongsh/siq-agent-security/tree/cursor/agentshield-w0-contracts-8eff)，尚未合入 `main`。发布：[v0.1.0](https://github.com/maoyadongsh/siq-agent-security/releases/tag/agentshield-v0.1.0)。

---

# AgentShield

本机智能体的门禁。把它当成一个可安装的 Skill 放进 Hermes、OpenClaw、WorkBuddy / CodeBuddy 之后，对话里就能调用；真正做判断的是本机上的 `agentshield` 程序，不是模型。

一句话：**先看清本机有哪些智能体和 Skill，装之前给出结论，人批准最小权限，之后每次工具调用都留一张签过名的回执。**

模型只负责跑命令、把结果原样给你看。它不能宣布「这个 Skill 安全」，也不能代你点批准。

---

## 它解决什么问题

一个能干活的智能体，手里同时握着 Skill 目录、工具、网址、文件路径和密钥引用。来历不明的 Skill 一旦拷进目录，往往已经开始执行。

市场上相关能力通常是拆开的：扫描器只管安装前、网关只管工具、沙箱只管隔离、企业控制台又太重。本机这一条链缺的是：**发现 → 审查 → 人授权 → 调用时拦截 → 出事能核对**。

AgentShield 补的就是这一条。它不另做一套账号体系，不自己造沙箱，也不做 HTTPS 中间人。

日常会看到三种结论：

- **隔离**：欺骗、藏指令、偷凭据再外传、文件被篡改——停，不要装。
- **附条件准入**：声明了要上网、写文件、装软件——记下这些能力，等人签发，而不是一律当病毒。
- **通过**：能力声明干净。仍须人授权后，运行时才放行。

默认拒绝未授予的能力。例如没批准过上网，`web_fetch` 就会被挡住，并留下回执。

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
go build -trimpath -ldflags "-s -w -X main.Version=0.1.0" -o agentshield ./cmd/agentshield
mkdir -p "$HOME/.local/bin"
install -m 0755 ./agentshield "$HOME/.local/bin/agentshield"
```

Windows 把生成的 `agentshield.exe` 放到用户目录下的 `.local\bin`，或设置环境变量 `AGENTSHIELD_BIN`。本机编译的文件哈希通常和发布清单不完全一致，默认会告警但仍可启动；要强制与发布文件一致，设 `AGENTSHIELD_REQUIRE_PINNED=1`。

### 第二步：把 Skill 放进你的智能体

把仓库里的 `skills/agentshield/` 整目录复制或链接过去，文件夹名保持 `agentshield`。

| 你用的产品 | 放到这里 |
| --- | --- |
| Hermes | `~/.hermes/skills/agentshield` |
| OpenClaw | `~/.openclaw/skills/agentshield` 或 `~/.agents/skills/agentshield` |
| WorkBuddy / CodeBuddy | `~/.codebuddy/skills/agentshield` |
| Trae | `~/.trae/skills/agentshield`（只能审查，拦不住运行中的工具） |

```bash
# 在仓库根目录。下面以 Hermes 为例，换成上表路径即可
mkdir -p "$HOME/.hermes/skills"
ln -sfn "$(pwd)/skills/agentshield" "$HOME/.hermes/skills/agentshield"
```

WorkBuddy 与 CodeBuddy 共用同一套工具钩子，命令里的平台名是 `codebuddy`，改的是 `~/.codebuddy/settings.json`。企业控制面另有只读的 `~/.workbuddy` 发现能力，那是台账采集，**拦不住**对话里的工具。

### 第三步：在对话里启用

打开智能体，直接说例如：「启用 AgentShield」「盘点本机有哪些 Skill」「先审查这个目录再决定能不能装」。

模型应按说明依次运行（你也可以自己在终端跑）：

```bash
skills/agentshield/scripts/bootstrap.sh    # Windows: bootstrap.ps1
skills/agentshield/scripts/adapter.sh      # Windows: adapter.ps1
```

前者校验清单和程序，必要时在本机 `http://127.0.0.1:47611` 打开控制台；后者给当前产品装钩子（先备份配置）。WorkBuddy 请重启一次客户端，钩子才会生效。

登录口令在本机状态目录的 `token` 文件里，**不要**贴进聊天或截图。

### 之后怎么用：管别人的 Skill

装上 AgentShield 的意义，是管**接下来要装的那些 Skill**。

1. 先问家里有什么：`agentshield inventory`（只看配置，不启动联网服务、不读密钥正文）。
2. **先审查，再拷贝。** WorkBuddy 没有「安装前自动拦截」，文件夹一放进去往往就已经加载。  
   `agentshield admit <候选目录>`  
   结论是隔离（退出码 3）就停止，不要改文件来「刷过」。
3. 审查通过后起草权限：  
   `agentshield grant <审查编号> --platform hermes|openclaw|codebuddy --subject <这个智能体的名字>`
4. **你自己批准**（控制台点一下，或 `grant approve --approve-as 你的名字`），再部署。模型不得代批。
5. 之后每次工具调用都会问门禁：没批过的能力默认拒绝，并记账。
6. 想核对记录有没有被改：`agentshield verify`。

Hermes 会多一个包装命令 `hermes-skills-install`：先审查再调用官方安装。OpenClaw 会在安装 Skill / 插件前询问门禁。WorkBuddy 没有这一层，务必遵守「先审查再复制」。

| 命令 | 人话 |
| --- | --- |
| `agentshield inventory` | 看看本机有哪些智能体和 Skill |
| `agentshield admit <目录>` | 装之前给结论；退出码 3 = 隔离 |
| `agentshield grant …` | 按审查结果起草最小权限 |
| `agentshield grant approve … --approve-as <人名>` | 只有人能批准 |
| `agentshield serve` | 打开本机控制台和决策服务 |
| `agentshield adapter install [平台]` | 给 Hermes / OpenClaw / WorkBuddy 挂钩子 |
| `agentshield adapter uninstall` | 按备份还原 |
| `agentshield verify` | 核对调用记录有没有断、有没有被改 |
| `agentshield export --out <文件>` | 导出脱敏包，不含口令和私钥 |

卸掉钩子：`agentshield adapter uninstall`。再删掉 skills 目录里的链接。状态目录里有密钥和历史记录，删了不可恢复。

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

**同一份资产两处用。** 控制面可不依赖特定业务平台单独部署；AgentShield 覆盖个人桌面。客户按规模选入口，安全语言一致。

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

## 现在能挡到哪一步

四档：看清楚（审计）→ 装之前能拒 → 调用时能拒并记账 → 把网络策略交给已验明的 OpenShell。

能力表目前全部是「试验中」，Trae 为「仅审计」。已在 NVIDIA DGX Spark（Linux ARM）留下可核对记录：

| 产品 | 已经验证过 | 明确不宣称 |
| --- | --- | --- |
| Hermes | 本机插件：审查、签发后越权会被拒、记录可核验 | 网络沙箱档 |
| OpenClaw | 隔离环境下的安装前审查与调用拦截 | 接管你机器上已经在跑的网关 |
| WorkBuddy / CodeBuddy | 隔离环境下的真实工具钩子 | 图形界面里的完整点击路径；网络沙箱档 |
| Trae | 产品规定只能审计 | 任何阻断 |

记录见 [`docs/evidence/agentshield/`](./docs/evidence/agentshield/README.md)。要把某行改成正式支持，需要新的核验记录并重新签发清单。

其它边界：文件系统 / 进程权限不会显示为「真正生效」；Windows 上的网络沙箱依赖 WSL2 或 Docker，当前发布不宣称；没有钩子就拦不住绕过工具层的直连访问。

---

## 想看实现细节

信任如何衔接、审查如何打分、签发如何变成各产品的工具名单、调用如何记账，写在 [`docs/agentshield-dev-spec-v1.md`](./docs/agentshield-dev-spec-v1.md)。形态为什么是三件套，见 [`docs/adr/0011-portable-skill-form.md`](./docs/adr/0011-portable-skill-form.md)。

```text
skills/agentshield/          对话入口、安装脚本、演示用例、已签名清单
apps/agentshield/            本机程序：审查 / 签发 / 控制台 / 核验
apps/web/src/local/          本机控制台（打进程序里）
adapters/runtime/            接到 Hermes / OpenClaw / WorkBuddy 的插头
packages/contracts/          各组件共用的字段约定
docs/control-plane.md        企业控制面
```

```bash
cd apps/agentshield && gofmt -l . && go vet ./... && go test ./...
./agentshield manifest-verify ../../skills/agentshield/skill-manifest.json
AGENTSHIELD_STATE_DIR=$(mktemp -d) ./agentshield admit ../../skills/agentshield
# 期望附条件准入，不得隔离
```

改本机控制台后：`cd apps/web && npm run build:local`，并再跑 `npm run build`，避免企业台的构建产物被带偏。

| 主题 | 文档 |
| --- | --- |
| 本机操作与演示目录 | [`AGENTSHIELD.md`](./AGENTSHIELD.md) |
| 企业控制面 | [`docs/control-plane.md`](./docs/control-plane.md) |
| 检测规则基线 | [`docs/detection-baseline.md`](./docs/detection-baseline.md) |
| 本地台账与企业语义 | [`docs/agentshield-local-ledger-dev-plan-v1.md`](./docs/agentshield-local-ledger-dev-plan-v1.md) |
| 发布与重新签发 | [`docs/agentshield-release-checklist-v1.md`](./docs/agentshield-release-checklist-v1.md) |
| 仓库开发约定 | [`AGENTS.md`](./AGENTS.md) |
