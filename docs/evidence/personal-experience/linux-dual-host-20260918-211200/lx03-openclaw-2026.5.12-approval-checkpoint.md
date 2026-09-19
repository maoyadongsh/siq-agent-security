# LX03：本机 OpenClaw 2026.5.12 原版审批后检查点核查

状态：`blocked_by_installed_host_capability`。证据级别：本机已安装宿主制品的类型与执行路径静态核查；不是原版宿主批准后执行通过证据。核查时间：2026-09-19。SIQ 第六代未签名 Linux/arm64 候选摘要为 `67bc48c4f751f9f6334295b78346e1290bd6f9d1d4e02a8695ca1ef26eb43428`。

| 本机安装包内文件 | SHA256 | 核查点 |
| --- | --- | --- |
| `package.json` | `84cb48b639a69a10703eb9d24c612f8f4780f73163dc09927309a6e0026968f2` | 版本为 `2026.5.12` |
| `dist/plugin-sdk/src/plugins/hook-types.d.ts` | `9d10a31d06e8850d192cd4da9826e4225161177a685c990b60fd802acbf812c4` | `PluginHookBeforeToolCallResult`（约 260 行）有 `block`、`params`、`requireApproval`；其批准类型有 `onResolution`，没有执行前返回布尔值的 `beforeExecute` |
| `dist/pi-tools.before-tool-call-BmZM4hyt.js` | `042d9a61c028964fe320c6217852820d0af9be8628b2762532912db2050cd082` | `requestPluginToolApproval`（约 392–478 行）调用 `safeOnResolution` 后，批准分支直接返回 `blocked:false`；`safeOnResolution` 对 Promise 仅附加错误日志，不等待完成或接受拒绝结果 |

在整个已安装 `dist/` 中搜索 `approvalExecutionRecheckVersion` 无命中；在上述插件类型和执行文件中搜索 `beforeExecute` 无命中。SIQ 适配器 `adapters/runtime/openclaw-agentshield/index.ts` 的 hold 分支要求 `ctx.approvalExecutionRecheckVersion === 1`，随后才提供 `beforeExecute` 回调，在最终参数上重新查询批准并预留唯一执行。这个能力标记在本机原版宿主不存在，因此该分支保持 **fail-closed**；不能把原版宿主的 `onResolution` 当成可阻断执行的异步检查点，也不能把隔离改造副本的通过结果移植到原版。

解除条件：宿主提供并声明受支持的、**等待异步结果且可拒绝执行**的最后检查点，传入最终工具参数与取消信号；SIQ 适配器应在此处重新验证 SEC、Grant、调用绑定和批准状态，并持久化唯一预留，然后分别用真实原版 OpenClaw 验证批准后单次效果、参数漂移、撤权、重放及服务断线。宿主升级后须重新核查版本、类型、执行路径和摘要，并在同一候选上重跑 LX03；仅出现新字段或类型定义不足以证明运行时保证。

本记录不声称 OpenClaw 永远不支持此能力，也不证明其他版本或其他入口的行为。Hermes 真实 CLI 与 SIQ 原版 OpenClaw 的允许、拒绝和 fail-closed 腿继续独立记账。
