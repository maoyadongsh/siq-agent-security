# 个人体验当前交接（K002，2026-09-11）

## 2026-09-12 持续开发接续

M38 已修复停止时 HTTP 尚未排空就释放写锁的窗口，验证见 [停止排空记录](evidence/personal-experience/stop-drain-20260912.md)。下一步继续系统后台注册与可恢复卸载；本增量不等同后台服务安装完成。

用户再次要求以更新后的原任务书持续开发；当前工作区在 `a195fab` 上保留 M35/M36，并新增 M37 原生 `start`。已创建持续目标，当前优先 UX-003/004；详见 [M35–M37 台账](personal-experience-development-progress-20260910.md) 和 [M37 验证](evidence/personal-experience/native-start-20260912.md)。初始化、目录健康绑定和前台启动已在 Linux arm64 验证；系统后台注册、桌面通知和安装包仍待实现，其他 OS 原生证据保持未完成。下文 K002 状态为该批历史交接，不能据其“只做本批”限制当前用户已授权的接续开发。

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


## 2026-09-12 持续开发增量 M35–M41

按用户继续开发授权，已在本工作区推进实例健康绑定、原生初始化/start、停止排空、Linux unit 导出、原生 systemd 临时单位验证与签名配置准备。详见 [开发台账](personal-experience-development-progress-20260910.md)及 [M41 验证](evidence/personal-experience/service-prepare-20260912.md)。旧 K002 交接中的“再决定首个增量”已被本轮实现进展更新。

当前继续实现产品后台注册、状态与恢复/卸载；不将临时 systemd 验证或 service-prepare 计为安装器完成。三系统三平台验收、可信 Skill 归属、更新原生旅程、隐私/追溯及 LAN 仍按原目标推进。本轮修改尚未提交或推送。

M42 已接入产品 `service-register [--runtime]` 并通过真实 Linux 临时注册/重复注册/范围冲突拒绝及系统启停清理验证。后续继续产品启停/状态/卸载；完整安装器和跨 OS 原生验收仍未完成，见 [M42 证据](evidence/personal-experience/service-register-20260912.md)。

M43 已接入产品 service-start/status/stop，真实 Linux 启停与停止确认负向验证通过；停止后主锁释放。下一步继续卸载及迁移，不将该进展计作三系统安装器完成，见 [M43 证据](evidence/personal-experience/service-control-20260912.md)。

M44 已完成 Linux 产品服务注销入口及真实 runtime 注册/启停/注销旅程；数据保留和运行中拒绝已验证。后续继续升级迁移、安装交付及跨 OS 生命周期，见 [M44 证据](evidence/personal-experience/service-unregister-20260912.md)。

M45 已复用既有发行清单实现原生制品暂存；尚未切换运行版本。正向验证使用包内开发密钥夹具，Linux 实际 CLI 拒绝 unsigned 清单，见 [M45 证据](evidence/personal-experience/client-stage-20260912.md)。下一步继续升级兼容与恢复事务。

M46 已加入独立签名兼容声明与只读 client-upgrade-check；v1 仍可暂存但升级预检拒绝。切换/恢复仍待实现，见 [M46 证据](evidence/personal-experience/client-compatibility-20260912.md)。

M47 已完成服务配置成对切换事务及文件阶段恢复，serve 会拒绝未完成切换；上层候选升级/reload/健康流程继续待办，见 [M47 证据](evidence/personal-experience/service-switch-20260912.md)。

## 2026-09-12 主分支整合

用户已明确要求先提交并合并 main，本批整合 K002 既有六次提交及 M35–M47 已验证增量。完整个人/LAN 开发目标保持 active；本次合并不代表任务书全部完成。升级命令草稿尚未验证、未接入 CLI，已另存于工作区外 `/home/maoyd/siq/.siq-upgrade-draft-20260912/`，不纳入本次主分支代码；后续恢复该草稿时重新复核当前状态。实际提交和合并状态以 PR #28/Git 为准。
