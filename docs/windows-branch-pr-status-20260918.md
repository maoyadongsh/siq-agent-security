# Windows 开发收口与仓库协作索引

2026-09-18；负责人 sunbo。本索引只整理 Windows 开发入口，不改变 main、其他协作者分支、发布设置或验收结论。功能说明见 [Windows 功能交付](windows-functional-delivery-20260918.md)。

## 唯一后续开发入口

`codex/windows-resource-facts-20260918` / [PR #83](https://github.com/maoyadongsh/siq-agent-security/pull/83)。已有功能修改、接口/规格和后续待验修复集中于此，不再向已被吸收的专题分支重复提交。

保留审阅顺序：**main → #80 → #81 → #82 → #83**。不要跳过依赖直接合并最后一层，也不要因关闭重复 PR 而误以为它们已进入 main。#83 在本次整理前的 head `925fb8d` 对其基线可合并但检查不全绿：38 成功、2 失败、2 跳过；因此保持 draft。本文提交不修改产品代码或放宽 CI。

| 保留 PR | 用途 |
| --- | --- |
| [#80](https://github.com/maoyadongsh/siq-agent-security/pull/80) | Windows 基础修复组合；保留独有 Writer/全量回归历史证据，后续三层依赖它。 |
| [#81](https://github.com/maoyadongsh/siq-agent-security/pull/81) | 迁移重入、只读备份发布修复。 |
| [#82](https://github.com/maoyadongsh/siq-agent-security/pull/82) | Windows 私密 ACL 和迁移恢复。 |
| [#83](https://github.com/maoyadongsh/siq-agent-security/pull/83) | 三宿主、Windows 共性功能及最终开发集成入口。 |
| [#44](https://github.com/maoyadongsh/siq-agent-security/pull/44) | 独有 NTFS/ACL/路径历史证据；不是当前开发分支。 |
| [#78](https://github.com/maoyadongsh/siq-agent-security/pull/78) | 独有 OpenClaw 原失败与 Hermes 失联/非法响应证据；不是当前开发分支。 |

## 已关闭的重复实现入口

#56、#57、#73、#74、#84、#85、#86 已关闭为由 #83 吸收，原分支和原 PR 内容保留。前六项通过祖先或 patch-id 等价核对；#86 的合同提交因共享规格后续增量产生不同 patch-id，已额外核对 Schema、样例、合同测试和专项规格字节一致，以及原新增共享规格/AGENTS 条款全部存在。

关闭重复 PR 不等于删除实现、合并到 main、通过验收或修复关联 Issue 的所有要求。合并门禁和维护者审阅仍保留。

## Issues 的真实状态

- **#62 已关闭**：计时测试修复由 #76 合并到 main，合并提交 `2187fea621ff40b368f2e01e51d26672239c9f8d`，对应定向/race/包回归与反向实验保留在 #76。
- **#43、#51、#63、#79 保持开放**：实现已在 Windows 依赖链，等待主线合并；不再重复建开发分支。
- **#39、#42、#77 保持开放**：实现已集成，但真实宿主/隔离或完整复验条件仍有缺口。原失败和未知状态保留，不凭代码存在关闭问题。
- **#53 保持开放**：原并发窗口及损坏状态证据保留；后续集中 #83，不把旧本地 grant-snapshot 草稿自动当作最终补丁。
- 非 Windows 的研究 Issues、其他作者的 PR 未改动。所有更新在原正文前补充状态，未删除旧说明或原始证据。

## 本地分支与未验证草稿

所有本地 Windows 分支已按“当前开发 / 依赖审阅 / 独立历史证据 / 已吸收 / 已合并历史 / 本地草稿”设置 Git branch description。没有删除本地或远端分支，没有移除工作树，也没有改写提交历史。

主集成工作树原有 `launch_agent_switch_test.go` 未验证修改已独立保存至本地 `codex/windows-deferred-launch-fixture-20260918`，提交 `3f7bbcfe43f2d8aa3d09dac168ea5edcb71b3e21`。归档文件与原工作区字节一致；该分支未推送，不能算已交付或已验证修复。主集成工作树中的原修改随后安全还原到交付版本。

`windows-grant-snapshot`、`windows-openclaw-epoch`、`windows-staging`、`windows-test-portability` 对应旧工作树中的草稿仍原样保留。可能包含已被后续实现替代的内容；使用前须与 #83 对比，不直接批量 cherry-pick、不丢弃。`.tmp` 中历史原生夹具和证据仍保留用于复现，本轮未执行其中脚本。

## 收口结论和后续边界

已开发代码有统一集成入口、依赖关系与可审阅说明；重复入口已关闭，已合并事项已更新，未验证草稿与交付代码分离。**仓库组织已收拢，但主线合并、正式发行和完整验收未完成。**

后续维护者按上述依赖链审阅。正式签名、Git 生产安全门禁和 CI 失败不能绕过；额外 WorkBuddy 模型调用及第二 Windows 身份仍需对应资源。按用户本轮限制不重启系统、不新增完整测评、不发布或自行合并。
