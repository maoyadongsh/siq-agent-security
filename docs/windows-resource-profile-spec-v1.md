# Windows 本地盘符资源解释（#39，候选规格）

本规格始于 2026-09-16 Windows 修复候选，2026-09-18 接续原生文件事实层，未声明宿主验收完成。继承本地规格的 Authority、Grant、回执、N01 状态边界。合同、词法和事实层分步验证；在明确批准链和跨层一致性接通前，不在生产裁决中选择新解释。

## 显式签名与兼容

`intent/v2`、`intent/v3`、旧 Grant、`local-runtime-identity/v1` 和既有会话仍保持原 POSIX 解释、签名字节和摘要公式。filesystem regex `.*` 的旧签名不能得到 Windows 权限；`//server/share` 在旧 POSIX 解释下仍是 POSIX 路径。不得根据 GOOS、请求参数形状、模型上下文或 `platform=hermes` 自动改解释。

新增 `intent/v4` 固定 `authority_kind=instance_permission`，并签入 `filesystem_profile=windows-local-drive/v1`，仅为用户明确确认的新 managed 实例权限包络。它继承 v2 的工具/效果/参数/Grant 边界，不宣称任务目的或来源已验证；不接受 provenance_constraints/effect_requirements，也不从 v3 自动降级。v3 provenance 和必需效果证据检查原样保留。普通 Intent HTTP 创建入口不得凭自报 issuer 创建此包络。

新增 `grant/v2` wire 身份及 `grant.v2.schema.json`，明确签入 filesystem_profile。新字段只进入新的授权，不向旧 Grant 注入默认值。权限摘要使用 `grant-permissions/v2` 域；旧摘要公式不变。新 identity 只能绑定已经明确批准、版本/摘要匹配的新 Grant。

2026-09-18 Grant 接续：新版另必需签入 `filesystem_bindings`，为每个非通配 filesystem fact ID 到现场身份 SHA-256 的完整映射；没有 filesystem fact 时是空对象。摘要前像为 canonical JSON 数组 `["windows-resource-identity/v1", canonical_path, native_device, exists, objects]`，objects 从卷根到目标逐级按 `[volume_serial, file_index_high, file_index_low, creation_time_high, creation_time_low, is_directory]` 排列。只有实际存在并完整核验的普通目录/文件可作授权边界；`*` 仅可作为 deny，保留而不进行文件身份绑定。未知操作、别名、缺失路径、重复 fact ID 或缺少/多余绑定拒绝。绑定本身不证明权限已批准。

仅针对已验签的 pending_approval managed baseline（Hermes/OpenClaw agent_instance）生成新版待批准资源草稿，必须显式确认新解释。旧签名 Grant 不原地升级；返回新修订待批准对象，原对象字节保持。原有 deny、审批条件、期限和场景边界保留，无法解释的旧路径限制拒绝转换，不能悄悄删除。pending 资源编辑重新生成精确事实绑定并改变权限摘要，使旧挑战失效。Approve 必须验签并重新核对所有绑定；批准后文件范围不可自动重绑定。拒绝/撤销仍可在目标消失后执行，不能因文件缺失阻止撤权。

新字段在旧 Grant 中必须完全省略，旧签名向量及 grant-permissions/v1 摘要逐字节不变。新版 Verify 校验版本/绑定结构后验签；历史读回不依赖资源仍存在，现场核验是批准/行使权限时的独立步骤。任何新版本 Grant 持久化前必须有明确旧消费者读写屏障；当前默认 reader/writer 2 状态不得写入新 Grant。先完成该屏障与身份/裁决全链，再开放 HTTP/CLI 新版创建入口。

`grant-permissions/v2` 的摘要前像为完整新 Grant 的 canonical JSON 投影：仅删除顶层 status、effective_readback、signature、signing_schema；facts 中 tool 的 declared/effective 状态统一为 runtime_eligible，其他域删除 state；所有 facts 删除 authority、authority_revision、readback_evidence_id；保留其余字段，特别是 schema_version 与 filesystem_profile，再加入 digest_schema=`grant-permissions/v2`，最后计算 SHA-256。该投影复用旧 v1 的排除规则，但域标记和新增签名字段显式属于 v2；旧 v1 前像和摘要完全不变。新 Grant Schema 只检查外形，路径合法性、profile语义、allow/deny与实际文件身份必须在签发层及裁决层分别验证，不能以 Schema pass 代替。

