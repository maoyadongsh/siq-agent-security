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
| 18 | Workstream B — Parameter-Level Provenance | 741 | 已核对；独立provenance包、Assertion/Issuer合同、taxonomy/trust与管理分权；P1–P3及固定向量 |
| 19 | Provenance 基本模型 | 772 | 已核对；独立provenance包、Assertion/Issuer合同、taxonomy/trust与管理分权；P1–P3及固定向量 |
| 20 | Source Type | 819 | 已核对；独立provenance包、Assertion/Issuer合同、taxonomy/trust与管理分权；P1–P3及固定向量 |
| 21 | Trust Level | 846 | 已核对；独立provenance包、Assertion/Issuer合同、taxonomy/trust与管理分权；P1–P3及固定向量 |
| 22 | 谁可以签什么 Trust | 875 | 已核对；独立provenance包、Assertion/Issuer合同、taxonomy/trust与管理分权；P1–P3及固定向量 |
| 23 | Trusted Provenance Issuer Registry | 914 | 已核对；独立provenance包、Assertion/Issuer合同、taxonomy/trust与管理分权；P1–P3及固定向量 |
| 24 | Provenance 不能证明内容为真 | 948 | 已核对；独立provenance包、Assertion/Issuer合同、taxonomy/trust与管理分权；P1–P3及固定向量 |
| 25 | Parameter Provenance Binding | 974 | 已核对；parameter-provenance、matcher、V3双读、required/minimum_trust/source约束；P4–P6 |
| 26 | Parameter Provenance Resolution | 1015 | 已核对；parameter-provenance、matcher、V3双读、required/minimum_trust/source约束；P4–P6 |
| 27 | IntentContract V3 | 1054 | 已核对；parameter-provenance、matcher、V3双读、required/minimum_trust/source约束；P4–P6 |
| 28 | Provenance Constraint | 1089 | 已核对；parameter-provenance、matcher、V3双读、required/minimum_trust/source约束；P4–P6 |
| 29 | High-Impact Parameter | 1103 | 已核对；Describe高影响字段全表、统一语义与解释器unknown；R1–R4 |
| 30 | RuntimeActionDescriptor 重构 | 1140 | 已核对；Describe高影响字段全表、统一语义与解释器unknown；R1–R4 |
| 31 | 所有安全模块消费同一个 Descriptor | 1179 | 已核对；Describe高影响字段全表、统一语义与解释器unknown；R1–R4 |
| 32 | Shell 仍保持 Conservative | 1204 | 已核对；Describe高影响字段全表、统一语义与解释器unknown；R1–R4 |
| 33 | Workstream B2 — MCP Provenance MVP | 1230 | 已核对；实际MCP report/select/Hermes显式桥接、默认untrusted与派生枚举；P7/P8 |
| 34 | MCP Provenance 生命周期 | 1242 | 已核对；实际MCP report/select/Hermes显式桥接、默认untrusted与派生枚举；P7/P8 |
| 35 | MCP 默认规则 | 1266 | 已核对；实际MCP report/select/Hermes显式桥接、默认untrusted与派生枚举；P7/P8 |
| 36 | 不做完整语义传播 | 1290 | 已核对；实际MCP report/select/Hermes显式桥接、默认untrusted与派生枚举；P7/P8 |
| 37 | Derivation | 1316 | 已核对；实际MCP report/select/Hermes显式桥接、默认untrusted与派生枚举；P7/P8 |
| 38 | Security Rule — Untrusted High-Impact Control | 1337 | 已核对；同值USER/MCP、默认高影响约束及十项reason code；P9/P10与provenance实现 |
| 39 | 示例 | 1352 | 已核对；同值USER/MCP、默认高影响约束及十项reason code；P9/P10与provenance实现 |
| 40 | 同值不同来源测试 | 1393 | 已核对；同值USER/MCP、默认高影响约束及十项reason code；P9/P10与provenance实现 |
| 41 | Provenance reason codes | 1427 | 已核对；同值USER/MCP、默认高影响约束及十项reason code；P9/P10与provenance实现 |
| 42 | Provenance 容量 | 1446 | 已核对；1024节点/4096边/32父/64深度，容量失败关闭、不可变摘要存储；G3与恢复测试 |
| 43 | Provenance 容量耗尽 | 1469 | 已核对；1024节点/4096边/32父/64深度，容量失败关闭、不可变摘要存储；G3与恢复测试 |
| 44 | Provenance 存储 | 1489 | 已核对；1024节点/4096边/32父/64深度，容量失败关闭、不可变摘要存储；G3与恢复测试 |
| 45 | Workstream C — EffectEvidence V1 | 1511 | 已核对；Effect独立合同、五维冻结枚举与tool_report限制；E1/E3及合同矩阵 |
| 46 | EffectEvidence Schema | 1535 | 已核对；Effect独立合同、五维冻结枚举与tool_report限制；E1/E3及合同矩阵 |
| 47 | 不设计单一“安全等级” | 1581 | 已核对；Effect独立合同、五维冻结枚举与tool_report限制；E1/E3及合同矩阵 |
| 48 | execution_state | 1607 | 已核对；Effect独立合同、五维冻结枚举与tool_report限制；E1/E3及合同矩阵 |
| 49 | source_type | 1621 | 已核对；Effect独立合同、五维冻结枚举与tool_report限制；E1/E3及合同矩阵 |
| 50 | independence | 1636 | 已核对；Effect独立合同、五维冻结枚举与tool_report限制；E1/E3及合同矩阵 |
| 51 | coverage | 1647 | 已核对；Effect独立合同、五维冻结枚举与tool_report限制；E1/E3及合同矩阵 |
| 52 | result | 1657 | 已核对；Effect独立合同、五维冻结枚举与tool_report限制；E1/E3及合同矩阵 |
| 53 | Tool Result 只产生 Observation | 1668 | 已核对；Effect独立合同、五维冻结枚举与tool_report限制；E1/E3及合同矩阵 |
| 54 | EffectEvidence API | 1696 | 已核对；独立capEffectObserve与管理/decision分权；E2原始HTTP测试 |
| 55 | Effect Observer Capability | 1718 | 已核对；独立capEffectObserve与管理/decision分权；E2原始HTTP测试 |
| 56 | File Effect MVP | 1747 | 已核对；真实文件/网络oracle、重定向、假成功及deny incident；E4–E7与nightly full |
| 57 | Network Effect MVP | 1786 | 已核对；真实文件/网络oracle、重定向、假成功及deny incident；E4–E7与nightly full |
| 58 | Network 重定向测试 | 1823 | 已核对；真实文件/网络oracle、重定向、假成功及deny incident；E4–E7与nightly full |
| 59 | Fake Tool Success | 1842 | 已核对；真实文件/网络oracle、重定向、假成功及deny incident；E4–E7与nightly full |
| 60 | EffectEvidence 与 Receipt 链 | 1872 | 已核对；真实文件/网络oracle、重定向、假成功及deny incident；E4–E7与nightly full |
| 61 | Completion 不在本轮完全实现 | 1917 | 已核对；只读Completion、四状态、无要求not_required及材料匹配；E8 |
| 62 | CompletionStatus API | 1938 | 已核对；只读Completion、四状态、无要求not_required及材料匹配；E8 |
| 63 | CompletionStatus 第一版规则 | 1965 | 已核对；只读Completion、四状态、无要求not_required及材料匹配；E8 |
| 64 | Workstream D — Runtime Security Benchmark V1 | 1999 | 已核对；独立成对语料、18类必需攻击、九指标及D0–D5分母；B1–B6 |
| 65 | Benchmark Endpoint Model | 2019 | 已核对；独立成对语料、18类必需攻击、九指标及D0–D5分母；B1–B6 |
| 66 | Benchmark Scenario Contract | 2045 | 已核对；独立成对语料、18类必需攻击、九指标及D0–D5分母；B1–B6 |
| 67 | Benchmark 必须覆盖的攻击 | 2073 | 已核对；独立成对语料、18类必需攻击、九指标及D0–D5分母；B1–B6 |
| 68 | Benign Controls | 2117 | 已核对；独立成对语料、18类必需攻击、九指标及D0–D5分母；B1–B6 |
| 69 | Benchmark Metrics | 2141 | 已核对；独立成对语料、18类必需攻击、九指标及D0–D5分母；B1–B6 |
| 70 | 不得错误计算 ASR | 2169 | 已核对；独立成对语料、18类必需攻击、九指标及D0–D5分母；B1–B6 |
| 71 | Performance Metrics | 2195 | 已核对；八阶段实测百分位，额外完整Decide；报告H及原始样本 |
| 72 | Workstream E — Threat Model | 2222 | 已核对；T27–T35控制/负例/残余风险；最低父trust与unknown传播；P8/P10 |
| 73 | Provenance Laundering Threat | 2263 | 已核对；T27–T35控制/负例/残余风险；最低父trust与unknown传播；P8/P10 |
| 74 | Aggregation Rule | 2297 | 已核对；T27–T35控制/负例/残余风险；最低父trust与unknown传播；P8/P10 |
| 75 | Transformation Rule | 2333 | 已核对；T27–T35控制/负例/残余风险；最低父trust与unknown传播；P8/P10 |
| 76 | UNKNOWN Rule | 2357 | 已核对；T27–T35控制/负例/残余风险；最低父trust与unknown传播；P8/P10 |
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
| 91 | Cross-language Vectors | 2929 | 已补齐并核验；三类合同共用固定canonical bytes/摘要/签名，Go race与Python通过 |
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
| 104 | Benchmark 不允许阻塞每个 PR 的项目 | 3248 | 已核对；smoke/full不同语料；nightly 34188106080三次完整运行success |
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

