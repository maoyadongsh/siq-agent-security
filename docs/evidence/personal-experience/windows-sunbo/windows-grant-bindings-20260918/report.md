# Windows Grant 文件身份绑定与状态写入边界

代码候选 `a24e029b177c110a97637f3c6902ab99670b33b7`；原生 Windows 组件验证，关联 #39 / PR83，依赖 PR82。不是宿主闭环或最终集成验收。

新版 Grant 明确签入 Windows profile 与每个范围的真实文件身份摘要；仅经确认生成待批准修订，审批重新检查文件身份。文件替换使原审批失效，仍允许撤销。旧签名和旧 POSIX 解释保留。审批绑定和范围摘要亦纳入版本与身份，防止同路径换对象后继续使用旧挑战。

状态升级协议尚未接通，默认状态禁止发布新版 Grant。原生复现发现 `GRANTS`、`grants/.` 绕过临时门禁：修复前实际产生两个文件；修复后普通/CAS 写入及原生探针均拒绝，独立检查文件数为零。这是新候选开发期问题，不描述为已上线新版授权漏洞。

Go 实际生成对象的独立合同校验又发现资源编辑丢失 evidence_ids。修复前新负向失败；新版编辑沿既有草稿约定保留 source_grant 来源引用，仍为 pending_approval。四个真实生成的对象（Hermes/OpenClaw，各 pending/approved）已通过 Python Schema、Ed25519 与权限摘要、审批绑定摘要、范围摘要的独立复算。探针使用合成事实及临时密钥，不产生宿主或生产授权；原始本机路径留在私有证据，不上传。

最终候选 Grant/路径、状态提交、receipt Authority 与旧 Intent 定向回归通过；Grant/路径 race 通过；fmt 输出为空、vet、233 个 Python 合同测试、Windows 构建通过。三个跨平台产物首次因临时未跟踪证据文件标为 modified=true，保留记录并移出证据后重建，替代产物均嵌入相同源码及 modified=false。逐项退出码与哈希见 clean-verification.json。

state 定向回归中一个原有符号链接测试跳过，不记通过。前候选 2cca13b 的 Runtime Identity 祖先链接/记录链接测试因 Windows 1314 失败；混合普通/race 命令均退出1，未把其他包通过冒充整条命令通过。此前 d384e24 整模块回归已结束且失败，详情见相邻 windows-resource-facts-20260918/full-go-status.json；不能作为本候选整模块通过证据。

复现：按模块 AGENTS 设置本机私有 TEMP，执行 grant/runtimepath 全包、state 的 TestWindowsGrant|TestCommitGrant|TestPutVersioned|TestRecover|TestGrantDraft、receipt 的 TestPermission|TestAuthority|TestIntent|TestGrant、Intent 的 TestLegacyFilesystemRegexDoesNotGainWindowsAuthority。原生输出探针见 producer.go.txt，需放在模块内部的隔离临时目录，传入一个不存在的测试根。私钥仅进程内生成；所有原始输出只留本机。

仍需接通可恢复状态版本升级、Runtime Identity v2、Intent v4、最终参数及 receipt/hold 全链，然后执行真实 Hermes/OpenClaw 允许、越权、失联恢复、审批与撤销。不能把当前门禁或组件结果视为 #39 已解决。

未调用模型、未操作日常实例或系统生命周期。探针目录保留作证据，未改日常配置，无本批自建服务需要恢复。旧完整 Go 控制器与本批控制器均已取得终态；本轮必需清单仍为73/303通过、3失败、5受阻、222未测，系统中断3项另列。
