# Linux 双宿主闭环任务进度

更新：2026-09-19。本文件跟踪[开发任务书](linux-dual-host-integration-development-taskbook-20260918-205119.md) LX00–LX10；每项实现与验收分开记账。[本批证据报告](evidence/personal-experience/linux-dual-host-20260918-211200/report.md)包含各代候选摘要、检查数量、边界和资源清理。

## 当前功能链路里程碑

| 链路 | 本阶段结论 | 仍不转移的边界 |
| --- | --- | --- |
| Linux 已安装服务、发现、授权、更新、卸载与完整用户旅程 | 跑通；第六代同候选 B02 16/16、已装 R07 31/31、直启 R07 30/30，两条嵌套 R04 均 31/31 | 测试发行信任根不等于正式签名发行 |
| Hermes 原生审批消费、拒绝、漂移、撤权与浏览器确认 | 跑通；浏览器确认联合腿 24/24 | 人工桌面视觉与跨进程外部效果原子性另行验收 |
| OpenClaw 原版与最新版 | 原版和最新版未改造宿主均在缺少审批后复查能力时安全拒绝；2026.9.4 隔离受控副本审批 18/18、产品托管公共 CLI 22/22 | 受控副本结果不冒充上游原版能力；暂不覆盖全局 2026.5.12 安装 |
| 原文保留、签名导出、任务隔离与注销撤权 | 当前范围已跑通；两代真实 A1=1 小时密文到期均 14/14，A2/B1=24 小时保留、任务隔离、默认排除和显式注销撤权均有独立证据 | 补充性的管理员会话连续 12 小时腿由项目负责人移出当前范围，记 `out_of_scope`，不产生到期通过结论 |
| OpenShell D05/B3 主体功能 | 跑通；D05 373 步零 fail，B3 57/57 | 远端单任务停止、旧无等待 CLI 与超时来源字段是外部/协议条件 |
| PostgreSQL + OIDC/JWKS | 本机隔离集成 27/27 跑通 | 客户生产 IdP、HA、备份和正式部署仍是外部验收 |

本表只回答当前“链路与功能是否跑通”，不会覆盖下方原任务的严格状态、性能门、正式签名或跨平台验收。

