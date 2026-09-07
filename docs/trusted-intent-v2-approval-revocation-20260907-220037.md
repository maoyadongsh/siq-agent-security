# Trusted Intent V2：平台审批等待期间的 Grant 撤销验收

- 时间：2026-09-07 22:00，Asia/Shanghai。
- 发布代码基线：`87fd1ce3b6b7967c94846a798b4fca868aedd857`。
- 运行时：OpenClaw 2026.5.12、Node v22.22.1、linux/arm64。
- 结论：**默认适配器与原版运行时存在审批等待期间撤销未阻断执行的缺口**。配套候选补丁在独立临时副本通过对照验收；未应用到本机安装或默认适配器，不能把生产组合标为已修复。

## 1. 复现的执行顺序

[已有修复](trusted-intent-v2-approval-gate-validation-20260907-213332.md) 保证进入平台审批前先取得本地批准，但这个检查发生在平台等待之前。本轮在真实网关 WebSocket 流程中插入一次管理面 Grant 撤销：

```text
SIQ 产生 signed hold
  → 合成管理员批准本地 hold
  → 原生网关发布平台审批请求，工具尚未执行
  → 合成管理员通过正式 Grant API 撤销该 Grant
  → decision token 查询 hold-status：denied / hold_authority_changed
  → 原生平台 operator 回复 allow-once
  → 原版包装器继续执行工具，随后接收 observation
```

Grant 撤销使用实际管理 API、预期 revision 和签名状态变迁，没有改写磁盘 Grant 或模拟 HTTP 授权结果。工具是原生前置包装器包裹的合成执行器，只写临时标记文件，不执行 command 字符串或调用真实模型。

| 场景 | 平台批准之前的本地状态 | 实际执行 | observation | 安全期望 |
| --- | --- | --- | --- | --- |
| 正常对照：双方批准 | approved | 是 | 1 | 允许，符合 |
| 平台等待时撤销 Grant | denied / hold_authority_changed | **是** | **1** | 不执行，不符合 |

测试 [validate-intent-v2-openclaw-approval-revocation.py](../scripts/validate-intent-v2-openclaw-approval-revocation.py) 退出码为 1，原始 [失败归档](evidence/intent-v2/native-openclaw-approval-revocation-20260907.json) 为 `passed=false`。六条回执均可验签，动作身份关联校验通过；这两个事实不能抵消已经发生的越权执行。

本轮没有把 Observe 改为“按接收时权限拒绝历史结果”。它关联的是原先已批准的 Decision；其接受不能当作执行瞬间 Grant 仍有效的证明。仅拒绝执行后的 observation 也无法阻止工具已经发生的副作用。

## 2. 宿主执行边界

原生 `requestPluginToolApproval` 在 `allow-once` 或 `allow-always` 后直接返回可执行结果。`onResolution` 使用非等待式 `Promise.resolve(...).catch(...)`，回调的返回值和异步失败不参与执行许可，因此不能把它当成可靠的最后一道门禁。

原有 `/v1/hold-status` 已能正确识别撤销；缺失的是平台审批结束后、调用工具之前的可等待、可否决检查点。本轮没有为了通过测试削弱 Grant 撤销，也没有把所有 hold 永久阻断来替代正常审批功能。

## 3. 配套候选补丁

候选包含两个必须配套的变更，清单位于 [2026.5.12-approval-execution-recheck.json](../patches/openclaw/2026.5.12-approval-execution-recheck.json)：

1. [原生包装器补丁](../patches/openclaw/2026.5.12-approval-execution-recheck.patch)：新增局部 `beforeExecute(finalParams, signal)` 检查点，在平台允许之后等待它完成；仅严格返回 `true` 才继续。拒绝、异常、取消或超过五秒预算均形成执行前 veto。传入最终合并后的参数，定时器与外部取消监听在结束时清理。既有 `onResolution` 通知语义不变。
2. [适配器候选补丁](../patches/openclaw/2026.5.12-approval-recheck-adapter.patch)：为 hold 提供该回调，使用原服务端动作身份和最终参数重新查询本地状态，额外预算一秒；只有仍 approved、身份与参数匹配、原 hold 未过期且未取消才返回 true。继续只使用 decision token，没有管理凭据或新签名逻辑。

