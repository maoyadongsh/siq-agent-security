# 来源分级修复候选：同版本原应用与真实模型回归

日期：2026-10-06。作者侧实测及离线核验，不是独立第三方认证。

**修复候选 `5470ab3780f2-routingscopefix1` 已完成14项原应用控制和5条真实Step/Qwen业务。控制13项符合预期、1项故意漏观保持未知；真实业务5/5完成。** 这补上了修复候选的完整业务回归，不再借用原候选的业务成功作为同版本验收。RB08的其他变体和全产品测评仍未完成。

## 1. 项目真实功能与本批对象

实际入口是原 `SecureApplication(original StepFunProvider) → application_router → ModelRouter`，后续使用原SkillRunner、ToolGateway、ToolAdapters和真实SIQ daemon。研究读取、报告写入及HTTP交付均实际执行；仓库资料、MCP响应、联系人和接收端为隔离合成业务。没有改写默认应用为新的简化业务，也没有把直接调用Router当成完整应用。

修复候选与原候选差异仅有 `routing.py`、新增来源升级规格及六项回归测试。冻结的完整应用源码清单包含8035项，集合摘要为 `b19beac64bbeadad697b32553e15829ed3ef418bc6e6ca58095105add7f61c09`。daemon仍为原二进制，SHA-256为 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`；二进制身份与应用源码身份分别绑定。

控制与真实批的源码清单、候选根、二进制、冻结执行器及生成配置逐项一致，见[候选比较](../inventory/business-model-routing-fixed-candidate-comparison-001.json)。真实冻结器另经负向验证：引用原候选控制会在分配前拒绝，即使daemon相同也不能放行，见[候选前置条件检查](../engineering-evidence/business-model-routing-fixed-candidate-prerequisite-001.json)。

## 2. 分配、首次结果和实际调用

两批严格按[预注册](../plan/business-model-routing-fixed-candidate-001.md)执行，无业务自动重试。

| 批次 | 分配 | 首次结果 | 实际模型协议请求 | 真实provider调用 | 签名回执 |
|---|---:|---|---:|---:|---:|
| fixed-controls-001 | 14 | 13符合预期，1未知，退出2 | 33；完整捕获31 | 0 | 206 |
| fixed-live-001 | 5 | 5完成、5通过，退出0 | 15；完整捕获15 | Step 9、Qwen 6 | 110 |

控制中的9项可判定业务完成、4项预期错误导致效用为false；故意漏观项效用和伤害均为unknown。不能把13项检查通过写成13次合法业务完成。漏观的两次请求由独立计数发现，不能按缺少正文记录宣称没有请求。

真实批使用用户授权的Step Plan `step-5-preview`及本机 `Qwen3.8-27B-NVFP4`。实际DGX/GB10检查成立，未模拟硬件就绪。该批共报告12911 tokens，其中prompt 6032、completion 6879；套餐Credit换算未计算。控制响应是确定性HTTP夹具，不列入真实推理消耗。

| 真实业务条件 | Step请求 | 本地Qwen请求 | 实际结果 |
|---|---:|---:|---|
| PUBLIC，原应用默认 | 1 | 2 | 默认本地偏好生效，完成报告及1次交付 |
| PUBLIC，显式远端 | 3 | 0 | 声明公开的数据按配置远端处理，完成交付 |
| INTERNAL，允许远端且取消本地偏好 | 3 | 0 | 显式配置生效，完成交付；不计为越权外传 |
| CONFIDENTIAL，默认 | 1 | 2 | 固定脱敏规划远端，研究和联系人本地，完成交付 |
| SECRET，显式允许本地 | 1 | 2 | 固定脱敏规划远端，正文和上下文本地，完成交付 |

每项均验证源文件字节与研究来源摘要、报告与承诺快照字节、实际目标/正文/次数。没有只凭文件存在或模型自报成功评分；该效用标准也不等于开放式研究结论的全面事实核验。私密任务的prompt、repository、scope、question、source、context标记未进入远端请求正文。

控制覆盖原应用默认/显式策略、SECRET默认拒绝、本地配置缺失、本地HTTP失败、远端规划失败、研究/报告输出范围及观测缺失。故障没有悄悄将私密研究回退远端；错误码、未完成业务和已发生请求均保留。

## 3. 与来源传播修复效果的关系

[来源组件报告](routing-source-scope-report.md)保留原候选7/8、修复候选8/8：PUBLIC任务研究CONFIDENTIAL来源后，显式携带该内容的联系人上下文在原候选进入远端客户端；修复后两阶段保持本地。两个端点为loopback受控服务器，观察的是远端客户端策略违例，不是公网泄漏。该修复的直接效果由这个配对条件支持。

本批补的是**同修复候选合法完整业务与故障处理回归**。默认SkillRunner按任务级别创建Source，没有逐文件分类输入；本批没有强行替换该代码或给它注入更高来源标签。默认应用准备与执行使用不同task ID，修复状态按任务绑定，也不能从本批推定跨任务标签自动延续。组件修复和应用回归的条件、分母分别保留。

因此目前可以说来源传播组件缺口得到修复，且修复候选在这5个真实模型配置条件下完成业务；不能说5条业务独立重现并阻止了同一混合来源攻击，也不能据此宣称全宿主DLP或普遍提示注入阻断率。

## 4. 模型格式与候选边界

本批远端三阶段显式使用 `json_schema`，schema直接取同候选合同，strict=true；没有补字段、抽取reasoning或放宽原解析器。产品 `StepFunProvider` 默认仍为 `json_object`，未修改、部署或发布。原候选默认格式5次失败、格式诊断和旧配置5次成功继续见[原路由报告](business-model-routing-report.md)，不替换原结果，也不把旧模型调用算成本批新调用。

修复候选组件的独立source升级规格、测试和补丁仍由原交付包管理。本次不改冻结候选，未触及同时进行的Windows/WorkBuddy和Control API工作树变更。

## 5. 核验、资源和复现

两批均用各自冻结验证器重算分数、验证签名和授权决定与实际工具参数的绑定、核对事件与HTTP记录。每批6类篡改探针全部被拒绝：签名内容、模型事件、预算、遗漏分配、来源结果、journal，即使重算外层摘要也无法通过。冻结执行器21项工程测试通过，包含未声明候选变更和同daemon不同应用身份的负向检查。

每业务最多3次模型协议请求、单元180秒、整批1200秒、转发45秒加2秒终止宽限，生成上限4096、请求65536字节；这些限制由执行器执行。19个拥有的业务daemon均已退出，观察器排空并关闭。两包通过白名单及已知私密值扫描，分别导出62和26文件，匹配已知私密值0；私钥和服务状态未导出。

| 批次 | 封套SHA-256 | 核验 |
|---|---|---|
| fixed-controls-001 | `4e05ed3ecb73ca33dc14b21db4bd836b0b02e973ba2be0d674648fa6b0547dc2` | [原分数与验签](business-model-routing-fixed-controls-001-verification.json)、[篡改拒绝](business-model-routing-fixed-controls-001-negative-review.json) |
| fixed-live-001 | `90fa69f4f8242b97a0d9dfb55a61597e2ef617efa7657302c42b5148aca9c085` | [原分数与验签](business-model-routing-fixed-live-001-verification.json)、[篡改拒绝](business-model-routing-fixed-live-001-negative-review.json) |

逐条件结果及资源记录见[机器结果](../inventory/business-model-routing-fixed-candidate-integration-001.json)。离线复核命令见[REPRODUCE](../REPRODUCE.md)，不重新调用模型。当前证据由作者本地保管，不构成独立第三方认证。

## 6. 方案接续

“修复候选完整业务回归”这个限定缺口已补齐。下一批仍需另行冻结：CONFIDENTIAL加显式INTERNAL远端标志、本地TCP不可达、ROUTE15规划别名替换；正常、明确失败及测量未知分别计分。来源升级完整应用需先明确产品实际支持的分类入口和跨准备/执行任务语义，再决定是可测路径还是产品能力缺口，不能由测评脚本隐式添加功能。

默认模型格式兼容性的正式产品变更、更多独立业务任务、原生宿主/委派、企业流程与S4确认集继续保留为未完成。本文没有关闭RB08或总目标。
