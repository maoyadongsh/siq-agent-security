# 有界持续发现计划 v1

CL-02 / ENT-007 增量。现有 enterprise-install-plan/v1 与首扫接口不改变；旧安装确认不自动升级为周期授权。已实现结构校验、持久预约、组织管理、设备确认、Edge 轮询及既有设备安装交互衔接；源码和隔离验证不代表真实设备持续扫描已启用。实施历史见开发台账，本合同描述当前行为。

## 确认载荷

`enterprise-discovery-schedule/v1` 包含精确字段：schema_version、schedule_id（eds- 加 32 位小写十六进制）、installation_plan_sha256（64 位小写十六进制）、device_identity（现有有界标识格式）、starts_at、expires_at（UTC Z，最多微秒）、interval_seconds、max_runs、purpose=discovery_only。不接受额外字段，不接受字符串数字、布尔数字或时间隐式转换。

全部期限与预算必须显式提供，没有默认持续授权。初版资源边界：间隔 900–86400 秒；有效窗口大于零且不超过 30 天；最多 2880 轮，每轮仍受已确认安装计划的采集器/范围及现有单任务资源限制。以上是代码支持边界，不是为用户选择的周期。合法但没有使用全部预算的短窗口可接受；不因剩余额度延长期限。

安装交互将周期、到期时间和预算与原范围一起展示，由用户选择确认；不要求用户手工调度。新载荷仅为配置意图，不是设备凭据或业务权限。激活前服务端须根据验证身份定位设备/环境/租户，核对原安装计划来源、确切摘要、设备的确认凭据；不得只凭客户端 JSON 或本模块校验通过激活。安装计划的短期安装有效期与确认后的周期截止时间是两个独立字段，不通过延长旧安装计划期限实现持续扫描。

## 时间槽和执行约束

从 starts_at 开始，每 interval_seconds 为一槽；零号槽是首个周期槽，不复用或重放 initial-scan 的任务 ID。有效区间为 `[starts_at, expires_at)`，计算使用显式传入的带时区当前时间。恢复连接时只考虑当前槽，不补发遗漏槽形成突发扫描。

一个持久 schedule_id 的预算按已原子预约轮数计算（包括后续失败轮次），不是槽编号；前一天离线不耗扫描预算，但仍受原到期时间约束。last_reserved_slot 单调增加，时钟回退不能重发已预约槽。同槽重试返回同一预约和任务集合，不创建新的副作用；未成功提交预约不消耗预算。暂停、吊销或过期立即禁止新预约，不删除历史。

纯函数只回答“时间和本地快照是否允许尝试该槽”，不批准执行。实际调度必须在数据库事务内锁定当前计划、复验状态/设备凭据/环境/能力版本/确认范围/期限/配额/未完成任务，在唯一 `(schedule_id, slot)` 约束下创建定向签名任务、计数、审计及 outbox。同设备已有未完成轮次时不积压新轮次；未知结果保留并核对，不自动重放。Edge 收到任务仍按现有范围、制品、签名和设备身份逐项复验。无效、未确认或无法核对时失败关闭。

## 当前实现边界

`app/discovery_schedule.py` 提供严格确认载荷、纯时间槽计算和摘要绑定核对，0028 提供下述存储表。设备 tick 接口调用预约事务；Edge serve 在已有合法确认日志及回执时轮询，任务执行仍经过原任务领取与验签。CLI 和既有 registered 设备 setup 的独立周期确认已接通；存量设备不自动激活。

未完成：新设备注册后组织创建周期计划的安装衔接、确认日志换代、Web 周期管理及同制品原生安装旅程。当前日志使用固定文件名且不覆盖；不能自动改绑新计划或重新签发旧请求。首次确认超出五分钟且服务端从未接收时，不能靠 --resume 延长确认资格；已接收但丢响应的同请求重试仍按服务端幂等规则处理。不能把保留日志当作所有故障均可恢复。

CLI 恢复错误区分：发送失败为 `confirmation_result_unknown`，要求保留已写日志，仅尝试原请求 --resume，不推断 active；返回结果未能验证/保存为本地回执时为 `confirmation_receipt_not_saved`，要求保留日志及原回执，不启动服务、不覆盖材料。两者仍属于 discovery_schedule_unconfirmed 类别，不回显上游错误正文。安装编排的周期失败只承诺未进入本次服务安装，提示先核对确认阶段；用户取消或尚无日志时，不误导为已有原请求可恢复。上述错误不承诺服务当前一定停止，也不证明远端一定未确认。

## 持久记录增量

