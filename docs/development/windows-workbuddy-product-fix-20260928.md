# Windows WorkBuddy 产品修复实施记录

目标来源：用户提供的 `windows-workbuddy-product-fix-plan.md`（2026-09-28 接手）。本记录区分源码实现、Windows 组件验证和真实 WorkBuddy 验收；历史 0.4.0 制品、证据与签名不变。用户已授权安装开发工具、修复开发问题，以及完成后提交并推送远端开发分支。

基线：`main@4c978aff`；定位提交 `2cd61160849f50794c2dc632771a6e6ed6149eef` 与本基线的 `apps/agentshield`、`apps/web`、`packages/contracts` 无差异。工作分支 `codex/windows-workbuddy-product-fix`，接手时工作区干净。

| 工作项 | 实施与验证状态 |
| --- | --- |
| W1 共享只读预检与私有配置事务 | 已实现配置/父目录/凭据对象共享只读快照、细分对象原因；替换与恢复保留 owner/deny/保护位/ACE 继承位；Windows 组件回归已通过 |
| W2 状态格式/profile、精确迁移错误与恢复 | 已实现新装自动 profile、环境身份拒绝、旧装只读预览、精确目录与固定 EXE 绑定；保留原五个生命周期锁及单链接屏障；升级/中断测试已运行 |
| W3 接入/批准/部署/运行状态及读回 | 已实现 apply 后重新读实例诊断、Grant 部署修订读回、同步提交锁、未知/null/到期语义；前端最终 1015 测试和两种构建已通过，嵌入资源已更新 |
| W4 并发复现与调用级 pending 证据 | 旧锁复现 10 个不同目标调用仅 1 个进入裁决；增加有界等待；新 pending v2/receipt v2 保留原生/派生 ID、摘要、阶段、原始时间；另复现 Windows 锁删除/创建间隙的 Win32 5；改为复验拥有者后移走锁名再删除，10 轮快速竞争、15 轮独立/同目标多进程及 race 均通过。不能据此声称历史 J-02 根因已确认 |
| W5 工具覆盖与缺失资源说明 | 已补 unknown effect 与最小 Grant 测试；present_files/Glob/Grep 不冒充 Read、不默认放行；界面说明产物卡片/历史记忆边界及资源身份不可用 |
| W6 生命周期、只读 help、失联/到期诊断 | 已实现 start/stop 只读 help、267009 scheduler_running/health=unverified；身份被拒/服务不可达/登记截止分别记本地事件；原生 stop/start 与到期矩阵待执行 |
| 门禁、候选、原生任务矩阵、回滚操作卡 | Go vet、四目标构建和 Windows Task Scheduler 原生切换已通过；完整 Windows 模块仍有基线/平台失败，保留比较；正式签名与 WorkBuddy 新矩阵未完成，未标记产品完成 |


运行预检第一切片：安装预览、应用前、配置读回和实际 hook 共用私密对象检查。诊断只检查凭据对象的元数据；只有 hook 读取凭据内容。分别返回配置父目录、配置对象、凭据父目录、凭据对象及兼容屏障的稳定错误类别；对模型仍为简短 fail-closed 提示。目录 owner/DACL/链接/重解析策略保持不变，不自动修改宿主 ACL。已有不合格对象在任何安装写入前拒绝。

全量结束门槛仍为原任务书 W1–W6 和 Windows 原生矩阵。组件夹具成功不代表原生宿主、签名发行或业务 Grant 已批准。

## 已记录的验证

