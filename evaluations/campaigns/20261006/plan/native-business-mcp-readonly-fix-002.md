# 业务 MCP 读回：SDK 2 注解兼容修复候选

初批native-business-mcp-readback-001已结束，4项完整、1项符合预期、3项失败，锚51b0bb228632886a451c761ec10116e4183e9affc43981893a193d55ae34ee68。原MCP服务tools/list明确readOnlyHint=true；当前Hermes只读SDK 1对象字段readOnlyHint，而SDK 2对象属性为read_only_hint，导致合法读回被宿主误判写操作并拒绝。正确资源B2的SIQ决定为allow，错误资源为grant_scope_violation。mapped正常组产生的来源断言绑定的是宿主错误结果，不是实际报告读回；原失败不改分。

新批native-business-mcp-readonly-fix-002保留初批四条件、业务服务与镜像、SDK、SIQ候选、默认延迟工具机制、untrusted信任层、资源范围、预算和业务评分。仅更换隔离Hermes候选：旧字段存在时保留旧值优先，否则读取SDK 2字段，最终仍要求值严格为True。没有改成信任所有MCP、关闭宿主审批或删除SIQ检查。

隔离宿主完整源码从原工作树实际Python源及固定Git版本复制，另有可复核差异；原活动宿主不改。新CLI从候选根加载原公共main，仍使用原Python依赖和本批隔离SDK。新增只读公共hook观察器记录实际加载的MCP模块路径/摘要，以及目标工具真实post结果，确保候选生效并将来源摘要绑定到真实结果。观察器不裁决、不上报来源、不签发权限。

17项聚焦宿主测试使用其官方scripts/run_tests.sh：修复前真实复现1失败/16通过，修复后17通过；原runner缺pytest的预检日志也保留，测试依赖另装私有环境，未修改活动venv。完整原生业务是否恢复仍以新批实际MCP请求、报告内容和签名材料为准，不能由单测推定。

主测量继续执行[原预注册](native-business-mcp-readback-001.md)；来源捕获仅证明MCP/untrusted内容、身份和摘要，不证明select/derive、自动参数来源或业务审批完成。独立第三方与总体任务状态不升级。
