# 联合开发计划实施台账

目标：[DEV01—DEV18 开发计划](development-plan-20260906-022735.md)。用户于 2026-09-06 授权将计划设为持续目标并直接实施。开始 commit：`0723f88cf4a242be6bf3f679996f5795ef75028e`；原有未跟踪的计划/仲裁文件保留。

本台账区分“代码已落盘”“聚焦验证通过”“整个任务验收完成”。真实设备信任、生产密钥撤销、IdP、PostgreSQL、OS/沙箱与独立扫描的缺证不记为通过。没有自行提交、推送、部署、清理 Git 历史或操作真实用户授权。

| 任务 | 状态 | 当前切片与剩余验收 |
| --- | --- | --- |
| DEV01 | 进行中 | **A 聚焦验证通过（仓库侧）：** [trust-inventory-20260906.md](evidence/trust-inventory-20260906.md)。在役 Edge 比对与生产撤销未做 |
| DEV02 | 进行中 | **A+B 聚焦验证通过：** 分权/配对；高影响 approve 绑定 challenge（digest/scope/revision/nonce/单次）。受管 Linux OS 隔离、S2b 真机未测 |
| DEV03 | 进行中 | **A+B+C+D 聚焦验证通过：** Link 排他；单写者；grant CAS；hold；链尾半行；audit Sync；`CommitGrant`（policy/audit 失败不伪成功 + incomplete 标记）。崩溃级跨文件原子性未宣称 |
| DEV04 | 进行中 | **A+B+C+D+E 聚焦验证通过：** 发行根；共用验签；Python content_hash；staging；显式下载（`ALLOW_DOWNLOAD=1`）后验签+pin+staging。GitHub 真实发布物端到端未测；同 UID 执行前改写未宣称 |
| DEV05 | 进行中 | **A+B+C 聚焦验证通过：** 特殊文件/有界读；枚举预算；ADR-013 打开后 Stat+SameFile，Unix O_NOFOLLOW+O_NONBLOCK。不宣称同 UID 零窗口；Windows 特殊文件矩阵未做；非整任务验收 |
| DEV06 | 进行中 | **A—G 聚焦验证通过：** 上项外加 Unicode 行分隔对等 + ASCII 词边界负向。RE2 完整 Unicode `\b`、整任务验收未宣称 |
| DEV07 | 进行中 | **A+B+C+D 聚焦验证通过：** 首备/外科卸载；pending JSONL；serve/decide 补签为链上回执。三端真实 GUI 旅程未做 |
| DEV08 | 进行中 | **A+B+C 聚焦验证通过：** 上两项外加生产强制 audience；mock JWKS 错 aud/iss/alg/过期与 TTL 轮换窗口。真实 IdP 联调未测 |
| DEV09 | 进行中 | **A—I 聚焦验证通过：** 上项外加 rulepack `.sig` 跨语言向量。整任务验收 / 防回滚策略变更未宣称 |
| DEV10 | 进行中 | **A—I 聚焦验证通过：** 上项外加 mcp/piagent/dify/workbuddy 最终路径 O_NOFOLLOW。强杀端到端、同 UID TOCTOU、整任务未宣称 |
| DEV11 | 进行中 | **A—F 聚焦验证通过：** 含限速与历史 null 盘点工具。真实 PG 并发/生产库盘点与整任务验收未宣称 |
| DEV12 | 进行中 | **A+B 聚焦验证通过：** 复核正交；Outbox claim/CAS/退避/死信。真实 PG SKIP LOCKED 与人工重放未宣称 |
| DEV13 | 进行中 | **A—E 聚焦验证通过：** 上项外加 agents/candidates/findings/permissions 截断头+加载更多。浏览器整旅程与整任务验收未宣称 |
| DEV14 | 进行中 | **A+B 聚焦验证通过：** 严格校验+降级；run 可追溯元数据（model_ref/temperature/seed=null/input_summary/tokens/latency/error_ref）。真实模型预算评估未宣称 |
| DEV15 | 进行中 | **A—E 聚焦验证通过：** 上项外加受管独立 checkpoint（`checkpoints/`，禁 HEAD 锚点）。整任务验收 / 跨挂载独立信任域实机未宣称 |
| DEV16 | 进行中 | **A+B+C+D+E 聚焦验证通过：** 上项外加空闲无污点/无 trifecta 过期。1万/10万归档与跨进程持久过期未宣称 |
| DEV17 | 进行中 | **A+B+C+D 聚焦验证通过：** 上三项外加 Pages SHA 钉扎 + Dockerfile 基础镜像 digest。整任务验收 / 真实网关下载实测未宣称 |
| DEV18 | 进行中 | **A+B+C 聚焦验证通过：** profile + 本地威胁 + OS×平台证据矩阵/生产 runbook 模板。真实 PG/OS/L3_enforce/独立复核未做 |

## 切片证据

### I0（2026-09-06，前序会话）

命令（`apps/agentshield`）：`gofmt -l . && go vet ./... && go test -count=1 ./...` 通过。本地 UI：`bash scripts/build_ui.sh` 后嵌入 `internal/ui/embedded/`。

- DEV03-A：`PutVersioned` 同目录 `CreateTemp` + `Sync` + `os.Link`（ADR-012）。`writeNew` 仅在字节相同时间幂等，否则 `ErrConflict`。准入 evidence ID 含 `source.locator`，避免跨 Skill 文件名碰撞把第二次准入打成失败。合同样例已按 `AGENTSHIELD_UPDATE_SAMPLES=1` 重生成。
- DEV04-A：`internal/skillmanifest/trust_test.go` — 自签/改 signed_by 不能当官方发布。
- DEV05-A：`internal/admission/reading_test.go` — FIFO、symlink 逃逸、无扩展名、越界 HashDir。
- DEV02-A：`internal/server/authz_test.go` — ui-config 无 token；配对单次；决策 token 调管理 403；坏 Host/Origin/cross-site 写拒绝。嵌入 UI 含「建立管理会话」。
- DEV01-A：`python3 scripts/trust-fingerprint.py`。历史任务签名公钥 SHA-256 `ffccdef01aedc404f110421151baec4aceb34409d9e63ddb1b803093d965eb55`。在役状态标未核实。
- DEV18-A：desktop-same-uid 与 L3 读回≠强制已写入规格、README/AGENTSHIELD 与能力 profile。

### I1 / DEV03-B（2026-09-06，本会话）

命令（`apps/agentshield`）：`go vet ./...` + `go test -count=1 ./...` 通过。本地 UI：`bash scripts/build_ui.sh` 后嵌入（`expected_revision` CAS）。

- 单写者：`state.AcquireWriter`（O_EXCL `serve.lock`；死 pid 则 rename 为 `serve.lock.stale.*`；禁止无条件删锁；Release 校验 owner）。`serve` 与离线 `grant` 共用；存活 serve 占用时 CLI 拒绝直写。
- CAS：`LatestSeq` / `PutVersionedCAS` / `PutGrantCAS`；管理 HTTP grant 变迁强制 `expected_revision`，冲突 409；`GET /v1/grants/{id}` 与列表 `state_revisions` 暴露序号。
- 负向：`cas_test.go`（双 CAS 恰一成功）、`server/cas_test.go`（缺 revision / 陈旧 409）、写者接管与拒释外锁。
- UI：本地签发页与资产补丁提交带 `expected_revision`。
- 规格 §2.3 与 ADR-012 已回写本切片边界；多文档审计事务与 hold CAS 仍属 DEV03-C。

### I1 / DEV05-B（2026-09-06，本会话）

- admission：`Limits.MaxDirs`；`walkContext`/`HashDirContext` 在枚举回调检查 `ctx.Err()`，取消返回 `ErrCanceled`；目录预算在 Walk 中触发 over_limit，不先攒全树。
- directory connector：候选收集阶段达到 `MaxFiles`/超时即停，`Truncated=true`，不再先 Walk 全量再截断。
- 负向：`budget_cancel_test.go`（MaxDirs+1、预取消）；全量 `go test ./...` 通过。

### I1 / DEV03-C（2026-09-06，本会话）

- hold：`ResolveHold` 同决议幂等、反决议 `ErrHoldConflict`（HTTP 409）、超时 `ErrHoldExpired`；决议回执固定 `heldID-res`。
- chain：`Append` 后 HEAD 经暂存+rename；`Read` 跳过最新文件末尾不完整行。
- audit：`AppendAudit` Sync。hold HTTP `DisallowUnknownFields`。
- 负向：`hold_test.go`；`go test ./...` 通过。多文档（grant+policy+audit）原子提交仍未做。

### I1 / DEV09-A（2026-09-06，本会话）

命令：`edge/agent` 下 `go test -count=1 ./...`；`apps/control-api` 下 `uv run pytest app/tests/test_signing.py -q` 通过。

- 根因：Edge `VerifyTaskSignature` 用 `encoding/json.Marshal`（HTML 转义 `<`→`\u003c`），与控制面任务签名 `ensure_ascii=True` 且保留字面 `<` 不一致。
- 修复：Edge 引入与 `apps/agentshield/internal/canon` 对齐的 `edge/agent/canon`；payload 经 `canon.Decode`（保留 `100`/`100.0`）后 `canon.Marshal` 验签。
- 独立生产者夹具：`packages/contracts/fixtures/task_signature_vectors_v1.json`（纯 CPython `json.dumps` + Ed25519 seed=`bytes(range(32))`，含 baseline、中文+HTML+`100.0`、嵌套 Unicode、int/float）。Go/Python 均为消费者。
- 合同澄清：任务签名 ≠ evidence（后者 `ensure_ascii=False`）。
- 未做：admission/grant/receipt/policy/rulepack/manifest 全清单；签名 schema 版本双读；Evidence 路径统一。

### I1 / DEV08-A（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_jwks_cache.py app/tests/test_config_security.py app/tests/test_identity_jwt.py -q` 通过。