| 任务 | 实现状态 | 验收状态 | 当前依据与下一步 |
| --- | --- | --- | --- |
| LX00 隔离基线 | done | done | 独立工作树 `codex/linux-dual-host-20260918`，基线 2187fea；源绑定与候选记录已落盘 |
| LX01 当前候选 | done | done（本项范围） | `client-install` 首装身份顺序修复、Go 全量测试与 vet 通过；第一代未签名候选 `70df5455…` 的直接 R07 从 27/27 增至 30/30。浏览器会话竞态修复后第二代候选 `929bfbe5…` 的 Go 全量测试、vet、四目标交叉构建及真实 OpenClaw R07 30/30、嵌套 R04 31/31 通过。第四代 `a13d6234…` 的根范围回归与构建证据保留为历史对照；第五代暂存候选 `6ce92b69…` 增补已安装 Skill 待确认投影修复；当前第六代未签名候选 `67bc48c4…` 修复获批 SEC 复查，Go 全量/vet/race 与四目标交叉构建通过。正式签名和第六代性能由 LX06/LX10 独立验收；证据见下文 |
| LX02 已装服务 × 旅程 | done | test_release passed | 第一代候选的 systemd B02 15/15、已装 R07 28/28；新 UI 源码的测试信任根构建 `ec8ea776…` 在 336 个 Go 文件及 214 个内嵌 UI 文件逐一复核后，已装 B02 16/16、已装 R07 31/31、直接进程 R07 30/30，嵌套 R04 均 31/31；单元和端口清理复核通过。测试信任根不等于正式发行；第四代、第五代均各自完成 B02 16/16、已装 R07 31/31、嵌套 R04 31/31。第六代 `67bc48c4…` 的 550 个生产 Go/内嵌 UI 文件逐一匹配测试发行覆盖，B02 16/16、已装 R07 31/31、直启 R07 30/30，两条嵌套 R04 均 31/31；专属 unit、端口及构建目录已清理，见[同候选摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx02-sec-hold-fix-installed-summary.json) |
| LX03 双宿主原生审批 | partial | partial | 第一代与第二代候选均分别实测 Hermes 原生审批 12/12、SEC 11/11，以及 OpenClaw 托管原生 CLI 19/19、原版 hold 执行前安全拒绝和隔离检查点宿主副本 18 场景通过。第二代 `929bfbe5…` 的有效 Grant 目录外直接读与 `..` 越界读在真实 Hermes CLI 13/13、真实 OpenClaw CLI 21/21 均以 `grant_scope_violation` 在宿主读前拒绝；OpenClaw 默认流程另回归 19/19。旧 Hermes 已安装 Skill 夹具迁移到任务级 SEC 后，身份撤销与 Skill 移除两条真实 CLI 腿各 19/19。原版 OpenClaw 无审批后检查点，不能把副本通过记为原版可执行；其他资源组合及跨进程效果仍待验；第四代真实 OpenClaw 链接及链接加 `..` 21/21、直接/普通 `..` 21/21，Hermes 15/15；第五代已安装 Skill 待确认修复及双宿主服务故障腿见下文；原版 hold 与原子性仍 partial |
| LX04 原文与导出 | done | passed_current_scope | 第一代候选双任务合成身份 export/trace-export 隔离 192/192、真实墙钟密文到期清理 19/19；真实 Hermes CLI 原生采集/60 秒授权到期 17/17，单原生任务采集→签名导出联合腿 18/18，双原生任务 A/B 签名导出隔离 23/23；第二代收窄测试 Grant 后的真实 Hermes 原生采集/60 秒自然到期回归 18/18。OpenClaw 双原生任务 A/B 隔离及管理员注销后导出 401 的旅程 30/30，嵌套 R04 31/31。两代候选分别产生 A1=1 小时、A2/B1=24 小时的六条真实 OpenClaw 原生密文，保留状态的旅程均 31/31、嵌套 R04 均 31/31；两代候选各自的真实墙钟原生密文清理复验均 14/14 通过。补充 12 小时管理员会话腿在期限前由项目负责人移出范围，精确停止 watcher/worker/daemon 并关闭专属端口；没有到期后结果，也不记通过。见[取消摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx04-admin-expiry-cancelled-summary.json) |
| LX05 浏览器恢复 | session_race_fixed | partial | 第一代候选四路由慢响应守卫与故障诊断 8/8 通过。真实 daemon + 内嵌 UI + headless Chromium 反例：旧会话延迟 401 在新配对后把页面退回配对；修复 API 会话世代、页面重载世代及同拍重复配对后，同用例 2/2 通过。第八代 scoped 修复进一步关闭 pair/logout 窗口内旧 401 先返回的反向时序，定向 16/16、完整 Web 117/117、两种构建、真实浏览器定向 2/2 与同候选完整 R07 30/30（嵌套 R04 31/31）通过。冻结三次完整 R07 重放首版的驱动兼容失败原样留证；修正后各 R07 30/30 + 嵌套 R04 31/31、phase-c 通过。历史 locator 超时仍未复现，根因未知；有限重放不构成关闭依据 |
| LX06 OpenShell 与性能 | historical_B2_and_taskexec_done; sixth_D05_B3_function_done | function_partial; sixth_B2_S1_S4_not_run | 第一代与第二代候选各自的完整 D05 均为 373 步、365 pass/7 partial/1 blocked/0 fail，13 项 10 pass/3 partial；远端停止确认仍 blocked。第二代 `929bfbe5…` 的 B2 doctor 同轮交错对照：旧/新 p95 152.890/153.692 ms，比率 1.0052，预算通过。随后旧 `70df5455…` 与第二代候选按同一冻结协议、独立沙箱顺序各跑 324 步，S1–S4 p95 分别为 52/91/783/30 与 52/90/770/26 ms，所有绝对预算通过、零失败及零无效样本；这些顺序测量的比率仅作描述，未预设相对门槛。第四代、第五代、第六代各自完成 D05 373 步 365 pass/7 partial/1 blocked/0 fail；第六代另完成 B3 功能旅程 57/57。第六代 B2 与 S1–S4 性能输入已就绪，但按当前“功能链路优先、不反复测试”要求保持 `not_run`，转入后续性能/发行门 |
| LX07 PostgreSQL/OIDC | isolated_runner_done | production_external_pending | 本机固定镜像 `postgres:17-alpine`、空库 Alembic、独立 API 与 loopback RS256/JWKS 测试签发者最新 27/27 通过，新增真实五秒 TTL 的新旧密钥轮换、JWKS 503 拒绝与恢复；含生产拒绝 SQLite/X-Dev、租户/审计隔离及重启。不是客户 IdP、生产 HA/备份验收；容器/进程已清理 |
| LX08 托管源/上游能力 | condition_checked | blocked | 本机三项 GitHub 托管源域名解析均在 198.18/15，仍触发设计内 SSRF 阻断；仅做只读 DNS，未改代理/hosts/白名单，尚未做真实 fetch |
| LX09 文档入口 | done（本地） | docs_review_passed | 中英文 README 已按 #75/#76 更新，英文适配器说明与平台范围决策一致；根级 RESEARCH.md 连接现有文献、研究问题、实现与证据。四份入口文件 246 个本地链接均存在；并补充 OpenClaw 2026.9.4 隔离受控副本 22/22 与原版检查点缺口的版本边界，代码合并和发布仍归 LX10 |
| LX10 总验收与发行 | batch_evidence_assembled | partial | 当前公开清单 97/97、84 条检查引用与 111 个 JSON 摘要绑定值通过完整性检查；正式签名、OpenClaw 原版审批检查点、Windows/macOS 实机和发布是独立门禁。LX04 补充 12 小时腿已移出范围且没有到期通过结论；第六代性能计划冻结未采样，按当前功能优先级不阻塞功能里程碑 |

按本任务书的本地任务门计算，LX00–LX10 共 11 项：5 项完成（LX00–LX02、LX04、LX09）、5 项部分完成（LX03、LX05–LX07、LX10）、1 项受网络条件阻断（LX08）。严格关闭比例为 5/11，约 45%；它不是代码量、工时或整个跨平台产品的完成率。最新安全修复保持 LX01/LX02 已关闭，LX03 仍因原版 OpenClaw 审批后检查点与跨进程效果边界未关闭而保持 partial。LX09 的本地文档复核通过不代表已提交合并，交付整合仍由 LX10 管理；Windows/macOS 实机、正式签名与发行另设门禁。

第六代已装服务联合旅程现已单独复跑：测试签名根构建二进制 `912bfd90…`，生产源码覆盖 550/550 与当前工作树逐项相符；B02 16/16、已装 R07 31/31、直启 R07 30/30，两条嵌套 R04 均 31/31。运行中服务身份、实例 HOME、重启后的状态身份、卸载与同状态回装均核验；专属 unit、端口 25229 和构建目录清理，私有证据 SHA256SUMS 25/25。它关闭的是 LX02 的 `test_release` 门，不等于正式签名或人工桌面验收；严格关闭比例现为 5/11。

[本机 OpenClaw 2026.5.12 原版能力核查](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-2026.5.12-approval-checkpoint.md)确认插件审批的 `onResolution` 不等待异步结果；插件合同没有最终参数的 `beforeExecute` 拒绝检查点，宿主制品也不声明 SIQ 所需的执行复查能力。SIQ hold 在该原版宿主上继续 fail-closed。该静态能力证据解释了 LX03 的外部阻塞，不能替代批准后原生单次效果实测；LX03 仍 partial，总体严格关闭数保持 5/11。