迁移 0028 新增 discovery_schedule 与 discovery_schedule_run，初始状态 pending_confirmation，不自动将旧设备转为 active。计划保存确认意图、原安装计划及其摘要、截止/预算/间隔、已预约计数/最后槽与 CAS revision。active 状态只供后续完成来源和设备确认核验的事务设置；数据库结构本身不证明授权。

计划通过复合外键绑定租户→环境→设备；每轮以 `(schedule_id, slot)` 为主键，并通过 `(tenant_id, schedule_id)` 绑定父计划，task_ids 仅为该轮已创建任务的引用。状态约束、计数与最后槽的基本一致性由数据库强制，完整任务归属/到期/预算和审计由后续事务执行器复验。禁止级联删除计划或轮次历史；非空计划或轮次使 0028 降级明确拒绝。没有旧记录回填或自动激活。

## 内部预约事务

内部 `reserve_discovery_round` 仅接受调用者已验证的 tenant_id/device_identity，不是对外认证入口。按租户、设备、计划顺序持数据库行锁；计划必须 active，设备未吊销，意图/安装计划 JSON 摘要与字段投影一致，存在本租户原 install.plan.create 审计及本设备 scan.schedule.confirm 审计（resource_id 为计划 ID、summary.intent_digest 为精确意图摘要、actor_type=edge、actor_id 为设备身份）。这些确认事件只能由后续核验本机用户明确确认的入口写入，本模块不会创建或伪造确认。

每轮要求最新心跳和相同采集器版本，沿用原根/include，目录 SKILL.md 拆分为 skill_scan，其余文件为 scan。租户行锁串行化本模块的配额核对；无法约束尚未采用相同行锁的旧手工任务入口，因此不宣称全系统配额并发问题已解决。该设备仍有非终态采集任务时等待，不自行将未知结果置为终态。任务截止不超过周期截止。

同槽重试仅返回持久任务 ID，必须仍有可核对原任务；不换 ID 或再次签发。新任务、签名、轮次、计数/revision、审计/outbox 在调用者事务中的 savepoint 内一起落盘，任一步失败全部回滚；最终提交由设备 tick 调用者负责。合成确认事件和隔离测试不能视为真实设备确认链已验收。

## 组织管理入口

POST `/api/v1/environments/{environment_id}/discovery-schedules` 接收精确 `{intent: enterprise-discovery-schedule/v1, installation_plan: enterprise-install-plan/v1}`。对象先按认证租户定位环境和 intent.device_identity 对应设备（404），再要求 env:manage 与 edge:manage（403）。核对设备未吊销、原安装计划的服务端签发审计、所有绑定摘要和周期尚未截止；仅保存 pending_confirmation 和创建审计，不创建扫描任务或确认审计。相同 ID/相同摘要请求幂等，不同摘要冲突，不允许跨租户覆盖。原安装计划过期不表示已安装设备失效；这里只保存待设备再次明确确认的意图，不延长原安装资格。

POST `/api/v1/environments/{environment_id}/discovery-schedules/{schedule_id}/revoke` 接收 `{expected_revision: 非负整数}`，同样双管理权限。与预约采用相同锁序，CAS 不匹配 409；已 revoked 重试不重复审计。成功只阻止后续新轮次，不删除已派发任务/历史，也不声称中止正在执行的采集。没有恢复 active 的管理接口；撤销后重启授权流程尚未实现。响应仅含 schema_version=enterprise-discovery-schedule-state/v1、schedule_id、status、revision、intent_digest，no-store，不包含设备凭据、原路径或原计划。创建接口本身不能使扫描生效，仍需设备明确确认与后续轮询。

## 设备签名确认

POST `/edge/v1/discovery-schedules/confirm` 同时要求有效设备凭据及注册设备 Ed25519 签名。精确请求字段：schema_version=edge-discovery-schedule-confirm/v1、schedule_id、device_identity、environment_id、control_plane_origin、intent_digest、installation_plan_sha256、expected_revision、confirmed_at（UTC Z）、user_confirmed=true、signature（128 位小写十六进制）。签名为去掉 signature 后 sort_keys、紧凑分隔、ensure_ascii=True 的 JSON 字节。不得用管理身份头、明文布尔确认或其他设备签名替代。

首次确认要求 pending_confirmation、revision 一致、确认时间不在未来且不早于当前 5 分钟、计划未到期；控制面地址、设备/环境、原计划和意图摘要必须完全匹配保存记录，原安装计划签发和组织侧待确认创建审计仍存在。确认事务只将状态置 active、revision+1，追加绑定请求摘要的 scan.schedule.confirm，不派发任何任务。相同已保存确认请求的重试仅返回原状态；不同确认请求或 revoked/paused 均拒绝，不自动恢复。锁后复验设备凭据哈希未轮换、设备未吊销，审计失败回滚。