- 环境：原生 Windows 11 Home build 26200；官方 SHA256 核对的 Go 1.27.1 windows/amd64；Node/npm；Python 3.12。测试私密临时根只含本批合成数据，不修改真实状态 ACL。
- `go vet ./...`：退出 0（阶段性结果，最终冻结后重跑）。
- Linux amd64/arm64、Darwin arm64、Windows amd64 交叉构建：退出 0（阶段性结果）。
- `npm test -- --run` / `npm run build` / `npm run build:local`：退出 0；113 个文件、1015 个测试，保留原有 React/构建体积警告。
- 新 pending v2、独立 local_failure receipt v2、迁移预览 schema：Python 3 项测试退出 0；v1 不修改。
- `go test -p 1 -count=15 -timeout 5m ./cmd/agentshield -run '^TestWorkBuddyManagedConcurrentProcesses$'`：退出 0，30.384 秒。同目标无 Post 的 9 次后续调用仍拒绝 uncertain，不为通过率重放。
- 精确 EXE/目录绑定、新装/profile/旧身份准备、目录绑定诊断与 pending service-switch 拒绝的定向回归：cmd 3.094 秒、state 1.249 秒，退出 0。
- SDDL 创建语义、deny/继承标记、配置替换回滚、WorkBuddy 安装 ACL 漂移及恢复：最新定向检查退出 0（privatefs 0.700 秒、adapterinstall 2.228 秒）。Windows CREATE_NEW 会清除 AI 系统记录位；仅该位不参与等价比较，owner/P/AR/每个 ACE 均保留并检查。
- 完整 Windows `go test -p 2 -count=1 -timeout 10m ./...` 第二轮退出 1；保存全部失败。已修复本次 init 行为改变导致旧态夹具假设不成立的问题；其余涉及 POSIX 路径、chmod、符号链接权限、固定 Linux JSON 样例、python3 商店占位符、sh 不在 PATH 和原有服务/安装测试。使用 `main@4c978aff` 只读源归档对照已复现 35 个同名失败；没有将其余未比较问题推定为基线。原始全量失败继续保留。
- 回执链 HEAD 替换曾返回 Access Denied，具体占用来源未知。根据既有规格，HEAD 只是可重建提示；已签名且 fsync 的链行及独立 checkpoint 仍为事实源。新增负向验证：不可写 HEAD 不撤销已落盘行，checkpoint 不可写依旧失败。未宣称确认占用进程。

## 原生验收状态

已通过 computer-use 的 `node_repl` + `@oai/sky` 找到两个 WorkBuddy 5.6.2 窗口。窗口 264878 显示旧专用工作空间及 step-5-preview / 默认权限，当前只读查看历史末次 F-up。未新建或发送模型任务，未改旧提示词、输入、输出、模型权限或账号状态。此前工具发现阶段未找到 node_repl 的临时限制已经解除。

原生新批次 N/R/W/T/J×3/F、全新状态安装及卸载/升级/回滚、正式发行签名仍未完成；组件通过不替代这些门槛。新业务 Grant 需要独立的具体批准，连接管理浏览器不产生业务权限。

## 工作记录位置

本地过程日志位于本任务 workspace 的 `work/validation/`，包含完整失败及后续修复结果；发布前将生成脱敏交付证据索引。基线源码归档只用于对照，不是新的发行候选。原始任务书、历史 0.4.0 包及旧证据未改写。契约和产品源码分别提交；远端推送及候选固定提交以最终交付索引为准。


## 最新收尾验证

- 受影响包最新组合：privatefs、statefs、state、adapterinstall、adapters、pending、receipt、runtimeaction、grant、skillmanifest 均在 r4 通过；cmd、runtimeidentity、workbuddycorrelation 在 r5 通过（145.996 / 20.255 / 9.502 秒）。Windows 缺少 symlink 特权的用例只对 Win32 1314 标为 skipped，不把它记为安全校验通过。
- server 的 WorkBuddy/Windows Authority/Observation/LocalFailure/RuntimeIdentity/Enrollment 定向测试退出 0（63.053 秒）。
- 最终 `go vet ./...` 退出 0。
- Windows amd64 `go test -race`：workbuddycorrelation、pending、receipt 全部退出 0。使用官方 LLVM-MinGW 20260922 UCRT 工具链，下载 SHA-256 与官方发布元数据一致。
- Windows hook 最新 15 轮多进程及同进程并发全部退出 0（51.551 秒）；同效果没有 Post 的后续调用继续拒绝 uncertain。新的释放负向测试确保不删除被换入的他人锁。
- pending/receipt/迁移预览三项 Python schema 校验退出 0（0.037 秒）；旧 v1 schema 保留。
- 运行 Windows 原生 Task Scheduler 的独立测试实例，用自建 source/target 测试版本验证实际进程切换、恢复与撤销保留。这是本地运行身份签名的测试，不是正式发行签名验收；结果另行记录。

版本拟为 `0.4.1-rc.1`，远端查询未发现同名候选 tag。本机正式发行 seed 尚未配置，已询问既有受控签名渠道；不检索秘密文件、不生成替代 key。新批准备材料只含合成输入与未执行矩阵；模型/默认权限、精确实例、T 命令和最小 Grant 需要独立读回及批准后才能冻结。


