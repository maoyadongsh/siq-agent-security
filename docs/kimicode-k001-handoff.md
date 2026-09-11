# KIMI-001 交接：CI 基线恢复与回归修复

```text
任务：KIMI-001
状态：local_verified / awaiting_ci
实际基线 SHA：b9e8ec6e1cb5f59c3346a2f5bdefd1582cc1b6f8（与任务书参考 HEAD 一致）
当前分支：kimicode/personal-k001-baseline-repair
本批提交 SHA：6297c9b（agentshield）、2fdae25（agent）、19f1d6a（adapters）、aae9d56（research）+ 本文档批次（SHA 见最终回复）
初始未提交/未跟踪内容与归属：仅 docs/KIMI-001-baseline-recovery-taskbook.md（本任务书原文，用户提供）
实际改动文件及每项理由：见各问题小节与对应提交
```

## 预检记录（K001-0）

- 工作区：分支 main 与 origin/main 一致，无暂存/未提交修改；仅有任务书原文未跟踪。
- 本机环境：Linux arm64（aarch64），Go 1.26.5（另经 GOTOOLCHAIN 取得 go1.22.12 arm64 用于对照），Node v22.22.2 / npm 10.9.7，Python 3.13.12，uv 0.11.7。
- CI 环境差异（保留登记）：ci/agentshield 用 Go 1.22（1.22.12）linux/amd64；runtime-security toolchain 用 Go 1.26.6 linux/amd64 + `-race`；research 用 uv 锁定环境 linux/amd64。本机 arm64 通过不能替代 amd64 CI，最终状态以远端 CI 为准。
- 失败证据取自任务书指定 run/job 的实际日志（2026-09-11T00:46–00:47Z）：
  - K001-A（ci run 34547879662）：`TestGrantDraftHTTPIndependentIdempotentAndAudited` 并发出现 `409 grant_draft_unavailable`；`TestGrantDraftContractSamples` 报 `draft contract drift grant-draft-created.json`。
  - K001-B（runtime-security toolchain run 34547879710 / job 103104306665）：同组两个测试在 `go test -race ./...` 下失败（日志为断言失败，未见 race detector 报告数据竞争）。
  - K001-C（runtime-security contracts job 103104306477）：`test_application.py` 20 个 ERROR（`secure_agent.gateway.Blocked: runtime_denied`）、`test_service.py` 7 个 FAIL（如 `'failed' != 'verified'`）。
  - K001-D（research run 34547879675 / job 103104306293）：`test_current_license_inventory_and_missing_notice` 与 `test_inventory_fails_if_audited_bundle_changes` 报 `ValueError: dependency inventory does not match lockfile`。

## 问题 A/B（Grant 草稿并发幂等 + 合同样例）

- 状态：已复现（样例漂移）/ 根因已定位（并发）、修复进行中
- 并发 409：本机直接重跑（-count=20/30、-race、go1.22.12）未复现；经代码走查定位为时序窗口。`replayCommit` 先发布 `grants/<id>.0.json` 再发布 `.done.json` 可见性标记（commit.go），而 `GetGrantWithSeq` 在 grant 文件已可见、done 标记未发布时会经 `checkGrantCommit` 返回 `ErrIncompleteCommit`（非 ErrNotExist），handler 将其映射为 `409 grant_draft_unavailable`。CI（amd64、不同 I/O 调度）放大了该窗口。
- 合同样例漂移：已复现。在 `/tmp/k001-wt`（同提交、不同绝对路径）运行 `TestGrantDraftContractSamples` 即失败。逐字段 diff 显示仅 `evidence_ids`（`ev-*`）不同。证据 ID 按来源定位符（绝对路径）派生——这是 admission 的既定安全设计（`TestEvidenceIDsAreScopedToSourceLocator` 锁定同内容不同定位符不得复用证据 ID），样例把路径相关值固化进跨环境比对的合同，属夹具/样例设计问题。
- 处置方向：handler 对进行中的 commit 读不直接 409（进入串行提交路径收尾），样例/夹具按既有路径无关样例的既有模式固定证据 ID 输入；不改变授权规则、不放宽签名/CAS/单写者语义。