### §18–44细项核验补充

核读原文每节并对应types/authority/store/graph/matcher/report/select/defaults及runtimeaction Describe。§41十个reason code均存在生产分支；缺失/非法引用不会成为可信来源。§44仅持久化内容摘要、父引用、作用域及签名，HTTP接收原文用于当次摘要/选择，不将MCP raw result长期写入provenance Store。

§42原文数值为候选工程默认，实际按完整scope（含task/session/agent/platform）图限制；issuer另有4096容量。不宣称全系统磁盘配额。§34以实际HTTP MCP初始化/工具调用和确定性选择验收，不扩展为所有宿主自动追踪。

nightly证据见[evidence](evidence/provenance-v1/nightly-693641d-20260908.json)：693641d三次full均success，第一份下载产物本地再次验证51回执/11效果及完整文件恢复链通过。其他两份以远端job结果为证据，不声称均已本地下载验签。

### §45–76细项核验补充

核读全部原文条目并与Effect schema、server auth、Correlation、Completion、文件/网络夹具及metrics实现对应。五类冻结枚举逐一比对相等；推荐样例中的independence=independent没有被照抄，采用§50正式枚举。Threat Model T27–T35的19个测试名称逐个核对到相邻源码链接。

§58真实302从localhost授权入口跳到127.0.0.1另一接收端，区分requested endpoint和服务端received event；受控loopback不等于通用公网拦截。§59假成功保持tool_result自报，实际after不存在导致Completion incomplete；工具自报不升级independence。§60独立完成效果若动作未授权，Correlation转换unexpected并产生unauthorized_effect_observed。

§69九项命名指标与D0–D5阶段结果分别报告，分母由适用样本决定；D0/D1没有观测时null。§70离线验证器禁止无归档效果/材料的D5声明，缺oracle不当失败。既有nightly三次full与第一份本地重验提供运行证据；此次文档核对未宣称重新执行全部夹具。

§73–76普通转换不能提高父trust，混合聚合不得用最高trust覆盖最低trust；unknown父不变成已知转换，关键参数缺引用拒绝。低影响参数仍由已签名Intent决定，不能由模型自报可信。

### §91固定向量补强

Context和Effect原有签名样例可用于跨语言验签，但未单独冻结canonical bytes/unsigned SHA256。现增加对应.vector.json，与Provenance既有向量由internal/contractvectors和test_authority_effect_vectors.py统一读取。Go通过三个生产Unsigned投影与既有canon/signing复核，Python独立编码、hash、验签及确定性签名复核；样例签名与生产合同不变。公用seed仅测试材料。
