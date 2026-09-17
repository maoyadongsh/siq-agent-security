# 发行候选准备＋真实 OpenShell 环境预检 — 执行计划与基线清单

- 任务批次：release-openshell-20260916-142706
- 执行人：glm（独立 worktree，不接触其他开发者工作树）
- 落盘时间：2026-09-16 14:27–15:0x (本地)
- 状态词约定：done / partial / blocked / conditional / external_manual

## 0. 本批范围（对应任务书）

**做**：
1. 发行候选准备：复用既有 release-manifest / manifest-verify / client-install / upgrade / rollback 流程，冻结候选来源绑定（commit、工具版本、产物摘要、嵌入信任根、脚本版本、已知缺口），完成 4 目标构建（linux/amd64、linux/arm64、darwin/arm64、windows/amd64）。
2. 真实 OpenShell 环境预检：以 client_expressible → documented → configured → handshake_verified → readback_verified → enforcement_verified 六级证据阶梯逐项核实 B2/B3/O05 的可执行条件。
3. 条件满足时执行 B2/B3 真实网关性能测量与 O05 真实后端会话验证；被预检证实未满足条件时，如实记录 blocked 与解锁条件。

**不做**（任务书硬边界）：
- 不做 T01–T06 团队功能；不改 N09 阈值；不接管 sunbo（Windows）/Luke（macOS）的工作，其未交付环境不得标记 passed。
- 不修改生产信任根以接受测试制品；不临时生成种子冒充正式发行密钥；不搜索/读取/导出维护者私钥；不得把私钥经 argv、环境日志、报告或仓库文件传递；不为跑绿绕过清单验签。
- 不 commit、push、merge、创建 Release、上传制品或修改 GitHub 设置；本批仅本地落盘。
- 不终止、重启或修改归属不明的既有服务；不因端口有监听、gateway info 或版本命令成功就认定服务在线。

## 1. 源码与分支基线

| 项 | 值 | 核实方式 |
|---|---|---|
| 基线 commit | `052c81617438d1eabf94a5e0166338312366c491` | origin/main HEAD = PR #65 合并点；merge-base 复核 main 未前移 |
| 我的 worktree | `/home/maoyd/siq/worktrees/siq-release-openshell-20260916-142706` | `git worktree list` |
| 我的分支 | `glm/release-openshell-readiness-20260916-142706` | 从 origin/main 新建 |
| 主仓状态 | `codex/personal-macos-stop-recovery` 有大量未提交改动（协作者活动） | 已确认不触碰 |
| 本 worktree 源码改动 | 无（候选=干净 052c816 产物；本批新增 doc/evidence 为 untracked，另行登记） | `git status` |

## 2. 任务相关状态基线（v5 任务书 §20 + 复盘文档修正）

| 批次 | 现状 | 本批动作 |
|---|---|---|
| B01 生命周期 | partial（test_release 层已过；正式签名腿 blocked） | 用干净候选重跑 lifecycle runner（test_release 层），产物绑定候选摘要 |
| B02 已安装旅程 | partial（r3 已过；HOME 隔离修复在源） | 条件性用新候选重跑（需 playwright 解释器） |
| B03 并发/状态兼容 | partial | 条件性；依赖真实网关预检结果 |
| B07 性能 | partial（diagnose_unconfigured p95 0.022ms 超阈值 15.79%，按失败记账未调阈值） | 不重跑测量（无新性能相关源改动则不虚耗）；记录沿用 |
| B08/O05 OpenShell 会话 | conditional | 预检→条件执行 |
| 正式签名 | blocked：`SIQ_AGENT_SECURITY_RELEASE_SEED` 未设置，仅维护者持有 | 产出候选+摘要+签名输入+验证命令+维护者签发指引；信任腿保持 blocked |
| B09 | external_manual | 不变 |

## 3. 机器与工具链基线

| 项 | 值 |
|---|---|
| 主机 / 平台 | spark-1319，linux/arm64 (aarch64)，内核 6.17.0-1014-nvidia |
| Go | 1.26.5（`apps/agentshield` 4 目标交叉构建 CGO_ENABLED=0） |
| Python | 3.13.12（默认 `python3`）；playwright 可用解释器：`/home/maoyd/report-finder-service/.venv/bin/python3`（已验证 import）；ruff 0.14.10（`/home/maoyd/.local/bin/ruff`） |
| Node | v22.22.2 |
| systemd --user | 可用（状态 degraded 但单元操作正常） |
| Docker | 29.1.3 可用（OpenShell docker driver 依赖项之一） |
| 磁盘 | / 剩余 1.7T |

## 4. 既有服务与端口归属（不采纳为验收环境的除外）

