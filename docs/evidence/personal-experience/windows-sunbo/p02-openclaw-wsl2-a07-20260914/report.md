# A07：A 失败，诊断采集完成

两次 provider 请求均携带 read/write；一次真实 write 失败并回传 ERR_ACCESS_DENIED，目标不存在。 A=false、diagnostic_completed=true 与 terminal_stack_marker_observed=false 分别记录；诊断完成没有覆盖 A 失败。

A07 仅在新身份中显式设置 tools.exec.applyPatch.enabled=false，并追加四项来源 pin；预建 imports、原 guard/driver、Node 权限、provider 谓词、A/诊断与超时语义保持。关闭附加工具是能力收紧，没有扩大 provider 的允许集合；原谓词仍是 write 必需、集合属于 {read, write}，read 可选。

第一次固定 write 响应已经发出。第二次请求包含对应 assistant write 和 role=tool 错误回执；调用目标与 plan 一致，固定内容摘要一致。Node stdout 的 toolSummary 为 calls=1、tools=[write]、failures=1，successfulToolNames 为空。目标在前后及两次请求时均不存在。native_tool_exchange_observed=false 是冻结成功消费谓词未达，不是否认已观察到的真实失败工具调用。

Node stdout 的 meta.error.message 实际含本地 400、HTML 和 Synthetic fixture rejected request；这是 request 2 因效果未落盘而触发的本地拒绝，与 A06 仅能从源码确定 400 的证据不同。未把它包装成云端/CDN 故障。

真实工具错误含 filesystem write failed 与 ERR_ACCESS_DENIED。本次没有 terminal stack 标记、底层 fs stack、permission 或 resource。运行后有限源码复核显示相关包装构造仍传入 cause/details；这不证明这些对象最终包含什么，也不证明外围序列化保留了哪些字段。具体被拒 API/权限/资源继续记为未知，不从目标路径或 A05 帧倒推根因，不扩大权限。

Node 约 5.027 秒、namespace 约 5.790 秒，Windows 传输约 6.527 秒；三个进程层及 Windows 外层实际均保留 exit 1。Node/namespace 已 wait/reap，provider socket/thread 与 decision socket 明确完成收尾；Windows stdin/传输完整且 wait/dispose，均无 timeout/kill。Linux cleanup 来自精确 guest 布尔，不由 Windows 退出码推断。

新 state 下 imports 的独占 mkdir(mode=0700) 与创建时为空由冻结计划/代码描述，before/after 记录的元数据及子条目计数列于摘要。快照没有 directory/regular 类型字段，不能仅凭 4096 字节或 symlink=false 声称收尾仍是普通目录；本批没有把数据库搬入 imports。

17 个冻结输入 bytes/SHA 一致；19 项安装源码 pins 与 guest 收尾摘要相符，Node/unshare 另列。这是两个不同清单；只核对已保留记录，没有重新运行 WSL 或宣称完整依赖审计。control、namespace 哨兵、父 namespace/tmp 及 Windows 私有根 ACL 记录保持。

盘点、WSL 主传输、namespace、Node 共八条原始流只公开长度/SHA。WSL 主 stderr 为 132 字节、driver 的 UTF-8 replacement/decode_error 保留，不等于 Node stderr。namespace/Node 的内嵌原始字节及独立提取文件已核对；runtime StringIO 不冒充额外进程原始流。

来源背景为干净 fd2cdba7c9d5111bc5fd475651fb6453d5b45d15，其相对 b303c6f92392f3a44c306d81ad7323c6291ef4f2 仅有 A05 文档交付。SIQ/真实模型/Gateway 均未运行，B 未运行。这仍是 WSL2/Linux 失败正对照，不是 Windows 原生宿主或完整平台验收通过；旧失败、18 行矩阵和分母不变，未修改产品 runtime。

详见 [摘要](summary.json)和[来源索引](raw-source-index.json)。本公开包没有原日志、环境明文、PID/UUID、工具调用 ID、请求或提示正文；归档验证由主任务另行完成。
