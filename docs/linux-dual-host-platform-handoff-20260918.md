# Linux 双宿主批次的平台影响与复测交接

更新：2026-09-19。本交接对应 [LX00–LX10 任务书](linux-dual-host-integration-development-taskbook-20260918-205119.md)与[实时进度](linux-dual-host-progress-20260918.md)，不是 Windows/macOS 验收报告。当前工作分支 `codex/linux-dual-host-20260918` 基于 `main@2187fea`，所有本批结果仍为本地未合并候选；合并后以实际主线 SHA 和最终补丁重新核对。

## 1. 当前候选的可转移内容

| 变更 | 影响范围 | 协作者应核对 |
| --- | --- | --- |
| Linux `client-install` 在可信发行校验后、暂存前准备持久 signing seed；拒绝仅靠安装 shell 环境变量提供的临时 seed | `apps/agentshield/cmd/agentshield/client_install.go`；目前只由 Linux 安装入口调用，底层 signing 代码未改 | macOS LaunchAgent、Windows Task Scheduler 的首次安装/重启仍应各自检查身份与状态；不能把 Linux systemd 15/15 当作两平台通过。若共享签名行为出现差异，以本机规格和各平台负向测试说明。 |
| 文件 Grant 的符号链接越界修复：Unix 决策同时校验词法及已存在前缀解析后的实际路径；显式 deny 对别名仍生效；链接加 `..` 的歧义路径拒绝 | `internal/receipt/resource_scope.go`、`internal/runtimeaction/resources.go` 及对应测试；共享 Go 核心，Linux 实机复现与验证 | **需 macOS/Windows 各自重建候选并复测**：macOS 系统根别名、Windows junction/reparse point 与 UNC/盘符规范化均不能由 Linux 结果替代。Windows 当前保持原词法分支，不能声称符号链接越界已修复；在补齐原生路径合同前，对可能被重新解析的宿主路径维持受控启动/宿主隔离及诚实能力标注。决策后换链的竞态仍须宿主级原子约束。 |
| OpenClaw 审批集成驱动可固定 SIQ 二进制并验证使用摘要；报告创建即为 0600 | `scripts/validate-openclaw-approval-integration.py`；验收工具，不改变宿主适配器与产品授权逻辑 | 在目标 OS 使用该 OS 构建的二进制和实际宿主版本；分别记录原版能力检查点、隔离补丁副本与真实安装宿主的结果。当前 Linux 原版 2026.5.12 缺检查点，hold 安全拒绝；不能从补丁副本的 18 个场景推断原版可执行。 |
| Linux R07 驱动以 `umask 077` 创建结果，保留了真实慢响应和完整旅程记录 | `scripts/personal-experience/r07-linux-user-journey-smoke.py`；Linux 验收工具 | Windows/macOS 不复用 systemd、Linux 路径和端口结论。采用各自平台合同与测试驱动，检查失败产物初始权限、恢复后旧会话失效、回执连续、宿主原配置无漂移。 |
| 本地 Web API 与页面把请求、配对、注销和状态重载绑定到会话世代；旧会话迟到的 401/成功结果不能覆盖新配对，同一轮重复配对只发一次请求 | `apps/web/src/local/api.ts`、`App.tsx`、对应测试及重新生成的 `apps/agentshield/internal/ui/embedded/`；所有桌面平台共用本地界面 | Windows/macOS 合入后分别用实际后台生命周期复测“旧请求在途 → 重启/重新配对 → 旧响应迟到”、重复提交和注销；不能只用静态构建或 Linux Chromium 2/2 结果替代。若平台壳层缓存了旧内嵌资源，还须核对实际服务返回的新资源摘要。 |
| OpenShell 性能驱动新增显式基线标记，避免把已拥有任务执行路由的 `2187fea` 误写为“不可比较” | `scripts/personal-experience/openshell-o05v6-taskexec-perf.py`；只改变本批报告口径 | 仅在有真实 OpenShell 目标时按预冻结协议测；构建成功不证明网关策略、任务执行或远端停止。当前 Linux 功能矩阵 13 项 10 pass/3 partial，性能独立记账。 |
| 已安装 Skill 的 `approved` 且 `adm-si-` 保留准入 Grant，在当前可信 Intent 明确选中时可进入待确认；未选中、撤销或换绑时仍不可批准 | `internal/receipt/confirmations.go` 与负向测试；共享 Go 核心，第五代暂存候选 | macOS/Windows 各自重建并测已安装 Skill 的 hold→收件箱→批准/拒绝、更新后旧 hold 不可用及签名回执。只测 API/页面不等于原生宿主已消费批准；宿主没有审批后检查点时保持 fail-closed。 |
| 已批准 hold 的执行复查从当前服务端验证的 SEC 重建 Skill 归属和调用绑定；SEC 缺失、撤销、换上下文或内容变化继续拒绝，不复用客户端声明或旧回执 | `internal/receipt/confirmations.go`、`hold_status.go`、`skill_context_sec_test.go` 及相关负向测试；共享 Go 核心，第六代候选 | 两平台必须分别复测已安装 Skill “hold → 批准 → 同参数消费一次”、撤权、换绑、更新后旧批准、参数/对象漂移和重放。审批 UI 显示 approved 不能代替宿主实际效果与零效果见证；若真实宿主没有最终执行检查点，仍须安全拒绝。 |
| 隔离 PostgreSQL + RS256/JWKS 验收驱动 | `scripts/personal-experience/control-api-postgres-oidc-smoke.py`；不改企业产品 API/合同 | 当前 27/27 只证明本机生产配置形态，含本地 JWKS 轮换、过期与故障拒绝；不涉及客户身份提供方、生产数据库备份与 HA，也不列入个人 OS 的实机通过数。 |

