# Hermes / Linux 证据（DGX Spark，2026-09-05）

主机：NVIDIA DGX Spark，`linux/arm64`。二进制 `agentshield 0.1.0`（本机构建，未走 GitHub Release URL）。

`support_matrix` **未**改为 `supported`。原因：grant 必须人类 `--approve-as`（本目录只起草、未批准）；OpenShell 网关未配置，L3 不宣称。

## 清单

| # | 要求 | 结果 | 文件 |
| --- | --- | --- | --- |
| 1 | 恶意 fixture → `quarantine`，退出码 3 | 通过 | `02-admit-toxic.json` |
| 2 | 官方风格 fixture → `admit_with_conditions` | 通过 | `03-admit-official-like.json` |
| 3 | 人类批准 grant | **未做**（模型禁止代批） | `04-grant-draft.json` |
| 4 | 越权工具调用 → deny | 通过：Hermes 插件 `pre_tool_call(web_fetch)` → `action=block`；回执 `action=deny`，`reason=no deployed grant for agent (default deny)` | `06-overreach-deny.json` |
| 5 | `agentshield verify` | 通过，`receipts=1` | `07-verify.json` |
| 6 | OpenShell probe / 网络段读回 | 未配置，保持 experimental | `08-openshell-probe.json` |

本地控制台：`GET http://127.0.0.1:47611/` → 200 HTML（`01-ui-http.json`）。`/ui-config.json` 有 token 字段（长度 64），证据里只记形状、不记原文。嵌入 JS 的 `localStorage.setItem` 仅用于导航折叠键，不靠近 token。

## 人类待办（批准后才能做完整 L2 授后越权）

`serve` 需仍指向同一状态目录。把 `<姓名>` 换成你的名字：

```bash
export AGENTSHIELD_STATE_DIR=/home/maoyd/siq/siq-agent-security/apps/agentshield/.state
cd /home/maoyd/siq/siq-agent-security/apps/agentshield
./agentshield grant approve grt-4af17a9f9719-bebf3ee8 --approve-as <姓名>
./agentshield grant deploy grt-4af17a9f9719-bebf3ee8
```

草稿 grant 的 subject 是 `demo`，允许工具 `read_file` / `terminal` / `web_extract`。部署后再用 `agent_id=demo` 调 `web_fetch`，期望 `tool web_fetch not granted`。

## 脱敏

- 无 token、无 signing seed、无参数原文
- 路径写成 `$HOME` / `$REPO`
- finding excerpt 与回执 `sig` / `params_excerpt` 已替换为长度 + sha256 前缀
