# N03 自动新版检查：来源引用与调度元数据规格（v1）

批次：n03-update-source-config-20260913（N03 第 1 步 / N03-A 前半：来源引用 + 调度元数据存储）；n03-update-scheduler-20260913（N03 第 2 步：守护进程调度器）；n03-update-source-http-20260914（N03 第 3 步：HTTP 端点 + Web 面板接线 + 契约样例）；r04b-update-source-disable-20260914（已保存来源一键停用）
状态：来源存储、调度器、HTTP、Web 面板、daemon 周期任务及 URL-free 停用已通过组件验收；完整原生更新旅程仍待验收。

## 1. 目标与边界

- N03 把"自动"限定在**检查**；确认安装仍走既有比较/确认事务。本批包含**来源引用与调度元数据**、有界调度循环和用户显式开启后的上游检查；不改安装状态、不自动安装新版。
- 复用 `CheckUpdate`（只读安装状态）与 `skillimport.CheckUpstream` 的来源绑定；检查结果可更新独立调度元数据，安装记录与 Grant 不变。

## 2. 来源引用（UX-010 第 1 项设计）

现状：ZIP 安装记录以来源定位摘要绑定，URL 仅存于浏览器内存；git 安装记录自带 URL。

设计：

1. **保存是显式用户动作**（`SaveUpdateSource`），按 install 逐条保存；不保存则自动检查显示"需要重新提供来源"（`needs_source`）。
2. **公共定位信息与私有/临时认证引用分离**：
   - 可持久化的"公共定位"= 经 `skillimport` 下载 URL 校验（https、公网地址、无 userinfo/fragment）**且查询串为空**的规范 URL。
   - 带查询串（常见为临时令牌）的 URL 属于私有/临时认证引用，**一律不持久化**——自动检查对这类来源不可用，仍需每次重新提供来源。
   - 认证头等引用 v1 不存在持久化通道。
3. **绑定校验**：保存的 ZIP URL 必须重新产生导入记录的 `source_locator_digest`（`skillimport.ZipSourceBinding`）；无法绑定的 URL 拒绝保存（ErrChanged），调度器因此不可能被改指向其他内容。git 来源无需单独保存 URL（签名记录已携带），保存动作只管理开启/关闭。
4. **展示脱敏**：持久化的 `display` 仅含 scheme://host/path；userinfo、查询串、fragment 不落盘、不入 API 视图、不入审计与日志。
5. 用户控制：旧 `save/v1` 的 `enable=false` 保持兼容；新界面停用走独立 `disable/v1`，只复用当前有效签名记录，不接收 URL。来源变更或重新启用仍须按来源规则显式保存，重新保存重置检查状态。

## 3. 调度元数据记录

- 路径：`<state>/skill-installations/update-sources/<install_id>.json`；与安装记录、操作记录、Grant 完全分开。
- schema `local-skill-update-schedule/v1`，canonical JSON + 本机状态密钥签名（与 N01 记录同法）；包级 slot 串行化写入。
- 字段：install_id、source_kind、locator（仅 zip，公共定位）、display、enabled、interval_seconds（默认 86400=24h，有界 [3600,604800]）、install_binding_digest（绑定 Plan.Source 摘要 + Plan 签名，防迟到结果写到新对象）、next_check_at、last_attempt_at、last_success_at、last_status、failure_category、failure_count（有界 [0,63]，>0 时必须伴随 failure_category）、saved_by、updated_at、signature。
- **零安装状态写入**：保存/读取调度元数据不产生 `update-sources/` 之外的任何新文件，不改 Grant、准入工件、安装版本。
- **兼容策略**：新目录旧程序不感知；读取用 DisallowUnknownFields + 签名验证，未知字段/篡改一律 ErrChanged（旧结构不会被新数据误读；未来加字段须升 schema version）。
- **保存前兼容校验**：持有 updateSourceSlot 时，显式保存（包括关闭、重新启用）必须先严格读取已有调度记录，复用版本、字段、签名、语义与 install_id 校验。仅明确不存在时允许创建，合法兼容记录才可替换；未来版本、未知字段、损坏签名或非法状态必须拒写并保留原字节，不得通过重新保存把不兼容记录覆盖为旧格式。

