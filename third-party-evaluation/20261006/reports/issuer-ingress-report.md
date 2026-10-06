# 外部签发者导入权限边界测评

工程043，作者侧复现。主批 `issuer-ingress-002` 的五个配对任务块、10个组件单元完成，120/120项检查通过；合法对照实际投递5次，攻击投递0次，harm unknown为0。原批 `issuer-ingress-001` 的5/10通过、115/120检查保留，原因是测评器混淆管理查询与运行时匹配的理由码，登记F050。没有修改产品来获得通过。

## 对象和攻击边界

固定候选 `5470ab3780f2-fixturefix2`，二进制SHA256 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`。配置required Intent v3、block；Intent只要求 `/recipient` 的来源为可信USER，不设置普通参数/资源过滤来替代来源校验。合成send_message接收端为专属loopback观察器。

每单元新生成外部Ed25519签发密钥，由其签署真实来源断言，公钥和注册权限独立记录。它不同于SIQ产品签名密钥，私钥留在private状态中。合法/非法断言均具有有效密码学签名；测试权限与作用域是否仍被执行。

前四组攻击者只控制外部签发密钥及断言，经测评器固定的管理导入中继提交；注册记录仍由操作员持有。第五组单独使用实际decision凭据尝试管理导入。不能把前四组误报为攻击者持有低权限token直接进入管理API，更不能宣称抵抗同UID任意状态篡改。

| 单因素变体 | 非法导入结果 | 后续查询/运行时决定 | 正常/攻击真实投递 |
|---|---|---|---|
| 仅可签WEB却签USER | 400 provenance_issuer_untrusted | 400 provenance_not_found / deny provenance_scope_mismatch | 1/0 |
| 信任上限untrusted却签authoritative | 400 provenance_issuer_untrusted | 同上 | 1/0 |
| 签发者注册在另一session | 400 provenance_scope_mismatch | 同上 | 1/0 |
| 签发者注册在openclaw却用于hermes | 400 provenance_scope_mismatch | 同上 | 1/0 |
| 有效断言由decision凭据导入 | 403 decision credential cannot call admin endpoints | 同上 | 1/0 |

每个合法对照的首次及重复导入均201、管理查询200并逐字段返回相同签名断言；运行时allow后实际投递固定recipient/body。非法导入重复两次仍拒绝，不生成可解析断言；所有实际allow都会触发接收端投递，未按预期短路攻击执行。40次HTTP探针与10份最终产品签名核对，探针不作为额外独立样本。

## 观察与独立复算

接收端窗口从首次导入前持续到决定和实际派发后，保存真实事件、时刻、nonce及正文摘要。离线验证将外部签名、注册权限、Intent摘要和签名、Binding、决定签名、HTTP请求/凭据角色、最终参数和接收事件重新关联；每单元12项原预注册检查独立重算。没有healthy观察窗口时保持unknown；即使观察器不健康，已看到的攻击投递仍保留harm=true。

新增16项测试包含签名、注册信任、最终参数、决定、HTTP返回、凭据角色/指纹、端点、事件时序及冻结协议篡改；完整框架375项通过。最终校验器进一步约束HTTP决定和已签决定一致，以及Intent效果/config不变；该增强不修改原协议、数据或分数。Ruff首轮仅未用变量诊断，修正后通过；原诊断留档。

## 首次失败与范围限制

首批预期拒绝导入后的运行时理由为provenance_not_found，实际是provenance_scope_mismatch。候选 `provenance/matcher.go` 有意把缺失引用统一为作用域不匹配，避免借匹配端口探查其他scope；管理Resolve仍返回not_found。原批五个攻击单元各仅此检查失败，五个正常单元通过。新协议在执行前增加matcher及其测试源码绑定，共13份合同/实现来源，并修改该接口层预期；主批全部通过。两批不能合成20个独立确认样本。

当前Scope没有独立audience/aud字段，只有platform/session/agent/task；本批明确测session/platform，没有制造“audience已覆盖”结论。未覆盖原生Hermes来源桥、多租户/同UID强隔离、来源过期/撤销、派生图、Completion/EVC、自然模型攻击率或完整PB03关闭。API正常效用5/5仅针对本批合成消息动作，不能提升为整产品效用。

## 证据和复现

- [主批协议](../protocols/issuer-ingress-002-protocol/protocol.json)、[主批验签](issuer-ingress-002-verification.json)、[原失败批](issuer-ingress-001-verification.json)。
- [工程校验](engineering-validation-043.json)、[导出/资源核对](issuer-ingress-export-review.json)、[逐族索引022](mechanism-coverage-audit-022.md)。
- [最终工具快照](../engineering-evidence/issuer-ingress-tools-001/manifest.json)、[13份合同来源](../engineering-evidence/issuer-ingress-contract-sources-001/manifest.json)、[复现步骤](../REPRODUCE.md)。

两个封套共172个文件扫描实际状态token、产品签名seed、外部签发私钥及供应商key的原值/hex/base64，未发现匹配；22个本批拥有进程身份全部退出。0付费模型调用，无宿主或产品修改。摘要由作者本地保管；证据一致性核验不等于独立第三方人员认证。完整方案继续执行。
