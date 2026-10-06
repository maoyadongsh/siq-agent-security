# SIQ 第三方测评执行工具

这是作者侧可复查测评工具。20261006 的 DGX／分析助手 Agent 与已安装 Skill 权限收口已完成，入口为[最终报告](../../third-party-evaluation/20261006/reports/research-permissions-final-report.md)和[权限复现说明](../../third-party-evaluation/20261006/README-PERMISSIONS.md)。原[阶段报告](../../third-party-evaluation/20261006/reports/progress-report.md)保留历史广义轨道状态；没有完成全部原计划或独立机构认证。

以[复核与复跑说明](../../third-party-evaluation/20261006/REPRODUCE.md)为执行入口。`run.py` 支持原 A 轨道以及 v2 协议的 B 轨道日志恢复校准；后者仅验证测评设施，不是新增产品成绩。B 产品样例、模型、AgentDojo、来源消融、企业 HTTP/PostgreSQL 仍有专项 runner 和 verifier，尚未全部迁移至统一生命周期。`governance_trial.py --include-edge` 可冻结合成 Edge 协议与资产证据扩展。各 cohort 先冻结任务、源码和预算，原始失败与后续修订使用不同目录。

[统一记录与恢复说明](LIFECYCLE.md)说明逐次尝试 Schema、首次尝试统计、显式重试与实际进程中断校准。旧封套保持原样，不以新 Schema 改写历史证据。

`oracles/` 负责评测方效果采集，`product_observers/` 向真实 SIQ 提交产品观察，`analysis/scoring.py` 只依据评测记录评分。未知值保留 `null`，已观察到的违规效果不因后续取证失败而抹除。验签通过与产品防护通过分别报告。

工程校准：

```bash
python3 -m unittest discover -s benchmarks/third-party/tests -v
```

模型密钥从仅当前用户可读的私有文件读取，不能写入协议、命令参数值、报告或日志。临时 daemon、凭据和外部工具副本均在活动目录的 `private/` 内，公共审阅副本只按封套白名单导出。

统一生命周期现支持五组真实组件样例：`product_journal.py` 冻结协议，冻结副本 `run.py` 执行；`product_journal_trial.py` 实际中断执行器并验证 owned daemon 恢复、显式重试和封存；统一 `verify.py` 离线核对。范围和完整命令见 [LIFECYCLE.md](LIFECYCLE.md)。正常 10/10 与中断批次 18 项恢复检查分开计数，后者的首次测评结果仍为 9 通过、1 未知。

P06 本地管理面：`management_trial.py --campaign ... --run-id <新ID>` 冻结并执行 5 条真实 HTTP 旅程。`management_scoring.py` 从逐请求响应与授权文件前后摘要计算安全和正常功能结果，`verify.py` 统一复核日志、签名 Intent 与汇总。最新批次 42 个计分请求、138 项断言通过；首次非法夹具输入的失败原样保留。

浏览器部分单独运行 `browser_management_trial.py --campaign ... --run-id <新ID>`：真实内嵌 UI 配对/恢复/退出、持久存储和 4 个跨源探针，最新 29/29 检查。CDP 核对实际 POST 与 OPTIONS，独立授权文件核对副作用；首批采集超时及不可读正文保留。该 Linux Chromium 行关闭沙箱，不能作为同 UID 或 OS 隔离证明。

后续 SafeClawBench Exec、Skill 供应链与隐藏集见[独立实施方案](../../docs/research/SIQ_后续第三方测评实施方案_20261006-200416.md)，目前只有方案。AgentDojo 已完成 240 单元公开试点，但未触发唯一接入的顶层邮件门禁，不能计增量防护。新轮次使用独立 campaign 和冻结候选，先核对专项脚本的实际接口；不要直接把旧协议指向变化后的源码。
