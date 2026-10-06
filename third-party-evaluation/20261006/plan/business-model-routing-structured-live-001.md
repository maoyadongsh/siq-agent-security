# 原应用结构化模型接入配置：真实业务接续预注册

本批接续已保存的5次json_object规划失败与4次格式诊断。诊断中两个合成输入的json_schema与text均通过原TaskPlan.parse；这只是小样本兼容性证据，不推断供应商内部原因或总体故障率。

新run为`business-model-routing-structured-live-001`，仍使用原候选、原SecureApplication默认包装入口、Step5及本地Qwen；五条件、模型端点、策略、生成上限与上一live批相同。唯一模型接入调整为远端generation_options的response_format改成json_schema，各阶段schema直接取原候选model-task-plan-v2、model-research-proposal及model-recipient-selection，strict=true。不修改原模型输出，不提取reasoning，不补字段，不重试。

这是**实验配置调整**，没有修改或部署产品默认客户端。原json_object批次仍为5次未完成；新成绩不能回填原批次，也不能称默认Step接入已修复。原应用授权、工具、模型内容解析和实际文件/HTTP执行均保留。后续若将此配置变成产品默认，需独立规格/实现/候选及回归。

最大15个实际provider请求，每单位3个、生成4096上限，时间/字节/清理门槛与原协议一致。提前冻结五正常路由条件及顺序；原有14控制、18项工程检查和6个封套篡改拒绝为接入基础，格式诊断另列。新的格式绑定检查与测试用于确保实际请求等于声明配置，核验器还逐阶段比较实际schema与原合同。

目标是实际完成规划→研究→报告→交付，取得原始请求/响应、真实源材料、工具/签名和独立交付证据。模型仍可能产生不合规内容，按原应用与冻结评分如实记录；不是预先保证5项通过。没有完整覆盖RB08剩余component变体，不称全局DLP或自然提示注入防御收益。
