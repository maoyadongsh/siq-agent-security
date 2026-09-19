# Linux 双宿主闭环执行报告

状态：本机阶段证据持续收口，更新于 2026-09-19。对应 [LX00–LX10 任务书](linux-dual-host-integration-development-taskbook-20260918-205119.md)与[进度台账](linux-dual-host-progress-20260918.md)。本文按实现、证据和外部条件分别记账；已完成的自然到期与性能计时只归属各自候选和协议。

## 1. 已实施的变更

- 在 `apps/agentshield/cmd/agentshield/client_install.go` 修复首次可信安装的身份建立顺序：验证清单和源二进制后、发布暂存文件前建立持久 seed；历史身份丢失仍拒绝，仅靠安装进程环境变量提供的临时 seed 也拒绝。相应 Go 负向测试与本机规格已同步。
- Linux R07 驱动从创建时限制私有成功/失败报告权限，并修复等待标记缺失时二次异常遮蔽原始失败；OpenClaw 审批集成驱动支持固定候选输入并复核使用摘要。OpenShell 性能驱动可显式声明当前 `main` 已含任务路由，防止沿用旧基点“不具可比能力”的错误标签。
- 新增隔离 PostgreSQL + RS256/JWKS 的企业生产配置形态验收驱动；README 中英文状态、根级[研究链路](../RESEARCH.md)、[平台影响交接](linux-dual-host-platform-handoff-20260918.md)与本批台账已更新。架构调整方案仍只是文档，未搬迁目录。

## 2. 验收结果与证据层级

第一代 Linux/arm64 未签名候选 SHA256 为 `70df54555205ccd6dca9779c5c18a4ccb2b5e1256038db387ff3030d572db02e`，Go/mod/embed 源绑定为 `036df1bd5fdd90d9ecb49f40d3f76761b1b85a03e74843c078600a0bacf77fab`（931 文件）。当时已装服务另使用测试信任根构建 `fe964dabba5a14526bda3a879e1f70c8f4e8a2d517f771a0205e4d354a7c35a3`；其 336 个生产 Go 文件与当时源码一致，但签名身份和二进制摘要不同。随后修复浏览器会话竞态得到第二代未签名候选 `929bfbe5ded6ea0e0c6a76766d5f2dcec84f99fedd3defc530eb63129fcb1935`，其 931 文件源绑定为 `be63b032635ed78be4c743f05fbbbb923c6a252799374fe6dabf094e845ca0af`。下表未特别注明的历史实测仍归属第一代，不能移作第二代验收。

| 任务 | 实际结果 | 证据边界 |
| --- | --- | --- |
| LX01 | 各代修复均完成对应 Go 全量/vet、受影响 race 与四目标交叉构建；当前第六代候选另完成同源真实旅程与 OpenShell 功能复测 | 交叉构建不等于异系统实机；headless 浏览器不等于人工视觉；正式签名独立验收 |
| LX02 | 第六代同源测试发行完成 B02 16/16、已装 R07 31/31、直启 R07 30/30，两条嵌套 R04 均 31/31；卸载、同状态回装、单元与端口清理通过 | 测试发行根，不是正式签名安装验收 |
| LX03 | Hermes 原生审批、SEC、越权、更新、服务故障和内嵌浏览器确认均有独立真实 CLI 证据，最新浏览器腿 24/24。OpenClaw 2026.5.12 原版在缺检查点时安全拒绝；2026.9.4 隔离受控副本审批 18/18、产品托管公共 CLI 22/22 | 测试 SEC/模型/审核员只服务验收；原版 OpenClaw 无审批后检查点，不能声称其 hold 已可执行；跨 daemon/外部效果原子性未证明 |
| LX04 | 当前范围通过：合成双任务导出隔离 192/192、真实墙钟密文到期 19/19；Hermes 原生采集与 60 秒授权到期 17/17/18/18、双任务隔离 23/23；OpenClaw 双任务、签名导出、显式注销撤权、两代 A1=1h 到期与 A2/B1=24h 保留均通过。补充 12 小时管理员会话腿由负责人移出当前范围，记 `out_of_scope`，没有到期后通过结论。 |
| LX05 | 四个慢响应真实 API 路由守卫和 8 项诊断故障测试通过；旧 401 覆盖新会话与同拍重复配对问题已修复。继续审查发现 pair/logout 期间启动的旧凭据请求可在切换前先返回 401 并取消成功配对，最终修复在响应状态处理前退休整个切换窗口请求；聚焦 Web 16/16、完整 Web 117/117、两种构建及真实 daemon/浏览器既有路径回归 2/2 通过 | 第七代候选如实保留为中间修复，第八代 scoped 候选关闭反向返回顺序；不继承第六代 systemd、OpenShell、R07/R04 或性能证据；历史 phase-c locator 超时未重现 |
| LX06 | 第六代候选真实 OpenShell D05 为 373 步 365 pass/7 partial/1 blocked/0 fail，B3 产品功能旅程 57/57；E06/E08/E11 残余已按外部 CLI、后端协议和超时归因条件审计。前代候选 B2 与任务执行 S1–S4 预算证据按各自身份保留 | 远端单任务停止确认 blocked；第六代 B2/S1–S4 性能冻结未采样且本阶段不阻塞功能里程碑；旧性能不得迁移 |
| LX07 | 隔离 `postgres:17-alpine`、空库 Alembic、生产配置 API 与 loopback RS256/JWKS：27/27，含热轮换、旧密钥 TTL 失效及发行者故障拒绝 | 本机测试签发者、单容器数据库；非客户 IdP/HA/备份 |
| LX08 | 三个托管源域名仍解析至 198.18/15，真实 fetch blocked | 未修改 SSRF 门禁、hosts 或代理 |
| LX09 | 中英文 README 与根级 RESEARCH.md 已按当前 main 基线和第六代本地候选边界复核；四份入口文档 246 个本地链接均存在 | 本地文档任务通过；提交合并仍归 LX10 |