## 4. 状态词汇表

`not_checked`（未检查）/ `checking`（检查中，**瞬态，永不持久化为 last_status**）/ `up_to_date`（已最新）/ `new_version`（有新版）/ `source_unavailable`（来源不可用）/ `unsupported`（暂不支持）。

写侧不变量（写入时强制）：`last_status ∈ {up_to_date, new_version}` 必须同时有非空 `last_success_at`——失败绝不能显示"已最新"。failure_category 为有界集合：source_unavailable / url_blocked / changed / limit / invalid / unavailable / canceled。

## 5. 本批 API（Store 层）

- `SaveUpdateSource(ctx, installID, req)`：前置同 CheckUpdate（installed_unverified、无移除进行中、导入记录摘要匹配）；zip 需绑定 URL；返回落盘后的记录。
- `DisableUpdateSource(ctx, installID, req)`：请求只有 schema 与 actor；必须已有有效、未陈旧且与导入定位一致的签名记录。首次停用仅清理调度结果并保留 locator/display/binding/interval；重复停用逐字节幂等。未保存返回 `ErrUpdateSourceNotConfigured`，未知版本、损坏签名、来源变化或绑定漂移返回 `ErrChanged`，均零写入。
- `ReadUpdateSchedule(ctx, installID)`：返回视图 `local-skill-update-schedule-view/v1`（source_state: saved / needs_source / unsupported / stale；status 为稳定状态；不返回 locator 原文）。绑定摘要不匹配 → stale（视为未检查，不泄露旧内容）。

## 6. 调度器契约（n03-update-scheduler 批次）

`RunScheduledChecks(ctx, req)`（schema `local-skill-update-schedule-run/v1`，结果 `local-skill-update-schedule-run-result/v1`）是守护进程唯一入口，语义如下：

1. **有界调度**：枚举 `update-sources/*.json`（目录 >256 条 → ErrLimit；无效/篡改记录计入结果的 stale 并跳过——从不修复、从不对其实施取数）；只取 `enabled && next_check_at <= now` 的条目，按 (next_check_at, install_id) 稳定排序；每次运行最多 `max_checks` 个（默认 4，有界 [0,16]）。
2. **抖动**：next_check_at 一律 = now + 间隔/退避 + 至多间隔 1/8 的随机抖动（`jitter` seam 只在 Open 构造时注入，绝不由运行时配置设置），避免安装群同时点火。
3. **失败退避**：连续失败自 15 分钟起几何翻倍，封顶为记录自身 interval；`failure_count` 有界 [0,63] 并记录 `failure_category`；`last_success_at` 跨失败保留（失败永不显示"已最新"）。
4. **手动优先、零并发重复**：手动 `CheckUpdate` 成功即记录其结果并把 next_check_at 推出当前 due 槽位；调度器在取得 stage 槽位**之后**重读记录，手动检查已完成的条目按 not_due 跳过——自动与手动从不并发重复取数。门序恒为 stageSlot → updateSourceSlot，无死锁路径。
5. **重启不形成请求风暴**：本轮未跑到的 due 条目按 `restaggerDelay`（install_id 的 sha256 派生，确定性）摊到整个 interval 上——重启后同一安装落在同一槽位，不会在启动瞬间集中重试。
6. **迟到/重放结果防护**：所有结果写入都经 `writeScheduleUpdate` 的绑定复核（记录缺失 / install 已不在 / 非 installed_unverified / 移除进行中 / install_binding_digest 不匹配 → 直接丢弃）——关闭、移除、重装后的迟到结果不会写到新对象上。
7. **只写调度元数据**：调度器对 `update-sources/` 之外零写入，不改 Grant、不自动确认；"有新版"仅置 status=new_version + requires_confirmation，动作留给既有比较/确认事务。
8. **取消语义**：预取消的运行立即失败返回；运行中途取消返回已完成的部分结果 + ctx.Err()，不写本次尝试元数据。

## 7. HTTP 契约（n03-update-source-http 批次）

