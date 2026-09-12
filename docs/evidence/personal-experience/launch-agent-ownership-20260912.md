# M62：macOS 配置签名归属与准备恢复

日期：2026-09-12。codex/personal-client-upgrade-recovery，本地未提交开发增量。

## 实现

新增 local-launch-agent-record/v1，规范化 Ed25519 绑定实例 ID、状态目录 ID、完整实例 label、plist SHA-256。launch-agent.json 与 <label>.plist 只在状态目录内排他发布；先记录意图再发布配置。已有记录必须完整匹配且验签，缺失配置可复用意图恢复；未知配置、变更内容、损坏签名拒绝。独立于 Linux user-service 合同。

launch-agent-prepare 仅 macOS，复用渲染与生命周期/主 Writer，输出签名记录。VerifyLaunchAgent 只读不修复；底层只固定渲染字节，不解释任意 plist 或宣称系统已加载。

## 验证

- Go 全量、vet、state/CLI race、四目标构建、gofmt/diff 检查通过。
- 状态正负向覆盖无 Writer、重复准备、缺失配置只读拒绝且不修复、显式准备恢复、内容漂移保留、未知文件拒绝接管、克隆目录拒绝、签名篡改和 Linux 记录混用拒绝。
- Go 运行生成固定 record 样例，Python 校验 schema、Ed25519 签名、对应 plist 哈希/label、缺字段/坏字段/额外字段拒绝；合同共 159 项通过，ruff 通过。
- 所有状态测试在 Linux 临时目录执行，未注册或启动 macOS LaunchAgent，没有 macOS 原生证据。

| 构建 | SHA-256 |
| --- | --- |
| linux/arm64 | 2b52c2c6aff96ec81d235b3e3f53d43d9046a58f65f24f693e669cd4f6214219 |
| linux/amd64 | bde6f3ce6966e6d76754112c669f15f939bb73e7a480ce11071201cce4f8752a |
| darwin/arm64 | ab4364340afc95371fbc30e2d2b52d90075a19cb96ba95ce9f96490bb92da7cb |
| windows/amd64 | 1b2fa27be618e65bfedd3420adfb76bf8218a2f5dee0cd5c5e9af2ed09b1a2fa |

## 剩余与台账

后续 macOS 系统注册、launchctl 读回与停止/恢复尚未实现。真实 OS/平台验收、正式制品与团队范围均未完成。台账首页已纠正停留在 M36 的当前基线，记录 main M47 与本地 M48–M62，UX-003/014 状态更新为实际部分实现，未标整体完成。
