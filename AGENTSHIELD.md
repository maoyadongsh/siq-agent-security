# AgentShield

本地单文件门禁官：盘点 Agent 资产、准入未知 Skill、签发最小权限、给每次工具调用签回执。

**模型不判断 Skill 是否安全。** 裁决只由 `agentshield` 二进制产出。本文件是评委 / 黑客松入口；企业控制面（Control API、PostgreSQL、登录台）见根 [`README.md`](./README.md)。

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

清单里的 `binary.artifacts[].url` 是预定 GitHub Release 路径，**尚未发布**；bootstrap **不会下载**，找不到二进制就失败退出。

## 档位（诚实）

机器可读事实源：[`skills/agentshield/skill-manifest.json`](./skills/agentshield/skill-manifest.json) 的 `support_matrix`。当前**没有任何一行 `supported`**。2026-09-05 已在 DGX Spark（linux/arm64）归档 Hermes L0–L2 路径证据（[`docs/evidence/agentshield/hermes-linux-2026-09-05/`](./docs/evidence/agentshield/hermes-linux-2026-09-05/)）：恶意 fixture `quarantine` / 退出码 3、官方风格 `admit_with_conditions`、Hermes 适配器越权 `web_fetch` deny、`verify` 通过。grant 已由人类 `--approve-as maoyd` 批准并 deploy，授后 `web_fetch` 为 deny。OpenShell 由 PATH 发现 CLI，但本机默认网关未验明为正身（常见：端口被 OpenClaw 占用），L3 不宣称；矩阵在有 probe+网络段读回证据并重签前不改 `supported`。

| 平台 | Linux | macOS | Windows | 说明 |
| --- | --- | --- | --- | --- |
| Hermes | L0–L3 experimental | L0–L2 experimental | L0–L2 experimental | 适配器已落地；L3 仅 Linux 宣称 |
| OpenClaw | L0–L3 experimental | L0–L2 experimental | L0–L2 experimental | policy-exec + 插件已落地 |
| CodeBuddy | L0–L2 experimental | L0–L2 experimental | L0–L2 experimental | hook 已落地；无 L3 |
| Trae | L0 audit_only | L0 audit_only | L0 audit_only | 无工具钩子，不能阻断 |
| Claude Code / Codex | L0 experimental | L0 experimental | L0 experimental | 非本轮 |

L0 审计 · L1 安装门禁 · L2 运行时回执与阻断 · L3 OpenShell 网络策略下发。

## 已知限制

- filesystem / process 策略不能热更新，grant 不得把这两域标成 `effective`
- Trae 只能审计，控制台必须显示无法阻断
- OpenShell `verify` 只到 `readback_verified`，不到 `enforcement_verified`
- AgentShield 会发现 PATH 上的 `openshell`，但**不会**执行 `openshell gateway start`，也不会猜测端口或改别人的网关
- 连到非 OpenShell 进程（OpenClaw / Hermes）时 probe fail-closed；运行 `agentshield openshell doctor` 看下一步
- Windows L3 需要 WSL2 / Docker；本快照不宣称
- GitHub Release 未打 tag；用源码构建，不要指望 url 能下载
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
# 人类执行：
./agentshield grant approve <grant_id> --approve-as <your-name>

# 4. 越权工具调用应 deny（需已安装 Hermes 适配器并走 /v1/decide）
# 5. 回执链
./agentshield verify
```

脱敏回执见 [`docs/evidence/agentshield/`](./docs/evidence/agentshield/README.md)。没有完整证据（含人类批准 grant）的矩阵行保持 `experimental`。

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
