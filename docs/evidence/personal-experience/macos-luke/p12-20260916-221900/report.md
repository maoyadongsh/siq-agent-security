# macOS Luke：WorkBuddy 桌面实测恢复与剩余缺口

**结论：Mac-P00–P05 尚未整体通过。** 用户手动操作 WorkBuddy 后，本批在真正的 WorkBuddy 5.5.6 macOS 桌面继续完成同一代码候选的工具调用，不沿用前批“发送不可用”的 0/8 结论。WorkBuddy 现在有 **5/8** 项直接原生证据；OpenClaw、Hermes 各 **3/8** 项直接原生证据。Hermes 另有 1 项已安装调度器夹具证据，不算公开 CLI 原生通过。用户已取消 Intel/amd64 实机范围；保留 18 行材料合同中的该行 `not_run`，不将其当阻塞或支持声明。

| 身份 | 值 |
| --- | --- |
| 受测源码 | `450fe1836d8a3bffefbd2ce9b6f02bbbfe730c64`，构建与补跑 Hermes 夹具时均为干净工作树 |
| 受测制品 | Mach-O arm64、CGO=0、`-trimpath`、隔离 go1.27.1；SHA256 `f067f96b05c3472b8ebe2d43ac9c19ce79c5063af19ec1dc66999a6da1bd3e23` |
| 本机/宿主 | macOS 26.6.2、Apple M4；OpenClaw 2026.9.4、Hermes 0.21.3、WorkBuddy 5.5.6 |
| 隔离 | 私有 HOME/状态/Go 缓存/工作区、仅 47614 测试服务；无 sudo、全局 PATH、安全策略更改、推送或发布 |

## P02：真实 WorkBuddy 桌面链路

隔离项目配置装入本候选 PreToolUse/PostToolUse 钩子，WorkBuddy Aqua 桌面实际打开受控工作区并发起工具调用；非产品原有钩子保留。具体脱敏断言见 [workbuddy-native-desktop.json](evidence/workbuddy-native-desktop.json)。

| 检查 | 实际观察 |
| --- | --- |
| discovery / normal_execution | WorkBuddy 原生 `Read` 允许；预执行回执 seq 16 `allow`，后执行 seq 17 `observation_accepted`；只读哨兵摘要前后不变。 |
| pre_execution_denial / final_parameter_recheck | 新桌面任务最终 `Read` 参数指向授权目录外哨兵；seq 18 `deny/grant_scope_violation`，宿主未读到内容，哨兵摘要前后不变。此前模型口头拒绝的尝试不计数。 |
| service_unavailable_denial | 先停本批隔离 47614，再由桌面原生 `Write` 尝试创建受控哨兵；宿主工具结果明确为 `decision service unavailable; blocked (fail-closed)`，目标前后均不存在。服务恢复后，待处理失联记录提升为签名拒绝回执 seq 19；不能说服务停止时已写出签名回执。 |
| 恢复 | 重启仅隔离 47614 后，桌面原生 `Read` 再得 seq 20 `allow`、seq 21 `observation_accepted`；`verify --chain local` 返回 `verified=true`、`head_seq=21`、22 条回执。 |

测试后只卸载隔离项目配置里的产品钩子；Pre/Post 每个事件仍各有 1 条原有非产品钩子。受控越权哨兵已移至私有 artifacts，不在工作区遗留。47614 已停止，原有 47612/47613 未操作；日常 WorkBuddy 配置 SHA256 仍为 `89e179cfe920c2ee4f8956f291ebc0013955071fbd75d320b1ffa410d37541fa`。私有状态及日志未归档；本目录不包含配对码、token、私钥、账号/对话原文、绝对用户路径或桌面截图。

## 同候选 Hermes 补证与 18 行材料

[Hermes 调度器夹具](evidence/hermes-dispatcher-component.json) 在该提交的临时干净工作树上、使用同一二进制与已安装 Hermes 0.21.3，15 项全过，包括插件加载、实际原生工具调度、越权拒绝、daemon 被杀后失联拒绝、待处理证据恢复与回执链。它绕过公开 `hermes chat --oneshot` 的完整模型会话，故在 [矩阵](manifest.json) 中把 `service_unavailable_denial` 标作 `component_fixture`，`--require-native` 仍将其列为缺口。已有公开 CLI 的 [OpenClaw](evidence/openclaw-managed-native.json) 17 项与 [Hermes](evidence/hermes-cli-runtime.json) 6 项 smoke 沿用同一候选、同一二进制的 P11 原始脱敏材料；各自原生通过项仍只有发现、正常执行、执行前拒绝。

按任务书 §8.2，仓外私有证据根生成完整 18 行矩阵，再复制脱敏材料归档。结构/证据摘要校验 [退出 0](structure-report.json)，`--require-native` [退出 3](native-report.json)，4 个引用文件的摘要均核对成功。材料工具只校验身份、格式、摘要和覆盖，不认证行为真实性。当前代码的 Go 全测、vet、gofmt、race、四目标交叉编译及两个公开 CLI smoke 的退出码见 [P11 验证](../p11-20260916-220456/verification.json)；本批新增检查见 [verification.json](verification.json)。

## P00–P05 当前验收边界

| 子批 | 当前可证明的完成部分 | 尚不能关闭的条件 |
| --- | --- | --- |
| P00–P01 | Apple Silicon/arm64、真实 GUI、隔离构建、配对/管理、LaunchAgent 当前 GUI 用户域生命周期已有前批实机材料。 | 正式发行签名/公证不以开发制品替代。 |
| P02 | 三宿主已接入并见真实工具调用；WorkBuddy 本候选 5/8，OpenClaw/Hermes 公开 CLI 各 3/8。 | 三宿主批准后原调用安全继续、同次可信 Skill 来源、宿主原生安装前拦截；OpenClaw/Hermes 的本候选公开 CLI 失联与最终换参仍缺。 |
| P03 | Darwin 卷别名修复、APFS/LaunchAgent、N01 迁移与原生升级/回滚已有前批材料。 | 仓库无法复建确切的“v1-only 且拒绝 v2”旧 macOS 保护程序；退出登录/重启/休眠和真实断电窗口未安排，不能冒称完成。 |
| P04 | 实际 macOS 通知投递、审批收件箱、Skill 安装/更新/移除已有分批材料。 | 当前 `osascript display notification` 无可靠点击回跳；三宿主真实 hold/resume、通知被拒/免打扰等系统场景和完整用户旅程未全证。 |
| P05 | 本候选结构校验 0、原生全覆盖 3；Intel/macOS 已由用户取消实机范围。 | arm64 三宿主 A01–A12 全旅程与独立审阅未通过，N09 不关闭。 |

对 WorkBuddy 的能力结论仅限本机 5.5.6 与实际钩子输入/调用。官方 [WorkBuddy 插件文档](https://www.workbuddy.cn/docs/workbuddy/Plugins)列有 Hook 插件类型；[CodeBuddy CLI Hook 文档](https://www.workbuddy.cn/docs/cli/hooks)列有 `PreToolUse` 及权限事件，但属于另一宿主，不能直接当 WorkBuddy 桌面的审批继续、可信 Skill 来源或安装前拦截合同。此处 `host_capability_missing` 表示当前接入没有已验证的受支持检查点，不声称供应商未来版本永远不可能提供。

下一步需要宿主提供/确认上述三个受信通道和旧版可追溯制品；整机注销、重启或休眠需操作者安排不会中断日常任务的维护窗口；正式签名/公证与独立审阅需外部授权或人员。缺这些条件时继续保持 blocked，不以模型提示、延长等待或构造旧二进制补绿。
