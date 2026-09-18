# Windows 历史迁移完成点的活动屏障修复

2026-09-18。代码候选 `e09b68489a495fa263488634508e11f661b5936f`，Windows amd64 CLI SHA-256 为 `5f7118b53ff270d25147f07e66b7e496b3117d8c3592c6d1e55b2e17a5db90d6`，实际构建信息为该源码、`vcs.modified=false`。

真实旧程序 `ff99317450784c9563f5b6a2308c98e8262df98d` 在隔离状态创建并撤销授权，旧程序此后不再访问升级状态。使用基于 `d1e7fd0` 的独立测试进程，在实际迁移的 plan、backup:0、backup、before-marker、marker、done 六个检查点以退出码 73 退出。前五项恢复及撤销保持通过；done 项发现普通 CLI `init` 返回 0，而活动 `logs/migration-plan.json` 仍存在。这违反 N01 普通入口在中断后拒绝的要求，原有单测也对 done 跳过了该断言。原始失败保留在 `before-fix.json`。

修复让活动旧迁移屏障始终阻止普通读写。显式恢复通过单独的完成凭据检查核对 plan/done/marker，并在持锁、版本兼容和归档/活动计划复验后清理屏障；不回放旧业务快照。N01 规格明确该既有规则，所有检查点的普通入口拒绝断言现在包括 done。

用修复后的干净 CLI 直接恢复同一个失败现场，未重建或改写测试历史：`init` 退出 1 且完整状态摘要不变；`state-migrate --confirm` 成功；独立 Python 核对全部 37 个备份条目的路径、类型、权限位、大小、摘要及实际字节，完成凭据摘要一致。最新撤销对象和 revision 与真实旧程序原输出相同；challenge/deploy 均以 revoked 原因退出 1，完整状态不变；重复迁移为 up_to_date 且状态不变。详见 `native-recovery.json`。这不宣称复制或独立证明全部 Windows ACL。

定向回归退出 0：4 个顶层、9 个子测试通过。原有 symlink-backup 子测试因本机创建符号链接能力不可用而跳过，未计通过。最初定向过滤未匹配 stateformat 测试，随后完整 stateformat 包单独运行通过。相关 state/stateformat 包 `go vet` 和改动 Go 文件 `gofmt` 通过。Windows amd64、Linux amd64/arm64、Darwin arm64 实际构建成功，逐个记录源码身份和制品摘要；交叉构建不是异 OS 实测。见 `targeted-regression.json` 和 `build-and-checks.json`。

复现时将 `historical-crash-driver.go.txt` 复制为隔离源码树中的 `internal/state/historical_crash_audit_windows_test.go`，用 `go test -c` 构建专用测试程序。仅该测试程序包含故障驱动，生产 CLI 不含环境变量故障入口。测试状态须位于明确自有的 `historical-migration-crash-r1` 目录内。真实旧程序先执行 init/admit/grant/revoke；专用测试程序通过 SIQ_HISTORICAL_CRASH_DIR、SIQ_HISTORICAL_CRASH_POINT 指定该状态及检查点，运行 `-test.run=^TestHistoricalMigrationAuditCrash$`。确认退出 73 后，以未修改的生产 CLI 检查普通入口拒绝，再运行显式恢复并逐项核对备份、撤销对象和状态摘要。测试驱动及其二进制摘要已记录，不能将其冒充正式发行二进制。

本批覆盖真实无标记历史到 v2 的中断恢复，不冒充受保护 v1 旧消费者或三个宿主验收。全量 Go、最终集成候选回归及宿主旅程仍待集成任务完成。该独立修复未修改已固定的 `0674509` 候选或共享工作树；不能将本报告与其他候选拼接为整体通过。

所有本批子进程已退出，未注册系统任务、启动后台服务、调用模型或改动日常配置。隔离状态保留以便复核，不将密钥、token、私有状态或原始输出入库。本批不涉及系统重启、注销或睡眠。
