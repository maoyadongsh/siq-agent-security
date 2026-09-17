# Windows Connector 发现修复组件证据

**本机 Windows 全 Go 检查失败，未完成所有测试。** 全模块运行现已终态，原始退出1与失败/未完成计数均保留。此目录保存完整终态材料，已完成独立复核及主任务公开审阅，提交前另核最终目录秘密扫描；材料完成不代表 Windows 平台验收通过。

候选 `d8a66bbdcec988faf2a4e66d3cb7dcfe7e6703bd` 基于 `b303c6f92392f3a44c306d81ad7323c6291ef4f2`，对应 PR #56。五个正式阶段的源码首尾均为该候选且 clean。修复只处理 Windows Connector 的明确 .exe 候选及文件判断，固定绝对路径；不扩大 PATH/PATHEXT、shell 或 shebang 回退，Unix 查找和现有 --serve/NDJSON、限额及权限事实过滤保持。

正式 Windows amd64 组件结果：

| 项目 | 观测结果 | 限界 |
| --- | --- | --- |
| 锁定开发依赖准备 | 两命令 exit 0 | setup旧记录未存runner SHA，公开保留未记录，不倒填 |
| gofmt / vet | 均 exit 0；gofmt stdout为空 | 本机组件检查 |
| 四目标构建 | 均 exit 0；实际制品bytes/SHA逐项一致 | 交叉编译不证明其他OS实机运行 |
| inventory原生测试程序 | 编译 exit 0，执行 exit 1；顶层23 pass、2 fail、1 skip | 整体仍fail |
| 全模块 Go | exit 1；45 已观察包为23 pass/16 fail/6 skip；2个顶层测试未完成 | 详见独立 full-go-summary.json，不称全Go通过 |
| 原有两个Connector测试 | 合并保留native与网络声明拒绝均pass | 使用自建原生fixture，非真实智能体宿主 |
| 标准Schema入口 | exit 4，实际缺少fcntl | 不记为标准入口通过 |
| 隔离Schema检查 | --noconftest下206 pass，exit 0 | 单文件Schema验证，不替代完整Control API测试 |

inventory 两项失败为 `TestFindConnectorBinWindowsRejectsSymlink` 和 `TestMCPSymlinkIsSkipped`，日志均显示创建 symlink 的权限前置错误；尚未到达待验证拒绝断言。因此保留失败和进程退出1，不宣称这两项安全负向通过。原有 `TestDiscoveryRejectsSymlinkAndOversizedConfig` 保留原 skip。完整26个顶层结果见 native-inventory-summary.json，布局子例不重复计数。


全模块命令为 `go test -json -p 2 -count=1 -timeout=10m ./...`。runner 的 subprocess.run 没有 timeout 参数；记录 elapsed=1800.6087021999992秒不构成“runner 1800秒全局超时/杀进程”。Go 原流明确记录 `internal/server` 与 `internal/skillinstall` 各一次 `panic: test timed out after 10m0s`，二者随后都有包级 fail。45个已观察包均有终态；这与所有测试完成不同。

全模块顶层测试启动1066项：954 pass、62 fail、48 skip、2项无终态。含父/子测试节点的另一视图为2297 run、2085 pass、142 fail、67 skip、3节点无终态，不能与顶层计数叠加。未完成的是 `internal/server: TestSkillRemovalHTTPAdminAndStrictRequest`，以及 `internal/skillinstall: TestInstalledRuntimeBindingAndImmediateInvalidation` 和其 `/instance` 子例。未启动测试数未知；不根据包级终态补造测试结果，也不把全部其他失败归因为本补丁或未经同范围基线即称既有问题。

命令 started_utc、monotonic elapsed 与首末 Go JSON Time 原样分列于摘要；不从墙钟算术推断外部kill或时钟变化。

四个构建输出身份：

| 目标 | bytes | SHA-256 |
| --- | ---: | --- |
| linux/amd64 | 24602145 | d5d79b5b8f79bd200598106ff8c559ae689583a96be4c84abb7d263f5241ca7d |
| linux/arm64 | 23164984 | 30e7e03a4cd55d5005047add5d920d2fbb52b959c8f322abb693ac788e33dd54 |
| darwin/arm64 | 23485458 | b69d077d1423f911f95ee3c0389935e566ab3883b177e513a0fda123dd8c4d0b |
| windows/amd64 | 24717824 | 8ce8b85590bef0d574ca0afb58d612ee17fdffdf46f5a3338b22bd6e30bb5a27 |

提交前开发期的定向8个顶层测试通过；使用 Go overlay 仅恢复旧 findConnectorBin 后，布局/dot-root/合并三项均失败，另一次原两个Connector断言均失败。这是新原生fixture对旧函数的回归证明，不是完整旧版本实测，不把开发快照写成正式clean候选。提交前独立九文件静态审阅未发现阻止性问题，相关来源仅以逻辑角色和摘要引用。

同一候选的 Ubuntu CI 最终为38 success、3 skipped；实际两个Go job测试的是PR合成merge `5b36f7859ee2c0a913c2e7c1d1d7335495dcef67`。新增merge-parent原件确认其两个parents恰为基线b303与候选d8a，未将merge身份改写成head。Go1.22.12兼容任务39个测试包通过，但扫描实际报告33项可达标准库漏洞，不能称CVE-clear；严格Go1.26.6任务39个包race通过，实际扫描输出No vulnerabilities found。CI的Linux运行及四目标构建与本机Windows结果分开，不能用它们关闭本机symlink前置缺口。

前轮已独立核对13份命令JSON、26份原始流及5份二进制摘要；本轮新增核对full-go的1份命令记录/summary及2份原始流，共14命令、28原流、5二进制；每个正式阶段summary与命令记录一致，构建完成后追加的binary字段另与实际文件核对。公开只包含白名单计数、退出码、测试名、工具/制品身份与来源SHA，不复制私有命令路径、SID、环境值、原始stdout/stderr或测试目录内容。setup缺失runner字段按原记录保留；其他四个阶段记录的runner摘要与现文件一致。

这是组件适配修复证据，不填写真实Hermes/OpenClaw/WorkBuddy宿主矩阵pass，不改变原18行分母，不冒称Windows平台验收完成。原始失败和原件仍私有保留，本终态候选不会覆盖它们。

后置原件记录候选d8a仍clean、私有目录与父目录ACL未变、允许ACE=3；限定范围的进程观察为0匹配，无进程终止和文件删除。范围仅为可执行路径位于私有根或命令行包含该根，排除观察PowerShell；不外推为全机无相关进程或OS隔离。公开来源已增加本批OS观测、merge-parent证明及postflight的逻辑角色/字节/SHA，原路径、SID和原流保留私有。
