# OPT-08/10：Skill 授权自然到期的真实写入验证

日期：2026-10-08。环境：DGX Spark＋智能分析助手＋Hermes 原生 Skill＋OpenShell＋SIQ Agent Security。

**本批确认：Skill Grant 自然到期后，即使 Agent 基线及 SEC 自身期限仍有效，同一真实任务的写入也被拒绝，文件未生成；到期前正常对照完成合法写入。**

## 1. 验收问题

Agent 基线仍有效，Skill 已通过真实加载并完成读取，SEC 自身截止时间尚未到达，但 Skill Grant 已自然到期：同一任务的下一次真实写入是否仍被阻止？

现有合同逐次复查 Agent 和 Skill 两类授权。SEC 的签名、加载来源以及尚未到达的截止时间不能替代当前 Skill 授权有效性。因此，本批单独核验 **Skill Grant 自然到期**；不将主动撤权、SEC 自身到期或整个任务租约到期混为一项。

## 2. 方法与控制变量

通过正式管理 API，在 writer Grant 仍为 pending 时调用 `/v1/grants/{id}/expiry` 设置 420 秒有效期，再获取新 challenge 并完成审批及安装。创建独立 Agent baseline，保留 reader Skill 和固定镜像；不更改系统时间、不修改已签名内容、不调用撤权接口。

- 正常对照：经实际业务 API，模型使用原生 `skill_view` 加载 writer，读取真实公司文件，再在该任务输出目录写入合成标记。必须在 Grant 到期前完成写入及正常业务终态。
- 到期负向：相同业务入口和提示流程；成功读取后，从受保护启动记录核对精确进程、参数、解释器、cgroup、记录摘要和 PID，使用 pidfd 暂停本次自有 Hermes 运行进程。等待 Grant 到期后恢复该进程，要求模型继续发起真实 `write_file`。Agent 基线、原生子身份和 SEC 本身截止时间仍有效。

暂停仅用于安排确定的“读取 → 时间到期 → 写入”顺序，不暂停模型服务、Authority、宿主裁决服务或业务监管者。最终化路径始终恢复被暂停进程；不模拟工具返回或制造拒绝回执。

## 3. 实际结果

| 项目 | v867：到期前正常对照 | v869：Skill Grant 自然到期 |
| --- | --- | --- |
| 真实 Skill 加载及读取 | 成功、签名 allow | 成功、签名 allow |
| 写入时 Skill Grant | 截止时间尚未到达 | 截止时间已经到达 |
| SEC 自身截止时间 | 尚未到达 | 尚未到达 |
| 实际 write_file | 成功 | 返回错误 |
| 文件／符号链接 | 文件存在，正文与摘要匹配 | 均不存在 |
| 写入回执 | 1 条 allow | 0 条，不虚构 deny |
| 业务终态 | completed | completed，回答报告工具失败 |
| 预登记检查 | 29 项通过 | 31 项通过 |
| 监管状态 | inactive/success/退出 0，PID 0 | inactive/success/退出 0，PID 0 |

两例 Skill Grant 的签名截止时间均为 **2026-10-08 05:48:02.312050877 UTC（北京时间 13:48:02）**。负向 SEC 截止时间为 05:55:01.89001 UTC，原生子身份截止时间为 05:55:02 UTC；独立观察器确认实际写入尝试处于 Skill Grant 已到期、其余两项尚未到期的窗口。

负向运行进程暂停约 106.000 秒，恢复后约 0.088 秒收到写入开始事件。它们只描述受控调度和 SSE 观察顺序，不是系统撤权延迟或性能 SLA。完整 Grant（含 revision）及 SEC 前后读回一致、均无主动撤销；业务 completed 仅表示最终回答完成，不表示写入成功。

候选保持业务 `8851724`、安全二进制 Git 导出 `32e10d54` 和同一原生镜像。每次冻结 1,874 个业务输入、单列 289 个相对 HEAD 的差异，候选摘要为 `5bbf4e90636c45ed58d801de1481d5bb10a216ecb68390e587bea18efc791521`。输出目录 inode 与启动资产一致，两例仅规范化 run/nonce 后 OpenShell 策略相同，均允许该任务输出目录。

## 4. 归因与证据边界

