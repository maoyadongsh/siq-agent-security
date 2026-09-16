# R05-B OpenClaw 真实运行时加载核验

- 时间：2026-09-14T20:46:00+08:00
- 主机：Linux/aarch64
- OpenClaw：`2026.5.12 (f066dd2)`
- 候选 SHA256：`10dedfb776d736c838593b28d24cac77e06eb2788615a74cd4c5f3ae9f46d617`
- 证据类型：真实 OpenClaw CLI 加载插件运行时；不是模型或工具调用证据
- 结果：pass，R05/N04 仍 partial

## 验证过程

在专用 `/tmp/siq-openclaw-runtime-probe-20260914-2045` 下创建全新 HOME、XDG 配置和 SIQ 状态目录，只写最小 `gateway.mode=local` 配置。随后：

1. 使用当前候选执行 `init` 和 `adapter install openclaw`。
2. 将 wrapper 的 `OPENCLAW_NODE_BIN`、`OPENCLAW_MJS` 显式指向本机已安装的 OpenClaw，保持 HOME 指向隔离目录。
3. 执行真实宿主命令 `openclaw plugins inspect siq-agent-security --runtime --json`。
4. 使用当前候选执行 `adapter uninstall openclaw`，读回隔离配置和文件状态。

OpenClaw 返回：插件 `id=siq-agent-security`、`version=0.3.0`、`enabled=true`、`activated=true`、`status=loaded`、`imported=true`，发现两个 typed hooks：`before_tool_call`（priority 10）与 `after_tool_call`。插件形态为 `hook-only`，OpenClaw 将该形态标为仍受支持的兼容路径，并提示尚未迁移为显式 capability registration。

卸载后插件入口不存在，配置不再含 SIQ 标识，原 `gateway.mode=local` 保留。整个过程只涉及隔离目录，没有读取或修改日常 `~/.openclaw`。

## 结论边界

- 这证明当前 OpenClaw 真实运行时能够导入并加载 SIQ 的前后工具钩子，强于静态文件存在检查。
- `hook-only` 兼容提示应纳入后续适配计划；当前版本仍成功加载，不能据此推导未来版本永久兼容。
- 没有启动 gateway、模型或 agent turn，没有执行真实工具；因此没有证明钩子在最终工具参数上完成允许/拒绝、SEC 归属、hold 恢复或观察回执。
- 后续原生门槛需在隔离会话里实际调用无破坏性工具，并记录钩子前后、SIQ 决策及零越权副作用。需要模型调用时必须先说明模型与费用范围。