第二代候选的新增验收独立记账：[候选身份](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-ui-session-race.json)、[浏览器竞态摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx05-session-race-summary.json)、[已装服务摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx02-ui-session-race-summary.json)及[双宿主原生摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-new-ui-native-summary.json)。旧候选的真实 daemon/内嵌 UI/Chromium 反例中，旧会话迟到 401 把新配对页面退回配对页；修复后同一反例和同拍重复配对两项通过。新候选 Web 测试 116 项、Go 全量 40 包、vet、四目标交叉构建通过，真实 OpenClaw 直接 R07 30/30 与嵌套 R04 31/31 通过。独立 test_release 构建 `ec8ea77654dc25e690fb92993dac48487d31ab2bef05154d16b32769a54b9c9b` 逐一复核 336 个 Go 文件及 214 个 UI 文件，已装 systemd B02 16/16、已装 R07 31/31、直接对照 R07 30/30、各自嵌套 R04 31/31，通过后精确清理单元与端口。两次驱动集成失败分别是缺独立 R07 的保留状态参数、显式注销后复用旧 bearer；修正驱动后复测通过，原失败日志保存在私有证据。第二代另跑 Hermes SEC 11/11、原生审批 12/12、OpenClaw 托管原生 CLI 19/19、原版 hold 安全拒绝及隔离副本 18 场景；不能把隔离副本可执行宣称为安装的原版可执行。第二代的六条真实 OpenClaw 原生密文持久种子旅程 31/31，独立自然墙钟清理复验 14/14 已在服务器期限后通过；历史 phase-c locator 超时仍未复现，不能断言由此次竞态修复。第二代完整真实网关 D05 已跑出 373 步 365 pass/7 partial/1 blocked/0 fail、13 项 10 pass/3 partial，见[独立网关功能摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-new-ui-gateway-summary.json)。按[测前冻结计划](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-new-ui-perf-plan.json)独占完成[B2 doctor 对照](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-new-ui-b2-perf-summary.json)及[任务执行 S1–S4 双候选对照](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-new-ui-taskexec-perf-summary.json)，绝对预算全过；后者没有冻结相对门槛，比率仅描述观察值。两条独立到期验证器均在测量前退出，所有本批性能沙箱均已精确删除。

机器可读逐项结果与局限在[本批公开证据](evidence/personal-experience/linux-dual-host-20260918-211200/)；其中第一代 D05 的[脱敏摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-gateway-summary.json)和[性能摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-perf-summary.json)以 SHA256 绑定各自私有完整报告及样本。B2 doctor 旧/新各 90 个读回样本 p95 153.882/153.759 ms、相对比率 0.9992（≤1.30）；任务执行 S1–S4 有效样本数 45/15/45/45，p95 52/93/768/30 ms，绝对预算四项通过、324 步 0 fail。S3 只测批准后的提交往返；B2 的对照不可当作任务执行的旧版对照。首次性能排他预检失败原样留在忽略提交的私有目录，不计作预算通过。

第二代 Hermes 新增[有效 Grant 的目录越界原生负向](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-grant-overreach-summary.json)：先复现到测试夹具把整个 workspace 授权，故 `company-b` 读取合法；修正 Grant 仅授权 `company-a` 后，同一真实 CLI 中直接路径与 `..` 路径均以 `grant_scope_violation` 拒绝，13/13 通过。最初的夹具失败与错误安全判断已在私有日志及证据报告中纠正，未当作产品缺陷。受夹具变更影响的 60 秒真实原文采集到期腿复跑 18/18 通过。旧已安装 Skill 夹具另经[任务级 SEC 迁移](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-installed-sec-summary.json)，身份撤销和 Skill 移除两条独立真实 Hermes CLI 腿各 19/19；四次旧版缺 SEC 拒绝和中间夹具失败保留私有，不能把测试用观察器误当产品能力。生产 Go、内嵌 UI 与 `929bfbe5…` 二进制均未因这些驱动调整而改变。

OpenClaw 也在同一第二代候选上完成[有效 Grant 的原生目录越界负向](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-grant-overreach-summary.json)：收窄到 `company-a` 后，`company-b` 直接路径与 `..` 路径均由真实原生插件在读取前拒绝，21/21；原默认流程回归 19/19。两腿的模型与操作员是合成夹具，宿主 CLI 和插件为真实安装，原版 hold 检查点缺口仍独立保留。

## 3. 回归命令与状态

- Go：第一代 `gofmt -l`、`go vet ./...`、`go test ./...`、安装相关 `-race` 及四目标 CGO=0 交叉构建通过。第二代 UI 嵌入后另跑 `go vet ./...`、`go test ./...`（40 包）及四目标 CGO=0 交叉构建通过；Web 26 文件 116 项及 `build`/`build:local` 通过。Python 验收驱动的后续修正不改变第二代产品二进制。
- Python：`ruff check` 覆盖本批修改/新增驱动，通过；`pytest -q` 对 OpenShell 协议、D05 守卫和 B04 范围共 32 个测试及 31 个子断言通过，LX05 浏览器诊断另有 8 个故障/拒绝测试通过。LX07 先前第三次实际服务运行 21/21，扩充 JWKS 生命周期后另起独立容器与 API 复跑为 27/27；前两次失败的验收脚本假设及原始报告保留私有。
- 源绑定：按 `openshell-b2b3-perf-protocol.py` 的 931 文件算法，第一代 `036df1bd5fdd90d9ecb49f40d3f76761b1b85a03e74843c078600a0bacf77fab`，第二代 `be63b032635ed78be4c743f05fbbbb923c6a252799374fe6dabf094e845ca0af`，各与自身候选记录相等。
- 文档：中英文 README、根级研究索引与研究目录入口当前共 246 个本地链接零缺失；任务书、平台交接、进度、执行报告和证据入口另做定向链接复核。第二代阶段公开证据清单 `sha256sum -c` 当时 **35/35** 通过；第四代阶段为 **57/57**，第五代阶段为 **64/64**，第六代阶段为 **89/89**，第七代中间修复为 **92/92**；加入第八代最终 scoped 修复与 LX04 取消记录后当前为 **97/97**，84 条检查引用与 111 个 JSON 摘要绑定值由 LX10 检查器验证。公开文件的私钥头、Bearer 凭据、配对码字段、管理员 token 字段及本机绝对路径扫描保持零命中。私有目录、文件权限与 `git check-ignore` 已复核；私有材料在取消清理后已重新计数并通过权限检查。一次临时预检文件初写为 0664，已收紧至 0600 并如实记入资源台账。执行用二进制 0700，非执行交叉构建证据 0600。中间曾因工作目录假设错误而出现清单校验失败，该结果没有用于验收，最终按证据目录相对路径重算并全部通过。

LX05 的[浏览器重放复核](evidence/personal-experience/linux-dual-host-20260918-211200/lx05-phasec-replay-review.json)保留了两批结果：首批三次因新增可选参数兼容错误在浏览器启动前失败，属于验收驱动回归；修正驱动并冻结传递依赖后，连续三次真实 OpenClaw × daemon × 内嵌 UI × Chromium 旅程各 R07 30/30、嵌套 R04 31/31，phase-c 均通过。历史 locator 超时未复现，根因仍未知；有限三次成功不关闭 LX05。