user_confirmed 是经设备签名的本机确认声明，不是服务端直接观测人类操作的证明。配套 Edge CLI 展示相同摘要/范围/周期并要求明确本机确认，签名密钥不交给模型或页面。源码实现不证明真实用户已确认；隔离测试仅使用临时合成设备密钥。

Edge 纯解析/签名准备函数只接受精确字段、拒绝重复/大小写别名/null、限制 8192 字节、UTC 微秒时间与相同预算；与当前本地确认安装计划的完整性、规范化摘要、环境/origin/设备及签名公钥逐项核对。需要调用者显式传入 confirmed=true，不读取文件、不修改 State、不联网；不能将该参数本身当成人类确认 UI。Go 导出的合成请求已由 Python 实际确认模型逐字节核对和验签。持久日志和 CLI 调用见下文。

Edge CLI 调用的确认传输方法只能向请求中精确绑定且与 Client 相同的 origin 发送一次 POST，使用现有超时、拒绝重定向和自动重试。响应最多 4096 字节，精确字段、无重复/别名/null/尾随对象；必须匹配 schedule_id、intent_digest、active 状态且 revision 大于确认前值（允许已确认后预约增加 revision 的重试读回）。任何错误返回固定类别，不回显上游正文、凭据或请求内容，不修改本地状态。调用者须先取得明确确认并持久保存同一签名请求，再使用该方法；传输方法本身不证明用户确认。

Linux 待确认日志：状态目录内 `discovery-schedule-pending.json` 独占创建，0600，文件和目录同步；最多 16384 字节。保存 schema=edge-discovery-schedule-pending/v1、非秘密状态基线摘要、精确意图及原签名请求，不保存设备 secret 或私钥正文。基线排除可轮换 secret，绑定设备/控制面/原安装计划和签名身份；轮换凭据不自动更换签名请求。读回复用私密文件的祖先归属/权限、无链接、单硬链接、重复 JSON 拒绝并严格核对嵌套字段。使用签名时刻重建请求，保证恢复字节不变，不用当前时间自动续期。过期日志可读用于核对，但不表示可发送或可恢复授权；服务端继续检查截止。已有或部分文件不覆盖、不清理；持有设备任务锁的 CLI 调用者先持久化再发送。

Linux CLI 增量：`confirm-discovery-schedule --intent FILE` 默认只显示经本地绑定核对的设备/组织/环境、origin、原安装范围、周期/预算/截止及意图摘要，不写日志、不联网。带 `--confirm-intent-sha256 DIGEST` 且精确匹配显示意图才持任务锁创建日志并单次发送。`--resume` 不能与 --intent 同用，默认仅预览原日志，显式匹配摘要才重发原请求；不使用当前时间重新签名。整个确认命令与 serve 互斥，已有服务持锁时明确失败，不偷偷终止服务。

成功后独占保存 `discovery-schedule-confirmed.json`，0600+同步，结构为 schema=edge-discovery-schedule-confirmed/v1、request_digest、result；关联原请求并保留一次历史 active 读回，不是任务执行或持续有效证明。重复读回允许保留相同请求的既有回执，不改写；不删除待确认日志。部分或未知回执拒绝覆盖，错误保留材料供恢复。独立确认命令不启动服务、不授予业务权限；安装编排和 serve 对回执的消费见下文。

安装服务前置检查：Linux `install-user-service` 在持设备任务锁且读取身份后、写 unit 和调用 systemd 前复用 serve 的周期日志/回执校验；已有未完成或不匹配的确认材料时报 `user_service_schedule_unconfirmed`，保持日志和服务配置不变。补齐原确认回执后可重试，但不能绕过安装计划有效期和发行包验签。没有周期日志的安装保持原语义，不自动增加周期授权。

## 已确认计划的设备轮询

安装交互衔接：既有 registered 设备可使用 `setup-enterprise --interactive` 配合 `--schedule-id ID` 或 `--resume-schedule`，不提供 `--confirm-schedule-sha256`。首次安装范围 yes 只确认安装范围；独立周期步骤必须重新展示完整周期意图并再次明确 yes，才可进入服务安装。取消、输出失败或确认失败均保留原材料并停止。非交互调用仍要求独立精确周期摘要；混用交互与周期摘要拒绝。新设备尚不能使用预绑定周期计划。

