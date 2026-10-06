# 结果状态与当前文案精确绑定：浏览器协议003

保留原001未展开导航及002旧文案假设两次未完成首试。002锚36d17ac0a9c36b6fce69d6798d47c6d0654ddf50ac93c1fa1fd7cb7ee5dfa473，实际接入、自检通过、五条回执与活动API均已到达，后续浏览器流程未执行，不能记为完整通过。

002期待旧开发smoke中的“效果仍未知”；固定候选resultPresentation.ts及其测试明确将unknown/not_required展示为“未设置结果核验”，并说明“此任务未定义可核验的结果要求”“当前调用记录不能证明任务完成”。真实security-view返回同任务unknown/not_required，页面与合同一致。这不是产品把自检冒充业务结果通过。

本批保持[原001](personal-runtime-browser-001.md)的业务范围、36谓词、正常/失效/取消/卸载及候选，继承[002导航修正](personal-runtime-browser-navigation-002.md)，只将结果判据改为精确API状态/理由＋三句对应UI文案同时匹配，并检查同一activity binding与snapshot。不同unknown理由不可仅因含“未知”而通过。

002冻结离线核验器另在未到达activity_detail时抛KeyError，原错误日志保留。本批未来核验允许缺失未执行阶段，但不给完整通过；已捕获阶段仍验签和绑定。旧002用独立补充工具复核，不改其原协议、分数或unknown。

这是测评器导航/当前展示合同适配，不改SIQ/Hermes或生产页面。所有原失败保留，新增同一任务块，不扩充自然攻击或S4分母。