- JWKS：`app/jwks.py` 用 `time.monotonic` TTL（默认 60s，`SIQ_AS_JWKS_TTL_SECONDS` ∈ [5,300]）；并发单飞；unknown_kid 强制刷新有最小间隔；TTL 过期且拉取失败 fail-closed（不无限信任陈旧集）。
- 生产：`SIQ_AS_OIDC_ISSUER` 必配；资源身份拒绝 `type=refresh`（`token_type_rejected`）；仅接受 RS256。
- 负向：TTL 越界、issuer 缺失、refresh 映射、并发单飞、unknown_kid 限频。
- 未做：真实 IdP 联调；有限 stale 容忍策略；service token 用途细分合同。

### I1 / DEV08-B（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_identity_jwt.py app/tests/test_edge_secret.py app/tests/test_enrollment_flow.py app/tests/test_config_security.py app/tests/test_jwks_cache.py -q` 通过。

- 资源 JWT：`RESOURCE_TOKEN_TYPES={access,user,service}`；`refresh`/`id_token`/未知 → `token_type_rejected`；`service`→`identity_type=service`（不因 type 放宽权限）。
- Edge secret：`mint_edge_device_secret`（`edge-`+urlsafe32）；验签 `EDGE_SECRET_MIN_LEN` 下界 + `hmac.compare_digest`；注册改用 mint。
- 负向：短 secret / 空 secret 不可接受；mint 碰撞抽样；哈希失配。
- 未做：真实 IdP 联调；有限 stale 容忍；独立 refresh 通道实现（仅资源侧拒绝）。

### I1 / DEV04-B（2026-09-06，本会话）

命令：`go test -count=1 ./internal/skillmanifest/` 通过；已用本地忽略的 release seed 重签 `skill-manifest.json`（未打印种子）。

- 共享路径：`skills/.../scripts/resolve_verified_bin.sh`（定位二进制 + `verify_manifest.py` + 内置发布公钥）。
- `bootstrap.sh` / `adapter.sh` 均经该脚本后才使用二进制；`adapter.ps1` 同样先验签。
- `EmbedReleasePubkey` / `ReadEmbeddedPubkey` 以 resolve 脚本为权威嵌入点。
- 负向：`REQUIRE_PINNED=1` 时错哈希二进制被拒（`TestAdapterAndBootstrapShareVerifiedResolve`）。
- 未做：私有 staging 复制后再验；真实发布向量端到端下载（bootstrap 仍不下载）。

### I1 / DEV02-B（2026-09-06，本会话）

命令：`apps/agentshield` 下 `go test -count=1 ./...` 通过；`bash scripts/build_ui.sh` 嵌入本地签发页挑战流。

- 高影响批准：`POST /v1/grants/{id}/challenge` 签发单次挑战（grant digest + scope digest + expected_revision + nonce，TTL 5m）；`approve` 强制 `challenge_id`+`nonce`，先验绑定再 CAS 消费挑战。
- 负向：缺挑战 400；重放消费失败；patch-desired 后旧挑战无效；陈旧 revision 409。CLI：`grant challenge` / `grant approve --challenge-id --nonce`。
- 诚实边界：响应与 CLI 注明 desktop-same-uid 下挑战不是 OS 隔离；同 UID Agent 仍可自签自批。
- 未做：受管 Linux 管理私钥隔离；S2b 真实浏览器攻击验证。

### I1 / DEV04-C（2026-09-06，本会话）

命令：`apps/agentshield` 下 `go test -count=1 ./internal/skillmanifest/` 通过（含 Python 对等与 mismatch 负向）。

- `verify_manifest.py`：`hash_skill_dir` 对齐 `admission.HashDir`（跳过 skill-manifest.json/.git/skill.oms.sig；DefaultLimits；symlink 逃逸/非普通文件 fail-closed）。
- 安装路径强制 `--skill-dir`：`resolve_verified_bin.sh`、bootstrap.ps1、adapter.ps1；仅签名自检可不带该参数。
- 夹具：`TestPythonHashSkillDirParity`、`TestPythonVerifierRejectsContentHashMismatch`；改 Skill 后已重签 `skill-manifest.json`（未打印种子）。
- 未做：私有 staging 复制后再验；真实发布下载链。

### I1 / DEV03-D（2026-09-06，本会话）

命令：`apps/agentshield` 下 `go test -count=1 ./...` 通过。

- `state.CommitGrant`：PutGrantCAS → desired_policy（可选）→ audit（可选）；后两步失败返回 `IncompleteCommitError`，写 `commits/<id>.<seq>.incomplete.json`，不得当成功。
- HTTP/CLI grant create 与 grant 变迁改走 CommitGrant；incomplete → HTTP 500 `incomplete_commit`（含 phase/state_revision）。
- `PutDesiredPolicy` 改为 Sync 落盘（`writeDurable`）。
- 负向：`commit_test.go` — policy 非法 id、audit.jsonl 为目录、CAS 冲突不写 incomplete。
- 诚实边界：append-only grant 不回滚；不宣称掉电后多文件原子提交。

### I1 / DEV09-B（2026-09-06，本会话）

命令：`edge/agent` 下 `go test -count=1 ./...`；`uv run pytest app/tests/test_signing.py -q` 通过。

- 根因：Evidence 曾用 `encoding/json` + `SetEscapeHTML(false)`，float/`[]int` 与 CPython `ensure_ascii=False` 不完全对齐。
- 修复：Edge `canon.MarshalUTF8`；`CanonicalJSON` 走 UTF-8 canon（原生 map 保留 `100.0`）。
- 独立生产者夹具：`packages/contracts/fixtures/evidence_signature_vectors_v1.json`；清单 `signing-inventory-v1.md`。
- 未做：admission/grant/receipt 全量跨语言向量；schema 版本运行时双读路由。

### I1 / DEV07-C（2026-09-06，本会话）

命令：`go test ./internal/pending/ ./internal/adapters/ ./internal/adapterinstall/`；Hermes `pytest tests/test_adapter.py` 通过。

- `internal/pending`：`<state>/pending/decisions.jsonl`，schema `pending_decision/v1`，`signed=false`。
- CodeBuddy `failClosed`、Hermes `_fail_closed`、OpenClaw `failClosed` 在不可达/畸形时追加 pending；block→outcome deny，warn/audit_only→allow。
- 嵌入 assets 已与 runtime 同步。
- 未做：serve 读取 pending 并补签 `observed`；OpenClaw 独立 node 单测（逻辑与 Hermes/Go 同合同）；三端真实 GUI 旅程。

### I1 / DEV07-D（2026-09-06，本会话）

命令：`go test -count=1 ./internal/pending/ ./internal/receipt/ ./internal/server/ ./internal/adapters/` 通过。

- `pending.Promote`：按 `promoted.lines` 游标提升未处理 JSONL；逐行成功后 Sync 游标；坏行受控停止。
- `receipt.AppendPendingObserved`：outcome deny/allow → 签名回执；`matched_rule_ids=pending.fail_closed`；链 Verify 通过。
- 入口：`serve` 启动强制提升；`/v1/decide` best-effort 追赶（serve 已在跑时适配器新写 pending）。
- 规格 §3.8.4 已回写 DEV07-D。
- 未做：崩溃窗口去重（cursor 在 append 之后，最坏可能重复一条）；三端真实 GUI 旅程；OpenClaw 独立 node 单测。

### I1 / DEV07-B（2026-09-06，本会话）

命令：`go test -count=1 ./internal/adapterinstall/` 通过。

- OpenClaw：活文件剥离 `security.installPolicy`，保留 gateway/用户后加字段；删除产品插件与专用配置。
- CodeBuddy：剥离本产品 hook 条目，保留 theme 等用户字段。
- 冲突：活文件坏 JSON → `uninstall_conflict` + `RecoveryPlan`（路径/首备/建议），不静默整文件回滚。
- Hermes：移除插件根；有 wrapper 首备则恢复。
- 未做：运行中 block/warn fail-closed 适配器矩阵；三端真实「安装→准入→批准→卸载」旅程。

### I1 / DEV07-A（2026-09-06，本会话）

命令：`go test -count=1 ./internal/adapterinstall/` 通过。

- 首备：`path.siq-agent-security.orig` 以 O_EXCL 写入，重装不覆盖；卸载从首备恢复（install→install→uninstall）。
- 坏 JSON / symlink 配置拒绝且不改写；`enforcement_mode` 仅 block|warn|audit_only。
- 写入：同目录 CreateTemp + Sync + Rename。
- 未做：安装后用户新增字段的外科卸载（仍可能整文件回到首备）；OpenClaw TS/三端真实旅程；运行中 block fail-closed 适配器矩阵（属后续切片）。

### I1 / DEV09-C（2026-09-06，本会话）

命令：`go test -count=1 ./internal/signing/`；`uv run pytest app/tests/test_signing.py -q` 通过。

- 独立生产者：`packages/contracts/scripts/gen_local_doc_signature_vectors_v1.py` → `fixtures/local_doc_signature_vectors_v1.json`（admission/grant 最小体 + 中文/HTML/`100.0`/null）。
- 路由：`NormalizeSigningSchema` / `VerifyWithSchema`；`local_canonical/v1`+`task_envelope/v1` 走 ASCII；`evidence_utf8/v1` 与未知 `local_canonical/v2` 受控拒绝。
- 跨合同：夹具 `cross_contract_note` 证明同一 Unicode 文档 ASCII≠UTF-8 canon。
- 未做：文档内嵌 `signing_schema` 字段（改签名域）；receipt/policy 全矩阵；写者切换到新版本。

### I1 / DEV09-D（2026-09-06，本会话）

命令：`python3 packages/contracts/scripts/gen_receipt_signature_vectors_v1.py`；`go test -count=1 ./internal/receipt/ ./internal/signing/` 通过。

