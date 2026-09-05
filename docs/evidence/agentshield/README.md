# AgentShield 实机证据

本目录归档评委可核验的脱敏录屏与回执，命名：`<platform>-<YYYY-MM-DD>/`。

当前快照：

- [`hermes-linux-2026-09-05/`](./hermes-linux-2026-09-05/)：DGX Spark（linux/arm64）Hermes 路径。admit 正负样例、`--approve-as maoyd` 批准并 deploy、授后越权 deny、`verify` 已归档。OpenShell 网关未配置。
- [`openclaw-linux-2026-09-05/`](./openclaw-linux-2026-09-05/)：隔离 `$HOME` 上的 `policy-exec`（L1）+ 插件形态 `POST /v1/decide`（L2）。未挂到本机 OpenClaw 网关进程。
- [`codebuddy-linux-2026-09-05/`](./codebuddy-linux-2026-09-05/)：隔离 `$HOME` 上的真实 `hook codebuddy` PreToolUse。未驱动 CodeBuddy GUI。
- `skills/agentshield/skill-manifest.json` 的 `support_matrix` **仍然没有任何 `supported` 行**。

## 每条证据最少包含

1. `admit` 恶意 fixture → `quarantine` 的 stdout（已脱敏）
2. `admit` 干净 / 官方风格 fixture → `admit_with_conditions`
3. 人类批准 grant 的命令行（可打码姓名）
4. 一次越权 deny 回执 JSON（无参数原文）
5. `agentshield verify` 通过
6. 可选：OpenShell `probe` / 网络段 `apply` 读回（Linux）

不要提交 token、私钥、完整家目录路径、客户文档。

矩阵行从 `experimental` 改为 `supported` 须同时重签 `skill-manifest.json`（发布私钥不在仓库）。Hermes Linux 在 OpenShell L3 未配置前不要把含 L3 的那一行改成 `supported`。
