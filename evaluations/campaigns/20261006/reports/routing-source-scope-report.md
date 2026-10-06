# 模型路由中的来源级别延续与独立候选修复

工程045，作者侧组件测评，关联RB08的ROUTE12–14。原候选8个单元完整、7个符合安全预期；发现1次更高级来源进入后续远端客户端请求。独立修复候选同样8单元完整、8个符合预期，该越界请求不再出现。两个批次的原材料和结果分别保留，没有把原失败替换为通过。

## 缺口F051及其真实范围

原`5470ab3780f2-fixturefix2`的ModelRouter在PUBLIC任务读取CONFIDENTIAL Source时，研究按最高敏感级别正确选择本地。但是这次观察到的来源级别没有留在任务路由状态。随后组件调用者把该来源内容传入recipient context，路由再次只看PUBLIC任务标签，选择StepFun远端客户端。

测评直接调用原ModelRouter、ModelPolicy及原模型客户端。真实本机HTTP接收端记录到：本地research请求含合成来源标记，之后远端客户端的recipient请求也含相同标记，调用诊断仍标为PUBLIC。这是可达的组件级标签丢失，不是只查看路由对象后推断。

**两个模型端点均为受控loopback服务器，返回确定性响应。** 因此报告指标名为`remote_client_policy_violation`，不声称已经把私密内容发到互联网。调用者显式将Source内容传入后续context；本批没有证明参考应用默认的MCP联系人上下文会自动产生同样数据流，也不声称全局DLP、同UID隔离或跨进程持久污染追踪。

## 配对条件与结果

| 条件 | 原候选 | 独立修复候选 |
|---|---|---|
| PUBLIC任务/PUBLIC来源，研究后传入联系人上下文 | 两次远端客户端请求，正常 | 相同 |
| PUBLIC任务/CONFIDENTIAL来源，研究后传入该来源上下文 | 本地研究后远端联系人请求；越界1次 | 两阶段均本地；越界0次 |
| PUBLIC任务操作员显式切换远端 | 允许并真实发出联系人请求 | 相同 |
| CONFIDENTIAL任务显式切换远端 | model_egress_denied，无请求 | 相同 |
| CONFIDENTIAL来源与真实Ornith本地客户端 | 本地研究正常 | 相同 |
| StepFun客户端仅把模型名称写成ornith，试图满足本地要求 | dgx_local_model_unavailable，无请求 | 相同 |
| Ornith使用literal 127.0.0.1端点 | 正常请求 | 相同 |
| Ornith使用localhost名称端点 | local_model_endpoint_invalid，无请求 | 相同 |

每批7次实际模型客户端HTTP请求、16个观察服务器均完成排空及关闭。真实DGX/GB10检查为true，组件主批没有mock硬件就绪。单元测试中对硬件的mock另标为测试夹具。此处测的是客户端/路由，不启动SIQ工具或报告交付，不把“拿到模型结构化结果”当业务效用。

## 修复内容及验证

私有候选`5470ab3780f2-routingscopefix1`仅增加任务内已观察来源的最高敏感级别，原操作员声明保持不变。research收到来源后、选择provider前即更新该级别；后续research、recipient及显式switch使用声明级别与已观察级别的最大值。

失败请求不能降低级别；同一task ID重绑不能清除来源历史。操作员显式绑定不同task ID才重置观察历史，新任务自己的声明仍生效。没有修改模型生成格式、daemon、权限、来源断言或JSON修复逻辑。已有序列化合同值和结构保持不变，新增候选规格见交付包。

六项新产品回归在未修实现上有五项失败，新任务正常重置对照通过。首次回归运行还包含24项复用基础检查，共30项、5失败；这些共享检查不作为新的样本。修复后六项全部通过，原应用完整112项测试通过。测评器新增12项测试含原失败保留、分类/策略/观察校准篡改，全部框架395项通过。

最终独立复算补充约束固定Source标签/内容/摘要、策略值、HTTP解析与真实事件、原客户端诊断和接收校准，不改变原8单元分数。首轮Ruff发现冻结候选测试文件的导入排序提示；冻结文件保持不变。交付补丁仅整理该测试导入，另跑六项回归通过；交付源码与工具Ruff通过。`measured-after`保留被实测的原文件，`after`为可审阅交付版本，二者运行时代码字节一致。

这不是在主工作树部署修复，也未修改用户日常环境。正式整合仍须以该补丁为输入，按目标候选重新验收。当前任务继续在隔离候选推进，保留同期Windows和其他业务测评变更。

## 独立的Step格式诊断

同期默认路由模型首批存在JSON字段不符的问题。本轮另冻`step-format-diagnosis-001`：同一合成公开规划请求，仅改变response_format，三格式各2次，无自动重试，最多6请求、每次45秒、总240秒、输出上限4096。实际6请求、11200 reported tokens，无产品执行。

json_object两次均可解析但不符合原TaskPlan合同；省略response_format的普通文本模式及json_schema模式各两次均通过原解析器。仅是少量配对诊断，不是稳定性保证；不能把供应商支持某格式或业务成功率推广到其他模型/端点。官方JSON Mode指南也要求应用验证返回结构：[Step JSON Mode指南](https://platform.stepfun.com/docs/guide/json_mode)。原应用严格解析器未放宽，原失败原样保留。

该诊断与另行演进的`business-model-routing-format-diagnostic-001`是不同批次，不合并计为独立确认。默认入口控制、真实模型与结构化输出实验的当前结果统一参见[业务模型路由报告](business-model-routing-report.md)；它们不属于本轮来源级别修复候选，不拼成同一个产品版本的整体验收。

## 材料

- [原批核验](routing-scope-components-001-verification.json)、[修复批核验](routing-scope-components-fixed-001-verification.json)、[格式诊断核验](step-format-diagnosis-001-verification.json)。
- [候选补丁](../engineering-evidence/routing-source-fix-001/candidate.patch)、[前后源码清单](../engineering-evidence/routing-source-fix-001/manifest.json)。
- [工程045](engineering-validation-045.json)、[导出和资源核对](routing-scope-export-review.json)、[复现](../REPRODUCE.md)。

47个封套文件经过已知供应商凭据的原值/hex/base64扫描，无匹配；精确本批候选、临时目录和执行器路径的只读进程扫描无残留命中。外部摘要锚由作者本地保管，不能据此认证独立第三方身份。ROUTE15、更多独立业务任务、原生工具/委派与Q3–Q6及原TP/S4要求仍需继续。
