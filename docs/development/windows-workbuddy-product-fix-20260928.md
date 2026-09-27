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
