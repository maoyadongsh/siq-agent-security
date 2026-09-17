# OpenClaw A05 诊断证据

本次 WSL2/Linux 正对照 **A 失败**；终端错误 stack 已取得，诊断采集和资源收尾完成。Node、namespace child、WSL 传输实际均以 1 退出。provider 请求 0，工具目标未创建。

实际 stack 记录 `ERR_ACCESS_DENIED`、`lstatSync`，并指向 `dist/openclaw-agent-db-registry-CQNE3K5p.mjs:392:17`。具体被拒资源没有被观测；本批不推测缺失目录或具体路径，不把本次帧倒推为 A04 根因。

- [报告](report.md)：结果与证据边界。
- [结构化摘要](summary.json)：显式白名单字段及八条原始流的长度/SHA。
- [来源索引](raw-source-index.json)：功能角色与私有原件摘要。
- [派生文件清单](manifest.json)：上述四个公开内容文件的摘要。

本批未运行 SIQ，B 未运行，不能记作 Windows 原生 OpenClaw 验收。未改变原 18 行矩阵、分母或产品 runtime；A04 失败保留。交付前检查见 [验证记录](verification.json)。