本阶段按用户要求优先验**真实功能链路**，性能、正式签名和跨平台发行门不阻塞功能联调，但保留原任务门状态。第六代又完成[OpenClaw 审批集成定向验收](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-approval-sixth-summary.json)一次运行 18/18：原版宿主 1/1 对 hold 在平台批准前拒绝、零执行/观察；隔离受控检查点副本 17/17 覆盖允许、拒绝、撤权、参数变化和故障，全部回执链验签。原版 OpenClaw **批准后执行仍未跑通**，不能把副本结果转移；LX03 仍为 partial；LX04 按修订后的当前范围关闭后，严格关闭数为 5/11。后续优先修真实功能缺陷，仅做相关必要回归，不重复整套通过矩阵。

[OpenClaw 2026.9.4 隔离升级评估](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-2026.9.4-upgrade-assessment.md)补充了新版真实 CLI × SIQ 第六代候选的基础链路 **19/19**，以及新版原版宿主的 hold 负向 **1/1**：在平台批准前安全拒绝，零执行/预留。新版要求 Node 24.16+（或 26.1+），当前默认 Node 22 不满足；新版也仍无 SIQ 所需的批准后执行复查接口。因此暂不覆盖本机 2026.5.12 安装，LX03 继续 partial。两条新腿只跑了一次，原始报告在私有区，原安装与共享配置未动。

[2026.5.12 受控启动研究入口](openclaw-controlled-start-linux-20260919.md)提供固定补丁复制体的 `prepare`/`inspect`/`run`：定向验证复制、完整性检查、隔离配置下版本启动和篡改拒绝通过。[新联合腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-controlled-start-ui-hold-summary.json)已用 `prepare`/`inspect` 产出的副本复跑内嵌浏览器审批与原生工具，批准一次效果、拒绝零效果，两项通过。网关仍由 harness 而非 `run` 子命令启动；用户安装流程、原版宿主接入和外部效果原子性仍待，LX03 状态不变，入口不能用于 2026.9.4。

[受控启动 `run` × 产品托管安装 × 公共 OpenClaw CLI 原生腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-controlled-start-managed-native-summary.json)另以第六代候选完成 22/22：原生会话和有效 Grant 下允许读取，缺权限写入与授权根外直接/`..` 读取在执行前拒绝，原文采集撤权与身份吊销后不新增授权回执，链验签。子进程注入旧版端点/模式、SIQ 模式、错误 OpenClaw 配置和无效 Node 预加载/模块路径，启动器清除继承覆盖值后链路仍通过。与浏览器审批腿分别计账；两腿均为临时受控宿主副本和合成模型/操作者，原版宿主审批、用户安装生命周期及跨进程效果原子性仍未关闭，LX03 继续 partial。

[Hermes 原生 CLI × 内嵌 SIQ 浏览器确认联合腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-browser-approval-native-summary.json)在同一第六代候选独立完成 24/24：六次原生 hold 经 headless Chromium 在 SIQ 页批准或拒绝；批准后的原参数重试产生一次本地文件效果与观察，拒绝、参数/对象变化、撤权后的重试均无文件效果；旧批准重放拒绝，八方并发预留一项 201、七项 409，20 条回执链验签。原有合成控制台腿仍独立保留；此腿是自动化浏览器和模型夹具，非人工视觉/桌面通知或外部效果原子性验收。LX03 继续 partial。

[受控检查点宿主 × SIQ 浏览器确认 × 原生工具联合腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-controlled-ui-hold-summary.json)又用同一第六代候选完成两项定向实测：浏览器批准后真实原生工具执行一次，签名预留/观察各一条；浏览器拒绝后零执行、零预留/观察，六条回执验签。OpenClaw 宿主是固定指纹的**临时改造副本**，平台审批员、模型与无害文件效果为本地夹具；它证明受控路径中的 UI→批准→执行功能链路，不等于本机原版或新版原版宿主支持批准后执行，也不证明外部效果原子性。LX03 保持 partial。

[OpenClaw 2026.9.4 受控审批摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-2026.9.4-controlled-approval-summary.json)将最新版本从“仅基础链路”推进到独立固定补丁副本的完整原生检查点验收：同一第六代 SIQ 候选、Node 24.18.0 下共 **18/18**，含原版安全拒绝 1、普通审批 6、撤权 2、回调异常/拒绝/未定义/非布尔/超时/取消/参数变化/离线等 9 项；批准路径仅一项效果与一组预留/观察，回执链验签。适配验收驱动同时兼容新版多行拒绝说明、移除的 `canvasHost` 配置、`.mjs` 及重命名 chunk。`openclaw-controlled-start.py` 现在按包版本选择互不混用的 2026.5.12/2026.9.4 配置，并在两版执行 `prepare`/`inspect` 回归，新版另通过 `run -- --version`；共享验收驱动对旧版再跑完整审批链 **18/18** 通过。本机安装仍是 2026.5.12；新版补丁不是上游能力，合成操作员和本地效果也不关闭人工桌面与外部原子性，因此 LX03 仍为 partial；总体严格关闭数保持 5/11。

### 第三代中间候选：符号链接越界修复

真实 OpenClaw 与 Hermes 均复现了旧候选 `929bfbe5…` 的有效只读 Grant 目录内符号链接指向目录外文件仍签发 allow，且受保护夹具内容抵达模型。修复后未签名 Linux/arm64 候选 `36042d1b…`、931 文件源绑定 `e1428502…`：Unix 决策逐次核对词法与实际路径，拒绝不可解析链接；路径同时含符号链接与 `..` 时在规范化前拒绝。真实 OpenClaw 符号链接 20/20、直接和 `..` 越界 21/21、默认流程 19/19；Hermes 14/14；直接 R07 30/30、嵌套 R04 31/31。独立测试信任根的已装 systemd B02 16/16、已装 R07 31/31、嵌套 R04 31/31 也通过。详见[候选身份](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-symlink-guard.json)、[双宿主前后对照](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-symlink-guard-summary.json)及[已装服务](evidence/personal-experience/linux-dual-host-20260918-211200/lx02-symlink-guard-summary.json)。

