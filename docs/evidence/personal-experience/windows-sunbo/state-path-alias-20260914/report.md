# Windows 状态目录尾字符拒绝：实现与验证

本批 Windows 路径定向测试与 76 次原生 CLI 的逐项判据成立；**完整 Go、race 阶段及标准 pytest 入口仍失败，不能宣称 Windows 全部检查通过。** 以下使用已终态材料：完整 Go 退出 1，45 个包均有终态，但仍有两个顶层测试未完成。文中链接对应本批归档摘要，原始私有流通过长度与 SHA 关联。

本补丁针对 [#43](https://github.com/maoyadongsh/siq-agent-security/issues/43)：Windows 状态目录原值中的尾点或尾 ASCII 空格，过去可能在环境读取或路径处理时变成另一个拼写。例如指定 `target ` 后，旧入口可能接受去尾字符的 `target`；现在在状态根仍保留原文时明确报错，避免继续读取或初始化该别名。

实现固定为 DCO 提交 `3461cd5540d9f84b8ebc144c5e7b06424966fcde`，基于 `b303c6f92392f3a44c306d81ad7323c6291ef4f2`。共 27 文件：18 份生产代码、1 份规格、8 份测试。先同步规格 §2.1，再实现 Windows 专属词法检查；现有 API 签名、schema、全局 `product.Env`、非 Windows 选择行为和目录身份算法保持。新增实现仅用标准库。制品和已完成正式阶段均绑定该 clean 候选，历史证据不改标为新候选实测。

Windows 的主/旧状态环境变量以原值选择，仅真正空值回退；非法非空主值不转用旧变量或默认实例。实际使用的默认基目录也在 Join 前校验。检查覆盖尾点、尾空格、中间组件、尾分隔符，以及会被 `..` 折叠掉的坏组件；完整 `.`、`..` 导航、中文和内部空格沿既有规则处理。UNC host 属 authority，保留 FQDN 尾点；share 根与后续目录组件按本次明确输入政策拒绝尾字符。**该 UNC 政策不是 SMB 别名行为的实测结论，本批没有访问真实 UNC。** 正常长路径有本批 CLI 正例，但不据此扩大为所有长路径/命名空间形式的支持声明。

正式状态入口、兼容/Writer、核心配置和凭据、目录身份、初始化/迁移、签名文件、适配器事务验证及显式 serve 在必要的 TrimSpace/Clean/Abs/Join 或状态访问前检查原文。五处拥有者比较也先验证 Store 与非 nil Writer 的原始目录，随后沿用原锁所有权、恢复及服务准备规则。真实 Writer 负向只改公开 Dir，保留原持锁身份；恢复正确值后正常操作并释放。适配器事务的修复针对其状态根，Prepare 仍可能先读取既有的独立 binary/config 准备信息，不能泛称任何文件都不会先读。

`statefs` 复用公共检查，无法还原上层已经丢弃的原始组件；没有遍历重写所有内部 getter。签名 `Load`/`LoadExisting` 的 **env-only seed 分支仍保持原语义**，本补丁的目录拒绝承诺针对其文件分支。hook 沿原 CodeBuddy 映射输出结构化 block，不用单独的非零退出码替代协议拒绝。

| 已完成范围 | 本批实际结果 | 证据与边界 |
| --- | --- | --- |
| 正式定向 Go | exit 0；6 包通过，11 顶层通过；含子项共 42 节点通过（即 31 个非顶层） | [验证摘要](verification-summary.json)。三种分母分开，不称全模块通过。 |
| Windows 原生 CLI | 76 条逐项判据成立，0 超时；2 条 fixture、4 条正向、70 条负向 | [CLI 摘要](native-cli-summary.json)。实际 exit 0 为 36 次、exit 1 为 40 次；负向包含正常输出的 hook 协议响应，不能写成 70 次非零退出。 |
| 旧生产入口 overlay | 两条 Go 命令均 exit 1，均执行选定测试并命中预期旧行为断言；未观察到编译、夹具、panic 或 timeout 失败 | [旧入口摘要](old-entrypoint-summary.json)。这是负向反证成立，Go 命令本身没有 pass。 |
| gofmt / vet / 构建 | checks 8 条命令均 exit 0；gofmt 输出为空，vet 成功；linux/amd64、linux/arm64、darwin/arm64、windows/amd64 构建成功 | [验证摘要](verification-summary.json)、[环境与制品](environment.json)。跨编译不等于外 OS 原生执行。 |
| Schema 标准入口 | exit 4，conftest 导入链缺少 `fcntl`，未开始该批 schema 测试 | [验证摘要](verification-summary.json)。失败保留。 |
| Schema 隔离入口 | `--noconftest` exit 0，206 passed；schema 组合 runner 仍 exit 1 | 隔离通过不覆盖标准入口失败。 |
| race | Go exit 1；6 包中 5 pass / 1 fail；14 顶层中 13 pass / 1 fail；33 子测试 pass，所有启动节点均有终态 | [race 摘要](race-summary.json)。新增 11 项路径顶层均 pass，但整个阶段失败。 |
| 完整 Go | exit 1；45 包：23 pass、16 fail、6 skip。1057 顶层启动：944 pass、63 fail、48 skip、2 unfinished | [完整 Go 摘要](full-go-summary.json)、[前批差异参考](full-go-comparison.json)。包终态不等于所有测试完成。 |

CLI 使用本批 Windows 二进制，SHA-256 `185403e60c6b1e83d23e7fa03d10e635d9930f39df4879702af1153845f5d0d3`；其构建元数据为 Go 1.27.1、windows/amd64、vcs.revision=3461cd5…、vcs.modified=false。四条正例是中文内部空格路径和长路径各自的 init/status。负向覆盖已存在空目录与已初始化目录、主/旧变量、默认基目录、显式 serve 和 hook。显式有效参数覆盖无效环境的选择规则也有定向测试，不能把失败路径验证写成服务已成功启动。

CLI 的 76 对 stdout/stderr 摘要已核验。72 对快照对应 **70 条负向及 2 条正向 status**，全部相等；另外 2 条正向 init 会创建状态，不列入零变化快照。快照覆盖相对条目名、type、attributes、普通文件 size/SHA，**不覆盖 DACL、ADS、file ID、链接计数、时间戳或瞬时 I/O**。端点快照相等只证明这些持久字段没有变化，不能单独证明从未创建过短暂文件；拒绝早于写入还依赖控制流审阅。

15 条 PreToolUse 返回对应事件的 deny/fail-closed；15 条 PostToolUse 返回对应事件且无阻断决定，未据此声称工具实际执行成功。自有 sentinel 的 POST 计数为 0，线程已停止；该计数只覆盖此端点，不代表全系统零网络。未初始化默认目录的 hook 单独失败可能也来自后续缺配置，需结合同行 init 的路径错误与源码前置顺序判断。这里运行的是 Windows 原生 SIQ CLI 组件，`hook codebuddy` 不是 WorkBuddy GUI 验收，也不增加 OpenClaw、Hermes 或 WorkBuddy 原生宿主矩阵通过项。

旧入口反证从 b303 提取 **14 份被修改过的既有生产 Go 文件**，逐 blob 核验并用 Go overlay 替换；4 份新增 helper 和新测试仍保留。它不是整个旧 checkout，也不是全模块基线。环境项实际命中非法主值、旧值及默认基目录未被按路径错误拒绝的断言；单独的 init/trailing-space 项实际命中错误类别不符、成功输出及 fixture 持久变化三类断言。未记录该旧 init 究竟改变了哪些文件及其数量，不能补造细节。两条预期失败不并入新候选通过分母。

race 唯一失败为 `internal/state/TestAcquireWriterBlocksSecondAndTakesOverDead`，命中“stale lock must be quarantined and acquired”，返回 writer busy 类别。测试及 `processAlive` 对应源码与 b303 相同：该 Windows 实现保守地把模拟的持有者视为仍存活，本轮没有完成 stale-lock 接管断言。原流未发现 data race、panic、timeout 或编译失败，但 **无 data race 报告不等于 race 阶段通过**；也不能由此把全模块其他故障都归为既有。

本次新增的 11 个路径顶层测试在完整 Go 中均实际通过；两项 Connector 失败停在发现缺失，未得到危险网络放行结论。原件与源码范围复核见 [失败定位摘要](failure-triage.json)。

完整 Go 实际命令为 `go test -json -p 2 -count=1 -timeout=10m ./...`，记录 elapsed 为 2106.8895433 秒，前后为同一 clean 3461 候选。10,053 条 JSON 可解析；含父/子测试的另一视图是 2298 个节点启动、2085 pass、143 fail、67 skip、3 unfinished，不与顶层分母相加。未启动测试数未知，6 个包级 skip 也不等同于 48 个测试级 skip。

两个顶层未完成项为 `internal/server/TestSkillInstallHTTPOperationStrictness` 和 `internal/skillinstall/TestPendingRemovalPreventsReactivationAndAuditFailurePreservesFiles`；后者的 `/claim` 子测试也没有终态。两包原流均报告自身 `10m0s` timeout，随后包级 fail。冻结 runner 的 `subprocess.run` 没有全程 timeout 参数；2106.8895433 秒是记录的 elapsed，不是 runner 总超时或外部 kill 的证据，也不能把两个包超时相加当作完整运行的时间解释。

与前批 d8a 的非通过清单按包名和顶层测试名比较，当前两项失败未列于前批非通过集合：`TestConnectorsMergeWithoutDroppingNative`、`TestConnectorsNetworkAccessSkipped`。前批包含 PR #56 Connector 修复，本批 3461 不含该改动，尽管两者共享 b303 基线，也不是相同候选的回放；仅记录状态差异，不由名称推断前批一定通过或本补丁引入回归。前批失败的 `TestFindConnectorBinWindowsRejectsSymlink` 当前是 `not_observed`，不能记为 pass。其他同名失败也未据此认定原因相同或全部既有。

本机只读环境观测记录为 Windows 11 专业工作站版、10.0.26200/build 26200、X64、NTFS、PowerShell 7.6.5、非提权。环境观测的实际时序见 [environment.json](environment.json)，不倒填为更早命令的逐次观测。完整 Go 与 cross-build/schema/CLI/race 存在并行执行背景，后续只保留各自记录的时间，不作性能或因果归因。前批 d8a Connector 修复与本批 3461 状态路径修复共享 b303 基线但属于不同改动，前批测试名仅供定位差异，不能替代本批同基线回放。

收尾观察记录为同一 clean 3461 源码；自有验证根是普通非 reparse 目录，根目录 3 条 ACE 满足前置政策。原始前置 SDDL 身份不可用，因而不是 exact SDDL 未变证明，也不覆盖所有后代、产品 ACL 或历史状态。按当时可取得的可执行路径/命令行在私有根内匹配、排除观察器本身，当前匹配进程数为 0；这不是历史进程树或全机器无残留证明。本次 postflight 没有停止进程或删除文件，保留验证目录与夹具。收尾摘要见 [verification-summary.json](verification-summary.json)。

下面是已读冻结 runner 的代表性验证命令；`<...>` 仅替代私有输出路径。六包集合为 `./internal/stateformat ./internal/statefs ./internal/state ./internal/signing ./internal/adapterinstall ./cmd/agentshield`，所有命令在相应 Go 模块或 Control API 目录执行：

```powershell
$packages = @('./internal/stateformat', './internal/statefs', './internal/state', './internal/signing', './internal/adapterinstall', './cmd/agentshield')
gofmt -l .
go vet ./...
go build -o <私有制品路径> ./cmd/agentshield
go test -json -p 2 -count=1 -timeout=5m -run '^TestWindows(StatePath|ServeStatePath)' @packages
go test -race -json -p 2 -count=1 -timeout=5m -run '^TestWindows(StatePath|ServeStatePath)|^Test(AcquireWriterBlocksSecondAndTakesOverDead|WriterReleaseRefusesForeignLock|ConcurrentVersionsPreserveEverySuccessfulWrite)$' @packages
go test -json -p 2 -count=1 -timeout=10m ./...
uv run --locked pytest app/tests/test_schema_contracts.py
uv run --locked pytest --noconftest app/tests/test_schema_contracts.py
```

四次 build 分别显式设置 `GOOS/GOARCH` 为 linux/amd64、linux/arm64、darwin/arm64、windows/amd64；race 分支额外启用 `CGO_ENABLED=1`，使用固定 GCC 12.2.0。旧入口两次命令形状为 `go test -json -p 2 -count=1 -timeout=3m -overlay <overlay.json> -run <expression> <package>`：分别选择 `^TestWindowsStatePathEnvironment$` / `./internal/state`，以及 `^TestWindowsStatePathAliasCommandsRejectBeforeMutation$/^init$/^trailing-space$` / `./cmd/agentshield`。命令返回值和预期失败语义仍按上表分别保留。

Refs #43。本批没有修复 #39 的 runtime 资源绑定或 #42 的 ACL 策略，也没有改变历史证据、发布身份或三宿主验收分母。实现不新增运行架构、依赖或系统权限。证据按 [manifest.json](manifest.json) 记录归档身份，原始含私有路径的流留在本机；公开文件摘要、链接与发布前秘密扫描由归档审阅统一核验。此报告不代表 OpenClaw、Hermes、WorkBuddy 宿主旅程通过。
