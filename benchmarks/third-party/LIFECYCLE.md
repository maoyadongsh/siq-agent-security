# 统一逐次尝试记录与中断恢复

实现范围：`schemas/case.v1.schema.json`、`lifecycle.py`、marker 校准执行器及 `product_journal.py`、`process_resources.py`、`verify_product_journal.py`。此增量属于 TP02。注册操作包括 `marker_calibration` 和五组真实组件样例 `product_samples`；尚未将全部产品、模型和企业专项执行器迁入此模块。

每条记录包含 run/unit/case/pair/task-block、候选和协议摘要、track/group/family、claim/product-group、attempt/retry_of，分别记录 execution、measurement、assertion 状态和 harm/utility 的 true/false/null。unknown 必须带原因；已确认损害和完成必须有关联材料。产品 Completion、reason、UI/Agent 陈述及 observer 引用保留独立字段。

`journal.jsonl` 逐事件追加并 fsync，使用递增序号、单调时间、进程 PID/boot ID/start ticks、前事件摘要和当前摘要。写入者持有本轮目录的 flock；不允许两个执行器同时派发。哈希链用于发现损坏，不能替代外部锚或独立执行身份认证。

恢复规则：

1. 完整校验协议、预分配单元、事件链和已有尝试。
2. `scheduled` 单元可以执行；`started` 单元不得自动重放。进程仍存活时保持原态。
3. 确认原进程退出、PID 已复用或 boot 已变化后，写入 `interrupted`；已知效果不抹除，未确认完成仍为 null。
4. 原进程退出不等于其后台任务已结束。必须由注册操作自己的资源核对器确认清理后，才可重试。当前 marker 操作不创建子进程、网络或后台任务；该核对规则不能直接用于未来宿主或模型操作。
5. `--retry UNIT` 显式生成新 attempt 和 retry_of，使用独立材料目录，并消耗冻结的 max_attempts。主结果仍选择 attempt=1；重试不会修饰首次失败或未知。
6. 残缺 JSONL 尾部、缺失分配或损坏链返回完整性错误；不截断、不覆盖。封存后的运行拒绝继续写入。

已执行校准 `journal-calibration-001/002`：外部驱动在确认首个 marker 写入并记账后，实际向自有执行器发送 SIGKILL；确认其退出后重新启动。16 个检查均通过。原中断单元只写入一次，恢复只运行另一个未开始单元；再次恢复无新派发；显式重试建立第三份独立尝试材料。最终 2 个分配单元、3 次尝试，首次结果为 1 个通过、1 个未知，最终退出码保持 2。

“已知损害”在该校准中仅指违反合成标记规则的自有文件写入，不是 SIQ 漏洞样本。校准自身 16/16 通过与被校准日志故意保留未知并不冲突，两个指标不可合并。

新建校准（需已有锁定开发环境的 Python）：

```bash
$SIQ_EVAL_PY benchmarks/third-party/journal_trial.py \
  --campaign third-party-evaluation/20261006 --run-id <全新批次ID>
```

该命令先冻结工具与 Schema，再运行已登记操作，不接受任意 shell/argv。Linux `/proc` 身份核对和 flock 是当前实现前提，未宣称 Windows 原生恢复验收。

底层统一入口支持：

```text
run.py --protocol frozen-v2.json --track B --out NEW_DIR
run.py --protocol frozen-v2.json --track B --out EXISTING_DIR --resume
run.py --protocol frozen-v2.json --track B --out EXISTING_DIR --resume --retry UNIT
run.py --protocol frozen-v2.json --track B --out EXISTING_DIR --resume --seal
verify.py RUN_DIR --expected-manifest-sha256 DIGEST
```

冻结协议绑定运行 ID、工具摘要和有限预算。复跑必须使用对应冻结源码；改变操作、候选或预算需建立新协议。旧 A 协议及旧专项结果不能通过新 `--resume` 原地重跑。

真实产品样例接入：`product-journal-001` 正常批次 10/10 通过，离线重新计算独立效果、产品签名回执和首次尝试汇总。5 组分别为同值不同来源、批准后变更、批准后撤销、虚假完成和拒绝后越权效果。EV08 故意绕过 deny 的写入产生真实违规效果，此用例验证检测，不能计为阻断成功。

`product-journal-recovery-001/002` 对 EV08 在完成独立观察和产品回执采集后、终态写入前实际 SIGKILL。18 项恢复检查通过，确认 daemon 在执行器死亡后确实残留。恢复按 PID、boot ID、start ticks、命令摘要核对已登记 daemon，通过 pidfd 发送信号，核对原进程组无存活成员才确认清理；不对任意进程组整体发送信号。发现未知成员或身份不符则保留未确认状态、禁止重试。依赖 Linux aarch64/x86_64 的 pidfd syscall ABI，不声称同 UID 对抗隔离。

首次结果保持 9 通过、1 未知、1 个已知违规效果，退出码 2。显式重试使用独立状态目录、随机 nonce 和 attempt，11 次尝试不改变首次分母。第二批还冻结了观察阶段立即保留已知断言失败、恢复时保留已知产品裁决的改进。正常及中断批次属于作者侧组件测评，不增加独立场景数。

新建真实产品批次或中断批次：

```bash
$SIQ_EVAL_PY benchmarks/third-party/product_journal.py \
  --campaign third-party-evaluation/20261006 --run-id <新正常批次ID>
# 按输出协议路径，使用同目录 harness-source/run.py 的统一入口运行并 --seal。
$SIQ_EVAL_PY benchmarks/third-party/product_journal_trial.py \
  --campaign third-party-evaluation/20261006 --run-id <新中断批次ID>
```

后续任务：迁移其余产品、模型和企业执行器；建立已有结果的可核验投影而不改写原文；为原生宿主和模型操作分别实现资源核对；完成跨轨道统一调度、完整校准矩阵及统一资源硬限制。当前注册组件调用沿用已有调用超时，故障注入驱动另设子执行器 240 秒等待上限，不能声称已完成所有轨道的资源控制。上述剩余工作完成前 TP02 保持进行中。
