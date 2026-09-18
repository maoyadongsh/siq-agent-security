# F02 停止能力只读复核（2026-09-17）

本次仅复核本机两套 CLI 的 `--version`、`sandbox --help`、`sandbox exec --help`；未连接、重启或改动共享网关，未创建沙箱。结论只适用于所列二进制与 CLI 可见接口，不是网关内部 gRPC 能力结论。

| 工具链 | SHA256 | 只读结果 |
| --- | --- | --- |
| 系统默认 `~/.local/bin/openshell` | `48b49e6418cd67f228083126d291d3b1bda6b19d1c92e110b8b18cc7dd64fb6c` | v0.0.13；`sandbox exec --help` 退出 2，提示 `unrecognized subcommand 'exec'`。不能用于本批真实执行。 |
| 项目固定 `siq-research-engine/var/openshell/toolchains/v0.0.83/bin/openshell` | `04158e0e24a621a60bcc6b390672853d58cbc5ed7412ac5e0a15d4cffeee17b7` | v0.0.83；`sandbox exec` 存在，帮助说明通过 gRPC exec 流式输出、返回远端命令退出码；`sandbox` 命令列表没有按单次执行 ID 的查询/停止入口，`exec --help` 也没有可复用的执行 ID 或 detach 参数。 |

上游当前 [CLI 参考](https://github.com/NVIDIA/OpenShell/blob/main/.agents/skills/openshell-cli/cli-reference.md) 同样列出 `sandbox exec` 和沙箱生命周期命令；这是持续变化的 `main` 文档，**不作为 v0.0.83 网关协议证明**。本次没有从 CLI 版本推断网关版本或 `remote_stop=unsupported` 的上游事实。

本候选的 `/stop` 仍仅在验证签名预留与身份后记录请求并取消**本进程**观察的 CLI。结果保持 `remote_stop_confirmed=false`；本地取消、响应丢失或进程重启均不能推出远端命令已结束。欲关闭 F02 的远端腿，需对同一后端版本找到可绑定单次执行身份的官方协议/实现，并在专属沙箱验证查询、停止与独立效果；若仍无此能力，应维持 `partial` 与人工对账。此处没有执行该真实腿。

并发修复：相同非空执行键已注册时第二条执行在 spawn 前拒绝，且不能把整条预留自动结案为未执行；本地句柄的释放只删除属于自己的注册项。停止在同一锁下完成“观察状态 → 审计/不可变记录 → 取消”，写入失败不取消。Go 负例覆盖重复键拒绝、写入失败和停止与释放并发；HTTP 原有签名归属、远端未知及审计失败用例继续保留。锁保护的是本进程句柄，不是跨进程或网关事务。