- Windows Task Scheduler 两项原生 opt-in 最终退出 0（137.302 秒）：真实 source→target→source；候选缺失/独占占用在停服务前拒绝；中断创建可恢复；撤销草稿在停止版本 CLI 下仍不可批准/部署；测试实例最后停止并注销，私密恢复材料保留。
- 安装发布补充：Windows WorkBuddy 新对象/恢复副本改用排他单链接移动，避免中断留下临时硬链接。完整 adapterinstall r6 退出 0（66.692 秒），再次 go vet 退出 0。
- 首轮 `13957297` 的未签名候选四目标隔离构建与 Skill 自扫描成功，但被上述收尾修正取代，保留旧过程记录，不作为最终候选。
- 实际 Windows 打包发现 `npm` 需要显式 `npm.cmd`，已修复；源码 tar 安全预检使用 POSIX 路径解释并拒绝 Windows 盘符/反斜杠/ADS 拼写，防止 `/escape` 在 Windows 被误判为相对路径。新增跨平台反例验证。

未验证边界：真实不同 owner 的集成场景未提升权限运行；需要符号链接特权的夹具有明确 skipped；不能把这些记为通过。正式签名、新 WorkBuddy 实例登录/模型配置、具体业务 Grant 批准和 N/R/W/T/J×3/F 仍是产品结束门槛。

## 回退兼容补充

在新建合成 Windows 状态上，b63c8638 新二进制写入并提升一条 v2 本地失败记录后，当前程序 verify 退出 0；main@4c978aff 的只读源码构建 state-status 退出 0，而 verify 退出 4（receipt hash mismatch）。这不涉及旧正式状态或发行私钥，证明仅检查 profile 3 marker 不足以判断回退数据兼容性。

新增当前发行工作流的只读历史检查：reader/writer 小于 4 的候选在 v2 pending/receipt 存在、历史不安全或无法检查时，于暂存/停止/切换前拒绝。新发行声明能力 4，旧 marker、profile journal、历史签名样例保持原字节。新 reader4 清单与 CLI 样例分别新增；不把旧二进制直接运行的失败宣称为 marker 已永久升级。恢复卡必须说明有 v2 记录后保留兼容程序和原状态。

clientrelease 正负向检查已通过，包含旧 v1 允许、v2 拒绝且零暂存/历史不变、兼容候选允许、重复/未知字段、超限和非普通日志拒绝。新增能力合同的 Python 8 项验证及 go vet 退出 0。完整 Windows 模块最新阶段记录仍失败，不能将整个仓库记为绿色；最终候选与详细检查结果在交付索引固定。

## 并发草稿状态读回补充

Windows r9 全模块共 35 个顶层失败名称，已在未改动 4c978aff 对照复现同名失败。最后一项实例草稿并发经 30 轮复查，当前出现 11 次、基线出现 12 次“新建计数 2 或 3”。底层同字节已完成事务幂等重放返回 nil，HTTP 原入口会再次返回 201；实际 Grant ID 相同，不能据此宣称重复创建了有效权限。

首次草稿改用在原发布锁内区分已完成记录的 CommitInitialGrant：冲突后读回并返回复用，普通 CommitGrant 恢复保持幂等。确定性同字节反例在旧入口返回 3 个创建者，新入口仅 1 个；Windows 原 HTTP 用例连续 30 轮通过（15.705 秒），原草稿/审计/批准状态断言保留。没有靠增加请求随机数或放宽测试隐藏问题。

草稿 PR #110 已建立。首轮远端 Go、前端、跨平台构建及相关检查通过；Control API Ruff 指出新增 Python 测试格式错误，已修复并本地全 app lint 通过，合同 3 项仍通过。后续检查按精确提交记录，不把旧提交的成功直接标成新提交通过。

## 扫描预览 Windows 身份补充

最终 11c72533 的全模块 r10 为 53 个包结果、9 个失败包、34 个顶层失败名；全部同名问题在未改动基线复现，但并不表示应忽略。进一步定向复现 inventory 的目录替换测试失败：Windows 路径型 FileInfo 的文件 ID 延迟到 SameFile 读取，移走原目录后，新旧比较可能都观察原路径的新对象。

扫描根初始快照现从只读句柄 Stat 固定身份，采样与访问结束时复验命名路径；不读取配置正文、不修改 ACL、不长期持有预览句柄。目录和同内容文件的替换负向用例均执行通过，替换后的重新预览正向通过；先前替换检测与 symlink 前置混在同一测试的问题拆开记录。将句柄采样回退为旧 Lstat 的 overlay 反例在目录和文件两项都失败，防止先调用 SameFile 意外填充缓存而掩盖回归。

