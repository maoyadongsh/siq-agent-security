# Windows Go 制品暂存组件复验

关联 [Issue #63](https://github.com/maoyadongsh/siq-agent-security/issues/63) 和 [PR #73](https://github.com/maoyadongsh/siq-agent-security/pull/73)。Windows 普通文件没有 Go POSIX 执行位；旧实现因此连真实自建 `.exe` 都在摘要校验前拒绝。本批先补规格，再仅将执行位检查限定于非 Windows。普通文件检查、源/副本/pin 摘要、排他复制及失败清理不变。

## 受测身份

- main 基线 `9b8c09af742cb9df94c6d02e6f2db6ecccd68951`；实现随后原样提交为 `ab5a6d2502e0e1c246650a319fe3d2ab5342686c`。
- 测试与构建启动时是基线加本批未提交修改；制品 buildinfo 明确为基线 revision、`vcs.modified=true`。不能称为干净最终候选。实际变更文件字节摘要及四制品 SHA256 见 [verification.json](verification.json)。
- Windows 11 10.0.26200 amd64，Go 1.27.1；Python 3.13.7 + 仓库锁定 dev 依赖。模型调用为零。

## 实际执行证据

旧代码执行新增两个 Windows 测试均失败：真实测试程序报 `stage source is not executable`，错误 pin 用例也未到达摘要拒绝。[原失败](before-fix.log)保留。

修复后以 `os.Executable()` 取得自建 Go 测试程序，固定源摘要，暂存到测试专属目录。检查副本为不同普通文件、名称及长度一致、摘要相同；用绝对路径直接启动副本的唯一 probe 测试。子进程复查实际程序路径，stdout 必须严格为 `SIQ_OWNED_STAGED_EXE_OK` 加 LF，退出 0；运行前后源及副本摘要均不变。错误 pin 必须在创建 stageRoot 前被摘要拒绝。无 shell、PATH 搜索、外部下载或模型参与。

这是真实 Windows loader 启动暂存副本的组件证据；不是任一 Agent 宿主旅程或客户端升级成功。Windows 允许复制普通无执行位文件，不以扩展名/PE 解析代替既有信任。`Chmod(0700)` 不证明 Windows DACL 私有，#42 仍独立处理。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 新增测试在旧实现上 | exit 1，两项失败，见原失败日志 |
| 暂存与下载针对性测试 | exit 0，7 项通过，见 [targeted.log](targeted.log) |
| gofmt -l . / go vet ./... | 均 exit 0，gofmt 无文件 |
| 完整 skillmanifest 包 | exit 1；符号链接权限、Python 制品架构、shell 错误输出三项失败；另一个 shell 暂存用例因未准备约定 repo binary 而 skip |
| 完整 Go 首轮 | exit 1；并行运行遇到 120 秒包超时，原始结果保留，不作为完整回归通过 |
| 完整 Go 复验 | `go test -p 2 ./... -count=1 -timeout 10m`，PYTHONUTF8=1；exit 1，16 个失败包，2 个超时 |
| 四目标构建 | linux/amd64、linux/arm64、darwin/arm64、windows/amd64 均 exit 0 |
| 锁定环境 Schema | `uv sync --dev --locked` 后 `PYTHONUTF8=1 uv run --locked pytest --noconftest app/tests/test_schema_contracts.py`，214 passed，见 [schema-locked.log](schema-locked.log) |

Schema 首次未设 UTF-8，遭遇 GBK 解码失败；第二次仅设 UTF-8，仍缺锁定依赖 rfc3339-validator。第三次使用本工作树锁定环境后通过，没有修改 Schema 或删减日期负向断言。完整 Go 失败包/测试名与原始日志摘要采用白名单公开，原始路径和测试上下文保留在本机私有材料。

另外只读检查执行环境：PATH 中 `python3` 指向 MSYS mingw64 解释器，其 `platform.machine()` 返回空字符串，而原生 Python 3.13.7 返回 AMD64；PATH 中没有 `sh`。因此 Python 制品选择和 shell 错误输出失败有明确环境原因。没有改全局 PATH、伪造平台值或将这些用例跳过；符号链接权限不足也未通过提权/关闭防护绕过。它们不等于 Windows 暂存函数仍要求 POSIX 执行位。

随后仅在测试进程 PATH 前置现有 Git `bin`，重跑 shell 拒绝用例：脚本已实际启动，但仍在 binary-not-found 检查退出，没有到达该用例预期的摘要失败，因此测试保持 fail（[诊断日志](shell-explicit-path.log)）。这比初次缺少 shell 的空输出更具体；没有以“脚本拒绝了”冒充摘要负向通过，也没有因此改动 Python/shell bootstrap。

复现：在 Windows 使用此实现的 `apps/agentshield`，执行 `go test ./internal/skillmanifest -run '^(TestStageVerifiedBinary|TestDownloadVerifiedArtifact)' -count=1 -v`。新 Windows helper 自动执行自己的 staged 副本；它不需要系统重启、管理员、宿主模型额度或现有用户配置。

## 剩余范围与清理

本批未改运行时 Authority、Windows 路径合同、适配器或三宿主配置。所有暂存 probe 子进程由命令等待回收，针对性测试临时目录由测试清理；全模块超时包的临时目录不在此声明已清理，原始日志保留待核查。源码、构建产物和私有日志保留用于复核。无计划任务、系统重启、注销、睡眠、防护设置或日常实例变更。

303 台账不因本组件修复增加通过项：保持通过 54、失败 3、受阻 8、未测 238，另用户排除系统中断 3 项。整体 Go 和三宿主闭环、最终候选、独立证据复核仍未完成；完整失败不得由针对性通过代替。Linux 共享组件回归以 PR 当前 head 的 CI 单独核实，跨目标构建不冒充其他 OS 原生验收。