这是一道决策时保护，不是宿主打开文件的原子沙箱；同 UID 在决策后换链、跨挂载命名空间和 Windows 路径身份仍有缺口，macOS 仅交叉编译。第三代尚未完成独立 OpenShell D05/B2/B3 性能门，不能沿用第二代网关结果；补充 12 小时管理员会话腿后来由项目负责人移出当前范围，未得到到期后结果；LX04 依据原任务范围内的真实保留与导出证据关闭。其余缺口维持 LX03/LX06/LX10 的 partial，严格关闭数为 5/11。

### 第四代历史候选：根目录范围兼容性与同候选复验

进一步组件复核发现第三代把原有合法的 `/` 根范围 Grant 误拒；修复后加入根范围允许与显式拒绝覆盖测试。第四代未签名 Linux/arm64 二进制 SHA256 `a13d6234…`，931 文件源绑定 `b3276b62…`，见[第四代候选身份与逐文件摘要](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-root-scope-final.json)。真实 OpenClaw 链接 21/21、直接及 `..` 越界 21/21，Hermes 15/15；直接 R07 30/30、嵌套 R04 31/31。[同候选双宿主摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-root-scope-final-summary.json)绑定独立私有原始报告。测试信任根已装 systemd B02 16/16、已装 R07 31/31、嵌套 R04 31/31、直接对照 R07 30/30，见[已装服务摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx02-root-scope-final-summary.json)；正式签名仍单独受限。

第四代候选在独占真实 OpenShell 0.0.83 开发沙箱完整 D05 373 步：365 pass、7 partial、1 blocked、0 fail，13 项 10 pass/3 partial，见[功能摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-root-scope-gateway-summary.json)。第三、四代沙箱分别精确删除，三座既有沙箱不变。第四代的 B2/B3 与 S1–S4 性能在该历史节点尚未按冻结协议测量；随后补充 12 小时腿被移出当前范围，已不再构成性能排他条件。Go 全量/vet、受影响包 race 和四目标交叉构建通过，构建不等于异系统实机安全验收。当前严格任务门为 5/11，约 45%。

LX03 又补充了同一第四代候选的**写入**边界：有效的公司 A 读写 Grant 下，真实 Hermes CLI 目录内写入成功、指向公司 B 既有文件及目录外尚不存在文件的两种链接写入均被拒（18/18）；真实 OpenClaw CLI 同样通过（19/19），两侧公司 B 夹具字节未变且新文件未创建。两宿主原默认旅程分别回归 15/15、19/19；共享驱动的 R07 亦同候选复跑 30/30、嵌套 R04 31/31。[写入边界摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-native-write-symlink-summary.json)绑定五份私有原始报告和驱动摘要。OpenClaw 首两轮只因新增写入与既有两条原文采集断言混跑失败，日志原样保留、不计通过；最终写入模式不签发原文采集 Grant，默认模式仍独立回归。此证据增加了资源与动作组合覆盖，但决策后换链竞态、原版宿主审批检查点及跨进程效果原子性仍未关闭，LX03 保持 partial。

同一第四代候选的 Hermes 原生审批链先独立运行 12/12，扩展参数漂移和已消费预留重放为 15/15，再增批准后撤销 Grant 得到 18/18：真实 Hermes `chat --oneshot` 中未批准的写入没有副作用，合成控制台批准后的新 tool-call 重试只产生一次本地文件写入、一条预留与一条观察回执；控制台拒绝的重试未写入；批准后改变内容的原生重试再次 hold、零写入，已消费预留重复提交返回 409、零新增回执；控制台批准后撤销 Grant 的原生重试零写入，签名拒绝回执为 `grant_missing`；回执链验证通过。[当前候选审批摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-approval-current-summary.json)绑定原始私有报告、日志、驱动与宿主 CLI 摘要。该腿使用隔离 HOME、合成模型和合成审核员；本地夹具的一次效果不证明跨进程或外部系统 exactly-once，也不补齐原版 OpenClaw 宿主的审批后检查点。因此 LX03 及总关闭比例不变。

同一第四代候选再以[Hermes 并发批准预留摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-approval-concurrent-current-summary.json)完成第五个真实宿主审批尝试：八个并发 HTTP 客户端对同一新批准以不同 retry ID 提交预留，恰一项 201、其余七项 `hold_execution_already_reserved`/409；宿主后续重试被拒，无第二次文件效果和竞态执行观察，完整驱动 21/21 且回执链验签。胜出的预留未执行外部动作，按 uncertain 保留；这不是跨 daemon 或外部系统原子性证明，LX03 保持 partial。

[Hermes 独立进程竞争摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-approval-process-race-current-summary.json)在相同第四代候选补充 22/22：八个独立客户端进程同时向**同一 daemon**提交不同 retry ID，仅一个获得 201 预留，另七个明确返回 `hold_execution_already_reserved`/409；真实 Hermes CLI 随后重试被拒，目标文件没有第二次写入，回执链验签。胜出预留未执行外部动作，结果仍为 uncertain。此证据比同一进程的八线程竞争更接近真实客户端，但不证明跨 daemon 或外部副作用原子性，因此 LX03 状态不变；总体严格关闭数保持 5/11。

