# v6 平台范围收口：本机 Linux 与全平台 CodeBuddy

日期：2026-09-17。用户确定本机 Linux 仅以 OpenClaw、Hermes 为当前交付目标，Linux/WorkBuddy 不再排期；CodeBuddy 的新接入和后续适配任务全平台取消。macOS 仍为 OpenClaw、Hermes、WorkBuddy（Luke 已阶段性推送，WorkBuddy 阶段性完成）；Windows 同三宿主（sunbo 持续开发，仅部分分支已推送）。协作者状态来自用户说明与本地远端跟踪分支，不能替代同候选实机验收。

## 本候选行为

- Linux 管理 API、CLI、嵌入控制台拒绝 WorkBuddy 新安装；所有 OS 拒绝 CodeBuddy 新安装。自动安装过滤已退出范围的平台。旧配置可只读查看、诊断、外科卸载。
- HTTP/CLI 拒绝新 CodeBuddy Grant，HTTP 不允许历史 CodeBuddy 草稿再挑战或批准；历史 Grant 可读取、拒绝或撤销。保留旧 hook 的失败关闭路径和历史回执格式，不伪装成当前支持。
- 原有九格 N09 矩阵保持历史结构，Linux/WorkBuddy 仅在新 v2 矩阵中可作整格 `out_of_scope`，不计通过。CodeBuddy 不在此三宿主矩阵中。

## 验证和修复记录

- `go vet ./...`、`go test ./...` 通过；`go test -race ./internal/adapterinstall ./internal/server` 通过。服务端负例覆盖安装预览、直接安装、新 Grant 与历史待激活 Grant 的拒绝，且旧配置可卸载、旧 Grant 可读取/拒绝。
- Python 两份诊断合同样例检查与 Ruff 通过；Web 26 文件、115 项测试通过。`npm run build:local` 重建嵌入页面，四目标 CGO=0 构建成功。
- 隔离 HOME/状态目录的 Linux/arm64 CLI 5/5 新接入与 Grant 负例通过，未创建 WorkBuddy/CodeBuddy 宿主配置；临时目录已清理。
- 真实 Chromium × 隔离 daemon 的嵌入控制台检查 `/settings`、`/bindings` 两页：两平台均显示当前范围说明且均无安装按钮。首轮浏览器脚本因 Playwright 缓存随隔离 HOME 重定向而无法启动；修复脚本后又发现嵌入前端仍为旧产物，重建并重新编译本候选后复测通过。失败样本未计产品通过。
- 源绑定复用 `openshell-b2b3-perf-protocol.py` 的 `source_binding` 计算，覆盖 931 个 Go、go.mod 与嵌入文件；见 [`candidate.json`](candidate.json)。本地脏树绑定不是正式签名或可重现发行提交。

## 候选与未完成门槛

本次最终 Linux/arm64 二进制 SHA256 为 `ac447ac92e65997952dc5a19ead7a83a8512924948a43f986d7f0d66aa0366ff6`。F01 真实网关 D05 229/0 与 F05 性能 150 样本属于此前 `ceddc59c…` 候选，**不能迁移为此二进制的验收**。本候选完成范围门禁、组件、CLI、浏览器与交叉构建验证；尚未重跑同候选 D05、OpenClaw/Hermes 完整原生旅程与性能。准备 D05 时只读发现当前 PATH 中 `openshell --version` 为 0.0.13，而上一实测候选记录 CLI 0.0.83；原私有 mTLS 环境脚本也未在本批可用位置找到。故未用不一致的 CLI 和共享网关硬跑并声称同候选通过。Darwin/Windows 交叉构建不替代 Luke/sunbo 实机验证。未提交、未推送、未合并、未签名、未发布。
