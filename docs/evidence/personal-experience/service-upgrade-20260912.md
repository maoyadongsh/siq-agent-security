# M48：产品升级编排与恢复

2026-09-12，分支 codex/personal-client-upgrade-recovery 基于已合并 main `69d9c59`。恢复工作区外草稿后补齐规格 §3.11.12、CLI 和验证；本批未提交/推送。沿用 v2 发行兼容清单与 local-service-switch.v1，不新增信任根。

`service-upgrade --manifest FILE --binary FILE --confirm-upgrade [--recover ID]` 先验签、暂存及重新验证候选，再在生命周期锁下核验源归属、停止保护、获取主 Writer、准备/应用签名切换、释放主锁、重载、复验目标并启动。API 目录绑定、发行版本、系统 active/MainPID 同时满足才报告完成。失败返回事务 ID；恢复必须使用同一目标，已运行且健康的目标只读复用。

## 验证

- Go 全量/vet、CLI/state race 及四目标构建通过；gofmt 无输出。
- 单测覆盖未确认不写、候选与归属失败不停止、reload 失败返回事务 ID、不同目标恢复拒绝、同事务前滚恢复、目标已运行复用不重复启停、释放主锁后才 start。
- 原生 opt-in：`SIQ_TEST_UPGRADE_SYSTEMD=1 SIQ_TEST_BINARY=/tmp/siq-m48-linux-arm64 go test ./cmd/agentshield -run TestNativeUserServiceUpgrade -count=1 -v` 通过。测试使用同一可信构建的两个路径副本，真实 Linux runtime unit 完成停止、配置切换、重载、目标新 PID、目录健康/版本与原配置保留检查，再注销清理。
- 生产二进制 CLI 在上述运行源实例期间拒绝开发签名候选，源 PID 保持不变。正向原生编排测试用包内可信构建摘要校验，不提供产品信任根绕过参数。
- 测试后 siq-agent-security-* 用户单位列表为空，未修改生产服务或开启登录自启。

| 制品 | SHA-256 |
| --- | --- |
| siq-darwin-arm64 | `bc1c64b13ac312bf7f5d32f0f4d53c08de3ceef63413adeb794c7ee88eeb6096` |
| siq-linux-amd64 | `60ce1c38a67e61d79b2206ad631e1ea913a2617fa7d2eeb84067da6bfd374e00` |
| siq-linux-arm64 | `3dfddff602d1c89a152fa74cf5b4fd32dc378887acc0f872ff09472ab81cff8d` |
| siq-windows-amd64 | `d0bb24a8bbae030bfe6710f3cf21f36b1aa6fd6a35730c9f00e6755d0266ad3e` |

## 未关闭边界

原生测试证明配置和进程代际切换，不证明两个真实发行版本的状态兼容，也不是正式发行签名验收。回滚尚未实现；失败前滚恢复不回滚授权或台账。跨 OS 生命周期、真实平台组合及安装交付仍待完成，完整个人/LAN 目标 active。PR #28 的管理员合并授权已用于该次合并，不扩展为本分支自动推送/合并授权。
