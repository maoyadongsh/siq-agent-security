# N01 状态协议与迁移实施规格

本文件补充 dev-spec §2.3.1；替代该节“本增量不实现迁移”的历史范围，历史审查证据仍保留。

## 协议

旧 `state-format/v1` 格式 1 和经现有有界识别的无标记格式族保留支持。新 `state-format/v2` 格式 2 添加 `min_reader`、`min_writer`、`state_directory_id`、`instance_id`，本实现 reader/writer 协议版本为 2。版本为正整数；reader <= writer，最低版本不得超过本程序；状态目录摘要算法复用 local-state-directory/v1，实例与 local-instance.json 严格匹配。schema/字段/重复键/尾随 JSON/预算验证必须在读写前发生。程序版本只是信息。标记不构成同 UID 安全隔离或签名授权。

全新 init 建立实例后发布 v2。既有 v1 不自动升级；既有无标记实例 init 最多增加旧 v1 元数据。显式 `state-migrate --confirm` 将已初始化 v1/可识别无标记目录转换为 v2。本转换真实改变目录协议及旧程序读写准入，业务格式未改变，所有业务对象逐字节保留。没有支持的转换器时拒绝，不把任意版本改标记当迁移。

## 独立文件访问边界

为避免 state → receipt/signing → state 循环，严格标记解析放在仅标准库的 internal/stateformat，业务文件读写使用 internal/statefs 标准库兼容封装，在发现状态根标记或迁移屏障后先校验读/写版本。上层 state 继续负责无标记目录识别。根路径显式传入或从文件路径祖先发现标记；每层都检查，嵌套 Skill/备份中的标记不得遮蔽外层不兼容状态，不按业务目录名猜根。wrapper 不为未知目录制造身份，也不接管状态目录以外的业务授权。

例外：stateformat 读取标记；迁移引擎在持锁和校验计划后写自己的计划、备份、提交点、兼容标记；writer 只负责经预检的新锁及按 owner 释放自己持有的锁。例外必须列入覆盖清单。读取未知旧结构仍由各业务对象格式检查负责。此机制是合作程序的兼容保护，不抵抗任意同 UID 删除标记或持有旧文件描述符的恶意进程。

## 迁移事务

迁移先持主 Writer 与所有维护 Writer（非阻塞获取，失败释放；不停止服务），验证实例/源标记及完整目录清单，之后发布 `logs/migration-plan.json` 作为读写屏障。路径固定、计划不可变，不接受调用方路径或步骤。旧 v1 防护二进制也识别该屏障。计划绑定源标记摘要、实例、目录、目标标记及备份清单。

清单递归包括真实目录、普通文件、权限及 SHA256；包含嵌套授权/撤销、回执、身份/密钥、配置及现有备份。排除精确的运行锁及本迁移管理目录，不跟随符号链接，不接受特殊文件；条目/单文件/总字节均设预算，超限在屏障前拒绝。备份为状态内私有目录，保留原权限但不放宽访问。备份条目逐一排他发布，可验证后重入；每个阶段完成点都是绑定计划摘要的不可变文件。

提交前复验原始文件清单及完整备份，原子发布 v2 标记，归档计划到 state-migration-v2/plan.json，最后发布完成点并移除已验证的活动屏障。活动屏障清理中断可重入；已完成迁移后新业务写入不会被当成旧快照漂移，也不会被回滚。崩溃后所有普通入口拒绝，只有相同 `state-migrate --confirm` 可持锁恢复。若文件漂移、备份损坏、计划被改、实例变化或未知目标，保留现场拒绝。迁移不恢复业务旧快照，不重新签历史数据，不复活已撤销/过期授权。备份供核验和灾难恢复，禁止把旧备份直接覆盖仍在使用的新状态以冒充安全回退。

Linux 对文件和相关目录 Sync；Windows 只声明可验证的进程崩溃恢复，断电耐久性等待实机证据。自动迁移仅执行已实现的 v1/无标记 → v2 这一个转换。

Windows 重入增量（2026-09-18）：迁移 checkpoint/暂存输出的既存文件仍须逐字节一致且为普通文件。POSIX 平台继续精确比较权限位；Windows 按 Go Chmod 实际支持的 owner-write 位比较只读属性，不将请求的 0600 与 Windows Stat 返回的 0666 误判为内容漂移，也不忽略只读属性变化。备份清单继续保存并比对实际观测的完整 Mode，不改写旧计划或历史文件。本检查不证明 DACL 私密；Windows 私密主体、继承及安全创建由 ACL 验收独立约束，不能以此关闭 ACL 缺陷。

