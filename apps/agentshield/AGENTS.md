# apps/agentshield 工作约定

AgentShield 本地二进制（Go）。上层约束见仓库根 `AGENTS.md`；本文只写本模块的就近规则。实现规格是 `docs/agentshield-dev-spec-v1.md`——**先读它，再改代码；规格与代码冲突时先改规格。** W7 本地台账计划见 `docs/agentshield-local-ledger-dev-plan-v1.md`（新 API / 状态文件须先回写规格）。

## 模块与职责

| 包 | 职责 | 状态 |
| --- | --- | --- |
| `internal/canon` | 与 CPython `json.dumps(sort_keys=True, separators=(",",":"))` 逐字节一致的规范化 JSON | 完成 |
| `internal/rulepack` | 内嵌规则包、外部包 Ed25519 验签、防降级、fail-closed 回退 | 完成 |
| `internal/threat` | 静态分析器（Python `threat_analysis.py` 移植，AST 层缺席） | 完成 |
| `internal/signing` | 本地 Ed25519 身份、文档/字节签名与验签 | 完成 |
| `internal/inventory` | 只读盘点：平台配置、Skill、Hermes profiles、OpenClaw agents.list；可选 `--connectors-dir` **exec** 子进程（不 import `connectors/*`） | 规格 §3.5 |
| `internal/export` | 脱敏导出包 `agentshield.export.v1`（无私钥/token/参数原文） | 规格 §3.8.1.3 |
| `internal/controlsync` | `sync --control-api` → Edge `POST /edge/v1/batches`；缺凭据跳过；失败不改本地决策 | 规格 §2.4 |
| `internal/admission` | frontmatter、哈希、限额、决策表、Skill Card | 完成（决策表变更需同步规格 §3.6.4 与 `dispositions.go`）|
| `internal/grant` | declared → allowlist / DesiredPolicy；状态机；`PatchDesired`；读回 effective | 完成（`CompilePolicy` 与 Python `artifact_hash` 对等）|
| `internal/receipt` | 决策引擎、污点/trifecta、哈希链、Verify；block 下无 host 的出网 exec deny | 完成 |
| `internal/state` | 状态目录、token、admission/grant/policy/assets/findings/audit 文件态存储 | 完成 |
| `internal/ledger` | 台账投影 + 资产生命周期 refresh（G7）；confirm/dismiss/drift/accept | 完成 |
| `internal/server` | `/v1/*` HTTP（loopback + bearer）+ `/ui-config.json` + embed UI | 完成 |
| `internal/adapterinstall` | `adapter install/uninstall/status`：写主机钩子，先备份可还原 | 完成 |
| `internal/openshell` | probe / 网络 `policy set` / 读回；不调 `create_generation` | 完成 |
| `internal/ui` | embed `apps/web` 本地模式构建产物（`npm run build:local`） | 完成 |
| `cmd/agentshield` | 子命令入口（含 `admit`/`grant`/`adapter`/`openshell`/`serve`/`export`/`sync`/`release-manifest`/`manifest-verify`） | 完成 |
| `internal/skillmanifest` | 发布清单构建、Ed25519 验签、诚实 support_matrix | 完成 |

## 硬性规则

1. **仅标准库。** 需要第三方依赖（如 tree-sitter）先立 ADR。交叉编译 `linux/{amd64,arm64}`、`darwin/arm64`、`windows/amd64` 必须始终通过；不得引入 `fcntl`/`syscall` 平台专属调用，文件独占用 `O_EXCL`。
2. **规则包是共享文件。** `internal/rulepack/data/threat_rules.v1.json` 必须与 `apps/control-api/app/data/threat_rules.v1.json` 逐字节一致（`TestEmbeddedPackMatchesControlPlaneCopy` 锁定）。改模式：RE2 可编译、CPython 语义等价、附边界用例、两侧测试都跑。
3. **对等优先于"更好"。** `threat` 的输出（sha256 / rule_id / line / excerpt_sha256 / excerpt）必须与 Python 相同；想改行为先在 Python 侧改并同步语料，再移植。
4. **签名只签规范化字节。** 所有文档签名 = `Ed25519(canon.Marshal(doc 去掉 signature))`，十六进制 128 位；回执链签 `hash` 字符串字节。任何新文档类型都走 `signing`，不得自建序列化。
5. **状态目录之外不写。** 路径由 `state` 包解析（`AGENTSHIELD_STATE_DIR` 覆盖）；目录 0700、文件 0600；只追加或新建，禁止原地改写准入/签发/回执文件。
6. **不执行被分析内容。** 不 `import` Skill、不解压嵌套压缩包、不跟随符号链接；git 来源用 `--depth 1` 并禁用 hooks。可选 `--connectors-dir` 仅 **exec** connector 二进制（规格 §3.5），禁止 import `connectors/*`。
7. **模型不是权威。** 任何未来的 LLM 语义层只能产生 `inferred` 事实或 `info` finding，不能改 verdict / action / status。
8. **fail-closed 表是合同。** `block` 模式下服务不可达、超时、401、非法响应 = 拒绝；`audit_only`/`warn` = allow + `advisory_action`。每个适配器必须有对应负向测试。
9. **日志只记类别。** 拒绝原因、异常消息不得包含规则内容、参数、文件内容或密钥。

## 测试要求

```bash
gofmt -l . && go vet ./... && go test ./...
for t in linux/amd64 linux/arm64 darwin/arm64 windows/amd64; do GOOS=${t%/*} GOARCH=${t#*/} go build ./cmd/agentshield || exit 1; done
```

- 每个内置检查、每条决策表行、每个 fail-closed 场景：**一正一负**。
- 边界值：限额恰好等于上限通过，+1 拒绝。
- 与 Python 对等的部分用**共用语料/固定向量**（`../control-api/app/tests/fixtures/threat/corpus.json`、CPython 生成的 canon/signing 向量），不得各写各的样例。
- 输出样例写入 `testdata/contracts/*.json` 并由 `apps/control-api/app/tests/test_schema_contracts.py` 用 schema 校验；Go 测试断言运行时输出与样例一致。
- 不写变更探测器：不要断言规则条数、版本号字面量等预期会变的数据；断言关系（如「每条规则至少一个语料命中」）。

## 提交

`agentshield: <主题>`；规则包改动用 `rulepack:`；涉及合同同时改 `packages/contracts/` 并用 `contracts:` 单独提交。安全修复必须带证明旧行为被拒绝的负向测试。
