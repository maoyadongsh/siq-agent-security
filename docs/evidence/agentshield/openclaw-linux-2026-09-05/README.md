# OpenClaw / Linux 证据（DGX Spark，2026-09-05）

主机：NVIDIA DGX Spark，`linux/arm64`。二进制 `agentshield 0.1.0`（本机构建，未走 GitHub Release URL）。

`support_matrix` **未**改为 `supported`。本目录是隔离 `$HOME` 上的适配器合同闭环：L1 走真实 `policy-exec`；L2 走插件会发出的 `POST /v1/decide` 请求体。 **没有**把插件挂进本机正在跑的 OpenClaw 网关进程（该进程占用 `18789`，且不是本次证据的目标）。未改操作者真实的 `~/.openclaw`。

## 清单

| # | 要求 | 结果 | 文件 |
| --- | --- | --- | --- |
| 1 | 适配器安装写入 `installPolicy` + 插件 | 通过；随后卸载还原 | `01-adapter-install.json`、`01c-openclaw-json-snippet.json`、`10-adapter-uninstall.json` |
| 2 | 恶意 fixture → `policy-exec` `block` / `quarantine` | 通过：`user_deception, credential_exfil` | `02-policy-exec-toxic.json` |
| 3 | 官方风格 fixture → `warn` / `admit_with_conditions` | 通过 | `03-policy-exec-official-like.json` |
| 4 | 授前越权 → default-deny | 通过：`web_fetch` deny | `04-overreach-before-grant.json` |
| 5 | 人类批准 grant | 通过：`--approve-as maoyd`，随后 `deploy` | `06-grant-approved-maoyd.json` |
| 6 | 授后越权工具 → deny | 通过：`tool web_fetch not granted` | `07-overreach-after-grant.json` |
| 7 | `agentshield verify` | 通过；`receipts=2` | `08-verify.json`、`09-receipts.json` |

已执行的批准命令（隔离状态目录，不是现场 `apps/agentshield/.state`）：

```bash
./agentshield grant approve grt-4af17a9f9719-f33ebb37 --approve-as maoyd
./agentshield grant deploy grt-4af17a9f9719-f33ebb37
```

## 脱敏

- 无 token、无 signing seed、无参数原文
- 路径写成 `$HOME` / `$REPO` / `$BIN`
- 回执 `sig` / `params_excerpt` 已替换为长度 + sha256 前缀
