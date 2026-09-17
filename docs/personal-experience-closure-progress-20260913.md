# 个人体验闭环接续进度（2026-09-13）

> **2026-09-16 策略加载修复后更新**：见 [修复与复测报告](openshell-policy-load-wait-repair-20260916.md)。L01 旧 `arrivals=1` 失败已定位到未等待沙箱加载；应用及回滚增加有界加载确认，3 轮真实复测均为 HTTP 403 + 零到达，rc.6 策略 HTTP 旅程 57/57。Python 同类路径同步修复并完成组件回归。旧失败证据保留；L02 完整任务/UI、新候选性能及外部实机仍未完成。此更新优先于下方历史状态。


> **2026-09-16 收尾复核更新**：以 [最新复核报告](local-o05-closure-review-20260916.md) 为准。rc.5 身份保护原生验证 4/4、策略 HTTP 旅程 57/57；L01 严格实测发现违规请求到达 1 次，保持未通过。L02 非完整任务执行；L04 的旧 0.9967 只对应 doctor_readback，B3 未测，新候选性能未测；L05 部分完成。旧绿色勾选仅保留为历史声明。


2026-09-15 基线提交：`53155b10c276fe41e71c47757e58e7e56d5d75d4` 已在当前分支本地提交 R06/R04/R07 修复与证据；未推送/合并。后续执行见 [v5 任务书](personal-experience-lan-team-next-development-taskbook-20260915-232155.md) 与 [GLM 提示词](glm-personal-next-execution-prompt-20260915-232155.md)。下方复核叙述及原报告中的“未提交”是当时快照，不代表当前 Git 状态。


2026-09-15 R06/R04/R07 独立复核（当前状态）：[修复与复测报告](evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md)。修复管理页面请求失效后不重新加载、适配器同值选择卡死；纠正 HTTP 201 被误算拒绝，增加有效签名下真实暂存内容漂移负例；浏览器使用单次导航、同一文档经历重启与重新配对；原文任务授权/撤销、未到期密文与回执保留采用实测断言；systemd 使用保留状态重新注册启动并清理。原 GLM 报告和摘要文件保留，但“LC01–LC09 全部通过”“完整用户旅程已关闭”不再作为当前结论。本批含 Web 源码和 embed 更新，候选身份已变化，全部新改动未提交/未推送/未合并。

GLM 历史交付见原 [R06](evidence/personal-experience/r06-linux-lifecycle-20260915-161515/report.md)、[R04](evidence/personal-experience/r04-openclaw-native-update-20260915-171614/report.md)、[R07](evidence/personal-experience/r07-linux-user-journey-20260915-211053/report.md)。当前状态以本段、任务书第 8.4/9.2/10.2 节及复核矩阵为准。

2026-09-15 复核修复（当前状态）：O04/O00 本机阶段已完成修复与复测，[完整报告](evidence/personal-experience/openshell-o04-review-20260915/report.md)。配置能力与历史证据分离并用于实际编译判断；两语言共享 status 校验；PATH/env.sh 缓存禁复用、显式配置/TLS 漂移拒绝、失败刷新清空旧证据；指定目标只读诊断返回 revision/digest，前端过期自动降级；RSS 格式升级 v2，不可得为 null。D 故障返回 p95=200.886ms、max=201.261ms，原 300/500ms 门槛不变。原生真实 HTTP 验证包含授权前拒绝、准入/确认/部署、允许、撤销后拒绝和回执验签；每轮 422 个请求，OpenShell/Docker Runner 调用为零。独立 archive 的 O04 增量对照满足 p95 增幅≤10%，并记录 CPU/RSS/磁盘写入及请求计数。此基线在 O01–O03 之后，不能冒充完整轻量化前 B0；B2/B3、Win/mac、WorkBuddy 和 O05 仍需后续真实环境验收。全部仅落盘，未提交/推送/合并/发布。

