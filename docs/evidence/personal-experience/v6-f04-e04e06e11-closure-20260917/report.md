# F04 / D05：E04/E06/E11k partial 收口批次（2026-09-17）

本批固定 Linux/arm64 二进制 SHA256 `0b16e5e09e6d807b5be732e390c373e6a4354d096b272eba827bddb84a6c8177`，源绑定 `ba8d266ef5ba861282f23a8576be8744d6023118f3f42efd8e1054632ffe06fc`（931 文件，本批复算一致；本批只改 Python 驱动与 docs，未改任何 Go 源、go.mod 或 embed）。/tmp 易失，候选复制到 `d05-private/bin/`（0700）并重新校验 sha256 一致。真实 OpenShell 0.0.83 gateway（共享，未重启）、本批独占沙箱 `siq-v6-f04-e04e06e11-20260917`、真实 SIQ daemon 与 E12 浏览器腿执行了扩展后的 `openshell-o05v6-d05-acceptance.py`，**不带 --only 的全矩阵**：[机器可读矩阵](d05-acceptance-matrix.json)344 步：337 pass、6 partial、1 blocked、0 fail。E01–E13 汇总 **11 pass / 2 partial**（E08、E11），**不等于全部验收通过**。

## 本批新增真实腿（对照上一批 238 步：229 pass / 8 partial / 1 blocked）

- **E04 过期 SEC（决策平面）**：批属第二 daemon 走完整 managed-instance 链（import → 安装绑定授权 → plan/apply/activate → runtime identity（session_ttl=3600）→ 会话 enrol → `POST /v1/skill-contexts` ttl=60，合同最小 TTL）。存活期 decide 返回 allow + `authority_status=valid` + `skill_attribution.status=verified`（E04sg）；真实墙钟等待 63.0 s 后同一 decide 返回 deny + `authority_status=invalid` + `authority_reason_code=skill_context_expired`（E04si）。decide 使用 enrol 后的 scoped runtime 凭据（全局 token 对 hri- 主体被 403 `scoped_decision_credential_required` 拒绝，已实测）。executor 路径的 SEC 主体命名空间不相交，本腿明确只证决策平面。
- **E04 缺必需 Authority**：第二 daemon 在 init 后 serve 前把 state `config.json` 的 `intent_enforcement` 改为 `"required"`（合法用户配置），`POST /v1/decide` 返回 200 + deny + invalid + `intent_binding_missing`，deny 决策无 hold 可批（404），零任务副作用（E04n1–E04n4）。
- **E06 加载窗口提交被拒**：`policy update`（不带 --wait）开窗，批准钉新 (revision,digest)，沙箱 `current_policy_version` 未前进时 submit → 409 `openshell_task_instance_unconfirmed`（E06m6–E06m8），零执行。
- **E06 加载等待中撤权**：新建**第二 grant**（独立 admission）并在窗口内 revoke，轮询确认加载完成后 submit → 403 `openshell_grant_invalid`（E06n1–E06n6）。主 grant 不动，K70 仍拥有主 grant 撤销案。
- **E06 加载超时**：驱动直跑 CLI `policy set --policy X <target> --wait --timeout 1`，本地等待 1 秒超时（exit 124）但 gateway 写入已落（revision 16→17 单独记账），钉旧 revision 的批准提交被拒 409 `openshell_task_policy_not_loaded`（E06t2–E06t6），随后恢复纯净策略并再读。
- **E06 旧 CLI v0.0.13**：`~/.local/bin/openshell`（只读）实测 `policy set --help` **有** `--wait/--timeout`（E06u3，纠正上一批「旧 CLI 不支持 --wait」的假设）。第二 daemon 成对设置 `SIQ_AS_OPENSHELL_CLI_BIN`+endpoint 指向旧 CLI：握手探测竟通过（probe_ok/tier L3），但执行前的实例/策略读回拒绝提交 —— 409 `openshell_task_instance_unconfirmed`，零任务启动（E06v1–E06v8）。拒绝形态以实测为准。
- **E11k 结果写盘故障（真实服务 + 真实 EACCES）**：三变体分开断言 —— A：运行中 chmod evidence 目录 0500 → 503 `execution_evidence_incomplete` + `binding_evidence_persisted=false` + `task_executed=yes`（sleep 8 rc=0，E11m2）；B：chmod audit.jsonl 0400 → 503 同码但 `binding_evidence_persisted=true`（审计单独失败，E11n3）；C：提交前 chmod → 503 `task_plan_not_persisted` + `task_executed=false`（plan 分支，未启动即拒绝，E11o3）。所有 chmod 在各变体 finally 恢复，先于 E09 的同状态目录重启。

## 修正关系与限制

- 驱动新增真实 `--only <腿前缀>` 过滤（迭代用），并把 restore 路径加固为「写落盘由读回判定、--wait 本地超时不致命」——迭代中实测到 `--wait` exit 124 但写入已落的真实分裂；恢复前先轮询排空在途 revision（实测：加载进行中再提交新写会卡住加载器，单个新 update 可解除）。
- E04/E06 矩阵行由 partial 升为 pass（各自子项全 pass）。E11 行保持 partial：E11k 存储故障已 pass，但 E11i（timeout 上报）仍是既有 partial —— 远端真实 `failed` 状态而非 `timed_out`/`execution_uncertain` 标签，本批不改该口径。
- E08 保持 partial / E08h blocked：v0.0.83 无单任务远端停止协议（依据 `v6-integration-20260917-153208/f02-stop-capability.md`）。E05g（跨进程 exactly-once）、E09q（进程内崩溃点/时钟注入；存储故障部分由本批 E11m/n/o 部分补强）、E10c（漂移拒绝形态为 instance_unconfirmed 而非 execution_refused）、E13d（绑定检查未到达）保持原判据。
- E12 真实浏览器 12 子检查同候选通过，但不转移到其他 OS/宿主。本批只证明本机 Linux + 该固定候选。

## 资源与清理

沙箱 `siq-v6-f04-e04e06e11-20260917` 为本批独占创建（本地固定镜像 `siq/hermes-openshell-siq-analysis:f470321d2fb2b2cda14b7c3b`），用毕按精确名称删除并只读复查不存在；共享 gateway 未重启、未改配置；其他沙箱（siq-analysis-canary-a01b02c91503、siq-l01-o05-181930、siq-o05v6-taskexec-002524）未动。本批 daemon/驱动进程全部退出，迭代临时目录（/tmp/siq-v6-*）删除。明细与清理证据见 [resources.json](resources.json)。私有材料（原始流量、候选副本）在 0700 的 `d05-private/`，公开区无配对码/私钥。