[Hermes 原生对象漂移摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-approval-object-drift-current-summary.json)继续用同一第四代候选跑 24/24：批准原写入目标后，真实 CLI 重试只把目标路径改为授权目录内另一文件，旧批准无法沿用，新调用进入待确认；两个目标都没有写入。内容参数漂移同轮仍被重新确认，八个独立客户端进程的竞争仍为一项 201、七项 409，回执链验签。这里证明的是具体对象绑定和单 daemon 预留边界，未补齐原版 OpenClaw 审批后执行检查点或跨 daemon/外部效果原子性；LX03 仍为 partial。

[OpenClaw 当前候选审批能力摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-approval-integration-current-summary.json)在相同固定候选上重新跑 18/18：已安装原版 OpenClaw 的单独负例证明不支持的 hold 在执行前安全拒绝；另 17 项仅在隔离的检查点 v2 副本中验证批准执行、撤权、参数变化、故障与回执链。已安装原版宿主源码哈希未变。副本通过不能升级为原版宿主具备批准后执行能力，LX03 继续 partial。

[Hermes 同候选更新后旧凭据摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-update-old-credential-current-summary.json)补充真实 V1→V2 安装更新 16/16：V1 Grant 已撤销、Skill 内容摘要改变后，旧 V1 运行身份凭据再请求 `/v1/decide` 得到 401 `unauthorized`，没有新增回执或文件效果；V2 必须重新激活、签发身份与 SEC，原生读取和安全移除继续通过。前四轮因驱动继承参数、可选版本字段和凭据/状态码假设错误失败，原日志私有保留、不计通过。此腿证明旧身份认证失效，不是待批准 hold 跨安装摘要变化后的消费测试，也不是签名 SEC 拒绝；LX03 仍 partial。

同一候选的[Hermes 服务不可达摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-service-down-current-summary.json)再独立验证 9/9：在线原生读取成功作为对照；停掉仅归本腿的隔离 daemon 后，真实 CLI 的读取与写入均拒绝，文件标记未创建、签名回执链不变。共享 SEC 夹具新增可选字段与在线检查数量后，前三轮因驱动兼容性失败，日志私有保留且不计通过；最终驱动按真实在线检查而非固定数量校验。离线写入还缺少窄范围的在线 Skill 权限，故这一腿对服务故障的最直接证明是在线可读、离线不可读。OpenClaw 服务故障另由下述独立腿实测，LX03 因原版审批检查点等边界保持 partial。

[OpenClaw 同候选服务不可达摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-service-down-current-summary.json)为原版 OpenClaw 2026.5.12 的真实 CLI 独立腿，16/16 通过：在线文件写入有正向效果见证；只停夹具专属 daemon 后，原生读写不产生新文件或受保护正文，loopback 接收器的计数没有新增；同端口恢复后，四条离线拒绝补入签名回执链并验签。`exec` 类调用在线本就因未知效果而拒绝，网络接收器只证明拒绝路径零 egress，不宣称授权网络出口或主机防火墙。两个宿主的服务故障腿各自绑定当前候选，原版 OpenClaw 审批后执行仍未通过。

[Hermes 同候选 SEC 自然到期摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-sec-expiry-current-summary.json)以真实 v0.21.0 CLI 的单个 `chat --oneshot` 会话验证最短 60 秒任务级 SEC：到期前原生读取 allow 且归属 verified，真实墙钟到期后另一个文件读取 deny、无受保护正文和执行观察，签名原因 `skill_context_expired`，10/10。测试专用身份观察器只转交 Hermes 生成的会话/任务 ID，不携带 SIQ 权限。[OpenClaw 同候选 SEC 自然到期摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-sec-expiry-current-summary.json)用原版 2026.5.12 CLI 的同一原生会话、不同 CLI 进程独立完成 60 秒会话级 SEC 到期腿：到期前 allow/verified，到期后 deny/`skill_context_expired`，无受保护正文或执行观察，严格断言复跑 10/10。第一轮较弱观察断言的通过记录仅保留在私有目录；两个宿主的这两条独立腿都不证明外部副作用原子性，原版 OpenClaw 审批后检查点仍缺，LX03 保持 partial。

LX04 对同一第四代候选追加了真实本地 daemon 的 A/B 双任务导出负例：200/200 检查通过，其中新增 8 项覆盖 export/trace-export 的短 ID、编码斜杠、编码父目录和 `task_id=../foreign` 注入；有效管理员凭据下均拒绝且无测试原文或其他任务数据返回。[导出边界摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx04-export-malformed-scope-summary.json)绑定私有逐项报告、独立签名验证与驱动摘要。该腿的任务由合成运行身份创建，不能冒充真实宿主原生采集；补充 12 小时管理员会话腿已由项目负责人移出当前范围，不记通过；LX04 按原任务范围内证据关闭。

LX07 的[隔离生产形态 JWKS 生命周期摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx07-postgres-oidc-jwks-rotation-summary.json)在原 21 项之上新增 6 项，真实 HTTP + PostgreSQL 全链 27/27：错误 RSA 签名拒绝，发行者热发布新 `kid` 后无需重启 API 即可验签，旧 `kid` 从发行者移除并经过实际五秒缓存 TTL 后被拒，剩余密钥仍可用；缓存过期且 JWKS 返回 503 时拒绝，恢复后重新接受签名请求。该腿只使用 loopback 测试签发者，不能替代客户 IdP 密钥轮换、HA 或备份验收；容器、API 和签发者均已退出，LX07 仍为外部生产验收待完成。

### LX03 已安装 Skill 待确认投影修复（第五代暂存候选）

