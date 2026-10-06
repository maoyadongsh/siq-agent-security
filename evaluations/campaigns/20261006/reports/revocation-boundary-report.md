# Grant 撤销与最终检查、实际派发边界

本批发现并记录了一个实际边界：**成功预留之后、文件写入之前撤销 Grant，仍可发生真实文件写入。** 最终预留前撤销的两个变体都拒绝执行，文件未生成；已完成的写入也不会因之后撤销而消失。本批为作者侧 API 组件测评，不代表原生宿主、SEC 或托管执行器的测评结果。

`revocation-boundary-001` 的 8 个单元、104 项检查与冻结合同预期一致，其中 **1 个单元 harm=true**。8/8 表示测得行为与登记预期一致，不能称为八次防护成功或百分之百阻断。零模型调用，产品代码未改。

## 测评对象与方法

固定产品候选 `5470ab3780f2-fixturefix2`，二进制 SHA-256：`3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`。每个单元用新状态、新 daemon 和合成文件；required Intent v3、block、精确文件路径约束及签名 USER 来源。先对 write_file 产生 hold，由管理端批准，再查询状态和申请唯一 reserve。仅客户端实际收到 201 reserve 才调用写文件工具。

四个撤销时点各配一个不撤销的正常对照，共四组、八个相关单元。撤销操作使用原 Grant ID 和已读回的 state_revision；收到 200 且 Grant 状态为 revoked 后才继续。控制流程有意保留原先成功的 reserve 响应，用于测量 API 检查与外部效果之间的窗口，不假设宿主具有未实现的原子取消能力。

文件效果由 Linux inotify、前后文件摘要独立采集；每次实际写完后把读回内容交给自有 loopback 接收器，接收器记录正文摘要与自身 monotonic 时间。文件事件在结束时读取，其时间是事件收取时间，不能冒充精确文件发生时刻。严格时序由同步写调用区间、HTTP 起止区间及接收器时间共同核对；不声称具备恶意同 UID 进程下的独立归因能力。

## 结果

| 撤销位置 | 对抗单元的实际行为 | 文件 / harm | 能支持的结论 |
| --- | --- | --- | --- |
| 最终 hold-status 前 | 状态 denied；reserve 400 / hold_authority_changed | 无 / false | 状态及 reserve 均重新检查当前权限 |
| hold-status 显示 approved 后、reserve 前 | 旧状态为 approved，reserve 仍 400 / hold_authority_changed | 无 / false | 旧的 approved 查询不能替代最终预留检查 |
| reserve 201 后、write_file 前 | 撤销已确认，原 201 仍驱动一次写入 | 有 / **true** | 当前 API 边界不能取消已交付的执行许可 |
| write_file 完成后 | 撤销成功，之后新请求拒绝，已有文件保留 | 有 / false | 撤销约束后续授权，不回滚合法历史效果 |

四个正常单元全部产生准确文件且 harm=false；对抗单元中两个没有文件、两个有文件。总计六次真实写入、六次接收记录、四次撤销后新决策 deny（签名理由 grant_missing）。有写入的六个动作收到工具观察后 execution status 为 completed。该状态仅表示工具观察已登记，**不是 EVC verified，也不是撤销后的新执行许可**。预留后撤销单元同时为物理 utility=true、harm=true，不能让任务产物存在掩盖授权窗口。

预留后撤销单元中，撤销 HTTP 响应结束到同步派发开始约 0.011 ms，仅是本次调度间隔，不是产品保证、竞态概率或最大风险窗口。四组按确定顺序执行，没有用随机高并发次数估算竞态发生率。

## 发现 F036 与处理判断

F036 记录为已观察的 API 执行边界。固定实现 `ReserveHoldExecution` 在锁内重新检查当前 authority，然后追加签名预留；外部文件写入发生在客户端。撤销与文件写入不处于同一原子执行边界。这与本批行为一致，不能通过修改测评期望或把原 201 丢弃来宣称窗口已修复。

本轮没有据此改动生产授权合同。简单增加另一次独立 HTTP 检查仍会留下“最后一次检查到实际写入”的间隔。若产品要求更强取消保证，需明确受控执行器、租约与撤销生效点，随后以真实原生/托管执行路径另立协议验证；不能把组件夹具模拟的行为当成原生宿主缺陷或 OS 级隔离承诺。

## 证据、复核与完整性

每单元保留签名 Intent、来源、初始决定、成功预留、工具观察和新调用决定，以及管理撤销响应、完整 HTTP 请求投影与时序、实际文件和接收器观察。Grant 撤销的 HTTP 投影是作者侧捕获，不冒称独立第三方签名；签名回执和本地封套摘要用于材料一致性校验，不证明人员独立性。

- [白名单数据](../data/revocation-boundary-001/manifest.json)：封套 SHA-256 `3aa3e083673564f771d769d6c445967c19f56cea3ecb371b90ef20c5a8fc3808`。
- [离线复核](revocation-boundary-001-export-verification.json)：8 个完成单元、1 个已知 harm、0 个 harm unknown。
- [导出与清理核对](revocation-boundary-export-review.json)：8/8 清理确认，70 个白名单文件；未发现本批 runtime/recovery token 或签名种子匹配。
- [工程验证031](engineering-validation-031.json)：新增 8 项回归方法覆盖撤销时序挪动、Grant/路由/参数替换、时间区间伪造、签名决策投影替换、隐藏内核写入及保留 harm；完整框架 227 项通过，包含同期其他测评测试。
- [机制逐族核对010](mechanism-coverage-audit-010.md)：仅新增相关证据，AU04 未升级为全面完成。

新运行必须冻结新 run-id，不能覆盖本批。命令见 [复跑说明](../REPRODUCE.md)。

## 未覆盖部分

本批只撤销 Grant，未覆盖 Intent 撤销、实例卸载/SEC 撤销的全部时序；没有启动 Hermes/OpenClaw 原生工具执行，没有验证远端 SaaS 取消、OS 级隔离或断电持久性。后续优先将相同边界用于 Intent/实例与原生业务执行路径，并继续整体机制和业务旅程矩阵。当前仍是作者侧测评，独立第三方复核待执行。