## 4. 未关闭项与解除条件

### 第三代候选的符号链接越界修复

对旧候选 `929bfbe5…` 的独立真实 OpenClaw、Hermes CLI 测试均发现：有效只读 Grant 指向 `company-a` 时，`company-a` 中的链接可读到 `company-b` 的受保护内容，决策签发 allow。修复位于 `internal/receipt/resource_scope.go` 与 `internal/runtimeaction/resources.go`；前者在 Unix 决策时同时检验词法与规范路径，后者保留普通目录内 `..` 合同，但拒绝与现存符号链接组合的 `..` 路径。第三代 Linux/arm64 未签名候选 SHA256 `36042d1b8ae8b305eeac5c83d14486bcfd884d9ac9b56af74e2beb8e7e469880`，931 文件源绑定 `e14285024a855074cd24a5e59261a365a3887b1866b93ce8007bcf5336a2678e`，详见[候选记录](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-symlink-guard.json)。

新候选在真实宿主下：OpenClaw 符号链接 20/20、直接和 `..` 越界 21/21、默认 19/19；Hermes 符号链接与越界 14/14；直接完整 R07 30/30、嵌套 R04 31/31。测试信任根构建 SHA256 `a872b7968319169e5f7b02aad5381e2c3f38ee678fd754e409a33fe168bcef60` 承载已装 systemd B02 16/16、已装 R07 31/31 与嵌套 R04 31/31、直接比较 R07 30/30；所属服务、监听与临时运行目录已按归属清理。修复前两份失败原始日志及修复后逐项报告只存于忽略提交的私有证据，公开[双宿主摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-symlink-guard-summary.json)与[已装服务摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx02-symlink-guard-summary.json)逐一绑定其 SHA256。Go 全量测试与 vet、受影响包 race、四目标 CGO=0 交叉构建及变更驱动 Ruff/py_compile 通过。

保护仍在决策时检查，不保证随后宿主打开文件的原子性；同 UID 链接置换和挂载命名空间差异尚未覆盖。Windows 保留原词法路径行为并需要本机实机安全合同，macOS 只有交叉构建。旧候选 OpenShell D05/B2/S1–S4 结果不可移植到第三代；该候选的 LX06 功能与性能仍待重验。上述修复没有关闭原版 OpenClaw 审批后检查点和跨进程外部效果原子性。

继续审查时发现第三代把原有 `/` 根路径 Grant 的合法范围误拒。新增根范围允许与显式拒绝覆盖测试并修复后，第四代历史未签名 Linux/arm64 候选 SHA256 为 `a13d623492efa0241deb73dcd4b09cbf9ca4c85bb53bca747101b4e9fdd59686`，931 文件源绑定 `b3276b62b40c34a09aff16eeeed931d9549895f2430faa37f4e67724e894fbf9`；逐文件列表与构建摘要见[第四代候选](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-root-scope-final.json)和[交叉构建](evidence/personal-experience/linux-dual-host-20260918-211200/cross-builds-root-scope-final.json)。真实 OpenClaw 链接 21/21、直接与 `..` 越界 21/21，Hermes 15/15；同候选直接 R07 30/30、嵌套 R04 31/31，私有结果 SHA256 列于[第四代双宿主摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-root-scope-final-summary.json)。独立测试信任根构建 `d43a5efa…` 的已装 systemd B02 16/16、已装 R07 31/31、嵌套 R04 31/31、直接对照 R07 30/30，私有证据清单 25/25，通过后所属单元/端口/运行目录均消失，见[第四代已装服务摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx02-root-scope-final-summary.json)。Go 全量测试、vet、受影响包 race、四目标 CGO=0 交叉编译均通过。

第四代候选独立运行完整 OpenShell D05：373 步 365 pass/7 partial/1 blocked/0 fail，13 项 10 pass/3 partial（E06/E08/E11）。第三代同矩阵也跑出相同分类，两次各有单独沙箱和私有矩阵摘要；最终候选原始矩阵 SHA256 `018c8eae03d00fb4bfc2705e8e78a89c4a5b408067b215ac6615c2b116ccc3f1`，见[网关功能摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-root-scope-gateway-summary.json)。最终候选沙箱删除后第一次列表仍短暂可见，随后的只读列表已确认消失，原有三座未变。复制的私有 XDG 配置父目录初建为 0775，但位于 0700 的批次目录内；删除日志也曾初建为 0664。两处已收紧，凭据文件始终为 0600，详见资源台账。**第四代 B2/B3 及 S1–S4 性能仍未按排他协议测量**；等待中的 LX04 管理员会话验证器尚未到期，不能把前两代预算结果移植过来。原版宿主审批后检查点、原子打开和其他 OS 仍为缺口。

第四代候选进一步验证真实**写入**路径：有效公司 A 读写 Grant 下，Hermes 18/18 与 OpenClaw 19/19 均观察到目录内真实写入，而经公司 A 文件链接写入公司 B 既有文件、或经目录链接写入公司 B 尚不存在的文件，均在宿主动作前被拒；公司 B 既有内容未变，新文件未创建。两宿主默认驱动分别回归 15/15、19/19，共享驱动 R07 同候选复跑 30/30 与嵌套 R04 31/31。见[同候选写入边界摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-native-write-symlink-summary.json)。OpenClaw 的前两次尝试触发旧原文采集旅程的固定两记录断言，均作为驱动失败保留、未计通过；写入腿与原文采集授权分开后才取得上述结果。此证据扩大了 LX03 的资源/动作组合覆盖，但不把决策时检查冒称为原子打开或原版宿主审批消费闭环。

同一第四代候选还重跑了[Hermes 原生审批腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-approval-current-summary.json)，真实 CLI 基础腿 12/12、参数漂移/重放腿 15/15、撤权最终腿 18/18 通过：未批准时无写入，合成控制台批准后新调用只观察到一次本地写入及相连的预留/执行回执，拒绝后无写入；批准后参数漂移的原生调用再次 hold 且无写入，已消费预留重复提交返回 409、零新增回执；批准后撤销 Grant 的真实宿主重试拒绝且不写入，签名拒绝原因 `grant_missing`。报告和日志留于被忽略的私有目录，公开摘要绑定二者 SHA256。隔离夹具证明的是本地这条宿主路径，不证明跨进程外部效果 exactly-once，也不提升原版 OpenClaw 的 hold 能力。