下段为 **GLM 原始交付记录，非当前验收结论**；其中“D 未达标”已通过修复复测关闭，“禁止 reset 导致不能做对照”是错误归因，已用独立 archive 补 O04 增量对照。“组件级完成”不表示所有 O04 状态或真实环境验收完成，最新状态以上段和总体任务书为准。原始证据文件保持原样。

2026-09-15 增量（O04）：O04“当前能力与性能”组件级完成。能力事实按合同六类分离（`client_expressible`/`documented`/`configured`/`handshake_verified`/`readback_verified`/`enforcement_reserved`），`gateway info` 成功不再等价后端在线，`cli_version` 与 `gateway_version` 分离且版本不提升能力，缓存绑定 endpoint 指纹+观测时间；诊断六态（unconfigured/configured_unreachable/identity_unconfirmed/handshake_verified/policy_readable/behavior_verified，另含 evidence_expired）落到 CLI doctor 与 HTTP 端点。`perfbaseline` 的 `rss_bytes_after` 由 Go `MemStats.Sys`（≈23MB，非 RSS）修复为 `/proc/self/status` VmRSS（≈13.3MB），读取失败记 `unavailable` 不伪造为零，JSON 键名保留、诚实性门禁通过。场景 A–E 用测量前冻结的协议（3 轮、A/B 交错、热路径每轮 200 样本、nearest-rank、零剔除、绝对预算）完成 B1 组件测量：A/B/E p95 全部远低于预算，场景 A 断言未启用 OpenShell 整轮零子进程调用；D 场景 p95 301.0ms 超 300ms 冻结预算 1.0ms——根因是 O03 冻结的 200ms `WaitDelay` 管道边界（设计上界 100+200ms），未放宽门槛、未剔除样本、max 301.4ms 在 500ms 预算内。B1−B0 对照 not_measured（禁止在活动工作树 reset 生成对照），B2/B3 缺真实后端 blocked；全部证据为组件级（进程内 fixture/真实子进程 fixture），不冠名端到端性能。证据：[O04 报告](evidence/personal-experience/openshell-o04-20260915/report.md)、[O04 性能协议与原始样本](evidence/personal-experience/openshell-o04-perf-20260915-062001/report.json)。回归：Go gofmt/vet/全量/race 通过、四目标交叉构建通过、Python 841 项+ruff 通过、`git diff --check` 干净。本轮改动未提交；不推送、不合并、不发布。

