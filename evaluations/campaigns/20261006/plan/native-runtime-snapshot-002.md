# 运行自检快照与业务授权状态：修订预注册002

保留[001](native-runtime-snapshot-001.md)的8个独立实例变体、两次实际自检、候选与范围。001 workspace-control首试41/41；001 skill-content首试40/41，其真实状态明确揭示原假设遗漏：修改业务Skill字节时旧自检passed不变，但身份为grant_unavailable、instance_authority=fail，恢复字节后身份可用、授权诊断pass。原错误断言与原退出1保留。

源码 runtimeidentity/summary.go 每次通过 GrantForReference 重验当前Grant及来源文件，server/adapter_diagnostics.go 将不可用身份单独报告失败；自检快照则不纳入业务Skill内容。这是预期的范围分离，不能把旧自检passed解释为忽略内容漂移，也不能在恢复内容后宣称重新批准了权限。

002在执行前调整：skill-content的授权诊断期望为pass→fail→pass，其他预期保持；新增身份读回，要求issued→grant_unavailable→issued。业务Grant本路径初始实际状态是approved，撤销后revoked；不将尚未部署的Grant写成deployed。business-grant期望issued→grant_unavailable并保持；business-identity期望issued→revoked并保持。均与独立自检passed分开。

全8格以002新ID冻结运行，每格原27项业务前置加15项快照检查；同一个既有任务块，不增加独立业务或攻击分母。旧001数据及核验保留，不并入002通过率。产品、宿主及正常业务权限不改；仅修订测评假设和采集字段。冻结增加runtimeidentity源码摘要。