## 问题 C（Secure Agent runtime_denied）

- 状态：已复现 / 已定位 / 已修复 / 本地已验证
- 复现：本地 100 个测试复现 CI 的 failures=7 + errors=20（证据 `secure-agent-before.log`）。
- 根因 1（全部 27 个失败/错误共因）：M34 落地 ADR-025「网络范围=主机+端口精确匹配」（dev-spec §个人权限资源边界修正、`receipt/resource_scope.go` 的 `hostGranted` 要求端口相等、`grant.NormalizeNetworkEndpoint` 要求 host:port）。演示授权准备 `deploy_application_grant` 仍按旧语义只给裸主机 `127.0.0.1`，动态端口的夹具 endpoint 永远匹配失败 → 首个 web_fetch 即 `deny: network egress to 127.0.0.1:<port> not in grant`（reason_code=runtime_denied）。属演示/测试准备未满足新合同，非引擎回归；修复在演示层把夹具 endpoint 以 host:port 显式授权（更严格，不含端口通配）。
- 根因 2（修复根因 1 后剩余 3 个 trifecta/凭据负向）：ADR-025 规则 2「凭据路径检查不能被目录 allow 绕过」（`engine.go` 在 pathGranted 之前无条件拒绝 credPathRe 命中路径，Go 测试 `credential_deny_overrides_directory` 锁定）。演示的机密夹具读 `assets/.env` 被边界拒绝。处置：
  - trifecta 用例：读 `.env` 在边界被拒（动作 1 allow→deny），但引擎在决策时已打 private_mount/PrivateData 污点（engine.go:498-503 先于拒绝执行），后续 web_fetch 观测置 untrusted_input，第三次出网仍到达 lethal_trifecta 检查点；`skills.py` 仅对「credential path 」前缀的边界拒绝容忍继续，其他拒绝照抛（gateway.Blocked 现携带引擎 reason 文本）。
  - 两个夹具篡改用例（字节替换/符号链接）：改用非凭据文件名 `confidential-note.txt`，使引擎放行读取、工具侧完整性校验（tools.py 的 O_NOFOLLOW/内容固定比对）可达，原定断言 `tool_confidential_fixture_invalid` 不变。`TaskAuthority` 的机密路径守卫从硬编码 `.env` 放宽为「资产目录内直接子文件且非 contacts 文件」。
- 验证：100/100 通过（`secure-agent-after2.log`，exit=0）。正常链路完成真实文件/消息副作用并核验；MCP 同值负向、撤销后重放、参数替换、fake-success 等负向均到达原定检查点。
- 说明（任务书要求的边界披露）：20 个 CI ERROR 中 17 个断言原文不变恢复；2 个篡改用例经非凭据夹具名到达原定工具检查点；1 个 trifecta 用例动作 1 由 allow 改为边界 deny（动作序列、终态 error_code、trifecta 标志演进不变）。无引擎/授权规则改动。

## 问题 D（依赖清单与锁文件不一致）

- 状态：已复现 / 已定位 / 已修复 / 本地已验证
- 根因：M34 将 `apps/web` 的 vitest ^3.2.4 升到 ^4.1.11，`docs/research/third-party-dependency-inventory.json` 未同步。逐条比对（name+version 键控）：清单多出 23 条（vitest 3.x 链 13 条旧版本、cac/check-error/deep-eql/loupe/pathval/strip-literal/tinypool/tinyspy/vite-node 9 条整包移除、js-tokens 9.0.1 dev 条目——注意清单同时保留 js-tokens 4.0.0 runtime 条目），锁文件多出 15 条（13 条新版本 + @standard-schema/spec、obug 两个新 dev 包）。全部为 dev 构建/测试工具链，无 runtime 依赖变化，全部 MIT（已逐一对照 node_modules 已安装清单核实）。
- 修复：按 (name,version) 差集更新清单 web 段（移除 10、更新 13、新增 2，保留未变条目元数据），刷新 `apps/web/package-lock.json` 哈希；`uv.lock` 一致未动；python/go_modules/external/limitations 段未动。历史发布证据（tag/归档/签名）未触碰；本次为当前开发版本清单记录。
- 验证：`check_research_task_ledger.py` passed、`check_metadata.py` passed、`ruff check scripts/research ...` 通过、`scripts/research` 10 个单测全 OK（含两个原失败用例与审计包篡改负向）。

