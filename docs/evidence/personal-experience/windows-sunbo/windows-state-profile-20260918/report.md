# Windows 资源状态升级与 Grant 一致读取

2026-09-18。本批源码为 `d1e7fd0aa3747874b3c9841d41a1a2a679863ac7`，干净工作树构建；原生二进制 SHA-256 为 `12c1f24e63e76351384ec0db8cf8e9595058c8498e327c85cbf16c8ce798c76c`。本批是状态层交付，不是三个宿主或整个 Windows 任务书通过证明。

## 行为变化

新增 `state-enable-windows-resources --confirm`。已初始化且旧迁移完成的 Windows 本机状态，可明确提升 reader/writer 要求到 3。默认初始化仍为 2；升级不签发、批准或改写旧 Grant。新 Grant 的持久化门禁要求完整升级证明；旧程序因版本要求拒绝访问升级状态。

升级持主 Writer 与四种维护 Writer，使用独立不可变计划、准备与完成凭据，保留原迁移历史。活动屏障只有显式恢复命令可清理；常规入口及旧迁移命令始终拒绝。单独测试进程的异常退出可恢复，不涉及系统重启、断电或当前会话中断。

同时整合 Issue #53 的状态部分：同状态目录、不同 Store 共用 Grant 写入门禁，列表正文与版本号在同一读取区间取得。活跃写入返回 busy，孤立未完成提交仍按错误拒绝。HTTP/UI 层由同一候选的主修任务继续接入，本批不宣称 #53 全部完成。

## 实际验证

- 干净候选的状态升级/Grant/快照/清单定向测试：23 个顶层通过、33 个子测试通过。1 个父进程中的子进程助手跳过；实际子进程退出恢复由父测试调用并通过。
- 并发检测 `-race`：7 个顶层和 4 个子测试通过。CLI 确认、结果合同及重复执行另行通过。
- `gofmt -l .` 输出为空、`go vet ./...` 退出 0；Python 合同验证退出 0。Windows amd64、Linux amd64/arm64、Darwin arm64 构建均成功，逐个核对实际产物的源码 SHA 与 `vcs.modified=false`。交叉构建不是其他 OS 实机测试。
- 真实历史二进制 `ff99317450784c9563f5b6a2308c98e8262df98d` 在全新隔离目录创建 admission、Grant 及撤销历史；实际 reader2 二进制 `a24e029b177c110a97637f3c6902ab99670b33b7` 完成旧状态迁移；本候选再启用新状态。
- 未确认时退出 1，状态快照不变；确认成功后，除兼容标记外，原有 80 个文件和目录保持一致。独立 Python 校验实际 plan/done/result 的 Schema、计划摘要、目标标记摘要及旧迁移历史摘要。
- 重复启用返回 `up_to_date` 且状态不变。实际 reader2 的 `state-status` 返回 incompatible，`init` 退出 1，原因是状态需要新版程序，状态快照不变。
- 独立 PowerShell ACL 核查升级日志根、tmp、plan、prepared、done 共 5 个对象：当前用户拥有、DACL 受保护、允许主体仅为当前用户/SYSTEM/Administrators。隔离测试根的既有继承隐私不冒充产品创建根目录的证据。

审阅中发现并修复一个恢复缺口：目标标记已发布后，归档计划缺失会被重建，准备凭据缺失则会先追加 done 再拒绝。修复前两条负向均真实失败，见 `pre-fix-negative.json`；修复后在取锁前验证原始准备证明，两条拒绝均不改变状态，正常检查点、缺失标记的受限恢复及真实进程退出恢复继续通过。

## 保留的未完成项

较早 `fbaa771` 的四包完整回归已退出 1：155 顶层通过、5 失败、13 跳过，168 子测试通过、4 跳过；stateformat/clientrelease 两包通过，state/skillmanifest 两包失败。原始终态见 `broader-regression-status.json`。该批 skillmanifest 有三条失败：缺少创建 symlink 的权限、MSYS Python 返回空架构、PATH 缺少 sh。后两项以已有原生 Python 转发器和 Git shell 明确配置后，在本候选定向复验通过；symlink 夹具仍需完成 Windows 等价验证，没有提权或改成跳过。另两条 state 失败已定向复验通过：旧夹具改用 WriterVersion + 1 表示未来版本；Windows 跨进程测试采用有界 2 分钟预算并明确输出 deadline 错误，实际 36.67 秒完成。完整 80 次唯一写入断言保留，未降低安全要求。该复验使用共享开发树，只变更两份测试，运行时产物证据仍归 d1e7fd0，最终统一候选仍需完整回归。

最终统一候选的全量回归、授权执行链、三个真实宿主复验仍由唯一验收台账跟踪。本批不提升 303 项台账的通过数，不拼接候选宣称整体通过。没有付费模型调用、系统生命周期操作或修改日常实例。

隔离测试子进程均已退出；本批未注册任务、启动测试服务或改变日常配置。私有测试状态保留用于复核，不向仓库提交密钥、token、完整状态及命令原始输出。较广回归进程已终结，真实退出码和失败保留。

## 复现

在本候选干净工作树、普通用户 Windows NTFS 隔离目录运行：

```powershell
go test -count=1 -run 'TestWindowsProfile|TestWindowsGrant|TestCommitGrant|TestGrantSnapshot' ./internal/state
go test -count=1 -run 'TestWindowsProfile|TestStateProtocol' ./internal/stateformat ./internal/skillmanifest ./cmd/agentshield
go test -race -count=1 -run 'TestGrantSnapshot|TestCommitGrant|TestWindowsProfilePublishedMarker' ./internal/state
```

原生历史旅程必须使用上面标明的真实历史构建，并先核对 `native-journey.json` 的二进制摘要。在专用 `SIQ_AGENT_SECURITY_STATE_DIR` 中依次执行历史程序的 init/admit/grant/revoke、reader2 的 `state-migrate --confirm`，保存全状态文件摘要；此后不再运行无保护的历史程序。执行新程序未确认/确认/重复启用和 state-status，再执行 reader2 的 state-status/init，分别核对退出码及前后状态摘要。旧历史材料不能手工伪造为“历史版本”。

本目录仅包含脱敏的摘要、退出码、测试统计和 ACL 类别；原始本机证据路径由私有交接记录定位。
