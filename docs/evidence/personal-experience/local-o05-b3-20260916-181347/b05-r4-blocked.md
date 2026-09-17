# B05 r4（rc.3 复验）外部阻塞记录 — 2026-09-16

## 结论

B05 无法在本环境对 rc.3 产出有效证据文件。判定为**外部环境漂移**，非 rc.3 候选回归。未产出 `b05-r4-rc3.json`（harness 成功时才写 out 文件，本批如实不写）。

## 证据链

对照实验（同一命令，仅换 `--binary`）：

| binary | 结果 |
| --- | --- |
| rc.3 `4866f307cf0328ca…` | `{"passed": false, "error_type": "RuntimeError", "failure_location": {"file": "openclaw-managed-native-smoke.py", "line": 263, "function": "run_cli"}}` |
| rc.2 `5b52109a43355168…` | 同一断言、同一位置失败 |

失败定位（通过 /tmp/b05-debug 临时插桩副本定位，原 harness 未改动，插桩副本批末清除）：

1. up-leg（服务在线）exec 契约断言失败：
   `b05-up-egress was not rejected while the service was down: 'b05-egress-receiver-ok'`
   — exec 工具被**原生执行**（curl 打到 loopback receiver 并返回 body），而非按契约被 daemon 以
   `runtime_effect_unknown` 拒绝。
2. 失败时刻导出的 daemon receipts 为 `[]`：连 b05-up-write 正控（已执行）也没有任何 decision receipt。
   即插件根本未拦截任何工具调用、未咨询 daemon——不是"决策从 deny 变 allow"，而是 **hook 生命周期未生效**。
3. 环境对照：上一轮 B05 通过记录（`closure-b05-20260915-222208/b05-journey-report.json`）记载
   `openclaw_version = "2026.5.12"`、`passed = true`，用的是真实 `~/.openclaw`。
   当前 `~/.openclaw/node_modules/openclaw/package.json` 版本为 **2026.3.11**（2026.5.12 → 2026.3.11 为降级，
   非本批改动；本批未安装/卸载/升级任何宿主组件）。机器上已无 2026.5.12 副本（NemoClaw、npx 缓存均核查）。
4. 2026.3.11 下插件配置警告仍为
   `plugin id mismatch (manifest uses "siq-agent-security", entry hints "openclaw-siq-agent-security")`，
   但插件 hook 不再触发（零 receipt、原生执行）。

## 影响与后续

- rc.3 的 openclaw 宿主插件路径（B05/B04 宿主原生采集腿）需要 OpenClaw 2026.5.12 或更高版本的真实宿主才能复验。
- rc.2 与 rc.3 在同一环境下失败模式完全一致，可排除本批候选引入回归。
- 不通过降级/升级宿主、不修改 `~/.openclaw` 生产配置来"凑通过"；如实记录为外部阻塞。
- 任务书中 B05 宿主原生腿的"剩余格"在 r4 增加该阻塞原因。

## 调试临时资源

`/tmp/b05-debug/`（插桩副本、run 日志）为本批创建，批末随其他临时资源一并清除。
