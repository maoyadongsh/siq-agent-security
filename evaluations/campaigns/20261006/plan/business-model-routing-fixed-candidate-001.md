# 来源分级修复候选的同版本业务验收预注册

日期：2026-10-06。候选`5470ab3780f2-routingscopefix1`。先前组件测评已保留原候选7/8及修复候选8/8；本批补同一修复候选的原应用控制和真实模型业务，不能借原候选5/5代替。

## 对象与变更边界

使用`routing-scope-components-fixed-001`冻结协议指定的候选根与源码摘要。冻结器重新核对原完整候选清单，并要求所有新增/变更文件都在组件候选声明内；额外生成应用源码集合摘要和差异表。daemon二进制保持原SHA不表示应用版本相同，二者分别绑定。

原SecureApplication、application_router、模型客户端、SkillRunner、ToolGateway、文件和HTTP执行路径不变。候选仅新增任务内已观察来源级别的最高值，具体规格、六项产品回归及112项原应用检查见[来源修复报告](../reports/routing-source-scope-report.md)。本轮不再改该候选源码。

## 分配与预期

控制批`business-model-routing-fixed-controls-001`：沿用原14条件、同seed和错误码，远端响应格式明确使用json_schema；确定性提议、真实HTTP、SIQ及文件/交付仍分层记账。预期13项符合业务/安全条件，1项故意漏观为unknown。漏观项不得改成通过。

真实批`business-model-routing-fixed-live-001`：只有同候选控制封存、独立核验和负向通过后才能冻结。执行PUBLIC默认、PUBLIC显式远端、INTERNAL显式远端、CONFIDENTIAL默认、SECRET显式本地共5条件，各一次。使用Step Plan step-5-preview及本机Qwen，三阶段schema直接取同候选合同。最多15次provider请求；不自动重试，不修复模型输出；普通失败与测量未知均保留。预期合法报告和交付完成，但预期不是结果保证。

两个批次的输入模板、三策略值、生成上限、观察窗口、计数和清理规则沿用[原路由预注册](business-model-routing-001.md)。控制14单元最多42次模型协议请求，0付费推理；真实模型5单元最多15次。单元180秒、运行1200秒、转发45秒加2秒终止宽限、4096生成上限及65536请求字节限制仍实际执行。

## 这批能证明与不能证明的事

可以验证：修复没有破坏原应用默认入口、正常/敏感任务路由、故障无静默回退、研究/报告/投递范围，以及特定结构化模型配置下真实业务可完成。原始请求、原客户端诊断、签名授权决定、文件及实际交付必须同候选关联。

原应用默认SkillRunner按照操作员的任务级别构建Source，不提供逐文件分级输入。本批不修改SkillRunner强塞更高级Source，也不把同级别业务回归称为混合来源传播效果验证。跨级别修复的作用仍由同候选独立组件证据支撑；同版本材料可以互相补充，但两类实验的条件与分母分别保留。

默认StepFunProvider的json_object兼容性未修改；本批仍是显式json_schema实验配置。尚未覆盖的别名、TCP不可达、任意宿主出网、独立业务确认集及跨平台验收继续单列。没有部署、提交或发布。

## 执行门槛与命令

新冻结参数`--candidate-protocol <routing-scope-components-fixed-001/protocol.json>`指定被实际测过的修复候选；`--control-run-id business-model-routing-fixed-controls-001`指定同版本控制。真实批若仍引用原候选控制，冻结器必须拒绝。新增负向验证同daemon不能代替应用身份、未声明文件变更及来源摘要漂移不能被接纳。

正式运行与离线复核继续使用各批冻结的business_routing_trial/verify_business_routing，保留原manifest锚。旧控制、旧失败、格式诊断和旧成功批都不重写。本次结果以新报告为准。