真实 Hermes 已安装 Skill 的 `approved`/`adm-si-` Grant 可形成 hold，却被原收件箱投影误判为 `unavailable`。修复确认投影只接受当前可信 Intent 明确选中的同一安装 Grant；未选中、撤销、换绑及非保留导入的 approved Grant 仍拒绝。先运行旧行为失败的定向回归，再完成 Go 全量、vet、receipt/server race 和四目标交叉构建。未签名第五代二进制 `6ce92b69…`、源码绑定 `dbc07ca5…` 已落[暂存候选记录](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-confirmation-fix-provisional.json)。同候选真实 Hermes V1 hold→批准→V2 更新→旧调用重试 **10/10**，旧确认转不可用、零文件效果/预留/观察；OpenClaw 直接 R07 **30/30** 与嵌套 R04 **31/31** 回归通过。见[Hermes 摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-held-install-update-repair-summary.json)与[OpenClaw 摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-confirmation-fix-openclaw-r07-summary.json)。

第五代已独立完成[已装 systemd 测试发行联合旅程](evidence/personal-experience/linux-dual-host-20260918-211200/lx02-confirmation-fix-provisional-installed-summary.json)：550 个生产 Go/内嵌 UI 源文件零不一致、B02 **16/16**、已装 R07 **31/31** 与嵌套 R04 **31/31**、直接对照 R07 **30/30** 与嵌套 R04 **31/31**；私有证据 25/25，实例 unit/端口/运行目录清理完成。正式签名仍独立待验。第五代 OpenShell D05 功能仍含部分项，B2/B3 与 S1–S4 性能同候选门尚未完成，该段记录的是第五代当时状态；补充 12 小时腿后来移出当前范围。当前严格 **5/11、约 45%** 是任务门关闭数，不能解读为第五代候选全部晋升或整个跨平台产品进度；LX03/LX06/LX10 仍为 partial。

第五代的[真实 OpenShell D05 功能矩阵](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-confirmation-fix-provisional-d05-summary.json)现已独立复跑：373 步 **365 pass / 7 partial / 1 blocked / 0 fail**，13 项 **10 pass / 3 partial**；K90 恢复四项通过，本批沙箱删除后原有三座保持不变。E06/E08/E11 仍 partial、E08h 远端停止仍受后端协议限制；B2/B3 与 S1–S4 当前候选性能仍未测，不能移植第四代数据。LX06 与严格关闭比例不变。

第五代再按宿主独立复跑了[服务不可达原生腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-confirmation-fix-service-down-summary.json)：OpenClaw 2026.5.12 公共 CLI **16/16**，在线写入阳性对照成立；只停本腿 daemon 后，原生读写没有新文件效果，loopback 接收器除自检外无新增请求；同端口恢复后四条离线拒绝进入签名回执链。Hermes v0.21.0 公共 CLI **9/9**，在线允许读取、离线读取被拒且不泄露正文，离线写入零标记、回执链不变。Hermes 写入在线时还缺窄 Skill 权限，故不能单独将其离线写入拒绝归因于服务断开；OpenClaw 网络腿只证明被拒 `exec` 的零出口，不声称授权网络路径或 OS 防火墙。两腿均使用本地合成模型与隔离 HOME，私有报告 0600 且驱动/宿主/候选摘要已绑定。LX03 的原版 OpenClaw 审批后检查点和跨进程外部效果原子性仍未关闭，总体严格关闭数保持 **5/11、约 45%**。

针对上述 Hermes 写入归因弱点，新增[同任务服务中断真实宿主腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-confirmation-fix-service-down-summary.json) **12/12**：一个 Hermes `chat --oneshot` 进程、一个宿主生成任务和 SEC，在 daemon 在线时先完成真实读取及文件写入；模型夹具在两个成功工具结果后仅停本腿 daemon，同一原生任务继续尝试读取和写入，均在执行前拒绝、无受保护正文与新文件，签名回执链不变。独立 9/9 旧腿保留作历史对照，不把其离线写入拒绝单独归因于断线。新驱动为 `scripts/personal-experience/lx03-hermes-same-task-service-down.py`，测试专用身份观察器与合成模型均在隔离 HOME 内；单进程本地效果不证明跨进程外部效果原子性。LX03 状态不变；总体严格关闭数保持 **5/11**。

第五代 LX06 的[测前冻结计划](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-confirmation-fix-perf-plan.json)与[任务执行冻结协议](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-confirmation-fix-perf-protocol.md)已落盘：第四代 `a13d6234…` 对照第五代 `6ce92b69…`，B2 doctor 交错三轮保留既有 1.30 相对预算，S1–S4 两个独占沙箱顺序测量且仅用原绝对预算，B3 独立功能旅程不冒充性能。CLI、镜像、驱动、两二进制和 931 文件源绑定均列明。该历史节点因 LX04 worker/daemon 存活而**没有进行性能采样或创建新沙箱**；该补充腿后来取消并精确清理。计划仍为 `not_run`，按当前功能优先要求不启动排他测量；LX06/LX10 仍为 partial，总体严格关闭数为 **5/11**。

第五代[Hermes 已安装 Skill 拒绝确认原生腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-confirmation-fix-hermes-installed-hold-denial-summary.json)最终加严断言后独立通过 **11/11**：有效任务身份与安装 Grant 下写入先 hold、零文件效果；SIQ 收件箱 pending→合成审核员拒绝，签名 resolution 与任务级 hold-status 均为 denied；同一处理重放 409。后续原生新调用经回执断言为新的 hold 且不写文件，没有预留/观察，签名链有效。首轮驱动误用管理 token 查询决策端点而得到设计内 403；修正凭据后的首个通过轮尚缺第二次 hold 的显式断言，两轮均私有保留、不充当最终结果。此腿不修改产品二进制或源绑定，不能冒称真人审核、原版 OpenClaw 批准后执行或跨系统 exactly-once。LX03 状态不变；总体严格关闭数保持 **5/11**。

