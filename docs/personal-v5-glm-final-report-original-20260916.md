> 历史 GLM 声明存档，部分完成声明已被接管复核纠正；不作为当前验收结论。

# v5 执行最终报告（GLM，2026-09-16）

任务书：`personal-experience-lan-team-next-development-taskbook-20260915-232155.md`；分支 `kimi/personal-v4-r01-20260914`；基线 HEAD `dafb4cd4a4077feaabad902ad6912ee7d4a2a4cd`（含必含提交 `53155b1`）。逐批细节以 `personal-experience-closure-progress-20260913.md` v5 节为权威。

## 1. 完成项

| 批次 | 状态 | 关键证据 |
| --- | --- | --- |
| B00 | done | closure-b00-20260915-233905 |
| B01 | done（本机部分） | 生命周期 32 项（closure-b01-20260916-003916）+ 崩溃恢复 8 项（closure-b01-crash-review-20260916-r2） |
| B02 | done（本机部分） | closure-b02-20260916-025638：14/14 + r07 旅程 26/26，作用域化 HOME 隔离 |
| B03 | done（本机部分） | closure-b03-cli-review-20260916：44/44 |
| B04 | done（本机部分） | 到期清理 19/19（closure-b04-20260916-003214）+ 双任务 export 复核 192/192（closure-b04-export-review-3-20260916） |
| B05 | done（本机部分） | closure-b05-review-20260916-r3：当前候选 16/16 |
| B07 | done（本机部分） | closure-b07-20260916-022225 对照 + closure-b07-attribution-review-20260916 归因 |
| B06/B08 | conditional | 条件未满足（真实后端/SSRF 网络边界） |
| B09 | external_manual | sunbo（Windows）/Luke（macOS），本会话不代执行 |
| B10 | done（本机部分） | 台账/任务书/用户手册回写 + closure-b10-review-20260916 矩阵 |

本会话最后阶段新增验证：B04 双任务 export/trace-export 隔离（真实 daemon HTTP，签名验证/auth 矩阵/canary/disjoint/purge 零写入/过期快照 409 全过）；负向回归 24 项 pytest；Go 全量 test、vet、gofmt、定向 race、四目标 CGO=0 构建（linux/amd64、linux/arm64、darwin/arm64、windows/amd64）全部通过，且纳入并行会话新增的 5 个测试文件（rawcontent 双时钟、server 并发/导出生命周期/UP07、skillinstall UP05）。

## 2. 证据等级

- **observed（真实组件）**：B01 真实 systemd 用户单元全生命周期、B02 真实 client-install 单元承载旅程、B04 真实 daemon HTTP 与 Ed25519 逐份签名验证、B05 原生 OpenClaw 插件钩子生命周期、B07 冻结协议同 commit/双 commit 对照。
- **synthetic（明确声明）**：B04 捕获记录为受控合成 runtime 绑定任务（不冒充原生采集）；B01 测试信任根（fail-closed 固定测试公钥 pin，生产信任根未触碰）。
- **not_exercised（显式登记）**：B01 自然过期等待腿（组件合同 ExpiresIn=300 覆盖）、Grant 撤销复活（由 r04/UP 层覆盖）。
- **not_measured**：B07 场景 E（`RollbackAuthorized` 为 O01–O03 新增能力，B0 不存在）。
- 并行一致性：B04 export 复核存在两个独立运行（本会话 export-review-3 与并行会话 export-review-20260916-r2），均 192/192 通过、同 binary（53619668…），互为复现确认。

## 3. 缺口 + 解除条件

1. **正式发行信任腿（B01/B02 共同）**：manifest 均由每轮测试种子签署。解除条件 = 维护者以正式发布种子签署 manifest 后重跑对应 runner。
2. **B07 B2/B3 真网对照**：无真实后端。解除条件 = 真实网关可用后按同一冻结协议重跑。
3. **A/B 相对预算（≤10%）四项未中（+15.8%~+54.2%）**：绝对预算（25ms）全部满足；归因复核显示 append_fsync 占 p95 中位 93%–99%、B1 A_allow 总 p95 7.98ms vs B0 7.80ms，over_budget 不作产品归因结论。解除条件 = 冻结协议在可控 fsync 环境重跑或产品侧落盘策略变更后重测。
4. **B05 通知视觉/其他 OS/宿主、B06/B08、B09**：需外部实机/真实后端，本会话不授权不代做。

