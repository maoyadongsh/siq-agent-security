# macOS Luke：Mac-P05 材料矩阵与平台验收汇总

接续 [P04](../p04-20260916-144224/report.md)。本批按任务书 8.2 以 `platform_acceptance.py` 对本批全部工作生成 18 行材料矩阵，填写本机实际覆盖行并离线校验，退出码三态如实保留。**macOS 总体、N09 不关闭；硬件与宿主未覆盖项保持缺口。**

| 身份 | 实际值 |
| --- | --- |
| 候选 SHA | `5c2d11a734233328f62deb5ba4b32d9a2eabf522`（分支 `codex/macos-luke-p04-20260916-133816`，`git status` 干净） |
| 受测二进制 | darwin/arm64，SHA256 `afe47938ee0df834d885f8635fcfb6d636f670d27ecb9dae82fec2480b2af010`（P04 构建参数：`CGO_ENABLED=0`、`-trimpath`、go1.27.1 darwin/arm64 原生） |
| 本机环境 | macOS 26.6.2，Apple M4，`sysctl.proc_translated=0` |

## 矩阵结果

[manifest.json](manifest.json) 为填写后的 18 行清单；[structure-report.json](structure-report.json) 与 [native-report.json](native-report.json) 为校验输出。

| 行 | 结果 |
| --- | --- |
| openclaw/macos/arm64/native | **ready_for_review**：8/8 检查 `pass`，method `native_cli`，evidence 摘要校验通过 |
| hermes/macos/arm64/native | **ready_for_review**：8/8 检查 `pass`，同上 |
| workbuddy/macos/arm64/native | needs_native_evidence：8 项 `blocked`（reason `not_tested`）——WorkBuddy 桌面接入旅程未做（P02 仅盘点，任务书要求 `native_desktop` 方法且需真实桌面交互） |
| 其余 15 行（windows/linux/macos-amd64 各架构） | 保持模板默认 `not_run`/`not_tested`，不填 pass |

**退出码记录**：`verify`（无 require-native）= 0；`verify --require-native` = 3（缺原生覆盖，预期，不隐藏）；无效材料路径 = 2（曾因证据文件摘要与清单不符、证据跨行复用等真实触发并修正）。

## 检查到证据的映射（macos/arm64）

- discovery / normal_execution / pre_execution_denial / final_parameter_recheck / skill_attribution：[P04 OpenClaw 托管原生](../p04-20260916-144224/openclaw-managed-native.json)、[P02 OpenClaw 托管原生](../p02-20260916-000754/openclaw-managed-native.json)、[P04 Hermes CLI 运行时](../p04-20260916-144224/hermes-cli-runtime.json)、[P02 Hermes 托管原生](../p02-20260916-000754/hermes-managed-native.json)
- service_unavailable_denial：[P02 Hermes 失联](../p02-20260916-000754/hermes-intent-offline.json)（daemon 被杀后哨兵未执行、fail-closed、重启绑定恢复）
- approval_resume：[P04 审批收件箱](../p04-20260916-144224/confirmation-inbox-browser.json)、[P04 通知](../p04-20260916-144224/confirmation-notifications-browser.json)（一次性批准、重放冲突、断连恢复、陈旧批准客户端截止）
- install_interception：[P02 隔离安装/还原](../p02-20260916-000754/isolated-install-restore.json)（预览无副作用、卸载还原、未知文件保留）

证据合同注意：校验器拒绝同一证据文件（按内容摘要）跨 case 复用；跨行引用通过按行标注的独立副本解决，每份副本内容唯一并逐字节校验。副本仅用于矩阵引用，上表链接指向原始批次的同一实验记录。

## 8.1 开发检查汇总（本批多轮全绿）

- Go：`gofmt` 空、`go vet ./...` 过、`go test ./...` 39 包、race（state/stateformat/server/notify）
- web：vitest 84/84、`build`/`build:local` 无 tracked embed 变化
- control-api：schema contracts 206 passed
- N01/LaunchAgent/审批/Skill 各批次实机结果见对应批次报告

## 平台完成标准对照（任务书 §8）

- 已覆盖：macOS arm64 native 上 OpenClaw、Hermes 的 A01–A08 主链（发现→接入→允许→越权→失联→还原）+ 审批收件箱 + Skill 安装更新移除闭环；LaunchAgent 生命周期与 N01 迁移/恢复（P03）；macOS 通知默认路径与真实投递（P04）
- 保持缺口（不关闭）：WorkBuddy 桌面（native_desktop 未做）、macos/amd64 与 Intel 实机、Rosetta、Safari 旅程、notarization/正式签名、N09 总体、approval-gate worker 2026.9+ 插件运行时挂接、Hermes 宿主回调重试语义

## 清理

矩阵工作目录 `~/.local/siq-macos-luke-p05-evidence-20260916/` 为私有证据根，manifest 与报告已复制入本目录，原目录保留至 PR 合并后清理；测试状态目录、临时二进制与 venv 均已删除。