2026-09-15 增量：总体任务书升级 [v4.1 第 15 节](personal-experience-lan-team-next-development-taskbook-20260914-112027.md#15-轻量化与-openshell-融合执行计划2026-09-15)，完整纳入轻量化/OpenShell 路线并拆分 O00–O06。O01 策略保真与 O02 进程内安全回滚已完成 Go/Python 实现、组件验证和隔离 OpenShell 0.0.83 真实读写验收；[O01/O02 证据](evidence/personal-experience/openshell-o01-o02-20260915/report.md)记录完整策略摘要、共享向量、零写拒绝、操作绑定、漂移/撤权拒绝、非连续 revision 及真实 revision `7→8→9` 精确恢复。research-engine 网关、强身份 broker、正确 `siq_analysis` 宿主服务和业务 canary 已恢复，运行选择为 OpenShell；当前保留 `canary-a01b02c91503`，真实模型请求和业务边界 probe 通过，但仍是 `NOT_PRODUCTION_CANARY/readiness_effect=none`。O03 子进程共享输出限额、环境白名单、超时/管道边界和错误脱敏已完成 Go/Python 本地验证，[O03 证据](evidence/personal-experience/openshell-o03-20260915/report.md)记录完整回归、四目标构建与跨 OS 限制；O00 只有组件性能初始样本，O04 仍待，O05/O06 未开展。sunbo/Luke 原任务不变。验证完成后已获用户授权提交并推送，具体提交身份以 Git 历史为准；下文旧候选矩阵不自动适用于新构建。

当前任务书：[v4.1](personal-experience-lan-team-next-development-taskbook-20260914-112027.md)。PR #45 已合入 main `4464dfbc8e66c8ec1fb2590b286351595fcd9667`；本次接续成果保留在独立功能分支，提交与推送身份以 Git 历史为准。N01 原有最低门槛保持有效；N05 已完成安全组件、Linux/Hermes 任务级和 Linux/OpenClaw 会话级原生 SEC，N06 已完成可信预留、Linux/Hermes/OpenClaw 批准重试及 Linux 通知总线传输；六条 Linux 证据腿已统一到同一候选并进入 N09 当前矩阵。跨系统、WorkBuddy、真网、通知视觉确认与 N09 仍 partial。

**继承结论：N01 已完成开发及 Linux 最低验收门槛。** 本轮补齐版本协议、递归备份、可恢复迁移、签名发行兼容检查及用户恢复指引，详见 [N01 完成报告](evidence/personal-experience/n01-completion-20260913-190637/report.md)。Windows/macOS 原生材料仍待 N07/N09；N00 由独立分支/旧树核查关闭；个人总体进度不因此自动完成。前一轮 Ornith 审查及失败证据保留为历史。

| 任务 | 原任务映射 | 状态 | 当前证据/下一步 |
| --- | --- | --- | --- |
| N00 基线 | UX-000 | verified | 55 个捕获引用均已纳入主线；旧树展开 469 条，7 份历史文档/证据已归档，无遗漏业务源码；原工作树/index 保留 |
| N01 状态兼容/迁移/回退 | UX-003/010/014 | verified（Linux 最低门槛） | 已完成状态 v2、实例绑定、递归备份和恢复、发行预检及真实双二进制拒写；其余 OS 原生见 N07/N09 |
| N02 安全 Git 获取 | UX-009/010 | partial（组件已验，生产关闭） | 固定 commit HTTPS 组件与负向验收完成；[R03 网络复核](evidence/personal-experience/r03-hosted-git-network-20260914/report.md)仍解析到 198.18/15 保留地址，真实 GitHub 联测 blocked，生产入口继续 503 |
| N03 自动新版检查 | UX-010 | partial（Linux/Hermes/OpenClaw 原生更新已验） | 来源调度与 Hermes 历史腿保留；[OpenClaw 复核](evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md)验证更新链及真实暂存漂移拒绝，UP05/UP07/公网故障和其他 OS 待补 |
| N04 平台能力与接入 | UX-001/002/005/006/009 | partial（Linux Hermes/OpenClaw 原生工具边界已验） | [R05 Linux 盘点](evidence/personal-experience/r05-linux-host-capabilities-20260914/report.md)、[OpenClaw 管理接入原生验收](evidence/personal-experience/r05d-openclaw-managed-native-20260914/report.json)及 R01 Hermes/OpenClaw SEC 证据覆盖两宿主；WorkBuddy 缺运行时、OpenShell 网关不可达，其余系统继续 |
| N05 可信 Skill 归属 | UX-007/011 | partial（Linux 两宿主原生通过） | SEC 签名上下文、安装 Grant 强制归属、调用绑定与权限交集已落盘；[Hermes `controlled_task`](evidence/personal-experience/r01-sec-hermes-native-20260914/report.json)与 [OpenClaw `controlled_session`](evidence/personal-experience/r01-sec-openclaw-native-20260914/report.json)真实工具链通过；WorkBuddy 和其他 OS 待补 |
| N06 审批后的继续执行/通知 | UX-008 | partial（Linux 双宿主重试及通知传输通过） | 签名预留、并发唯一消费、uncertain 管理结案、[Hermes 原生批准重试](evidence/personal-experience/r02-hermes-approved-retry-20260914/report.json)、[OpenClaw 18 场景原生控制链](evidence/personal-experience/r02f-openclaw-approved-retry-20260915/report.md)及 [Linux GNOME 通知总线传输](evidence/personal-experience/r02g-linux-desktop-notify-20260915/report.md)已验；WorkBuddy、上游 OpenClaw 支持、Linux 视觉确认及 Windows/macOS 通知待补 |
| N07 三系统安装与生命周期 | UX-003/014 | partial（各 OS 持续开发） | [Linux 复核](evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md)通过 runtime 用户服务保留状态重入；原 LC01–LC09 全通过声明撤回，正式发行包升级与安装实例串联仍待；sunbo/Luke 继续原任务 |
| N08 完整个人用户旅程 | UX-004/005/009/011/012/013 | partial（Linux/Hermes 更新原生闭环已验） | 历史 Hermes 腿保留；[新候选复核](evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md)通过单次导航与会话重启旅程，完整安装串联、真实到期/任务导出等仍待 |
| N09 综合验收 | UX-015 | partial（当前候选逐行矩阵有效，未完成） | [新矩阵](evidence/personal-experience/r06-r04-r07-review-20260915-223037/n09/report.md)只登记同一修复候选的 R04/R07 两条腿；旧候选矩阵为历史，零 complete_acceptance；外部平台与本机缺口未关闭 |
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
| R04 | N03/N08 | partial：OpenClaw 更新链与完整性负例见[复核](evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md)，UP05/UP07/公网故障未关闭 |
| R05 | N04 | partial：Linux/OpenClaw 与 Hermes 已完成真实工具边界；WorkBuddy 缺运行时、OpenShell 网关不可达，Windows/macOS 由协作者继续 |
| R06 | N07 | partial：runtime 用户服务保留状态重入通过；正式包升级与安装实例串联仍待，sunbo/Luke 继续 |
| R07 | N09 | partial：单次导航、当前页面重启恢复、真实原文授权/撤销见[复核](evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md)；非正式安装到旅程的完整验收 |
| O01 | OpenShell P0-A/B/F | 实现、组件验证和隔离真网验收完成：完整策略保留、严格 revision、受限 YAML、未知/L7/deny 零写拒绝、实际静态差异规划与完整摘要读回均已落盘；真实 `7→8→9` 更新/恢复和摘要一致；[报告](evidence/personal-experience/openshell-o01-o02-20260915/report.md)；提交状态以 Git 历史为准 |
| O02 | OpenShell P0-C | 实现、组件验证和隔离真网验收完成：私有操作绑定、精确 base 快照、no-op 零写、目标串行、前后漂移检查、撤权复核、伪造回执和重启未知记录拒绝已落盘；仅保证同进程协调，不宣称跨进程 CAS；提交状态以 Git 历史为准 |
| O03 | OpenShell P0-E | 本地实现/验收完成：[报告](evidence/personal-experience/openshell-o03-20260915/report.md)；跨 OS 实机待补；提交状态以 Git 历史为准 |

T01–T06 保持 todo，依赖 R07/N09 关闭；本次未发布产品制品。

## v5 执行批次（2026-09-15/16，进行中）

基线 `dafb4cd`（含 O01–O03 与 O04 修复链）；执行书 `personal-experience-lan-team-next-development-taskbook-20260915-232155.md`。

| 批次 | 状态/交付边界 |
| --- | --- |
| B00 | done：基线/环境/发行材料/资源归属清单见 [closure-b00](evidence/personal-experience/closure-b00-20260915-233905/) |
| B01 | partial：test_release 生命周期复核 35/35（closure-b01-review-20260916，含真实消费码、301 秒自然过期、撤销 Grant 保留重入）及显式崩溃恢复 8/8；正式发行信任腿未关闭 |
| B02 | partial：实例 HOME 隔离已实现并完成 Linux test_release 实测（closure-b02-scoped-home-20260916-r3：批次 15/15、安装服务旅程 26/26、直接进程 25/25）；复核修正见 closure-b02-home-validation-20260916。正式发行信任腿仍未关闭，旧共享 manager HOME 方案仍不采纳 |
| B03 | partial：双 CLI 合成未来/损坏状态拒写 44/44；独立管理员配对、loopback HTTP 并发与签名 409 是另行 Go 回归，不能混称 44 项实机覆盖 |
| B04 | partial：真实墙钟到期 19/19；两个独立 HTTP export 复核各 192/192。合成捕获不冒充宿主原生采集，保留证据等级边界 |
| B05 | partial：当前指定候选 53619668…，共享 harness 修复后 r3 16/16；已修复忽略 --binary 而重建 HEAD 的问题。通知视觉及其他 OS/宿主未关闭 |
| B07 | partial：原声称干净的 022051 B1 实与 Go race 重叠，022225 对比已标 INVALID；最终对照 closure-b07-final-review-20260916：绝对预算全过，仅 diagnose_unconfigured 的相对 +15.79% 超 10%，其余等工作量项通过。C 工作量变化、E 无 B0，不计等工作量通过；B2/B3 仍待真实后端，fsync 占比不能证明回退由噪声造成 |
| B06/B08 | conditional：本次 DNS 重查 GitHub/codeload 仍为 198.18/15，未绕过 SSRF。OpenShell PATH doctor 为 configured_unreachable；历史 17671/17672 有监听，只证明端口开放，未证明本批可用且归属确认的后端 |
| B09 | external_manual：sunbo（Windows）/Luke（macOS）继续；不代发消息不代提交 |
| B10 | partial：本机文档/负向回归/矩阵更新；不代表 B02、N09 或正式发布验收关闭，最终矩阵 closure-b10-final-review-20260916 使用 B05 r3；脚本回归 33/33；复核以 personal-v5-takeover-review-20260916.md 为准 |

T01–T06 仍 todo，依赖 N09；本批未 commit/push/merge，落盘状态以工作区为准。

## 发行候选准备批次（2026-09-16，release-openshell-20260916-142706）

| 项 | 状态/交付边界 |
| --- | --- |
| 发行候选 | rc.1 保留历史；安全修复后 rc.2 独立构建并绑定源文件/差异/制品摘要，详见修复报告；未正式签名，不代表发行就绪 |
| 环境预检 | 旧候选 policy_readable 已观察；协议匹配不是会话绑定或当前网关能力证明；新候选复核以修复报告为准 |
| B2/B3 真网 | partial（复核）：撤回全部通过；旧 doctor 样本未逐次校验状态，同 CLI 控制项不能归因候选，测试驱动不是候选 B3；v2 工具已修复，正式复测待专用目标 |
| O05 真后端 | partial（复核）：有策略控制面证据；会话身份/撤销/执行关联未证明，行为阻止负例根因未确认；撤回 7/8 与 interceptor 归因 |
| 正式签名 | blocked：官方种子未设置；解锁见 readiness 文档 §9 |
| 跨平台 | external_manual：sunbo (Windows) / Luke (macOS) 不代做不标记通过 |
| 资源 | 批次沙箱 siq-relcand-20260916-154423 用毕删除；原始日志存私有 /tmp；未 commit/push/merge |

证据: docs/evidence/personal-experience/release-openshell-20260916-142706/{candidate,b01-lifecycle,openshell-live}/（均含 SHA256SUMS）；
报告: openshell-real-environment-readiness-20260916.md 与 release-openshell-execution-report-20260916.md。

2026-09-16 最新复核：[release-openshell-review-fixes-20260916.md](release-openshell-review-fixes-20260916.md)。限制字段再下发零写拒绝、端点检查不误判、验收工具与签名指引修复；原始证据只读保留。


### 2026-09-16 OpenShell L01/L02 本地安全复核

本批状态以 [GLM 进度的复核修正](local-o05-b3-progress-20260916-181347.md) 和 [安全修复规格](openshell-l01-l02-repair-spec-20260916.md) 为准。阻断分类与策略恢复、完整批准参数绑定、当前签名 Grant 复核、写前撤权检查、证据失败响应已修复。L01 真实行为复测仍待；L02 仅策略控制面原型，无沙箱任务执行。L03/L04/L05/L07 未因这些修复自动完成；跨平台实机、正式签名与发布状态保持原边界。新源变更不追溯替换冻结 rc.2。
