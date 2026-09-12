# M65：macOS 未加载状态判定

日期：2026-09-12。候选：codex/personal-client-upgrade-recovery，基于 main 69d9c59 的本地未提交工作区，包含 M48–M65。实现位置：cmd/agentshield/launch_agent_presence.go、launch_agent_status.go；规格 §3.11.27。无持久合同变更。

## 行为与来源

状态命令在签名源、注册链接和 GUI 域核对后枚举任务。全部行合法且目标精确标签缺席，才报告查询时未加载；目标存在仍核对 XML 原配置。查询失败、重复标签、截断、污染输出与详情查询间消失不解释为缺席。列表中的 PID/Status 不证明配置归属或 API 健康。原始列表不保存、不输出到错误消息。

TSV 格式依据 [Apple 历史 launchctl 源码](https://github.com/apple-oss-distributions/launchd/blob/main/support/launchctl.c) list_cmd/print_jobs：三列输出及 Status 的数字、横线和未知状态标记。该历史实现不能证明当前 macOS 支持情况。仍需真实 macOS 检查 list、list -x 与用户域行为。当前没有执行任何真实 launchctl、系统注册或服务变更。

## 验证结果

- `go test ./cmd/agentshield -run 'Test(LaunchList|InspectLaunch|LoadedLaunch)' -count=1` 通过。
- `go vet ./...`、`go test ./...`、`go test -race ./cmd/agentshield` 通过。
- 新增列表解析 24 个场景：空域、其他任务、运行/空闲目标、精确匹配、格式错误、重复、目标后污染、非法 UTF-8/控制符、数值错误及 65536/65537 字节边界。
- 新增流程 9 个场景：缺席、已加载、运行 PID、枚举失败/非法、详情间消失、异配置、异用户域、期望标签不符；错误不返回成功缺席，错误域不枚举，未确认列表不查询详情。
- 四目标交叉构建通过；不算四系统原生运行验收。gofmt 与 git diff --check 通过。

| 候选构建 | SHA-256 |
| --- | --- |
| linux/arm64 | 0e93aa5df341a3261216d58b6ae9faac5b13e8f8c5f72595ea766d511c07a0b4 |
| linux/amd64 | 279b351fa449c91b2ee7bea5b068b63b6039ca00e02b8b724bec612a232a22ad |
| darwin/arm64 | ee93379248b0399cccbd3815054f811600f4f4e5a7c82e01f0d63d49e889ec50 |
| windows/amd64 | 93d0b197ef1983145904ab48591e4cf02adec0a50f883e3f7e4be225b2e7e25a |

下一步：在即时域、签名源、精确注册链接和存在状态复核基础上实现加载/启动及恢复；未知同标签任务不接管。macOS 原生、Windows 生命周期、个人功能其余项与 LAN 均未因此完成。
