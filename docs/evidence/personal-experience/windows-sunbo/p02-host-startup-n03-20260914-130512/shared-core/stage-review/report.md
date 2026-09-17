# Windows 复验 PR #45：安装诊断与受控安装入口

在固定源码 `9cc18630be584692905e1ce612b91a9ba5aee610` 的独立检出运行三项定向 Go 测试，结果为 **2 pass / 1 fail，退出码 1**。新增的 Hermes 受控安装测试无条件要求 shell 包装器存在，但产品在 Windows 明确不生成它。该结果已提交到 [PR #45 审阅记录](https://github.com/maoyadongsh/siq-agent-security/pull/45#issuecomment-5658560779)，共享文件未在本批修改。

机器、工具和命令身份见 [summary.json](summary.json)，逐事件结果见 [adapterinstall-tests.jsonl](adapterinstall-tests.jsonl)。Windows 11 amd64、Go 1.27.1，CGO=0，禁用模块代理和自动工具链下载。检出前后保持同一 SHA 且 clean。这是本机编译执行的包测试，不是 Hermes 公共 CLI、桌面或完整 SIQ 用户旅程；没有给旧 Windows SIQ 二进制重新标注源码身份。

| 测试 | 实际结果与边界 |
| --- | --- |
| TestHermesNativeEvidenceSeparatesRegistrationFromCompatibility | pass；仅证明该测试中的注册/可执行兼容性分层断言 |
| TestConfiguredEndpointReadsConnectionDocumentOnly | pass；仅证明配置读取的限定行为 |
| TestHermesControlledInstallPathChecksBeforeNativeInstall | fail；install_entry_test.go:82 读包装器返回文件不存在，后续 0700 与 admit 顺序断言尚未执行 |

`plan.go:439` 只在非 Windows 创建 `hermes-skills-install`；`install_entry_test.go:74` 开始的新测试却没有区分系统。建议 POSIX 继续验证先 admit 后原生安装，Windows 验证包装器缺席、明确提示当前受控安装入口缺失及没有宣称安装拦截。不能靠简单跳过将 Windows 能力记为完成，也不能由两个诊断测试通过推导宿主原生工具可用。

执行前的分支盘点看到 PR #45 尚打开，执行后的远端核查确认维护者已于 `2026-09-14T03:19:44Z` 将它合并为 `4464dfbc8e66c8ec1fb2590b286351595fcd9667`，早于本次测试开始。原私有 runner 汇总中的“unmerged”是盘点状态过时，派生摘要保留更正说明。实际受测源码始终为 9cc，没有在测试中更新 checkout。

首次在较深路径创建 worktree 时，Git 因六个既有长文件名失败并自行撤销失败检出。核对目录和 worktree 登记均不存在后，以仅作用于当前命令的 `git -c core.longpaths=true worktree add --detach ...` 成功；未改全局 Git 配置、已有分支或用户文件。测试使用独立私有 NTFS 临时根，Go 自身执行测试临时目录的常规清理；没有手工删锁、改断言或制造实际宿主配置。独立检出及原始测试日志继续留存。

公开 JSONL 只替换输出里的本次私有目录前缀，原始字节摘要和展示副本摘要均已记录；没有归档临时签名身份或 token。新旧候选与原始失败不混写，三宿主平台矩阵不因此提升。

复现时在固定检出的 `apps/agentshield` 目录运行 `summary.json` 中的 Go 命令。摘要中命令前面的环境赋值是描述形式；PowerShell 应逐项设置进程环境，并在结束后恢复。`TMP`、`TEMP`、`GOTMPDIR` 和 `GOCACHE` 应指向新建且已核对私有 DACL 的测试根，不能直接复用本批临时目录。
