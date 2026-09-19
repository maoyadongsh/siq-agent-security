# v6 阶段提交与分支审查（2026-09-17）

用户已授权提交、推送并按阶段合并。审查基线 origin/main 为 9b8c09a；本机集成树 codex/personal-v6-integration-20260917。

## 提交范围

1. 产品实现、版本化合同、UI 与组件测试：OpenShell 已审批任务绑定/持久化/状态读回、安全失败路径，平台范围收紧。Linux 仅 OpenClaw/Hermes；Windows/macOS WorkBuddy 保持各自实测边界。
2. 验收驱动、离线守卫、公开证据及阶段文档：保留失败/partial/blocked，原始私有资料不入库，不宣称正式发行或完整验收。

验证已执行：Go vet/test 全量、openshell/server race、四平台 CGO=0 构建；Python 全量 pytest 与 app Ruff；Web 115 项测试及两种构建；脚本 44 项 unittest；127 项公开证据清单哈希匹配。R07 驱动既有 21 处长行不声称 lint 全绿，其余规则通过。产品 source binding 仍为 ba8d266ef5ba861282f23a8576be8744d6023118f3f42efd8e1054632ffe06fc（931 文件）。

## 远端批次选择

- PR #72：只新增 Windows 历史候选的 OpenClaw WSL2 与 WorkBuddy 基础证据，CI 通过；明确不等于 Windows 原生 OpenClaw 或 WorkBuddy SIQ 保护验收。适合阶段合并。
- PR #73/#74：Windows 功能修复仍为 draft，保持协作者开发状态。
- PR #71：实验叙述未附可复核的冻结候选与原始证据索引；百分比仅为五个固定案例结果，暂缓纳入验收基线。
- 旧 Windows 分支有落后或冲突；本批不以覆盖方式消除差异，不删除协作者分支。macOS 已集成分支无新增独有提交，不重复合并。

## 分支差异快照

下表仅列存在 main 未包含提交的分支；其余本地/远端引用均为 main 已包含的历史。工作树中的未提交改动不由此表代表。

| 分支 | 独有提交 | 落后 main |
| --- | ---: | ---: |
| `origin/codex/experiment-report-20260917` | 1 | 0 |
| `origin/codex/windows-adapters-json-test-20260914` | 2 | 54 |
| `origin/codex/windows-connector-discovery-20260914` | 2 | 54 |
| `origin/codex/windows-filesystem-evidence-20260914` | 1 | 61 |
| `origin/codex/windows-hermes-a9-20260914` | 1 | 54 |
| `origin/codex/windows-hermes-test-20260914` | 3 | 54 |
| `origin/codex/windows-hermes-write-control-20260914` | 2 | 54 |
| `origin/codex/windows-host-evidence-20260914` | 1 | 54 |
| `origin/codex/windows-host-runtime-evidence-20260917` | 3 | 0 |
| `origin/codex/windows-openclaw-debug-20260914` | 5 | 54 |
| `origin/codex/windows-p04-file-lock-20260915` | 1 | 54 |
| `origin/codex/windows-resource-binding-20260916` | 2 | 54 |
| `origin/codex/windows-schema-test-entry-20260915` | 2 | 54 |
| `origin/codex/windows-skill-journey-20260914` | 1 | 54 |
| `origin/codex/windows-stage-executable-20260917` | 2 | 0 |
| `origin/codex/windows-state-path-alias-20260914` | 2 | 54 |
| `origin/codex/windows-task-bootstrap-20260917` | 1 | 0 |
| `origin/codex/windows-unmarked-migration-20260915` | 1 | 54 |
| `origin/cursor/setup-dev-environment-fdee` | 1 | 44 |

合并遵守远端必需检查与代码所有者审核，不修改保护规则。剩余上游原子执行/远端停止、生产身份、真实源网络与协作者实机等门禁仍按任务书保留。