- 路由：`GET` / `POST /v1/skill-installations/operations/{install_id}/update-source`（挂在既有 operation 路由上，凭据层级与方法限制与同路由其余子资源一致：无凭据 401、decision token 403、非 GET/POST 405）。
- `POST` 请求：`local-skill-update-source-save/v1`，字段严格四项 `{schema_version, remote_url, enable, actor_id}`（`readStrictFlatRequest`：未知/重复/嵌套字段 → 400 `skill_install_invalid`）。git 来源的 `remote_url` 必须为空（URL 来自签名记录）；zip 来源必须重新提供可绑定的原下载链接（即使只是停用）。
- 一键停用：`POST /v1/skill-installations/operations/{install_id}/update-source/disable`，请求 `local-skill-update-source-disable/v1` 严格只有 `{schema_version, actor_id}`。该端点不能创建、重绑定或修复来源；没有已保存记录时返回 409 `skill_update_source_not_configured`。无凭据 401、decision token 403、非 POST 405。
- 响应（GET 与 POST 相同）：视图 `local-skill-update-schedule-view/v1`，字段封闭：`schema_version, install_id, source_kind, display, enabled, source_state, status` + 可选 `failure_category, next_check_at, last_attempt_at, last_success_at`（`omitempty`）；`display` 仅 saved 且非本地来源时非空（脱敏 scheme://host/path），其余为 `""`。不含 locator / 签名 / interval / install_binding / saved_by。
- 错误分类：未知安装 404 `skill_install_not_found`；请求非法 400 `skill_install_invalid`；改动源/冲突 409 `skill_install_changed`；移除中 409 `skill_install_removal_pending`；调用方取消 408。
- 互斥：GET/POST 与 `CheckUpdate` 共用同一 install 槽（`skillInstallSlot`），调度元数据写与更新检查从不并发；POST 是"保存后回读"的单次往返。
- **双端契约样例**：`apps/agentshield/testdata/contracts/local-skill-update-schedule-view.json` 由真实 Store 输出生成并提交；Go 测试（`TestUpdateScheduleViewContractSample`）逐字节比对，Web 测试把同一文件喂给 `isSkillUpdateScheduleView` 校验器——两侧任一漂移即测试失败。
- Web 数据层：`readSkillUpdateSource` / `saveSkillUpdateSource` / `disableSkillUpdateSource` 对响应跑校验器（精确键集、install_id 必须等于路径 id、displayURL 无 query/fragment/userinfo；停用响应必须 `enabled=false`），不合规抛 502 `skill_install_incompatible_response`。调用方 zip 链接仅存 React state，成功保存后清空；不写 Web Storage、不进审计、不出现在 URL。已保存来源停用永远不携带 URL，Git 首次启用/重新启用携带空 URL。
- "有新版"行为：端点与面板均不自动确认；面板在 `new_version` / `requires_confirmation` 时展示指向既有 `/skill-imports`（重新导入）与 `/skill-updates?install_id=`（比较/确认）的链接，授权语义零新增。

## 8. 后续批次衔接

- daemon 已接入 5 分钟 tick；启动时不立即取数。用户显式开启后，默认每 24 小时检查，失败有退避。
- Git 生产入口仍返回明确不可用；HTTPS ZIP 为可执行来源。真实上游、原生安装更新以及跨 OS 生命周期证据仍待后续批次。

## 独立复核增量（2026-09-14）

每次手动或自动获取前固定调度记录签名，完成时在 updateSourceSlot 内比较该签名；期间用户关闭、重新保存或替换来源后，迟到结果必须拒写。首次检查没有调度记录时，也不能把结果写进后来创建的记录。无效调度计入 stale。当前公开 HTTP/持久化文档均补齐 packages/contracts 的版本化 schema。

## R04-B 一键停用增量（2026-09-14）

界面在已保存且启用时只调用新停用端点；ZIP 不再要求用户重新粘贴链接。尚未保存的 Git 来源点击启用会正确创建记录，ZIP 仍要求原链接。页面以安装、导入、actor、服务签名身份组成同步请求身份，路由或会话刚切换而 effect 尚未来得及清理时，旧对象的成功或失败响应也不得写入新对象状态。组件证据见 [R04-B 报告](evidence/personal-experience/r04b-update-source-disable-20260914/report.md)。