[Hermes 并发批准预留腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-approval-concurrent-current-summary.json)在同一固定候选扩展至 21/21：八个同时提交、不同 retry ID 的请求竞争同一新批准，结果为一项 201、七项 `hold_execution_already_reserved`/409；真实原生宿主后续重试被拒，目标文件无第二次效果，回执链验签。成功预留未执行外部动作，状态是 uncertain；该测试限于单 daemon 并发 HTTP，不提升为跨进程外部效果原子保证。

[Hermes 独立进程竞争腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-approval-process-race-current-summary.json)用同一候选和真实 CLI 再跑 22/22：八个独立客户端进程同时向同一 daemon 提交，恰一项 201、七项 `hold_execution_already_reserved`/409；随后原生重试被拒、无第二次本地文件效果，签名回执链通过。胜出预留未执行外部动作、结果仍为 uncertain；单 daemon 证据不外推跨 daemon 或外部系统原子性。

[Hermes 原生对象漂移腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-approval-object-drift-current-summary.json)在相同候选又以真实 CLI 完成 24/24：获批写入对象变更为授权目录内另一文件后产生新 hold，原目标与新目标均未写入；内容漂移、独立进程争抢预留和签名链也在同轮通过。新的私有原始报告及日志分别哈希绑定，不把对象绑定证明外推为跨 daemon 或外部副作用原子性。

[OpenClaw 当前候选审批能力腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-approval-integration-current-summary.json)复测 18/18：原版已安装宿主 1 项不支持 hold 安全拒绝；隔离检查点副本 17 项批准、撤权、参数漂移与故障场景通过，四组签名回执链均通过，安装源码零漂移。副本不是上游发布能力，原版宿主的审批后执行闭环仍待可验证检查点。

[Hermes 当前候选更新后旧凭据腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-update-old-credential-current-summary.json)完成 16/16：V1→V2 更新使旧 V1 凭据在决策入口返回 401 `unauthorized`，零新增回执与效果，V2 新身份/SEC 的真实原生读取与后续移除继续通过。四轮测试驱动假设失败原样保留在私有区。该 401 是认证层拒绝，不冒称旧 SEC 的签名 deny，也不替代待审批调用跨安装摘要变化的真实消费验收。

[Hermes 同候选服务不可达腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-service-down-current-summary.json)在共享夹具兼容修正后 9/9 通过：在线真实读取对照成立；仅停本批隔离 daemon 后，原生读写均 fail-closed，写入标记不存在、回执链不变。前三轮因新增参数与固定在线检查数量假设失败，保留私有失败日志，不算通过。离线写入另缺窄范围在线权限，不能单凭它归因服务故障；OpenClaw 离线行为另由下述独立腿验收。

[OpenClaw 同候选服务不可达腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-service-down-current-summary.json)真实原版 CLI 16/16：在线正向写入成功；只停独立 daemon 后，原生读写零新增副作用，网络接收器零新增命中；同端口恢复后四条待补记拒绝进入签名回执链且验签通过。在线 `exec` 本就因未知效果被拒，因此 egress 腿仅证明拒绝路径无流量；不能冒称已授权网络出口或操作系统防火墙。

[Hermes 同候选 SEC 到期腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-sec-expiry-current-summary.json)在同一真实公共 CLI 会话内越过 60 秒真实墙钟：到期前读取由有效任务级 SEC 允许，到期后另一原生读取拒绝且无正文/执行观察，签名原因 `skill_context_expired`，10/10。隔离的模型与身份观察器是测试夹具。[OpenClaw 同候选 SEC 到期腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-sec-expiry-current-summary.json)则在同一原生会话的独立 CLI 回合验证最短 60 秒会话级 SEC：到期前 allow/verified、到期后 deny/`skill_context_expired`、无受保护正文及执行观察，严格断言复跑 10/10 并验签。两宿主证据独立，均不证明跨进程外部副作用原子性；原版 OpenClaw 的审批后检查点仍待上游能力。

[LX07 JWKS 生命周期实测](evidence/personal-experience/linux-dual-host-20260918-211200/lx07-postgres-oidc-jwks-rotation-summary.json)在另一个专属 `postgres:17-alpine` 容器、生产配置 API 和 loopback RS256 发行者上复跑 27/27：错误签名拒绝、新密钥无重启接受、旧密钥经真实五秒缓存 TTL 后拒绝、发行者 503 时过期缓存 fail-closed、恢复后接受。仅是隔离生产形态；客户 IdP 的真实轮换、HA 与备份仍未验收。 对应 OIDC JWT 定向用例另跑 7/7；`uv` 本批生成的忽略目录 `.venv` 已在进程退出后精确清理。

OpenClaw 原版宿主需要可验证的审批后执行检查点，才能把隔离副本结果提升为用户已安装宿主的批准执行验收；Hermes/OpenClaw 未覆盖的资源组合和跨进程效果仍需各自真实负向。LX04 管理员显式注销后的任务导出撤权已实测；两代候选的原生密文到期各 14/14 已通过。补充 12 小时管理员会话腿在期限前由项目负责人移出当前范围，预到期阳性对照保留，但没有到期后拒绝结果，也不记通过。LX05 已有真实迟到 401 竞态的修复与复测，历史浏览器 phase-c flake 根因仍未知；LX06 第六代候选的 D05 仍有 E06/E08/E11 三项 partial，但 B3 产品功能旅程已完成 57/57，剩余远端停止依赖后端协议。前代 B2 与 S1–S4 预算证据保留在各自候选，第六代性能冻结未采样且不阻塞当前功能阶段。LX08 需可合规到达且通过 SSRF 校验的真实托管源网络；Windows/macOS 由各自协作者按同候选实机验收。正式发行需维护者签名和独立发行门禁，不能用测试信任根替代。

LX04 另以第四代候选的真实本地 daemon 补充双任务签名导出安全腿：200/200 通过，新增八项 export/trace-export 畸形活动 ID 与 `task_id=../foreign` 注入负向，均无测试哨兵内容泄露；签名仍由独立公钥验证。[导出边界摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx04-export-malformed-scope-summary.json)绑定私有报告和驱动。该腿使用合成运行身份，不替代原生宿主采集证据或仍在等待的管理员自然到期结果。

## 5. Git、资源与恢复

