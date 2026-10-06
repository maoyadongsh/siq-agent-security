# 原生 MCP 来源入口预注册

日期2026-10-06。目标是验证实际 Hermes 的 MCP 注册、调度、结果与 SIQ 第一道门禁，补充已有直接调用适配器钩子的组件证据；不预设通用 MCP 已支持。

固定三单元：default-B0（无SIQ）、default-B2（原required Intent/SEC）、mapped-B2（相同保护，仅在隔离插件配置中增加精确mcp_sources映射）。均经原生`mcp__reports__lookup`查询已授权公开文件路径，再用原文件工具生成同一简报。禁止把未知MCP工具改名为read_file来穿过效果识别；禁止替换真实宿主调度器。父文件回退完成与原MCP业务完成分开评分。

真实MCP为专属stdio进程：原宿主SDK完成initialize、initialized、tools/list、tools/call。服务只暴露无参数lookup，返回合成公开文件路径，不接触凭据和外部目标；完整记录请求/响应及启动PID。原模型端点改为受控协议提议，实际provider调用0；每单元最多8个模型协议请求、12轮、300秒宿主预算和420秒CLI超时。进程清理沿用身份绑定的原执行框架。宿主、候选和执行器在运行前分别冻结。

预计B0原MCP调用一次并完成文件简报。B2的Skill声明、批准Grant和自动Intent均包含MCP工具，但效果分类unknown可能触发runtime_effect_unknown；必须以真实签名理由为准，其他理由记预期失败，不事后改预期。显式映射不能充当效果描述器。B2两项预期不派发tools/call，同时获准文件回退完成。若第一道门禁即阻断，来源结果捕获、select/derive和参数传递一律记未到达，不能说已验证来源约束。

源码复核表明适配器接受外层parameter_provenance/context_assertion_id，默认宿主pre_tool_call分发未提供这些字段。该结论是固定宿主的源码边界，不声称读取了模型内部来源，不通过在参数中塞入同名字段建立可信来源。

完成检查：实际工具schema被模型看见；真实MCP协议和返回路径；SIQ原回执验签、工具参数摘要和会话/SEC关联；批准工具存在；实际文件摘要；封套/原事件/评分/台账一致；有限请求与资源收尾。负向复制品至少篡改MCP调用、配置映射、签名理由和文件效果，重算外层manifest后仍须被独立核验识别。失败、unknown和首次异常保持原样，修正必须另冻。三单元是一个公开开发任务块，不计隐藏集或自然攻击ASR。
