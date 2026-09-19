# Windows Hermes 自检失败、恢复与快照修复证据

2026-09-18。本包结论为 **真实产品旅程失败、快照修复组件通过、正式 CLI 清理通过**。没有把任何结果计入 303 行宿主验收，也没有证明新候选原生自检通过。

## 真实候选与两次失败

两批均使用干净提交 `13129e1e6e68c9632b127a4182d7739ae4508579`，Windows 二进制 SHA256 为 `95bffe15d2957ccb97942a1d61a1ad4c3c8f9a857104d25cdae3d100d56d67b3`。构建 exit 0（16.392 秒），构建记录确认源码执行前后均干净；本次真实失败不是 b877 修复后的实跑。

| 批次 | 控制器结果 | 实际到达阶段 | 结论 |
| --- | --- | --- | --- |
| r1 | exit 1，32.207 秒 | 原生安装预览 HTTP 400；尚未安装 | 合成配置含冗余 `secrets: {}`，Hermes 保存时移除空节点，SIQ 无关配置变化保护拒绝预览。 |
| r2 | exit 1，59.048 秒 | 安装预览 200、安装 200、自检预览 500 | 自检快照返回 `runtime_check_snapshot_failed`，尚未 start/chat/模型调用。 |

r1 的独立元数据复现只在新私有副本执行 `config get → plugins enable → config get`，三条命令均 exit 0。按产品原有比较规则去掉本产品注册字段后，唯一差异是空 `secrets` 根被删除；双主 fallback 与 18 个 aux 路由未变。r2 仅省略该冗余空节点，保留其余合成路由条件和全部保护。这是夹具规范化修正，不能宣称一般 profile 兼容问题已完成。

r2 自检预览的真实产品缺陷位于 `adapterinstall/runtime_target.go`：Windows 专属字段把命名类型 `FilesystemProfile` 放入 `map[string]any` 后直接交给 `canon.Marshal`；规范化器仅接受原生 JSON 字符串类型。管理层 `runtimecheck.digest` 会先经 JSON round-trip，故问题在实际目标 inspector，而非模型配置解析。

两批控制器均保留失败报告并关闭自有 Job；观察到的子进程均已终止。两批没有 `/v1/runtime-checks/start` 请求，没有自检 journal，也没有 product-runtime-check 阶段进程。原生元数据 CLI 的运行不能被误记为模型自检运行。

## r2 正式 CLI 恢复

r2 的 HTTP 卸载预览发生 `RemoteDisconnected`，没有完成的 HTTP 响应状态；控制器留下 `installed=true` 并保存剩余清理说明后退出。此原始失败未改写为成功，也不能由后来 CLI 成功推断 HTTP 卸载已修复。

随后使用原 clean131 二进制、只针对该隔离实例执行正式 CLI 的卸载预览、应用和状态查询：exit code 分别为 0、0、0，用时 22.440、24.369、0.821 秒。三次自有 Job 均关闭且关闭前活动进程为 0。保留的只读清理核验确认：原报告和原始备份未改；SIQ 原生启用与工具覆盖注册恢复；无关配置语义保留；三个自有插件文件移除；状态为 `not installed`。允许的格式规范化仅 `_config_version` 和空 `plugins.entries`。本次打包再次只读核对三个插件文件缺席；不重新调用宿主。

## 已提交快照修复的组件证据

修复提交 `b8779b8ede94729c13c8056a13d3c1e99255e162` 只增加 `string(profile)` 转换及专属 Windows 回归测试，不扩展 canon，不改变签名或合同含义。

同一 `TestWindowsRuntimeTargetCanonicalProfile` 在旧生产代码上 exit 1：实际 Windows 状态完成初始化并明确激活 profile 后，直接 `InspectRuntimeTarget` 返回 `runtime_check_snapshot_failed`。一行修复后 exit 0（测试 4.20 秒，包 6.064 秒），快照与独立构造的 JSON 字符串规范摘要一致；未激活状态、配置漂移、CLI 漂移仍拒绝。程序文件及原生安装记录是合成元数据，状态目录、Windows 文件身份及 inspector 是实际组件入口；没有启动宿主、安装事务、服务或模型，也没有替换 Snapshot 回调。

前两次夹具准备因为先写入 legacy backup 再初始化状态而未获得 fresh v2 状态，停在 profile 激活门禁。这两次 exit 1 仍保留，排除于产品缺陷复现。修正初始化顺序后才取得上面的旧行为失败证据。

组件运行在修复提交前的开发树。生产文件 SHA 与 b877 完全一致；提交仅进一步澄清测试注释。已按 Git blob 核对：将提交中的注释还原后，测试文件 SHA 恢复到组件运行时记录。两份身份均列在 `verification.json`，没有伪称该组件命令来自提交后的干净制品。

## 材料与边界

- `verification.json`：白名单结构化摘要，含真实候选、二进制、控制器、计划、源码摘要、退出码及分层结论。
- `source-manifest.json`：仅选定非秘密原始证据的 SHA256 与长度；以来源编号关联，不公开本机路径或原文。
- `SHA256SUMS`：本包三个文件的完整性校验。

本包不复制私有报告、配置、账号路径、进程 ID、环境或凭据；密钥文件未读取、未计算摘要。后续 HTTP 预算修复、新候选重建和新的真实自检结果均不属于本包，不能覆盖这里的失败结论。