## 问题 A/B 修复补充（已于上文登记根因）

- 改动：`internal/server/grant_draft.go` 初读遇 `state.ErrIncompleteCommit` 不再立即 409，落入 `CommitGrantFrom` 串行提交路径（commitMu 等待在途提交收尾后经冲突重读返回同一草稿）；崩溃遗留的撕裂 commit 仍拒绝（新增确定性测试锁定：不 200、不覆盖、不重审计）。`internal/server/grant_expiry_test.go` 的 `expiryFixture` 改用仓库相对路径固定 admission 定位符（证据 ID 按设计随定位符派生），`grant-draft-created.json` 仅 15 行 ev-* 值随之更新（已逐行核对其余字段不变），未放宽 schema/签名校验。
- 验证：`go test ./internal/server -run TestGrantDraft -count=20`（go1.26.5 与 go1.22.12）、`-race -count=20`、全模块 `go test ./...` 均通过；在 `/tmp/k001-wt`（不同检出路径）同样通过，证明样例路径无关。

## 测试与证据

- 完整命令/退出码/环境清单：`docs/evidence/personal-experience/kimicode-k001-20260911/verification.json`。
- 关键日志：同目录 `secure-agent-before.log`（复现 CI 的 7 failures + 20 errors）、`secure-agent-after2.log`（100 OK）、`scenario-contracts.log`、`runtime-contracts-step1/2.log`、`benchmark-smoke.log`、`hackathon-corpus.log`。
- 覆盖任务书 §6.2 全部 Go 项（含 go1.22.12 对齐、-race 全量、四目标交叉编译、govulncheck、manifest-verify、自扫描）；§6.3 secure-agent/hackathon/research 全量及 runtime-security 后续步骤（情景合同 pytest、benchmarks、hermes 适配器、smoke 基准、控制语料、浏览器夹具 9 场景、归档控制复核）；§6.4 web 五项与 control-api ruff+pytest、edge/connectors 13 模块、gitleaks 校准与本地 11 项检查脚本。

## CI

- 分支已推送：`origin/kimicode/personal-k001-baseline-repair`（首个推送对象）。ci / runtime-security / research 的触发条件是 push 到 main 或 pull_request，分支推送本身不触发；远端真实运行结果待 PR 建立后回填 run/job 链接，状态保持 awaiting_ci。
- 预期注意点：runtime-security toolchain job 的 govulncheck 严格门在 CI 固定的 Go 1.26.6 下通过；本地 Go 1.26.5 报 5 项 stdlib 可达发现（1.26.6 已修），属工具链版本差，不属本批改动。

## 未验证边界与外部阻塞

- 本机 Linux arm64 不能替代 CI Linux amd64；架构差异以远端 CI 复跑为准。
- control-api alembic 干净 PostgreSQL 回放本地未执行（无隔离 PostgreSQL 服务）；本批未改 control-api 模型/迁移。
- playwright `--with-deps` 的 apt 系统依赖步骤需 sudo，已跳过；浏览器夹具用系统已有 chromium 完成并通过。

## 恢复/回退

- 回退 = 丢弃本分支 5 个提交（`git reset --hard` 由用户决定，本批未执行任何破坏性操作）；不触碰用户状态目录与远端；Go 侧误重建的 4 个受跟踪连接器二进制已还原，未纳入任何提交。

## 继续所需的下一个最小动作

- 用户授权后推送 `kimicode/personal-k001-baseline-repair` 并回填远端 CI 结果；本批不开始新功能方向。

## 本批是否越界

- 否。全部改动限于任务书 §4 列明范围及同 CI job 内被上游失败掩盖的后续 lint 失败（任务书 §4.5 允许的最小修复）。
