# Trusted Intent V2：原生平台审批与本地 hold 的执行缺口

- 时间：2026-09-07 21:11，Asia/Shanghai。
- SIQ 代码基线：`78e740a01fa9c46cfb256fa2d84c2cf0739bdb2e`；新增验证脚本在工作树中，生产代码未修改。
- OpenClaw：本机 `2026.5.12` 原始安装；具体选取的源码指纹见归档。
- 状态：**原生运行时已复现，尚未修复**。此项阻止将完整审批链路标为验收通过。

后续更新：21:33 的[执行前门禁修复报告](trusted-intent-v2-approval-gate-validation-20260907-213332.md) 已验证对下述缺口的修复。本文与原始失败归档保留为 21:11 历史证据，复现旧行为需使用 `78e740a` 的 daemon/适配器与本文列出的旧夹具；验证当前工作树应使用新报告中的 gate 脚本。

## 1. 结果

在原生 OpenClaw 网关、真实 operator WebSocket 和原生工具前置包装器中，平台 `allow-once` 会继续执行工具，即使 SIQ 的本地 hold 尚未批准或已经明确拒绝。

SIQ 对这些动作的 `/v1/observe` 拒绝仍然有效；但该拒绝发生于工具执行之后，无法阻止本次执行。因此“没有成功 observation”不能作为“没有执行”的证据。

| 场景 | 平台决议 | SIQ 本地决议 | 合成工具实际执行 | 成功 observation | 执行前门禁 |
| --- | --- | --- | --- | --- | --- |
| platform-deny | deny | 未处理 | 否 | 0 | 通过 |
| both-approve | allow-once | 批准 | 是 | 1 | 通过 |
| local-missing | allow-once | 未处理 | **是** | 0 | **失败** |
| local-reject | allow-once | 拒绝 | **是** | 0 | **失败** |

最终进程退出码为 **1**；报告 `passed=false`、`observation_invariants_passed=true`。四条 hold 决策、两条本地处理回执和一条 observation 共七条签名回执，HTTP 读取及离线验签通过。

原始摘要归档：[native-openclaw-approval-gap-20260907.json](evidence/intent-v2/native-openclaw-approval-gap-20260907.json)。其中记录每个场景的执行结果、观察数量、SIQ 二进制、脚本、适配器及相关 OpenClaw 源码 SHA-256。它是验证摘要及来源记录，不是完整签名回执导出包，也不是整个 OpenClaw 模块加载追踪。

## 2. 验证路径与边界

```text
临时 SIQ daemon：optional / block，已批准部署且保留 exec 逐次审批的 Grant
    ↓ 原生插件 POST /v1/decide
签名 hold
    ↓ requireApproval
原生 OpenClaw 网关 plugin.approval.request
    ↓ 真实 WebSocket 事件到合成 operator
夹具确认工具尚未执行，按场景调用 SIQ 管理 hold 或保持未处理
    ↓ operator 经真实 WebSocket 发送平台决议
原生前置包装器决定是否调用合成工具 execute
    ↓ 临时文件记录工具是否实际被调用
若已执行：调用原生 after relay → SIQ /v1/observe
    ↓ 校验唯一决策、授权结果、动作关联、回执链
```

使用原生插件加载器显式激活 SIQ，并断言插件加载成功。网关、审批请求/等待/处理、operator 客户端和前置包装器均来自本机运行时；没有替换这些函数或伪造它们的 HTTP/WebSocket 响应。

工具执行器是合成函数：工具名称为 `exec`，参数固定为 `printf fixture`，执行时只写临时标记文件，**不会执行该命令字符串**。这证明原生门禁是否调用受保护执行器，不宣称复现了真实 shell、外网或生产数据副作用。after relay 由夹具调用，不是完整模型会话自动触发。

夹具只用临时网关 token 和临时 SIQ 管理会话；SIQ 管理会话由 Python 操作者持有，未交给适配器。没有真实模型、消息渠道或人类点击。插件只接收原有 decision token。网络连接限定为两个临时 loopback 服务；该测试 IO 限制不是 OS 安全隔离。

该场景刻意使用 `optional` 下未绑定 Intent 的 hold。`required` 且绑定 Intent 的任意 shell 命令仍因 `unknown` 副作用提前拒绝；本轮没有放宽该限制，不能把本次失败外推为所有 required/bound 调用的同类绕过。

## 3. 原因与修复约束

[OpenClaw 适配器](../adapters/runtime/openclaw-agentshield/index.ts) 将 hold 直接映射为 `requireApproval`。平台包装器在平台决议为 `allow-once/allow-always` 时返回可执行结果；此路径没有再次确认 SIQ 本地 hold 的批准状态。与之相比，SIQ Observe 强制要求本地批准，两处对“已批准”的认定没有在执行之前衔接。

原生 `onResolution` 采用不等待完成的异步回调，失败只记录警告。因此直接添加“回调里异步请求 SIQ 批准”不构成可靠执行门禁；把管理 token 放入适配器也违反权限边界。

修复必须建立实际执行之前可等待、可拒绝的本地授权检查，并保留平台自己的拒绝。可行设计需要评估原生 hook 的超时与取消语义：本地批准尚未完成时不得返回可执行结果；本地拒绝、到期、服务不可达或关联不匹配必须终止；双方允许仍应能够执行。不能仅把所有 hold 永久转成 deny 后就宣称审批功能完成。

已有 `POST /v1/hold/{receipt_id}` 的管理权限、回执幂等与恢复约束继续保留。若新增 decision 侧只读状态接口，必须绑定原动作身份、工具调用 ID、参数摘要与前置回执；不能允许该接口签发或批准自己的授权。还需补充本地批准等待、平台批准等待、取消、超时、强杀及恢复的实际执行断言。

## 4. 复测命令

在仓库根目录运行：

```bash
python3 scripts/validate-intent-v2-openclaw-approval.py \
  --openclaw-root /home/maoyd/.nvm/versions/node/v22.22.1/lib/node_modules/openclaw \
  --node /home/maoyd/.nvm/versions/node/v22.22.1/bin/node \
  --out /tmp/siq-openclaw-approval-validation.json
```

依赖 Go、Python、Node 和可用的本地 OpenClaw 安装。执行后检查 JSON 中的四个场景；当前代码应退出 1，不能把非零退出隐藏后当成成功测试。临时网关、daemon、工具标记、配置和凭据在结束时清理，未更新实际安装或真实用户配置。

脚本入口为 [validate-intent-v2-openclaw-approval.py](../scripts/validate-intent-v2-openclaw-approval.py)，原生工作进程为 [openclaw-approval-worker.mjs](../scripts/openclaw-approval-worker.mjs)。Ruff、JavaScript 语法和来源指纹校验均通过；功能结果仍明确为失败。

## 5. 验收状态

`78e740a` 的 28/28 远端 CI 成功仍成立，但该 CI 未运行本原生网关夹具，不能据此否认此缺陷。能力矩阵的综合状态保持 `unverified`。本轮将此前静态检查发现的审批衔接疑点推进为可复现的动态失败；优先完成执行前门禁修复，再继续网关 reset、旧适配器兼容、CodeBuddy 实机与独立复核。
