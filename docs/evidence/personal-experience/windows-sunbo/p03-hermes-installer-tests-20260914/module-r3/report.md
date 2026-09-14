# PR #48 Windows 全模块检查补充（r3）

固定候选 `2f84d5af6934f3cc17354107f66beae6dc8e1b59` 的 Windows 原生 `go vet` 通过；全模块测试命令退出 1。10 个包出现明确的 90 秒包预算超时，另有已输出终态的实际断言失败，因此本轮不能记为全模块通过。源码在两阶段前后均为该候选且 clean；相对基线 `b303c6f92392f3a44c306d81ad7323c6291ef4f2` 仅修改两个 adapterinstall 测试文件，生产实现未改。

| 检查 | 命令（工作目录 `apps/agentshield`） | UTC 起止 | 结果 |
| --- | --- | --- | --- |
| 模块 vet | `go vet -p=2 ./...` | 2026-09-14 05:33:45.583954—05:34:21.228738 | exit 0，空输出 |
| 模块测试 | `go test -json -p=2 -parallel=1 -count=1 -timeout=90s ./...` | 2026-09-14 05:34:22.576512—05:47:17.981970 | exit 1，未触发 900 秒外层超时 |

测试日志包含 6,416 条 JSON 事件，无非 JSON 行。以下层级分别统计，不相加作为用例或缺陷总数。

| 终态层级 | pass | fail | skip |
| --- | ---: | ---: | ---: |
| 包（45 个） | 21 | 18 | 6 |
| 顶层测试 | 577 | 41 | 34 |
| 子测试 | 556 | 52 | 12 |

6 个包级 skip 的输出为无测试文件。测试级 skip 保留在事件中，未计为通过。41 个顶层 fail 与 52 个子测试 fail 会包含父子汇总关系，不代表 93 个独立问题。另有 10 个顶层、5 个子测试仅有 run 而无 pass/fail/skip，记录为未完成；因包超时而未开始的测试数量未建立完整分母，不能当作已测试或已通过。

本补丁两条被修改测试在 r3 仍实际通过：`TestUninstallOfOneInstanceRestoresOnlyThatInstance` 5.43 秒、`TestHermesControlledInstallPathChecksBeforeNativeInstall` 1.82 秒。adapterinstall 包没有测试级 fail，包级 fail 来自 90 秒预算在 `TestCodeBuddySurgicalUninstallKeepsUserSettings` 期间耗尽。[r2](../r2/report.md) 已在同一 clean 候选完成整个 adapterinstall 包（59 个顶层 pass、12 skip，42 个子测试 pass、5 skip，exit 0）；r3 的预算截断不能改写为该补丁回归，也不能据两条通过把 r3 包终态改为 pass。

## 明确超时与未完成范围

以下仅按日志中 `panic: test timed out after 1m30s` 认定。运行中用例的括号时间来自 Go panic 输出，表示当时该用例已运行的时间，不是该用例独占了全部 90 秒，也不足以证明死锁或性能回归。包终态 elapsed 可包含收尾开销，不能单凭其超过 90 秒认定另一个超时。

| 包（省略模块前缀） | panic 时运行中用例及日志时间 |
| --- | --- |
| `cmd/agentshield` | `TestServiceUpgradeFailedTargetRecovery`（2s） |
| `internal/adapterinstall` | `TestCodeBuddySurgicalUninstallKeepsUserSettings`（1s） |
| `internal/intent` | `TestBindingRevocationInputAndCapacity`（10s） |
| `internal/provenance` | `TestGraphNodeAndEdgeCapacityBoundaries` 与 `/nodes`（均 1m20s） |
| `internal/receipt` | `TestGlobalIntentRevocationHardDeniesEveryModeAfterRestart` 与 `/block/required`（均 1s） |
| `internal/runtimecheck` | `TestAuditFailureNeverStartsHostOrReportsPass`（5s）、`/at_finish`（3s） |
| `internal/server` | `TestApprovalChallengeInvalidatedByPatch`（6s） |
| `internal/skillimport` | `TestReviewerGitFetchRejectsPrivateDNSBeforeTransport`（1s） |
| `internal/skillinstall` | `TestInspectionSeparatesHistoricalRecordAndCurrentContents`（43s）、`/type_changed`（14s） |
| `internal/state` | `TestMigrationFullBackupAndEveryCheckpointRecovery`（27s）、`/backup:1`（8s） |

