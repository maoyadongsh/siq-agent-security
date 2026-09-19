# 当前开发入口

核查日期：2026-09-19。仓库调整启动基线为 `main@1173042`；整理工具首批为 `ea0024f`，后续固定候选及 PR 见 [RA 台账](reorganization-progress.md)。开始工作前以 `git fetch origin main`、`git status --short --branch` 和 `git rev-parse HEAD origin/main` 确认自己检出的身份；本页不是移动分支指针。正式客户端 `0.3.0` 的源码固定 `83fde2d`，研究源码版仍为 `aefab111`。

本页维护当前范围和下一动作，逐步执行日志仍由各原始台账维护。历史 `personal-experience-current.md` 的 v3/v4 入口与早期“未提交”状态不再是启动依据；平台阶段记录仍保留其证据作用。

| 工作范围 / 责任角色 | 有效任务与权威入口 | 当前实施 / 证据状态 | 下一动作及限制 |
| --- | --- | --- | --- |
| 仓库组织 / 主线维护者 | [调整方案](../repository-architecture-reorganization-proposal-20260918-095230.md)、[RA 进度](reorganization-progress.md) | 用户已授权持续实施；冻结/路径守卫已建立 | 本轮导航、15 条测评索引、发行工具及 Skill 说明已实现；四目标源码检查和恢复演练通过；集成身份见 RA 台账 |
| 个人端与 LAN / 产品维护者 | [个人/团队 v5 总任务书](../personal-experience-lan-team-next-development-taskbook-20260915-232155.md)、[接续进度](../personal-experience-closure-progress-20260913.md) | 个人实现与分批验证已合入；N09 跨平台全量验收仍未关闭 | 先个人验收；LAN-001–006 不因企业基础存在而记完成 |
| Linux / Linux 维护者 | [LX00–LX10 任务书](../linux-dual-host-integration-development-taskbook-20260918-205119.md)、[进度](../linux-dual-host-progress-20260918.md)、[跨平台交接](../linux-dual-host-platform-handoff-20260918.md) | 第六代功能与第八代 UI 修复候选独立记账；范围为 OpenClaw/Hermes | 原版 OpenClaw 检查点、桌面视觉、性能与完整验收按原台账处理；已取消 12 小时补充腿不恢复为阻塞 |
| macOS / macOS 维护者 | [M01–M11 剩余任务](../personal-macos-luke-remaining-development-20260917.md)、[阶段集成](../evidence/personal-experience/macos-stage-review-fixes-20260917/report.md) | 阶段实现已合入，不能借用 Linux 新核心验证关闭同候选复测 | OpenClaw/Hermes/WorkBuddy 原生安装升级与共享核心复测；Apple 公证另记 |
| Windows / Windows 维护者 | [平台任务书](../personal-windows-sunbo-taskbook-20260913-202355.md)、[整合复核](../windows-main-integration-review-20260919.md)、[后续源码/发行边界](../skill-source-release-boundary-20260919.md) | #80–#83/#90 已合入；旧文档的 junction 待签阻塞已解除 | 新候选原生安装/升级、宿主复测；OpenClaw 的 WSL Agent 与原生 Windows 分列 |
| 客户端发行 / 发行维护者 | [打包与安装](../signed-release-packaging.md)、[0.3.0 记录](../evidence/releases/0.3.0/README.md) | 普通 Release、Latest；14/14 包检查、8/8 回读、5/5 源码工作流分别记账 | [通用验包与回读](../../scripts/release/README.md)已实现；新版本原生验收继续，不重签或覆盖 0.3.0 |
| 研究 / 研究维护者 | [研究 JSON 台账](../open-source-research-tasks-20260908.json)、[生成视图](../open-source-research-tasks-20260908.md)、[研究入口](../../RESEARCH.md) | 状态来自 JSON 台账及对应验证器 | 外部复现、长期归档/DOI、新实验协议等按原任务推进，不复制完成数 |
| 企业与 Edge / 企业维护者 | [控制面](../control-plane.md)、[运维模板](../enterprise-production-runbook-v1.md)、[Edge](../../edge/agent/) | 产品基础与隔离生产配置 smoke 存在；客户生产验收另记 | 真实 IdP、部署运维及多设备条件按场景验证，不查询兄弟仓库数据库 |

## 协作与历史替代

- [整合审计](../local-development-integration-audit-20260919.md)已经核查旧本地来源；旧目录脏状态不表示尚需整树合并。独有新增内容仍需重新审查，保留原现场。
- [Windows 分支索引](../windows-branch-pr-status-20260918.md)已收敛为历史兼容入口；旧待合并栈与整合报告的待签状态按源码/发行边界后续记录判定替代范围。
- #68 云开发环境按既定要求保留，不合并、不关闭、不删除，不阻塞本轮整理。
- 采用独立工作树和范围明确的 PR；同一路径先协调。任务提示使用仓库相对路径，不依赖某个维护者的 HOME 或 worktree 名称。
- 规范/合同、产品实现与证据不一致时先核对所属规格；导航不产生 effective 权限，也不把发布标签当原生验收证据。

## 仓库检查

```bash
python3 scripts/repository/check.py --base origin/main
python3 -m unittest discover -s scripts/repository -p 'test_*.py' -v
python3 scripts/check_research_task_ledger.py
python3 scripts/research/check_metadata.py
python3 scripts/check_capability_honesty.py
```

从仓库根执行。第一条需本地已有 base 提交；CI 使用 PR base 或 push-before。外部网页可达性独立检查，离线路径守卫不会触发服务、下载或签名。

[工具职责与稳定入口](tools.md) · [历史材料与当前状态](history.md) · [研究路线](../../research/README.md)
