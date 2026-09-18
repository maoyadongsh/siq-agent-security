# Windows 迁移重入与只读备份修复

源码候选 `54df8d44a33dfb6cd871b3fc8c21fd123190d770`，基于 Windows 集成候选 84c84a1 的独立分支。本批未修改日常状态或系统权限，未调用模型。测试数据为组件夹具，不冒充历史发行状态或完整宿主验收。

## 两个已复现的问题

1. 迁移 checkpoint 使用 0600 发布，但 Windows Go Stat 返回 0666。恢复时逐位比较导致完整、未篡改的 `backup.done.json` 等误报 existing output differs。Windows 现在只比较 Chmod 实际表达的 owner-write/只读位；其他平台仍精确比较。字节、对象类型和完整备份清单验证保留；变更字节或只读属性仍拒绝。
2. 新增只读负向揭示：暂存文件与发布备份互为硬链接，Go Windows os.Remove 的只读回退会清除共同对象的只读属性。现在保留本次创建句柄得到的文件身份，清理时复验打开对象，用 DELETE | IGNORE_READONLY_ATTRIBUTE 删除精确暂存链接，不改只读位。身份替换或系统不支持时失败并保留现场，无降级清除属性。

原生探针直接证明目标字节、只读属性保持，暂存名消失、最终链接数为1。测试身份用 File.Stat 从打开句柄捕获；Windows 路径 Stat 的 SameFile 身份是延迟解析，不能作为替换前身份快照。

## 验证

- 第一轮 bf6e39a：23 个顶层测试通过、1 个失败。迁移 checkpoint 恢复已修正，新增只读文件测试暴露第二个问题；该失败保留，不覆盖。
- 当前候选：25 个顶层测试通过、0 失败；68 个子测试通过，1 个构造符号链接的子测试因本机权限不足跳过，不能计为拒绝成功。详情见 verification.json。覆盖每个实际迁移检查点、完整备份和重入、源/备份/计划漂移拒绝、缺标记恢复前置、未知暂存保留、发布幂等、内容/属性漂移拒绝、替换对象拒删、真实提交子进程崩溃恢复及 Windows Writer 负向。
- go vet ./... 通过；Windows amd64、Linux amd64/arm64、Darwin arm64 构建均通过；锁定 Python 环境的 Schema 检查通过。
- 根候选84c84a1的完整 Go 回归仍在单独执行，并保留其他 Windows 失败。本批不宣称全仓或最终集成候选全绿。

复验命令：在 apps/agentshield 用原生 Windows Go 执行 `go test -json -count=1 -timeout=10m ./internal/state -run 'TestMigration|TestUnmarkedMigration|TestInitializeHistoricalState|TestCommitRecoveryAfterProcessKill|TestWindows.*|TestAcquireWriterBlocksSecondAndTakesOverDead'`。使用本批隔离 TEMP/TMP；不要操作真实历史状态来制造故障。

## 范围

这不是 DACL 私密验证或安全创建修复，不关闭 #42。没有伪造受保护 v1 旧发行程序，不据此给原生迁移、升级回退或三个宿主完整旅程记通过。状态合同和历史计划不变，迁移成功仍以完整清单/字节/观测权限验证为准。用户排除的重启、注销、睡眠未执行；303项分母不变。

Windows 删除标志语义：[Microsoft FILE_DISPOSITION_INFORMATION_EX](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddk/ns-ntddk-_file_disposition_information_ex)。本机 Win32 FileDispositionInfoEx 使用结果另由原生探针验证；不从该测试推断所有历史 Windows 版本支持。
