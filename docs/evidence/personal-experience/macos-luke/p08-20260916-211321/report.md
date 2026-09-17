# macOS Luke：干净候选回归与 WorkBuddy 参数终检收口

本批把 P06/P07 的实现提交后，以干净 HEAD `2162907c980c9a4d17a22d64437be9b97502f9ab` 重建 darwin/arm64 CGO=0 候选，并重跑 OpenClaw、Hermes、WorkBuddy 原生路径。WorkBuddy 新增真实桌面 `final_parameter_recheck` 通过；测试清理时发现并修复跨配置根重装会污染卸载记录的恢复缺陷。未推送、未发布，未改日常 WorkBuddy 配置、全局 PATH 或系统安全策略。

| 身份 | 实际值 |
| --- | --- |
| 分支 | `codex/macos-luke-p06-20260916-153008` |
| 候选 SHA | `2162907c980c9a4d17a22d64437be9b97502f9ab`（构建时干净） |
| 二进制 | Mach-O arm64，SHA256 `7ea96e90fc3b9012f98e32d24406534ccf9d0d847bf8b52206c47eff93dc9362` |
| 构建 | go1.27.1 darwin/arm64，`CGO_ENABLED=0`，`-trimpath` |
| WorkBuddy | 5.5.6，已登录 Aqua 桌面，会话工作区和 SIQ 状态均隔离 |

配对码、管理 token、状态私钥、宿主账号内容及未脱敏绝对用户路径未写入本目录。

## 干净候选原生回归

- [OpenClaw](openclaw-managed-native.json)：公开 `openclaw agent --local` 与真实插件生命周期，17 项检查通过；写前拒绝、允许读、原参数/结果显式授权采集、回执链和身份撤销均通过。
- [Hermes](hermes-cli-runtime.json)：公开 `hermes chat --oneshot` 与真实插件生命周期，6 项检查通过；允许读、写前拒绝、拒绝后继续和回执链均通过。
- [WorkBuddy](workbuddy-final-parameter-recheck.json)：真实桌面任务要求 Read 最终解析到隔离工作区根的 `outside.txt`，而 Grant 只允许 `safe/`。签名回执 seq 10 为 `action=deny`、`reason_code=grant_scope_violation`；目标文件前后 SHA256 相同。模型随后尝试 Bash/Glob/Grep，seq 11–13 均默认拒绝。回执链 14 条、head_seq 13 验证通过。

## 清理阶段发现并修复的恢复缺陷

同一 WorkBuddy 状态先后对两个 `WORKBUDDY_CONFIG_DIR` 安装时，旧实现把两份路径合并到一个记录，但卸载只处理当前配置根并立即写入已卸载标记，另一根可能遗留产品钩子。修复提交 `2162907` 在已有 CodeBuddy/WorkBuddy 记录与当前配置根不一致时，于任何写入前 fail-closed；`TestWorkBuddyReinstallRefusesDifferentConfigRoot` 证明第二根未创建、第一根未变化且仍可正常卸载。

现场残留使用安装时不可变 `.siq-agent-security.orig` 精确恢复。最终两个隔离配置均无产品 hook，47614 已停止；既有 47612/47613 未停止。日常 `~/.workbuddy/settings.json` SHA256 仍为 `89e179cf…` 且无产品 hook。

## Mac-P00–P05 状态

| 阶段 | 当前结论 |
| --- | --- |
| Mac-P00 | 本机环境、APFS/Aqua、Apple M4 arm64 原生和隔离边界已完成；Intel/amd64 与 Rosetta 保持 blocked/not_run。 |
| Mac-P01 | 原生构建、配对/会话、错误实例和 LaunchAgent 用户域生命周期已实测通过；正式签名/公证不在本机开发候选结论内。 |
| Mac-P02 | OpenClaw、Hermes 当前干净候选回归通过；WorkBuddy 为 5/8：discovery、normal execution、pre-execution deny、service-unavailable deny、final-parameter recheck 通过。 |
| Mac-P03 | LaunchAgent、Darwin 卷别名/APFS 负向、N01 原生升级/失败恢复/显式回退的可执行路径通过；旧 v1 程序拒写、退出登录/重启/休眠和真实断电保持 blocked/not_run。 |
| Mac-P04 | macOS 通知投递、审批收件箱、Skill 安装/更新/移除和 OpenClaw/Hermes 宿主路径已有实测；通知点击导航及 WorkBuddy 缺失宿主通道不伪称通过。 |
| Mac-P05 | 18 行材料合同和已有 macOS arm64 行已校验；本批提供最终干净候选增量证据。N09 不关闭，因为 Intel/amd64、独立审阅及下述宿主能力仍缺。 |

WorkBuddy 仍有三项 `host_capability_missing`：`approval_resume`（无 resume/hold-status 通道）、`skill_attribution`（无可信同调用 Skill 上下文）、`install_interception`（无受支持 pre-install hook）。这些是明确阻塞，不用 stdin 夹具或模型口述替代。

## 开发验证

[verification.json](verification.json) 记录：`gofmt`、`go vet ./...`、`go test ./... -count=1` 全过；linux/amd64、linux/arm64、darwin/arm64、windows/amd64 四目标 CGO=0 编译通过。跨平台编译不替代对应 OS 原生验收。
