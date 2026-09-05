# CodeBuddy / Linux 证据（DGX Spark，2026-09-05）

主机：NVIDIA DGX Spark，`linux/arm64`。二进制 `agentshield 0.1.0`（本机构建，未走 GitHub Release URL）。

`support_matrix` **未**改为 `supported`。CodeBuddy 无装前钩子；本目录是隔离 `$HOME` 上的 L2 钩子合同闭环：真实 `agentshield hook codebuddy` 读 PreToolUse stdin、打本机决策 API。 **没有**驱动 CodeBuddy GUI 客户端。未改操作者真实的 `~/.codebuddy`。

## 清单

| # | 要求 | 结果 | 文件 |
| --- | --- | --- | --- |
| 1 | 适配器安装写入 PreToolUse / PostToolUse | 通过；随后卸载还原 | `01-adapter-install.json`、`01c-codebuddy-hooks.json`、`10-adapter-uninstall.json` |
| 2 | 恶意 fixture → `admit` `quarantine`，退出码 3 | 通过 | `02-admit-toxic.json` |
| 3 | 官方风格 fixture → `admit_with_conditions` | 通过 | `03-admit-official-like.json` |
| 4 | 授前越权钩子 → default-deny | 通过：`permissionDecision=deny` | `04-hook-overreach-before-grant.json` |
| 5 | 人类批准 grant | 通过：`--approve-as maoyd`，随后 `deploy` | `06-grant-approved-maoyd.json` |
| 6 | 授后越权工具 → deny | 通过：`tool WebFetch not granted` | `07-hook-overreach-after-grant.json` |
| 7 | `agentshield verify` | 通过；`receipts=2` | `08-verify.json`、`09-receipts.json` |

已执行的批准命令（隔离状态目录，不是现场 `apps/agentshield/.state`）：

```bash
./agentshield grant approve grt-4af17a9f9719-260a2709 --approve-as maoyd
./agentshield grant deploy grt-4af17a9f9719-260a2709
```

## 脱敏

- 无 token、无 signing seed、无参数原文
- 路径写成 `$HOME` / `$REPO` / `$BIN`
- finding excerpt 与回执 `sig` / `params_excerpt` 已替换为长度 + sha256 前缀