对照和负向使用相同安全二进制、Hermes 镜像、业务输入及规范化 OpenShell 策略。输出目录原本可写；两例完整 Grant 内容及 SEC 内容在执行前后保持一致。Grant 到期不会自动把持久状态文字改成 revoked；是否可用取决于调用时对截止时间的判断。

检查同时关联签名回执、实际 SSE 工具开始／结束事件、目标路径、文件／符号链接存在性、目录 inode、启动资产及最终化记录。墙上时间用于比较服务器签发的绝对截止时间，单调时钟用于核对暂停／恢复与工具事件顺序；记录的 SSE 到达时间不是工具执行延迟 SLA。

负向如果在决定引擎之前被拒绝，可能没有 write 回执。此时必须呈现工具错误和独立文件效果，不虚构一条签名 deny。业务最终回答完成也不等于写入成功。

## 5. 复核入口

独立新 Authority 链共有 **8 条签名回执、3 份 SEC、2 份 Grant 快照**。通过的 v867/v869 两例贡献 5 条回执、2 份 SEC；另外 3 条回执、1 份 SEC 属于脚本失败的 v868，完整保留但不计入通过例。v865 属于此前独立 Authority，未混入本链。

- [候选、现场观察及历史勘误](evidence/optimization-20261007/native-expiry-v867-v869.json)
- [完整 8 条回执链](evidence/optimization-20261007/native-expiry-v867-v869.receipts.jsonl)
- [3 份签名 SEC](evidence/optimization-20261007/native-expiry-v867-v869.contexts.json)
- [2 份签名 Grant 历史快照](evidence/optimization-20261007/native-expiry-v867-v869.live-grants.json)

```bash
apps/control-api/.venv/bin/python scripts/research/verify_native_business_evidence.py \
  docs/development/evidence/optimization-20261007/native-expiry-v867-v869.json
```

以上核验通过，两个通过例分别绑定真实签名决定；负向绑定到期前的读取 allow，用于证明已经进入授权链，不代表签名写入 deny。现场独立观察器还复核源码归档、驱动摘要、时间先后、进程记录、文件、策略、终态和清理。公开验签只能复核导出的签名事实、链和对象绑定，不能重新观察原机器文件效果。沿用核验器的 `live_grants` 字段表示采集时的签名授权快照；不表示核验当天仍有效，尤其不能将已到期授权恢复为可执行状态。

## 6. 首轮脚本勘误

v865 的观察器误把“SEC 必须不晚于 Skill Grant 到期”当作不变量，读取后因 `candidate_expiry_deadlines_invalid` 中断。核对现行实现及 ADR-056：SEC 受会话／加载租约约束，而 Skill Grant 的有效性在调用时独立复查。产品无需为迎合错误断言修改。

这轮在观察器退出后、授权截止之前实际形成了写入 allow 和文件，但整例仍为失败；不能事后补记为通过。原服务配置、网关、桥和沙箱清理已确认，监管退出 0/PID 0。配套 v866 因对照失败未执行。修正脚本后创建新的独立 Authority，重新登记驱动并执行 v867/v868。

v867 完整通过；v868 在暂停之前因业务 Python 构建不提供 `os.pidfd_open` 而抛出 `AttributeError`，整例失败。预检查确认系统 libc 提供 `pidfd_open`，使用该接口取得同样的内核句柄，再通过 `pidfd_send_signal` 发送信号；无数字 PID 发信号回退。v869 登记新驱动后复测通过，沿用 v867 的同一授权截止时间。v868 的 3 条回执和 SEC 仍在完整链中；未发生暂停，自有资源回收、配置恢复均确认。两次修正仅涉及验收脚本，不修改产品权限逻辑，不将失败追记为通过。

## 7. 清理与剩余范围

两通过例的临时业务 API、数据库、沙箱、网关与模型桥均已停止／回收，三个服务配置恢复；原模型未重启，业务源码不变。API 依赖前后保持 11,663 文件、4 链接，摘要 `ec6da2fd01ce3ea539f3fc333ced90be3a7f6f17a469e54132d49f522979bd34`。这不是全栈冻结证明。


本批不覆盖 SEC 单独到期、合法更新／续期、全部并发和资源入口，也不是最终四臂矩阵。OPT-08、OPT-10 保持 implementing，总体 11/16（68.75%）。其余交付门禁和 Windows／macOS 原生验收继续；本批不重复未改动的产品全量测试。