LX04 当前范围已经闭合；补充 12 小时管理员会话腿已由项目负责人移出范围且没有到期通过结论。第六代 LX06 B3 已完成 57/57，不再列为下一批。LX03 原版 OpenClaw 检查点、跨 daemon/外部效果原子性及 LX06 远端停止继续等待宿主或后端协议。Hermes 已安装 Skill 夹具迁移后的 19/19 属于真实 CLI 与测试专用 SEC 引导的组合证据，不能冒称产品宿主自动签发 SEC。OpenClaw 原版宿主缺少审批后检查点时维持 fail-closed，待可用宿主能力后再做原版原生批准执行验收。当前所有文件仍在本机工作分支，未提交、推送、合并或发布。

### LX03 已批准 SEC 复查修复（第六代暂存候选）

真实 Hermes 已安装 Skill 批准后，在**内容尚未变化**时，原决策凭据读取 hold-status 曾返回 `denied/hold_authority_changed`。根因是复查路径重新执行 Grant 判断却未从当前服务端验证的 SEC 重建 Skill 归属；批准记录本身并未变成执行权。先新增正反用例并在旧实现上复现错误，随后按当前 SEC 重算 Skill ID、版本、内容摘要、上下文 ID、证据等级和原调用绑定；任一差异仍拒绝。已安装导入 Grant 的批准状态与唯一签名预留组件用例通过，Go 全量、vet、receipt race 和四目标构建通过，规格已同步。

[第六代暂存候选](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-sec-hold-fix-provisional.json)未签名 Linux/arm64 摘要 `67bc48c4…`，931 文件源码绑定 `63643d40…`。[同候选原生摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-sec-hold-fix-provisional-summary.json)记录 Hermes 真实公共 CLI 在隔离 HOME 中的安装内容变化 **14/14**：变更前批准状态可读；测试自有 Skill 文件变更后，旧凭据在认证层 401、收件箱不可用，后续原生调用零文件效果/预留且链验签。另独立复跑 Hermes V1→V2 待确认更新 **10/10** 和 OpenClaw 直接 R07 **30/30**、嵌套 R04 **31/31**。旧第五代驱动三次诊断失败只在私有区保存，不计通过；内容变化后的 401 不冒称签名拒绝回执。

第六代已补做已装 systemd 联合旅程及 B3 功能旅程；B2 与 S1–S4 性能仍未测量。第五代已冻结的性能计划**仅作历史记录**，第六代计划已单独冻结；补充 12 小时腿已取消并完成精确资源清理。Linux OpenClaw/Hermes、跨平台与发行的其余缺口没有因此关闭，严格任务门为 **5/11，约 45%**。这只表示本份 LX00–LX10 任务书已关闭的阶段门数，不是整个产品开发百分比。

随后第六代又完成[真实 OpenShell D05 功能复测](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-d05-summary.json)：同候选 373 步 **365 pass / 7 partial / 1 blocked / 0 fail**，13 项 **10 pass / 3 partial**，未关项为 E06/E08/E11；K90 策略恢复 4/4。测试独占创建 `siq-lx06-sec-hold-fix-20260919`，结束后精确删除，原有三座沙箱前后列表一致；共享网关未改配。隔离 XDG 客户端和原始日志仅在私有区。D05 退出码 0 只表示矩阵完整运行，不表示全部验收通过；第六代 B2/B3、S1–S4 性能仍未测量。

第六代[浏览器会话竞态复核](evidence/personal-experience/linux-dual-host-20260918-211200/lx05-session-race-sixth-summary.json)在真实隔离 daemon 和内嵌 UI 上 **2/2**：旧会话迟到 401 没有冲掉新配对，同拍重复提交只产生一个配对请求。历史 phase-c locator 超时本轮未复现，根因仍未知；LX05 保持 partial。补充 LX04 12 小时腿后来取消并完成精确资源清理；按当前功能优先要求不启动性能矩阵。严格总体关闭数为 **5/11（约 45%）**。

第六代另以新专属沙箱完成[OpenShell B3 功能旅程](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-b3-summary.json) **57/57**：产品入口覆盖预览、取消、批准应用、回执、越权拒绝、撤权、回滚及失联拒绝；沙箱精确删除后原有三座名称不变。B3 不是性能测量，也不证明后端单任务远端停止或跨系统原子性。[第六代测前冻结计划](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-perf-plan.json)和[协议](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-perf-protocol.md)已重新绑定第四/第六代源码、二进制、驱动、CLI、镜像、轮次、样本和原预算；第五代计划保留历史。补充 LX04 12 小时腿已取消并清理，B2 与 S1–S4 第六代样本数仍为零；LX06 保持 partial，总体严格关闭数为 **5/11**。

LX10 新增[证据完整性检查器](../scripts/personal-experience/lx10-linux-dual-host-evidence-check.py)：当前公开清单 97 项与实际文件一一对应、84 条检查引用可解析、111 个检查行摘要值在所引 JSON 中可找到；34 个私有目录被忽略且权限合规。原 `checks.json` 后追加的 17 行漏了驱动摘要字段，13 行按当时已绑定证据补回，4 行明示未知；全表仍有 12 行 `driver_sha256=null`，不据此声称运行环境可完全重建。此项只提高交付可复核性，LX04 到期腿和 LX03 原版 OpenClaw 审批执行仍未关闭，LX10 保持 partial。

本阶段执行口径进一步收窄为“本机真实链路和核心功能是否跑通”。第六代 D05 剩余 E06/E08/E11 已完成[残余项审计](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-d05-residual-audit.json)：已运行链路零 fail，E06 只缺本机不存在且任务书禁止临时下载的无 `--wait` 旧 CLI，E08 只缺上游远端单任务停止协议，E11 只缺远端与 CLI 超时来源的结构化区分；没有证据指向新的本机产品缺陷，因此不重复运行 373 步矩阵。第六代性能计划继续冻结，作为后续性能/发行门保留，不阻塞当前功能链路里程碑；补充 12 小时管理员会话腿已按负责人指令取消并记 `out_of_scope`。