完整 Windows inventory 最新检查只剩两个明确的 symlink fixture 特权失败；本次预览 symlink 检查仍因同一特权缺失跳过，没有按通过计。go vet ./... 退出 0。完整模块、远端检查和候选记录随后按本次提交固定；正式签名与 WorkBuddy 新批仍未完成。

## Windows 回归夹具与展示合同补充

7494b754 的完整 r11 为 53 个包结果、9 个失败包、33 个顶层失败名，七个远端 PR 工作流均通过。继续定位后修正 8 项实际夹具问题，未改变生产行为或放宽任何权限检查：

- 当前未签名诊断与 Windows 发现样例移除已退役 CodeBuddy 行；逐字段对照确认其他字段不变，历史签名样例保留。
- 新增 Windows 的 adapter-plan v2/v3 和草稿返回样例。真实 Windows 没有 POSIX 受控安装 wrapper，Hermes 原生根使测试选中 legacy default，证据 ID 的定位字符串也有平台差异；保留完整字段比较与真实 Grant 签名预检，不删除差异字段来制造通过。
- admission 的 inode 替换反例先从句柄取身份并关闭，再改名保留旧文件，确保 Windows 能真正注入替换且旧 ID 不被重用。
- UP07 用 `.exe` 编译并启动 Windows 测试 CLI；启动失败独立判为测试错误。实际不兼容状态拒绝、恢复提示和零写入已通过。
- 原始内容过期清理的快照断言统一相对路径分隔符，仅允许精确 raw-task-content 子目录变化；其他签名历史仍逐项不变。

上述 8 项 Windows 定向检查退出 0，server 6.708 秒；相应新旧 DTO 的 10 项 Python schema 正负向检查退出 0。其他旧式 POSIX 资源夹具在 Windows 仍可能失败，未将未验证能力自动转换成 Windows Authority，也未用整包 skip 代替真实回归。全量 Windows 和远端记录以最终固定提交的交付索引为准。

## Windows 写入故障与 Git 夹具补充

`12636ee3` 的完整 Windows r12 退出 1：53 个包结果、8 个失败包、25 个顶层失败名，上一节 8 项均通过。剩余同名失败均在未改动基线复现，仍是失败而非验收豁免。

其中三项 OpenShell evidence 测试用目录 `chmod 0500` 注入写失败；Windows 实测 DACL 未改变且仍能创建文件。现改用测试专用 deny-create ACE，仅作用于本次临时 evidence 目录并在清理时恢复；真实创建返回 PermissionDenied 后才执行断言。计划持久化失败仍要求零执行和原 reservation 的签名结案；执行后持久化失败仍要求明确 executed/uncertain、单次执行、无自动重放、不泄露输出。其他平台保留 mode 注入，同样验证注入确实生效。产品代码、用户对象 ACL 与权限均未改变。

本地 Git 夹具的脱敏 stderr 定位到路径过长；仅规范 file URI 或启用 `core.longpaths` 仍因 `$GIT_DIR` 超限失败。缩短临时状态目录后两个测试通过，另一个显露 Windows 不表示 POSIX 执行位的样例假设。现使用短随机目录，分别校验源文件和快照的真实平台模式，保留条目、验签、固定副本、错误 pin、缺失子目录及 hook 禁用断言；正式 Git fetch 接口保持不变，不执行候选脚本。

Windows 定向 r13 退出 0：四项 Git 导入/上游测试（含三个先前失败名，6.411 秒）和全部 17 项 OpenShell task-exec 测试（含三个先前失败名，11.489 秒）通过。此结果只证明组件，不代替正式签名及新的 WorkBuddy 原生矩阵。

## Windows 原生文件效果与持久化组件补充

完整 r13 在 `97fea090` 结束：53 个包结果、8 个失败包、19 个顶层失败名，上一节 6 项修复均通过，7 个远端工作流通过。剩余旧 POSIX 用例不能直接改成 Windows：intent/v4 实例权限明确不接受 intent/v3 的 effect_requirements。旧用例及失败记录保留，不从 GOOS 推定新版 Authority。

新增 Windows 外部包测试调用真实 Initialize/ActivateWindowsProfile 事务，随后用原生 v2 快照、pending/v2 检查 store 重开、相同发布并发重试、唯一接管胜者、原期限、容量及历史完整性。原 pending 的字节、签名和 before 始终不改；有界失败及未发布临时文件不改变 owner。首次探针期待“未改内容的恢复历史硬链接被拒绝”，实测不成立：该历史目前是普通签名读取，现有单链接合同适用于私密读与资源采样，不能混称。保留探针失败，正式用例验证通过别名篡改已签 owner 后拒绝；没有为绿色结果放宽产品读取或改写历史。

