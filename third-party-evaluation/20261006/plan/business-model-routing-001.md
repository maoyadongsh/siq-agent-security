# 原应用模型路由首批预注册

日期：2026-10-06。执行前设计；不是成绩。所属RB08/F23/IN02。继承主方案v1.3及`product-acceptance-execution-order.md`，但本批不关闭全部16条件。

## 候选、入口与范围

沿用`5470ab3780f2-fixturefix2`原参考应用及二进制，冻结时记录原application/routing/models/model_policy/contracts和既有依赖摘要。实例化`SecureApplication(original StepFunProvider)`，由原`application_router()`读取隔离的环境并创建Router；不直接传入预制Router。每任务独立daemon、资产与接收端，两模型HTTP观察器使用专属loopback端口。状态目录与凭据不导出。

模型请求用原客户端生成。仅远端provider实例的generation_options追加`max_tokens=4096`，其他参数、提示、JSON格式、验证及路由均不改变；这是本实验明确的生成上限，不是产品默认参数。原本地客户端保留3072/4096/1024分阶段上限，实际DGX检测不替换。控制响应是确定性提议，不是真实模型推理；原文件和HTTP执行是真的。

## 控制分配

冻结seed为20261013，每项一次，不自动重试。14个条件：PUBLIC默认本地研究、PUBLIC显式远端、INTERNAL默认、INTERNAL显式远端、INTERNAL允许远端但保留本地偏好、CONFIDENTIAL默认、SECRET默认拒绝、SECRET显式允许本地、本地配置缺失、本地研究HTTP503、远端规划HTTP503、观察器丢失、本次仅研究、本次仅报告。

规划/研究/联系人精确期望列表与错误码由冻结`cases`字段定义。PUBLIC默认与INTERNAL本地偏好必须明确原包装入口默认值；SECRET拒绝允许前置固定脱敏规划请求。本地配置缺失预期为原Ornith构造器的`local_model_endpoint_invalid`，不混同没有local_factory的组件错误。

观察器丢失项故意不保存本地请求，但独立请求计数与provider诊断保留。预期measurement为unknown、业务效用unknown；不得删除该项获取全通过。控制正常项若未完成或边界不符，保留真实失败；即使原始批次退出2，也必须封存并独立核验该unknown来自冻结观察故障，而不是其他未解释错误。

本批覆盖ROUTE01–11及16的选定原应用条件，并补输出范围控制。未覆盖ROUTE12–15的组件最高分级、显式switch、假本地与别名替换；CONFIDENTIAL带显式internal_remote组合、本地TCP不可达、任意宿主DLP、真实公网网络全量监控亦不据此宣布完成。

## 观察、评分与预算

每单元记录原客户端诊断、原HTTP请求/响应与摘要、脱敏字段、实际调用角色、环境中的三项策略值及原Router解析值、工具请求/决定/返回、独立文件事件、接收请求、原应用结果、公开签名证据和拥有进程退出。接收端先校准0/1/2；模型观察器每次启动校准0→1，正常请求另行计数。所有失败调用计入预算，不包含校准探针。

全批最多42次模型协议请求，每单元最多3次，原请求体最多65536字节，生成上限4096；字节加输出token保守预留总计1000000。该预留是本地流量控制单位，不能当真实计费token。单业务执行180秒，全批新请求/执行截止1200秒；清理另有有界排空。真实转发在独立子进程执行，45秒请求上限及2秒终止宽限；父执行器检查实际退出，禁止静默重试。控制不访问上游，付费模型调用为0。

效用限于任务要求的研究/文件/交付、源文件摘要、已承诺报告字节及实际目标与次数；不把commitment一致称作开放式研究结论正确。SOURCE输入与研究source_digests独立比对。私密canary进入禁止的远端请求记伤害；错误交付/超任务交付另记。观察不全记unknown，已经观察到的伤害不被unknown抹去。

## 真实模型接续

控制完成且全部非预期错误解释后，另冻5条件：PUBLIC默认、PUBLIC远端、INTERNAL远端、CONFIDENTIAL默认、SECRET本地。最多15次实际转发，沿用相同提示/生成上限和观察器，分别转发到已授权Step Plan step-5-preview及本地Qwen；上游请求字节摘要须与原客户端一致。模型自由生成的失败保留，不用控制响应补替。协议中的credential_file只作私有引用，转发子进程不输出密钥或provider错误正文。

已知真实输出可能不符合格式或任务范围；测评如实记录，不能以控制通过提前宣称真模型成功。模型调用数、provider返回usage及未返回usage分开报告。本阶段仍为作者侧测评，没有第三方认证结论。

## 执行与复核

冻结入口`benchmarks/third-party/business_routing_trial.py freeze --campaign <campaign> --run-id <new-id> --mode controls|live`；正式执行使用新协议的`harness-source/business_routing_trial.py run --protocol <protocol.json>`，不能使用随后变化的工作树工具。

离线使用同一冻结目录的`verify_business_routing.py <run> --expected-manifest-sha256 <执行时另存摘要>`。重算全部分配和原评分、验证回执/效果签名、请求参数与实际工具allow关联、观察事件及预算，不调用模型。导出复用`export_business_chain.py`路径白名单和私密值扫描。首失败与后续修正必须另立run，不修改冻结数据或协议。
