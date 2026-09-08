# Provenance-Bound Effect Security V1 开发台账

- 用户开发模板：[原文，逐字保存](templates/provenance-bound-effect-v1-development-template.md)。
- 模板 SHA256：`9e6d575d0f3bd1639eaa57b59c59e503849b332d86e76289ba1fbbfb998d9817`。
- 实际起点：`d001c4d2c1b7a1230604e8b2ecf813a39deb251c`；分支：`codex/provenance-bound-effect-v1`。
- 本轮开发目标以此模板 §0–120、INV-1–7 和 45 项 DoD 为准；旧 Provenance 优化计划仅作为背景，不覆盖本模板。
- 状态：已设置为持续开发目标，进行中；A1 本地验收通过，继续 A2。不向 main 直接写提交，不修改 GitHub Ruleset 或实际用户平台配置。

| 工作包 | 范围 | 状态 |
| --- | --- | --- |
| A1 | Authority Hard Gate、回执分层、required/optional × 三模式、历史签名兼容 | 本地验收通过；全仓 CI 待最终集成 |
| A2 | 移除 caller cwd 授权、ContextAssertion、受信 workspace 与重放/到期 | 待完成 |
| R | 统一 RuntimeActionDescriptor，高影响参数、shell unknown，六类消费者统一 | 待完成 |
| B1 | 签名 provenance、issuer registry、范围/到期/撤销、容量、不可变存储 | 待完成 |
| B2 | Intent V3 双读、参数内容/来源绑定、MCP 默认不可信、派生/聚合防升级 | 待完成 |
| C1 | EffectEvidence、独立 capability、文件 observer、可控网络 oracle | 待完成 |
| C2 | 幂等/冲突/越权效果事件、CompletionStatus、恢复 | 待完成 |
| D | 独立 benchmark，至少20场景、攻击对应 benign、D0–D5 分母与阶段性能 | 待完成 |
| G | ADR 15–17、威胁27–35、能力矩阵、README、CODEOWNERS、CI smoke/nightly | 待完成 |
| 验收 | 45项DoD、P01–10/C01–04/E01–05、race/全仓CI、最终工程报告 | 待完成 |

完成证据必须绑定具体命令/源码/回执/CI；未覆盖平台保留 unverified。

## A1 实际验证（2026-09-08）

- 修复前新增 `TestMandatoryAuthorityCannotBecomeAdvisoryAllow/warn/intent_binding_missing` 和 `TestCallerCWDDoesNotGrantWorkspaceWrite`，实际执行失败：required+warn 缺绑定仍 allow；伪造 cwd 使未授权 shell 写路径 allow。修复后通过。
- `apps/agentshield: go test -race ./...` 通过，包含 15 类 Authority 错误 × 三模式、required/optional 撤销矩阵、never-bound 策略兼容、HTTP deny 后伪造 Observe 拒绝、历史签名与新字段篡改负例。
- `apps/agentshield: go vet ./...`、linux/amd64、linux/arm64、darwin/arm64、windows/amd64 编译通过；产物在 `/tmp/siq-authority-*`。
- `apps/control-api: .venv/bin/pytest app/tests/test_schema_contracts.py -q` 67 项通过；新增历史/当前/Authority invalid 三份 Go 回执与三模式非法组合测试。Ruff 对修改测试通过。
- `apps/web: npm run build` 通过（包含 TypeScript 编译）。
- A2 中 cwd 隐式写权限已删除，但签名 ContextAssertion 仍待实现；本条不表示 A2 完成。
- A1 不提供断连客户端的独立授权证明；离线模式和外部平台能力仍按实际证据标注。
