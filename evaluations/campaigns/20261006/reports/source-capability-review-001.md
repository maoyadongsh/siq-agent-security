# 来源导入能力复核与测评口径修正

日期：2026-10-06。性质：作者侧源码、合同、历史证据和固定候选组件复核，不是新增业务端到端成绩。

本轮在既有六条产品链、40项功能、18条业务旅程梳理上，重点读通来源获取→固定副本→准入→权限创建→安装复验。重新计算465份已索引源码和14份历史索引输入的摘要，均与前次一致；另比对42份来源相关源码、合同和ADR，当前工作区与既有固定候选完全一致。详见[复核清单004](../inventory/function-review-refresh-004.json)。摘要一致是证据复用条件，不代表本轮重新逐行审计全部源码或逐帧观看视频。

## 1. 四种来源不能合并成一个“已支持”

| 来源 | 当前生产入口与真实边界 | 测评口径 |
|---|---|---|
| 本地目录 | `POST /v1/skill-imports`，`source_kind=local_dir`；复制后再次扫描原目录，对比树摘要 | 已有本地安装和来源身份旅程；复用准确批次，补未覆盖的目录/竞争变体 |
| 本地ZIP | 同一入口，`source_kind=local_zip`；有界解包、必须选中根层SKILL.md | 组件支持不等于已完成同候选原生安装；单列ZIP正常链及畸形归档负向 |
| 公网HTTPS ZIP | `POST /v1/skill-imports/remote`；生产传输限定公网HTTPS/443，真实DNS/TLS校验，不用代理 | 私有拨号器/TLS夹具测试与真实公网获取分别报告；公网成功证据仍须补齐 |
| Git定位符 | `POST /v1/skill-imports/git`；合法受支持GitHub定位符最终仍到关闭门禁 | 目前只能验收明确不可用且无候选发布，不能记Git导入成功；不支持来源、非法参数另行分层 |

生产关闭依据是 [productionGitFetch](../../../apps/agentshield/internal/skillimport/gitsource.go) 和[门禁测试](../../../apps/agentshield/internal/skillimport/production_git_gate_test.go)。[HTTP映射](../../../apps/agentshield/internal/server/skill_import.go)将该错误映射为503 `skill_import_git_transport_unavailable`。此处是代码和组件层依据，本轮没有额外调用该生产HTTP接口。

[ADR-0051](../../../docs/adr/0051-controlled-hosted-git-source.md)顶部明确“生产入口仍关闭”，正文却保留“ErrGitTransportUnavailable随本决策移除”和“首批可用”的目标描述。应将后者视为尚未兑现的目标，不能据此覆盖当前实现。测评记录该文档矛盾；本轮不修改产品门禁或历史ADR。`fetchHostedGit`、测试用`cloneGit`、诊断preflight均不能充当生产入口成功证据。

## 2. 导入到底证明什么

[Store.create](../../../apps/agentshield/internal/skillimport/store.go)发布的是签名候选及准入分析。所有来源以`TrustLevel=unknown`进入准入；HTTPS成功、摘要一致、固定commit或签名记录均不自动证明发布者可信，也不批准Grant或安装Skill。内容中包含网络/文件能力需求不应仅因此被隔离。

来源身份、内容身份和权限身份必须分开：`source_locator_digest`绑定来源定位输入，`artifact_digest`绑定所选文件树，`analysis_sha256`绑定分析；import_id和Grant又有自己的身份。[已有同字节实验](source-identity-report.md)证明本地相同内容的新导入不继承原Grant批准，不能将此结论扩大成远端发布者认证。

远端ZIP记录保留下载时归档摘要、字节数、最终定位符摘要及目录选择，默认不持久保存原始ZIP。后来验签/读回核对的是签名记录及本地载荷，不会重新证明远端当前内容。执行器若需要原始ZIP复算，必须作为测评方材料独立保存并绑定获取时间，不虚构产品已经保留原包。

## 3. 重试、更新和完整性是三个不同动作

同import_id、同规范化请求的重试会读回并复验已发布候选，不再次下载；同ID不同来源/目录/预期摘要应冲突。不能把此幂等重试当作检查远端更新。[CheckUpstream](../../../apps/agentshield/internal/skillimport/upstream.go)才会重新获取来源；ZIP URL需重新提供并与原定位摘要匹配，检查自身不产生安装或新权限。其结果与更新计划、批准、换发和安装分别验收。

[PermissionAdmission](../../../apps/agentshield/internal/skillimport/permissions.go)重验完整候选，不能凭旧摘要跳过载荷漂移。[InstallationSnapshot](../../../apps/agentshield/internal/skillimport/snapshot.go)在打开、逐文件读取及整批结束后分别复验；文件模式中的可执行位也参与核对。只检查最后安装文件字节会漏掉准入分析/元数据替换，只有签名通过也不能证明工具被正确执行。

## 4. 固定候选的限额与网络事实

当前实现限定：归档32 MiB、单文件8 MiB、总解包64 MiB、文件2000、目录2000、相对路径深度16、导入暂存槽64。各自按正常上限和上限+1构造，避免一个用例同时越多个预算而归因不清。ZIP还拒绝路径逃逸、链接、大小写冲突、加密、ZIP64/多卷和不支持压缩；`.git`排除与恶意链接拒绝分别观察。

公网传输逐次检查DNS结果、固定已验证地址拨号、验证证书及主机名，最多三次重定向，每跳重验；完整下载45秒，外层导入60秒。下载器禁用代理，环境中浏览器/curl可通过代理访问，不证明产品直连可达。测评HTTP等待应覆盖服务工作预算（建议客户端75秒、外层进程120秒），不能复用普通管理请求的10秒等待造成伪故障。

限额来源：[tree.go](../../../apps/agentshield/internal/skillimport/tree.go)、[store.go](../../../apps/agentshield/internal/skillimport/store.go)、[zip.go](../../../apps/agentshield/internal/skillimport/zip.go)；传输边界见[ADR-035](../../../docs/adr/0035-https-skill-import.md)。这是所核对候选的事实，后续换候选须重新冻结，不能当作永久通用常数。

## 5. 对整体方案的影响

修正F05能力表，按四种来源分别登记状态；RB09保留部分完成。后续依[修订执行方案](../plan/product-grounded-evaluation-revision-001.md)及[来源任务清单](../plan/source-import-work-items-001.json)补缺。已解释清楚的自检和本地身份变体不重复扩量；Git门禁作为能力限制单列，正常导入链、企业完整部署链及独立确认集继续推进。

本轮固定候选组件检查原始日志和结果见[source-capability-component-check-001.json](source-capability-component-check-001.json)：44个顶层测试通过，计入子测试为136个通过事件；`TestLiveHostedSourcePreflight`未启用而跳过。其中传输私有测试缝的成功不升级成公网端到端，诊断跳过不升级成验收通过。没有新增业务任务或真实模型调用，既有冻结分数保持不变。
