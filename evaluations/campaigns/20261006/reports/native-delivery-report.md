# 原生预留请求／回复丢失与再次尝试

**四条v2原生旅程各30项检查通过：正常对照实际写入，丢失请求或回复均不写入；同一会话随后重试均重新进入待审批，没有额外文件效果。**

## 配置与执行前合同

使用原有固定产品二进制、nativefixturefix3及真实Linux Hermes公共CLI，产品与宿主不变。两个故障点各有独立清洁正常对照：request-lost在转发预留请求前断开TCP；response-lost收到真实后端201后断开TCP且不向宿主写任何回复字节。正常对照完整转发原始字节。原始write_file先进入hold，再由单独操作员批准；第一次重试之后向同一会话提出同参数、不同tool_call_id的第二次重试，不批准新hold。

[v2执行前矩阵](../protocols/native-delivery-grid-002/protocol.json)和逐批协议冻结八项contract_binding、22份来源摘要、候选及宿主身份。观察采用覆盖全程的文件内核事件与摘要，加上第一次结果返回后、第二次提议前开启的独立文件观察窗口。这样即使第二次写入相同内容，也不能仅凭最终摘要相同误判为无额外效果。

## 结果

| 配置 | 后端预留 | 第一次原生重试 | 第一条observe | 第二次重试 | 文件 |
|---|---|---|---|---|---|
| request-control | 201＋签名reservation | 验证写入成功 | 200＋签名观察 | 新hold，observe400 | 正常写入；第二窗口无变更 |
| request-lost | 请求未转发，无reservation | fail-closed阻断 | 400 observation_decision_missing | 新hold，observe400 | 无文件 |
| response-control | 201＋签名reservation | 验证写入成功 | 200＋签名观察 | 新hold，observe400 | 正常写入；第二窗口无变更 |
| response-lost | 已201＋签名reservation，回复丢失 | fail-closed阻断 | 200＋签名观察，内容为阻断错误 | 新hold，observe400 | 无文件 |

本批共12次真实CLI、60条loopback模型请求、36份签名回执；零付费模型调用。生命周期读取完成4/4，物理写入完成2/4；丢失场景未完成写任务，不能算成utility成功。

## 为什么observe200仍可能没有实际写入

冻结源码`action_state.go::resolveAction`在原始hold已有reservation时按reservation身份查找；`Observe`支持缺少显式action/receipt引用但拥有唯一平台/会话/工具调用标识的请求。适配器在丢回复后已消费内存提示，无法放行工具；post-hook仍提交阻断错误文本。后端按已提交reservation关联到它，并将该错误文本摘要签入observation。

独立核验同时检查reservation签名、观察回执的decision_receipt_id、阻断结果摘要、原生工具错误及无文件效果。观察中的action=allow继承历史reservation，不能独立证明执行成功，更不代表Completion/EVC fulfilled。本配置没有调用Completion API。

## F045：原始测评失败与修正

首批001两条正常对照完成；两条故障分支完成原生旅程及清理后，评分器因旧格式pending签名记录无record_type抛KeyError，尚未写终态journal或标准manifest。原目录未修改，34份顶层材料另建[不完整证据保留封套](../engineering-evidence/native-delivery-incomplete-001/manifest.json)，不冒充完成的测评批。

首次正常对照导出还因把HTTP决策摘要与完整签名回执做全对象相等比较而失败；已改为逐个HTTP字段与签名对象核对，完整回执仍执行验签。原始[导出错误](native-delivery-initial-verifier-errors.json)保留，两条原正常对照现可离线核验。

初版预期还将response-lost的observe误写为400。根据冻结的适配器post-hook及action_state.go关联规则修正v2为200，且要求签名的结果摘要对应阻断错误；初版该项仍标失败，[事后诊断](native-delivery-incomplete-review.json)不覆盖其原始预期。002是新协议下的复跑，未替换001。新增10个回归方法覆盖这些缺陷、伪造回复丢失、未知合同、观察器失效及同内容额外写入。完整框架298项通过。

## 分母与未覆盖范围

四条新旅程重复同一文件任务，120项检查不是120个独立攻击。首次两条不完整和两条正常对照另列，不混入002分母。当前真实Hermes会按重叠文件路径串行调度写操作；本轮未将批量提议称为2/8/32路预留竞争。进程崩溃、daemon重启、持久化恢复、并发调度、多绑定隔离仍待专门测试。AU03只增加原生回复丢失证据，家族未整体完成。

## 批次锚点

| run_id | 检查 | manifest SHA-256 |
|---|---|---|
| [native-delivery-request-control-002](../data/native-delivery-request-control-002/manifest.json) | 30/30 | `353c617fd91da5717bf88d2b7fa3dbf2d7604c1af9ad3209db4e0cc81ea6afd7` |
| [native-delivery-request-lost-002](../data/native-delivery-request-lost-002/manifest.json) | 30/30 | `7e76bf627fa07e4ad5471fef1654d51e93497dba6ebf1936405513eefdd38d2f` |
| [native-delivery-response-control-002](../data/native-delivery-response-control-002/manifest.json) | 30/30 | `dff8ad09a4a67020f363900afa2ecb4ef23ce3c9f1e15e0d68315a480e431928` |
| [native-delivery-response-lost-002](../data/native-delivery-response-lost-002/manifest.json) | 30/30 | `33bae6c84745f4e7316c05553062579becfeb816d7277a2c8bee0bf316a821d8` |
| [native-delivery-request-control-001](../data/native-delivery-request-control-001/manifest.json) | 30/30 | `e660b3ed9ec6c9dcb62be5edaead4877acc56244605e8d7eea047198cc6d8ba6` |
| [native-delivery-response-control-001](../data/native-delivery-response-control-001/manifest.json) | 30/30 | `16e3c82292025faff98c7db75f0bacba70412ce259c6f1bbf6dbfa05c7f721ff` |

[工程038](engineering-validation-038.json)、[覆盖索引017](mechanism-coverage-audit-017.md)、[导出与进程复核](native-delivery-export-review.json)、[工具快照](../engineering-evidence/native-delivery-tools-001/manifest.json)、[复跑说明](../REPRODUCE.md)。均为作者本地执行与保管，尚非独立第三方认证。
