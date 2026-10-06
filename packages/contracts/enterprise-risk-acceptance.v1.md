# Enterprise risk acceptance boundary v1

版本1，2026-10-06。整理现有威胁模型T15、对象级鉴权不变量和企业风险终态规格在`POST /api/v1/findings/{finding_id}/accept-risk`上的服务端要求。路径及请求字段不变；不新增批量接受、续期或重新打开API。

请求只含`owner_user_id`、`reason`、`expires_at`。负责人为1–64字符标识，格式与CandidateConfirm一致：`^[A-Za-z0-9][A-Za-z0-9._:@-]*$`。原因1–512字符，至少包含一个非空白字符，保留用户原始合法文本。expiry沿用datetime解析；客户端应传明确时区，UTC换算越界受控422 `invalid_expiry`，过去时间422 `expiry_in_past`。本修复不改变历史无时区输入的解析兼容性。

合法请求体先按验证身份派生tenant定位finding，不存在/外租户404，再校验`finding:manage`（本租户无权限403）。只允许open或acknowledged接受；risk_accepted、resolved及未知状态409 `invalid_state`，不能重写owner、reason、修复证据或重复产生事件。参数解析失败仍由请求模型返回422，不声称无效请求体也一定先定位对象。

成功状态risk_accepted，owner/reason/accepted_by/expiry与`finding.accept_risk`审计、`agent.finding.resolved.v1`（resolution=risk_accepted）outbox同事务。失败不得改变finding、审计或outbox。后端持有目标finding行锁到事务结束，避免顺序终态检查与写入分离；并发保证仍需真实并发专项测评，不能仅据本次顺序补测宣布通过。

负责人存在性和组织目录归属仍由IAM负责，本接口格式验证不等于身份目录查验。接受风险不是修复风险或授予运行权限。到期由worker重开，既有UTC换算修复继续有效。
