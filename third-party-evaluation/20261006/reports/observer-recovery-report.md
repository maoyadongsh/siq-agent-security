# Observer 撤销、接管与崩溃恢复测评

本批检验已持久化的文件观察能否在真实进程崩溃后正确接管，以及撤销历史 owner 后是否仍可恢复。修正协议批 `observer-recovery-002` 为 **6/6 单元、101/101 检查**；包含 8 次 SIGKILL 后重启。首次批 `observer-recovery-001` 的 4/6 结果及两项夹具预期失败保留，未被后续批替换。两批零模型调用、产品代码未改。执行方仍为作者侧 Codex，尚无独立第三方认证。

## 对象与协议

被测二进制来自固定候选 `5470ab3780f2-fixturefix2`，SHA-256 为 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`。配置为 required Intent v3、block：由管理端签发任务和精确路径来源，人工批准 hold，经成功 reserve 后实际写入私有合成文件。开始观察时文件不存在，写入正文为固定 synthetic 数据；内核文件 oracle 独立核对实际效果。

每个单元先建立 pending 文件观察，再完成合法写入与工具观察上报。故障发生在效果观察 finish 之前。测试仅 SIGKILL 本批所属 daemon，保持文件 oracle 存活，使用同一私有状态重启。接管通过管理 API 指定 successor 和 expected owner，验证原始签名 pending、所有权转移链和撤销记录。

| 变体 | 正常对照 | 对抗条件 | 修正批结果 |
| --- | --- | --- | --- |
| revoke-original | 原 observer 未撤销，重启后合法接管 | 原 observer 撤销后重启，再请求接管 | 2/2；正常完成，已撤销拒绝 |
| revoke-recovered | 首次接管后再次重启，再合法接管 | 首次接管的新 owner 被撤销，再次重启 | 2/2；正常完成，已撤销历史 owner 阻止接管 |
| wrong-owner | 使用真实 expected owner | 先用错误 expected owner，再用真实 owner | 2/2；错误请求冲突且不破坏后续合法恢复 |

两次重启变体各产生两次 SIGKILL，其余各一次，共八次。六个单元不是六个独立攻击族，101 个检查也不是 101 次攻击。

## 真实观察与判定

修正批有 9 次管理接管请求：6 次成功，3 次冲突（原 owner 撤销、已接管 owner 撤销、错误 expected owner）。8 次未经管理接管的直接 begin 均冲突。重启后旧 token 的 8 次请求均 403，但 token 本身为进程内对象，不能单凭这一现象证明持久化撤销有效；撤销结论还依赖两份签名撤销记录和重启后的管理接管拒绝。

两次显式撤销后，同一进程内原 token 立即 finish 均 403。重启并尝试接管后，两个被拒单元的 successor finish 均为 404 `effect_evidence_not_found`，效果查询也为 404，任务保持 incomplete。正常的四个单元 finish 为 201，效果读回与签名封装一致，任务 verified；恢复的 before 均为原始“文件不存在”，没有把崩溃后已存在的文件重采样为 before。

六个单元的文件都已合法写入，物理 utility=true、没有本批定义的越权效果。两项 incomplete 表示撤销后不能完成效果证据，并不意味着合法文件写入失败。此批检验恢复与证据边界，不证明能够撤回已经发生的写入。

## 首次失败与修正 F035

首次批 6 个单元全部完成测量，4 个满足原预期、2 个失败，99 个检查中 97 个满足。夹具误将“接管被拒后 finish”预期设为 409。固定产品实现中，管理恢复冲突返回 409；finish 找不到已恢复的内存观察会返回 404 `effect_evidence_not_found`。两者是不同接口的状态边界。

修正仅把后者的精确状态及错误码登记到 v2 协议，新建 `observer-recovery-002`；原数据、原协议及原失败判定不变。离线验证同时继续确认 001 为 4/6、002 为 6/6，防止后续验证器把历史失败抹平。POSIX pending v1 通过签名 decision 关联 Intent，验证器不假设其具有 Windows pending v2 才有的直接 Intent 字段。

## 离线证据与工程验证

验证器核对签名 Intent/来源、原始 pending、恢复哈希链、撤销对象及时间顺序、HTTP 请求与响应投影、完整探针顺序、新旧进程身份、SIGKILL 退出码、重启前后历史回执连续性、内核文件事件与实际文件摘要。公开导出限于封套白名单，私有 observer bearer 不序列化；导出扫描未匹配到本批 runtime/recovery token 或签名种子。

新增 10 项回归方法覆盖篡改快照、调换恢复链、错撤销对象、删除探针、替换请求/进程/回执身份、伪造摘要和用正常退出冒充 SIGKILL。完整测评框架执行 216 项通过；其中包含同期业务测评已有的 14 项测试，不能把这些算作本批新增。具体日志与作用域见 [工程验证030](engineering-validation-030.json)。

| 材料 | 摘要/入口 |
| --- | --- |
| 首批封套 | `7be2d89127b564d6e5e76061ac3379a5b111229600c61050925adeed6522d1ff` |
| 修正批封套 | `d8ec77a065fc66156799f169072cb1b993a83f4df105aef9f7df81b3ed92206b` |
| 原始结果复核 | [001](observer-recovery-001-export-verification.json)、[002](observer-recovery-002-export-verification.json) |
| 导出与清理检查 | [export review](observer-recovery-export-review.json) |
| AU05 逐要求核对 | [requirement review](AU05-requirement-review.json) |
| 全机制索引 | [audit009](mechanism-coverage-audit-009.md) |

## 范围与后续

AU05 的四个登记变体由本批和 hold-recovery-002 共同覆盖，仅完成 required Intent API 组件配置。SIGKILL 不等于磁盘断电，受控文件不等于所有外部业务效果；原生 SEC、同 UID 恶意进程隔离、原生业务恢复和独立人员复核仍未由此证明。继续推进 AU04 撤销/最终复查/派发边界，以及原生业务与剩余机制矩阵。