- 合同：`content_hash = sha256(local_canon(body without hash/sig))`；`sig = Ed25519(hashHex ASCII)`（非 SignCanonical(body)）。
- 导出：`receipt.ContentHash` / `VerifyHashSignature`；schema id `receipt_hash_chain/v1` 在 `VerifyWithSchema`/`NormalizeSigningSchema` 受控拒绝。
- 独立生产者夹具：`fixtures/receipt_signature_vectors_v1.json`（创世中文/HTML、链式第二条）；`signing-inventory-v1.md` 已拆分 receipt 行。
- 负向：对 body 的签名不得通过 hash-chain 验签；链式 `prev_hash` 必须等于上条 hash。
- 未做：正文内嵌 `signing_schema`；policy 向量；整任务 DEV09 验收。

### I1 / DEV05-C（2026-09-06，本会话）

命令：`go test -count=1 ./internal/admission/`；`connectors/directory` `go test -count=1 .` 通过。

- ADR-013：扫描打开保证与残余 TOCTOU；明确不宣称同 UID 零窗口 / Windows 特殊文件完整矩阵。
- admission + directory：`openRegular`（Unix：`O_NOFOLLOW|O_NONBLOCK`；其他：`os.Open`）+ fd `Stat` 须普通文件 + `SameFile`。
- 负向：symlink 直接打开拒绝；FIFO 3s 内不阻塞；持有旧 inode 后路径替换 → `changed while opening`；symlink 替换路径拒绝。
- 未做：managed-linux / 沙箱；Windows 特殊文件实机矩阵；整任务 DEV05 验收。

### I1 / DEV04-D（2026-09-06，本会话）

命令：`go test -count=1 ./internal/skillmanifest/` 通过；已重签 `skill-manifest.json`（未打印种子）。

- Go：`StageVerifiedBinary` — 0700 私有目录、排他复制、Sync、源摘要==暂存摘要（可选 pin）；拒绝非普通/不可执行文件。
- Python：`verify_manifest.py --stage-to`；`resolve_verified_bin.sh` / bootstrap.ps1 / adapter.ps1 验签后 staging，stdout 返回 staged 路径供执行。
- 负向：错 pin 拒绝；resolve 在 REQUIRE_PINNED 下拒假二进制；`TestResolveStagesVerifiedBinary` 确认路径落在 stage 根下。
- 未做：真实发布下载链；验证到执行期间对抗同 UID 改写的 OS 隔离（desktop-same-uid 边界仍在）。

### I1 / DEV04-E（2026-09-06，本会话）

命令：`go test -count=1 ./internal/skillmanifest/` 通过；已重签 `skill-manifest.json`（未打印种子）。

- Go：`SelectArtifact` / `DownloadVerifiedArtifact` / `FetchAndStage` — 仅 HTTPS（或显式允许的 loopback HTTP）；`Content-Length`/字节 pin、sha256 pin、硬顶 256MiB；下载后 staging。
- Python：`verify_manifest.py --fetch-artifact`（须 `--stage-to`）；环境变量 `SIQ_AGENT_SECURITY_ALLOW_INSECURE_DOWNLOAD=1` 仅限 loopback 测。
- 入口：无本地二进制时默认拒绝下载；`SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD=1` 才走 signed-manifest URL（`resolve_verified_bin.sh` / `bootstrap.ps1`）。
- 负向：错 hash、超字节 pin、CL 不符、未允许的非 HTTPS；`TestPythonFetchArtifact` 与 Go httptest 覆盖。
- 未做：对 GitHub Release 真实 URL 的网络端到端；同 UID 执行前改写 OS 隔离。

### I1 / DEV06-G（2026-09-06，本会话）

命令：control-api 威胁三组 **97 passed**；oracle 44 vectors；`go test ./internal/threat/` 通过。

- Go `splitLines` 对齐 Python `str.splitlines` 分隔符（CR/LF/VT/FF/FS/GS/RS/NEL/LS/PS）；U+2028 切开后仍可伪管道接合。
- 语料：`mal-download-exec-pipe-unicode-ls`、`benign-download-exec-notcurl-boundary`；基线 **30/30**。
- 未做：RE2 vs Python 完整 Unicode 词边界矩阵；留出集评测；整任务 DEV06 验收。

### I1 / DEV06-F（2026-09-06，本会话）

命令（`apps/agentshield`）：`go test -count=1 ./internal/admission/` 通过（含 `CapabilityAdmission*`；顺带修 `card_test` 的 `EngineMeta`→`Engine` 编译断裂）。

- [`capability-admission-matrix-v1.md`](capability-admission-matrix-v1.md) + `dispositions_matrix_test.go`：rulepack 25 条全覆盖；scripts 无 egress 主表；cred+egress / authorized_keys / docs 散文 vs 代码正交负向。
- 未做：Unicode/属性变异语料；跨产品 profile 差分；整任务 DEV06 验收。

### I1 / DEV06-E（2026-09-06，本会话）

命令：control-api `pytest` 威胁三组 **95 passed**；`gen_threat_match_oracle_v1.py` → 42 vectors；agentshield `go test ./internal/threat/` **14 passed**。

- Go/Python `scanLines`：shell/powershell 在显式续行之外，若下一物理行（去前导空白）以 `|` 开头则接合，且**不嵌入换行**（兼容 `[^\n|]*\|` 类规则）。
- 语料：`mal-download-exec-pipe-pseudo`、`mal-download-exec-powershell-pseudo`；基线 **29/29**。
- 未做：能力事实→准入全矩阵；Unicode/属性变异语料；整任务 DEV06 验收。

### I1 / DEV06-D（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_threat_analysis.py app/tests/test_threat_match_oracle.py app/tests/test_detection_baseline.py -q`；`go test -count=1 ./internal/threat/` 通过；已重生 `match_oracle_v1.json`。

- Go/Python：`detected_type=powershell` 时接合行尾 `` ` `` 续行后再匹配；行号取续行块首物理行。
- shell 仍只用 `\`，不得把反引号当续行；语料 `mal-download-exec-powershell-continued`；基线 27/27。
- 未做：无反斜杠伪管道跨行；能力事实→准入全矩阵；整任务 DEV06 验收。

### I1 / DEV15-E（2026-09-06，本会话）

命令（`apps/agentshield`）：`go test -count=1 ./internal/receipt/ ./internal/server/ ./internal/state/` 通过。

- `CheckpointStore`：`<state>/checkpoints/<chain>.json`（`agentshield.checkpoint.v1` + `local_canonical/v1`）；拒绝 `receipts/` 下路径；`RejectColocatedHEAD`。
- Append 成功后自动 Publish；导出 CLI/HTTP `LoadOptional` 喂入 `VerifyDetailed`。
- 负向：截断 receipts 相对 checkpoint → `history_integrity=failed`；篡改 checkpoint 拒载。
- 诚实：同 UID 整 state 回滚不宣称；可用 `OpenCheckpointStoreAt` 指独立目录。
- 未做：独立挂载实机；整任务 DEV15 验收。

### I1 / DEV16-E（2026-09-06，本会话）

命令（`apps/agentshield`）：`go test -count=1 ./internal/receipt/ ./internal/state/` 通过。

- `SessionIdleTTL`：默认 30m；负值关闭；范围 [1s,24h]。仅无 taint 且无 trifecta 记忆可空闲过期（lazy + 分配前 sweep）。
- 污点/trifecta 永不过期腾位；容量满仍 `ErrSessionCapacity`（与 DEV16-A 一致）。
- `config.session_idle_ttl_seconds`（0 默认 / -1 关 / 1..86400）；serve 写入引擎。
- 负向：`session_idle_test.go`；统计 `idle_expired` / `idle_ttl_seconds`。
- 未做：跨进程持久化过期状态；1万/10万人工归档；整任务 DEV16 验收。

### I1 / DEV16-D（2026-09-06，本会话）

命令：`go test -count=1 ./internal/perfbaseline/`；`python3 scripts/check_perf_baseline_harness.py` 通过。

- `internal/perfbaseline` + `cmd/perfbaseline`：写入/ReadLimited/导出 Seal 观察；报告 `agentshield.perf_baseline.v1`；环境字段；p50/p95/p99；**`thresholds` 恒 null**；诚实 notes。
- 规模预设 smoke/medium(1万)/large(10万)；CI 仅 smoke；证据说明见 `docs/evidence/perf/README.md`。
- 未做：medium/large 人工硬件归档；空闲无污点过期；整任务 DEV16 验收。不把 smoke 记为 1万/10万通过。

### I1 / DEV15-D（2026-09-06，本会话）

命令（`apps/agentshield`）：`go test -count=1 ./internal/export/` 通过。

- `export.Seal`：脱敏投影嵌入 `signing_schema=local_canonical/v1` + 独立 `signature`；`derived_from`（`agentshield.export.derived/v1`，`attestation_scope=share_projection_only`，tip hash/seq）。
- `export.Verify`：验派生签；篡改失败；回执 `sig` 粘贴不得当导出签通过。
- CLI `export` 与 `GET /v1/export` 写者路径强制 Seal；规格 §3.8.1.3 与 signing-inventory 已回写。
- 未做：受管独立 checkpoint 持久化；跨语言导出向量；整任务 DEV15 验收。

### I1 / DEV18-C（2026-09-06，本会话）

命令：`python3 scripts/check_capability_honesty.py` 通过。

- [`agentshield-capability-matrix-v1.md`](agentshield-capability-matrix-v1.md)：OS×平台×(build/L0–L2/L3_readback/L3_enforce) 证据索引；linux 三平台回链 2026-09-05 归档；**L3_enforce 全表 unverified**；零行 supported。
- [`enterprise-production-runbook-v1.md`](enterprise-production-runbook-v1.md)：TLS/OIDC/Secret/PG/Edge/worker/轮换/事故模板；大量 `blocked`/`template`；明确不宣称 IdP/PG/L3_enforce/managed-linux/S2b/深扫通过。
- CI 增加诚实门禁；能力 profile 回链上述两文。
- 未做：真实 PG/OS/L3_enforce 归档；独立对抗复核；整任务 DEV18 验收。

### I1 / DEV08-C（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_oidc_jwt_verify.py app/tests/test_config_security.py -q` 通过。