其中 cmd、runtimecheck、server、skillimport、state 在超时前已另有测试级 fail；另外 5 个超时包没有测试级 fail。本轮不重跑、不放宽断言或跳过测试。后续应先按包制定足够的预算，再判断仍未完成用例的真实行为。

## 已发生失败的初步分类

以下依据本轮日志和固定候选的最小源码核对；没有完整基线 A/B，因此不统称为“原有失败”，也不归因于本次两文件测试补丁。完整包终态、每条失败诊断及未完成列表见 [analysis.json](analysis.json)。

| 类别 | 实际观测与源码边界 | 后续责任/验证 |
| --- | --- | --- |
| POSIX 平台测试假设 | 4 组 LaunchAgent 用例在构造阶段返回 canonical absolute path 错误；`TestPrepareRollbackMissingBinary` 返回 systemd service-unit 路径约束错误。源码 fixture 使用 POSIX 路径/服务模型；尚未进入对应平台真实生命周期。 | 平台测试维护者明确适用 OS，保留 POSIX 安全断言，Windows 用独立可表达的模型验证。 |
| 符号链接/打开文件 fixture 条件 | cmd、effectevidence、inventory、runtimeidentity、skillmanifest 的部分 fixture 创建 symlink 报缺少权限；admission 的 `TestAddFileDetectsReplacedInode` 删除仍打开文件被 Windows 共享语义拒绝。 | 修复测试便携性，保留原始失败；不通过提权或改变日常系统设置绕过。当前失败没有验证到原本的负向产品断言。 |
| JSON 与 connector fixture 便携性 | adapters 单条测试缺 admission/verdict；其 fixture 拼接未转义的 Windows 路径。inventory 两条 connector 测试返回 `connector_missing`，其 Unix shebang/可执行位 fixture 不满足 Windows 发现入口。 | 维护者适配 fixture/平台入口后原生复验；不能写成真实 Hermes/OpenClaw 不存在，或归咎于 Python 缺失。 |
| Windows 资源路径合同候选缺口 | completion 与 effectevidence 多条实际返回 `file_observation_unavailable`；与 Windows 资源路径不可按现行规范表达的既有 [Issue #39](https://github.com/maoyadongsh/siq-agent-security/issues/39) 边界相关。runtimecheck 两条输出 `runtime_check_intent_failed`，另有 `launch not reached`，本轮未单独证明其每条完整根因。 | 共享合同/核心 owner 先确定 Windows 路径合同并保留拒绝边界；本批不替换斜杠或放宽规则假通过。runtimecheck 后续随合同修复逐项复验。 |
| 权限表达差异与产品边界待核 | pending 断言 0600 但读到 0666；runtimeidentity 正向检查 `Mode().Perm()==0600` 失败，其 `/permissions` 子例 `Chmod(0644)` 后仍能 Authenticate。 | 这些 Go mode/Chmod 观测不是 DACL 认证，也没有实测其他登录身份。与 [Issue #42](https://github.com/maoyadongsh/siq-agent-security/issues/42) 的既有真实 ACL 复现分开，由单一共享 owner 定义 Windows 私密读取合同。 |
| 产物可执行性与辅助工具边界 | skillmanifest 下载 fixture 期待可执行位，Stage 多条实际被 `stage source is not executable` 拒绝；Python fetch 返回 `no artifact for windows/`；shell resolve 负向只记录预期诊断缺失。 | 不只改期望值掩盖生产 Stage 的可执行性判断。分别协调 Windows 产物合同/平台识别和 shell fixture；Python 平台识别及 shell 失败的精确根因仍 unknown。 |
| 合同样例差异 | runtimecheck 报 `incoherent runtime outputs`；server 报 `adapter-plan.v2.json` drift；skillimport 报 `local-skill-import-result.v2` sample differs。 | 核对平台相关输出与共享样例，不据此推断 schema 本身无效，不在本补丁中修改合同快照。 |
| 尚未定位 | cmd sync 输出 empty inventory 并未达到预期 401 失败；skillimport 两条本地 Git fixture 返回 download failed；state 的合成死 PID 锁没有接管。 | 保留真实断言及上下文，按 Windows HOME/子进程环境、Git 路径、进程存活判定分别最小复现；本轮不声称根因已证明。 |

## 环境、隔离与清理边界

本机为 Windows 11 专业工作站版 25H2、build 26200.8875、amd64、NTFS。受控官方 Go 为 `go1.27.1 windows/amd64`，CGO=0、工具链 local、telemetry off，实际身份与 SHA 见 [summary.json](summary.json)。本轮复用先前自有私有 Go build cache，未重写先前测试日志；新建独立受保护 NTFS 根和合成 HOME/USERPROFILE/APPDATA/TMP 等路径。根 ACL 前后均为 3 个明确 FullControl ACE（当前用户、SYSTEM、Administrators），无宽泛 ACE；未修改父级或用户日常目录 ACL。

Go 子进程使用环境白名单、GOPROXY/GOSUMDB off、空 Git 全局配置/模板且禁交互，没有真实宿主 opt-in 或模型凭据。PATH 包含实际已安装的 MSYS2 mingw64 `python3.exe`（CPython 3.10.10、`sys.platform=win32`）与 OpenSSL 3.1.0，也保留受控 PowerShell 路径。未创建 Python shim、未安装依赖。该辅助 Python 版本低于仓库通用 Python ≥3.12 开发约定，本轮仅如实记录现有按名称查找工具的 Go fixture 行为，不代表完成 Python 模块测试；控制器 Python 为 3.13.7。实际工具 SHA 均有记录。

“禁 Go 下载/白名单环境”不等于 OS 网络隔离：既有测试可对固定 `localhost.localdomain` 使用系统 DNS；HTTP 使用临时 loopback/injected fixture；Git 使用合成本地仓库。Windows Task Scheduler 覆盖仅内存 TaskDefinition/解析和随机任务名的只读查询，没有注册、启动或修改日常任务。控制器只读 Git/ACL 命令不使用同一完整子进程白名单；部分既有测试自行构造子进程环境，也不能声称所有后代环境完全相同。

已执行 [runner](run-windows-module-checks-r3.py) 的顶部 docstring 沿用旧的 “adapter installer test fix, offline” 标题。保留其执行时字节/身份；实际范围以 argv、上述环境限制和结果为准，该旧标题不能作为全离线声明。

两阶段 Go 直接子进程均被 wait 回收，未触发外层 taskkill。2026-09-14 05:52:38.9775823Z 的独立 CIM 快照显示最终 Go PID 不存在、可见进程中匹配本轮私有根的 executable/commandline 数为 0，详见 [process-observation.json](process-observation.json)。这是一时点观察，不是所有历史后代逐个回收成功的证明。保留私有 fixture 与日志供审阅，没有删除证据。

本轮为 Windows 组件/模块检查，未做真实 Hermes 安装或工具调用验收，未启动三宿主，也未生成新的发行 SIQ 二进制。POSIX 实跑与四目标构建由 PR 的独立 CI 证据说明，不能把 Darwin 交叉构建当 macOS 实机测试；本包不重复计入该 CI 结果。

## 证据与公开派生

原始模块日志私留且未改：1,555,847 bytes，SHA-256 `06f21b5f45918f9e1cf18bd53c8398f1eff99dc4d1f1d3f716d3f11135499aba`。公开 [module-tests.jsonl](module-tests.jsonl) 为脱敏派生，1,585,317 bytes，SHA-256 `7d616fc573cc1bdb9c0d37c409c58fc2e10325cb9df587462975bca856ad5232`，不能代称原始日志。

独立审阅发现首次公开派生第 15 条事件的 Output 内嵌 JSON 路径因双重反斜杠残留。新增 [derive-public-results.py](derive-public-results.py) 从未改的私有原件进行二次派生，仅该条 Output 改变；6416 条事件的非 Output 字段均保持一致，未修改执行过的 runner 或原始日志。两份公开 summary 同步了新的派生长度/SHA，并保留旧派生身份与处理方法。重建时提供 runner 中同角色的本机路径参数；公开包不包含这些私有路径。

[verification.json](verification.json) 记录源身份、重新解析计数和字节核对；[manifest.json](manifest.json) 列出除自身以外每个公开文件的 bytes/SHA。原始失败、包超时、skip 和未知分母均保留。全部结论来自同机执行/审阅，不是独立 OS 复现或完整三宿主验收。
