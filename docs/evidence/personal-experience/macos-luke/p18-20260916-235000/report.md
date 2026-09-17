# macOS Luke：合并最新 main 后的新候选与三宿主复测

**结论：PR 冲突已在本分支解决，新候选实测通过部分能力；Mac-P00–P05 / N09 仍未整体验收。** 将 `origin/main` 的 `052c81617438d1eabf94a5e0166338312366c491` 合并为 `720ea397ca189669516b474e6f549c52d91a8dcc`。冲突为两处 OpenClaw Python 测试脚本与 Web 内嵌产物；脚本保留两侧所需 import/原生失败诊断，内嵌产物通过锁定 npm 构建重生成。无 Go 安全核心手工冲突。上游合并带入 N05 Skill Execution Context、N06 预留/可信重试等新代码，故先前 `450fe18` 二进制和矩阵不能直接作为新候选结论。

干净源码提交上的 darwin/arm64、CGO=0、`-trimpath` 二进制 SHA256 为 `b245897b994dcd23bae30c80933407d4663340bc0e894cd4e226c297895d42f0`。本机 macOS 26.6.2 / Apple Silicon / Aqua；宿主为 OpenClaw 2026.9.4、Hermes 0.21.3、WorkBuddy 5.5.6。完整退出码见 [verification.json](verification.json)：Go 全测 `-count=1`、vet、gofmt、相关 race、四目标交叉构建，Web 95 项测试及两种构建、Control API Schema 测试均通过。四目标构建是代码门禁，不将 Linux/Windows 或已取消的 Intel Mac 当实机通过。

## 新候选原生矩阵

| 宿主 | 本候选直接原生证据 | 尚未通过 |
| --- | --- | --- |
| [OpenClaw](evidence/openclaw-native.json) | **4/8**：发现、允许、执行前拒绝、服务失联拒绝；公开 `agent --local`，受控本地模型。另有 admin 签发 `controlled_session` SEC 后允许、撤销后拒绝的真实钩子探针，**不**算可信 Skill 因果归属。 | 批准继续、批准后换参终检、可信同调用 Skill 来源、原生安装前拦截。批准门禁夹具在本机 2026.9.4 的原生 worker 于 hold 结果前退出，exit 1；未改成 pass。 |
| [Hermes](evidence/hermes-native.json) | **5/8**：前四项加批准后安全重试。公开 `chat --oneshot` 同一宿主进程先阻断原写，再由受控操作者批准；模型以**新调用 ID、相同参数**重试，服务端先签名预留后实际写入一次；拒绝例无副作用。另有 admin 签发 `controlled_task` SEC 的跨任务重放拒绝探针。 | 换参重试的原生终检、宿主证明每个实际 Skill 片段来源、原生安装前拦截。批准路径不是原调用透明继续，外部副作用不宣称 exactly-once。 |
| [WorkBuddy](evidence/workbuddy-native.json) | **5/8**：用户明确允许的隔离桌面三次无害请求，`Read` allow+observation（seq 22/23）、最终越界 `Read` deny（seq 24）、服务停机时 `Write` fail-closed；恢复后 pending 拒绝只提升一次（seq 25）。越权哨兵摘要未变，离线写目标始终不存在。 | 批准后安全继续、可信同调用 Skill 来源、宿主原生安装前拦截。 |

[18 行矩阵](manifest.json)保留所有其他组合 `not_run`，本机仅填 macOS/arm64；[结构校验](structure-report.json)退出 0，[原生覆盖校验](native-report.json)退出 **3**，3 份脱敏证据摘要核对。矩阵只验证结构与摘要，原始夹具报告保留在本机私有 `.tmp`，归档仅含所需断言和其 SHA256；不上传令牌、配对码、私钥、原始提示、账号身份或绝对用户路径。WorkBuddy 模型使用现有账号仅限用户本次明确授权的测试工作区；其真实模型调用不混同 OpenClaw/Hermes 的本地合成模型。

## 可行性结论与下一门槛

1. **N06：** Hermes 在本机可用“阻断原调用 → 明确批准 → 精确重试 → 预留 → 执行”路径，已把 `approval_resume` 从旧候选的 blocked 改为本候选 pass；换参、响应丢失和外部不确定副作用仍需独立原生负向。OpenClaw 2026.9.4 的当前批准夹具无法走到 hold 结果，不能套用旧版固定源补丁或 Linux 证据。WorkBuddy 的当前桌面接入也没有已验证的 resume/hold-status 通道。
2. **N05/N04：** SEC 的服务端和两宿主真实钩子执行探针已通过，但 `controlled_session` / `controlled_task` 由受控管理员签发；宿主没有给出可审计的每次工具调用由哪个已加载 Skill 指令直接导致的因果证明。三宿主原生安装前拦截也无本机受支持通道；保留 `host_capability_missing`，不靠模型自报或插件配置伪造。
3. **P03/P04/P05：** 可追溯历史 0.1.0 对 v2 状态的实际拒写失败见 [P15](../p15-20260916-225339/report.md)。新合入材料中使用的旧源码 `efad840` 已是 reader/writer v2，不是所需 v1-only 兼容感知旧程序；仍缺正向旧版证明。macOS 已有 `notarytool`/`swiftc` 工具，但本批没有读取 Keychain、没有正式签名身份/发布凭据授权，不把工具可用等同公证通过。当前 `osascript` 通知可投递但无可靠点击回调；登录自启的 plist 仍 `RunAtLoad=false/KeepAlive=false`，本批不暗改用户启动策略。断电耐久性和独立审阅仍未完成。

WorkBuddy 清理：新候选项目级产品钩子已卸载，原有每事件 1 条用户钩子保留；隔离 47614 已停止，项目配置恢复安装前 SHA256，日常 WorkBuddy 配置 SHA256 未变。其余宿主夹具均使用一次性 HOME/profile/状态目录和本地模型，没有动日常服务或系统安全设置。无 sudo、全局 PATH、签名/公证、正式发布或 main 合并。
