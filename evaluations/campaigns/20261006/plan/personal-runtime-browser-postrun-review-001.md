# 浏览器003执行后的补充证据核验

这是执行后发现核验器接口假设错误而增加的复核，不冒充运行前注册。原003协议、数据、36项分数与原核验器全文比较失败日志均保留。

固定候选的 `packages/contracts/local-task-activity-detail.v1.schema.json` 与 `apps/agentshield/internal/server/task_activity_detail.go` 定义活动回执的14字段摘要。回执摘要无完整签名与任务字段；这些字段必须从原始签名链独立验证，不能因API未返回而推测。

补充工具先对全链验签，再核对活动摘要与指定五条原始回执的14字段有序投影。仅 decision_receipt_id 在原始决定记录省略时按Go零值空串映射，其余字段严格匹配；随后对内存副本运行原冻结核验的所有其他检查。源文件不修改。

负例包括签名修订、活动任务、借用回执、错误unknown理由、伪造已验证文案、恢复旧pass、重复启动、摘要动作与摘要次序九类；它们是离线证据核验负例，不是九次真实攻击。补充工具及所据合同摘要冻结于 `engineering-evidence/personal-runtime-browser-review-tools-001/review-manifest.json`。

框架全目录采集曾因独立upstream_tests需要AgentDojo专用环境而失败，保留日志002。框架回归显式排除该独立目录；不将未执行的上游套件算入框架通过数。