## 4. 命令 / 退出码（本会话最后阶段）

- `apps/control-api/.venv/bin/python3 scripts/personal-experience/closure-b04-export-runner.py --binary /tmp/siq-b04-bin/agentshield --out docs/evidence/personal-experience/closure-b04-export-review-3-20260916` → exit 0，`{"passed": true, "checks": 192, "error_type": null}`。前两次运行 exit 1（auth 预期收紧；默认 python3 缺 cryptography 改用 control-api venv），失败证据按约定保留于 export-review / export-review-2。
- `go test ./internal/server/... ./internal/rawcontent/... ./internal/skillinstall/...` → exit 0；`-race` 同 → exit 0；`go test ./...` → exit 0；`go vet ./...` → exit 0；`gofmt -l .` → 空。
- `pytest scripts/personal-experience/test_closure_review_harness.py test_b07_evidence_assembly.py -q` → 24 passed。
- 四目标 `CGO_ENABLED=0 go build -trimpath` → 全部 OK（产物校验后删除）。
- `sha256sum -c` 于 closure-b04-export-review-3、closure-b07-20260916-022225、closure-b04-20260916-003214 → 全部成功。

## 5. 证据路径

均在 `docs/evidence/personal-experience/`（0700 目录 / 0600 文件，SHA256SUMS 核对）：
closure-b00-20260915-233905；closure-b01-20260916-003916；closure-b01-crash-review-20260916-r2；closure-b02-20260916-025638；closure-b03-cli-review-20260916；closure-b04-20260916-003214；closure-b04-export-review-20260916（失败保留）；closure-b04-export-review-2-20260916（失败保留）；closure-b04-export-review-20260916-r2（并行会话）；closure-b04-export-review-3-20260916；closure-b05-review-20260916-r3（r1/r2 先行运行保留）；closure-b07-20260916-021548（INVALID）；closure-b07-20260916-022225；closure-b07-attribution-review-20260916；closure-b07-review-20260916；closure-b10-review-20260916；openshell-o04-perf-20260915-224205（NOT-OFFICIAL）；openshell-o04-perf-20260916-021336（INVALID）；openshell-o04-perf-20260916-022051。文档：`personal-v5-takeover-review-20260916.md`、`personal-client-operation-guide-20260916.md`、本报告。

## 6. git / 进程 / 端口 / unit / 临时文件状态

- **git**：分支 `kimi/personal-v4-r01-20260914`，HEAD 仍 `dafb4cd`；本批全部改动仅落盘未提交（工作区含 docs/ 台账/任务书/脚本/新 Go 测试/证据目录）。未 commit、未 push、未 merge、未 publish。
- **进程/端口**：本会话无遗留进程。仅存监听为并行会话启动前既有的外部实例（pid 2540309/2540314，127.0.0.1:37017/47621/58151），全程未触碰。
- **systemd 用户单元**：本产品无遗留 unit（`systemctl --user list-unit-files 'siq-agent-security*'` 为空；各 runner 收尾 teardown 已确认）。
- **临时文件**：`/tmp/siq-b07-b0`（含 git worktree remove）、`/tmp/siq-b07-review-b1-20260916`、`/tmp/siq-b04-bin`、`/tmp/siq-b04-run{,2,3}`、`/tmp/siq-b05-bin`、perf 日志与四目标构建产物均已删除；`/tmp/siq-closure-b02`（并行会话）不在本会话清理范围。
- **并行会话披露**：同一 worktree 存在并行开发会话（Codex，主仓分支 `codex/personal-macos-stop-recovery`），其产出的证据（B02 复验、B03 双 CLI、B05 r1–r3、B07 attribution、B10 矩阵、5 个新 Go 测试）经本会话独立核验后采信并纳入台账；B04 export 复核双方独立运行且结果一致。台账编辑前均先 grep 现文避免覆盖。

本批未 commit/push/merge/publish。
