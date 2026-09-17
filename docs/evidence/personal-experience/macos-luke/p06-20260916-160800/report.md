# macOS Luke：P06 原生升级/回滚与文件系统、Skill 深度负向

接续 [P05](../p05-20260916-151500/report.md)。本批补齐任务书第二类本机可做项中优先级最高的三条：§6.3.5 macOS 沿 LaunchAgent + clientrelease 的原生升级/回滚，§6.2 文件系统负向剩余项，§7 Skill 深度负向中产品已强制的实机路径。**macOS 总体、N09 不关闭。** 配对码、管理员 token、状态私钥未写入本目录。

| 身份 | 实际值 |
| --- | --- |
| 分支 | `codex/macos-luke-p06-20260916-153008`（工作区脏；未提交） |
| git HEAD | `e03c9f5bb9f5208d673b23e96ad0d5b8f2d8385b` |
| 受测二进制 | darwin/arm64，SHA256 `823d44be2626214a6e97c102c1b6e892fc953eb5a43f0f449c862a833a5ba0e1`（`CGO_ENABLED=0`、`-trimpath`、go1.27.1；adhoc/linker-signed，非正式签名） |
| 本机 | macOS 26.6.2，Apple M4，`sysctl.proc_translated=0`，Aqua GUI 域 uid 501 |

## 1. §6.3.5 macOS 原生升级 / 失败恢复 / 显式回退

规格已写 §3.11.53–54；§3.11.12/13 改为指向 macOS 组合，不再把 systemd 语义套到 launchd。产品入口 `service-upgrade` / `service-rollback` 在 darwin 走 `local-launch-agent-switch/v1`：stop → Writer → 切换 plist/`launch-agent.json` → bootout → bootstrap → kickstart。

opt-in 实机（`SIQ_TEST_UPGRADE_LAUNCHD=1`，真实 `gui/501`）：

| 用例 | 结果 |
| --- | --- |
| 同一受信构建两路径升级 → 健康 → 回退 | **pass**；PID 77075 → 77109 → 77153；事务 `ec64ad7c…` |
| 开发签发者 CLI 拒绝且不中断源进程 | **pass**（生产 CLI，无信任根覆盖） |
| 注入端口占用失败启动后 `--recover` 前滚，缺失旧程序从本地快照恢复，再回退 | **pass**；PID 77209 → 77279 → 77314；事务 `b6504d66…` |
| 结束后 LaunchAgents 无 siq 链接、无已加载 siq 作业 | **pass** |

材料：[native-upgrade.json](native-upgrade.json)，模拟控制器负向见 [switch-cmd-tests.txt](switch-cmd-tests.txt)、[switch-state-tests.txt](switch-state-tests.txt)。

这些证明的是进程/配置切换与恢复，**不是**不同发行版本兼容或 Developer ID / notarization。

## 2. §6.2 文件系统负向

[darwin-fs-tests.txt](darwin-fs-tests.txt)（默认 APFS TempDir + 用户态 `hdiutil` 挂到测试 mountpoint，不填用户磁盘、不改 `/Volumes` 日常挂载）：

| 项 | 结果 |
| --- | --- |
| 路径空格/中文/NFC 初始化 | compatible=ok |
| 同一 inode 的 NFD 拼写 | APFS 别名为同一目录；`DirectoryID` 拼写不一致则 `state-status` fail-closed `corrupt`（路径拼写提示），不生成第二身份 |
| 大小写别名路径 | 不把 `CAFÉ 中文` 当作原绑定 |
| `O_EXCL` 排他发布 | 已有文件返回 exist，内容不变 |
| POSIX chmod vs xattr / ACL | chmod 0600 不清除 `siq.test` xattr，也不清除 `everyone deny write` ACL；N01 **仍不复制** ACL/xattr |
| 只读目录 / 只读卷 | 拒绝创建，占位文件不变 |
| Case-sensitive APFS | `instance` 与 `Instance` 为两个 DirectoryID、两套 instance 身份 |
| 跨卷 `Link` | 失败且不留下目标占位（EXDEV） |
| 小容量卷 | 8MiB 卷写 8MiB 返回 `no space left on device`，不是覆盖未知对象 |
| 导出脱敏 | 中文状态目录下植入 raw-content 哨兵，CLI export 不含哨兵/`ciphertext_base64` |

未测/不声称：正式签名扩展属性清理、SIP 关闭、把 ad-hoc 当公证。

## 3. §7 Skill 深度负向（本机已强制语义）

[skill-darwin-tests.txt](skill-darwin-tests.txt) 全部 pass：

| 子项 | 结果 |
| --- | --- |
| Unicode 文件名占位（NFC 载荷 vs NFD 占位） | 安装不得标成功覆盖；占位保留或进入 recovery |
| 大小写目录别名 | APFS 上 `EXAMPLE`/`example` 冲突 → `recovery_required`，`user.txt` 保留 |
| 父目录 0555 | 安装失败，不留下所属安装文件 |
| 时钟过期 | Stage 后时间拨过 `ExpiresAt`，Apply 失败且不把目标标为已安装 |
| 首个文件发布后目录改 0555 | 不得标 `installed_unverified` |
| 发布窗口撤销 | `rolled_back`，所属目标删除 |

未做（仍缺实机旅程，不以单测冒充）：GLM 安全 Git 导入、系统休眠、损坏密文的独立浏览器旅程（导出脱敏与 raw-content 篡改 fail-closed 仍由既有包测试覆盖）、通知点击导航（osascript 无回调，缺口已记录）。

## 4. 开发检查（本批触及的 Go 包）

隔离 Go 1.27.1，`CGO_ENABLED=0`：

- `gofmt -l .` 空
- `go vet`：`cmd/agentshield`、`internal/state`、`internal/stateformat`、`internal/skillinstall` 通过
- `go test ./... -count=1`：模块全部包通过（约 110s；`cmd/agentshield` 含 Darwin 卷测试，opt-in launchd 用例在无 `SIQ_TEST_UPGRADE_LAUNCHD` 时 skip）

未在本批重跑 web / control-api / 四目标交叉构建（未改那些树）。Intel/amd64 实机仍缺。

## 5. 仍保持缺口（不关闭总体）

- WorkBuddy `native_desktop`、Safari、正式签名/公证、登录/重启/休眠唤醒、真实断电
- §6.3.4 旧程序拒写：仓库历史没有「只认 v1、不认 v2」的 macOS 保护二进制可复建；该项保持 blocked
- GLM Git 导入、SSH 无 GUI 通知、UserNotifications 点击导航、approval-gate 2026.9+ 插件挂接
- 独立审阅确认、N09 总体验收、最终干净 PR head 重测

清理：opt-in launchd 测试自卸注册链接；证据私有根 `~/.local/siq-macos-luke-p06-upgrade-evidence-20260916` 仅含脱敏日志。未提交、未推送。
