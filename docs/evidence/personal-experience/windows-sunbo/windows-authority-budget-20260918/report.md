# Windows Authority 4 秒 HTTP 组件预算证据

2026-09-18，受测源码为 `f42a7c94b5ad2a766c79001aee3d760c02a3574c`。最终 r4 在同一个原有 4 秒期限内完成新会话登记和裁决：登记累计 **1.923 秒**，裁决累计 **3.301 秒**，并断言 `action=allow`、`authority_status=valid`。这是一次真实 loopback HTTP 组件检查，不是宿主或模型运行，不替代独立 Hermes 原生运行证据。

当时唯一未提交内容为 `apps/agentshield/cmd/agentshield/launch_agent_switch_test.go` 中的 Mac 测试夹具，不参与 `./internal/server` 预算目标；不宣称整棵工作树无改动。r1–r3 是不同开发中工作树阶段，未记录可完整重建的不可变源码身份，因此不得归到 r4 commit 或作严格同候选性能对照。各轮原始失败完整保留，不用后来的通过覆盖。

## 预算结果与边界

| 轮次 | 源码阶段 | 退出码 | 结果 |
| --- | --- | ---: | --- |
| r1 | 初版元数据快照，身份去重复之前 | 1 | 登记 3.029 秒；decide 在共同 4 秒到期 |
| r2 | 加入同调用身份去重复，最终快照/记录读取修复之前 | 1 | enrollment 在 4.0021362 秒超时，尚未进入 decide |
| r3 | 快照共享/标记一致性及身份去重复后，记录读取修复之前 | 1 | 安静窗口 enrollment 在 4.0011249 秒超时 |
| r4 | 指定 f42a7c9 完整集成候选 | 0 | 登记 1.923 秒，登记＋裁决共 3.301 秒 |

r2 同时期发生过应用首次启动/解压，未确认其与耗时的因果关系。r3、r4 已协调暂停其他代理编译/测试；这仍不是普遍负载或冷启动性能保证。r4 日志中 fixture 内首次登记 1.968 秒与预算内新 session 登记 1.923 秒是两次不同请求，只有后者属于共同 4 秒验收。fixture 准备耗时不算入该 deadline。

测试入口 `apps/agentshield/internal/server/windows_authority_budget_windows_test.go` 使用实际 `httptest.NewServer` loopback transport，先真实准入和实例 baseline、Windows Grant/审批/部署/身份准备，再给全新 session 的 enrollment 和 decide 共用 `context.WithTimeout(..., 4*time.Second)`。没有延长超时、删去安全检查、授权结果缓存或模型调用。

## 修复与安全验证

同一次兼容元数据检查固定祖先/文件句柄并复核当前 ACL；保留原 DirectoryID 算法、所有外层/嵌套版本及 N01 屏障。登记在同锁内返回已验证的身份/绑定，保持当前 Grant、撤销和发布前复验。随后把 Windows Intent 同一记录的重复检查合并为受保护读取：前后各一次 RequirePath，中间固定并复核根/记录目录/文件，缺失或不安全的目录不能被解释为“无撤销”。没有跨请求缓存。

`record-read-safety-test.log` 四包 exit 0：包括重解析/已有写句柄、根/目录/文件 ACL、缺文件与缺撤销目录区别、硬链接、大小/路径边界、新调用立即读取新字节、外层/嵌套/活动迁移屏障、当前撤销及发布前 Grant 变化。受影响五包 vet exit 0。

vet 的标准输出/错误均为空，原 PowerShell Tee-Object 未生成原始日志文件。包内 `record-read-vet-result.log` 是明确标注的会话工具终态摘要，不冒充原始日志；空输出摘要和来源另见规范化清单。整理本证据包没有重跑测试或编译。

## 命令与执行环境

原环境：Windows，Go `go1.27.1`。工作目录 `<WORKTREE>/apps/agentshield`；Go 可执行文件 `<GO_TOOLCHAIN>/bin/go.exe`；`TEMP` 和 `TMP` 均指向原先已核验的物理私密目录 `<PRIVATE_TEMP_ROOT>`。执行中没有修复既有 ACL、重启、睡眠或提权。

预算各轮（退出码见上表）：

```text
go test ./internal/server -run '^TestWorkBuddyWindowsFreshSessionHTTPBudget$' -count=1 -v
```

最终局部安全组（exit 0）：

```text
go test ./internal/privatefs ./internal/statefs ./internal/intent ./internal/runtimeidentity -run 'TestWindowsReadSnapshot|TestPrivateRecord|TestWindowsIntentPrivateReadAndCachedStore|TestWindowsIntentUnsafeRevocationDirectoryIsNotAbsence|TestWindowsIntentMissingRevocationDirectoryDenies|TestEnrollmentContext' -count=1 -v
```

相关 vet（exit 0，输出为空）：

```text
go vet ./internal/privatefs ./internal/statefs ./internal/intent ./internal/runtimeidentity ./internal/server
```

## 脱敏和摘要

原始本地输入保留不改。提交副本转换为 UTF-8/LF，实际用户名和绝对私有路径使用固定占位或仓库相对路径，动态 loopback 端口统一为 `<EPHEMERAL_PORT>`。`normalization-manifest.json` 分别保存原始字节 SHA256 与脱敏后 SHA256；`tested-source-files.json` 仅保留最后七个跟进文件的原工作树字节摘要，不冒充完整源码/制品签名。`SHA256SUMS` 校验本包所有载荷文件，不包含它自身。

本包只收口 HTTP 组件性能及相关局部安全验证，不声明三宿主验收、桌面冷启动、额外负载、大量历史状态、全量测试或正式签名完成。**303 固定台账未变更，通过数增量为 0。**