新增 WorkBuddy Windows HTTP 检查使用既有生产实例草稿、挑战批准、部署、专属 identity/v2 凭据、intent/v4 登记和 Pre/Post 入口。实际写入及“Post 声称成功但没有文件”分别运行，独立 observer 在清缓存、错误路径恢复、正确接管后保留原 before，发布真实 expected/completed 或 unexpected/failed 事实；旧 observer 不可结束新 owner 的观察，已完成重试复用原签名，撤销阻止后续采样及恢复，Grant 字节不变。两种情形任务完成度都保持 unknown，因为实例权限没有任务效果要求。

定向 r14 退出 0：3 项原生 pending 检查（含 6 个边界子项，effectevidence 31.832 秒），WorkBuddy 文件效果检查的真实写入/缺失输出两项（server 14.455 秒）通过。这里运行的是 Windows NTFS、生产状态和 HTTP 组件，未启动 WorkBuddy 桌面或模型，也没有批准真实业务 Grant；正式 publisher 签名与新原生任务验收仍未完成。

## Windows 导入模式与合同样例补充

`84076cf6` 的固定源码 r14 结束：53 个包结果、8 个失败包、19 个顶层失败名。上一节新增 4 项组件及 8 个子项在完整运行中通过，并发 pending/唯一接管两项 Windows race 通过（4.510 秒）；7 个远端工作流通过。正式签名与新宿主任务矩阵仍未执行。

其中远程导入 DTO 失败已逐字段定位：只有实际复制 `run.sh` 的 executable=false，以及由其派生的 artifact_digest/signature 不同，共 7 个 JSON 路径；request 一致。ADR-033 要求摘要绑定实际文件事实，不能在 Windows 保留归档中的 POSIX 执行位声明。现新增 record/result/list 三份完整 Windows 样例，保留旧签名样例；Go 在归一化合成时钟前后都验证签名，并校验实际复制文件模式，Python 对两套样例执行同一正负向 schema 检查。

物理执行位篡改的旧探针已证明 Windows `chmod(0700)` 前后均为普通 0666 文件，没有注入变化。该单一子项现在明确 skip/未验证，POSIX 继续真实 chmod 并验证执行位确已改变。新增 Windows 正向测试验证不变的文件模式/身份仍保留原签名与摘要；新增各平台负向篡改合成记录的 executable，重算清单摘要并合法签名，先证明记录层可读，再要求完整 Load 因与实际文件不符而拒绝。它不冒充物理 mode 变更，不删除内容、分析或签名篡改断言。

定向 r15 的六项 Windows Go 顶层检查通过（1.617 秒），物理执行位和原有 symlink 两子项分别记 skip；7 项新旧合同 schema 检查、Ruff 与 go vet 通过。首次 Python 命令误加载依赖 FastAPI 的全应用 conftest，退出 4，未运行合同测试；随后使用本纯 schema 模块的 `--noconftest` 正确执行，原错误日志保留。完整固定源码结果及候选记录以最终交付索引为准，不把定向结果等同原生验收。

## 合并后的剩余 Windows 回归修复

PR #110 已合并到 `76cea35897c59c8e35b6191bc88dfb189a49021d`。本批从该 main 增量修复，保留配置读回与运行时证据区分、Windows CI 私密 NTFS 根和进程 owner 修正。r15 的 17 个旧失败名不作为继续失败的豁免。

连接器查找确有父目录跳转缺陷：只检查 exe 叶子时，子目录、显式连接器根及其上级三处真实 junction 都能让候选逃逸到外部目录。三个反例在旧实现失败，修复后通过；查找现在检查到卷根的普通目录祖先。保留明确绝对路径、布局优先级、目录/脚本/PATHEXT 拒绝及本地原生 exe 执行检查，不宣称抵御同用户之后的并发路径替换。

文件采样、持久化 pending、恢复与完成度算法共用真实初始化状态，Windows 经实际 profile 激活运行 v2 快照与 v2 pending；POSIX 保留 v1。外部测试包通过公开 API 检查原有签名、篡改、幂等、容量、恢复唯一胜者及冲突，未从操作系统隐式产生业务授权。链接负向保留叶子 symlink；仅本机明确缺少创建特权的具体子项记未验证，并单独执行真实目录 junction 拒绝。类型变化用普通文件替换为目录验证；失败清理先证明注入成功，再验证拒绝、修复后清理与外部内容不变。

