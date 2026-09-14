# A06：A 失败，诊断采集完成

一次 provider 请求携带 apply_patch/read/write，触发原工具集合校验；固定 write 响应未下发，目标不存在。 A=false、diagnostic_completed=true 与 terminal_stack_marker_observed=true 分别记录；诊断完成没有覆盖 A 失败。

provider 的冻结谓词是 write 必需、工具集合须为 {read, write} 的子集，read 可选；它不是“必须恰好有两个工具”。额外 apply_patch 导致 request 1 的本地 `host exposed unexpected tool allowlist` 拒绝。请求无 role=tool，成功 provider-response 文件为 0，计划中的 write 尚未下发，不能用 namespace setup 合成写入冒充工具效果。

本地 HTTP 400 来自冻结 Handler 的 send_error(400) 分支。Node 原始 stdout/stderr 没有直接保留 400 或 fixture rejection 文字；错误响应正文也未单独存档。因此只能说明该代码路径，不能声称原始 Node 状态码读回。通用 FailoverError/CDN 提示不是实际云端或 CDN 故障证据。

Node 约 6.123 秒、namespace 约 7.188 秒，Windows 传输约 8.251 秒；三个进程层及 Windows 外层实际均保留 exit 1。Node/namespace 已 wait/reap，provider socket/thread 与 decision socket 明确完成收尾；Windows stdin/传输完整且 wait/dispose，均无 timeout/kill。Linux cleanup 来自精确 guest 布尔，不由 Windows 退出码推断。

新 state 下 imports 的独占 mkdir(mode=0700) 与创建时为空由冻结计划/代码描述，before/after 记录的元数据及子条目计数列于摘要。快照没有 directory/regular 类型字段，不能仅凭 4096 字节或 symlink=false 声称收尾仍是普通目录；本批没有把数据库搬入 imports。

15 个冻结输入 bytes/SHA 一致；15 项安装源码 pins 与 guest 收尾摘要相符，Node/unshare 另列。这是两个不同清单；只核对已保留记录，没有重新运行 WSL 或宣称完整依赖审计。control、namespace 哨兵、父 namespace/tmp 及 Windows 私有根 ACL 记录保持。

盘点、WSL 主传输、namespace、Node 共八条原始流只公开长度/SHA。WSL 主 stderr 为 132 字节、driver 的 UTF-8 replacement/decode_error 保留，不等于 Node stderr。namespace/Node 的内嵌原始字节及独立提取文件已核对；runtime StringIO 不冒充额外进程原始流。

来源背景为干净 fd2cdba7c9d5111bc5fd475651fb6453d5b45d15，其相对 b303c6f92392f3a44c306d81ad7323c6291ef4f2 仅有 A05 文档交付。SIQ/真实模型/Gateway 均未运行，B 未运行。这仍是 WSL2/Linux 失败正对照，不是 Windows 原生宿主或完整平台验收通过；旧失败、18 行矩阵和分母不变，未修改产品 runtime。

详见 [摘要](summary.json)和[来源索引](raw-source-index.json)。本公开包没有原日志、环境明文、PID/UUID、工具调用 ID、请求或提示正文；归档验证由主任务另行完成。
