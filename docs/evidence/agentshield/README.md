# AgentShield 实机证据

本目录归档评委可核验的脱敏录屏与回执，命名：`<platform>-<YYYY-MM-DD>/`。

当前快照：**尚无归档证据**。因此 `skills/agentshield/skill-manifest.json` 的 `support_matrix` 没有任何 `supported` 行。

## 每条证据最少包含

1. `admit` 恶意 fixture → `quarantine` 的 stdout（已脱敏）
2. `admit` 干净 / 官方风格 fixture → `admit_with_conditions`
3. 人类批准 grant 的命令行（可打码姓名）
4. 一次越权 deny 回执 JSON（无参数原文）
5. `agentshield verify` 通过
6. 可选：OpenShell `probe` / 网络段 `apply` 读回（Linux）

不要提交 token、私钥、完整家目录路径、客户文档。

DGX Spark 上拉同一功能分支后，把本目录填上，再把对应矩阵行从 `experimental` 改为 `supported`（须同时重签 `skill-manifest.json`）。