- 生产必须显式 `SIQ_AS_JWT_AUDIENCE`（禁止静默默认）；dev 仍可默认。
- mock RS256 JWKS：合法 token 通过；错 aud/iss、过期、非 RS256 → 401；TTL 信任窗口内仍可验旧 kid，过期后旧 kid 消失拒绝；unknown_kid 刷新后新 kid 可用。
- 未做：真实 IdP 联调；有限 stale 容忍（仍 fail-closed）。

### I1 / DEV09-I（2026-09-06，本会话）

命令：`go test ./internal/rulepack/ -run RulepackSignature`；`uv run pytest app/tests/test_signing.py::test_rulepack_signature_vectors_v1_match_local_canonical -q` 通过。

- 独立生产者：`packages/contracts/fixtures/rulepack_signature_vectors_v1.json`（中文/HTML、键序无关、`100.0`；sidecar base64 `.sig`）。
- Go `canon.Marshal` + `VerifySignature`；Python `_canonical_bytes`；与 evidence UTF-8 字节必不同。
- 未做：防回滚严格递增策略；整任务 DEV09 验收。

### I1 / DEV09-H（2026-09-06，本会话）

命令：`cd edge/agent && go test -count=1 ./...`；`cd apps/control-api && uv run pytest app/tests/test_signing.py -q` 通过。

- Edge `SealEvidence` 默认嵌入 `signing_schema=evidence_utf8/v1`（参与签名字节）；剥离后原签失效。
- 控制面 `normalize_evidence_signing_schema` / `verify_evidence_signature`：缺省双读同合同；`local_canonical/v1` 等错 schema 拒绝。
- 合同：`evidence.schema.json` 允许可选 `signing_schema`；`EdgeEvidenceIn` 对齐；独立夹具 `evidence_embedded_schema_vectors_v1.json`。
- 未做：rulepack 跨语言签名向量；整任务 DEV09 验收。

### I1 / DEV18-B（2026-09-06，本会话）

命令：`python3 scripts/check_threat_model_local.py` 通过。

- `docs/threat-model.md` 增补「本地产品威胁」L1–L12：rebinding、同 UID 自批、Skill/供应链、单写者、读回≠强制、会话/投影/导出预算、安装卸载等；回链能力 profile 与 DEV 切片证据。
- 明确残余：S2b 真机、managed-linux、enforcement_verified、跨用户 ACL 等缺证不记通过。
- 未做：OS×平台×后端完整能力矩阵实测；企业生产 runbook；独立对抗复核；整任务 DEV18 验收。

### I1 / DEV17-D（2026-09-06，本会话）

命令：`python3 scripts/check_pages_action_pins.py` 与 `python3 scripts/check_dockerfile_digests.py` 通过。

- `pages.yml`：checkout / peaceiris 钉完整 SHA；`timeout-minutes: 15`；`contents: write` 保留（推 gh-pages 所需）。
- `apps/control-api/Dockerfile`、`apps/web/Dockerfile`：python/node/nginx/uv 均 `@sha256:…`（registry 索引 digest，记录于检查脚本）。
- 未做：真实网关 OpenShell 下载实测；整任务 DEV17 验收（SBOM/离线签名包等）。

### I1 / DEV17-C（2026-09-06，本会话）

命令：`python3 scripts/check_openshell_compat_workflow.py` 与 `python3 scripts/check_site_mermaid_vendor.py` 通过。

- `openshell-compat.yml`：`cli_bin_asset`/`cli_bin_sha256`/`live_sandbox` 经 `env:`；GitHub 发布域白名单；`sha256sum -c`；禁止 `run:` 直接插值 inputs；checkout/setup-uv 钉完整 SHA；`timeout-minutes: 30`。
- `site/architecture.html`：加载 `./vendor/mermaid-11.4.1.min.js`（npm `mermaid@11.4.1` 的 `mermaid.min.js`）；去掉 jsDelivr CDN import；sha256 sidecar + CI 检查。
- 未做（当时）：基础镜像 digest；Pages workflow 钉扎；真实网关 OpenShell 下载实测；整任务 DEV17 验收。

### I1 / DEV17-B（2026-09-06，本会话）

命令：`python3 scripts/check_web_nginx_headers.py` 与 `python3 scripts/check_ci_action_pins.py` 通过。

- `apps/web/nginx.conf` + `security-headers.inc`：nosniff、DENY frame、Referrer-Policy、Permissions-Policy、CSP（`frame-ancestors 'none'`）；**不**在 listen 80 上设 HSTS。
- `ci.yml`：checkout/setup-go/setup-node/setup-uv/gitleaks 钉完整 commit SHA；CI 增加上述两检查。
- 未做（当时）：基础镜像 digest；pages/openshell workflow 钉扎；Mermaid 自托管；OpenShell 下载哈希；整任务 DEV17 验收。

### I1 / DEV17-A（2026-09-06，本会话）

命令：`python3 scripts/check_control_api_dockerfile_lock.py` 通过；`cd apps/control-api && uv sync --locked --no-dev` 通过。

- `apps/control-api/Dockerfile`：多阶段 `uv sync --locked --no-dev`（不再 `pip install .`）；运行层仅复制 venv+app。
- CI：各 job `timeout-minutes`；Dockerfile 锁合同检查；npm audit 注册表不可用 → 失败（不装绿）；`govulncheck@v1.7.0` 必跑，工具崩溃失败，有发现仅 warning（不宣称 CVE 清零）。
- 未做：Actions 完整 SHA 钉扎；基础镜像 digest；nginx CSP/HSTS；Pages/OpenShell/Mermaid；整任务 DEV17 验收。

### I1 / DEV16-C（2026-09-06，本会话）

命令（`apps/agentshield`）：`go test ./internal/receipt/ ./internal/export/ ./internal/server/ -count=1` 通过。

- `receipt.ReadLimited`：按 MaxRecords/MaxBytes **流式扫盘**提前停止；`Truncated`/`DiskBudget` 区分记录帽与字节帽（非全量 Read 后再切片）。
- `export.Budget` + `incomplete`/`truncation`；`MarshalJSONBytesBudget` 超限 fail-closed。
- HTTP/CLI 导出走 ReadLimited + 预算；投影仍可含完整链供其他路径。
- 未做：1万/10万压测基线；会话空闲无污点过期；分段 NDJSON 流式响应体。

### I1 / DEV16-B（2026-09-06，本会话）

命令（`apps/agentshield`）：`go test ./internal/server/ -count=1` 通过（含 `TestProjectionCacheStableAcrossGets`、更新后的 corrupt→stale 合同）。

- GET `/v1/assets|permissions|findings|export` 读缓存投影；`ok` 时不每次 inventory+lifecycle。
- `Refresh`/ticker 写路径构建；响应含 `projection{revision,generated_at,health,age_ms,last_error}`。
- 重建失败且已有版本 → `health=stale` 可读旧投影；无先验 → `500/unavailable`（坏文件不成空集成功）。
- 变更（admit/grant/decide/observe）`invalidateProjection`，下次 GET 重建一次。
- 未做：游标分页；流式导出；1万/10万压测基线；会话空闲无污点过期。

### I1 / DEV16-A（2026-09-06，本会话）

命令（`apps/agentshield`）：`go test ./internal/receipt/ -count=1 -run 'SessionCapacity|MaxSessions'` 与 `go test ./internal/receipt/ ./internal/server/ -count=1` 通过。

- `receipt.Engine`：`MaxSessions`（默认 4096，范围校验）；满时对新 `session_id` 返回 `ErrSessionCapacity`，既有会话可继续决策。
- **不** LRU/淘汰会话腾名额（污点不得因淘汰变成“干净”）。
- `SessionStats` + decide/observe HTTP `503` 暴露 `active/max/capacity_refusals`（无正文/secret）。
- 未做：空闲无污点过期；快照读投影与 inventory 写分离；流式导出；1万/10万压测基线。

### I1 / DEV15-C（2026-09-06，本会话）

命令（`apps/agentshield`）：`go test ./internal/display/ ./internal/admission/ ./internal/export/ -count=1` 通过。

- `internal/display`：`ForTerminal` 中和 ESC/CSI/OSC/DCS；`ForMarkdownUntrusted` 标记不可信区并阻断 fence/标题逃逸。
- Skill Card：description 仅在 untrusted 区渲染；路径/元数据经终端转义。
- 导出 `SanitizeReason` 复用终端转义。
- 未做：HTML 导出面；派生文档独立签名；受管 checkpoint 持久化；整任务 DEV15 验收。

### I1 / DEV15-B（2026-09-06，本会话）

命令（`apps/agentshield`）：`go test ./internal/export/ ./internal/receipt/ -count=1` 通过。

- `privacy.go`：`NormalizeAbsPath` / `NormalizeLocator` / `NormalizeResourceValue` / `SanitizeReason`；profile id `agentshield.export.privacy.v1`。
- 分享包 Build 应用上述变换；禁止绝对 home 路径与用户名泄漏；params/excerpt 仍拒绝。
- 未做：终端 ESC/CSI/OSC 转义；Skill Card 不可信区；派生文档独立签名；受管 checkpoint 持久化；整任务 DEV15 验收。

### I1 / DEV15-A（2026-09-06，本会话）

命令（`apps/agentshield`）：`go test ./internal/receipt/ ./internal/export/ -count=1` 通过。

- `VerifyDetailed` + `VerificationReport`：`prefix_valid` / `history_integrity`（verified|unknown|failed）/ 可选独立 `Checkpoint`。
- 无 checkpoint：前缀通过仍标 `history_integrity=unknown`（截断尾部不可离线检出）；同目录 HEAD 不得当锚点。
- 有 checkpoint：tip 一致→verified；不一致→failed（截断/回滚可检）。
- 导出：`chain_prefix_valid` + `history_integrity`；`chain_verified` 仅表示前缀通过。
- 未做：受管 checkpoint 持久化；字段级隐私 profile；终端/Markdown 转义；Skill Card 不可信区；整任务 DEV15 验收。