本批位于独立工作树 `codex/linux-dual-host-20260918`，基点 `2187fea`；当前所有改动只在本机落盘，尚未提交、推送、合并或发布。历史证据、其他工作树、共享网关配置和已有沙箱未修改。D05 两座及性能专属一座本批沙箱均已精确删除，原有三座保持；复制的 XDG 客户端材料已清理。已完成的早期 LX04 到期腿进程已退出、端口 25224 不再监听；第一代原生保留期验证器在 A1 到期后 14/14 通过并退出；第二代原生保留期验证器也在自身 A1 到期后 14/14 通过并退出；两个独立隔离状态仍保留在忽略提交的私有目录供审计，没有该腿 daemon 监听。新的管理员会话自然到期腿仍保留一座**本批专属**隔离 daemon、一条 loopback 监听和自动复核进程，精确 PID、启动时钟、端口和清理规则在忽略提交的私有种子与公开 `resources.json` 中；到期前不得写“全部进程清理”。B02 新候选的两次脚本集成失败和成功腿均已按归属清理，成功腿单元、端口和运行目录无残留。

产品回退必须按缺陷边界分别处理：恢复 `client_install.go` 会重新暴露首装持久身份建立顺序问题；恢复 `resource_scope.go`/`runtimeaction/resources.go` 会重新允许 Unix 已存在符号链接越出 Grant；恢复 `confirmations.go`/`hold_status.go` 会重新引入已批准、内容未变化的已安装 Skill 被误判权限变化；恢复 `apps/web/src/local/api.ts`/`App.tsx` 及内嵌 UI 会重新暴露旧请求覆盖新会话与重复配对。每组对应测试和规格必须与实现同进退。证据文件只描述其绑定候选，回退源码后不能继续把相应候选结果称为当前实现证据；私有运行材料按归属独立保留或删除。

## 6. 第五代暂存修复候选（2026-09-19）

LX03 的真实 Hermes 已安装 Skill hold 曾被确认收件箱误投影为 `unavailable`：决策引擎允许可信 Intent 选中的 `approved`/`adm-si-` 安装 Grant，而确认投影只接受 deployed/effective。定向测试先在旧实现上失败；最小修复后，只有当前可信 Intent 选中的同一保留导入 Grant 可以待确认，未选中、撤销、换绑和普通 approved 仍拒绝。Go 全量、vet、receipt/server race、四目标 CGO=0 构建通过；规格已同步。

[第五代候选](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-confirmation-fix-provisional.json)为未签名 Linux/arm64 `6ce92b69…`，931 文件源绑定 `dbc07ca5…`，只作修复验收。真实 Hermes CLI 完成 V1 hold→批准→确认更新 V2→旧写入重试 10/10：旧确认不可用、零文件效果/预留/观察、回执链验签。第五代 OpenClaw 直接 R07 30/30、嵌套 R04 31/31。完整脱敏摘要和私有报告哈希见[Hermes](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-held-install-update-repair-summary.json)、[OpenClaw](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-confirmation-fix-openclaw-r07-summary.json)。更新还撤销旧凭据，因此不能把重试拒绝只归因于安装摘要；原版 OpenClaw 审批后检查点及跨 daemon 外部效果原子性仍未关闭。

第五代已独立补做[已装 systemd 测试发行旅程](evidence/personal-experience/linux-dual-host-20260918-211200/lx02-confirmation-fix-provisional-installed-summary.json)：550 个生产 Go/内嵌 UI 文件与候选源绑定逐一相符，B02 16/16、已装 R07 31/31 与嵌套 R04 31/31，直接对照 R07 30/30 与嵌套 R04 31/31；私有证据 25/25 哈希通过，精确 unit、端口和临时目录清理复核通过。测试信任根二进制与未签名候选二进制摘要分开记账，不充当正式签名。该段记录的是第五代当时状态；补充 LX04 12 小时腿后来被移出当前范围。第五代不得继承第四代的网关/性能证据。当前 5/11、约 45% 是严格任务门关闭率，不代表第五代已满足全部门禁或整个产品完成率。新交叉构建文件初建 0775 后已在私有目录内收紧为执行文件 0700、其余 0600，未触碰共享服务。

第五代已经独立完成[OpenShell D05 真实功能复测](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-confirmation-fix-provisional-d05-summary.json)：目标为本批专属沙箱，候选摘要 `6ce92b69…`，373 步 365 pass、7 partial、1 blocked、0 fail；13 项 10 pass、3 partial，E06/E08/E11 未关。K90 四项策略恢复通过，精确删除沙箱后原有三座不变。CLI 0.0.83、镜像摘要、预检、原始矩阵和清理记录均由私有证据 SHA256 绑定；未改变共享网关。同候选 B2/B3 与 S1–S4 冻结性能门仍待完成。该历史节点因第四代 LX04 worker 存活而没有并行性能采样；该补充腿后来取消并精确清理。旧候选数据不移植，当前严格任务门为 5/11。

第五代的[双宿主服务不可达复核](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-confirmation-fix-service-down-summary.json)按真实公共 CLI 分开报告：OpenClaw 16/16，在线文件写入阳性对照、离线读写零新增文件效果、被拒 `exec` 零新增 loopback 到达、同端口恢复后四条离线拒绝补入签名回执链；Hermes 9/9，在线读取阳性对照、离线原生读取拒绝且无正文、写入零标记、回执链不变。两腿执行第五代同一未签名二进制，各自独立 HOME/daemon 与本地合成模型；私有报告摘要、驱动和宿主入口摘要写入公开证据。Hermes 的写入还缺在线窄 Skill 权限；OpenClaw 网络腿无授权出口阳性对照，不证明主机防火墙。进程与临时目录已按本腿归属清理，第四代 LX04 自然到期进程未触碰。这补强 fail-closed 证据，不关闭原版 OpenClaw 审批后检查点或跨进程外部效果原子性，LX03/LX10 仍 partial。

加入两条独立宿主报告后，公开证据清单包含根层文件和既有 `lx06-taskexec-perf/protocol.md` 共 **65 项**。只按根层 glob 生成清单会遗漏该嵌套冻结协议，已在落盘时改为递归枚举公开文件；私有目录继续排除，最终哈希与敏感内容复核以该 65 项清单为准。

Hermes 服务故障腿随后以[同一任务内断线补强](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-confirmation-fix-service-down-summary.json)重新构造并 **12/12** 通过：窄 Grant 对公司 A 读写均授权，一个真实 CLI 任务在在线状态下成功读取和写入；测试模型在两个工具结果后仅终止该腿隔离 daemon，同一任务的后续读写被插件拒绝，无受保护正文、新文件或签名回执链变化。该证据解决早先 9/9 腿离线写入缺在线允许对照的归因不足。测试专用 SEC 引导只传宿主生成身份，合成模型不构成生产模型接入；仍不证明跨进程外部效果原子性。新驱动和三份私有原始报告的 SHA256 均列在公开摘要，批属进程已退出，LX04 等待进程保持运行，LX03/LX10 仍 partial。

