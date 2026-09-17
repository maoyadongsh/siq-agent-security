# Windows N01：历史无标记状态迁移子旅程

真实 Windows 原生子旅程通过：从完整历史源码构建的旧程序建立无版本标记的实例和已撤销 Grant，再由当前主线程序显式迁移到 v2。33 个原状态条目的摘要、文件大小及记录属性保持一致；37 个备份条目完整核对，文件还与现场原对象逐字节比较。重复迁移返回 up_to_date，再次撤销已撤销 Grant 返回退出 1；两次操作结束后的状态快照均无变化。

本批仅补“已初始化无标记→v2”。旧程序不具备兼容防护，进入新程序阶段后没有再运行旧程序。受保护 v1 的活动屏障、旧程序拒写 v2、故障中断恢复、正式客户端升级/回退仍未由本批验证；既有旧源码缺口保持。没有启动 Hermes、OpenClaw、WorkBuddy 或 SIQ 服务，18 行平台矩阵和三宿主验收结论不变。

此独立源族由 [N01 规格](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/docs/n01-state-protocol-design-20260913.md) 明确支持；历史身份对应 [原初始化实现](https://github.com/maoyadongsh/siq-agent-security/blob/ff99317450784c9563f5b6a2308c98e8262df98d/apps/agentshield/internal/state/initialize.go)。已有调查缺的是受保护 v1 的完整旧快照，不能把该缺口扩大为“无标记历史源也无法测试”。

## 固定身份与实际步骤

- 旧源码：`ff99317450784c9563f5b6a2308c98e8262df98d`；Windows binary SHA256：`0fa81005ee65bc12c00e8390251d19fc1d3958beb988cecff61e62eeca517a42`。
- 新源码：`b303c6f92392f3a44c306d81ad7323c6291ef4f2`；Windows binary SHA256：`ee4b78c79bb2aee0d2ea1996ce8e937e9d8a0b320c77cabb3b71ef2b2233e470`。
- Windows 11 专业工作站版，10.0.26200，x64，NTFS；PowerShell 7.6.5，CPython 3.13.7，Go 1.27.1。两份源码均原样 `go build -trimpath`，无 Version 覆写；build metadata 均为正确提交且 `vcs.modified=false`。旧/新模块分别 1018/1066 个文件与 Git blob 字节核对。

唯一一次旅程共十条原生 CLI：旧 init → pubkey → admit 自建纯文本 Skill → grant → revoke；新 state-status → state-migrate --confirm → 重复迁移 → state-status → 再次 revoke。前九条退出 0，最后一条按预期退出 1，错误为 illegal transition revoked → revoked。没有超时、强杀或未回收进程。每条进程等待和收尾预算 30 秒，其中收尾保留 5 秒；文件摘要及快照检查另计，不声称硬性抢占 OS 调用。

Grant 实际由 pending_approval/revision 0 变为 revoked/revision 1，从未 approved、deployed 或 effective；本结果不冒充已执行权限的撤回。迁移后的新程序读取同一状态并拒绝重复撤销，原准入、Grant 修订、提交/审计、配置和密钥等对象摘要保留。没有手写或删除版本标记，也没有把新程序换版本名当历史程序。

新程序迁移前只读诊断为 legacy_unversioned/format 0；迁移计划实际记录 source_marker_sha256=absent，绑定原实例和目录。备份 37 条目由原 33 条加迁移持锁创建的四个维护目录组成。完整备份集合、内容摘要、Windows Go mode、目标标记、归档计划和完成点摘要均核对；活动计划已经清理。零写结论限操作前后持久状态快照一致，不等于没有临时 Writer 锁 I/O。

## 复验与边界

`journey.py` 是实际执行脚本的逐字节副本。准备两份上述干净源码/二进制、同一新私有父目录下的 build 和空 journey 子目录，再传入五个必需参数：`--private-root`、`--old-binary`、`--old-sha256`、`--new-binary`、`--new-sha256`。由操作者先设定私有 ACL；脚本只接受空目录、普通祖先和预期二进制摘要，错误即停并保留现场。不能对已有测试根重复运行，不能将无防护旧程序用于已迁移状态。

根任务重新核对 32 条构建/CLI 原流及 2084 个模块源文件。现场状态、完整备份和原始业务输出始终留在仓库外；公开文件只含白名单结果与摘要。根目录 DACL 首尾一致。另读回 124 个测试对象，其中 84 个显式当前用户 ACE，40 个为 OWNER RIGHTS 且 owner 为当前用户；均另有 SYSTEM/Administrators 两条 FullControl ACE。首次按字面 SID 比较产生的 40 个 false 保留，补充分类没有修改 ACL。此处没有迁移前逐文件 ACL 基线或跨用户访问实测，不能声称 ACL 保真或完成 #42。

六份本次真实输出另用 jsonschema 4.26.0 验证，全部通过四种原候选合同：迁移前/后的状态诊断、首次/重复迁移结果、v2 标记和归档计划。Schema 字节与 b303 Git blob 相同，见 `output-schema-validation.json`。这次直接验证使用既有 Windows 依赖环境，只导入 JSON Schema 库，不加载 API；它不替代 P05 原标准 pytest 入口。

独立只读复核未发现差异：另算 32 条原流、12 份快照及两份二进制摘要，实际遍历的最终 81 条状态记录与保存快照一致，37 条备份及两版 Grant 历史匹配。详见 `independent-review.json`；该复核没有重跑 CLI、源码编译、签名验证或独立 Get-Acl，密钥只流式计算摘要。

没有产品代码改动，因此未为此证据批次重跑全量 Go、跨 OS 编译或三宿主测试；此前失败不改写。构建原流和每步退出/耗时见 `build-provenance.json`、`summary.json`，根复核范围见 `verification.json`。本批不发布制品、合并 PR 或修改治理设置。
