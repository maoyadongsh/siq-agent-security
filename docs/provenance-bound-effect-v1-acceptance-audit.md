# Provenance-Bound Effect V1 逐项验收索引（进行中）

核对日期：2026-09-08。源码基线：`915ff2b`，分支 `codex/provenance-bound-effect-v1`。

本文件从用户原文模板提取全部45项DoD，作为最终Engineering Report的验收入口。**定位到测试文件不等于通过该项验收**；本表不公布虚构的完成项数，也不替代模板§0–120、INV-1–7及报告A–K等要求。已运行证据与限制见[开发台账](provenance-bound-effect-v1-progress.md)。

| 条目 | 原文要求 | 首个证据入口 | 本轮审计状态 |
| --- | --- | --- | --- |
| DoD-A1 | Mandatory authority invalid： required + audit required + warn required + block 全部 effective deny。 | [authority_gate_test.go](../apps/agentshield/internal/receipt/authority_gate_test.go) | 本地验收通过；详见Authority证据说明（全目标仍未完成） |
| DoD-A2 | Optional legacy never-bound session 保持兼容。 | [authority_gate_test.go](../apps/agentshield/internal/receipt/authority_gate_test.go) | 本地验收通过；详见Authority证据说明（全目标仍未完成） |
| DoD-A3 | Previously bound session 不得降级。 | [intent_test.go](../apps/agentshield/internal/receipt/intent_test.go) | 本地验收通过；详见Authority证据说明（全目标仍未完成） |
| DoD-A4 | `context.cwd` 不再扩大 Authority。 | [context_test.go](../apps/agentshield/internal/receipt/context_test.go) | 本地验收通过；详见Authority证据说明（全目标仍未完成） |
| DoD-A5 | Trusted workspace 必须来自 signed authority/assertion。 | [context_test.go](../apps/agentshield/internal/intent/context_test.go) | 本地验收通过；详见Authority证据说明（全目标仍未完成） |
| DoD-P1 | 存在 signed ProvenanceAssertion Contract。 | [provenance-assertion.v1.schema.json](../packages/contracts/provenance-assertion.v1.schema.json) | 证据入口已定位；待逐项核读验收 |
| DoD-P2 | Decision client 不能自报 authoritative provenance。 | [validate_test.go](../apps/agentshield/internal/provenance/validate_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-P3 | 存在 TrustedSourceIssuer registry。 | [store_test.go](../apps/agentshield/internal/provenance/store_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-P4 | Parameter → Provenance refs 可以验证。 | [matcher_test.go](../apps/agentshield/internal/provenance/matcher_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-P5 | Provenance 绑定： task session agent | [authority_test.go](../apps/agentshield/internal/provenance/authority_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-P6 | Intent V3 能定义 parameter provenance constraints。 | [provenance_test.go](../apps/agentshield/internal/receipt/provenance_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-P7 | MCP 默认 untrusted。 | [validate-mcp-provenance.py](../scripts/validate-mcp-provenance.py) | 证据入口已定位；待逐项核读验收 |
| DoD-P8 | 普通 Agent transform 不提高 trust。 | [aggregation_test.go](../apps/agentshield/internal/provenance/aggregation_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-P9 | 相同值不同来源能产生不同授权结果。 | [matcher_test.go](../apps/agentshield/internal/provenance/matcher_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-P10 | High-impact parameter 无合法 provenance 时 fail closed / hold。 | [provenance_test.go](../apps/agentshield/internal/receipt/provenance_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-R1 | 存在统一 RuntimeActionDescriptor。 | [describe.go](../apps/agentshield/internal/runtimeaction/describe.go) | 证据入口已定位；待逐项核读验收 |
| DoD-R2 | Grant/Intent/Taint/Provenance 使用同一个 Tool semantic source。 | [describe.go](../apps/agentshield/internal/runtimeaction/describe.go) | 需全范围源码审计，单文件不足证明 |
| DoD-R3 | Shell 继续保留 unknown Effect。 | [describe_test.go](../apps/agentshield/internal/runtimeaction/describe_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-R4 | 现有 tool/resource/effect regression 全部通过。 | [intent_test.go](../apps/agentshield/internal/receipt/intent_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-E1 | 存在 EffectEvidence Contract。 | [effect-evidence.v1.schema.json](../packages/contracts/effect-evidence.v1.schema.json) | 证据入口已定位；待逐项核读验收 |
| DoD-E2 | Decision token 不能伪造 external independent evidence。 | [server](../apps/agentshield/internal/server) | 证据入口已定位；待逐项核读验收 |
| DoD-E3 | Tool success 不自动成为 verified effect。 | [evaluate_test.go](../apps/agentshield/internal/completion/evaluate_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-E4 | file.write 存在 host observer fixture。 | [file_test.go](../apps/agentshield/internal/effectevidence/file_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-E5 | network.request 存在 controlled external oracle fixture。 | [runtime-security](../benchmarks/runtime-security) | 证据入口已定位；待逐项核读验收 |
| DoD-E6 | denied action 出现真实 effect 时产生 security finding。 | [correlation_test.go](../apps/agentshield/internal/effectevidence/correlation_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-E7 | conflicting evidence 被明确表示。 | [store_test.go](../apps/agentshield/internal/effectevidence/store_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-E8 | 存在 minimal CompletionStatus。 | [evaluate_test.go](../apps/agentshield/internal/completion/evaluate_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-B1 | 建立： benchmarks/runtime-security/ | [runtime-security](../benchmarks/runtime-security) | 证据入口已定位；待逐项核读验收 |
| DoD-B2 | 实现 D0–D5 数据模型。 | [scenario.schema.json](../benchmarks/runtime-security/scenario.schema.json) | 证据入口已定位；待逐项核读验收 |
| DoD-B3 | 至少 20 个 deterministic security scenarios。 | [check_contracts.py](../benchmarks/runtime-security/check_contracts.py) | 证据入口已定位；待逐项核读验收 |
| DoD-B4 | 每类攻击至少有 benign control。 | [scenarios](../benchmarks/runtime-security/scenarios) | 证据入口已定位；待逐项核读验收 |
| DoD-B5 | 报告： false allow false deny benign completion unknown effect D2–D5 outcomes | [metrics.py](../benchmarks/runtime-security/metrics.py) | 证据入口已定位；待逐项核读验收 |
| DoD-B6 | 没有 Oracle 的样本不得计 D5 success/failure。 | [test_metrics.py](../benchmarks/runtime-security/test_metrics.py) | 证据入口已定位；待逐项核读验收 |
| DoD-C1 | Trusted Intent V2 历史 Receipt 仍可验证。 | [authority_gate_test.go](../apps/agentshield/internal/receipt/authority_gate_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-C2 | Intent V2 dual-read 保留。 | [store_test.go](../apps/agentshield/internal/intent/store_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-C3 | OpenClaw approval execution recheck 不退化。 | [test-openclaw-adapter.cjs](../scripts/test-openclaw-adapter.cjs) | 证据入口已定位；待逐项核读验收 |
| DoD-C4 | Binding revocation 不退化。 | [revocation_test.go](../apps/agentshield/internal/intent/revocation_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-C5 | Hermes / OpenClaw / CodeBuddy 现有核心测试通过。 | [ci.yml](../.github/workflows/ci.yml) | 本轮核心兼容检查通过，见下方命令与证据；不等于原生V3集成完成 |
| DoD-C6 | Legacy optional authorization 继续按现有安全兼容语义工作。 | [authority_gate_test.go](../apps/agentshield/internal/receipt/authority_gate_test.go) | 证据入口已定位；待逐项核读验收 |
| DoD-G1 | Go race tests 全绿。 | [ci.yml](../.github/workflows/ci.yml) | 证据入口已定位；待逐项核读验收 |
| DoD-G2 | 全仓 CI green。 | [runtime-security.yml](../.github/workflows/runtime-security.yml) | 92b9efe远端运行中；当前HEAD待推送验证 |
| DoD-G3 | 没有新增无界 map。 | [capacity_test.go](../apps/agentshield/internal/provenance/capacity_test.go) | 需全范围源码审计，单文件不足证明 |
| DoD-G4 | 没有新增第二套 signing/canonicalization。 | [signing](../apps/agentshield/internal/signing) | 需全范围源码审计，单文件不足证明 |
| DoD-G5 | 没有新增 LLM final authorization。 | [AGENTS.md](../AGENTS.md) | 需全范围源码审计，单文件不足证明 |
| DoD-G6 | 没有把实现 evidence 写成 production supported。 | [agentshield-capability-matrix-v1.md](../docs/agentshield-capability-matrix-v1.md) | 证据入口已定位；待逐项核读验收 |

## 已识别的验收边界

- 模板DoD-E4/E5要求host observer及受控外部oracle fixture；现有组件夹具可以用于这两项验收，但不能证明生产隔离或所有平台原生集成。
- DoD-C5明确要求三平台“现有核心测试”，不能只用Hermes V3桥接结果替代OpenClaw/CodeBuddy；需要列出各自现有核心命令和当前结果。
- DoD-B5及最终报告G需要D2–D5逐层结果。当前metrics.py分别输出阶段分母、未评估数量、positive_rate和命名指标；报告须解释D2尝试、D3执行、D4观测、D5独立核实的不同语义，不能把全部叫攻击成功率。
- metrics中的benign completion分母仅包括有Completion记录的正常样本；unknown effect分母仅包括有effect_record的样本。最终报告必须同时公开缺少记录的数量，不能暗示覆盖所有42个观测。
- G3要求“没有新增无界map”，provenance容量测试只覆盖一部分；须审计相对于起点新增的全部map/缓存及淘汰策略。G4/G5也须检查完整diff，而不是依赖规范文字。
- 全部DoD通过仍不足以省略模板§115的Engineering Report及前文指定测试/交付物；最终SHA和CI证据必须对应，不能用54f5d32的绿灯替代后续修改。

## 下一批核验顺序

1. 逐项阅读A/P/R对应实现与测试，记录真实覆盖范围及遗漏。
2. 三平台核心兼容命令、全范围map与签名路径审计。
3. 基准完整报告的逐阶段分母、证据归档及最终报告要求映射。
4. 将未满足项作为开发任务完成后，再形成最终Engineering Report；当前目标继续保持进行中。


## 三平台核心兼容核验（2026-09-08）

源码基线deeebee，本轮仅增加CI/文档。结果摘要与原报告SHA见[evidence](evidence/provenance-v1/platform-core-20260908.json)。日志中的Go cached结果是测试工具复用有效缓存，server为本次执行；不能称所有包均无缓存重跑。

| 命令（仓库根目录，Go命令在apps/agentshield） | 结果与范围 |
| --- | --- |
| `node scripts/test-openclaw-adapter.cjs` | correlation、宿主capability、approval recheck通过 |
| `python3 scripts/test-openclaw-checkpoint-compat.py` | 15项兼容测试通过 |
| `go test -race ./cmd/agentshield ./internal/adapterinstall ./internal/server` | 三包通过，包含CodeBuddy bootstrap及配置生命周期 |
| `apps/control-api/.venv/bin/pytest adapters/runtime/hermes-agentshield/tests/test_adapter.py -q` | 56项通过；Ruff通过，新增CI门禁 |
| `python3 scripts/validate-intent-v2-hermes.py --hermes-root /home/maoyd/siq/hermes-agent --hermes-python /home/maoyd/siq/hermes-agent/.venv/bin/python --out /tmp/siq-platform-hermes.json` | 默认200样本/8并发，14类检查、412回执通过 |
| `python3 scripts/validate-intent-v2-codebuddy.py --codebuddy-root /home/maoyd/.local/share/siq-runtime-fixtures/codebuddy-2.146.0/node_modules/@tencent-ai/codebuddy-code --node /home/maoyd/.nvm/versions/node/v22.22.1/bin/node --out /tmp/siq-platform-codebuddy.json` | 10类原生CLI流程、13回执通过 |
| `python3 scripts/validate-codebuddy-hook-failures.py --codebuddy-root /home/maoyd/.local/share/siq-runtime-fixtures/codebuddy-2.146.0/node_modules/@tencent-ai/codebuddy-code --node /home/maoyd/.nvm/versions/node/v22.22.1/bin/node --out /tmp/siq-platform-codebuddy-failures.json` | 正常/故障/恢复10场景通过；包括legacy warn/audit兼容，不外推为required权限绕过允许 |

这些结果覆盖DoD-C5的现有核心兼容命令；OpenClaw本批为钩子/兼容测试，没有重跑其全部原生网关会话。V3来源原生传播、效果调度及全目标其他项仍待继续。


## Authority A1–A5本地验收结果（2026-09-08）

核读生产`runtimeauthz/gate.go`、`receipt/engine.go`、`receipt/context.go`及签名Context存储，逐项核读以下测试，并在Go1.26.6无缓存race运行receipt/intent/server相关测试通过，日志/tmp/siq-authority-acceptance.log。receipt vet通过。

| 条目 | 已核读并执行的证据 | 判断与边界 |
| --- | --- | --- |
| A1 | TestMandatoryAuthorityCannotBecomeAdvisoryAllow：15类错误×3模式；TestUnknownAuthorityErrorFailsClosed；真实Context与撤销集成 | 无效Authority effective deny、无advisory、不进policy，拒绝字段签名保护。错误分类矩阵部分用受信lookup注入，真实签名路径由其他集成测试交叉覆盖 |
| A2 | TestOptionalNeverBoundKeepsPolicyModes | 从未绑定会话保留allow以及普通policy三模式行为；不把所有warn/audit策略改为hard deny |
| A3 | 新增TestSignedBoundSessionCannotDowngradeAcrossModesAndRestart | 真实签名Store绑定建立后，required/optional×3模式×重启前后12次降级拒绝，保留Intent摘要及bound状态 |
| A4 | TestCallerCWDDoesNotGrantWorkspaceWrite；源码无caller cwd授权入口 | 伪造/secret cwd不能授权写入，随后假Observe也拒绝；该项不要求普通policy advisory模式全部改为deny |
| A5 | TestContextIntegrityScopeReplayAndExpiry、TestContextReferenceHardGateAndRecovery、TestContextCannotReplaceGrantAndApprovalRechecksExpiry、TestContextIssuanceIsAdminOnly | Context必须从管理端签发、存储验签；request/scope/expiry绑定且重启复核，不能替代Grant；不声称已经部署外部attestor |

这5项的本地验收状态不等于最终45项DoD通过率或工程百分比。新增测试所在最终提交仍需远端CI；其他条目仍按各自状态取证。
