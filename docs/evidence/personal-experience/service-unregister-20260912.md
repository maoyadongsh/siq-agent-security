# M44：Linux 服务注销与重试验证

日期 2026-09-12；当前未提交工作区，继承 M35–M43。规格 §3.11.8；不新增签名对象或 HTTP 合同。

## 实现与边界

新增 `service-unregister --confirm-unregister`。要求先停止；生命周期锁和主 Writer 下验证既有身份/签名配置，以及 manager 已停止、无 drop-in、同名链接归属。只删除实际加载的注册链接，不使用广泛 disable，不删除源 unit、记录、密钥或数据。删除后 reload/readback，只有完整 not-found 状态才成功；中断后缺失链接仅触发 reload 与复验。重复注销可返回当前未注册。

这属于服务入口注销，不是整个应用卸载或数据清理。其他用户自建别名不会删除；如其影响读回，明确返回未确认。恶意同 UID 竞争仍不在隔离保证内。

## 验证

- Go 全量/vet、CLI race、Ruff 通过；gofmt 无输出。四目标交叉编译通过。
- 单测：只移除归属链接、保留未知别名/源文件、链接已删除时恢复、已注销重试；运行/异常 Result/drop-in/普通文件拒绝；reload 失败不能返回成功。
- 原生 Linux `SIQ_TEST_SYSTEMD=1 SIQ_TEST_BINARY=/tmp/siq-m44-linux-arm64 uv run pytest ../../scripts/personal-experience/test_systemd_user_service.py -q`：1 passed in 2.05s。
- 完整临时实例旅程：prepare/register --runtime、重复注册、范围变更拒绝、产品 start/status/stop、运行中注销拒绝且进程保持、再次启动/pair、停止后产品注销两次通过。
- 注销前后逐字节比对 config/local-instance/user-service/signing.seed/源 unit 均保留。manager not-found；测试后 siq-agent-security-* 列表为空。没有修改用户生产服务或登录自启。

## 构建摘要

| 制品 | SHA-256 |
| --- | --- |
| siq-darwin-arm64 | `c66ca5783ad4b5df3df56e0ce82a15f706b339d14fd2762f7c4e3f85b0ea9d5d` |
| siq-linux-amd64 | `6ccef83a2bfa97af4523bcad3a444cb2f0834e8b4156503f6cb186b59335b918` |
| siq-linux-arm64 | `05c3e23ae6993a1905a17f19e4272a2b9d1e1042eff07d55aee592b66fb4a719` |
| siq-windows-amd64 | `91f33ba33544dd08b4d46748a6c43d190fe80bd82e13c2c01c9ebf71a0a26eae` |

下一步仍包括升级迁移、安装交付与跨 OS 生命周期、个人任务书其余项；LAN 后置。Linux runtime 原生证据不代表持久路径、Windows/macOS 或完整三平台验收；完整目标 active。