设备终端确认增量：`confirm-discovery-schedule` 可用 `--interactive` 替代复制 `--confirm-intent-sha256`，两者互斥。必须为真实终端输入；管道在读取状态、获取计划或写日志之前拒绝。先成功展示绑定身份、范围、周期、预算、有效期与摘要，再提示默认取消；仅精确 yes 加换行确认（允许 CRLF），EOF、其他输入、输出失败或取消均不确认。等待后重新读取当前时间检查到期，再复用原日志先行、签名、发送及回执路径；恢复仍发原请求，不续签。无确认选项仍只预览，不改变业务授权。

安装编排增量：Linux setup-enterprise 可选 `(--schedule-id ID | --resume-schedule) --confirm-schedule-sha256 DIGEST`，或上述双确认交互方式，只能用于已注册身份。非交互周期摘要必须单独提供，不能由采集范围确认推导；周期参数与 --review-only 互斥，缺失/非法/冲突参数在准备前拒绝。顺序为暂存验签与能力核对→既有采集范围确认→原周期确认/恢复→用户服务安装。周期失败或取消不进入服务阶段，保留暂存与原恢复记录，不自动重签。未提供周期参数仍保持原行为。周期预览沿用人类可读输出，安装阶段另有 JSON 进度，不将整个混合输出声明为纯 NDJSON。新设备首次注册尚需后续组织侧创建其绑定计划，不能将此可选编排称为全自动注册到周期启用。

设备 CLI 获取增量：`confirm-discovery-schedule --schedule-id ID` 与 --intent/--resume 三选一，持任务锁、读取现有私密身份后，对绑定控制面发一次认证 GET。默认仅预览，无确认请求、签名或日志写入（与本地 --intent 预览不同，此模式有只读网络请求）。响应至多 16384 字节，拒绝重复/额外字段、重定向、非法 ID、意图设备/摘要不符；首次获取只接受 pending_confirmation 且 revision=0。之后仍按本地安装计划核对意图、显示范围和摘要，只有精确摘要参数或终端独立确认才进入原持久确认流程。重试 GET 如果意图变化，旧摘要无法确认；已确认或未决发送恢复使用 --resume 原请求，不能通过重新获取自动续签。

设备获取意图：GET `/edge/v1/discovery-schedules/{schedule_id}`，仅凭当前设备凭据读取相同租户/环境/设备的指定记录，不提供列表或自动选择。响应精确字段 schema_version=edge-discovery-schedule-intent/v1、intent（原意图完整结构）、intent_digest、status、revision；no-store，不返回安装计划、目录路径或凭据。先锁租户/设备并复验身份，再定位计划；错设备/租户返回 404，记录摘要/绑定/投影损坏固定 409。读取不写审计或业务状态，不确认、不派发；过期/撤销记录仍可核对，不表示可激活。Edge 后续必须用本地安装计划核对意图绑定，并取得明确确认。

POST `/edge/v1/discovery-schedules/tick` 接收精确三字段：schema_version=edge-discovery-schedule-tick/v1、schedule_id、intent_digest。要求当前设备凭据；租户/环境/设备均从验证身份定位，锁序为租户→设备→计划，锁后再次核对凭据未轮换及设备未吊销。其他设备/租户计划返回 404，摘要不匹配或完整性异常返回固定 409，不回显配置或异常正文。

只用服务端 UTC 时间调用既有预约事务；不得接受客户端指定时间、范围、预算或任务载荷。同槽返回原任务 ID，不重复计数或审计；未到期、暂停、撤销、计划到期、预算耗尽或背压时不创建新任务。缺少确认审计、能力不匹配等仍失败关闭。预约、任务、outbox 与审计同一事务提交，失败不部分保留。该请求不能激活或恢复计划。

成功响应精确字段 schema_version=edge-discovery-schedule-tick-result/v1、schedule_id、intent_digest、status（计划当前存储状态）、task_ids（本轮已预约 ID，或空数组）；no-store。active 不代表本次已派发、计划尚未过期或保护生效。任务仍经原任务领取与签名校验流程执行，轮询返回 ID 不直接执行。该入口本身不证明 Edge 后台服务已接通；客户端集成另行记录。

Linux Edge 后台接入增量：serve 持任务锁启动时，只有待确认日志与成功回执均不存在，才保持原心跳/首扫行为；若仅有成功回执（包括残缺文件或链接），视为未完成恢复并拒绝启动，不静默当作未配置周期。如有日志，必须同时核对安全读取的成功回执与原请求摘要/计划 ID/意图摘要/active 读回及递增 revision。缺失、部分、错误身份或不匹配文件令启动失败，不自动确认或修复文件。服务安装前置检查复用相同判定。服务运行期间不能用确认 CLI 更换日志。

