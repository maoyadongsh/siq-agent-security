# Windows 升级／回退边界补充证据（2026-09-18）

本批补充 PR #86 的缺失程序、Windows 独占文件句柄和撤销记录保持验证。测试提交为 `adf5812be2959fc40e7b14f17fca0da9784a4381`；没有修改产品运行时代码。原生进程复用此前干净构建的 `319d3ac4cf4f56a17f212ed45a927e7e29957490` 产物，两个版本仅为明确标注的测试版本，不是历史正式发行。

## 结果与范围

| 验证 | 结果 | 证据与边界 |
| --- | --- | --- |
| 源／目标程序缺失或独占占用 | 3 顶层、6 子用例通过，exit 0 | component.jsonl；Windows 文件句柄真实，任务控制器为夹具。预检失败不停止或修改任务，不产生事务；还原原字节后成功。 |
| pending 恢复目标缺失／占用 | 包含在上述用例 | 保持原 pending 字节与任务缺席，不产生任务操作；恢复原文件后使用同一 ID 完成。 |
| 回退源程序缺失 | 包含在上述用例 | 缺失时当前目标保持运行；原字节还原后回退成功。没有将手工还原称为正式 CLI 快照恢复。 |
| 真实原生升级／回退 | 1 顶层通过，exit 0 | native.jsonl；真实 Task Scheduler、服务进程和版本健康检查。私有目标副本被独占／删除时，运行中的源没有停止；恢复后源→目标→源成功。 |
| 撤销状态保持 | 4 次阶段断言通过 | 真实 CLI admit→grant→revoke；初始 pending_approval，撤销后 revision 1。challenge、deploy 均 exit 1 且原因明确为 revoked；9 个业务文件的路径集合、摘要、Grant 签名和 revision 在切换前后不变。 |
| 相关 race | 13 顶层、68 子用例通过，2 包，exit 0 | race.jsonl；包含前批状态／编排与本批组件负向；不是整模块回归。 |
| 独立历史核查 | exit 0 | independent-history.json；Python Ed25519 验证 2 份 Grant、2 份事务、4 份任务记录，校验文件 ID、done 字节、XML 摘要、正反向关系和 2 条匹配审计，其中 1 条撤销审计。 |
| 独立清理核查 | exit 0 | independent-cleanup.json；系统任务缺席，两个精确程序进程均为零，无 Writer/pending，产物摘要匹配。保留私密状态作为证据，不上传密钥或原始状态。 |
| 格式／静态检查 | exit 0 | 两个新增文件 gofmt 无输出；go vet ./cmd/agentshield；git diff --check。此前模块 vet、四目标构建见前批报告。 |

原生 source SHA-256 为 `f8fadd2fc44f41643fbac5885045cc17483e65d8553d1c7d5a41108933cc01bc`，版本 `0.0.0-win-switch-source`；target 为 `581c027f329dc6761567d300a5090e4dafd249e52ce0988663b6942278b957e3`，版本 `0.0.0-win-switch-target`。测试仅操作隔离目录中的副本，没有锁定共享构建文件。

## 复现

在具备仓库要求的 Windows 工具链、普通用户私有 TEMP/TMP 和受限状态 ACL 的环境，从 apps/agentshield 执行：

```powershell
go test ./cmd/agentshield -run '^(TestWinSwitchBinaryBoundary|TestWinSwitchRecoveryBinaryBoundary|TestWinSwitchRollbackMissingBinary)$' -count=1 -json
$env:CGO_ENABLED='1'
# CC 指向已安装的受信任 GCC；本次使用 mingw64 gcc。
go test -race ./internal/state ./cmd/agentshield -run '^(TestWinSwitch(Recovery|Refuse|JSON|Identity|Prepare|Contract|BinaryBoundary|RecoveryBinaryBoundary|RollbackMissingBinary)|TestWinTaskSwitch(Recovery|Preflight|RecoveryRefuse|Rollback))$' -count=1 -json
```

原生测试设置 SIQ_TEST_WINDOWS_BOUNDARY=1，SIQ_TEST_WINDOWS_SOURCE/TARGET 分别指向上述经核验产物，SIQ_TEST_WINDOWS_SOURCE_VERSION/TARGET_VERSION 使用对应版本，然后执行 `go test ./cmd/agentshield -run '^TestWinTaskSwitchNativeBoundary$' -count=1 -json`。该 opt-in 会创建本轮专用的当前用户任务，成功后优雅停止并精确注销，保留状态；失败时未知归属或 pending 不自动删除，需要检查现场。不得针对日常服务目录执行。

原生测试输出的私密 case 目录可以传给 `python verify-history.py <case-directory>`。脚本仅借助该 case 的 source.exe pubkey 读取公钥，独立验签并打印脱敏结果，不读取或输出私钥内容；需要 Python cryptography。首次本地核查把状态名误写为 pending、又只数 JSON 漏掉 skill-card.md，修正核查口径后通过，未修改被测状态。

## 保留的失败与限制

development-fixture-failure.jsonl 保留初次真实失败（exit 1，1 顶层通过、2 顶层失败，3 子通过、3 子失败）：PowerShell 锁夹具使用 WindowStyle Hidden 时提前 EOF，尚未取得独占句柄。改为编码脚本、标准输入传路径，并去掉导致该环境管道提前退出的参数后，组件全部通过。一次中间定点重试仍失败，去掉该参数后的定点重试通过，随后执行完整选中组件与 race。没有关闭断言或跳过负向。未使用 Start-Process，不改执行策略或提权。

这是实际原生任务和产品编排函数的测试驱动证据。尚不覆盖正式 v3 签名清单生产 CLI 的完整升级／回退、真实历史版本兼容、此前已部署 effective 权限撤销后的全部旅程、正式快照恢复缺失程序、全部占用位置以及状态兼容组合。撤销声明不能冒充已生效权限。此前基线 macOS 夹具失败和最终全模块／受影响宿主回归仍由集成任务处理，不能将本批绿色结果冒充最终候选通过。

本批关联 P03-STATE-17/18/19 的部分要求，由原任务维护唯一验收台账，不提升通过计数，不变更 303 分母。没有模型调用、系统重启／注销／睡眠、日常实例变更、main 合并或发布。

公开 JSONL 仅替换本机工作区路径为 $WORKSPACE，保留事件、时间、退出与失败语义；原始证据保留在本机。SHA256SUMS.json 校验本目录其余所有文件的实际字节。前批报告见 ../windows-task-switch-20260918/report.md。
