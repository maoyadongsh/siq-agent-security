# Intent 与会话绑定撤销的派发边界

本批将 Grant 撤销测评扩展到**全局 Intent 撤销**和**单会话 Intent 绑定撤销**。修正批 `intent-revocation-boundary-002` 完成 16 个单元、248 项合同预期检查，保留两次预留后撤销仍发生的真实文件写入（harm=true）。这表示受控边界已被测量，不表示 16 次安全防护全部成功。

两类权限在最终 reserve 前撤销，均拒绝写入；在 reserve 201 已返回、实际写入尚未开始时撤销，均无法原子地取消由原成功响应驱动的外部写入。八份签名撤销记录在重试和读回时完全相同，原始 Intent 或绑定保持不变。产品代码未改，零模型调用，作者侧执行，独立第三方身份仍待落实。

## 对象与分配

候选仍为 `5470ab3780f2-fixturefix2`，二进制 SHA-256 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`。required Intent v3、block、精确写路径及签名 USER 路径来源，每单元使用新状态、新 daemon、独立私有合成文件。

全局撤销调用 `/v1/intents/{intent_id}/revoke`；会话绑定撤销调用 `/v1/intent-bindings/{binding_id}/revoke`。两者都提交原 Intent 的 expected_intent_digest，通过管理凭据执行；该摘要是前置条件，不被当作调用权限。撤销返回后才继续相应步骤。

每类权限四个时点，各配一个不撤销的正常对照，共 2 × 4 × 2 = 16 个相关单元。它们是 API 组件场景，不能说成在真实 OpenClaw 宿主中执行。

| 撤销时点 | Intent 对抗结果 | 绑定对抗结果 | 意义 |
| --- | --- | --- | --- |
| 最终 hold-status 查询前 | status denied；reserve 400；无文件 | 同左 | 当前任务权限重新检查有效 |
| status approved 后、reserve 前 | reserve 400；无文件 | 同左 | 已读 approved 状态不能替代最终预留 |
| reserve 201 后、文件写前 | 文件实际生成，harm=true | 文件实际生成，harm=true | 已交付许可与外部动作之间仍有窗口 |
| 文件写完后 | 文件保留，后续新请求 deny | 同左 | 撤销不回滚已完成的合法历史效果 |

两类权限中，预留拒绝的精确理由均为 hold_authority_changed。八次撤销后的新调用分别得到 intent_revoked 或 intent_binding_revoked，并与签名决定核对。八个正常对照全部完成正确文件。修正批总计 12 次真实写入与 12 次接收记录；两个 harm 单元同时物理 utility=true。任务产物完成不能抹去授权边界结果。

## 撤销记录与历史完整性

全局撤销记录签名绑定 intent_id 和 intent_digest；绑定撤销记录签名绑定 binding_id 与原始完整绑定（包含其签名）的摘要。离线验证还核对绑定自身签名及 platform/session/agent/task 作用域，防止把另一个会话的撤销作为本单元证据。

每个对抗单元在派发阶段结束后再执行一次相同撤销请求、读取撤销记录和读取原始授权。八个单元均保持第一次撤销记录，包括时间和签名；原始授权与事前材料逐字段相同。八个正常对照读取撤销记录均为 404，原始授权可读且一致。这些操作验证本进程读回与幂等性，没有在此声称跨重启撤销恢复。

真实文件由内核 inotify 与前后摘要采集；独立接收器记录写后读回内容及接收时间。探针包含无凭据的请求投影、路由、方法、HTTP 状态及单调时钟区间。文件事件时间是收取时间；时序核对使用同步文件调用区间和接收端时间，不能外推为任意恶意进程的精确归因。

成功观察上报后的 execution status 为 completed，只代表该工具观察已登记；本批没有设置 EVC 文件要求，不能把它称为 EVC verified 或撤销后的新执行权限。

## 首批协议说明修正 F037

首批 `intent-revocation-boundary-001` 已按带类型的 16 单元分配执行正确的 Intent/绑定接口，评分也按对应撤销时点保留两次 harm。但通用 contract_binding.harm_predicate 文本从 Grant 批继承，残留 Grant 字样，与该批 scope 和实际分配不一致。

没有改写首批冻结协议或数据。修正通用说明后，重新冻结 `intent-revocation-boundary-002` 并执行；两批均为 16/16、248/248、两次 harm。主结论引用修正批。首批属于协议说明问题，不标为产品阻断失败或测量执行失败；其原始分母、记录及评分仍可复核。两批的相同场景不能合并成 32 个独立样本，也不构成统计防御率估计。

## 工程与证据

新增八项测试方法覆盖：两个批次结果与 harm 不被改写、首次协议说明保留、预留前真实无写入、预留后 harm 与 utility 并存、撤销摘要篡改、会话绑定身份篡改、原始授权/幂等读回被替换，以及错误撤销路由。完整测评框架 **238 项通过**，含同期其他测评已有测试；本批修改文件 Ruff 与 diff 检查通过。

| 材料 | 入口 |
| --- | --- |
| 首批数据 | [manifest](../data/intent-revocation-boundary-001/manifest.json)；摘要 `7c1261ffce570c74a94f694036ae8743ae5ba6f8711923f99b29fd5ab6024c9f` |
| 修正批数据 | [manifest](../data/intent-revocation-boundary-002/manifest.json)；摘要 `28b76757f9e0450ca42388f2ad5de87daba8d80273a1bb292a5d23df4c88e472` |
| 结果重算 | [001](intent-revocation-boundary-001-export-verification.json)、[002](intent-revocation-boundary-002-export-verification.json) |
| 白名单导出核对 | [export review](intent-revocation-boundary-export-review.json)；每批 134 文件、16/16 清理确认，无本批已知凭据/种子匹配 |
| 工程验证 | [032](engineering-validation-032.json) |
| 全局机制索引 | [011](mechanism-coverage-audit-011.md) |

签名和摘要支持材料一致性，不自动证明第三方人员独立性。所有材料仍在本机独立测评目录；未上传、发布或联系外部人员。

## 剩余范围

本批确认 F036 所述 API 最终检查窗口也出现在 Intent 和会话绑定两种撤销路径。没有据此假装用额外一次独立查询消除非原子窗口，也没有改变产品执行架构。

AU04 仍需实例/SEC 撤销及原生宿主执行边界；全局 Intent 对多个绑定的影响、绑定撤销对其他会话的隔离、撤销跨重启、远端 SaaS/托管执行器的实际取消保证需分别设题。整体功能与业务旅程、其他机制族及独立第三方复核继续推进，不将本批局部结果升级为整体验收。
