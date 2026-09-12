# M63：macOS 用户配置目录发布

日期：2026-09-12。codex/personal-client-upgrade-recovery 本地增量，未发布。

## 实现

launch-agent-register 复用签名 plist 准备，持生命周期与主 Writer，在当前规范化用户 home/Library/LaunchAgents 中排他发布实例专属链接。源签名在前后复验；重复只接受同一绝对源路径的精确符号链接。目录逐级检查/创建/同步，不跟随 Library 或 LaunchAgents 的符号链接，不覆盖已有文件、异目标或相对别名。

准备与注册共享 withPreparedLaunchAgent，保持原准备输出合同。用户目录发布例外登记在规格 §3.11.25 与模块 AGENTS.md。当前不执行 launchctl，不改变 RunAtLoad/KeepAlive，不报告已加载或保护启用。

## 验证

- Go 全量、vet、CLI race、四目标交叉构建、gofmt/diff 检查通过。
- Linux 临时 home 文件层测试：首次发布、重复复用、0700 新目录、保留已有普通用户文件；重定向 Library/LaunchAgents、异目标与相对链接、无效 label、源缺失均拒绝，重定向目标目录无写入。
- 未操作真实用户 Library，未在 macOS 运行命令或 launchctl；这些测试不构成 macOS 安装、加载、启动或登录自启验收。

| 构建 | SHA-256 |
| --- | --- |
| linux/arm64 | a02fba33bf240417e3ed9cba2eb136e5c0c1d375d4369dd8d10bb2f21d0e10fd |
| linux/amd64 | 29e212aaee5a97c02a6540647ccea3d93c9ee4967bb4329ab0087bbc3971a751 |
| darwin/arm64 | 49a32e0023dbdbac5ada398bcd9a08af4952badd14064dd289f08dc6f3ebbdd0 |
| windows/amd64 | 4a8fd7abc4fffaf6381741ec0976e4271a780a38183eeb14f7fed6e438d8bd2c |

## 下一步

实现 GUI 用户域的 launchctl 加载与归属读回，再接启动/停止/恢复；必须识别同 label 的既有任务，不能仅凭磁盘链接推断运行进程。macOS 实机环境、正式发行与跨 OS 验收仍待完成，目标保持进行中。
