# M61：macOS LaunchAgent 配置导出

日期：2026-09-12，codex/personal-client-upgrade-recovery 本地增量。

## 实现

macOS launch-agent-plist 只读导出已初始化实例配置。复用 currentServicePaths 的实例、配置文件及规范化程序路径检查，不改 Linux service-unit 输出。标签包含完整实例 ID，argv 为程序与 serve；环境显式绑定状态目录，输出到 /dev/null，不自动运行/保活。标准库 XML 转义保留路径原文，非法 UTF-8、控制字符、XML 禁止码点、非规范路径和 ID 拒绝。

字段依据：[Apple LaunchAgent 指南](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)及[Apple launchd.plist 定义](https://github.com/apple-oss-distributions/launchd/blob/main/man/launchd.plist.5)。Umask 使用十进制 63，退出等待 30 秒。不添加独立守护进程或第三方库。

## 验证

- Go 固定 plist 样例与运行输出一致，XML 解析验证 argv/环境路径；实例隔离、相对/非规范路径、控制字符与非法 ID 负向通过。
- Python plistlib 独立解析样例并核对完整字段；合同测试合计 158 项通过，相关 ruff 通过。
- Go 全量、vet、CLI race、四目标交叉构建、diff 检查通过。
- 因提取共用路径检查，回归隔离 Linux 完整 setup/ui/self-start/teardown/重新 setup 流程通过；macOS 未运行 launchctl，不能视作实机支持。

| 构建 | SHA-256 |
| --- | --- |
| linux/arm64 | 82c12143a092ab0fce60b1e03884436a5df16624ecf6a56b650c9f3130e961fc |
| linux/amd64 | 46b6a2e1b651cc916a45edc44b5d43924c6950785b5af123841ba70bcaf0fd88 |
| darwin/arm64 | e63d249eb36b45d4d548dd6c8b2bc0da7c17961f53ba62be8e13e163d9442f55 |
| windows/amd64 | 1f5a2dda8f727b0aa6701da292cc7ff3d3e136a41e44b0e1b9ad9bfbdac8d910 |

## 下一步

增加 macOS 签名归属合同和可恢复发布、launchctl 注册/读回/停止；不得套用 Linux unit_name 合同。当前导出不写 Library/LaunchAgents、不启动/自启，不是安装完成。真实 macOS 环境、发行制品与跨系统验收继续待办。
