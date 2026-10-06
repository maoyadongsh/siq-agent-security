# 批准重放、真实进程崩溃与观察回复丢失

固定产品二进制未修改。`hold-recovery-002` **12/12 单元、190/190 检查通过**；包含 10 次真实 SIGKILL 后重启、11 次合法文件写入及 6 次被拒绝的批准重放。此前 `hold-recovery-001` 为 10/10、157/157，扩展批增加了观察持久化后实际丢失 HTTP 回复的配对变体。两批独立归档，不合并成独立攻击样本数。

## 本批验证什么

配置为 required Intent v3、block；使用有效任务绑定、精确文件资源限制、签名 USER 路径来源以及正式 Grant 人工审批。每单元有独立临时状态、文件和接收 nonce。真实 `write_file` 操作写入受控合成内容，将实际文件字节发送到持续运行的接收器计数。所有客户端可见的预留成功，包括任何意外成功的重放，都会触发一次写入，夹具不去重。

SIGKILL 只针对本单元拥有的产品子进程，等待回收并记录退出码 -9，再以原状态目录和原二进制启动新进程。新旧 PID/启动标识与资源登记核对，签名公钥不变。API 在新 loopback 端口重新配对；不测试原生适配器的自动重连。接收器和评估进程在产品重启期间持续存活，因此能持续统计真实效果。

每个崩溃点由顺序屏障控制：上一步 HTTP 调用或文件写入已返回，才发 SIGKILL；旧进程已回收、新进程就绪后才进行下一步。该方法证明边界间顺序，不宣称命中某条 fsync 内部指令，也不等同于存储介质断电。

## 002 结果

| 变体 | 正常对照 | 攻击/故障条件 | 故障单元最终文件 / 产品状态 | 重放 |
|---|---|---|---|---|
| 同进程批准重放 | 一次完整执行 | 原请求再次 reserve | 1 次效果 / completed | 409 |
| 重启后批准重放 | 完整执行后 SIGKILL，重启读回 | 同样重启后重放原请求 | 1 次效果 / completed | 409 |
| 预留前崩溃 | 完整执行后重启读回 | 批准后、reserve 前 SIGKILL，恢复后消费 | 1 次效果 / completed | 完成后的重放 409 |
| 预留后崩溃 | 完整执行后重启读回 | reserve 已返回 201，写入前 SIGKILL；恢复后不盲派发 | 0 次效果 / uncertain | 409；新调用也 deny |
| 派发后、观察前崩溃 | 完整执行后重启读回 | 文件写完，但未提交 observe 即 SIGKILL | 1 次效果 / uncertain | 409；新调用也 deny |
| 观察回复丢失 | 正常提交观察后重启读回 | 后端 observe 返回 200 后代理断开客户端，再 SIGKILL | 1 次效果 / completed | 409 |

全部 12 次初始 reserve 均为 201 / `hold_execution_reserved`；6 次精确重放为 409 / `hold_execution_already_reserved`。两个 uncertain 单元另发新 tool call，都得到签名 deny / `hold_execution_uncertain`，没有通过重新申请批准清空不确定状态。六个正常对照均完成合法效果。

观察回复丢失不是模拟返回值：一次性自有 HTTP 代理转发 `/v1/observe`，记录后端 200 后直接关闭客户端 socket。客户端实际收到断连且没有 observation receipt；离线评分方用代理记录的 receipt ID 核对已落盘签名观察。产品重启后状态为 completed，说明“客户端不知道结果”和“后端尚无结果”在本路径被区分。评分方的后端记录不会被当成客户端的重复执行许可。

物理任务效用与产品状态分别统计。预留后尚未执行的故障单元 utility=false；已写文件但尚无观察的单元 utility=true、状态 uncertain。这不是用客户端宣称的成功替代文件效果，也不把安全停止计为任务完成。这里的 completed/uncertain 是 hold execution 状态，不是 EVC 任务 Completion。

## 证据与复核

每个重启单元都有重启前后签名快照、原始请求/响应、事件顺序、真实进程标识、文件状态、接收记录及最终回执链。验证器分别验签两份快照，再逐条检查原历史回执未丢失或被改写。状态查询必须引用同一预留；观察必须引用该预留和 retry ID；SIGKILL 前后的进程必须对应资源登记。

九项回归测试涵盖两批实际数据、物理效用与产品状态区分、进程身份替换、崩溃顺序篡改、状态/重放关联替换、丢回复冒充收到、decision ID 冒充 observation、历史回执丢失以及正常退出冒充 SIGKILL。它们是验证器校准，不作为新的产品攻击样本。

初次离线验证发生 F033：把重启前后有重叠历史的快照当作两个互不重叠的回执包合并验证，导致 duplicate receipt identity。修正为分别验签并检查包含关系；后续加强检查时也按 API 实际只返回 receipt ID 的投影核对签名记录，而非要求 HTTP body 等于完整链记录。错误证据保存在 `reports/hold-recovery-verifier-initial-error.json`。未改产品、未修改已封存测量，未把验证器错误写成产品防护失败。

001 manifest：`76ae18c6bfd2c32704720bb1fb613abed85f0ece1c1b4a8789f76138911e0cef`。
002 manifest：`7bcdab3dbd41ca95de26399a10999c4e6eb4b006d278fefa875650e7775d51b7`。

数据在 `data/hold-recovery-{001,002}`，协议和源快照在对应 `protocols/`，复核报告为 `reports/hold-recovery-*-verification.json`。每批分母保留，001 是初始五变体批，002 是增加第六变体的新协议，不是用重试替换首次结果。

协议行中的 `drop_response` 是复用文件 oracle 的“预期零执行”标记，仅在预留后崩溃单元为真，不表示该处实际丢了 reserve 回复；该单元已真实收到 201。真正的观察 HTTP 回复丢失由 `observe_response_loss` 和代理证据标识。此说明不回写已冻结协议。

## 尚未覆盖

AU02 的“观察先于批准、后到批准不能追认非法效果”尚未完成；AU05 的 observer 撤销与接管尚未完成。AU04 的撤销/最终复查/派发竞态仍需单独测试。本批不能关闭这两个机制族，也不覆盖原生 Hermes/OpenClaw SEC、恶意同 UID 干扰、磁盘断电、远端业务系统 exactly-once 或全部线程时序。

本批零模型调用、无生产数据或真实外部联系人。作者侧执行和本地摘要保管不等于独立第三方认证。

后续 [效果授权时序批](effect-authorization-time-report.md)已补测 AU02 的早效果/晚批准，原有 001/002 重启批分母和结论不变。AU05 observer 撤销与接管仍待实施。
