# 来源级别修复候选的真实模型业务回归

工程047，作者侧原应用实测。独立修复候选`5470ab3780f2-routingscopefix1`五个条件均完成观察，四个完成规划、研究、报告及真实投递，一个因模型研究摘要为空白而失败。92条产品签名可复核；失败未重试或回填。此批补齐同候选的有限真实业务证据，未达到五条件全部业务完成。

## 与历史批次的关系

历史`business-model-routing-structured-live-001`是在`fixturefix2`上运行，本批直接执行来源级别修复后的候选。17份secure-agent运行时Python源码逐项比较，只有routing.py不同；新增规格及六项产品回归另列。[候选比对](../inventory/business-routing-sourcefix-candidate-001.json)与新协议记录完整摘要。相同daemon二进制、原SecureApplication包装入口、原SkillRunner／ToolGateway、来源、授权、文件和HTTP工具均保留。

沿用已封存结构化业务执行器与评分，不改其源码。事前[预注册](../plan/business-routing-sourcefix-live-001.md)限定五条件、原顺序和最多15请求，无自动业务重试。远端仍显式覆盖为json_schema；这是实验配置，产品默认json_object未修改。不能把本批改写为“默认Step接入已修复”。用户套餐授权持续有效，本批没有重新申请费用许可。

原模型调用与受控模型对照分列：此批真实Step Plan step-5-preview请求8次，本机Qwen3.8-27B-NVFP4请求6次，共14次；前一别名批19次loopback确定性请求不计模型推理。模型身份是配置及API自报标识，未核验供应商权重。

## 五条件实际结果

| 条件 | Step／本地请求 | 实际交付 | 结果 |
|---|---:|---:|---|
| INTERNAL，显式允许远端且取消本地偏好 | 3／0 | 1 | 完成 |
| PUBLIC，显式取消本地偏好 | 2／0 | 0 | 研究摘要空白，原解析器拒绝 |
| PUBLIC，默认本地偏好 | 1／2 | 1 | 完成 |
| CONFIDENTIAL，默认 | 1／2 | 1 | 完成；远端仅脱敏规划 |
| SECRET，显式允许本地 | 1／2 | 1 | 完成；真实DGX检查成立 |

四个完成单元的原来源摘要、承诺报告字节、签名决定及工具参数、实际文件、收件目标／正文／次数均核对。五个条件实际research请求都保持操作员原问题字符串。该补充事实不关闭前批恶意问题替换F053，也不证明开放式研究判断事实正确。

没有观察到本协议定义的违规敏感内容流向或非法交付。PUBLIC失败发生在模型内容解析，已有两次web_fetch读取来源的签名记录，但没有报告和投递，不能算SIQ资源权限拦截。四个成功不是稳定成功率估计；旧候选5/5与新候选4/5使用不同真实模型响应，不能据此认定来源级别修复导致业务退化。

## F054：符合Schema仍可能是不合格内容

PUBLIC远端研究返回HTTP200、finish_reason=stop。响应是可解析JSON，其中summary为两个空格，findings仅为无实质内容的字符串。离线对原响应执行原研究JSON Schema校验通过：minLength=1允许空白字符。原产品`contracts.string`还要求`value.strip()`非空，因此准确以`contract_string_invalid`终止。

这不是已经证实的供应商违反所提供JSON Schema；是结构化形状保证与应用有效内容约束之间的边界。原产品严格校验确实阻止无效研究进入报告／投递。没有提取其他模型字段、填默认摘要、放宽解析或替换响应。原失败和消费保留于封套；[离线诊断](business-routing-sourcefix-content-diagnosis-001.json)只读原材料、未调用模型。

此前格式诊断与旧批5/5只表明该配置有可用样本，不保证所有研究响应可用。若后续改善提示／Schema约束或引入有界重试，必须先形成新候选／协议，并将首次失败与额外调用分别计账。当前不把这种改进先写成已修复，也不改变冻结批次。

## 核验、资源与消费

原数据及导出均按本批冻结核验器复算：五个测量完整、4通过／1失败、0unknown，92条签名，退出码1。六种重新封套篡改（签名、模型事件、预算、缺分配、来源结果、journal）均拒绝，原材料不变。执行器未改，无新实现需要重复完整框架；工程046同轮407项框架和该候选先前112项产品测试作为相关工程证据，不能换算为本批业务分母。

API报告tokens为Step8660、本地2114，总10774，含失败请求；不据此臆测套餐Credit换算。每单位最多3请求、输出4096、上游45秒、单位180秒、总1200秒及字节加输出预留限制保留，没有自动重试。

26个导出文件经供应商key和本批state token／recovery／signing seed原值及hex/base64扫描，无已知秘密匹配；私有状态未导出。五个拥有daemon身份已退出，十个模型观察服务器均排空并关闭，未终止其他用户进程。

封套SHA-256：`8323d4e0e4500c994efd6ac09dd5368af47f5b1ece7482b7a8d9504370c465ca`。见[导出复算](business-routing-sourcefix-live-001-export-verification.json)、[六项负向](business-routing-sourcefix-live-001-negative-review.json)、[消费和清理](business-routing-sourcefix-export-review.json)、[工程047](engineering-validation-047.json)。

## 剩余范围

本批任务声明与来源级别相同，未覆盖PUBLIC任务自动读取更高级来源再进入另一阶段的完整应用路径。显式策略剩余组合、本地TCP不可达、默认模型兼容性产品修复、F053问题忠实度、原生来源／委派、Q3–Q6及TP／S4独立确认仍需推进。五个配置单元属于同一业务模板，不能算五个未见独立确认任务；总体目标保持active。
