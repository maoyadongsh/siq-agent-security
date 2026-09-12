# KIMI-002-NATIVE 交接：真实平台能力与生命周期假设验证

```text
任务：KIMI-002-NATIVE（UX-001/UX-002 接续，非 KIMI-001 补修）
状态：ready_for_review（含义：本批可执行探测与材料已完成；不是所有目标原生通过）
基线 main：1e20635843c0966e24d73d149e3d7bcd080f89c4
分支：codex/personal-k002-platform-readiness
执行候选 SHA：32b086ec18e15ead1e4c39a076e0863a22e5ccf2（本批新增脚本后的提交点）
候选二进制 sha256：897ec40be05cf60a2c8235457106bf79f3d8f0797dc657149a9057531fce9307
最终分支 HEAD：见本批最后一个 docs 提交（SHA 在最终回复给出）
```

## 预检与基线保护

开工时工作区仅余 R1-B1 留下的未跟踪 `artifacts/`（本地基准产物，已移至 /tmp 保持树干净，未删除他人内容）；分支按远端安全检出，HEAD 与参考 2d23cae 一致。审阅方已提交的工具/合同/测试/CI 未重复实现。审阅方交接后本批验证增量由 Kimi 主写。

## 本批新增（两个隔离验证脚本 + 文档/证据）

- `scripts/personal-experience/discovery-native-smoke.py`：发现探针（下述）。
- `scripts/personal-experience/hermes-approval-gap-native-smoke.py`：Hermes 批准边界探针（下述）。
- `scripts/personal-experience/README.md`：登记两个探针的用法与边界。
- `docs/k002-native-lifecycle-findings.md`：生命周期假设验证发现。
- `docs/evidence/personal-experience/kimicode-k002-native-20260912/`：矩阵、11 份证据文件、verify 与 --require-native 报告。
- 未改动任何产品代码、合同、工作流、历史证据。

## 逐项结果（linux/arm64 真实探测；其余组合 blocked）

八项能力 × 三平台矩阵见 `platform-matrix.json` + 两份 verification 报告。关键结果：

**OpenClaw 2026.5.12（f066dd2）/ Ubuntu 24.04.4 LTS arm64 / native**：
- 通过（native_cli）：normal_execution、pre_execution_denial、service_unavailable_denial（kill daemon 后 fail-closed 且 pending 记录）、approval_resume、final_parameter_recheck（`validate-openclaw-approval-integration.py` 18 案全过：含批准后参数变更不执行、撤销不执行、超时/取消/离线不执行；stock 未打补丁运行时的 hold 安全 fail-closed 亦实证）。
- 通过（component_fixture）：discovery（隔离双实例 + 合成 Skill 被发现且身份/版本分开；正文与未登记私人目录内容不进入任何响应）。
- 缺口：skill_attribution 按行内三条标准（可核验宿主上下文、自报不能取权、未知保持未知）在实例/会话级通过 native_cli 验证；**Skill 版本级可信归属仍缺**（ADR-025/0048 既有缺口，不掩饰）。install_interception blocked/not_implemented（OpenClaw 原生安装入口无前置拦截，SIQ 发现为事后盘点；SIQ 自有安装路径不是宿主拦截）。
- 实证发现的既有工具漂移（不属于本批修复范围）：`validate-intent-v2-openclaw-approval*.py` 三个旧脚本在当前适配器下因缺 `approvalExecutionRecheckVersion=1` 的宿主上下文而确定性 fail-closed（worker 超时）；`validate-openclaw-approval-recheck-patch.py` 的适配器钉住摘要自 d860bdf 起与提交内容不符（历史失配）。当前有效入口是 approval-integration 脚本。旧证据不改写。

