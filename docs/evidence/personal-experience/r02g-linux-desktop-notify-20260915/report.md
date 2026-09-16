# R02-G Linux 桌面通知传输验收

日期：2026-09-15。结论：当前 Linux/aarch64 实机的产品通知链 6/6 通过。启用 `desktop_notify` 的真实 SIQ daemon 在出现一条签名 pending hold 后调用系统 `notify-send`，GNOME 会话总线实际收到 `org.freedesktop.Notifications.Notify` 方法调用。

通知标题为 `SIQ AgentShield`，正文严格为“有 1 项待确认操作，请在本地控制台处理”。总线消息不包含工具调用 ID、action ID、receipt ID 或参数。测试最后明确拒绝 pending hold，并验证签名回执链，未留下待处理授权。

## 身份与边界

- 候选二进制 SHA256：`b6e7650f9ab35f6b259cbd64fe9be5a19347b3689ed3dab0be38874d4bda6708`
- Runner SHA256：`2ff1165f04f11d0409252202f28799f01ae13ddbf7f77333dcdbe28172f8b332`
- `notify-send` SHA256：`21491085324f2859a9c5e6d60279b9f26185611cba7fe36b775ccdb88cbfd91b`
- 环境：Linux 6.17.0-1014-nvidia/aarch64、远程 TTY，复用当前登录用户的真实 GNOME notification service。
- 证据证明产品调度器到桌面会话总线的真实传输已被系统服务接受；远程测试无法观察屏幕像素或证明用户实际看见通知。
- hold 和操作者是自动测试夹具，没有真人审批或外部模型；Windows/macOS 通知不由本报告覆盖。

机器可读结果见 [report.json](report.json)，文件摘要见 [SHA256SUMS](SHA256SUMS)。