| 端口 | 进程 | 归属 | 本批处置 |
|---|---|---|---|
| 17671 (TLS) / 17672 (health) | openshell-gateway PID 4009810（2026-09-15 12:06 由 maoyd 启动，siq-research-engine 工具链 v0.0.83） | 项目隔离网关 siq-openshell-dev，O01/O02 批次用户明确授权启动（docs/evidence/personal-experience/openshell-o01-o02-20260915/report.md:25） | 预检对象：只读探测（health GET、CLI status/doctor），不重启不改配置；行为级使用需预检验明身份/策略 |
| 8016 | python3 PID 2687（本地统一路由器） | 与本批无关 | 不采纳为验收环境 |
| 18789 | 无监听 | `~/.config/openshell/active_gateway` = "nemoclaw" 指向的死端点 | 记为 configured_unreachable（如实） |
| 25283 等 | 此前 B02 测试残留可能性 | 本批自建临时实例 | 测量前自查端口占用 |

## 5. OpenShell 环境基线（预检输入）

| 项 | 值 | 证据等级 |
|---|---|---|
| CLI | `~/.local/bin/openshell` 0.0.13（`--version` 可执行） | client_expressible |
| CLI 默认配置 | `~/.config/openshell` active gateway = nemoclaw → https://127.0.0.1:18789（死端点） | configured（错误目标） |
| 项目网关配置 | `/home/maoyd/siq-research-engine/var/openshell/xdg/config/openshell/gateways/siq-openshell-dev/metadata.json`：endpoint https://127.0.0.1:17671 | documented（文件存在+字段读取，脱敏） |
| 网关配置 | gateway.toml：bind 17671、health 17672、mTLS require_client_auth=true、gateway_jwt ttl 3600、docker driver、sandbox_namespace siq-openshell-dev、镜像 ghcr.io/nvidia/openshell/sandbox:0.0.83 | documented |
| 运行中网关 | siq-openshell-dev（0.0.83），17671/17672 监听中 | documented+进程归属核实；handshake 待预检 |
| 预检方法 | 经 `XDG_CONFIG_HOME=<siq-research-engine XDG>` 或 `--gateway-endpoint` 使 CLI 指向 17671；只读命令（status/doctor/health）；mTLS 客户端证书存在性→握手→策略读取逐级上升 | — |

## 6. 发行物料基线

| 项 | 值 |
|---|---|
| 嵌入信任根 | `skillmanifest.ReleasePublicKeyB64` v1（随 052c816 源码固定） |
| 官方种子 | 环境未设置 `SIQ_AGENT_SECURITY_RELEASE_SEED` → 官方信任腿 blocked（不得生成替代种子冒充） |
| test_release 层 | 每次运行新生成测试种子 + 测试公钥注入独立测试构建（fail-closed 单密钥 pin），runner：`scripts/personal-experience/closure-b01-lifecycle-runner.py` |
| 负向回归要求 | 测试签名清单必须在官方 manifest-verify 下失败（单密钥 pin 验证） |

## 7. 阶段计划

### 阶段 A：候选构建与冻结（本计划批准后立即开始）
1. 从干净 052c816 构建 4 目标（linux/amd64、linux/arm64、darwin/arm64、windows/amd64，CGO_ENABLED=0，trimpath+ldflags 版本注入）。
2. 生成 SHA256SUMS；逐产物核对版本字符串与 GOOS/GOARCH。
3. 制品安全自查：无测试私钥/管理令牌/个人状态目录路径嵌入。
4. 负向回归：测试种子签名的清单在官方 `manifest-verify` 必须失败；Linux 候选保留 HOME 隔离与审批预留修复的既有回归测试全绿。
5. 产出维护者签发指引（签名输入、命令、验证命令）；官方信任腿标记 blocked。
6. （条件）B01 lifecycle runner + B02 journey runner 以 test_release 层重跑，核实 runner 确实执行指定候选（摘要绑定断言）。

### 阶段 B：OpenShell 真实环境预检（与阶段 A 可并行的只读探测）
1. 结构化预检：CLI 可执行性、配置完整性、网络可达、身份/握手、策略可读、测试资源、行为验证可能性，逐项打证据等级。
2. 输出 `docs/openshell-real-environment-readiness-<ts>.md`：即使后端不可用也交付（就绪工具改进、缺口清单、即用命令、fail-closed 回归、拒绝既有端口/进程为验收环境的理由）。
3. 预检判定 B2/B3/O05 是否满足任务书前置条件；满足才进入阶段 C。

### 阶段 C（条件）：真实环境验收
- B2/B3 真实网关性能测量（冻结协议：测量期间无并行构建/测试、不删慢样本、事后不放宽阈值、不重跑择优）+ O05 真实后端会话验证（effective 权限只能来自后端读回；审批≠执行需 hold_reservation；预留响应丢失按不确定处理）。D 场景约 94.5 分钟，仅在条件满足时排程。

### 阶段 D：验证门与收尾
1. gofmt、`go vet ./...`、`go test ./...`、受影响模块 `-race`、4 目标交叉构建；触改 Python 脚本则 ruff+相关测试。
2. 证据目录落盘（schema_version、task_id/phase、时间/OS/arch、来源 commit、候选摘要、实际检查、退出码、未执行项及原因、解锁条件、脱敏引用、SHA256SUMS）。
3. 更新任务书状态/交接文档/操作指南；最终报告 6 自足小节；资源清理（清理前后复核归属）。

## 8. 基线证据

见 `docs/evidence/personal-experience/release-openshell-20260916-142706/baseline/`（environment.json + report.md + SHA256SUMS）。
