# KIMI-001-R1 交接：语义修复与最终验证

```text
任务：KIMI-001-R1
状态：ready_for_review（CI 通过不等于审阅通过；远端三工作流已对候选实跑通过）
实际基线：c1a4b0f9d6074dfccdbf15841bafe79defd74f45（含审阅方 90bd14e、c1a4b0f，本机只读核对+快进同步，未覆盖任何改动）
被测代码候选：32be3b353d8b26082b4492638afe8abcbf0da267（全部代码/测试/构建产物冻结于此；CI 运行对象）
最终分支 HEAD：本交接的 docs 回填提交（仅文档，不改被测代码；SHA 在最终回复与 PR 中给出）
新增提交和逐文件目的：
- 790a9e2 agent: R1-A 语义分离（skills.py 移除 reason 前缀兜底恢复原 fail-closed；gateway.Blocked 还原纯 reason_code；test_application.py 重写三类场景；README 与 DemoPage 文案按当前语义；新增 docs/adr/0048 提案登记设计阻塞）
- 44f2a2a agentshield: R1-B 确定性在途提交并发测试 internal/state/commit_inflight_test.go；commit.go 的 commitBoundary 注释更新为测试用途约定
- d54370d web: 重建本地演示内嵌产物（DemoPage 文案的构建结果）
- 22c3792 hackathon: scripts/hackathon/browser-smoke.py 的 trifecta 预期按 ADR-025 边界拒绝语义校正
```

## R1-A：三类场景实际语义

1. **凭据硬拒绝**：`test_confidential_credential_read_denied_before_network`——`.env` 读取被 Go 边界拒绝（`runtime_denied`，回执 reason 为 `credential path ... denied`），工具未进入（d3_materialized=false）、无 Observe 伪报、任务止于任何网络动作前；拒绝尝试在决策时保守置位 private_data=true（引擎行为，见下）。
2. **真实允许读取**：`test_confidential_note_read_allowed_without_private_classification`——`confidential-note.txt` 经真实 ToolAdapters 成功读取（O_NOFOLLOW、固定字节比对在 tools.py），引擎当前**不**把非凭据文件分类为私有数据（private_data 全程 false），任务走正常授权链完成。该现状差异登记为设计阻塞 `docs/adr/0048-private-data-classification-entry.md`（提案，未实施，列三个候选方向）。
3. **拒绝尝试后的保守状态**：引擎层 `TestLethalTrifectaDenied`（apps/agentshield/internal/receipt/receipt_test.go:196）已覆盖——被拒绝的 `.env` 读取仍置 private_data，随后不可信输入+出网触发 lethal trifecta；应用层由用例 1 记录同一置位。无「通用 SkillRunner 吞拒绝」逻辑残留。
4. **无关拒绝负向**：`test_confidential_read_denied_for_unrelated_reason_still_terminates`——Intent 被撤销导致的拒绝同样终止流程。
5. `gateway.Blocked.reason` 已随兜底移除而删除；演示 UI/冒烟不再以人类可读 reason 文本控制流程或作断言依据。
6. 审阅方两项修复（内嵌适配器同 blob、confidential_name 前置校验）保持原样，`test_confidential_preflight` 本地通过。

## R1-B：确定性并发证明与变异检查

- 提交内：`internal/state/commit_inflight_test.go` 在 grant 已发布、done 未发布的真实窗口（commitBoundary 通道门控）内证明：读取方得 `ErrIncompleteCommit`；同草稿重复提交方在 commitMu 上等待（有界超时仅证明窗口内未完成）；写者释放后重复方冲突、重读收敛同一草稿 seq=0、创建审计仅一条。-count=20 与 -race 通过。
- 变异检查（隔离 worktree，未提交任何变异代码）：注入 commit.go 窗口加宽 50ms + 错峰请求测试；将 handler 回退为对 ErrIncompleteCommit 直接 409 后，错峰请求 3/3 确定性失败（`409 grant_draft_unavailable`，与 CI 原症状一致）；恢复修复后同窗口 5/5 通过。这同时构成原 CI 失败的确定性机制复现。
- 保留不动：源 revision/CAS、签名校验、操作者/请求隔离、`TestGrantDraftHTTPTornCommitRefusedThenSettled` 的崩溃撕裂负向。

## R1-C：最终候选复验

以最终候选（含全部 R1 提交）整树复验，逐项命令/退出码见 `docs/evidence/personal-experience/kimicode-k001-r1-20260911/verification.json`。要点：Go 全量 `-count=1` 与 `-race -count=1` 各 33 包通过；secure-agent 104 项通过；适配器两份文件逐字节一致（cmp）；ruff/pytest、研究四项、控制面合同与全量 pytest、benchmark smoke+hackathon 语料、浏览器九场景（含修正后 trifecta 预期）、web 测试与双构建、四目标交叉编译、manifest-verify、自扫描 admit_with_conditions、govulncheck（go1.26.6）零发现、gitleaks 提交范围无泄露。

## 未验证范围

- 远端 CI 已回填，见下节。
- control-api alembic 干净 PostgreSQL 回放：本机无隔离 PostgreSQL 服务（本批未改其模型/迁移）；CI control-api job 含该步骤且通过。
- playwright `--with-deps` 的 apt 步骤需 sudo 未执行；浏览器夹具用系统已有 chromium 通过，CI hosted chromium 步骤亦通过。
- 本机 linux/arm64，CI 为 amd64；远端运行已覆盖 amd64。

## 远端 CI（推送后实跑回填）

候选 HEAD `32be3b353d8b26082b4492638afe8abcbf0da267`（推送后 PR #27 触发）：

- ci run 34573854493：success（agentshield、gitleaks、web、control-api、edge 双版本 × 12 模块全部 success）
- runtime-security run 34573854583：success（runtime-security-contracts、runtime-security-toolchain 均 success；nightly 按事件条件不运行，登记为条件性跳过而非通过）
- research run 34573854590：success（research-reproduction）
- pages run 34573854646：success（非本批范围，无回归）

## 记录更正

- K001 交接对并发项的表述（本机未自然复现、经 CI+源码定位）保持准确；K001 最终回复中「均已先复现」的概括不适用于并发项，R1 的变异实验补齐了确定性复现证据。
- K001 verification.json 中 gitleaks 提交范围扫描的占位项，实际结果已执行并登记（no leaks found）。
- K001 的 `secure-agent-after2.log` 等历史证据文件保留未改。

## 是否推送

是（用户已授权推送到原分支以更新 PR #27）。未合并、未改 main、未改保护/工作流门槛、未发布、未动用户服务。