Windows 只读备份发布的暂存清理不能使用会清除只读属性的 os.Remove 回退，因为暂存与最终对象是同一硬链接文件。仅对本次创建、已记录文件身份的暂存对象，重新打开 DELETE + FILE_READ_ATTRIBUTES 句柄并比对身份，以 FileDispositionInfoEx 的 DELETE | IGNORE_READONLY_ATTRIBUTE 删除精确暂存链接；不清除文件属性、不改已发布备份、不删除替换对象。API 不支持、身份变化或清理失败返回错误并保留可恢复现场，不回退清除只读位。该 API 使用属于 Windows 平台文件操作例外，依然仅标准库、仅状态目录内的本次私有暂存对象。

Windows 私密读取采用单链接约束后，迁移发布不能继续暴露“os.Link 已完成、暂存链接尚未清理”的双链接窗口，否则进程中断会令下一次恢复拒绝已发布输出。Windows 迁移改为对已写完并 Sync/Close 的私密暂存文件重新获取不共享的 READ + DELETE 句柄，检查普通单链接、DACL 和创建时文件身份，再以同卷 FileRenameInfo、ReplaceIfExists=false 原子发布到目标；保留私密 ACL 和只读属性，不覆盖目标，不回退 copy、清只读位或先删除目标。成功后源暂存名已不存在，不再次清理；失败只可清理本次创建且身份匹配的暂存，未知对象保持不变。非 Windows 保留排他硬链接发布。内部测试在发布前及发布后提供仅测试可设置的故障点，以真实隔离子进程终止证明重入；故障点不是环境变量、配置或 CLI 功能。

发布前进程中断留下的未知暂存不自动删除，新尝试使用新名字；发布后应只有完整目标一个链接。旧候选留下、无法证明归属的额外硬链接继续拒绝并保留现场，不能仅按暂存前缀删除。这种旧损坏/别名状态不冒充本次新发布流程的可恢复证据。

## 发行与用户恢复

候选签名清单升为 manifest v3，新增必需 state_compatibility 读/写支持声明；保留 v1/v2 读取，旧清单只对应旧无标记/v1 族；v2 状态的升级和回退必须存在并匹配声明，在 staging/恢复二进制/停止服务前预检，并在执行切换前再次检查。不得执行未知候选程序探测能力。实际受支持旧 v1 防护二进制必须对 v2 状态零写入拒绝；未实现检查的历史二进制明确不纳入直接运行保障。

提供 `state-status` 只读诊断和稳定恢复提示：不支持时使用匹配版本；中断迁移用相同命令恢复；损坏时保留目录，依据备份清单核验后人工恢复；不建议删除状态、重初始化或回放旧批准。UI 对 state_incompatible 显示同样可执行指引，不直接展示私有路径。

Windows 原生补验发现的诊断增量（2026-09-14）：`state-status` 同时检查所选目录和全部祖先的兼容标记/迁移屏障。内层实例兼容而外层要求未来版本时，返回 `compatible=false` 与 `status=future`；外层标记损坏时返回 `status=corrupt`，保持只读与路径脱敏。成功输出诊断的退出码仍为 0，不改变既有读写拒绝或迁移合同。

macOS 原生补验发现的祖先检查增量（2026-09-15）：Darwin 的 `/var`、`/tmp` 是指向 `/private/...` 的卷别名。2026-09-17 复核收窄：`stateformat.AcceptDirectory` 仅在 Darwin 接受 `/var`、`/tmp`、`/etc`，其 Readlink 解析目标须分别为 `/private/var`、`/private/tmp`、`/private/etc` 且目标本身为真实目录；其他 OS 或根级链接不豁免。`LeafDirectory` 始终拒绝叶节点符号链接；状态根本身与用户在中间路径创建的符号链接仍拒绝，标记文件仍拒绝符号链接。未区分卷别名时，空的 `t.TempDir` / `TMPDIR` 状态会被标为 `corrupt`，`init`/`serve`、Runtime Identity 目录、Skill 导入/安装祖先检查和 `--state-dir` 字符串规范比较都会失败。同一祖先规则适用于 inventory 发现、adapter 配置镜像读取，以及 Hermes profile 根（含 HOME 之外的 Override）；被检查的叶路径仍拒绝符号链接。DirectoryID 仍绑定规范路径。


