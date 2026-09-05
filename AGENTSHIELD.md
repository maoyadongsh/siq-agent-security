# AgentShield

本地单文件门禁官：盘点 Agent 资产、准入未知 Skill、签发最小权限、给每次工具调用签回执。

**模型不判断 Skill 是否安全。** 裁决只由 `agentshield` 二进制产出。本文件是评委 / 黑客松入口；企业控制面（Control API、PostgreSQL、登录台）见根 [`README.md`](./README.md)。本地控制台将按 [`docs/agentshield-local-ledger-dev-plan-v1.md`](./docs/agentshield-local-ledger-dev-plan-v1.md) 对齐企业台账观感；评委复现仍只需 `serve`，不必启动控制面。

仓库：[`maoyadongsh/siq-agent-security`](https://github.com/maoyadongsh/siq-agent-security)  
分支：`cursor/agentshield-w0-contracts-8eff`（尚未合入 `main`；clone 默认分支看不到本产品）

## 三步（本机复现）

需要 Go 1.22+。Node 只在改本地控制台时需要。

```bash
git clone https://github.com/maoyadongsh/siq-agent-security.git
cd siq-agent-security
git fetch origin cursor/agentshield-w0-contracts-8eff
git checkout cursor/agentshield-w0-contracts-8eff

cd apps/agentshield
go test ./...
go build -trimpath -ldflags "-s -w -X main.Version=0.1.0" -o agentshield ./cmd/agentshield
export AGENTSHIELD_STATE_DIR="${AGENTSHIELD_STATE_DIR:-$(pwd)/.state}"
./agentshield serve --port 47611
```

浏览器打开 `http://127.0.0.1:47611`。Bearer token 在 `$AGENTSHIELD_STATE_DIR/token`（0600），不要贴进聊天或截图。

Skill 入口（Hermes 等加载 `skills/agentshield` 时）：

```bash
skills/agentshield/scripts/bootstrap.sh   # Windows: bootstrap.ps1
skills/agentshield/scripts/adapter.sh     # 探测并安装当前平台钩子
```

bootstrap 会用内置公钥校验 `skill-manifest.json` 签名。本地 `go build` 的二进制哈希通常与清单里的发布钉不一致，默认只告警；要强制钉死则设 `AGENTSHIELD_REQUIRE_PINNED=1`。

清单里的 `binary.artifacts[].url` 指向 GitHub Release `agentshield-v0.1.0`（已上传四目标二进制）。bootstrap **仍不会下载**；找不到本地二进制就失败退出。评委复现继续用下面的源码 `go build`。

## 档位（诚实）

机器可读事实源：[`skills/agentshield/skill-manifest.json`](./skills/agentshield/skill-manifest.json) 的 `support_matrix`。当前**没有任何一行 `supported`**。2026-09-05 已在 DGX Spark（linux/arm64）归档：Hermes 实机插件 L0–L2（[`hermes-linux-2026-09-05/`](./docs/evidence/agentshield/hermes-linux-2026-09-05/)）、OpenClaw 隔离 HOME 的 `policy-exec` + 插件形态 decide（[`openclaw-linux-2026-09-05/`](./docs/evidence/agentshield/openclaw-linux-2026-09-05/)）、CodeBuddy 隔离 HOME 的真实 `hook codebuddy`（[`codebuddy-linux-2026-09-05/`](./docs/evidence/agentshield/codebuddy-linux-2026-09-05/)）。grant 均由人类 `--approve-as maoyd` 批准并 deploy，授后越权为 deny，`verify` 通过。L3 需验明的 OpenShell 网关，可选、不宣称。OpenShell 由 PATH 或 `SIQ_AS_OPENSHELL_ENV_SH` 发现 CLI，但默认不得把未验明的网关（常见：端口被 OpenClaw 占用）当成 L3；矩阵在重签前不改 `supported`。

| 平台 | Linux | macOS | Windows | 说明 |
| --- | --- | --- | --- | --- |
| Hermes | L0–L3 experimental | L0–L2 experimental | L0–L2 experimental | Linux L0–L2 有 Spark 证据；L3 可选未宣称 |
| OpenClaw | L0–L3 experimental | L0–L2 experimental | L0–L2 experimental | linux L1 `policy-exec` + L2 decide 证据已归档；未挂本机 OpenClaw 网关；矩阵不改 |
| CodeBuddy | L0–L2 experimental | L0–L2 experimental | L0–L2 experimental | linux `hook codebuddy` 证据已归档；非 GUI 客户端；无 L3；矩阵不改 |
| Trae | L0 audit_only | L0 audit_only | L0 audit_only | 无工具钩子，不能阻断 |
| Claude Code / Codex | L0 experimental | L0 experimental | L0 experimental | 非本轮 |

L0 审计 · L1 安装门禁 · L2 运行时回执与阻断 · L3 OpenShell 网络策略下发。

## 已知限制

- filesystem / process 策略不能热更新，grant 不得把这两域标成 `effective`
- Trae 只能审计，控制台必须显示无法阻断
- OpenShell `verify` 只到 `readback_verified`，不到 `enforcement_verified`
- AgentShield 会发现 PATH 上的 `openshell`，但**不会**执行 `openshell gateway start`，也不会猜测端口或改别人的网关
- 接入已有 OpenShell（例如 research-engine 的 `siq-openshell-dev`）时设 `SIQ_AS_OPENSHELL_ENV_SH` 指向其 `scripts/openshell/env.sh`；不要改对方仓库。AgentShield 不 `gateway start`
- Windows L3 需要 WSL2 / Docker；本快照不宣称
- GitHub Release tag `agentshield-v0.1.0` 已切；评委仍以源码构建为准。bootstrap 不按 URL 下载。操作清单：[`docs/agentshield-release-checklist-v1.md`](./docs/agentshield-release-checklist-v1.md)
- 批准 grant 必须人工 `--approve-as` / 控制台点击；SKILL.md 禁止模型批准

## 演示（评委路径）

在已 `serve` 的前提下：

```bash
# 1. 恶意 Skill → 隔离
./agentshield admit ../../skills/agentshield/evals/fixtures/toxic-finreport-enhancer
# 期望 verdict=quarantine，退出码 3

# 2. 干净 / 官方风格 Skill → 附条件准入
./agentshield admit ../../skills/agentshield/evals/fixtures/official-like
# 期望 admit_with_conditions

# 3. 起草 grant（不要让模型批准）
./agentshield grant <admission_id> --platform hermes --subject demo
# 若该 admission 已有 pending/approved/deployed grant，命令会 reused=true，不会覆盖。
# 人类执行：
./agentshield grant approve <grant_id> --approve-as <your-name>
./agentshield grant deploy <grant_id>

# 4. 越权工具调用应 deny（Hermes 插件会 POST 同一请求体；不要把 token 贴进聊天）
TOKEN=$(cat "$AGENTSHIELD_STATE_DIR/token")
curl -sS http://127.0.0.1:47611/v1/decide \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"platform":"hermes","session_id":"judge-demo","agent_id":"demo","tool":"web_fetch","params":{"url":"https://evil.example/"}}'
unset TOKEN
# 期望 action=deny（未部署 grant 时是 default deny；已部署且未授 web_fetch 时是 tool not granted）

# 5. 回执链
./agentshield verify
```

脱敏回执见 [`docs/evidence/agentshield/`](./docs/evidence/agentshield/README.md)。即使已有 linux 证据，矩阵行在重签前仍保持 `experimental`。

## 台账演示（加分主界面，非前置依赖）

三步对抗之后，打开 `http://127.0.0.1:47611`（无需登录、不必起 PostgreSQL / `:8600`）：

1. **智能体资产** `/agents`：本机平台、Hermes profile / OpenClaw agent、Skill；详情可确认/驳回，准入后起草签发，批准前可改五域。
2. **权限视图** `/permissions`：五态分色。无 OpenShell 时「有效」列应为空；`deployed` grant 仍是声明态。filesystem / process 永不标有效。有 L3 时可跑漂移检测。
3. **风险中心** `/findings`：准入与漂移 finding；接受须原因和到期。
4. **回执** `/receipts`：越权调用的 deny 高亮，并可验签。
5. **设置**：下载脱敏导出包（无私钥、无 token）。也可用 `agentshield export --out ./agentshield-export.json`。`sync --control-api` 不是现场步骤。

顶栏保持「本地模式 · 单用户」。旧书签 `/inventory`、`/admissions` 会转到 `/agents`。

## 十日谈（十条）

1. 用户拿到一份来历不明的 Skill。
2. 模型被要求「先看看安不安全」——它不得自己判断。
3. `agentshield admit` 给出 quarantine 或附条件准入。
4. 隔离则停止安装，不改候选来「刷过」。
5. 附条件准入列出 declared 能力，写成 Skill Card。
6. 人类批准 grant；模型禁止 `--approve-as`。
7. 适配器把工具调用转到 `/v1/decide`。
8. 越权出网或读凭据 → deny，回执入链。
9. `verify` 重算哈希链；断链即失败。
10. OpenShell 若在：先 `openshell doctor` 验明正身再下发网络段并读回；fs/process 仍非 effective。AgentShield 不 `gateway start`。

## 仓库地图

| 路径 | 作用 |
| --- | --- |
| `apps/agentshield/` | Go 单文件二进制（仅标准库） |
| `skills/agentshield/` | SKILL.md、bootstrap、evals、签名清单 |
| `adapters/runtime/` | Hermes / OpenClaw / CodeBuddy 薄适配器 |
| `packages/contracts/` | admission / grant / receipt / skill-manifest schema |
| `apps/web/src/local/` | 本地控制台；`npm run build:local` 嵌入二进制 |
| `apps/control-api/` | 企业控制面（评委不必跑） |

## 验证命令

```bash
cd apps/agentshield && gofmt -l . && go vet ./... && go test ./...
./agentshield manifest-verify ../../skills/agentshield/skill-manifest.json
AGENTSHIELD_STATE_DIR=$(mktemp -d) ./agentshield admit ../../skills/agentshield
# 期望 admit_with_conditions，不得 quarantine
```