经确认的周期轮询在原心跳成功后运行，计划开始前/到期后不发送；每次单独 POST，拒绝重定向，无内部自动重放，严格校验最多 8192 字节响应、字段/重复键/关联摘要/任务 ID。失败独立从 30 秒指数退避至 15 分钟，不抑制健康心跳；成功至少间隔 30 秒，服务端负责时间槽幂等和预算。返回非 active 状态后本次服务生命周期停止轮询，不自动恢复计划。任务 ID 不直接执行，仍由独立原任务循环领取、验签与回执。以上是源码与隔离测试结果，不证明原生服务/真实设备安装旅程已验收。

版本导航：上文"设备获取意图"一段所述"不提供列表或自动选择"仍然成立——设备**不能**自动选择计划，也不能绕过签名确认。R01 另行新增只读的待确认枚举端点 [enterprise-discovery-schedule-pending-list/v1](enterprise-discovery-schedule-pending-list.v1.md)，让设备能发现"有一个计划在等自己确认"；该端点只列出本设备自身的 pending_confirmation 行，不改变本条目的按 ID 读取、确认、tick 三段语义。上述所有确认与激活规则对本版本继续适用。

## 设备 CLI 发现增量（只读）

`confirm-discovery-schedule` 的参数来源为严格四选一：`--intent FILE | --schedule-id ID | --discover | --resume`。任意两者同用即拒绝，缺失来源同样拒绝；`--discover` 不改变其余三种来源的任何既有语义。

`--discover` 让**已注册设备在不预先知道 schedule_id 的前提下**发现"是否有计划在等本机确认"：持设备任务锁、读取现有私密身份后，只向绑定控制面发认证 GET，轮询上文待确认枚举端点（`limit=100`，按 `next_cursor` 有界翻页）。全程**只有 GET**：不创建运行绑定、扫描、任务、预约、权限、审计或其他业务写入，不激活、不恢复、不确认、不派发任何计划，不写任何 `discovery-schedule*` 文件（不写待确认日志，也不写成功回执）。任务锁可能创建或复用既有 `tasks.lock` 互斥文件；该文件不含计划、凭据或确认事实，不属于业务状态。页面严格校验：精确顶层/条目字段集、拒绝额外字段、拒绝重复键、拒绝 `null`（`next_cursor` 除外）、拒绝尾随 JSON、限制单页字节数、拒绝重定向、不接受非 200；条目 ID 必须位于请求 cursor 之后并严格升序，非空 `next_cursor` 必须精确等于本页最后一个条目 ID，禁止空页伪造推进或跳过候选。条目必须满足 `status=pending_confirmation`、`revision=0`、ID 形态合法、意图设备身份等于本机、`intent_digest` 与意图自身摘要一致。

三种结果的处理是**固定**的，不存在自动选择：

- **0 项**：输出固定文案，说明本机当前没有等待确认的计划、本次未创建任何请求、周期发现未被启用，并提示由组织控制台为该设备创建计划后重试。纯 `--discover` 查询返回成功；若本次调用同时带 `--interactive` 或 `--confirm-intent-sha256` 明确要求完成确认，则返回失败，因为实际没有任何计划被确认。两种路径都**不得**声称周期接入已完成。
- **恰好 1 项**且无完整性失败：直接进入上文既有的本地预览路径——完整展示设备/组织/环境/范围/周期/预算/有效期/意图摘要，然后仍按原规则需要 `--interactive`（真实终端、默认取消、管道输入不构成同意）或精确 `--confirm-intent-sha256` 才确认。
- **多于 1 项**：**绝不自动挑选**。只打印有界候选列表（每项 schedule_id / intent_sha256 / status / 起止时间），并要求改用精确 `--schedule-id` 重试；不进入预览、不确认、返回失败。
- **任一页存在 `integrity_failed`**：失败关闭，仅输出受控的 schedule_id 与固定原因，绝不回显上游正文；不确认、不写入。

发现**不是授权**：`--discover` 的列表读取阶段永不自动选择、永不确认、永不授予任何业务权限；只有随后满足既有摘要确认或真实终端 yes 的单一候选才能进入原确认路径。列表可见性扩大只影响"设备能否发现自己有活干"，不降低确认强度。不新增"默认确认""首项自动确认""复用安装范围"等任何捷径。
