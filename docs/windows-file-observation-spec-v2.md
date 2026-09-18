# Windows 文件观察 V2（2026-09-18）

本增量接续 Windows 显式资源解释及 N01 reader/writer 3 屏障，不增加执行权限。旧 POSIX CaptureFile、snapshot、observation、pending/v1、record/v1 的签名字节与摘要不变。Windows 使用 file-snapshot/v2、file-observation/v2、file-observation-pending/v2 和 effect-evidence-record/v2；顶层 effect-evidence/v1 仍以 evidence_digest 绑定完整新版观察材料，旧资源引用和 action ID 公式不变。

begin/finish/recover 均从引擎已验证 action 的 Intent ID/digest 查询原签名 Intent，再核对当前相同会话绑定、有效期、撤销及精确 Grant。Windows 必须恢复 windows-local-drive/v1，并重新核对已批准 Grant 的现场文件绑定；不能由请求、GOOS、平台名称或路径形状选择解释。新版 pending 另签入原 Intent ID/digest，恢复不能移换 Authority。旧无 Intent 的兼容观察仍只使用 POSIX。

Windows capture 先以 runtimepath 检查完整目标与父目录，拒绝非固定 NTFS、别名、大小写错误、reparse/junction、多硬链接等无法验证资源。允许最后一层不存在；不读目录。已有文件只限量读取，比较打开前后文件身份、大小、时间及路径指向，再次复验 runtimepath。只持久化资源引用、内容摘要、存在性、大小/时间、目标身份摘要及父目录身份摘要，不保存路径、内容或原始卷/文件标识。

begin、结束和恢复须保持相同父目录身份。正常写入可以创建、删除或替换叶文件；这不允许替换已签 Grant 的授权边界，授权边界仍须实时复验。文件变化仅证明观察到变化，可能来自其他同用户进程，coverage 保持 partial；不声明 OS 沙箱、消除 TOCTOU 或 exactly-once。相同内容/时间且相同对象不能凭模型成功声明完成。

Windows recover 使用 file-observation-recovery-request/v2，新增必需 schema_version 和 path；原 v1 请求不变。路径只作为瞬时待验证输入，必须匹配原资源引用并复验父目录/目标事实，不持久化。恢复时不覆盖原 before 快照，不重新执行工具。已有恢复记录仍用 recovery/v1：其 pending_digest 已绑定完整新版 pending，不改变历史签名字节。

所有新增持久状态在完整 RequireWindowsProfile 成功后才能写入；无效版本、跨 profile、旧对象夹带新版空/null 字段、缺失/多余身份、当前 Authority 撤销/过期或替换均拒绝。完成记录可继续作为历史证据读取，但不因此允许追加新的观察。验证在功能接通后集中执行：旧签名固定向量、Windows 创建/原位更新/叶替换、父替换/别名/多链接拒绝、同action/digest/绑定和撤销、恢复及新旧合同样例。
