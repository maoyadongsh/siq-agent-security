# R05-C 最终候选双宿主运行时合同核验

- 时间：2026-09-14T21:16:00+08:00
- 主机：Linux/aarch64
- 候选 SHA256：`f4b5c23cfff4f89608b1e113b36858c2938d6f8e06630b6e9031c7665c77420c`
- OpenClaw：`2026.5.12 (f066dd2)`
- Hermes：`0.21.0 (2026.8.31)`
- 结果：两个真实宿主运行时合同均通过；没有模型/工具调用，R05/N04 仍 partial

## 方法与结果

在 `/tmp/siq-host-runtime-contract-20260914-2115` 建立全新 HOME、XDG、Hermes 与 SIQ 状态目录。当前候选分别安装两个适配器，真实宿主 CLI 验证后再由候选卸载。

OpenClaw 执行 `plugins inspect siq-agent-security --runtime --json`，返回 `status=loaded`、`activated=true`、`hook_count=2`，typed hooks 为 `before_tool_call` 和 `after_tool_call`。

Hermes 对候选实际安装目录执行 `plugins doctor ... --ci`，runtime discovery、manifest parsing、import、registration 全部 OK，注册 0 tools、2 hooks，无警告。此前发现的 `provides_hooks` 缺失已经修复。

卸载后两个插件入口均不存在；OpenClaw 原 `gateway.mode=local` 与 Hermes 原 `model: test-fixture` 均保留。测试完成后专用临时目录被删除。

## 边界

本报告绑定最终候选，证明真实 OpenClaw/Hermes 可以加载或导入当前适配器并识别两个工具钩子，也证明基本安装/卸载不会删除所测无关配置。没有启动 agent turn、模型或真实工具调用；未证明最终参数上的 allow/deny、SEC 因果归属、hold 重试或结果观察。后续原生执行证据仍需受控、无破坏性工具调用。