第五代后续 OpenShell 测量已经冻结[计划](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-confirmation-fix-perf-plan.json)及[协议](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-confirmation-fix-perf-protocol.md)，列出第四/第五代真实二进制摘要、CLI/镜像、B2 三轮交错和既有预算、S1–S4 两沙箱顺序测量的原预算与 B3 独立功能路径。计划与协议 SHA256 写入第五代候选描述。该历史节点第四代 LX04 worker 仍在运行，故为**零性能样本、零新沙箱**；B2/B3/S1–S4 的第五代状态为 `not_run`，冻结文档不等于性能通过。补充时钟腿后来取消并精确清理；按当前功能优先要求仍不启动性能测量。冻结阶段公开证据清单为 **67 项**，其中包含既有嵌套协议文件；新增 Hermes 拒绝腿后重算为 **68 项**。

LX03 进一步补[第五代 Hermes 已安装 Skill 拒绝确认腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-confirmation-fix-hermes-installed-hold-denial-summary.json)最终 **11/11**：真实公共 CLI 的一个已安装 Skill 任务请求授权范围内写入，hold 前后文件均不存在；SIQ 收件箱 pending 后由本地合成审核员拒绝，签名 resolution、任务级 hold-status 为 denied，重复处理 409；下一次原生写入经独立回执断言为新的 hold 且零文件效果，回执链验签且无预留/观察。首轮驱动误用管理 token 得到设计内 403；修正后的首个通过轮未显式断言第二次 hold，两轮仅私有保留。最终加严断言后独立运行，通过数只取最后一轮。结果只证明单 daemon、本地夹具下的拒绝路径，不能升级 OpenClaw 原版审批后执行或跨系统效果原子性。产品候选源码和二进制未变，LX03/LX10 仍 partial。

## 7. 第六代已批准 SEC 复查暂存修复（2026-09-19）

第五代真实 Hermes 已安装 Skill 在获人工批准后、安装内容尚未变化时，hold-status 错误返回 `denied/hold_authority_changed`。复查权限时遗漏了决策阶段已由 SEC 证实的 Skill 归属，使导入 Grant 的再评估假拒绝；新增定向正反 Go 用例先在旧实现上失败。现在复查从**当前**服务端验证的 SEC 重建归属和原调用绑定，并与签名决策字段精确比较，不复用客户端声明或旧回执作授权依据。未变化者可读取 approved 并取得唯一预留；SEC 消失、撤销或换上下文者仍拒绝。Go 全量、vet、receipt race 与四目标 CGO=0 构建通过。

[第六代候选](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-sec-hold-fix-provisional.json)为未签名 Linux/arm64 `67bc48c4…`，931 文件源绑定 `63643d40…`。[脱敏汇总](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-sec-hold-fix-provisional-summary.json)绑定隔离私有原始报告：Hermes 公共 CLI 安装内容变化 14/14（变更前批准可读，变更后旧凭据 401、收件箱不可用、无文件效果/预留/观察），Hermes 已批准 V1→V2 更新 10/10，OpenClaw 直接浏览器 R07 30/30 且嵌套 R04 31/31。合成模型/审核员和本地文件夹具不构成真人验收或外部效果原子性；变更后 401 是认证层拒绝，不能写成签名 SEC deny。第五代三轮失败驱动私有留存，不计最终通过。

第六代已改变产品源码，故第五代已装 systemd/D05 和冻结性能计划均为**前代证据**，不能当作第六代门禁。第六代已装联合旅程、D05 和 B3 功能旅程已在后续分别补跑；B2 与 S1–S4 性能仍待同候选执行；正式签名、其他 OS、原版 OpenClaw 审批后检查点和跨 daemon 外部副作用仍独立受限。补充 LX04 12 小时腿已取消并精确清理，性能输入虽就绪但按功能优先要求保持 `not_run`。本任务严格关闭为 **5/11（约 45%）**，不代表跨平台产品总体完成率；当前变更仅本地落盘，未提交、推送、合并或发布。

第六代随后以隔离 OpenShell 客户端和[专属沙箱](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-d05-summary.json)完整复跑 D05，373 步 **365 pass / 7 partial / 1 blocked / 0 fail**；13 项 **10 pass / 3 partial**，E06/E08/E11 未关，K90 恢复 4/4。仅删除本批精确沙箱，前后三座既有沙箱一致，共享网关配置未变。原始矩阵/控制台及 mTLS 客户端副本只在 0700/0600 私有区，公开摘要绑定哈希。脚本 exit 0 不代表全部验收通过，第六代性能尚未测量。

[LX05 同候选竞态复核](evidence/personal-experience/linux-dual-host-20260918-211200/lx05-session-race-sixth-summary.json)在真实隔离 daemon、内嵌 UI 和 headless 浏览器上 2/2：旧 401 不覆盖新会话，重复配对只发一项请求。历史 phase-c locator 超时未复现，根因仍未知。补充 LX04 12 小时腿已取消并完成精确资源清理；LX05/LX06/LX10 状态不变，总体严格关闭数为 **5/11**。

第六代[OpenShell B3 产品功能旅程](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-b3-summary.json)在另一座仅归本批的真实沙箱 **57/57**；策略预览、取消、合法批准应用、回执关联、越权拒绝、撤权、回滚与失联拒绝均由产品路由及真实 CLI 观察。沙箱精确删除并复查不存在，三座既有沙箱前后列表逐项一致。B3 不测延迟，也不证明 v0.0.83 远端单任务停止或外部效果原子性。

[第六代 B2/S1–S4 冻结计划](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-perf-plan.json)与[协议](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-perf-protocol.md)在采样前绑定旧/新候选、CLI、镜像、驱动、三轮交错、预热、样本、原绝对预算及 B2 1.30 相对预算；S1–S4 比例仅描述。第五代协议不再作为第六代测量依据。补充 LX04 真实墙钟腿已取消，精确资源清理完成；第六代性能样本仍为零，计划为 `frozen_not_started`。LX06 的 D05 部分项和性能门仍未通过，总体严格关闭数为 5/11。

