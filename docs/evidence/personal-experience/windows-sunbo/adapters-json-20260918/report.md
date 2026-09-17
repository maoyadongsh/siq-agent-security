# Windows 适配器测试 JSON 路径修正（接续 PR #49）

已有 PR #49 同步 main d4850f5 后保留最新安装策略协议。本次只改测试，不改变运行时接口或安全判定。源码提交为 `30acef6c80dedd96853805fb7d0b738608ec459c`。

Windows 原始路径直接拼进 JSON 会使反斜杠产生错误转义，正向案例未到准入层就失败，负向案例可能因 JSON 错误而虚假通过。现在动态路径均经 JSON 编码；保留 protocolVersion/sourcePathKind 等新合同字段、旧协议/未来协议/尾随对象拒绝。每个负向检查具体拒绝原因，持久化失败还必须实际调用 Persist。

WorkBuddy 安装测试原先在原始 JSON 中匹配未转义 StateDir，导致真实已绑定路径被误判。现在先解码，再分别检查 PreToolUse/PostToolUse 仅有一个命令且固定正确状态路径；原备份、未知设置、幂等与卸载断言保留。

原代码两个顶层测试失败（before.log）；修复后相关 17 项顶层测试通过。已有 3 个跳过记录保留：Windows 不运行 POSIX shell 引号测试，以及无法创建 symlink/祖先 symlink 两个 fixture；不算原生通过。两个包 vet 通过，修改文件 gofmt 无输出，相对 main diff-check 通过。同步引入的上游历史证据存在原始空白，未改其字节；本 PR 增量检查无此问题。

执行命令：`go test -p 1 ./internal/adapters ./internal/adapterinstall -run '^Test(PolicyExecBlocksQuarantineWarnsConditionsAllowsClean|PolicyExecFailsClosed|WorkBuddy.*|DesktopInstallUninstallPreservesUserHookQuotingProduct|RecordedToolHookAcceptsOnlyGeneratedCommands)$' -count=1 -timeout=5m -v`。测试环境使用本批私有 TEMP/TMP；未提升权限或关闭防护。

这不是 WorkBuddy 桌面前置拒绝的真实旅程，也不消除 PR #74 中记录的全模块失败。旧 PR 证据仍以其原候选和时间保留，不改写成新协议结果。
