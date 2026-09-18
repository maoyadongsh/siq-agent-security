# Windows 当前用户任务的升级、回退与恢复

本规格补充 Windows 任务书 P03-STATE-16–22。沿用 `clientrelease`、Windows 任务归属、优雅停止、排他注册、状态 Writer 和发行清单 v3，不新增服务框架，不改发行信任根。仅对明确确认的当前用户、当前实例任务切换，不操作系统登录、睡眠或其他任务。

## 命令与预检

`service-upgrade --manifest FILE --binary FILE --confirm-upgrade [--source-manifest OLD] [--recover ID]` 在 Windows 分派到 Task Scheduler 流程。候选必须通过内置发行根、当前 Windows 架构、实际文件摘要/大小和当前状态兼容声明，暂存后再次验证。首次切换保留当前可执行程序快照，确认当前 CLI 路径精确对应签名任务的 source XML，并绑定源/目标二进制摘要。旧清单可显式保存以备回退；source-manifest 不能与 recover 混用。无确认、无可信候选、旧/新文件不可读或身份不符、未知系统任务、状态不兼容均不得停止现有保护。

## 不可变合同

新增 `local-windows-task-switch/v1`：`transaction_nonce`、`schema_version`、`binary_bindings`、`source_record`、`target_record`、`source_xml`、`target_xml`、`signature`。两份 record 复用 `local-windows-task-record/v1`，必须与当前实例、状态目录和同一用户 SID/任务名一致；XML 摘要分别匹配，source 与 target 不同。二进制摘要为规范小写 SHA-256。外层和每个嵌套对象拒绝重复、大小写混淆、未知、缺失或 null 字段；记录及外层均使用现有规范 JSON Ed25519 签名，文件 ID 为实际完整字节 SHA-256，不接受跨平台事务。每次新事务使用密码学随机的 16 字节 nonce（32 位小写十六进制），升级、回退后再次升级不得复用旧完成凭据。完整 JSON 字节不得超过 64 KiB，超限在发布前拒绝。

`service-switches/<id>.json` 保存不可变事务，`service-switch.pending.json` 沿用已有启动屏障。准备持主 Writer，且调用层持 service-control Writer；同一时刻不能与 Linux/macOS/Windows 其他切换重叠。应用阶段仅替换已验证的本地任务 XML 与 windows-task.json，两份文件必须分别为事务记录的 before/after 之一；未知内容、另一个 pending、缺失完成证据均保留现场拒绝。只替换这两个配置，不修改 admission、Grant、Intent 或撤销历史。应用本地配置不清理 pending。

## 系统任务与完成边界

新事务在当前签名任务已优雅停止且主 Writer 可取得后准备。系统任务若存在，必须完整匹配记录的 source 或 target XML，用户 SID 相同、状态空闲且实例数为零。只移除匹配 source 的精确任务，复用现有删除端的最终 XML/状态复验；创建 target 使用 TASK_CREATE 排他注册，不采用覆盖更新。恢复可接受记录内的源、目标或已确认缺席；未知配置、无法确定存在性、排队或运行中的源均拒绝，不删未知任务。

在确认目标系统任务与签名本地记录一致且空闲后，显式切换流程追加相同事务字节的 `<id>.done.json`，再删除复验一致的 pending。done 在此表示配置切换完成，不表示服务已健康。主 Writer 释放后才启动目标，调用已有任务启动/目录健康验证，并确认实际运行实例及发行版本。失败保留事务 ID 与现场，提示使用相同候选和 `--recover ID`；不会把超时当成已取消后台作用。已有完成事务且目标运行时，只有目标配置、二进制及版本健康全部匹配才可幂等复用。

## 回退

`service-rollback --transaction ID --binary OLD --confirm-rollback [--manifest OLD] [--restore-missing-binary] [--recover ID]` 只从已认证原事务的 target 返回其精确 source XML，反转相同二进制摘要绑定。沿现有保留清单与快照恢复逻辑核验旧发行签名和当前状态兼容；缺失程序只在明确 restore 选项及可验证快照下排他恢复，不覆盖未知文件。当前版本新产生的权限、撤销和业务记录保持原样，不以状态备份复活旧授权。配置切换仍按上述可恢复流程执行。

## 验证与证据

先验证合同样例及 Go/Python 字段一致。组件正负向覆盖合法/外来 Writer、签名/摘要/实例/SID 漂移、重复及未知 JSON 字段、跨平台事务、每个本地配置半完成组合、pending/done 丢失或不符、系统任务未知/不空闲/缺席、创建/删除/启动失败、候选漂移、健康/版本不符和幂等恢复。原生隔离 Task Scheduler 旅程另验源停止、目标实际进程/健康、故障恢复、回退、撤销保持和精确清理。测试签名与可控测试读取器只证明其实际覆盖链路，不代替正式发行签名安装/升级验收；不改旧正式清单，不把重启等排除项记通过。