Linux **当前第六代修复验收候选**的未签名 arm64 二进制 SHA256 为 `67bc48c4f751f9f6334295b78346e1290bd6f9d1d4e02a8695ca1ef26eb43428`，931 文件源绑定为 `63643d40fc503dc524f2d8b9f5fc0eb8cac6726d944d7780085a16f0c2045aa0`；见[第六代候选身份](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-sec-hold-fix-provisional.json)。同源测试发行已通过 B02 16/16、已装 R07 31/31、直启 R07 30/30 和两条嵌套 R04 31/31；真实 OpenShell D05 为 373 步 365 pass/7 partial/1 blocked/0 fail，B3 功能旅程 57/57。Hermes 浏览器确认 24/24；OpenClaw 2026.9.4 隔离受控副本审批 18/18、产品托管公共 CLI 22/22，但原版 2026.5.12 和 2026.9.4 都没有 SIQ 所需的审批后执行复查合同。第六代 B2/S1–S4 性能仍是[测前冻结、未采样](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-perf-plan.json)，不是发行就绪。

第五代 `6ce92b69…` 及其[候选记录](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-confirmation-fix-provisional.json)保留为独立历史对照，不向第六代迁移结果。第四代 `a13d6234…` 及其[候选记录](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-root-scope-final.json)曾承载补充的 12 小时管理员自然到期腿；项目负责人已在期限前取消该腿并完成精确资源清理，状态为 `out_of_scope`，没有到期通过结果，也不得向后续候选转移。

这些摘要只用于**本批 Linux 证据**，不能当作 macOS/Windows 构建或实机结果。交叉构建仅证明可编译；Windows 当前仍保留词法路径分支，原生 junction/reparse point 越权验收是安全门禁。根路径 `/` Grant 的兼容性回归已在第四代修复；协作者合入共享修复后应分别检查根路径允许、显式拒绝与具体对象越权。

## 2. 各平台保持的职责

- Luke 的 macOS 范围为 OpenClaw、Hermes、WorkBuddy；已有阶段成果按其原候选有效，合入当前修复后需新候选同源复测。LaunchAgent 的标签、启动、停止、重启、卸载及用户目录权限应在 macOS 实机确认。
- sunbo 的 Windows 范围为 OpenClaw、Hermes、WorkBuddy，开发仍在进行，部分分支已推送；原生和 WSL2 分列。当前 Linux 批次不读取或改写其工作树，也不把尚未完成的适配提前合并。
- 本机 Linux 只交付 OpenClaw 与 Hermes。Linux/WorkBuddy 为产品范围外；CodeBuddy 新接入和新任务全平台取消，历史记录的安全查看、拒绝、撤销及卸载兼容保留。不得用旧 CodeBuddy 行替代 WorkBuddy 证据。

## 3. 复测单元和可接受证据

每个平台的每个真实宿主至少独立记录：候选源码与二进制摘要、宿主准确版本和安装形态、OS/架构、原生或受控启动方式、配置前后摘要、权限确认、允许动作实际效果、越权动作零效果、批准后一次消费、重放/撤权/参数漂移拒绝、回执链验签、更新取消/确认/回滚、浏览器与后台生命周期。没有宿主检查点或系统 API 时，记录 **blocked**、可观察拒绝和解除条件；不要模拟成功结果。人工通知视觉与 headless 浏览器/API 分开记录。正式发行签名、安装公证及客户环境仍是独立门禁。

验收报告区分：组件级、真实宿主、真实网关、测试签名安装、正式发行。失败轮保留原样；每批公开证据应含候选/驱动绑定、检查数量、环境与资源清理、SHA256 清单和限制，私有日志/配对码/密钥留在被忽略且权限受限的目录。Linux [证据目录](evidence/personal-experience/linux-dual-host-20260918-211200/)可作字段示例，但不可复制其状态为其他 OS 的结论。

## 4. 合并前冲突检查

本批产品源码除 Linux `client-install` 外，现还改动共享文件资源判定、规范化路径、已批准 SEC 复查和本地 Web 会话世代；这些内容**不可**按 Linux 专用修复合并后直接宣称 macOS/Windows 安全覆盖。审阅协作者 PR 时，先用 `git diff --name-only` 确认是否碰到 `internal/signing`、`internal/state`、`internal/receipt/resource_scope.go`、`internal/receipt/confirmations.go`、`internal/receipt/hold_status.go`、`internal/runtimeaction/resources.go`、Grant/SEC/审批回执、`client_install.go`、`apps/web/src/local/api.ts`、`apps/web/src/local/App.tsx` 或内嵌 UI。若触及同一授权语义或会话生命周期，先合并合同和不变量，再以各平台独立负向复测；不能靠文本冲突解决就宣称安全语义兼容。PR #68 是 Cursor 云端开发环境分支，用户明确要求不要合并。
