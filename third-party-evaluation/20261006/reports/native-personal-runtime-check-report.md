# 同实例个人接入与独立运行自检测评

日期：2026-10-06。作者侧真实执行及离线复核；不代表独立第三方认证。

`native-personal-runtime-check-001` 首次执行完整，**48/48 检查符合预期**：前置个人接入27项，加产品运行自检21项。正常业务完成，自检通过后临时权限撤销；修改配置使旧自检结果失效，恢复配置也不会将旧结果恢复为通过。没有修改产品或宿主代码。

## 实际测到什么

本批沿[同候选接入协议](../plan/native-personal-onboarding-format-002.md)重新建立独立实例，实际完成发现、正常/恶意准入、审批、安装及公开读写和私有读取拒绝，再清理测试SEC同步桥、恢复安装时profile，调用同一实例的产品自检入口。不是把旧批次的安装结果与另一实例的自检拼接。

固定 SIQ 候选 `5470ab3780f2-nativefixturefix1`，二进制 SHA256 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`；原本机 Hermes CLI。协议固定268份候选输入及宿主源码身份。对象和入口见[冻结协议](../protocols/native-personal-runtime-check-001-protocol/protocol.json)，实验范围在[事前登记](../plan/native-personal-runtime-check-001.md)中定义。

| 步骤 | 实际结果 | 解释 |
| --- | --- | --- |
| 前置业务 | 公开读/写allow，私有读取`grant_scope_violation` | 原生工具和实际摘要效果核对通过；含隐藏指令Skill仍被静态隔离 |
| 自检preview | 返回同实例计划，原Grant集合未变 | 预览不生成有效权限 |
| 错误计划摘要 | HTTP403，`runtime_check_launch_credential_invalid` | 不允许借用或改写计划 |
| 缺少显式确认 | HTTP400，`runtime_check_invalid_request` | 两次拒绝后原Grant集合均未改变 |
| 产品启动自检 | 实际daemon子进程启动真实Hermes，独立原生会话 | 只读/proc观察保存PID、boot及start_ticks；本批没有代填attach或passed |
| 自检读—拒写—读 | 产品结果passed，三决定及两观察共五条签名回执 | write_file按`intent_tool_not_allowed`拒绝，随后read_file仍allow |
| 活动关联 | 同check、instance、agent、session、task、Intent及五条回执 | 活动前缀有效、历史完整性verified，离线逐项重新关联 |
| 自检清理 | 临时Grant revoked，带过期时间；材料目录为空 | 原业务Grant未变化，profile字节未变 |
| 有效自检的诊断 | hook_load=pass，runtime_state=unverified | 两个字段用途不同；配置诊断没有冒充全运行状态 |
| 配置注释变化 | 原自检变为invalidated／`runtime_check_snapshot_changed` | 旧快照的通过证据不能覆盖新配置 |
| 恢复配置 | 原结果仍invalidated，hook_load=unknown | 恢复旧字节不会复活已经失效的旧结果；须重新自检 |

自检的临时 `rca-…` agent、`rci-…` Intent 和新会话与前置业务身份不同，这是产品自检合同规定的隔离作用域；同实例不等于同业务会话。它不验证旧会话、任意业务或可信Skill归属，不能把自检read-only权限当作原业务权限。

## 证据与计数

- 一个已见个人接入任务块，一个新增完整运行；没有新增S4独立确认任务。
- 70次实际管理HTTP，前置业务捕获5次受控模型协议请求；产品内置自检端点的具体请求数未单独采集，不能将5作为本批协议请求总数。真实模型推理0次。
- 10条唯一回执：前置业务5条、自检新增5条。自检导出包含前置前缀，离线复核两份材料不能累计成15条。
- 原接入12份签名权威文件；自检另核验3份临时Grant/Intent/绑定及7份追加签名修订。修订0–6依次包含preparing、waiting_host、running、passed、invalidated，原签名文件保持不变。
- 一个daemon、一个前置业务Hermes和一个产品自检Hermes均确认退出；未创建容器。
- 测评框架568项及118子检查通过；新增3项边界单测。七类离线篡改全部拒绝，分别是修订签名、活动任务、实例、临时Grant绑定、回执清单缺项、恢复后借用旧pass、回执链前缀截断。

原冻结复核器通过；补充复核器进一步要求API读回匹配**最新**签名修订，而非任意历史有效签名。补充工具、输入和结果均单独保留，不改冻结协议和首试分数。见[原核验](native-personal-runtime-check-001-verification.json)、[补充负向](native-personal-runtime-check-001-negatives.json)、[资源与计数索引](../inventory/native-personal-runtime-check-integration-001.json)。

导出保留10份白名单文件，筛查35种已知私有值形式、零匹配；它是本地导出，不是公开发布或普遍无敏感信息证明。manifest锚为：

`2b826474a7f092bbd36024a56068bdf7a29efaf6aaae695b47a9e04392e4b677`

按[复核命令](../REPRODUCE.md)“个人接入后的产品运行自检”章节执行，不重新调用业务或模型。

## 结论边界与接续

本批证明产品自检、临时权限清理、活动关联和配置快照失效按上述路径工作。前置业务有独立文件/内容评分；**自检的临时探针物理效果没有另设外部系统调用观察器**，其读写结论来自产品检查和签名回执，外部只另确认真实宿主进程。因此不将自检passed当独立攻击阻断证据，不据此计算自然模型攻击收益或OS隔离强度。

RB09/Q4仍是部分完成。已补同实例API自检及一种配置变化失效；浏览器展示、自检取消/超时故障、其他制品或权限变化、完整来源异常、跨宿主/OS及企业治理旅程继续按执行台账验收。后续优先验证用户实际看到的自检与任务活动关联，并复用已有生命周期和审批证据，避免重复已有全拒绝或同值任务来扩大分母。