[OpenClaw 2026.9.4 受控公共 CLI 托管原生摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-2026.9.4-controlled-managed-native-summary.json)进一步用受控启动器实际运行最新版公共 `agent --local`，同一第六代 SIQ 候选完成 **22/22**：产品托管安装、原生会话自动登记、授权读取、无权写入及有效 Grant 下直接/`..` 越界读取零效果、按任务原文授权后撤权、身份吊销、环境覆盖防护和七条签名回执均通过。全局 2026.5.12 与共享配置未改；最新版仍是固定补丁副本，不能计作上游原版审批能力，LX03 保持 partial。

LX06 第六代测量前预检发现 B2 驱动 `--help` 会在解析帮助前读取实时环境并以 `KeyError` 退出。现已最小修复为先解析参数、离线帮助不接触网关、缺少环境以退出码 2 和固定错误类别结束；离线守卫 **10/10** 通过。修复发生在零样本状态，冻结计划保留原驱动摘要并更新当前摘要；轮次、样本、顺序、预算和协议未改。LX04 不再阻塞采样，但按当前功能优先要求不启动性能矩阵。

[LX06 第六代性能输入预检](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-perf-input-preflight.json)确认第四/第六代候选、计划绑定的 OpenShell 0.0.83、镜像 ID、B2 驱动，以及 S1–S4 主驱动与其两个导入辅助脚本均匹配。S1–S4 现在会在任何实时访问前拒绝辅助脚本漂移，并把三者摘要写入 P00 和最终报告；基础旅程还会先剥离父进程的 XDG/OpenShell 变量再加载私有 env.sh，修复“父 shell 已 source 导致必需输入消失”，同时拒绝脚本未定义的环境污染。新增 6 项 S1–S4 守卫后，与 B2 守卫合计 **16/16**。环境 PATH 当前指向摘要不同的 OpenShell 0.0.13，已明确禁止用于本轮测量；计划使用的受管 0.0.83 制品仍在。该预检没有访问网关、创建沙箱或采样，状态仍 `not_run`，唯一当前前置是 LX04 自然到期腿终态和归属清理。

[LX04 管理员会话到期收口器预检](evidence/personal-experience/linux-dual-host-20260918-211200/lx04-admin-expiry-harvester-preflight.json)已完成 **3/3** 离线守卫：短于真实期限拒绝、原 worker 身份仍存活时拒绝、公开摘要不投影 bearer/cookie。收口器只在私有结果证明同一 daemon 经生产 12 小时期限后 bearer 导出和 cookie 恢复均为 401、worker 已终止、精确归属 daemon 与 loopback 端口均退出时才以排他创建方式写最终摘要；必要清理也只按 PID、starttime 和私有 state 路径三项共同归属发送 SIGTERM。预检本身没有访问 daemon 或写通过摘要；随后负责人取消此腿，watcher/worker/daemon 已按精确归属清理，LX04 按修订后的当前范围关闭。

LX05 定向审查发现 pair/logout 已开始但尚未提交时启动的旧 bearer 请求，与切换操作共享原世代。第七代通过提交时推进世代拒绝晚到响应；反向顺序继续暴露旧 401 可在 pair 成功响应之前先触发全局过期并取消配对。第八代把整个转移窗口标为不可提交，普通请求在解析状态码前以 `LocalSessionChangedError` 退休；确定性用例同时断言过期监听不触发、随后配对成功。聚焦 Web **16/16**、完整 Web **117/117**、企业版与本地内嵌构建、真实浏览器既有路径 **2/2** 均通过。第七代 `06ffd328…` 保留为被替代的中间证据；最终 scoped 候选 `a85c76b0…`、源码绑定 `163d5ded…`，见[候选身份](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-session-transition-final.json)和[摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx05-session-transition-eighth-summary.json)。定向修复后仅补跑一次第八代直接完整 R07/R04；第六代 systemd、OpenShell 与性能证据未迁移。LX05 仍为 partial；LX04 当前范围关闭后总体严格关闭数为 **5/11（约 45%）**。


### 第八代最终 scoped 候选完整功能旅程

为优先确认完整功能链，随后只对第八代最终 scoped 候选执行一次完整直接 R07：真实 OpenClaw 2026.5.12 × 隔离 daemon × 内嵌 UI × headless Chromium **30/30**，嵌套原生更新/移除 R04 **31/31**，候选与驱动摘要均由私有机器可读报告绑定；所属 daemon、Node、Chromium 和临时目录清理完成。见[完整旅程摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx05-session-transition-eighth-r07-summary.json)。本轮没有重复旅程，也没有重跑 systemd、D05/B3 或性能矩阵；第六代的已装服务、OpenShell 与性能证据不迁移。历史 phase-c locator 超时根因仍未知，因此 LX05 维持 partial；LX04 当前范围关闭后严格总体关闭数为 **5/11**。


## 12 小时补充腿范围取消与 LX04 收口

2026-09-19，项目负责人明确要求不再等待补充性的管理员会话连续 12 小时验收。该腿在期限前停止，状态记为 `out_of_scope`，不记 `passed`；预到期导出阳性对照继续保留，但没有到期后的 bearer/cookie 行为结果。watcher、worker 和 daemon 均按 PID、`/proc` 启动时钟与私有状态路径核对后精确停止，专属 `127.0.0.1:51759` 端口已关闭，未使用按进程名批量清理。详情见[取消摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx04-admin-expiry-cancelled-summary.json)。

LX04 原任务范围内的默认不采集、Hermes/OpenClaw 原生采集、采集授权自然到期、A1=1 小时密文自然到期删除、A2/B1=24 小时字节保持、任务隔离、签名导出、默认排除、显式注销撤权和畸形范围拒绝均已有独立真实证据，因此 LX04 调整为 `done / passed_current_scope`。这次范围修订使严格任务门关闭数从 4/11 调整为 **5/11（约 45%）**；其余 partial、blocked、正式签名和跨平台门禁不变。
