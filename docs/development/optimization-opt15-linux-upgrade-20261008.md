# OPT-15：Linux 用户服务升级与恢复

日期：2026-10-08。任务保持 **implementing**，总体 **11/16（68.75%）**。

当前二进制 `aa25999e`（`0.0.0-dev`，linux/arm64）在本机 systemd 用户会话中完成两次临时实例升级。
单元名带本次实例标识，测试结束后已不在用户会话中。没有调用模型，也没有改产品代码。

| 检查 | 结果 |
| --- | --- |
| `TestNativeUserServiceUpgrade` | 通过，1.917 秒 |
| `TestNativeUserServiceUpgradeTransientFailure` | 通过，2.687 秒 |

正向例里，开发签发清单被拒绝且原进程继续运行；同一二进制的候选路径完成切换，`config.json` 不变，再回滚到原单元且健康检查通过。
故障例里，端口占用使升级失败并给出恢复事务；释放端口后按该事务恢复，然后回滚。

这是同一字节的进程与配置切换，不是两个功能版本的兼容升级，也不是企业候选 `.3`/`.4` 的签名安装或设备迁移。
未覆盖越权决定拒绝。Windows 与 macOS 仍没有原生机器。

证据：[linux-user-service-upgrade-20261008.json](evidence/optimization-20261007/linux-user-service-upgrade-20261008.json)。