**Hermes Agent 0.21.0（2026.8.31）/ 同机**：
- 通过（native_cli）：normal_execution、pre_execution_denial、service_unavailable_denial（kill 后 fail-closed + pending）、skill_attribution（实例凭据绑定；环境变量不能覆盖受管实例；撤销后新会话全拒；未绑定会话拒绝）。
- 通过（component_fixture）：discovery（同一探针覆盖 Hermes 双 profile）。
- 缺口（探针实测，非推测）：approval_resume blocked/host_capability_missing——Hermes 无原生批准通道，hold 按设计降级 block；控制台批准被记录，但适配器不调 hold-status，相同参数重试仍被拒绝、文件全程未写（`hermes-approval-gap.json`，11 项检查）。final_parameter_recheck 同因 blocked（宿主路径不可达批准恢复，daemon 侧参数摘要复核存在但 Hermes 未接线）。
- install_interception blocked/not_implemented（同 OpenClaw 理由，证据 `install-interception-hermes.txt`）。

**WorkBuddy（用户已确认无 Linux 版本）**：
- 全部 6 组合 blocked。Linux 行 upstream_runtime_unconfirmed（官方资料无 Linux 运行形态，用户确认无 Linux 版本）；Windows/macOS 行 environment_unavailable（本机无对应桌面环境）。官方资料核查（2026-09-12 访问）见 `workbuddy-upstream-review.txt`：安装指南仅 Windows 10+/macOS 12+；插件页仅宣称 Hooks「在特定时机自动执行」，无可用的前置阻断合同公开证据；CodeBuddy CLI hooks 文档仅作对照，未外推。另：WorkBuddy 需账号登录且任务走云端模型，即使取得桌面环境也缺确定性无付费执行路径，须届时另行确认测试条件。
- WorkBuddy 明确不以 CodeBuddy 替代；网页/移动端不替代桌面目标。

**其他 OS/架构组合（openclaw/hermes × windows native、windows wsl2、macos arm64/amd64、linux amd64）**：全部 blocked/environment_unavailable（本机无相应环境；交叉编译与 CI 不冒充原生验收）。WSL2 行无 Windows 主系统，os_version/guest_version 均为 null（不猜测）。

## 生命周期假设验证（ADR-050）

见 `docs/k002-native-lifecycle-findings.md`。要点：Linux 用户级机制（systemd 用户服务 + XDG 自启动）本机可用（Linger=yes）；双启动写锁拒绝、优雅停止/重启状态完整、浏览器不耦合均实证；裸状态目录 serve 报 `runtime_identity_invalid`（安装器需生成初始配置）；`status` 不区分状态目录实例（ADR-050 §2 缺口实证）。Windows/macOS 机制缺环境保持未验证。

## 验证与命令（数值）

- 矩阵工具：`verify` exit 0（结构/摘要一致，11 个证据文件）；`--require-native` exit 3（如实：仍有缺口）。
- §7 回归：`test_platform_acceptance.py` 35 项 OK；`scripts/personal-experience/tests` 全套 39 项 OK；`ruff check` 工具与测试目录通过；本批两个新脚本 ruff 通过。注意：personal-experience 目录的既有脚本存在 25 项历史 lint（EXE001/BLE001/PLW1510），属既有状态，CI 不 lint 该目录，本批未扩大范围处理。
- 证据运行：10 项原生运行全部 exit 0（命令、候选、二进制摘要见各 JSON 内字段）。
- 未跑：control-api/Go 全量等（本批不改其产品面；以最终 PR CI 为准回填）。

## CI

推送后新 HEAD `90f9d16`（含全部代码与证据）实跑结果：

- ci run 34661065172：success
- runtime-security run 34661065169：success（nightly 按事件条件不运行，登记为条件性跳过）
- research run 34661065167：success
- personal-experience run 34661065181：success（三系统工具单测与合同、lint）
- pages：未触发——其 pull_request 触发带 paths 过滤（site/、apps/agentshield/、adapters/runtime/ 等），本批改动不在其路径内，属条件性不运行而非通过。

## 剩余产品决策（交审阅方）

1. Hermes 批准恢复通道：是否实现适配器侧 retry+hold-status 接线（本批证明其缺失）。
2. install_interception：两平台原生安装入口的前置拦截能力是否立项。
3. Skill 版本级可信归属（ADR-025/0048 持续跟踪）。
4. status 实例关联字段（新合同）与裸启动报错可读化。
5. WorkBuddy：仅在有真实 Windows/macOS 桌面与合规测试条件时推进 native_desktop 探测。