### I1 / DEV14-B（2026-09-06，本会话）

命令（`apps/control-api`）：`uv run pytest app/tests/test_classification_contract.py app/tests/test_rules.py -k 'classif or provider' -q` 通过。

- `ClassificationRun` 增列：`input_summary` / `error_ref` / `latency_ms` / `prompt_tokens` / `completion_tokens`；迁移 `0016`。
- Provider 成功：如实落库 `model_ref`、发送的 `temperature=0`、`seed=None`（未发送不编造）、用量与耗时；`input_summary` 仅长度/哈希前缀/framework，不含原文名。
- 失败：`error_ref={error_code,error_digest}`；temperature/model_ref 仍可追溯。
- 未做：真实模型预算评估；整任务 DEV14 验收。

### I1 / DEV14-A（2026-09-06，本会话）

命令（`apps/control-api`）：
`uv run pytest app/tests/test_classification_contract.py app/tests/test_rules.py -k 'classif or provider' -q`；
`uv run pytest app/tests/test_inventory_hardening.py -k baseline -q`；
`uv run pytest app/tests/test_eval_baseline.py -q` 通过。

- `validate_provider_output`：非 object、缺键/错类型、confidence 非有限/越界/bool/str、伪造 evidence_ids 拒绝；额外顶层字段剥离。
- 稳定降级码：`schema_invalid` / `non_finite_confidence` / `forged_evidence` / `provider_timeout|unreachable` / `response_too_large` / `parse_error` 等；落库 `classification_degraded:…` + `degradation_reason`。
- `classify_asset`：合同/provider 失败与 `model-off` 一律候选→`needs_review`；不创建 PermissionFact。
- HTTP：`httpx.Client` 用 `with` 关闭；响应体 64KiB 硬顶。
- 未做：`model_ref`/真实 temperature/token/latency/input_summary 列与迁移；真实模型预算评估；整任务 DEV14 验收。

### I1 / DEV13-E（2026-09-06，本会话）

命令：`apps/control-api/.venv/bin/python -m pytest app/tests/test_list_meta.py -q` → **6 passed**。

- API：`/agents`、`/candidates`、`/findings`、`/permissions` 统一 `limit+1` + `X-SIQ-List-*` / `X-SIQ-Next-Cursor`；findings 稳定按 `first_seen_at|id`；permissions 按 `created_at|id`（不再误用无字段的 `updated_at` 游标）。
- Web：Agents / Findings / Permissions 展示覆盖文案与「加载更多」（复用 `useApiList`）。
- 未做：浏览器整旅程；审计服务端筛选 UI；整任务 DEV13 验收。

### I1 / DEV13-D（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_list_meta.py -q`（control-api，3 例）通过；`apps/web`：`npm test`（11 例）+ `npm run build` 通过。

- API：`list_meta.py`；`audit-events` / `change-requests` 用 limit+1 探测截断；响应头 `X-SIQ-List-*` / `X-SIQ-Next-Cursor`；`include_total` 可选总量（审计）；CORS `expose_headers`。
- Web：`getListPage` + `useApiList` 覆盖文案/加载更多；Audit（含 total）与 Changes 展示「本页≠全量」。
- 未做：agents/findings/permissions 等其余列表头；审计服务端筛选 UI；浏览器旅程；整任务 DEV13 验收。

### I1 / DEV13-C（2026-09-06，本会话）

命令（`apps/web`）：`npm test`（9 例含 `verification.test.ts`）+ `npm run build` 通过。

- `ui/verification.ts`：部署验证归一（none/pending/config_readback/behavior_enforced/failed/stale/unknown）；`readback_verified`→「配置已读回」，仅 `enforcement_verified`→「阻断已验证」；effective 无载荷不得冒充已验证。
- Changes：部署列展示验证徽章 + 绑定/rev/详情。
- Permissions：五态中文标签齐全；去掉静默 `environments.rows[0]`。
- 未做：列表分页/总量语义；审计服务端筛选 UI；浏览器完整旅程；整任务 DEV13 验收。

### I1 / DEV13-B（2026-09-06，本会话）

命令（`apps/web`）：`npm test` + `npm run build` 通过。

- Agents：智能扫描增加环境 `<select>`；未选则禁用按钮并报错；禁止 `envs[0]`。
- 环境列表来自 `GET /environments`（`useApiList`），不静默顶替。
- 未做：分页/总量语义；verification 五态；浏览器旅程；整任务 DEV13 验收。

### I1 / DEV13-A（2026-09-06，本会话）

命令（`apps/web`）：`npm test`（`protocol.test.ts` 4 例）+ `npm run build`（`tsc -b && vite build`）通过。

- 协议：`api/protocol.ts` + `client.request` — 成功响应须 JSON Content-Type；HTML/`<!DOCTYPE` 判为协议错误，不得当已连接。
- 列表：`useApiList` 非数组 → disconnected + 协议错误；仅 `VITE_DEMO_PLACEHOLDERS=true` 才填示例行且仍标 disconnected。
- Changes：显式 `<select>` 环境/绑定；禁止静默选首个；`approved`/`emergency_applied` 可部署；展示 `review_status`。
- 未做：Agents 扫描仍可能选首环境；分页/总量语义；verification 五态统一展示；浏览器完整旅程与截图核对；整任务 DEV13 验收。

### I1 / DEV12-B（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_outbox_lease.py app/tests/test_worker.py app/tests/test_policy_flow.py -k 'break_glass or outbox or loop' -q`（`apps/control-api`）通过。

- Outbox 字段：`lease_owner`/`leased_at`/`lease_revision`/`attempt`/`next_attempt_at`/`dead_lettered_at`；迁移 `0015`。
- `claim_outbox_batch` → 网络发送 → `confirm_outbox_published`（CAS）或 `nack` 退避/死信；领取事务在发送前结束。
- 负向：双 worker 不相交领取；错 owner 确认失败；租约过期可接管；达上限死信。
- 未做：真实 PostgreSQL `FOR UPDATE SKIP LOCKED`；人工死信重放 UI；exactly-once 宣传。

### I1 / DEV12-A（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_policy_flow.py -q`（`apps/control-api`）通过。

- `ChangeRequest` 增加 `approved_at` / `review_status` / `review_due_at` / `reviewed_by`；迁移 `0014`（存量 `post_review_due` 只标 `review_status=due`，不猜测还原业务终态）。
- break-glass 批准：业务态 `emergency_applied` + `review_status=pending`，期限=批准时刻+TTL（非 created_at）。
- `reap_break_glass_reviews`：仅 `pending` 且 `review_due_at` 到期 → `review_status=due`，**不改** status；重复运行不重复发事件。
- 未做：Outbox DB 租约多实例；死信/人工重放；到期自动撤权；真实 PG 证明。

### I1 / DEV11-F（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_outbox_null_inventory.py -q`（`apps/control-api`）通过。

- `scan_outbox_null_refs` / `inventory_report`：盘点 payload 已知引用键与 envelope `resource_ref`/`environment_id` 空值；`policy=inventory_only_no_guess_repair`。
- CLI：`scripts/inventory_outbox_null_refs.py`（只读；有命中 exit 1）。
- 未做：带依据的追加修复；生产/真实 PG 库盘点；注册并发压力；整任务 DEV11 验收。

### I1 / DEV11-E（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_registration_rate_limit.py app/tests/test_enrollment_flow.py app/tests/test_request_id.py -q`（`apps/control-api`）通过。

- 滑动窗口限速：注册键=`device_identity` + enrollment_code 哈希；创建注册码键=`tenant:env`；**不按源 IP**。
- 超限 `429` + `Retry-After`；`registration_rate_limited` / `enrollment_create_rate_limited`；进程内 `rejected_total`。
- 配置：`SIQ_AS_REGISTER_RATE_LIMIT` 等；`.env.example` 已注明。不宣称多副本/跨进程一致。
- 未做：真实 PG 并发；历史 null 事件盘点修复；整任务 DEV11 验收。

### I1 / DEV11-D（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_request_id.py app/tests/test_enrollment_flow.py app/tests/test_audit_outbox.py -q`（`apps/control-api`）通过。

- `normalize_client_request_id`：限长 64、`[A-Za-z0-9._-]{8,64}`；控制字符/空白/非法 → 服务端 `req-*`。
- 中间件写入 `request.state` 并回显规范化值；enrollment 审计读 state 而非原始 header。
- `audit()` 显式 `id=new_id("aud")`；操作者仍来自身份上下文。
- 未做：注册容量/速率控制；真实 PG 并发；历史 null 事件盘点。

### I1 / DEV11-C（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_enrollment_flow.py app/tests/test_config_security.py -q`（`apps/control-api`）通过。

- `create_enrollment` 使用 `load_settings().enrollment_ttl_seconds`（不再写死 900）。
- 启动校验：`clamp_enrollment_ttl` 允许 `[60, 604800]`；越界 `RuntimeError`；`.env.example` 已注明。
- 聚焦：非默认 120s 写入 `expires_at`；坏配置单测。
- 未做：Request-ID 规范化、注册限速、真实 PG 并发、历史 null 事件盘点。

### I1 / DEV11-B（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_enrollment_flow.py -q`（`apps/control-api`）通过。

- `register_edge`：重复 `device_identity` 预检 + `IntegrityError` → `409 device_identity_conflict`（无 500）；冲突路径不标记 `used_at`，同码换新身份仍可注册。
- Edge 创建时应用层赋 `id`；审计带 `resource_id`。
- 未做：真实 PostgreSQL 并发双成功恰一；enrollment TTL 配置生效；Request-ID 规范化；注册限速。

### I1 / DEV11-A（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_audit_outbox.py app/tests/test_policy_flow.py app/tests/test_rules.py -q`（`apps/control-api`）通过。