第六代补做[已安装 systemd 测试发行联合旅程](evidence/personal-experience/linux-dual-host-20260918-211200/lx02-sec-hold-fix-installed-summary.json)：550 个生产 Go/内嵌 UI 文件与本轮工作树逐一相符，测试签名根构建二进制 `912bfd90…`，B02 16/16、已装 R07 31/31、直启 R07 30/30，两条嵌套 R04 均 31/31。服务运行实例 HOME、状态身份、端口、签名 unit、重启 MainPID 与回执历史均按阶段核对，卸载及同状态回装成功；专属 unit、端口 25229 和临时构建目录清理，私有证据清单 25/25 通过。此腿不把测试信任根冒称正式发行，也不代替第六代 OpenShell 性能、人工 GUI 或原版宿主审批后执行检查点；总体严格关闭数为 5/11。

[OpenClaw 2026.5.12 原版审批检查点能力核查](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-2026.5.12-approval-checkpoint.md)固定本机安装包版本及关键文件摘要：`requireApproval.onResolution` 被异步触发而不被等待，批准后宿主直接继续执行；公开 hook 类型和该执行路径没有可返回拒绝结果的最终参数 `beforeExecute`，宿主也不声明 `approvalExecutionRecheckVersion`。因此 SIQ 适配器 hold 继续 fail-closed，不能用回调竞态绕过。此为本机原版宿主静态能力证据，非批准执行通过证据；LX03 保持 partial，待宿主提供受支持的执行前检查点再做真实原生验收。

按本阶段功能链路优先的要求，以**第六代固定候选**只跑一次[OpenClaw 审批集成定向验收](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-approval-sixth-summary.json)：共 18/18，原版本机宿主 1/1 对不支持的 hold 在平台批准前安全拒绝、无外部效果或观察；临时受控检查点副本 17/17 覆盖获批单次预留与观察、拒绝、撤权、参数变化和检查点故障。四组回执链均验签，原版安装文件前后摘要相同，临时副本自动删除。原版宿主的**批准后执行链路未通过**，隔离副本结果不能当作产品原版能力；本轮没有发现新的产品缺陷，故不追加重复矩阵。性能、12 小时自然到期及发行门维持独立待验。

[受控启动公共 CLI 联合腿](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-controlled-start-managed-native-summary.json)在第六代候选上完成 22/22：经 `prepare` 固定包副本、产品 managed adapter 安装、`run` 启动真实 `openclaw agent --local`，验证授权读取、无权限写入及有效 Grant 下越界读取拒绝、原文授权/撤权、身份吊销与七条签名回执。额外向单个原生 CLI 子进程注入会破坏路径或弱化模式的旧环境变量和无效 Node 预加载/模块路径，链路仍通过。此前 21/21 保留在私有区，不合并计数。此结果是合成模型及临时检查点副本验收；原版 OpenClaw 审批后执行、用户安装生命周期和跨进程外部效果原子性仍缺，LX03/LX10 状态不变。

[Hermes 原生 CLI × 内嵌 SIQ 浏览器确认](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-browser-approval-native-summary.json)在同一第六代候选完成 24/24：六次 hold 均经 headless Chromium 页面操作；原参数获批重试产生一次本地效果，拒绝、参数/对象漂移、撤权、重放不产生新增效果；并发预留一项 201、七项 409，20 条回执验签。这补上 Hermes 的浏览器确认链，不替代人工桌面/通知验收，也不证明跨进程外部效果原子性；LX03 保持 partial。

[OpenClaw 2026.9.4 受控审批链](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-2026.9.4-controlled-approval-summary.json)继续使用第六代固定 SIQ 候选，在 Node 24.18.0、自包含隔离 npm 安装上完成 **18/18**：未改造原版保持执行前安全拒绝；独立按 `809c4545…` 目标指纹固定的受控副本覆盖普通审批 6 项、撤权 2 项、回调异常/拒绝/未定义/非布尔/超时/取消/最终参数变化/服务离线 9 项，批准路径仅一次效果与一组预留/观察，四组回执链均通过。驱动为新版补充 `.mjs`/chunk 名、拒绝说明和配置兼容，固定候选输入避免现场重编译。受控启动器现在按版本选择 2026.5.12 与 2026.9.4 两套互不通用的固定配置；两版 `prepare`/`inspect` 通过，新版 `run -- --version` 通过，共享验收驱动对旧版完整审批链回归 **18/18** 通过。本机全局安装仍为 2026.5.12，最新受控副本不是上游或正式升级验收；人工界面、恶意同进程插件和外部效果原子性仍未覆盖，LX03/LX10 保持 partial。

[OpenClaw 2026.9.4 受控公共 CLI 托管原生旅程](evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-2026.9.4-controlled-managed-native-summary.json)使用隔离 Node 24.18.0、自包含 npm 包和产品 managed adapter，通过 `openclaw-controlled-start.py run` 实际启动公共 `openclaw agent --local`，一次运行 **22/22**。权限内读取有宿主效果；无权写入、有效 Grant 下目录外直接及 `..` 读取、原文撤权后新增采集和身份吊销后的新调用均按预期拒绝；七条回执链验签，继承环境覆盖未削弱 block 配置。全局 2026.5.12 未升级；该腿不将固定补丁副本声明为上游能力或正式升级。

LX06 第六代性能执行前的可重复性检查先修复了 B2 驱动帮助路径：`--help` 不再要求实时环境，缺少必需环境返回干净的参数错误而非 `KeyError` 轨迹。随后补齐 S1–S4 主驱动对基础任务旅程与 B2 source-binding 辅助脚本的摘要绑定；任一漂移都会在实时访问前拒绝，P00 与最终报告也会携带三者身份。新增 3 项依赖守卫后，又用 3 项环境加载守卫证明父环境同值不会隐藏脚本导出、脚本未定义的 ambient gateway 不会混入、无关私有变量不会转发；与 B2 守卫合计 **16/16**。这些修复均在首次采样前完成，冻结计划保留每次旧主驱动与基础旅程摘要并绑定当前主驱动、两个依赖及守卫；测量方法、顺序、样本和预算没有改变。

LX06 第六代性能输入预检已确认两代候选、受管 OpenShell 0.0.83、镜像 ID、B2 驱动、S1–S4 主驱动及两个导入辅助脚本摘要均匹配冻结计划；同时识别 PATH 上是另一份 OpenShell 0.0.13，并将其列为禁止误用的环境漂移。预检没有连接网关、创建沙箱或产生样本，性能门已不再受 LX04 阻塞，但按当前功能优先要求保持 `not_run`。

