# M49：启动失败后的升级恢复

2026-09-12，codex/personal-client-upgrade-recovery 当前未提交工作区，继承 M48。规格 §3.11.12 补充，合同无变化。

## 缺陷与修复

原恢复复用“正常停止”断言，要求 Result=success，候选启动失败且 MainPID=0 后仍无法重试。新增 TestServiceUpgradeFailedTargetRecovery 在修复前明确失败；修复后同一已签名事务可在 inactive/failed、MainPID=0 下取得主 Writer 并前滚。首次升级正常停止、停止命令成功口径不变。恢复没有把失败说成正常停止，也没有删除锁、停止未知进程或接受替换候选。

## 验证

- Go 全量、vet、CLI/state race 和四目标构建通过，gofmt 无输出。
- 新负向验证：活跃主 Writer、activating、缺失或非零 MainPID 拒绝恢复，源配置保持不变。
- 原生命令 `SIQ_TEST_UPGRADE_SYSTEMD=1 SIQ_TEST_BINARY=/tmp/siq-m49-linux-arm64 go test ./cmd/agentshield -run TestNativeUserServiceUpgrade -count=1 -v`：正常切换与瞬时失败恢复两项通过（总 3.179s）。
- 真实临时用户服务：在源停止后注入本机 HTTP 端口占用，候选启动失败，不能报告成功；释放占用，确认 manager failed/MainPID=0，使用同一事务恢复后新 PID 与实例/版本健康通过。原配置保留，服务和端口测试资源清理完毕；测试后 siq-agent-security-* 单位列表为空。
- 继续覆盖生产 CLI 拒绝开发签名发行者且源 PID 不变。

| 制品 | SHA-256 |
| --- | --- |
| siq-darwin-arm64 | `36b5f68309fc1e58f173fc955473883099513954967e430674c64ee886cfda2d` |
| siq-linux-amd64 | `6d9427069d575e21f29a1a0394bd8f546b809da69c2b30f3600892f83d3332c1` |
| siq-linux-arm64 | `1f50ad9c4b48dd68bebfa7723d60ff14d722ed971336b5695b61a6db8aa7668f` |
| siq-windows-amd64 | `416d146b856280f8c44f585074f676543fa5276b88f2c78082f4450b281dd498` |

原生正向仍为同一构建的路径副本，只证明切换及真实瞬时故障恢复，不是正式发行跨版本验收。自动回退、完整安装交付和跨 OS 原生运行继续待办。完整个人/LAN 目标 active；本批未提交或推送。
