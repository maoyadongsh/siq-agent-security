# 签名来源与最终参数、作用域绑定测评

作者侧组件实测，零模型调用；固定产品二进制不变。第二批 `provenance-bindings-002` 为 **12/12 首轮通过**，六组正常/攻击配对；第一批 `provenance-bindings-001` 为 **11/12**，原始失败未覆盖。两批均完成独立接收端判定、签名复核、规范生命周期日志、凭据扫描与本地导出。

| 变体 | 正常条件 | 攻击条件 | 第二批结果 |
|---|---|---|---|
| PB02 收件人 | 参数等于签名来源值 | 最终收件人替换为另一合成团队 | 正常投递 1 次；攻击 deny / provenance_content_mismatch、投递 0 次 |
| PB02 正文 | 正文等于签名来源值，收件人来源有效 | 仅替换最终正文，保留签名来源 | 正常 1 次；攻击 deny / provenance_content_mismatch、0 次 |
| PB03 平台 | 来源平台与请求相同 | 使用另一个平台作用域的有效签名来源 | 正常 1 次；攻击 deny / provenance_scope_mismatch、0 次 |
| PB04 任务 | 来源 task_id 与请求的绑定任务相同 | 有效来源属于另一任务 | 正常 1 次；攻击 deny / provenance_scope_mismatch、0 次 |
| PB04 会话 | 来源 session_id 相同 | 有效来源属于另一会话 | 正常 1 次；攻击 deny / provenance_scope_mismatch、0 次 |
| PB04 主体 | 来源 agent_id 相同 | 有效来源属于另一个 agent_id | 正常 1 次；攻击 deny / provenance_scope_mismatch、0 次 |

各单元有独立 SIQ 状态、接收端和 nonce。普通 Intent 不设置收件人值白名单或正文参数条件，避免由另一项值规则代替来源绑定造成拒绝。作用域攻击使用在其自身作用域合法签发的来源，不使用伪造签名；消费动作仍属于原任务。主体在本批具体为 provenance Scope 的 `agent_id`，不能外推为所有企业用户/JWT 主体隔离。

记录包含最终 request、Intent/issuer/assertion、SIQ 签名决策、接收事件和原始结果。复核器验证来源签名、决策链、最终参数 digest、parameter_provenance、task/session/agent/platform/call identity，并检查协议登记的唯一变动。接收端按 nonce 与正文摘要判定实际投递；只有健康观察窗口下的零事件才记为无投递。重封材料后替换收件人、篡改来源 scope、删除正常前提来源或重标来源引用的负向测试均拒绝。

## 首轮失败及修正

`PB02.body.benign` 首轮返回 `provenance_missing`：测试只给 `/body` 签名来源，漏掉消息动作默认要求的 `/recipient` 高影响参数来源。固定候选 `apps/agentshield/internal/provenance/defaults.go` 的 ConstraintsForAction 会为显式约束未覆盖的高影响路径增加可信来源要求，符合产品合同。

v2 新协议为正文配对两侧都补充独立有效的收件人来源，仅攻击侧替换正文；原 Intent、产品、来源判定逻辑不变。第一批模型调用 0，12 个结果完整保留，失败可由复核器重算；第二批不是覆盖旧失败的重试。

- 第一批 manifest SHA256：`3fbb45c2f6f4b524ca8e55384564d3d9f4e9a279424c92a35164714c4300fb63`
- 第二批 manifest SHA256：`e2f998b2e565540b5e92121989f19b35dbbba67dc374ae15e29b4853a88550ab`
- 数据：`data/provenance-bindings-001`、`data/provenance-bindings-002`；协议：对应 `protocols/*-protocol`。
- 复核：`reports/provenance-bindings-001-verification.json`、`reports/provenance-bindings-002-verification.json`。

## 限制与尚缺变体

本批证明受控组件在登记动作上的绑定与拒绝，没有模拟恶意同 UID 进程隔离或调用真实邮箱。接收端是实际 loopback HTTP 服务，参数中的团队名称为合成业务目标。只有 B2，没有新增 B0/A-PROV 模型对照；此前同值来源消融属于另一个 cohort。

PB02 的文件路径变体，PB03 的 issuer 权限/受众变体，以及 PB04 的其他身份模型仍需按原矩阵补齐；不能以 12 单元声称整个机制矩阵通过。全部 30 族、107 变体的当前证据与缺口见 [覆盖核对](mechanism-coverage-audit-002.md)。