LX04 补充 12 小时管理员会话腿已由项目负责人取消；此前已新增[离线收口器预检](evidence/personal-experience/linux-dual-host-20260918-211200/lx04-admin-expiry-harvester-preflight.json) **3/3**。收口器把“私有结果通过”与“worker 终止、精确归属 daemon 退出、loopback 端口关闭”合成最终证据门，并拒绝把 bearer/cookie 投影到公开摘要；它不会按进程名或端口模糊清理。该预检没有进行实时请求或发送信号，不能替代期限后的实际执行，LX04 状态不变。

按用户最新阶段目标，后续只以真实链路和核心功能跑通为优先，不因性能或本机无法解除的上游条件重复运行全矩阵。[第六代 D05 残余项审计](evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-d05-residual-audit.json)复核了同候选原始矩阵、两份可用 CLI 与产品实现：E06 已覆盖加载窗口、撤权、超时和旧 CLI 拒绝，仅缺无 `--wait` CLI；E08 的本地停止和拒绝边界已通过，远端确认需要网关协议；E11 的输出、非零退出、存储故障均通过，剩余是 `remote_or_cli` 超时来源不可区分。三项均未证明新的本机产品缺陷，故不再重跑 373 步。冻结的 B2/S1–S4 性能计划保留为后续发布门，不计入本阶段功能链路阻塞项。

### 第七、八代 scoped UI 修复：切换窗口内旧请求隔离

定向审查发现此前的 `sessionEpoch` 只隔离了 pair/logout **开始前**的请求；在切换请求已经发出、但新会话或注销尚未提交的窗口内，其他请求仍可能携带旧 bearer。第七代先在切换提交时推进世代，能拒绝提交后的迟到响应；继续做反向时序审查时发现，若旧 bearer 的 401 在成功 pair 响应之前先到，它仍会触发全局会话过期并取消本次配对。第八代显式标记整个 session transition，让普通请求在任何响应状态处理前退休；pair/logout 自身按其转移所有权完成或失败，重叠转移仍由世代拒绝。

聚焦模块测试 `src/local/api.test.ts` **16/16** 通过，覆盖 pair/logout 两个切换窗口、旧 401 先返回不触发过期通知且后续配对成功，以及注销后新请求不再携带 Authorization；完整 Web 测试 **117/117**、`npm run build` 与 `npm run build:local` 均通过。第七代 `06ffd328…` / `5efac528…` 作为中间结果保留并标记被替代；最终第八代未签名 Linux/arm64 scoped 候选为 `a85c76b0…`，源码绑定 `163d5ded…`，见[候选身份](evidence/personal-experience/linux-dual-host-20260918-211200/candidate-session-transition-final.json)和[功能摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx05-session-transition-eighth-summary.json)。真实 daemon + 内嵌 Chromium 2/2 只回归既有“迟到 401 不覆盖新会话、同拍重复配对单请求”路径；精确的早到 401 顺序由确定性模块测试证明。

为优先确认完整功能链，随后只对第八代最终 scoped 候选执行一次完整直接 R07：真实 OpenClaw 2026.5.12 × 隔离 daemon × 内嵌 UI × headless Chromium **30/30**，嵌套原生更新/移除 R04 **31/31**，候选与驱动摘要均由私有机器可读报告绑定；所属 daemon、Node、Chromium 和临时目录清理完成。见[完整旅程摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx05-session-transition-eighth-r07-summary.json)。本轮没有重复旅程，也没有重跑 systemd、D05/B3 或性能矩阵；第六代的已装服务、OpenShell 与性能证据不迁移。历史 phase-c locator 超时根因仍未知，因此 LX05 维持 partial；LX04 当前范围关闭后严格总体关闭数为 **5/11**。

## 8. 可审查交付拆分

当前只形成拆分方案，不执行提交、推送或合并。获得交付授权后按下列依赖顺序组织，每一片先从完整工作树暂存对应文件并检查 staged diff，不能用后续候选证据反向替代前片测试：

1. `agentshield: persist install identity before staging`：`client_install.go`、对应测试及规格中的首装身份约束。
2. `agentshield: reject canonical resource scope escapes`：`resource_scope.go`、`runtimeaction/resources.go` 与正负向测试；macOS/Windows 路径复测要求随平台交接同片审阅。
3. `agentshield: recheck approved installed-skill authority`：`confirmations.go`、`hold_status.go`、SEC/确认测试及规格；不得与第一、二片合并成难以独立回退的大补丁。
4. `web: isolate local session generations`：本地 API、页面、Web 测试和由同一次构建生成的完整内嵌 UI；源码与生成物不能分开提交。
5. `agentshield: add Linux dual-host acceptance tooling`：宿主、OpenShell、保留期、浏览器诊断、受控启动脚本及其守卫测试；固定 OpenClaw 补丁与元数据和调用它们的启动器同片。
6. `docs: record Linux dual-host evidence and boundaries`：中英文 README、研究入口、任务书、进度、执行报告、平台交接及公开证据。公开证据只归属其记录的候选；私有目录永不暂存。

第 5、6 片依赖第 1–4 片形成的候选身份。若审阅期间产品源码再变化，须重建候选并只补受影响的真实功能腿，再更新第 6 片；不能只改摘要字符串维持旧哈希。正式签名、发布和跨平台实机仍不在这些提交片的通过含义内。

## 9. LX04 补充时钟腿取消与当前范围结论

2026-09-19，项目负责人明确取消继续等待管理员会话连续 12 小时的补充实测。该腿在期限前终止，机器状态为 `out_of_scope_by_project_owner`，没有生成到期后 `result.json`，也没有把预到期对照提升为通过。watcher、worker 和 daemon 均按 PID、`/proc` 启动时钟及私有状态路径核对后精确停止，专属端口 51759 已关闭；未使用 `pkill`、`killall` 或模糊端口清理。公开[取消摘要](evidence/personal-experience/linux-dual-host-20260918-211200/lx04-admin-expiry-cancelled-summary.json)绑定私有清理记录。

LX04 当前任务范围所要求的默认不采集、真实宿主原文采集、采集授权自然到期、A1 到期删除、A2/B1 保留、重复清理、任务隔离、默认导出排除、签名导出、显式注销撤权及畸形任务范围拒绝均已有独立证据。因此 LX04 记为 `done / passed_current_scope`，严格任务门为 **5/11（约 45%）**。第六代性能输入已就绪，但遵循本阶段只验证功能链路、不反复测试的要求保持 `not_run`。
