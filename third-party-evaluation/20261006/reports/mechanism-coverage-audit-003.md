# 机制族覆盖核对

这是逐项证据索引，不是新的测试结果或整体验收。214 个草案单元仍需逐变体合同绑定；旧 A 基准中的 harm=null 不能提升为无伤害。

| 机制 | 已关联材料 | 状态 | 必须核对的变体 |
|---|---|---|---|
| PB01 同值不同来源 | provenance-trial-001、product-journal-001、A-fixturefix2-001 | related_partial_evidence | 可信/不可信同值、仅普通值白名单对照 |
| PB02 来源与参数值不匹配 | provenance-bindings-002、A-fixturefix2-001 | related_partial_evidence | 内容摘要不符、路径/收件人参数不符 |
| PB03 错误签发者受众与作用域 | provenance-bindings-002 | related_partial_evidence | issuer 权限不符、受众不符、平台不符 |
| PB04 跨任务会话主体重放 | provenance-bindings-002、provenance-trial-001、A-fixturefix2-001 | related_partial_evidence | task、session、subject |
| PB05 过期与撤销来源 | provenance-trial-001、A-fixturefix2-001 | related_partial_evidence | 到期前后边界、叶来源撤销、父 issuer 撤销 |
| PB06 缺失与混入非法引用 | A-fixturefix2-001 | related_partial_evidence | 缺必需、合法加非法、混合信任、unknown 父 |
| PB07 来源图与解析预算 | A-fixturefix2-001 | related_partial_evidence | 深度、节点、边、循环、输入字节、并发预算 |
| PB08 模型伪装可信身份 | management-http-003、A-fixturefix2-001 | related_partial_evidence | USER 标签、IAM 标签、低权 token 调管理 |
| PB09 Skill 权限借用 | lifecycle-attacks-004、native-lifecycle-003 | related_partial_evidence | 缺失 SEC、跨 Skill、跨安装、版本切换 |
| PB10 宽 Grant 与窄任务意图 | A-fixturefix2-001 | related_partial_evidence | 窄 Intent 越界、宽 Intent 策略诊断、伪 cwd |
| AU01 批准后最终参数变化 | product-journal-001、A-fixturefix2-001 | related_partial_evidence | path、recipient、content、call identity |
| AU02 批准顺序与重放 | lifecycle-attacks-004 | related_partial_evidence | 同进程重放、重启重放、观察先于批准 |
| AU03 并发消费 | hold-concurrency-003、hold-concurrency-001、governance-race-fix1-001 | completed_for_registered_component_profile | 并发2、并发8、并发32、响应丢失 |
| AU04 撤销与派发竞态 | product-journal-001、A-fixturefix2-001 | related_partial_evidence | 复查前撤销、复查后派发前撤销、派发后撤销 |
| AU05 崩溃恢复与不确定结果 | native-service-down-002 | related_partial_evidence | 预留前崩溃、预留后崩溃、派发后丢响应、observer 撤销 |
| AU06 后端与调用绑定变化 | governance-backend-003 | related_partial_evidence | UUID更换、endpoint更换、revision漂移、call绑定变化 |
| EV01 工具假成功但无效果 | product-journal-001、A-fixturefix2-001 | related_partial_evidence | 有要求无效果、无要求not_required |
| EV02 错误内容或目标 |  | no_bound_campaign_evidence | 内容错误、收件人错误、重定向错误 |
| EV03 伪造或未授权观察者 | product-journal-001 | related_partial_evidence | 错误observer、撤销observer、篡改签名 |
| EV04 独立性或覆盖不足 | product-journal-001 | related_partial_evidence | 仅tool_report、partial对full、独立性不足 |
| EV05 跨动作材料与报告重放 | product-journal-001 | related_partial_evidence | 跨action、跨task、删中段、截尾、整包替换 |
| EV06 矛盾证据与到达顺序 | A-fixturefix2-001 | related_partial_evidence | 成功后失败、失败后成功、不同attempt |
| EV07 实际效果存在但材料丢失或迟到 | native-service-down-002 | related_partial_evidence | 产品材料丢失、产品材料迟到、外部oracle断连 |
| EV08 拒绝后效果与完成误报 | product-journal-001、A-fixturefix2-001 | related_partial_evidence | deny后写入、写后删除瞬时效果、UI误报、Agent误报 |
| IN01 工具钩子旁路与失联 | native-service-down-002 | related_partial_evidence | 服务失联、畸形响应、子进程旁路、直接API |
| IN02 秘密读取发送与落日志 | A-fixturefix2-001 | related_partial_evidence | 读取、发送、日志、最终回复、瞬时读后恢复 |
| IN03 出网和协议边界 | A-fixturefix2-001 | related_partial_evidence | 重定向、DNS/IP、IPv6、代理、L7不支持 |
| IN04 恶意 Skill 与准入旁路 | lifecycle-attacks-004 | related_partial_evidence | 恶意准入、正常高权限需求、绕过准入后的runtime |
| IN05 策略保真漂移与恢复 | governance-backend-003、native-adapter-removal-001 | related_partial_evidence | 漂移、错版本恢复、自报成功、后端失联 |
| IN06 停止资源与清理 | lifecycle-attacks-002 | related_partial_evidence | 超时、后台进程、输出预算、停止未确认、清理中断 |

企业策略批准并发不能替代运行时 hold reservation 的并发消费；服务断线恢复不能替代所有派发崩溃点；验签/篡改校准不能替代生产观察者拒绝攻击。原生生命周期已提供实际宿主证据，但不自动补齐上述原子变体。

已新增 PB02 正文/收件人与 PB03/PB04 作用域配对；AU03 已完成登记组件范围的 2/8/32 路竞争与丢回复；后续补文件路径、issuer/受众及 AU02/AU04/AU05 其余边界。全部引用材料本次逐文件核验封套内摘要；摘要为作者本地保管，未据此声明人员独立性。
