# macOS Luke：Mac-P02 三宿主接入（darwin/arm64）

接续 [P00/P01](../p00-p01-20260915-222504/report.md)。本批在隔离宿主 HOME 与临时实例上完成 OpenClaw / Hermes 的发现→确认安装→真实宿主调用→允许/越权/撤销失联→卸载还原，并如实盘点 WorkBuddy 桌面。**macOS 总体、N09、A01–A12 全旅程不关闭。** Intel/amd64、Safari、LaunchAgent、系统通知仍未测。

配对码、管理员 token、状态私钥、日常 `~/.openclaw` / `~/.hermes` / `~/.workbuddy` 正文未写入本目录。

| 身份 | 实际值 |
| --- | --- |
| 上游 / 实现 SHA | `b303c6f92392f3a44c306d81ad7323c6291ef4f2` + 本批工作区修复（已固化为 `170c13ecfc950105cc805411e38e948e6fc69629`，重测见 [p01-retest](../p01-retest-20260916-101021/report.md)） |
| 分支 | `codex/macos-luke-p01-20260915-222504` |
| 本批 darwin/arm64 候选 SHA256 | `4fe4be6830df67a6df653a98def8017f37cf1ba20768cb6d1d9f50762a443cf0` |
| `file` | `Mach-O 64-bit executable arm64`，`CGO_ENABLED=0` |
| 发行身份 | 本机自建 `0.0.0-dev`，无正式签名 |

## 本批发现并修复的 OS/宿主问题

1. **Darwin 卷别名祖先检查。** `/var`、`/tmp` 是指向 `/private/...` 的符号链接。把任意符号链接祖先都标 corrupt 时，默认 `TMPDIR`（`/var/folders`）下的 `init`/`serve`、inventory、adapter 镜像读取和 Hermes Override 会失败。规格与 `stateformat.AcceptDirectory` 只允许卷根下、Stat 为目录的别名；状态根与用户中间路径符号链接仍拒绝。
2. **OpenClaw 2026.9.4 会话仓。** Homebrew 包不再写 `agents/<id>/sessions/sessions.json`，路由键在 `agents/<id>/agent/openclaw-agent.sqlite` 的 `session_nodes.session_key`。适配器仍只用 hook 的 `sessionKey`。托管 smoke 按当前存储读回，不假定 2026.5.12 的 JSON 路径。
3. **卸载残留。** 卸载已删除本产品插件文件，但留下空的 `plugins/siq-agent-security` 目录；OpenClaw 在接入前无 `plugins` 时把空 `entries`/`load.paths` 写回用户配置。已改为：空产品插件目录删除；剥离登记后若无用户 plugins 则删除该键。含未知文件的目录仍保留。

Hermes 原生命令启用会规范化 YAML（`_config_version`、空 plugins 列表）。用户 `model` 设置保留；接入前原文在 `*.siq-agent-security.orig`。这是宿主格式，不是把无关插件删掉。

## 实测结果

| 组合 | 结果 | 材料 |
| --- | --- | --- |
| OpenClaw 2026.9.4 Homebrew CLI，`agent --local`，托管 v3 安装 | 17 项检查通过：预览不改宿主、安装资产与源一致、无 `installPolicy`、允许读、越权写未落盘、撤销后新调用阻断 | [openclaw-managed-native.json](openclaw-managed-native.json) |
| Hermes v0.21.3 CLI，独立 work profile，托管安装 + 原生命令启用 | 17 项检查通过：默认 profile 未改、自检与实例授权分离、允许/拒绝/撤销 | [hermes-managed-native.json](hermes-managed-native.json) |
| 隔离 HOME CLI 确认安装 / 卸载 | 预览无副作用；Skill 与用户保留文件未改；卸载去掉产品插件目录和空 OpenClaw `plugins` 键 | [isolated-install-restore.json](isolated-install-restore.json) |
| Hermes 原生 dispatcher 失联 | daemon 被杀后写/读哨兵未执行，`fail-closed` + pending；重启后绑定恢复 | [hermes-intent-offline.json](hermes-intent-offline.json) |
| WorkBuddy 5.5.6 桌面应用 | 仅只读盘点。Electron 主程序，无 CLI，包内未见 SIQ 钩子。日常配置未打开、未写入。允许/越权/失联 **blocked** | [workbuddy-inventory.json](workbuddy-inventory.json) |

OpenClaw 2026.5.12 风格的 `validate-intent-v2-openclaw.py` worker 在本机 2026.9.4 上失败（未把宿主 stderr 写入材料）。公共 `openclaw agent --local` 托管会话是本批有效入口，不能用 worker 失败否定托管 smoke。OpenClaw **daemon 被杀** 的独立失联未在本批用 worker 复证；托管会话证明的是服务仍在时的越权拒绝与身份撤销 fail-closed。

## 未运行 / blocked

- darwin/amd64 native、Rosetta
- Safari / 系统浏览器管理会话
- WorkBuddy 真实桌面交互、钩子、安装拦截、可信归属
- LaunchAgent 用户域（Mac-P03）
- 系统通知、正式签名/notarization
- 日常宿主 HOME 写入
- 浏览器确认安装路径（本批 CLI / 托管 API）
- OpenClaw 2026.9.4 的旧 worker 夹具

## 副作用与恢复

隔离宿主 HOME 的 7 个夹具 Skill/配置在卸载后仍在。产品留下首次接入 `*.orig` 快照（规格：人工恢复参考，不覆盖）。测试用 `user-keep` 文件已删除。日常 LaunchAgents、Keychain、默认 SIQ 状态未改。监听 `127.0.0.1:47612` 的既有 P02 管理进程未被本批终止。

下一批：Mac-P03 LaunchAgent / APFS / N01。本批已在隔离状态目录做只读 `launch-agent-plist` 与 `launch-agent-prepare`（`RunAtLoad=false`、`KeepAlive=false`、日志 `/dev/null`，用户域 LaunchAgents 无本产品条目，未 register/load）。见 [launch-agent-prepare.json](launch-agent-prepare.json)。