新增 `local-runtime-identity/v2`、create/v2、issued/v2；签名记录/返回视图含 filesystem_profile，其 grant_ref 明确 `permission_digest_schema=grant-permissions/v2`。create/v2 要求 `confirm_filesystem_profile=true`，但不接收可由请求自选的 profile 值；服务从已验签新 Grant 与可信实例来源派生，确认只表示用户明确接受展示的范围。当前首片仅支持 Windows 本地盘符解释。旧 identity/session 不升级；新版本恢复中断时复验完整同一解释、Grant/会话绑定和期限。

新包络、Grant、identity 的 schema 和 profile 均属于签名内容。签发前必须阻止旧消费者误读新记录，按 N01 检查和写入边界处理；不能仅添加字段并假定旧 Go 解析器会拒绝。首片不创建任何此类持久状态。

## 确定性词法入口

`runtimeaction.NormalizeResourceForProfile(profile, domain, value)` 和 `DescribeForProfile(profile, tool, params)` 仅接受显式 `posix/v1` 或 `windows-local-drive/v1`。缺省、未知 profile 失败，不回退。旧 NormalizeResource 和 Describe 仍使用旧算法。非 filesystem 域复用现有 network/message 解释。

Windows 首版规则：

- 只接受 ASCII 盘符加冒号加斜杠/反斜杠的绝对路径；仅盘符大写、分隔符转 `/`。不得补全 cwd、当前盘、环境变量或用户 home。
- 允许合法 UTF-8、中文和内部空格，保留组件大小写与 Unicode 序列。不 trim、case-fold、NFC/NFKC。
- 普通 Win32 子集：完整路径最多 259 个 UTF-16 code units，每组件最多 255；长路径及扩展命名空间不支持，不依赖系统 longPaths 开关。
- 盘符根 `C:/` 合法；其他路径不接受尾分隔符、空组件、`.`、`..`、重复分隔符。先检查原始组件，不能 clean 后接受非法尾点或尾 ASCII 空格。
- 拒绝 NUL/控制字符、`<>:"|?*`、除盘符外的冒号（ADS）、设备保留基名及扩展形式（含 COM/LPT ¹²³）、UNC/扩展 UNC/设备/GLOBALROOT/Volume GUID 命名空间。
- 多个 path/file_path 字段必须全部合法；错误时不产生 partial refs。等价分隔符/盘符拼写可归一为同一资源，但原始 params_digest 不因此相等。
- 新 Windows 描述器在 ResourceError 时清空 legacy Paths hints，裁决链必须直接拒绝，不能使用旧提示路径降级匹配。旧 Describe 的 POSIX hints 行为保持不变。

词法结果不是文件身份结论，不访问文件系统，不证明路径在本地卷、大小写实际拼写、8.3/SUBST/映射盘、reparse/junction/hardlink 或检查后替换安全。当前 b303 fileopen 的 Windows fallback 只是 os.Open，不能当作已实现的事实层。

## 后续生产接通门槛

### Windows 文件事实层（2026-09-18，#39 接续）

`internal/runtimepath.InspectWindows` 只检查显式选择新 profile 后的本地资源，不改变旧路径解释，也不单独授予权限。先调用既有 Windows 词法检查，再从盘符根逐组件打开带 READ_DATA（目录为 LIST_DIRECTORY）及 READ_ATTRIBUTES 权限的只读句柄，保留所有父句柄直到本次检查结束；不共享 DELETE，阻止检查期间对已打开组件改名；仅属性句柄不具备此共享检查语义，不能替代。句柄不读取内容，缺少读取/列目录权限或共享冲突时拒绝，不退回弱检查。所有失败只返回固定类别，不输出路径或 Win32 参数。

