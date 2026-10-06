# 原生业务来源的字段选择与参数入口预注册

一项真实 mapped-B2 业务读回，沿用 readonly-fix-002 的隔离 Hermes 候选、原业务服务、SDK、只读固定根、精确授权和确定性提议。新增读取型观察 hook，只记录原业务调用与摘要写入时 pre_tool_call 的字段名和来源参数是否存在；不修改调用、不上报来源、不签发权限。

任务正常读回并写摘要后，在该专有 daemon 停止前，用管理 API 对本次真实来源断言执行五项诊断。它们是测评者显式的组件诊断，不是宿主自动选择／传播，不增加业务样本数。

| 诊断 | 请求内容 | 预期 HTTP／结果 |
| --- | --- | --- |
| resolve-parent | 原来源 ID 和实际运行 scope | 200，返回相同签名断言 |
| original-field | 原 post hook 字符串，pointer=/structuredContent/report_key | 400，provenance_missing |
| parsed-object | 将同一字符串解析成对象，同一 parent 与 pointer | 400，provenance_content_mismatch |
| mutated-string | 原字符串追加一个空格，同一 parent 与 pointer | 400，provenance_content_mismatch |
| original-root | 原字符串，pointer为空字符串 | 400，provenance_missing（现合同选择器不支持根指针） |

这些预期来自固定候选的 Select、PointerValue、ContentDigest 和实际捕获类型。保留真实 HTTP 状态及响应；任何偏离必须报告，不能改原协议或按预期填数。解析后对象仅作为负向请求，不调用 provenance-reports 创建替代父来源。实际来源仍是 daemon 从原 post hook 签发的 MCP/untrusted，签名、内容摘要、作用域和真实报告 key 均需独立复核。

业务成功只按原 MCP 请求、原服务内容、独立文件摘要和清理评分。字段选择能力单列：没有有效选定断言即为不可用；五项诊断符合预期不等于来源链成功。pre hook 未携带来源参数仅说明此默认路径没有自动传播；不以自动 Intent v2 下的合法写入证明绕过 v3 来源约束。下游受约束参数实测本批未到达。

本批仍是一块既有开发业务，最多8个受控模型协议请求、12轮、300秒宿主预算、420秒CLI超时；0真实模型推理。只增加上述五项本地API诊断。清理仍按明确进程身份及专属容器ID执行；观察失败记unknown。协议、选择相关合同、原生调用方和测评源码在运行前冻结；原001/002数据不改。
