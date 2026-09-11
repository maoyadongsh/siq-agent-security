# 个人体验当前交接（K002，2026-09-11）

原始范围：[个人体验与局域网团队任务书](personal-experience-lan-team-development-taskbook-20260910-145507.md)，D01–D11、UX-000–015、LAN-001–006 保持不变。

## 已结束的基线修复

KIMI-001/R1/B1 经 PR #27 合并；main 基线 `1e20635843c0966e24d73d149e3d7bcd080f89c4`。合并后的 ci `34588402820`、runtime-security `34588402849`、research `34588402923`、pages `34588402834` 通过；nightly 条件跳过。原材料仍在 [M1–M34 台账](personal-experience-development-progress-20260910.md)及 K001 交接文件，历史状态与证据不改写。

## 当前批次：K002 平台验证基础与安装设计

分支 `codex/personal-k002-platform-readiness`，从上述 main 新建，不在已合并 K001 分支继续开发。

| 原任务 | 本批增量 | 未关闭条件 |
| --- | --- | --- |
| UX-000 | 建立本交接，明确 K001 已结束与 K002 范围 | 不是重新完成需求基线，不重复计算 M1–M34 |
| UX-001 | 离线平台材料校验器、两个 QA 合同、正负向测试与跨 OS 工具 CI | 真实 OS/宿主版本、正常/拒绝/审批/归属能力，待 Kimi 实机执行 |
| UX-002 | ADR-049 材料与支持声明分离；ADR-050 生命周期方案提案 | 各 OS 后台机制/权限、WorkBuddy 原生能力、具体安装合同尚需实测决策 |
| UX-003/014 | 复用现有 Go/状态协议/Web embed 的实现方向 | 尚未新增产品安装器、托盘或正式制品 |

工具通过只表示材料处理代码与输入规则通过，不表示18个目标已验证。尚不能宣布 M0/UX-001/UX-002 完整完成；缺系统不阻塞相互独立设计。当前不开始 LAN，不把 ADR-0048 的未实施变成需求放弃，原文存储继续关闭。

### 交付入口

- [平台材料规格](personal-platform-validation-spec-v1.md)与 [ADR-049](adr/0049-personal-platform-evidence-inventory.md)。
- [生命周期方向提案](adr/0050-personal-client-lifecycle-direction.md)。
- `scripts/personal-experience/platform_acceptance.py` 和 `scripts/personal-experience/tests/`。
- [Kimi 本批实机执行单](KIMI-002-native-platform-validation.md)。
- 本地验证：`docs/evidence/personal-experience/reviewer-k002-20260911/verification.json`；远端结果以 PR 的最终 HEAD 与 run 为准，不把提交前状态改写为 CI 已通过。

审阅方环境可执行新工具和测试，但 Git DNS 不可用，未取得完整克隆，未在这里重跑旧 Go/前端或目标宿主。完整仓库回归由本批 PR CI 实跑；原生桌面/真实智能体另行验证，不用 CI 的工具单测代替。

## 接下来只做本批未覆盖部分

Kimi 按同一分支交付真实平台材料与生命周期假设验证；审阅方在交接后不并行修改同组文件。完成后审阅本批 PR，再决定 UX-003 的首个可运行安装/生命周期增量；真实 Hermes 更新旅程继续保留为 UX-010 优先补验，其他原任务不丢弃、不一次下发。

用户已授权本轮分支开发、提交与推送；不自动合并 main、发布、部署、删除分支或更改仓库保护。未来合并仍按已约定的单独授权流程。
