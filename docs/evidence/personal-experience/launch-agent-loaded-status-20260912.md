# M64：macOS 已加载任务的只读配置核对

日期：2026-09-12。codex/personal-client-upgrade-recovery 本地增量。

## 依据与选择

[Apple 开源 launchctl 实现](https://github.com/apple-oss-distributions/launchd/blob/main/support/launchctl.c)的 list_cmd 提供 list -x label XML 输出，并有 manageruid/managername 查询。该代码属于历史兼容接口依据，不能证明当前 macOS 提供相同能力。当前没有本机 launchctl/macOS 环境；接口不支持时拒绝，不改用未约束的 print 人类输出当作安全事实。

## 实现

新增 launch-agent-status。先只读验证签名配置和用户目录链接，再经绝对 /bin/launchctl 查询当前非 root uid、Aqua manager 和指定 label 的 XML。15 秒/64 KiB 输出限制，不保留或打印原始 manager 内容，剔除 LAUNCHD_SOCKET 覆盖。

XML 标准库解析限制 64 KiB、16 层、2048 元素，拒绝重复 key、命名空间、嵌套标量和不支持类型。原渲染所有字段必须相等，额外字段仅允许 PID、整数 LastExitStatus、OnDemand=true、LimitLoadToSessionType=Aqua；其他字段不猜测默认含义。无 PID 只报告已加载，正 PID 才进一步核对目录 API 健康。命令失败从不解释为任务不存在。

本批不执行 bootstrap/kickstart、不中止或替换任务，不证明内存映像身份。

## 验证

- Go 全量、vet、CLI race、四目标构建与 diff 检查通过。
- 模拟 launchctl：已加载无 PID、已运行 PID 读取；外用户/非 Aqua 在 list 前拒绝；参数/环境差异、执行覆盖、非法 PID、非 XML 拒绝；root 不查询，失败不解释为不存在。
- XML 负向：重复字段、标量嵌套、布尔杂项、命名空间、非法整数、缺值、过深、过多节点、尾随文档、超大输入全部拒绝。
- 没有真实 macOS 查询/启动或完整 CLI 成功证据，模拟输出不算原生支持。launch-agent-status 当前兼容性仍待 macOS 实测，不能据此标记 UX-003 完成。

| 构建 | SHA-256 |
| --- | --- |
| linux/arm64 | 90f153e86f74145095f533ffe937983ea904f7624ed68438a8488fb7a2adb577 |
| linux/amd64 | 1d805f311f3e1803801c41ede5e1093dbe9915af0d7d03da717825118ca51457 |
| darwin/arm64 | b20282ce4b4622e6d435f6d360175574915b113bbbe2e7099b651d863718c428 |
| windows/amd64 | 81c810726931eb36765f1ac5181cb9cfc608f61aecab53a251bd5ed7397d9325 |

下一步加载流程必须依赖域确认和完整配置核对，并保留对未知同 label 任务的拒绝；不把失败查询用作不存在证据。
