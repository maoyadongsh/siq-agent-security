# R02-F Linux/OpenClaw 审批后签名预留验收

日期：2026-09-15。结论：OpenClaw 2026.5.12 的原版/配套检查点宿主共 18/18 场景通过；Linux/OpenClaw 的 R02 原生控制路径达到阶段门槛。候选来自当前未提交工作树，未发布，也未修改本机 OpenClaw 安装。

## 修复内容

此前 OpenClaw 在平台批准后只调用 `/v1/hold-status` 做只读快照，未消费 R02 的签名执行预留。当前适配器在宿主 `beforeExecute(finalParams, signal)` 检查点内完成以下动作：

1. 用原 hold 身份和最终参数重查本地批准与当前权限。
2. 从签名 action、decision receipt 和原生 call ID 派生独立执行尝试 ID；该值不能由模型文本、参数或用户配置提供。
3. 调用 `/v1/hold-executions/reserve`，只有匹配且未过期的 HTTP 201 `reserved` 响应才向宿主返回 true。
4. 执行后 observation 使用执行尝试 ID、预留时的参数快照和 reservation receipt；原 hold 与实际执行仍可沿 action ID 关联。

预留被拒、格式错误、响应丢失、重复回调、参数变化、授权撤销、超时、取消或 daemon 失联均返回 false。预留已持久化但响应丢失时保留 `uncertain`，不自动重试，需管理员核对外部副作用后结案。

## 原生结果

验收使用真实 OpenClaw gateway WebSocket、审批管理器、配套补丁后的原生 tool wrapper、当前 shipping adapter、真实 SIQ daemon/签名链，以及隔离 profile。原版宿主也实际加载当前适配器，证明缺少受信检查点时 hold 在平台审批前拒绝。

| 分组 | 场景 | 执行 | 签名预留/observation |
| --- | ---: | ---: | ---: |
| 原版宿主不兼容拒绝 | 1 | 0 | 0 / 0 |
| 双审批与各类拒绝 | 6 | 1 | 1 / 1 |
| 平台等待期间撤销 | 2 | 1 | 1 / 1 |
| 回调、参数、取消、超时和失联故障 | 9 | 1 | 1 / 1 |

三个正向执行各自只有一条 `hold_reservation` 和一条 observation；retry tool-call ID 与原 hold 的 native call ID 不同，observation 的 `decision_receipt_id` 等于对应 reservation receipt。全部四条独立回执链离线验签通过。

## 身份与边界

- 候选二进制 SHA256：`b6e7650f9ab35f6b259cbd64fe9be5a19347b3689ed3dab0be38874d4bda6708`
- Shipping adapter SHA256：`c293bd0979050e042244f0f4723524ffe4302d48f0ccbfa8e0f3b109105512a5`
- 总验收 runner SHA256：`286c605b2150da6edde5e804ba24e4c4caa0c5ce90ec026921cfa683dab82111`
- OpenClaw 宿主补丁 SHA256：`3739f75e28996dc3253b28ff4ff8f2d3288e937f329159be7c8b7cefee376a64`
- 机器范围：Linux/aarch64，OpenClaw 2026.5.12；原版安装只读，补丁只应用到临时副本。
- 工具执行器和两层批准操作者为确定性测试夹具，没有调用模型，也没有证明真人点击、桌面通知投递或真实外部系统副作用。
- 配套检查点尚未成为 OpenClaw 官方 SDK 能力；原版宿主继续安全拒绝 hold，不能描述为开箱即用的完整审批。
- 本地签名预留与外部工具副作用不是跨系统原子事务，不承诺 exactly-once。

机器可读结果见 [report.json](report.json)，文件摘要见 [SHA256SUMS](SHA256SUMS)。