`beforeExecute` 是本项目的**候选扩展**，不是 OpenClaw 官方现有 API。原版宿主会忽略它；只打适配器补丁不能修复漏洞。原生补丁对未提供回调的其他插件保留旧行为；只打宿主补丁也不会自动为 SIQ 添加授权查询。因此不能仅检查版本字符串或某个文件存在就宣称能力生效。

当前未把任一候选合并进默认安装资产。采用前应确认宿主支持、配套版本、加载的实际文件指纹和执行否决负向测试；平台综合状态仍为 `unverified`。

## 4. 临时副本验收

[验证入口](../scripts/validate-openclaw-approval-recheck-patch.py) 先检查包名、版本、原生源文件、适配器源文件及两个补丁的 SHA-256，再独立复制完整运行时。在副本执行 `git apply --check`、应用原生补丁和 JavaScript 语法检查；适配器补丁只应用到每个场景临时安装的插件。复制使用独立文件，不使用硬链接。

| 验收组 | 结果 |
| --- | --- |
| 原有六个场景：双方批准、平台拒绝、本地未批准、本地拒绝、平台取消、daemon 失联 | 6/6 通过；仅双方批准执行，12 条回执验签通过 |
| 正常批准对照 | 工具执行一次，产生一条关联 observation |
| 平台等待期间撤销 Grant | 状态先确认为 denied；平台再允许后，工具执行 0 次、observation 0 条 |
| 撤销组回执链 | 五条回执，HTTP 与离线验签通过 |
| 本机原安装、仓库默认适配器 | 运行后 SHA-256 与运行前一致 |

总计八个场景通过，验证入口退出码 0。完整 [候选补丁归档](evidence/intent-v2/native-openclaw-approval-recheck-patch-20260907.json) 显式区分 `baseline_project_sources` 与实际加载的 `executed_adapter_sha256`，同时记录实际原生包装器指纹、配套补丁清单和 runner 指纹。普通六场景与撤销组各使用独立状态；前者的强杀恢复不会污染后者。

复测原版缺口（预期当前基线退出码 1）：

```bash
python3 scripts/validate-intent-v2-openclaw-approval-revocation.py \
  --openclaw-root /path/to/node_modules/openclaw \
  --node /path/to/node \
  --out /tmp/openclaw-approval-revocation.json
```

复测配套候选（预期退出码 0）：

```bash
python3 scripts/validate-openclaw-approval-recheck-patch.py \
  --openclaw-root /path/to/node_modules/openclaw \
  --node /path/to/node \
  --out /tmp/openclaw-approval-recheck-patch.json
```

运行需要 Go、Python、Node、Git 及运行时副本的临时磁盘空间。报告路径不要覆盖原版失败归档；不兼容的版本或指纹应失败退出，不做模糊应用。

## 5. 结论的限制与剩余工作

新增检查点解决了“撤销已完成后，平台才批准”的可复现路径，仍不构成与外部工具副作用原子提交的执行租约。检查返回后发生的并发状态变化、工具内部延迟执行或恶意插件后续变更不在这八个场景的证明范围内。候选中定义了超时与异常失败关闭行为，本轮没有分别注入每一种回调故障；应在采纳前补充这些门禁与最终参数篡改场景。

原生宿主扩展尚未上游采纳，也没有更新实际安装；真实用户审批流程、消息渠道生命周期、CodeBuddy 原生运行时、旧适配器完整兼容及独立复核继续按目标报告跟踪。`87fd1ce` 的 CI 通过仍是该已提交基线的证据，不包含本轮候选补丁和新增脚本。
