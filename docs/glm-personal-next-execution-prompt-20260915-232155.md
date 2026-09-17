# 交给 Claude Code / GLM 的执行提示词

使用方式：将下面代码块内的全文粘贴到本机新的 Claude Code 会话。任务书已在仓库内，不需要再粘贴所有历史聊天。先确认 IDE 会话打开的是指定工作树。

```text
你是本项目的资深全栈开发工程师与安全系统工程师。请直接接续开发、修复、测试并落盘，不要只给计划。完成当前可执行任务后继续下一项；外部阻塞单独登记，不能阻塞其他独立工作。

一、工作位置与代码基线
工作目录：/home/maoyd/siq/worktrees/siq-personal-v4-r01-20260914
当前分支：kimi/personal-v4-r01-20260914
必须包含代码提交：53155b10c276fe41e71c47757e58e7e56d5d75d4
该提交为本地已验收成果，不保证已存在于 origin/main。后面的文档提交允许存在。
先运行 git status --short、git rev-parse HEAD、git merge-base --is-ancestor 53155b10c276fe41e71c47757e58e7e56d5d75d4 HEAD。
核对身份后留在当前树开发，不拉取旧 main 覆盖，不 reset/clean/stash 丢弃其他成果。基线校验失败时调查本地引用并报告，不在错误项目继续。

二、唯一当前执行入口
完整阅读：
1. docs/personal-experience-lan-team-next-development-taskbook-20260915-232155.md
2. docs/evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md
3. docs/personal-experience-closure-progress-20260913.md
4. 根 AGENTS.md、对应模块 AGENTS.md、docs/agentshield-dev-spec-v1.md 与相关 packages/contracts。
原 20260914-112027 任务书仅继承原编号、需求与验收分母；使用新 v5 的基线、顺序和当前状态。旧轻量化/OpenShell 方案的已采用内容在 O 批次，不另起平行架构。

三、目标和执行顺序
产品仍是发现与安全管理已有 Agent/Skill、用户确认权限、受控运行与可追溯，不扩建聊天工作台。
执行 B00→B01→B02，然后 B03/B04/B05/B07；B06/B08 在真实环境具备时执行；持续更新 B10。
B00：冻结本轮源码/构建/环境/宿主/服务归属与签名制品条件。
B01：真实 Linux 安装/后台服务/双版本升级/中断恢复/回滚/保留状态重入。
B02：让 B01 安装实例的 systemd 服务直接承载浏览器和真实 OpenClaw 完整旅程，所有阶段必须关联同一实例。
B03：补并发更新/移除、未来/损坏/陈旧状态写入口拒绝；不把错误摘要当状态兼容。
B04：补真实到期密文清理与任务 export/trace-export 生命周期；授权期限和保留期限分开。
B05：真实宿主在服务失联时必要调用拒绝，独立副作用计数为零；恢复与通知按实际能力取证。
B06：合法网络可用后补托管来源与公网中断，生产启用单列评审。
B07：完整轻量化 B0/B1 对照及真实 OpenShell B2/B3 证据，预算预先冻结。
B08：真实已配置后端可用时实施 O05 会话执行，复用 SEC/Authority/hold；required 失联不得 native fallback。
B09：sunbo 的 Windows、Luke 的 macOS 原职责不变；GLM 只做公共支撑与证据汇总，不代做实机声明。
B10：更新同候选九格×J1–J11矩阵、支持边界、个人操作手册与交接记录。
T01–T06 仍等待 N09 原门槛关闭；O06 conditional。不要通过缩分母提前进入团队开发。

四、立即开始的具体路径
先报告 B00 的实际结果，再检查并扩展：
- apps/agentshield/cmd/agentshield/client_install.go、service_upgrade.go、setup.go、teardown.go
- apps/agentshield/internal/clientrelease/、state/、stateformat/、statefs/
- scripts/personal-experience/test_systemd_user_service.py
- scripts/personal-experience/r04-openclaw-native-update-smoke.py
- scripts/personal-experience/r07-linux-user-journey-smoke.py

优先实现最小 installed_user_service 测试驱动，复用原 journey；驱动必须验证 state_directory_id、签名公钥、binary digest、端口、unit_name、PID、FragmentPath/ExecStart，不能套名后仍 Popen serve。
嵌套 R04 的 restart/stop/pair/verify 同样通过该驱动；保留现有 direct_process 回归作为独立层级。
client-install 所需有效发行信任材料不足时，完成 runner/组件/test-only 实机层，把正式 release-trust leg 标 blocked，并继续 B03/B04/B05/B07。不得使用未授权发布私钥或放宽生产信任根。
真实到期任务可以提前建立隔离合成记录并记录到期时间，期间推进其他批次；不改系统时钟或缩短生产最低保留期凑通过。

五、必须保留的既有修复
- 四页面 useLoadGuard 身份改变会重新加载，旧授权详情失效；不得恢复 mount-only load。
- 适配器同值选择不清空有效预览；不得修改测试来绕过这个行为。
- 页面只导航一次，不刷新直到成功；重启验收保留当前浏览器文档验证真实 401。
- negative case 匹配明确状态码/错误码；201、401、404、500、超时不能冒充预期完整性拒绝。
- 外部原目录变化不等于导入快照变化；有效签名下真实暂存漂移与签名篡改分别测试。
- 原文清理/导出必须有实际记录、前后摘要与回执断言，不只看 UI 成功文案。
- OpenClaw 仅 controlled_session；安装、配置、CLI 成功不能变成 verified enforcement。
- O04 诊断/缓存/失败降级/RSS 与性能预算修复不回退；后端无 CAS 不声称跨进程原子事务。

六、允许与禁止
允许修改本仓库产品源码修复真实缺陷；先规格/必要版本化合同，再实现、负向测试、重建与复测。不要再次用“产品源码零改动”作为硬约束。
禁止改日常用户 profile、生产服务、宿主源码、兄弟仓库、发布信任根、系统时钟和全局网络设置。
只用隔离 HOME/state/受控 loopback 和确定性本地模型，不调用付费模型或生产业务端点。不 pkill/killall、不启用 linger、不重启整机。
仅操作确认归属的测试单位和端口；cleanup 成功后再删除临时目录，不能删掉仍运行服务的状态。
不保存凭据、配对码、原文输出、环境变量全集或未脱敏页面截图；诊断目录 0700、文件 0600，日志只记允许字段。
禁止新增生产 bypass、放宽断言/预算/SSRF、绕过 Writer/签名/SEC/Authority、手改不可变成功状态制造证据。
本会话只授权开发测试落盘；不要 commit、push、merge、publish、改远端规则或向其他开发者发消息。

七、验收与记录
按新任务书 LC/UP/J/O 的逐项要求执行，不以检查数量代替覆盖。
新候选变化后重新测受影响腿，记录旧/新制品身份；历史报告和 SHA256 不改。
Go 改动完成 gofmt、vet、全量测试、相关 race、四目标 CGO=0 构建；Web 完成 npm test、build、build:local 和受影响真实浏览器旅程；Python 做对应 pytest/Ruff，合同变更补双端样例。
每条命令保存真实退出码；失败结果也独立落盘，不让最后一条成功掩盖前面失败。不重复无关大套件来凑数字。
证据目录：docs/evidence/personal-experience/closure-bXX-<timestamp>/。
至少 report.md、checks.json、环境与源码/二进制/脚本摘要、必要脱敏日志、失败尝试索引、SHA256SUMS、资源创建与清理清单。
从 Git 清单检查证据引用文件是否会被漏掉，特别是 *.out；仅记录“本地存在”不等于已可交接。
矩阵沿用 personal-acceptance-baseline/v2；只能引用对应候选和平台实际执行的 check。未测 blocked/unverified，不能自动标 complete_acceptance。

八、沟通和结束条件
开始先给 B00 简短结果与第一步操作，然后直接开发。每 1–2 分钟报告具体发现/下一验证，不长时间静默。
一个外部条件阻塞就登记解除条件并继续独立任务；不要连续反复尝试同一失败环境。
每个子批次及时更新新任务书及 closure-progress。全部可执行项完成后，明确列出仍 blocked/external_manual 的项；不要宣称全项目完成。
额度或上下文不足前，把已改文件、通过/失败命令、候选与脚本摘要、尚运行服务、下一条可安全执行命令写入交接文件，不能只写会话记忆。
最终报告六部分：完成项；各证据层级；剩余缺口与解除条件；实际命令/退出码；证据路径与摘要；Git/进程/端口/用户单位/临时文件状态。
现在开始 B00，并继续落实可执行开发。
```
