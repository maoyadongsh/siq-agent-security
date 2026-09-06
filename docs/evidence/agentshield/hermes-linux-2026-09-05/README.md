# Hermes / Linux 证据（DGX Spark，2026-09-05）

主机：NVIDIA DGX Spark，`linux/arm64`。二进制 `agentshield 0.1.0`（本机构建，未走 GitHub Release URL）。

`support_matrix` **未**改为 `supported`。L0–L2 路径已有实机证据；OpenShell 网关未配置，L3 不宣称。改矩阵须重签 `skill-manifest.json`。

## 清单

| # | 要求 | 结果 | 文件 |
| --- | --- | --- | --- |
| 1 | 恶意 fixture → `quarantine`，退出码 3 | 通过 | `02-admit-toxic.json` |
| 2 | 官方风格 fixture → `admit_with_conditions` | 通过 | `03-admit-official-like.json` |
| 3 | 人类批准 grant | 通过：`--approve-as maoyd`，随后 `deploy` | `10-grant-approved-maoyd.json` |
| 4 | 越权工具调用 → deny | 授前 default-deny 见 `06`；授后 `web_fetch` → `tool web_fetch not granted` | `11-overreach-after-grant.json` |
| 5 | `agentshield verify` | 通过；批准后 `receipts=3` | `07-verify.json`、`12-verify-after-grant.json` |
| 6 | OpenShell probe / 网络段读回 | 未配置，保持 experimental | `08-openshell-probe.json` |

本地控制台：`GET http://127.0.0.1:47611/` → 200 HTML（`01-ui-http.json`）。token 不进证据。

已执行的批准命令：

```bash
export AGENTSHIELD_STATE_DIR=/home/maoyd/siq/siq-agent-security/apps/agentshield/.state
cd /home/maoyd/siq/siq-agent-security/apps/agentshield
./agentshield grant approve grt-4af17a9f9719-bebf3ee8 --approve-as maoyd
./agentshield grant deploy grt-4af17a9f9719-bebf3ee8
```

## 脱敏

- 无 token、无 signing seed、无参数原文
- 路径写成 `$HOME` / `$REPO`
- finding excerpt 与回执 `sig` / `params_excerpt` 已替换为长度 + sha256 前缀
