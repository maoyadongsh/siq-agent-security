# Provenance-Bound Effect V1 全模板逐节审计

起点d001c4d，核对源码693641d及之后文档修改。原文模板共121个编号节（0–120）。这份表保留DoD之外的交付要求；“待逐节复核”并不表示尚无代码，只表示未完成该节全部细项与证据的对应核验。

事实源：[原文模板](templates/provenance-bound-effect-v1-development-template.md)、[DoD验收索引](provenance-bound-effect-v1-acceptance-audit.md)、[Engineering Report草稿](provenance-bound-effect-v1-engineering-report.md)。不要将45项DoD直接折算成121节完成率。

| 节 | 原文标题 | 原文行 | 本轮状态/证据入口 |
| --- | --- | --- | --- |
| 0 | 角色与执行要求 | 5 | 范围/基线已核对；保留排除项与INV，见Engineering Report A/E/K |
| 1 | 当前已经实现的能力：禁止重复开发 | 58 | 范围/基线已核对；保留排除项与INV，见Engineering Report A/E/K |
| 2 | 当前技术阶段 | 111 | 范围/基线已核对；保留排除项与INV，见Engineering Report A/E/K |
| 3 | 本轮最高层安全不变量 | 183 | 范围/基线已核对；保留排除项与INV，见Engineering Report A/E/K |
| 4 | 本轮工作范围 | 291 | 范围/基线已核对；保留排除项与INV，见Engineering Report A/E/K |
| 5 | 本轮明确不做 | 317 | 范围/基线已核对；保留排除项与INV，见Engineering Report A/E/K |
| 6 | Workstream A — Authority Hard Gate | 367 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 7 | 建立 Authorization Decision 两阶段模型 | 417 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 8 | Hard Gate reason codes | 456 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 9 | Enforcement Mode 只处理 Policy Result | 491 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 10 | Receipt Schema 升级 | 528 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 11 | Required / Optional 兼容矩阵 | 558 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 12 | Workstream A2 — 消除 `context.cwd` 的隐式授权能力 | 576 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 13 | 新规则 | 598 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 14 | Workspace Authority | 619 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 15 | ContextAssertion V1 | 647 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 16 | ContextAssertion 限制 | 691 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 17 | ContextAssertion 信任来源 | 713 | 已核对；A1–A5与C1/C6证据覆盖hard gate、历史回执及Context管理边界 |
| 18 | Workstream B — Parameter-Level Provenance | 741 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 19 | Provenance 基本模型 | 772 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 20 | Source Type | 819 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 21 | Trust Level | 846 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 22 | 谁可以签什么 Trust | 875 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 23 | Trusted Provenance Issuer Registry | 914 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 24 | Provenance 不能证明内容为真 | 948 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 25 | Parameter Provenance Binding | 974 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 26 | Parameter Provenance Resolution | 1015 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 27 | IntentContract V3 | 1054 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 28 | Provenance Constraint | 1089 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 29 | High-Impact Parameter | 1103 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 30 | RuntimeActionDescriptor 重构 | 1140 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 31 | 所有安全模块消费同一个 Descriptor | 1179 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 32 | Shell 仍保持 Conservative | 1204 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 33 | Workstream B2 — MCP Provenance MVP | 1230 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 34 | MCP Provenance 生命周期 | 1242 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 35 | MCP 默认规则 | 1266 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 36 | 不做完整语义传播 | 1290 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 37 | Derivation | 1316 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 38 | Security Rule — Untrusted High-Impact Control | 1337 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 39 | 示例 | 1352 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 40 | 同值不同来源测试 | 1393 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 41 | Provenance reason codes | 1427 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 42 | Provenance 容量 | 1446 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 43 | Provenance 容量耗尽 | 1469 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 44 | Provenance 存储 | 1489 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 45 | Workstream C — EffectEvidence V1 | 1511 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 46 | EffectEvidence Schema | 1535 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 47 | 不设计单一“安全等级” | 1581 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 48 | execution_state | 1607 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 49 | source_type | 1621 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 50 | independence | 1636 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 51 | coverage | 1647 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 52 | result | 1657 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 53 | Tool Result 只产生 Observation | 1668 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 54 | EffectEvidence API | 1696 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 55 | Effect Observer Capability | 1718 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 56 | File Effect MVP | 1747 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 57 | Network Effect MVP | 1786 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 58 | Network 重定向测试 | 1823 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 59 | Fake Tool Success | 1842 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 60 | EffectEvidence 与 Receipt 链 | 1872 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 61 | Completion 不在本轮完全实现 | 1917 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 62 | CompletionStatus API | 1938 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 63 | CompletionStatus 第一版规则 | 1965 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 64 | Workstream D — Runtime Security Benchmark V1 | 1999 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 65 | Benchmark Endpoint Model | 2019 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 66 | Benchmark Scenario Contract | 2045 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 67 | Benchmark 必须覆盖的攻击 | 2073 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 68 | Benign Controls | 2117 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 69 | Benchmark Metrics | 2141 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 70 | 不得错误计算 ASR | 2169 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 71 | Performance Metrics | 2195 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 72 | Workstream E — Threat Model | 2222 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 73 | Provenance Laundering Threat | 2263 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 74 | Aggregation Rule | 2297 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 75 | Transformation Rule | 2333 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 76 | UNKNOWN Rule | 2357 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 77 | Workstream F — Capability Matrix | 2379 | 已修正文档并核对；能力矩阵九项独立能力及组件状态，不抬高平台支持 |
| 78 | 实现 ≠ 平台证明 | 2427 | 已核对；组件evidenced与平台原生V3 unverified分开 |
| 79 | Workstream G — Adapter 设计 | 2441 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 80 | Adapter 自报来源的限制 | 2471 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 81 | OpenClaw Hold Gate 不得退化 | 2491 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 82 | Intent Binding Revocation 不得退化 | 2506 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 83 | Workstream H — Enterprise Compatibility Preparation | 2522 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 84 | Issuer abstraction | 2548 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 85 | Workstream I — Security Testing | 2575 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 86 | Context Tests | 2712 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 87 | Hard Gate Tests | 2752 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 88 | Effect Tests | 2770 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 89 | Concurrency / Recovery | 2876 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 90 | Schema Tests | 2906 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 91 | Cross-language Vectors | 2929 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 92 | Security Boundary — Same UID | 2951 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 93 | Managed Linux 预留 | 2979 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 94 | Documentation | 3015 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 95 | ADR — Authority Hard Gate | 3031 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 96 | ADR — Provenance | 3055 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 97 | ADR — Effect | 3075 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 98 | README | 3095 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 99 | 工程结构建议 | 3113 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 100 | Receipt Engine 重构原则 | 3134 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 101 | 不允许出现 God Engine 进一步膨胀 | 3173 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 102 | CI | 3194 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 103 | 新 CI Job | 3227 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 104 | Benchmark 不允许阻塞每个 PR 的项目 | 3248 | 已实现smoke/full区别；nightly运行34188106080尚未完成 |
| 105 | CODEOWNERS | 3270 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 106 | 不直接修改 GitHub Branch Protection | 3299 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 107 | Commit Strategy | 3315 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 108 | Definition of Done — Authority | 3353 | 对应DoD均有基线限定证据；见验收索引，最终SHA仍待定 |
| 109 | Definition of Done — Provenance | 3385 | 对应DoD均有基线限定证据；见验收索引，最终SHA仍待定 |
| 110 | Definition of Done — RuntimeAction | 3435 | 对应DoD均有基线限定证据；见验收索引，最终SHA仍待定 |
| 111 | Definition of Done — Effect | 3455 | 对应DoD均有基线限定证据；见验收索引，最终SHA仍待定 |
| 112 | Definition of Done — Benchmark | 3491 | 对应DoD均有基线限定证据；见验收索引，最终SHA仍待定 |
| 113 | Definition of Done — Compatibility | 3531 | 对应DoD均有基线限定证据；见验收索引，最终SHA仍待定 |
| 114 | Definition of Done — Engineering | 3559 | 对应DoD均有基线限定证据；见验收索引，最终SHA仍待定 |
| 115 | 完成后必须输出 Engineering Report | 3587 | A–K草稿已落盘；最终SHA/CI/nightly与全节审计待定版 |
| 116 | 禁止使用的产品宣称 | 3780 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 117 | 可以使用的准确表述 | 3802 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 118 | 本轮完成后的目标架构 | 3814 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 119 | 最终安全模型 | 3868 | 待逐节复核；已有实现/测试入口见DoD索引 |
| 120 | 开始执行 | 3909 | 待逐节复核；已有实现/测试入口见DoD索引 |

后续按18–44、45–76、79–107、116–120分组核对具体字段、reason code、P/C/E测试、命令与交付物；发现缺口先修复，再更新对应状态。
