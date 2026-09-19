# 历史材料与当前状态的对应关系

[当前开发](current.md)维护下一动作；本页提供历史路径，不修改旧候选、失败、签名或原始分母。首轮 RA-06 建立历史导航；后续旧入口清理见本页处置表，冻结报告和工作树保留。

| 历史范围 | 保留入口 | 如何使用 |
| --- | --- | --- |
| V5 比赛与早期模型 cohort | [冻结状态](../hackathon/final-submission-state.md)、[基准报告](../hackathon/benchmark-report.md) | 原候选、23 控制、StepFun/Ornith 早期 4/5 与后续 5/5 分开；不能用当前发行替代 |
| 研究开源首版 | [研究操作](../research/operations-20260908.md)、[历史处置](../research/history-disposition.md)、[处理结果](../research/history-resolution.md) | `research-v0.1.0-rc.1` 的源码、许可与验证身份保持 |
| 个人开发早期 current 与版本台账 | [旧 current](../personal-experience-current.md)、[现行接续台账](../personal-experience-closure-progress-20260913.md) | 旧 current 已缩为短入口，完整历史正文由固定提交保存；早期“未提交”不覆盖集成结果 |
| 本地开发整合与 Windows 栈 | [整合审计](../local-development-integration-audit-20260919.md)、[Windows 复核](../windows-main-integration-review-20260919.md) | 分支提交纳入 main 不等于旧工作树内容可删除，更不等于全部平台通过 |
| 客户端旧签名与正式版 | [历史 fixture](../../apps/agentshield/testdata/releases/README.md)、[0.3.0 发行](../evidence/releases/0.3.0/README.md)、[源码/发行边界](../skill-source-release-boundary-20260919.md) | fixture 只作回归；正式资产在 Release，不把源码目录复制当作安装 |
| 旧站点 | [冻结页面快照](../archive/gh-pages-9a4ebdc/)、[现行站点源码](../../site/) | 旧快照保留原资源和许可证，不能当现行平台承诺 |
| 本轮组织变更 | [RA 进度](reorganization-progress.md)、[路径/冻结清单](repository-map.json) | 新入口链接历史，回退导航不撤销 Release、不降级用户状态 |

PR #68 按现有要求独立保留。旧工作树清理需要另行确认独有提交、脏文件、忽略资产、进程和路径依赖；本轮不执行清理、强制 reset 或历史重写。已有文献全文已按用户要求归入根级 research，见[迁移记录](../evidence/repository-literature-placement-20260919/README.md)；架构规范、计划和脚本的物理搬迁在导航已足够时不需要。


## 旧入口清理（2026-09-19 追加）

本批以 `0b2c8135af39071e82effc339cdf88dfd559f9ac` 为基线。文献迁移已完成后，按用户要求退役旧空壳目录；三个历史交接页仍有现行文档入链，保留原文件名作为短入口，完整正文转用固定提交访问。仓库内没有指向这三个页面旧章节的锚点链接；不会改写既有证据中的历史路径和哈希。回退本批提交即可恢复清理前入口。

| 对象 | 处置 | 理由与恢复入口 |
| --- | --- | --- |
| `Frontier References on Agent Security/` | 删除最后一份 README，退役整个旧目录 | 36 项文献已在根级 research；[清理前迁移说明](https://github.com/maoyadongsh/siq-agent-security/blob/0b2c8135af39071e82effc339cdf88dfd559f9ac/Frontier%20References%20on%20Agent%20Security/README.md)保存在 Git 历史，旧 main 目录 URL 将失效 |
| [个人体验旧 current](../personal-experience-current.md) | 删除堆叠的历史“当前指令”，保留短入口 | 由现行 current 和接续台账替代；页面链接原全文 |
| [Windows 旧分支索引](../windows-branch-pr-status-20260918.md) | 收敛为现行/历史分流入口 | 旧待合并栈已整合，避免继续从旧分支启动；Issue 实时状态不从旧快照推断 |
| [Windows 旧签发交接](../windows-signing-handoff-20260918.md) | 移除当前页面中的过时签发命令，保留历史原文链接 | 由源码/发行边界、签名包指南及发行工具替代 |
| [AGENTS](../../AGENTS.md) 中旧周期 | 明确标为历史 | 保留原约束与冻结语境，消除多个“当前周期”误导 |
| RESEARCH.md、docs/research/README.md | 保留薄入口 | 已有内部消费者、研究元数据和许可范围依赖，正文不重复 |
| 带日期任务书、审阅报告、历史失败材料 | 保留 | 承载独有决策或验收上下文，不能只凭日期或无首页链接判断无用 |
| 空日志、测试夹具、重复的上游许可证 | 保留 | 空日志可证明命令无输出；夹具和各依赖许可具有各自消费者，不能按零字节或相同哈希批量删 |
| 旧工作树、私有运行状态与恢复备份 | 本批保留 | 与已跟踪文档清理分开；清理前需逐项确认进程、忽略资产及恢复要求 |

删除路径在资产清单中记录原提交和源 blob，由守卫确认路径已不存在且原件仍可定位；原冻结规则继续检查删除操作，不能借“退役”绕过。历史文件名出现在 manifest、原任务书或 original_path 中是追溯数据，不应全局替换。


## 根目录文件复核（2026-09-19）

根目录文件按用途维护，不按提交日期批量删除。`.gitattributes` 保护跨平台摘要字节，`.gitignore` 隔离私密状态/构建产物，`.gitleaks.toml` 和 `sonar-project.properties` 分别服务现有秘密扫描及可选代码分析；保留有效配置，仅修正忽略文件中已失效的源码清单注释。

README 双语保留原章节，增加四目标源码检查的独立记录；AGENTSHIELD 修正生命周期“尚未实现”的旧描述，研究复现指南明确源码候选身份；HACKATHON 保留历史路线，修正“main 仍冻结”的表述。贡献、治理和安全政策接入当前导航、签名发行与实际支持边界。第三方说明补列已有 2026.9.4 补丁及其独立元数据，不重写早期来源清单。

`LICENSE`、`NOTICE`、`DCO` 和原许可文本保持；`CITATION.cff` 仍标识研究源码版 `research-v0.1.0-rc.1`，不随客户端 0.3.0 或目录清理改版本。社区行为规则内容继续适用，只更新研究总览链接。配置仍被 CI/工具消费，许可、治理与复现入口仍被源码发行或社区文档引用，均保留。
