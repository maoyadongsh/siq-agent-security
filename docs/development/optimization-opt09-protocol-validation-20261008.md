# OPT-09 企业 OpenShell 行为协议与校验器（2026-10-08）

本批完成 ADR-058、单次行为挑战合同、版本化观测结果合同和纯候选证据校验器。58 项新用例及 63 项原 v1 探针回归通过，Ruff 通过。全部观测均为合成组件输入，没有启动真实探针、调用模型或提升部署等级。

## 解决的协议缺口

企业部署入口目前只调用配置读回验证，未传入行为证据。旧 enforcement-probe/v1 绑定目标／指纹／revision／digest，但没有挑战时效和持久消费语义。新实现按[ADR-058](../adr/0058-enterprise-openshell-behavior-verification.md)独立版本化，不改写旧证据含义。

| 新约束 | 验证内容 |
| --- | --- |
| 操作与权限范围 | 租户、环境、RuntimeBinding、Deployment、既有 apply operation、目标和网关指纹逐项绑定 |
| 运行身份 | 策略 revision／digest、镜像摘要、相同 ELF 探针内容及受保护执行身份摘要固定；真实身份核验仍由后续收集器负责 |
| 时效与资源预算 | 挑战最长五分钟、3–10 轮、有界单次超时；窗口须覆盖计划超时预算，完成结果和全部观测均在窗口内 |
| 差分对照 | 同一批准 IPv4 TCP 接收端，每轮前可达性对照、允许路径、拒绝路径、后可达性对照；规则集合必须允许前者而不允许后者 |
| 重复与错配 | nonce、验证 ID、挑战摘要、轮次／顺序／来源／端点／程序摘要均核对；旧操作状态不再 eligible |
| 失败归因 | DNS 失败、探针错误不算拒绝成功；允许臂或任一可达性对照失败均不能接受 |
| 前后漂移 | 观测前后策略读回须与可信调用方提供的当前读回一致；目标、策略或保护身份变化即拒绝 |

“纯校验器拒绝已消费状态”不等于已经实现持久防重放。调用方仍需从持久状态读取 running、验证实时授权，并原子消费结果；不允许用客户端自填 running 代替这个过程。校验器成功返回的是候选观测可接受，不直接生成 enforcement_verified。

## 源码与验证

- [挑战合同](../../packages/contracts/openshell-behavior-challenge.v1.schema.json)
- [结果合同](../../packages/contracts/openshell-behavior-result.v2.schema.json)
- [纯校验器](../../apps/control-api/app/adapters/openshell/behavior_protocol.py)
- [定向测试](../../apps/control-api/app/tests/test_openshell_behavior_protocol.py)
- [本批机器记录](evidence/optimization-20261007/enterprise-behavior-protocol.json)

在 apps/control-api 执行：

```bash
uv run --frozen pytest -q app/tests/test_openshell_behavior_protocol.py app/tests/test_enforcement_probe.py
uv run --frozen ruff check app/adapters/openshell/behavior_protocol.py app/tests/test_openshell_behavior_protocol.py
```

新用例覆盖有效候选、合同 schema、非 running 状态、十二类当前身份／策略漂移、前后漂移、其他挑战重放、到期边界、未来结果、过长／不足时间窗、畸形与非有限输入、可达性及探针失败、程序替换、重复／缺失轮次、非 block 配置、错误允许集和客户端自述成功。原 v1 校验器、观测通道和生产部署入口源码摘要保持不变。

## 剩余验收

OPT-09 从 planned 进入 implementing；已完整验收任务仍为 9/16。下一批实施持久协调和审计、原子消费／崩溃不重放，再接入可信 ELF 收集器、企业 API／前端及真实 OpenShell 三臂效果验收。当前企业等级仍为配置读回，不能用本批 121 项组件测试代替真实行为验证。IPv6、DNS、重定向和替代程序路径继续单列缺口。
