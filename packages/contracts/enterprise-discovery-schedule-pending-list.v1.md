# 设备侧待确认周期计划枚举 v1

R01 增量，补齐 [enterprise-discovery-schedule/v1](enterprise-discovery-schedule.v1.md) 中"不提供列表或自动选择"留下的缺口：组织侧创建计划要求设备已注册，而设备侧原先只能按已知 schedule_id 读取，新注册设备无法自行发现"有一个计划在等我确认"。本版本只新增一个只读枚举端点，不改组织侧创建语义，不新增自动授权。

命名说明：本文件是**线路 schema** `enterprise-discovery-schedule-pending-list/v1`，与安装侧本地日志文件 schema `edge-discovery-schedule-pending/v1`（见 v1 契约"Linux 待确认日志"）不是同一命名空间，不得互相引用。

## 端点与认证

GET `/edge/v1/discovery-schedules`。仅凭当前设备凭据（Authorization Bearer + X-Edge-Identity）。租户、环境、设备全部从验证身份定位，不接受任何客户端指定的租户/环境/设备参数，因此不存在跨租户或跨设备枚举入口。

先定位（环境缺失或身份不可信 404/401），再在租户行锁下重读设备并复验：凭据哈希未轮换、设备未吊销、设备仍属该环境，否则固定 409 `discovery_schedule_device_changed`，不回显配置或异常正文。

## 枚举范围

只枚举当前设备的 `status=pending_confirmation` 行。`active` 继续走既有按 ID 读取与 tick；`paused`/`revoked` 不属于待办，不进本列表。这是**待办发现**，不是计划总览：组织侧总览仍归 `enterprise-discovery-schedule-management/v1`。

分页：`cursor` 为 schedule_id（`eds-` 加 32 位小写十六进制），按 ID 升序严格大于游标；`limit` 1–100，默认 20。cursor 形态非法在参数校验阶段拒绝。

## 响应

精确字段：schema_version=`enterprise-discovery-schedule-pending-list/v1`、evaluated_at（服务端 UTC Z）、items、integrity_failed、next_cursor。no-store。不接受额外字段。

`items` 每项白名单投影：schedule_id、status、revision、intent（完整 `enterprise-discovery-schedule/v1` 意图结构）、intent_digest。与按 ID 读取使用**完全相同**的绑定与投影一致性校验：`require_binding(设备身份, 原安装计划摘要)`，且 schedule_id/意图摘要/起止时间/间隔/轮数预算与持久行逐项一致。不返回安装计划、目录路径、任务载荷或凭据。

`integrity_failed` 列出本页中**存在但无法通过上述校验**的 schedule_id。这类行绝不投影其意图内容，也绝不静默当作"没有待办"：显式列出，让设备与审计都能看到"该行存在但无法安全读取"。分页仍正常推进，否则一行损坏会让其后所有待办永久不可达。这是与按 ID 读取唯一的行为差异：按 ID 读取对单行损坏返回 409，因为该请求只针对那一行；本端点必须继续服务其余行。

## 只读与授权边界

GET 不创建运行绑定、扫描、任务、预约、权限、审计或其他业务写入；不激活、不恢复、不确认、不派发任何计划；无新增数据库迁移。列出一个计划不改变其状态，也不构成任何授权。

列表**不是自动选择**：设备仍须按既有 `POST /edge/v1/discovery-schedules/confirm` 完成带本机明确确认的 Ed25519 签名确认才使计划生效。本版本不引入任何"设备自动采纳"路径，也不降低确认强度。因此可见性的扩大只影响"设备能否发现自己有活干"，不影响"计划是否被授权"。

本版本不含组织侧反向能力：设备不能通过本端点请求新计划、延长预算或修改周期。新注册设备的组织侧绑定计划创建仍属既有组织管理入口，本版本不改变其时序要求。

## 实现与状态

`app/routers/discovery_schedule_pending.py`。**尚未在 `app/main.py` 注册**，因此在接线前该端点对外不可达；隔离测试通过在本测试模块内单独挂载该 router 验证行为，不修改共享应用。接线属 R08 冻结前的待办项，见开发台账。

本版本为源码级与隔离验证级（合成设备、临时密钥、独立 SQLite）。不代表真实设备已获得周期发现，也不代表组织侧新设备自动绑定已实现。