本次支持普通本地固定 NTFS 卷。盘符必须由 QueryDosDevice 读回为直接 HarddiskVolume 映射，GetDriveType 必须为 fixed；每个句柄的最终 DOS/NT 路径分别与规范长拼写和该设备映射一致。拒绝 SUBST、映射盘、8.3/大小写别名、reparse/junction、非磁盘对象、待删除对象及多硬链接文件。每个父目录必须支持 FileCaseSensitiveInfo 且标志为零；未知或启用大小写敏感时拒绝，不修改目录属性。现阶段此子集不代表 Windows 全文件系统支持。

只允许最后一个叶子不存在，且由调用方明确传入允许新叶子；所有父目录必须实际存在。事实保留盘符映射、每级卷序列号/文件索引/创建时间/目录类型及叶子存在性。返回值只在内存保存，内部字段不导出，不作为可由调用方伪造的签名事实。Revalidate 重新打开整条路径并逐级比较，父目录/目标替换、原缺失叶子出现、硬链接数变化及映射变化均拒绝；内容摘要不属于本层，读取内容和效果证据仍走各自合同。

检查不创建资源、不更改 ACL、不设置系统或会话盘符映射、不执行文件，也不改变签名或状态格式。新 API 仍须接通 Grant/Intent/identity 的明确批准及最终调用参数链后才能启用。检查结束关闭句柄，无法消除宿主执行前的同 UID TOCTOU，不宣称 OS 沙箱；审批恢复必须重新检查，不能缓存一次结果永久放行。

限定标准库 Windows API 例外仅在该包 `_windows.go` 使用 syscall/unsafe 查询句柄、卷、盘符和目录属性。其他平台返回未验证错误，不用词法成功替代原生事实。测试只在临时目录创建普通文件、硬链接及 junction，恢复测试资源；不要求提权或修改全局盘符。未具备条件的原生场景如实记 skip。

参考 Microsoft [最终句柄路径](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)、[DOS 设备映射](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-querydosdevicew)、[句柄信息类型](https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ne-minwinbase-file_info_by_handle_class)、[卷信息](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getvolumeinformationbyhandlew)，2026-09-18 核对。

新 profile 的 Intent matcher、Grant read/write/deny 匹配、runtimeaction 描述、hold/final params、action/receipt、file observer 必须统一从已验证 Authority 恢复解释。范围先精确相等，或以 `/` 为组件边界的 prefix；只允许 equals/one_of/prefix，filesystem regex/suffix 不开放。allow/deny 使用同一大小写与文件身份规则，未知别名拒绝。

Windows 事实层需在真实操作前验证所有已有父组件/授权边界和已有目标：普通本地卷、非 reparse/junction、实际规范拼写、目录大小写属性、单链接对象等受支持条件。新叶子需绑定已核父目录及不存在状态。无法证明时拒绝；同 UID 和 hook 检查仍不是 OS 沙箱，无法排除的 TOCTOU 必须明示。不得复制状态目录路径规则来冒充宿主资源规则。

新版 canonical资源仍以已签 Intent 绑定 authority，旧 ResourceRefs/ActionID 公式不改。若后续需要将 profile 加进摘要前像，须另行升版相应 action/ref/receipt，而非改已有向量。

现有 W01–W16 分层验证：W01–09 词法；W10 Grant 目录边界；W11 词法不合并大小写 + Windows 事实层；W12 多字段提取；W13 旧签名回归 + 新授权操作符约束；W14 跨 profile 与旧网络/消息；W15 原始参数/调用身份 + 审批最终复验；W16 实际 reparse/别名/替换。不得将纯词法通过写成后续层通过。

完成四目标构建、合同/兼容、Windows事实层和 managed 链测试后，固定新候选执行 Hermes B01 允许、B02 越权零副作用、B03 失联、B04 恢复、B05 撤销。当前安装 Hermes 有后续 modify/approve 钩子，审批恢复及最终参数复验需独立证据，不因 B01–B05 自动通过。

本子集参考 Microsoft 的 [命名规则与命名空间](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)和[路径长度限制](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation)（2026-09-16 查询）。上述拒绝导航、UNC、长路径和未知身份是本产品较窄的合同选择，不能解释为所有此类路径在 Windows 本身非法。