- `emit_event` / `audit`：payload 已知对象引用键与 `resource_ref` / `resource_id` 非空 fail-closed（R05）。
- 创建前应用层赋 ID：`Environment` / `DesiredPolicy` / `ChangeRequest` / `Finding`（rules/drift/deployment_verify）/ `ClassificationRun`；threat 路径保留 flush。
- 聚焦：创建 env/CR 后 outbox 引用与响应 ID 一致；空引用单测拒绝。
- 未做：重复身份冲突码、注册码事务回滚与并发、enrollment TTL 启动校验、Request-ID 规范化、注册限速、真实 PostgreSQL、历史 null 事件盘点修复。

### I1 / DEV10-I（2026-09-06，本会话）

命令：`go test -count=1 ./...` 于 `connectors/{mcp,piagent,dify,workbuddy}` 全部通过。

- 四者 `readFileLimited` → `openRegular`（Unix `O_NOFOLLOW|O_NONBLOCK`；打开后拒非普通文件）。
- 各包负向：`TestReadFileLimitedRefusesSymlink`；既有 symlink escape collect 用例仍绿。
- 未做：强杀进程端到端；检查后同 UID TOCTOU；整任务 DEV10 验收。

### I1 / DEV10-H（2026-09-06，本会话）

命令：`go test -count=1 ./...`（`connectors/hermes`）通过。

- Hermes `readFileLimited` → `openRegular`（Unix `O_NOFOLLOW|O_NONBLOCK`；打开后拒非普通文件）。
- 负向：`TestReadFileLimitedRefusesSymlink`；`TestCollectRefusesSymlinkedConfigYAML`（外链配置不得产出候选）。
- 未做：mcp/piagent/dify/workbuddy 等同路径加固；强杀端到端；整任务 DEV10 验收。

### I1 / DEV10-G（2026-09-06，本会话）

命令：`go test -count=1 ./...`（`connectors/openclaw`）通过。

- `readFileLimited` 改走 `openRegular`：Unix `O_NOFOLLOW|O_NONBLOCK`；打开后拒绝非普通文件。
- 负向：`TestReadFileLimitedRefusesSymlink`；`TestCollectRefusesSymlinkedOpenclawJSON`（外链配置不得产出候选/权限事实）。
- 未做：其余 Connector 配置读取点全表；同 UID TOCTOU；整任务 DEV10 验收。

### I1 / DEV09-G（2026-09-06，本会话）

命令：`AGENTSHIELD_UPDATE_SAMPLES=1 go test ./internal/admission/ ./internal/grant/`；`go test ./internal/signing/`；`uv run pytest app/tests/test_schema_contracts.py -k 'admission or grant' -q` 通过。

- admission/grant 写者默认嵌入 `signing_schema=local_canonical/v1`（参与签名字节）；`resign`/`signDoc(..., true)`。
- 合同：`admission.schema.json` / `grant.schema.json` 必填该字段；Go 样例与 Python VALID_EXAMPLES 已更新。
- 负向：剥离嵌入字段后验签失败；篡改仍失败；遗留 Evidence 本地 writer 仍省略字段（双读）。
- 未做：rulepack 跨语言向量；Evidence → `evidence_utf8/v1` 写者切换；整任务 DEV09 验收。

### I1 / DEV10-F（2026-09-06，本会话）

命令：`go test -count=1 ./...`（`edge/agent`）通过。

- `exec_ledger/{task_id}.json`：记录 `content_digest`（与任务验签信封同 canon 的 sha256）+ Receipt。
- `Execute`：签名/过期通过后 Lookup；同 digest 复用结果不跑 connector；异 digest → `task_content_conflict`；过期失败不入账。
- 负向：digest 对 payload 敏感；路径穿越 task_id 拒绝；expiry 不复用。
- 未做：各 Connector scope 正负向全表；强杀进程端到端；宣称整任务 DEV10 验收。

### I1 / DEV10-E（2026-09-06，本会话）

命令：`go test -count=1 -run 'PendingReceipt|DrainPending' ./...`（`edge/agent`）；`uv run pytest app/tests/test_edge_task_lease.py -q` 通过。

- Edge：`pending_receipts/{task_id}.json` 在上传成功（或空成功批）后原子落盘；`tasks` 先 `DrainPendingReceipts` 再领取；回执成功后删除 journal。
- 控制面：`pending|uploaded` 均可 claim（同租约规则）；过期惰性清扫覆盖 `uploaded`。
- 负向：journal 路径穿越拒绝；drain 部分失败保留条目；uploaded 原持有者可再领；过期 uploaded → expired。
- 未做：执行去重账本（同 task_id 内容变更拒绝的完整本地账）；强杀进程端到端样本；各 Connector scope 全表。不宣称整任务 DEV10 验收。

### I1 / DEV10-D（2026-09-06，本会话）

命令：`go test -count=1 -run ValidateScopeSafety ./...`（`edge/agent`）通过。

- `ValidateScopeSafety` / `countGlobMatches`：改用 `Lstat`；scope 根与 `/*` glob 命中若为 symlink 则拒绝（不再经 `Stat` 跟随后当成合法目录）。
- 负向：`TestValidateScopeSafetyRejectsSymlinkRoot`（明文根 + 仅 symlink 的 trailing glob）。
- 未做：各 Connector 读取点全矩阵；检查后 TOCTOU/同 UID 替换；uploaded 卡住；执行去重账本。不把本切片记为整任务 DEV10 验收。

### I1 / DEV10-C（2026-09-06，本会话）

命令：`go test -count=1 ./...`（`connectors/systemd`）与 `go test -count=1 ./...`（`edge/agent`）通过。

- systemd：停止上传完整 `exec_summary`；允许字段为 `exec_path`（可执行路径）+ `exec_argv_digest`（脱敏后 ExecStart 的 sha256 hex）。
- redactor（`siq.redaction.v1` 加性）：`--password/--token/--api-key` 等空格与 `=` 形式、引号值、`scheme://user:pass@host`；故意不覆盖歧义短 flag（如裸 `-p`）。
- 负向：`TestCollectRedactsExecSecrets`（含空格 `--password`）断言 attributes 无原文密钥且无 `exec_summary`；`TestRedactorString` 覆盖空格 flag/URL。
- 未做：去重账本；scope symlink（M-E2）；uploaded 卡住恢复；宣称 redactor 穷尽所有 CLI 变体。

### I1 / DEV10-B（2026-09-06，本会话）

命令：`go test -count=1 . -run 'PerOpDeadline|Expiry' -timeout 15s`（`edge/agent`）通过。

- `call`：父进程 `context.WithTimeout` 覆盖 stdin 写 + 响应读；超时 `killLocked`；超大请求拒写。
- 负向：挂起 connector（`exec sleep`）约 250ms 内 `ErrTimeout`，随后 `ErrConnectorClosed`。
- 未做：进程组/孙进程跨 OS 清理证明；scope symlink；systemd 脱敏；uploaded 卡住恢复。

### I1 / DEV10-A（2026-09-06，本会话）

命令：`go test -count=1 ./... -run 'Expiry|Signature'`（`edge/agent`）通过。

- `ExpiryError` / `Expired`：空或空白 `expires_at` → 拒绝（不再无限有效）；不可解析 → 拒绝；`now > expires_at+60s` → 过期。
- `Execute` 使用 `ExpiryError` 文案写入 `error_code=expired`。
- 未做：执行去重账本；Connector per-op 超时全矩阵；scope symlink；ExecStart 脱敏；uploaded 卡住恢复；issued_at 合同字段。

### I1 / DEV09-F（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_policy_compile_vectors.py -q`；`go test -count=1 ./internal/grant/ -run PolicyCompile` 通过。

- 夹具 `policy_compile_vectors_v1.json`（Python `compile_policy` 生产）：全域对等、最小策略、静态 network、字段矩阵 unsupported 桶、未知键拒绝；冻结 `known_keys` 白名单。
- Go `TestPolicyCompileVectorsV1` 与 Python freshness 测试消费同一夹具。
- 未做：写者默认嵌入 `signing_schema`；rulepack 跨语言签名向量；整任务 DEV09 验收。

### I1 / DEV09-E（2026-09-06，本会话）

命令：`go test -count=1 ./internal/signing/ ./internal/admission/ ./internal/grant/` 通过。

- `DocSigningSchema` / `VerifyDocument`：缺字段默认 `local_canonical/v1`；嵌入字段参与 canon 且须 Normalize；evidence/receipt/未知/非字符串受控拒绝。
- 独立夹具：`local_doc_embedded_schema_vectors_v1.json`（生产者 `gen_local_doc_embedded_schema_vectors_v1.py`）；legacy 与 embedded 字节/签名必异。
- admission/grant `Verify` 改走 `VerifyDocument`（双读消费者）；写者默认仍不嵌入（`WithSigningSchema` 预留）。
- 未做：写者切换默认嵌入；policy 编译全字段矩阵；整任务 DEV09 验收。

### I1 / DEV06-C（2026-09-06，本会话）

命令：`go test -count=1 ./internal/admission/` 通过。

- H5b：`zoneDocs` 且非 `isCodeFile` 才强制 info；`assets/*.sh` 等代码文件保留核心 disposition（download-exec → declare）。夹具 `malicious/docs-code-exec`。
- H5c：移除“两个引号即示例”；改为 blockquote + 显式 example/do-not-follow/red-flag 等措辞。夹具 `malicious/quoted-injection`；官方样例仍靠措辞降级。
- 未做：PowerShell 续行；fence 语义扩展；能力事实→策略全矩阵；跨语言准入对等。

### I1 / DEV06-B（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_threat_analysis.py app/tests/test_threat_match_oracle.py app/tests/test_detection_baseline.py -q`；`go test -count=1 ./internal/threat/` 通过；已重生 `match_oracle_v1.json`。

