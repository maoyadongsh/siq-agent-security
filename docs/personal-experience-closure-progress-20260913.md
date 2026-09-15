# 个人体验闭环接续进度（2026-09-13）

2026-09-15 增量：总体任务书升级 [v4.1 第 15 节](personal-experience-lan-team-next-development-taskbook-20260914-112027.md#15-轻量化与-openshell-融合执行计划2026-09-15)，完整纳入轻量化/OpenShell 路线并拆分 O00–O06。O01 策略保真与 O02 进程内安全回滚已完成 Go/Python 实现、组件验证和隔离 OpenShell 0.0.83 真实读写验收；[O01/O02 证据](evidence/personal-experience/openshell-o01-o02-20260915/report.md)记录完整策略摘要、共享向量、零写拒绝、操作绑定、漂移/撤权拒绝、非连续 revision 及真实 revision `7→8→9` 精确恢复。research-engine 网关、强身份 broker、正确 `siq_analysis` 宿主服务和业务 canary 已恢复，运行选择为 OpenShell；当前保留 `canary-a01b02c91503`，真实模型请求和业务边界 probe 通过，但仍是 `NOT_PRODUCTION_CANARY/readiness_effect=none`。O03 子进程共享输出限额、环境白名单、超时/管道边界和错误脱敏已完成 Go/Python 本地验证，[O03 证据](evidence/personal-experience/openshell-o03-20260915/report.md)记录完整回归、四目标构建与跨 OS 限制；O00 只有组件性能初始样本，O04 仍待，O05/O06 未开展。sunbo/Luke 原任务不变。验证完成后已获用户授权提交并推送，具体提交身份以 Git 历史为准；下文旧候选矩阵不自动适用于新构建。

当前任务书：[v4.1](personal-experience-lan-team-next-development-taskbook-20260914-112027.md)。PR #45 已合入 main `4464dfbc8e66c8ec1fb2590b286351595fcd9667`；本次接续成果保留在独立功能分支，提交与推送身份以 Git 历史为准。N01 原有最低门槛保持有效；N05 已完成安全组件、Linux/Hermes 任务级和 Linux/OpenClaw 会话级原生 SEC，N06 已完成可信预留、Linux/Hermes/OpenClaw 批准重试及 Linux 通知总线传输；六条 Linux 证据腿已统一到同一候选并进入 N09 当前矩阵。跨系统、WorkBuddy、真网、通知视觉确认与 N09 仍 partial。

**继承结论：N01 已完成开发及 Linux 最低验收门槛。** 本轮补齐版本协议、递归备份、可恢复迁移、签名发行兼容检查及用户恢复指引，详见 [N01 完成报告](evidence/personal-experience/n01-completion-20260913-190637/report.md)。Windows/macOS 原生材料仍待 N07/N09；N00 由独立分支/旧树核查关闭；个人总体进度不因此自动完成。前一轮 Ornith 审查及失败证据保留为历史。

| 任务 | 原任务映射 | 状态 | 当前证据/下一步 |
| --- | --- | --- | --- |
| N00 基线 | UX-000 | verified | 55 个捕获引用均已纳入主线；旧树展开 469 条，7 份历史文档/证据已归档，无遗漏业务源码；原工作树/index 保留 |
| N01 状态兼容/迁移/回退 | UX-003/010/014 | verified（Linux 最低门槛） | 已完成状态 v2、实例绑定、递归备份和恢复、发行预检及真实双二进制拒写；其余 OS 原生见 N07/N09 |
| N02 安全 Git 获取 | UX-009/010 | partial（组件已验，生产关闭） | 固定 commit HTTPS 组件与负向验收完成；[R03 网络复核](evidence/personal-experience/r03-hosted-git-network-20260914/report.md)仍解析到 198.18/15 保留地址，真实 GitHub 联测 blocked，生产入口继续 503 |
| N03 自动新版检查 | UX-010 | partial（Linux/Hermes 原生更新已验） | 来源存储、调度器、daemon、HTTP/Web、签名迟到写入防护及 R04-B 一键停用已验；[R04-E](evidence/personal-experience/r04e-hermes-native-update-20260914/report.md)完成 V1→V2 原生使用、取消、确认、权限切换与移除，公网来源及其他平台/OS 仍待 |
| N04 平台能力与接入 | UX-001/002/005/006/009 | partial（Linux Hermes/OpenClaw 原生工具边界已验） | [R05 Linux 盘点](evidence/personal-experience/r05-linux-host-capabilities-20260914/report.md)、[OpenClaw 管理接入原生验收](evidence/personal-experience/r05d-openclaw-managed-native-20260914/report.json)及 R01 Hermes/OpenClaw SEC 证据覆盖两宿主；WorkBuddy 缺运行时、OpenShell 网关不可达，其余系统继续 |
| N05 可信 Skill 归属 | UX-007/011 | partial（Linux 两宿主原生通过） | SEC 签名上下文、安装 Grant 强制归属、调用绑定与权限交集已落盘；[Hermes `controlled_task`](evidence/personal-experience/r01-sec-hermes-native-20260914/report.json)与 [OpenClaw `controlled_session`](evidence/personal-experience/r01-sec-openclaw-native-20260914/report.json)真实工具链通过；WorkBuddy 和其他 OS 待补 |
| N06 审批后的继续执行/通知 | UX-008 | partial（Linux 双宿主重试及通知传输通过） | 签名预留、并发唯一消费、uncertain 管理结案、[Hermes 原生批准重试](evidence/personal-experience/r02-hermes-approved-retry-20260914/report.json)、[OpenClaw 18 场景原生控制链](evidence/personal-experience/r02f-openclaw-approved-retry-20260915/report.md)及 [Linux GNOME 通知总线传输](evidence/personal-experience/r02g-linux-desktop-notify-20260915/report.md)已验；WorkBuddy、上游 OpenClaw 支持、Linux 视觉确认及 Windows/macOS 通知待补 |
| N07 三系统安装与生命周期 | UX-003/014 | partial（各 OS 持续开发） | Linux 与 Windows 增量已合入此前 PR；sunbo 尚未完成 Windows，Luke 负责 macOS；不宣称三系统通过 |
| N08 完整个人用户旅程 | UX-004/005/009/011/012/013 | partial（Linux/Hermes 更新原生闭环已验） | 迟到响应与会话清理、93 项前端测试；30 项会话/断连及 7 项更新事务浏览器检查通过；R04-E 又完成 15 项真实 Hermes 工具链更新验收，跨平台完整旅程仍待 |
| N09 综合验收 | UX-015 | partial（当前候选逐行矩阵有效，未完成） | [当前候选矩阵](evidence/personal-experience/n09-current-candidate-20260915/report.md)将 6 条 Linux 腿统一到 `b6e7650f…6708` 并通过 v2 完整性/coverage 校验；无 complete_acceptance 行。旧矩阵保留为[历史独立复核](evidence/personal-experience/n09-independent-review-20260914/report.md)；WorkBuddy、生产真网、完整产品生命周期及 Windows/macOS 仍待实机，团队前置门槛未关闭 |
| T01 局域网控制面部署 | LAN-001 | todo | 依赖 N09；本轮无新增交付证据 |
| T02 团队加入与设备身份 | LAN-002 | todo | 依赖 N09；本轮无新增交付证据 |
| T03 多设备资产与隐私 | LAN-003 | todo | 依赖 N09；本轮无新增交付证据 |
| T04 定向与批量任务 | LAN-004 | todo | 依赖 N09；本轮无新增交付证据 |
| T05 组织策略实际应用 | LAN-005 | todo | 依赖 N09；本轮无新增交付证据 |
| T06 两台真实设备综合验收 | LAN-006 | todo | 依赖 N09；本轮无新增交付证据 |

## 2026-09-14 独立阶段复核

本批接受范围、暂缓原因和验证详见 [GLM 成果复核报告](evidence/personal-experience/glm-stage-review-20260914/report.md)。下列旧执行顺序为 v3 历史；v4 已固定本批合并基线，优先可信归属、审批重试及原生验收。

## 下一执行批次（v3 历史）

1. 先读 [N01 完成报告](evidence/personal-experience/n01-completion-20260913-190637/report.md)、本批入口覆盖表和状态协议规格，保留全部负向测试。旧的“自动迁移未实现”是前一轮历史范围，不能据此删除当前已验收转换器。
2. N00 核查已完成；下一窗口只需刷新新 main 和新出现的差异，不重复导入原 IDE 目录。
3. 优先 N02 安全 Git 与 N04 平台能力核验。N03/N07 可依赖 N01 的签名状态支持范围继续；未知 Git/平台能力仍保持拒绝或 unknown。
4. N07/N09 补充 Windows/macOS 实机升级、失败恢复与生命周期材料，测试密钥和验证构建不作正式发行证明。
5. N09 未验收前不进入团队。当前 N01 完成不等于整个个人产品、三平台或 LAN 目标完成。

## v4 执行批次

| 批次 | 目标映射 | 状态/交付边界 |
| --- | --- | --- |
| R01 | N05 | 阶段门槛完成：规格/合同/实现/并发测试/Web、57 步服务活体、Linux/Hermes `controlled_task` 及 Linux/OpenClaw `controlled_session` 原生工具链通过；N05 跨平台整体仍 partial |
| R02 | N06 | partial：[可信重试组件复核](evidence/personal-experience/r02-trusted-retry-review-20260914.md)、[Linux/Hermes 原生批准重试](evidence/personal-experience/r02-hermes-approved-retry-20260914/report.json)、[Linux/OpenClaw 原生控制链](evidence/personal-experience/r02f-openclaw-approved-retry-20260915/report.md)及 [Linux 通知传输](evidence/personal-experience/r02g-linux-desktop-notify-20260915/report.md)通过；WorkBuddy、上游 OpenClaw 支持、通知视觉确认及其他 OS 待补 |
| R03 | N02 | partial：组件已合入，真网验收及生产启用待办 |
| R04 | N03/N08 | partial：R04-B 一键停用与浏览器更新 7 项完成；[R04-E](evidence/personal-experience/r04e-hermes-native-update-20260914/report.md)完成 Linux/Hermes 原生 V1→V2 使用、权限/身份切换、回执和移除 15 项；真网上游及其他平台/OS 待办 |
| R05 | N04 | partial：Linux/OpenClaw 与 Hermes 已完成真实工具边界；WorkBuddy 缺运行时、OpenShell 网关不可达，Windows/macOS 由协作者继续 |
| R06 | N07 | partial：sunbo/Luke 继续对应 OS 实机与适配 |
| R07 | N09 | partial：同一当前候选 6 条 Linux 腿已逐行登记并通过 v2 校验；无 complete_acceptance，外部平台和完整旅程未完成 |
| O01 | OpenShell P0-A/B/F | 实现、组件验证和隔离真网验收完成：完整策略保留、严格 revision、受限 YAML、未知/L7/deny 零写拒绝、实际静态差异规划与完整摘要读回均已落盘；真实 `7→8→9` 更新/恢复和摘要一致；[报告](evidence/personal-experience/openshell-o01-o02-20260915/report.md)；提交状态以 Git 历史为准 |
| O02 | OpenShell P0-C | 实现、组件验证和隔离真网验收完成：私有操作绑定、精确 base 快照、no-op 零写、目标串行、前后漂移检查、撤权复核、伪造回执和重启未知记录拒绝已落盘；仅保证同进程协调，不宣称跨进程 CAS；提交状态以 Git 历史为准 |
| O03 | OpenShell P0-E | 本地实现/验收完成：[报告](evidence/personal-experience/openshell-o03-20260915/report.md)；跨 OS 实机待补；提交状态以 Git 历史为准 |

T01–T06 保持 todo，依赖 R07/N09 关闭；本次未发布产品制品。
