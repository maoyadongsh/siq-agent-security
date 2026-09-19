# 仓库调整最终补充验收（2026-09-19）

## Skill 源码入口

[CI 回读](skill-source-ci.json)固定 PR #97 的源码 head `bf7dcedddb00a6ef2ff359bd9a8e6ceb2b07e85c` 和实际工作流。每个原生报告另记 GitHub PR merge 检出的完整 SHA、实际程序和 Skill 正文摘要，不能将 PR head 冒称为执行检出身份。

| 原生目标 | 公开报告 | 实际范围 |
| --- | --- | --- |
| Linux amd64 | [记录](skill-source-linux-amd64.json) | 自建程序自扫描；缺 manifest 拒绝且无状态/暂存写入；空状态 start 与 init→serve 的 status/pair/控制台/停止 |
| Linux arm64 | [记录](skill-source-linux-arm64.json) | 同上，原生 ARM64 runner |
| macOS arm64 | [记录](skill-source-darwin-arm64.json) | 同上，不注册 LaunchAgent、不代表 Apple 公证或桌面宿主验收 |
| Windows amd64 | [记录](skill-source-windows-amd64.json) | 同上，PowerShell 缺清单拒绝，不注册任务、不代表 Authenticode 或桌面宿主验收 |

四目标报告的源码树均记录 clean、Skill 正文摘要一致。另有 Ubuntu/macOS 的既有 pinned CLI 复制安装/移除检查成功。托管源码检查不产生新的官方签名包，不改 0.3.0 的原生安装范围，不证明完整升级、系统服务或 OpenClaw/Hermes/WorkBuddy 验收。首次源码说明候选也完成了四目标运行，最终只以本目录记录的 head 为本批归档身份。

本机额外执行原 Skill evals：5 项准入案例通过、2 项 routing 案例按原执行器跳过；36 项分发工具测试与 Go skillmanifest 包通过。原始秘密状态、服务输出及配对码未上传。

## ZIP 预检完善

复核发现单点路径 `.` 会触发未捕获的索引错误，控制字符文件名及文件/目录冲突也应在写入前拒绝。已修正并扩展现有负向语料；15 项发行工具测试和 Ruff 通过。[工具候选摘要](zip-preflight-candidate.json)固定提交前的实际文件，[正式 0.3.0 离线复验](release-offline-verification.json)通过。本次未重签、改包或重跑原生安装，不覆盖[之前的工具与原生记录](../repository-reorganization-20260919/README.md)。

整体恢复演练仍见[固定候选记录](../repository-reorganization-closure-20260919/README.md)；后续索引/Skill 修订分别通过 PR #96/#97 的相应检查。本目录追加记录不回写旧的 8 条目录/候选计数或实验结果。[实施台账](../../development/reorganization-progress.md)维护最终范围与集成入口。
