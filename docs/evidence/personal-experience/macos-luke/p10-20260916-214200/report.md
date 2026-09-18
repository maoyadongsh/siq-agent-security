# macOS Luke：混合配置根恢复与当前候选验收矩阵

本批修复旧桌面安装记录跨配置根卸载时遗留产品钩子的恢复问题，再以干净源码候选 `39e8ef5561021b4f96a579fff506b36ca802c08b` 复测三个真实宿主，并重建 18 行材料矩阵。**本机 macOS arm64 的部分检查通过；Mac-P00–P05 / N09 总体未达到完整验收。** 原 P05 报告的 OpenClaw/Hermes 8/8 包含浏览器夹具、配置还原和其他宿主的替代材料，不能视为当前候选的八项原生通过；保留历史报告，但以本批矩阵为当前候选的保守结论。

| 身份 | 实际值 |
| --- | --- |
| 分支 | `codex/macos-luke-p06-20260916-153008` |
| 候选 | `39e8ef5561021b4f96a579fff506b36ca802c08b`，构建时工作区干净 |
| 二进制 | Mach-O darwin/arm64，CGO=0、`-trimpath`、隔离 go1.27.1；SHA256 `d9f4b381a488cf95b58914a8a590974a69759d2415edae87d00707dc3e435155` |
| 本机 | macOS 26.6.2，Apple M4，GUI 桌面；OpenClaw 2026.9.4、Hermes 0.21.3、WorkBuddy 5.5.6 |
| 隔离 | 私有状态/HOME/工作区、隔离 Go 工具链和缓存；无 sudo、全局 PATH、安全策略更改；无推送或发布 |

## 缺陷与恢复

历史记录可能已经混有两个 WorkBuddy/CodeBuddy 配置根。只拒绝以后跨根安装会让这类旧记录无法完整卸载。`c64b932` 使卸载遍历该记录**实际创建/修改过**的配置文件，逐根精确移除本产品钩子，且保留新跨根安装的写前拒绝；二进制与状态路径经 shell 引号处理。`39e8ef5` 排除仅在元数据中出现、并未由本产品写入的路径，防止卸载时越权处理。新增正负向测试覆盖混合根恢复、仅元数据路径保持原样、带空格/引号的实际 shell 参数及新跨根拒绝。规格已先同步。此修复不宣称恢复任意手工改造的未知钩子。

## 当前候选原生检查

| 宿主 | 本批直接通过 | 尚未证明 |
| --- | --- | --- |
| [OpenClaw](evidence/openclaw-managed-native.json) | 3/8：discovery、normal_execution、pre_execution_denial；公开 `agent --local`、真实插件生命周期、允许读/写前拒绝、签名回执、身份撤销；17 个细项通过 | service_unavailable_denial、final_parameter_recheck 本候选未重测；approval_resume、skill_attribution、install_interception 无可信原生能力证明 |
| [Hermes](evidence/hermes-cli-runtime.json) | 3/8：discovery、normal_execution、pre_execution_denial；公开 `chat --oneshot`、真实插件生命周期、允许读/写前拒绝、拒绝后继续及签名回执；6 个细项通过 | service_unavailable_denial、final_parameter_recheck 本候选未重测；approval_resume、skill_attribution、install_interception 无可信原生能力证明 |
| [WorkBuddy](evidence/workbuddy-native.json) | 3/8：discovery、pre_execution_denial、final_parameter_recheck；真实 5.5.6 桌面 Read 的最终参数落到隔离工作区的越权目标，签名回执 seq 15 为 `deny/grant_scope_violation`，受控目标前后 SHA256 相同，16 条回执链已验证 | normal_execution、service_unavailable_denial 曾在旧候选 P08 实测，但本候选未重测；approval_resume、skill_attribution、install_interception 仍缺受支持的宿主检查点 |

OpenClaw/Hermes 使用合成模型和操作者，故没有借此声称真人批准、可信 Skill 归属或 OS 隔离。WorkBuddy 无安装前拦截、可信同次 Skill 来源与 hold/resume 通道，不以模型口头行为替代宿主能力。跨平台 15 行（含 macOS Intel/amd64）保持 `not_run`，不把交叉编译当原生通过。

## 材料与副作用

按任务书 §8.2，在仓库外私有的 `siq-macos-luke-p10-evidence-20260916-214200` 根创建脱敏证据副本，生成 [18 行清单](manifest.json)。`platform_acceptance.py verify` 的结构/哈希校验退出 **0**；`verify --require-native` 退出 **3**（覆盖缺口，预期），结果分别见 [structure-report.json](structure-report.json) 和 [native-report.json](native-report.json)，均为 `needs_native_evidence`、3 个文件摘要通过。直接用本归档目录作为 `--evidence-root` 重跑亦为 0/3，结构报告逐字节相同。材料校验器只核对格式、身份、摘要和覆盖，不等于独立安全认证。

WorkBuddy 受控 `outside.txt` 的前后 SHA256 均为 `2c130edb6409ed676b7d4a0de5502170a746386b4fb58ed0ec5ec9d9f2d95789`，未见被禁止的写入。试验后停止仅隔离端口 47614，卸载产品钩子，两份隔离配置均不留钩子；日常配置摘要 `89e179cfe920c2ee4f8956f291ebc0013955071fbd75d320b1ffa410d37541fa` 未变化且无本产品钩子，既有 47612/47613 未停止。状态密钥、配对码、管理 token、账号内容、原始提示/回复与用户绝对路径未归档。原始私有状态留在本机受控范围，未提交。

## 尚需继续

- P02：同候选对三个宿主补失联、允许/还原；对 WorkBuddy 补正常允许与失联；可用宿主能力才能完成同次 Skill 归属、安装前拦截和批准后可信继续。
- P03/P04：旧 v1 macOS 二进制拒写、注销/重启/休眠窗口、真实通知点击导航、平台真实 hold/resume；正式签名/公证不以开发候选替代。
- P05/N09：Intel/amd64 与其他 OS 的真实硬件/GUI 测试和独立审阅仍缺，故不能关闭总体目标。旧候选证据仅供诊断和追溯，不自动升格到本候选。

当前候选的构建与代码验证见 [verification.json](verification.json)。