## 实现预算与恢复范围

迁移最多 10,000 条目、单文件 128 MiB、总文件内容 2 GiB；超限需另行扩展并验收，不能静默跳过。备份记录普通文件内容与 POSIX 权限，拒绝 symlink、特殊文件及 setuid/setgid/sticky 位；不宣称复制 OS ACL/xattr 或提供任意目录重定位。私有 journal/backup/tmp 必须限制访问，未发布 scratch 位于 journal/tmp，重启保留它们，不凭文件名前缀删除未知数据。

只有完整备份完成点及精确的 prepared target 都匹配计划时，才允许恢复失败 rename 后缺失的兼容标记；更早阶段缺失源标记仍拒绝。普通业务文件从不参与此替换例外。用户恢复必须使用原实例和原目录；无法证明身份/原数据/备份完整性时保留现场，不自动回放旧授权。

## Windows 资源解释显式启用事务（reader/writer 3，2026-09-18）

Windows Grant v2 / Runtime Identity v2 / Intent v4 必须在旧消费者拒绝的状态中发布。状态外形仍为 state-format/v2、format_version=2，显式启用将 min_reader/min_writer 从2提升到3；不重签或升级既有业务对象。全新初始化仍为2，不自动改变旧实例。完整新版授权消费链开放前，新版 Grant 的临时拒写门禁保留。

启用只接受已初始化且常规 v1→v2 迁移已收尾的 Windows 本机状态，明确 confirm，持主 Writer 与 service-control/adapter-write/client-releases/client-snapshots 全部维护 Writer。v1、未知格式、活跃旧迁移或非本机平台拒绝，不自动停服务、不提权。

新增 state-windows-profile-plan/v1：filesystem_profile 固定 windows-local-drive/v1，source_marker 与 target_marker 保存两个标记的原始 JSON 字符串，migration_history_sha256 记录既有归档迁移的关联摘要，无历史为 absent。目标必须保留目录/实例身份，只提升兼容版本并更新信息性版本/时间；原 min_reader/min_writer 必须均为2，目标均为3。所有外层键严格且计划采用 Go JSON 紧凑编码加LF；两个内层标记按现有严格解析。预算16KiB，单标记不超过4096字节。合同 Schema 只检验外形，实施复验绑定、版本、历史与现场。

历史摘要为 SHA256(UTF8("state-windows-profile-history/v1\0" + sha256(旧归档plan原始字节) + "\0" + sha256(旧done原始字节)))。旧done的计划摘要与标记摘要必须分别匹配旧plan和本次source_marker，旧plan target/目录/实例必须相符。旧归档plan/done及备份保持不变；这项关联不宣称重新验证了整个备份内容。

先以旧程序已经识别的 logs/migration-plan.json 发布新schema活动屏障，旧程序对该schema拒绝。新私密目录 state-windows-profile-v1 保存不可变plan.json、prepared.json与done.json；暂存只在其tmp内，排他发布复用现有Windows单链接原语。prepared绑定计划摘要，并在标记切换前发布精确target.json。仅允许替换本次验证过的兼容标记，不恢复任何业务快照。

目标标记发布并读回复验后，追加state-windows-profile-done/v1（plan_sha256、marker_sha256），复验完整链后移除精确活动屏障。完成后旧reader/writer2因最低版本3拒绝；新读取器必须验证归档计划、完成记录、目标标记及旧迁移关联，不能只信一个版本数字。已有对象的副作用与权限状态保持原样。

任意中断后只可由同一显式启用事务持锁恢复；计划漂移、源标记替换、旧迁移历史变化、未知输出或权限异常均保留现场拒绝。标记缺失只在prepared与精确target暂存都匹配计划时可恢复；更早阶段不补造。done以后重试不比较过时业务快照、不回滚新业务写入。拒绝或未确认时不产生事务材料。测试覆盖逐阶段故障和真实隔离进程退出，Windows不据此宣称断电耐久性。

显式入口为 `state-enable-windows-resources --confirm`；无确认/多余参数在访问状态前拒绝。`state-status` 对中断启用给出此恢复命令，损坏记录保持拒绝。命令返回 local-state-windows-profile-result/v1，仅表示兼容元数据 activated/up_to_date，不表示批准或启用某个宿主。发行清单的 reader/writer 声明随实现提升到3，已有清单不改写；旧最低版本2制品对升级状态的发行预检拒绝。