- Python/Go：`detected_type=shell` 时接合 POSIX 行尾 `\` 续行后再做规则扫描；行号取续行块首物理行。
- 语料：`mal-download-exec-pipe-continued`；单测锁定命中与 Python 非 shell 不接合。
- 未做：无反斜杠的“下一行以 `|` 开头”伪跨行（非 POSIX 续行）；PowerShell 反引号续行；引用/fence/zone（H5b–c）。

### I1 / DEV06-A（2026-09-06，本会话）

命令：`uv run pytest app/tests/test_threat_match_oracle.py -q`（`apps/control-api`）与 `go test -count=1 ./internal/threat/ -run TestMatchOracleFieldParity`（`apps/agentshield`）通过。

- 合同 Oracle：`match_oracle_v1.json`（Python `gen_threat_match_oracle_v1.py` 生产）冻结共享正则层 `content_sha256` / `detected_type` / `shared_rule_ids` / 标注规则的 `line`·`excerpt`·`excerpt_sha256`·severity·confidence。
- Go `TestMatchOracleFieldParity` 与 Python `test_threat_match_oracle.py` 逐字段消费同一夹具；AST 规则列入 `python_only_rule_ids`，Go 不得发出。
- 支持矩阵：[detection-support-matrix-v1.md](detection-support-matrix-v1.md)。
- 未做：H5 多行续行/引用启发式/zone 降级；能力事实→准入端到端；属性/变异语料全覆盖。

### 基础切片的修复合同

- DEV03-A：同一版本路径的 O_EXCL 冲突不得成功吞掉；版本追加重试分配，固定 ID 只有内容一致才能视为幂等。读者不应把损坏记录变为正常空集。此切片不能代替多文档事务和单写者。
- DEV03-B：存活写者独占；grant 读改写必须 CAS；冲突不得伪成功。CLI→HTTP 完整管理会话代理与跨文件提交协议不在本切片。Windows 无法证明 pid 死亡时保守视为占用（不静默接管）。
- DEV04-A：公开 manifest-verify 的发行身份来自程序受信根；清单里的 signed_by 不授予信任。开发签名自检/测试使用调用者显式提供的可信公钥，不改变官方发布验证。
- DEV05-A：静态可识别的非普通文件不得打开；文件读取严格受剩余预算约束；HashDir 不得为越界/不完整树发布正常摘要。保持普通文件和规格允许的根内文件链接行为。
- DEV05-B：枚举期强制目录/文件预算与取消；达上限返回 incomplete/截断，不输出“安全完整”。directory connector 不得先收集全部路径再截断。
- DEV05-C：打开后 fd Stat + SameFile；Unix O_NOFOLLOW|O_NONBLOCK（ADR-013）。不得把前后 Stat 或本切片称为同 UID race-free / 整任务验收。
- DEV03-C：hold 决议幂等/冲突/过期；链读者不消费半行；audit 落盘 Sync。不代替 grant+policy+audit 多文档事务。
- DEV09-A：任务验签必须与 CPython `signing._canonical_bytes` 逐字节一致；禁止用 Go 默认 `json.Marshal`；夹具由独立生产者冻结。不把 evidence UTF-8 合同误当成任务合同。
- DEV08-A：JWKS 不得永久缓存；unknown_kid 刷新有界；生产缺 issuer 不得启动；refresh 不得当资源身份。真实 IdP 缺证不记通过。
- DEV08-B：资源 API 仅接受 access/user/service；Edge secret 须高熵 mint + 验签长度下界与常量时间比较。不引入口令 KDF；不宣称真实 IdP 兼容。
- DEV04-B：adapter 与 bootstrap 必须共用验签路径；未验证二进制不得执行。改 Skill 目录后须重签 manifest。
- DEV02-B：grant approve 必须消费绑定 digest/scope/revision 的单次挑战；正文变更或重放不得成功。不把挑战当成同 UID 防自批。
- DEV04-C：Python `hash_skill_dir` 必须与 Go `HashSkillDir` 逐字节一致；安装入口带 `--skill-dir` 时摘要失配必须拒绝。staging 再验不在本切片。
- DEV03-D：grant 成功响应前 policy/audit（按需）必须落盘；失败返回 incomplete，不伪成功。不回滚已发布版本，不宣称崩溃原子性。
- DEV09-B：Evidence/Batch 必须 `ensure_ascii=False` + 独立向量；不得与任务 `ensure_ascii=True` 混用。清单见 signing-inventory-v1.md。
- DEV09-C：本地 admission/grant 向量走 `local_canonical/v1`；验签须经 schema 路由；未知版本与 evidence schema 不得由本地 ASCII 验签器接受。正文内嵌见 DEV09-E。
- DEV09-D：receipt 须 hash-then-sign（`receipt_hash_chain/v1`）；禁止把 SignCanonical(body) 当回执验签；链式 prev_hash 必须绑定上条 content_hash。
- DEV09-E：验签须双读正文 `signing_schema`（缺省 local v1；嵌入字段计入签名字节）；不支持的 schema 在验签前失败。不得把未切换写者记为合同升版完成。
- DEV09-F：Desired Policy 编译须与 Python 向量的 artifact_hash/unsupported/needs_generation 对等；未知键拒绝；known_keys 白名单双边锁定。
- DEV09-G：admission/grant 新签文档须默认嵌入 `signing_schema=local_canonical/v1`；字段参与签名；验签双读遗留无字段体。不得把 Evidence UTF-8 写者切换记为本切片完成。
- DEV10-A：Edge 任务缺/坏 `expires_at` 必须拒绝执行；允许有界时钟偏差；不得把无期限任务当永久有效。
- DEV10-B：Connector per-op 超时须由父进程独立强制（写+读）；超时须终止子进程；环境变量超时不得代替父端 deadline。
- DEV10-C：systemd 不得上传完整 ExecStart；仅允许路径与脱敏 argv digest；空格分隔敏感长 flag 与 URL 凭据须经 redactor。不宣称穷尽全部 CLI 变体或整任务验收。
- DEV10-D：scope 根与 trailing `/*` 匹配不得为 symlink；须用 Lstat 判定。不宣称各 Connector 读取链全覆盖或同 UID TOCTOU 消除。
- DEV10-E：uploaded 须可被原持有者（或租约过期接管方）再领；过期须惰性标 expired；Edge 须在回执前提交 pending receipt journal。不宣称完整执行去重账本或强杀端到端。
- DEV10-F：同 task_id 同内容摘要须复用本地结果；摘要变更须拒绝（task_content_conflict）；过期结果不得入账复用。不宣称强杀端到端或 Connector 全表。
- DEV10-G：openclaw.json 最终路径不得为 symlink；须 O_NOFOLLOW（或等价）拒绝并不得产出逃逸候选。不宣称其他 Connector 读取点已全覆盖。
- DEV10-H：Hermes 配置最终路径同 openclaw，须 O_NOFOLLOW 拒绝 symlink 且不得产出候选。不宣称其余 Connector 或强杀端到端已完成。
- DEV10-I：mcp/piagent/dify/workbuddy 配置读取须同样 O_NOFOLLOW；不得把强杀端到端或整任务验收记为本切片完成。
- DEV07-A：用户配置首备不可覆盖；坏 JSON/symlink/未知 mode 不得改写；配置写入须同目录原子替换。
- DEV07-B：卸载须外科剥离本产品钩子/策略，保留安装后用户字段；冲突须返回可审阅 RecoveryPlan，禁止静默整文件覆盖活配置。
- DEV07-C：fail-closed 须追加 `pending_decision/v1` 未签名 JSONL；block 记 deny，warn/audit_only 记 allow。不宣称 serve 已补签 observed。
- DEV07-D：serve/decide 须将 pending 提升为签名回执并推进游标；幂等；坏 JSONL 不得静默跳过整文件。不宣称崩溃零重复。
- DEV04-D：安装入口须对将执行的精确对象做私有 staging 复制后再哈希；源与暂存摘要不一致必须拒绝。不宣称同 UID 防改写。
- DEV04-E：下载须 opt-in；须先验签清单再取 URL；字节与 sha256 pin 必须匹配；默认拒非 HTTPS。不把 loopback 测当成 GitHub 真发布验收。
- DEV06-A：共享正则层须字段级 Oracle 对等；不得把 AST 独有规则记成 Go 对等；仅 rule_id 命中不算本切片完成。
- DEV06-B：shell 类型须接合 POSIX `\` 续行后再匹配下载即执行等跨行载荷；不得把无 `\` 的伪跨行或 PS 续行记为本切片完成。
- DEV06-C：docs 区代码文件不得一律 info 降级；提示注入不得仅因引号个数降级。不宣称 fence/PS/策略全矩阵完成。
- DEV11-A：emit 前须有非空对象 ID（应用层赋 ID 或 flush）；outbox 对已知引用键与 resource_ref fail-closed。不得把注册冲突/TTL/Request-ID/限速或真实 PG 并发记为本切片完成。
- DEV11-B：重复 device_identity 须稳定 409 `device_identity_conflict` 且不消耗注册码；不得把真实 PG 并发或 TTL/限速记为本切片完成。
- DEV11-C：enrollment TTL 须读配置且启动期校验范围；不得把 Request-ID/限速或真实 PG 记为本切片完成。
- DEV11-D：客户端 Request-ID 须限长限字符仅作 correlation；非法则服务端生成；审计主键服务端生成。不得把注册限速或真实 PG 记为本切片完成。
- DEV11-E：注册限速须按业务键（身份/码/租户环境）而非源 IP；429+Retry-After。不得把多副本一致或真实 PG 并发记为本切片完成。
- DEV11-F：历史 outbox 空引用只盘点、不猜测补 ID；报告须含不可自动恢复计数。不得把生产库已修复或整任务验收记为本切片完成。
- DEV12-A：break-glass 复核须正交于业务 status；到期只改 review_status；期限源于批准时刻。不得把 Outbox 多实例领取或真实 PG 记为本切片完成。
- DEV12-B：Outbox 须 DB 领取+租约 CAS 确认；发送前结束领取事务；失败退避/死信；默认至少一次。不得把真实 PG SKIP LOCKED 或 exactly-once 记为本切片完成。
- DEV13-A：200 HTML/非 JSON 须协议错误；断连不得伪称已连接并回退示例（除非显式演示开关）；部署须用户选环境与 binding。不得把浏览器整旅程或分页/五态 UI 记为本切片完成。
- DEV13-B：智能扫描须用户显式选环境，禁止 `envs[0]`。不得把分页/五态或浏览器旅程记为本切片完成。
- DEV13-C：配置读回与阻断验证须分开展示；权限五态标签齐全；权限页不得静默选首环境。不得把分页/总量或浏览器旅程记为本切片完成。
- DEV13-D：列表须声明截断/游标（或总量）；本页条数不得冒充全量。不得把其余列表端点或浏览器旅程记为本切片完成。
- DEV13-E：agents/candidates/findings/permissions 须同样截断元数据+可翻页；本页条数不得冒充全量。不得把浏览器整旅程或整任务验收记为本切片完成。
- DEV14-A：模型输出须严格校验；合同/传输失败须稳定降级码并 needs_review，禁止 500 或冒充低风险；不得写入 effective/PermissionFact。不得把真实模型评估或 run 元数据扩列记为本切片完成。
- DEV14-B：run 须记录实际发送的 model/temperature；未发 seed 须为 null；input_summary 不得含原文；失败须有 error_ref。不得把真实模型评估记为本切片完成。
- DEV15-A：回执验证须拆分前缀有效与历史完整性；无独立 checkpoint 须标 history unknown。不得把同目录 HEAD 当锚点，或把脱敏/终端转义记为本切片完成。
- DEV15-B：分享导出须字段级归一/替换绝对路径与用户名；不得泄漏 params/excerpt。不得把终端转义或派生签名记为本切片完成。
- DEV15-C：终端/Markdown 须中和 ESC/CSI/OSC；Skill 原文须在不可信区。不得把派生签名或整任务验收记为本切片完成。
- DEV16-A：会话须有容量上限与可观测拒绝；容量不足拒绝新 session，禁止 LRU 清污点。不得把快照投影分离或压测基线记为本切片完成。
- DEV16-B：GET 须读带 revision/health 的投影缓存；写路径 Refresh；坏文件不得伪装空集成功。不得把流式导出或压测基线记为本切片完成。
- DEV16-C：导出须磁盘有界读取与 JSON 总量预算；截断须 `incomplete`；不得把内存切片当成磁盘上限。不得把压测基线记为本切片完成。
- DEV17-A：镜像须吃 uv.lock；扫描不可用不得装绿；govulncheck 须执行。不得把 Actions SHA/digest/nginx 头或 CVE 清零记为本切片完成。
- DEV17-B：ci.yml Actions 须钉完整 SHA；企业 nginx 须有 CSP/frame/nosniff/Referrer；HTTP 不得套 HSTS。不得把 digest/OpenShell/Mermaid 记为本切片完成。
- DEV17-C：OpenShell 下载须 env+摘要+允许域；`run:` 不得直接插值 inputs；Mermaid 须自托管固定版本。不得把基础镜像 digest、Pages 钉扎或真实网关下载实测记为本切片完成。
- DEV17-D：pages.yml Actions 须钉完整 SHA；control-api/web Dockerfile 基础镜像须 `@sha256`。不得把真实网关下载或整任务 DEV17 验收记为本切片完成。
- DEV18-B：威胁模型须含本地产品威胁（rebinding/同 UID/Skill/读回≠强制等）并回链证据；不得把真机 L3 强制或 managed-linux 记为本切片完成。
- DEV09-H：Evidence 新签须嵌入 `evidence_utf8/v1`；消费者双读遗留无字段体；错 schema fail-closed。不得把 rulepack 跨语言向量记为本切片完成。
- DEV09-I：rulepack `.sig` 须有独立生产者跨语言向量（ASCII local canon）；篡改拒绝；与 evidence UTF-8 必不同。不得把防回滚策略变更或整任务验收记为本切片完成。
- DEV08-C：生产须显式 JWT audience；mock JWKS 须覆盖错 aud/iss/alg/过期与 TTL 轮换窗口。不得把真实 IdP 兼容记为本切片完成。
- DEV18-C：须有 OS×平台证据矩阵与生产 runbook 模板；L3_enforce/真实 PG/IdP 不得记通过；零行 supported。不得把独立深扫或整任务验收记为本切片完成。
- DEV15-D：分享导出须独立派生签名与 `derived_from`；禁止套用回执 hash-chain 签名冒充原样有效。不得把受管 checkpoint 持久化或整任务验收记为本切片完成。
- DEV16-D：须有可运行观察骨架与 `thresholds=null` 诚实报告；smoke 可门禁。不得把 smoke 记为 1万/10万验收，不得预填毫秒 SLA。
- DEV16-E：仅无污点/无 trifecta 可空闲过期；污点不得因空闲被清后同 ID 冒充干净。不得把跨进程持久过期或整任务验收记为本切片完成。
- DEV15-E：受管 checkpoint 须在 `receipts/` 外并签名；禁止 HEAD 当锚点；截断相对 checkpoint 须 history failed。不得把整 state 同 UID 回滚防护或整任务验收记为本切片完成。
- DEV06-D：powershell 须接合反引号续行；shell 不得误接合反引号。不得把无 `\` 伪跨行或整任务验收记为本切片完成。
- DEV06-E：shell/powershell 须接合「下一行以 `|` 开头」的伪管道（无续行符）；接合不得嵌入换行；非 shell 类型不得接合。不得把能力→准入矩阵或整任务验收记为本切片完成。
- DEV06-F：共享 rulepack 每条规则须有 category/disposition/declared capability 合同行；cred+egress 与 docs 散文降级须正交。不得把属性变异语料或整任务验收记为本切片完成。
- DEV06-G：Go 行切分须覆盖 Python splitlines 分隔符；U+2028 不得使行号/命中与 Python 分叉；`\\bcurl\\b` 不得命中 notcurl。不得把完整 Unicode `\\b` 或整任务验收记为本切片完成。

下一刀：DEV10 强杀恢复端到端样本，或 DEV12/14 等仓内项；缺真实环境的项保持 unverified。不宣称 DEV01–18 整目标完成。

### 继续核验（2026-09-06，本会话）

- `apps/control-api`：执行 `uv run ruff check app --fix`，清理 13 个新增/遗留 lint 问题；随后 `uv run pytest app/tests/test_outbox_lease.py -q` 通过（4 passed）。完整 `uv run pytest` 为 445 passed、3 failed；失败来自同一测试会话共享 SQLite 中历史 outbox 事件占满 `limit=10`，目标事件未被选中，并非断言到租约逻辑的失败。该测试隔离问题待后续用例夹具修复，未将全量标为通过。
- Go 工具链：当前执行环境未安装 `go`（`go: command not found`），因此本会话未能重新运行 `edge/agent` 与 `apps/agentshield` 的 Go race/vet 回归；既有台账中的 Go 通过记录保持历史证据，不冒充本次验证。
- 代码仅做 lint 导入整理及文档尾部格式修复；未提交、未部署、未操作真实凭据或生产数据。

### Go 工具链恢复与回归（2026-09-06，本会话）

- 安装 Go 1.26.5 linux/arm64 到用户目录 `/home/maoyd/.local/go`，校验官方 SHA-256；加入 `.bashrc` PATH。
- `apps/agentshield`：gofmt、`go vet ./...`、`go test -race -count=1 ./...` 通过；随后交叉编译 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 全部通过。
- `edge/agent`：`go test -race -count=1 ./...` 通过。

### DEV12 测试隔离修复（2026-09-06，本会话）

- `app/tests/test_outbox_lease.py` 增加自动清理 fixture，在每个租约用例前后删除测试 Outbox 事件，避免共享 SQLite 中其他测试事件占满 claim limit 导致误失败。
- `uv run ruff check app/tests/test_outbox_lease.py` 通过；完整 `uv run pytest -q`：448 passed。

### DEV10/17 回归继续（2026-09-06，本会话）

- Edge：四目标交叉编译（linux/amd64、linux/arm64、darwin/arm64、windows/amd64）及 `go test -race -count=1 ./...` 全部通过。现有 connector 超时、pending receipt、执行账本测试覆盖强杀后的基础恢复语义；真实进程级崩溃注入仍未宣称完成。
- DEV17 静态门禁全部通过：Actions SHA、Dockerfile digest、Web 安全响应头、能力矩阵诚实性检查。

### DEV03 一致性切片复核（2026-09-06，本会话）

- 复核现有 `Store.CommitGrant`：grant 先 CAS 发布，policy/audit 失败会写入 `commits/*.incomplete.json`，HTTP 返回 `incomplete_commit`，不会伪造成功。
- 聚焦回归：`go test -race -count=1 ./internal/state ./internal/server ./internal/grant` 通过。已有 policy/audit 失败、CAS 冲突及 incomplete marker 负向测试覆盖当前协议。
- 多文件崩溃恢复与自动重放仍未实现，不能将 DEV03 父任务标记完成。

### DEV03 恢复标记可观测性（2026-09-06，本会话）

- 新增 `Store.ListIncompleteCommits()`：按确定顺序读取并严格校验 incomplete marker；损坏/未知 phase 直接报错，不当作成功提交。
- 增加 policy 失败后 marker 列举测试；`go test -race ./internal/state` 通过。
- 该切片提供恢复操作所需的可靠待处理清单；自动重放仍需在后续切片中加入完整提交材料与幂等恢复命令。

### DEV03 运维入口（2026-09-06，本会话）

- 新增 `siq-agent-security incomplete` CLI，输出严格校验后的 durable incomplete commit JSON 清单，供后续人工恢复和 runbook 使用；不会自动重放或篡改历史版本。
- `gofmt`、`go vet ./...`、`go test -race ./...` 全部通过。
