# macOS Luke：公开宿主 CLI 失联 fail-closed 补证

在既有干净产品候选 `450fe1836d8a3bffefbd2ce9b6f02bbbfe730c64`、Mach-O arm64 CGO=0 二进制 SHA256 `f067f96b05c3472b8ebe2d43ac9c19ce79c5063af19ec1dc66999a6da1bd3e23` 上，隔离 profile、合成模型和无害工作区的**公开宿主入口**直接补测服务失联。OpenClaw 2026.9.4 使用 `agent --local`，Hermes 0.21.3 使用 `chat --oneshot`；两个测试均从已允许的只读调用进入，然后在下一笔原生写调用前杀掉仅测试用 SIQ daemon，验证宿主返回 fail-closed 且受控写目标不存在。daemon 在宿主 CLI 结束后才以同一私有状态重启，待处理拒绝恰好提升一次，回执链验证通过。

| 宿主 | 本次原生新证据 | 特别边界 |
| --- | --- | --- |
| [Hermes](evidence/hermes-offline-native.json) | 公开 CLI 7 项检查通过；允许读取、失联写阻断、待处理拒绝一次性提升；3 条签名回执。 | 合成模型/操作者，不是批准后原调用继续。 |
| [OpenClaw](evidence/openclaw-offline-native.json) | 公开 CLI 15 项检查通过；托管接入、允许读取、失联写阻断、待处理拒绝一次性提升；2 条签名回执。 | 故意终止 daemon 的时点下，模型收到先前允许读取的内容，但对应 PostToolUse 观察回执未落盘。仅有 `allow` 决策不能标成“观察到执行”或“结果已核验”；这不影响下一笔写的失联拒绝结论。 |

两份可复现 [Hermes 测试夹具](evidence/hermes-offline-harness.txt) 与 [OpenClaw 测试夹具](evidence/openclaw-offline-harness.txt) 均由本批私有 `.tmp` 脚本按 SHA256 固定，归档为非执行 `.txt`。它们使用真实公开宿主 CLI/插件生命周期，但模型为受控 HTTP fixture，不涉及日常宿主 profile 或付费调用；原始临时状态由夹具退出时清理。本批没有修改产品代码，所以不将旧二进制日志改填新候选。

按任务书 §8.2 以仓外私有根重建 [18 行矩阵](manifest.json)，7 个引用文件摘要通过；[结构校验](structure-report.json)退出 **0**，[原生全覆盖校验](native-report.json)仍退出 **3**。本机 arm64 直接原生通过数变为 OpenClaw **4/8**、Hermes **4/8**、WorkBuddy **5/8**。`service_unavailable_denial` 在两 CLI 行由 `blocked`/Hermes 旧 `component_fixture` 升为 `pass/native_cli`；批准继续、最终换参复核、可信 Skill 归属、原生安装前拦截仍未证明，不因本批失联测试顺带变绿。Intel/amd64 仍为用户取消的实机范围，合同保留 `not_run`。

限制与后续：本批没有真人审批、Skill 来源、OS 级隔离或发行签名证据；OpenClaw 的观察缺口需按“结果未知”呈现并可进一步诊断，但不可据此伪称实际写被允许。Mac-P03 真实重启后状态恢复另见 [P13](../p13-20260916-223833/report.md)。Mac-P00–P05/N09 整体仍未达到完整验收。
