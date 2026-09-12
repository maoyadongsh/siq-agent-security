# M57：本机管理页面入口

日期：2026-09-12，codex/personal-client-upgrade-recovery 本地增量，未发布。

## 行为

ui 读取本机端口，核对目录绑定健康后输出固定 loopback 管理 URL 并请求系统浏览器打开；ui --print 仅打印。setup --open-ui 在后台启动就绪后调用该入口。无凭据/配对码读取或写入 URL，无任意地址参数，无 shell；启动器为 xdg-open / open / rundll32.exe 的固定参数向量，10 秒超时、输出丢弃。打开失败保留手工地址，不停止服务。

## 验证

- Go 全量、vet、CLI race、四目标构建与 diff 检查通过。
- 模拟健康服务与浏览器回调测试：目录不符、HTML、重定向均不输出/打开页面；健康后 print 不调用启动器；打开失败保留 URL 且不透出子进程错误；任意 URL 参数拒绝。三系统固定参数向量测试通过。
- 完整 Linux CLI 在隔离 systemd 实例上执行 setup、ui --print、重复 setup，实际 URL、同 PID 和配置保持检查通过；runtime 注册完成清理。
- 未实际启动桌面浏览器，未验证页面渲染或 macOS/Windows 浏览器实机；参数测试不算原生支持验收。

| 构建目标 | SHA-256 |
| --- | --- |
| linux/arm64 | 2fcde09dd917400f6a37a0af9b95b936bab44a25bca557fd2b982afd219b028d |
| linux/amd64 | a9c00ca6abcbae099afac8d11cbff165479e49daabe101adedae972b9a235af2 |
| darwin/arm64 | 21053ac6eb9563fdf3782ea4075de32f80493ee4b6f0a9216c9e4879b4be43a2 |
| windows/amd64 | 3707a72e0c63b1b23641391c83a0f8a15276d5cefcddfb686566dbbca30b91f4 |

配对仍独立；尚未完成安装包、登录自启和跨系统后台生命周期，任务总体保持进行中。
