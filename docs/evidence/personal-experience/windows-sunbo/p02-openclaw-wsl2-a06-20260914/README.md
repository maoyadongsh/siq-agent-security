# OpenClaw A06 独立子批证据

本次 WSL2/Linux **A 失败，diagnostic_completed=true，terminal_stack_marker_observed=true**。一次 provider 请求携带 apply_patch/read/write，触发原工具集合校验；固定 write 响应未下发，目标不存在。

[报告](report.md)说明实际结果与限界；[摘要](summary.json)记录白名单事实；[来源索引](raw-source-index.json)仅记录功能角色、字节数及 SHA；[清单](manifest.json)固定四个公开内容文件。

来源上下文为干净的 fd2cdba7c9d5111bc5fd475651fb6453d5b45d15，仅为 A05 文档后继背景，不冒充安装包身份。SIQ 从未运行，B 未运行；这不是 Windows 原生 OpenClaw 或完整平台验收通过。旧尝试、原 18 行矩阵和分母均保留。verification 由主任务另行生成，本目录不含原始日志、环境值、私有路径、进程身份或提示正文。
