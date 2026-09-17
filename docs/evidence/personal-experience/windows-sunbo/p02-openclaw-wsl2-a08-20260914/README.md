# OpenClaw A08 插桩诊断证据

本批一次 WSL2/Linux 插桩诊断：行为 A 仍 fail，目标不存在；诊断完成，cause 捕获完整。捕获的 permission/resource 是实际空字符串，name/syscall absent，stack 明确跳过。cause 只能关联同一受控进程，没有 CALL_ID 绑定。

A08 使用内存源码插桩，不能作为未插桩 A 通过、修复完成、SIQ/B 或 Windows 原生平台验收。原 A04–A07、原18行矩阵与分母保持；本批一次插桩运行独立记载。

report.md 解释结论与限界，summary.json 保存白名单字段，raw-source-index.json 仅列来源身份，manifest.json 固定四份内容摘要。Run 为8条原始流；Plan加Run共12条记录。原始nonce、进程身份、私有路径、模型消息和日志正文均未复制。公开材料已由主任务审阅，按独立证据提交归档；实际平台判定见 report.md。