两个 intent/v3 文件 HTTP 测试限定为 POSIX 合同；Windows 的真实 v4 Authority HTTP 用例扩展到 block/warn × 写入/缺失输出四种情况，额外拒绝在有效 v4 中插入 effect_requirements。Windows 的任务完成度仍为 unknown；不能将组件算法的合成 Task 当作实例权限取得任务目的。Linux namespace relay 的私密描述符正向留在 POSIX，Windows 明确拒绝该路径/描述符通道，平台无关 JSON 解析仍验证通过。

定向检查覆盖上述文件、恢复、导入、安装检查、清理、连接器和 HTTP 场景，静态检查通过。CI 比较器现在列出新增辅助包和未运行的旧失败名，保留新失败与 skip，不把移出某平台的用例写成通过；新增包仍由 go list 与完整 go test 结果逐项对齐，删除包仍拒绝。比较器 6 项测试通过。全量 Windows、跨平台构建与远端检查随后按本批确切提交和代码树记录；正式签名、WorkBuddy 桌面新任务矩阵仍未完成。

首轮全量探针 r16 另见 OpenClaw 卸载替换 `openclaw.json` 返回 Windows AccessDenied；该用例单独连续 20 轮未复现。用真实未允许 delete-sharing 的读句柄可确定复现相同的 rename 错误，但不能据此断言原占用进程是谁。旧实现的读句柄释放、持续占用、占用期间用户改写三个反例均立即失败。现仅重试 Windows 暂存配置 rename 的 AccessDenied/SharingViolation，最多 300 ms 累计等待，每次复核原 before，持续占用仍拒绝，用户变化返回 ErrPlanChanged，零 ACL 调整，临时文件清理不变；三项反例及原卸载场景合计连续 10 轮通过。r16 保留为诊断探针；补充修复后以再次完整运行作为最终源码的验证依据。首次未签名组包已编译四目标，但目录发布遇到另一个 WinError 32，仍记失败，未把仅编译完写成候选交付成功。

## 远端全量基线的最后六项与严格门禁

`5d4deaebf28f12ec370cc81bc282126bfba92542` 的六个远端工作流均成功，但 Windows 比较报告仍列出 6 项候选失败；它们在精确 main 基线同样失败，旧门禁仅检查“无新增失败”。下载的完整日志保留，不能据工作流绿色宣称全量通过。该源码的本机 r17 覆盖 55 包，skillinstall 达到累计 15 分钟包超时，记录为失败；其余包完成，不能把超时省略为通过。

- Windows UNC host 的 DNS 尾点被 Go 1.26.6 的 VolumeName 分界误当目录尾点。已在本机同版 Go 复现；原始输入现在明确定位 share 起点，保留 share/后续目录尾点和尾空格拒绝。设备 UNC 三种拼写与分隔符的正负向同时验证。
- 同步 HTTP 失败夹具原先只设置 HOME，Windows 实际使用 USERPROFILE；CI 因空盘点跳过 HTTP，本机可能依赖真实配置。现在隔离两种 home、宿主覆盖、本地应用目录和连接器，并断言测试服务器确实收到一次批次 POST；401 必须失败，原本地决策仍不变。
- Windows 私密 seed 读取在初始化守卫前已拒绝 dangling symlink，错误明确为 reparse_object。测试按平台检查确切错误、nil key、链接未替换及外部目标仍缺失；仅缺少创建特权的叶子链接断言记未验证，不把它算通过。产品私密检查不变。
- 三个依赖目录 fsync 的 systemd/launchd 发布恢复正向测试留在 POSIX 执行，保留原断言。Windows 单独验证 CLI 在创建状态/用户目录之前拒绝两种平台入口，以及自身 Task Scheduler 九种删除/恢复场景；未运行的旧 POSIX 测试在比较结果中单列，不冒称已在 Windows 通过。

修复后的定向 r18 使用 Go 1.26.6，通过路径、同步、导出、身份与 Windows 服务检查；dangling 叶子链接本机缺特权，需由有该能力的 Windows CI 验证。CI 候选现在必须全模块退出 0，基线仅作诊断。最终固定提交的远端完整结果、跨平台候选和来源摘要以交付报告记录；正式签名与真实 WorkBuddy 新批次仍独立待验收。
