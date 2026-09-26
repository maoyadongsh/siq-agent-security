# Qwen3.8：周期采集同槽重放完整性修复

任务编号：CL-02-SCHEDULE-REPLAY-CLOSEOUT。
项目：`/home/maoyd/siq/siq-agent-security`。

请直接完成实现与最少必要回归，不只输出方案。用户要求减少重复测试、禁止扩展功能、加快收口。本任务只修复既有周期预约重放的范围完整性，不增加接口、产品能力、数据表或依赖。

## 1. 开始前

阅读 `/home/maoyd/siq/AGENTS.md`、项目 AGENTS.md、相关下级 AGENTS.md（若有）、工作区 `VIBECODING_SCIENTIFIC_METHOD.md`。
阅读总任务书与收口记录中 CL-02、安全不变量，以及：

- `packages/contracts/enterprise-discovery-schedule.v1.md`
- `apps/control-api/app/discovery_scheduler.py`
- `apps/control-api/app/discovery_schedule.py`
- `apps/control-api/app/tests/test_discovery_scheduler.py`
- `apps/control-api/app/tests/test_discovery_schedule_tick.py`
- `apps/control-api/app/models.py` 中相关模型和 `app/signing.py`

执行 git status，阅读目标文件当前内容和 diff。大量未提交及未跟踪文件属于并行成果，不得还原、清理或覆盖。发现目标文件正在被修改时先报告冲突，不盲写。

## 2. 已观察到的缺口与目标

主开发者检查时，`reserve_discovery_round` 的 `previous is not None` 分支仅核对租户、任务存在数量、环境与 target_device_identity，然后返回原 task_ids；未把任务类型和完整采集 payload 与已确认安装计划逐项核对。

请先用合成夹具验证：同槽任务的 connector、roots、include 或 task_type 被改变，但设备和环境不变时，现实现是否仍成功返回。若可复现，按以下冻结边界修复；不要把这个缺口描述为已经证明 Edge 会执行篡改任务——Edge 仍有独立验签。

目标：同槽重试只返回符合原确认范围和既有任务拆分规则的原任务 ID；不符则固定错误并停止，不重建任务、不重签、不扩大范围。

## 3. 文件所有权

允许修改仅：

- `apps/control-api/app/discovery_scheduler.py`
- `apps/control-api/app/tests/test_discovery_scheduler.py`

允许新增：`docs/development/enterprise-schedule-replay-closeout-handoff.md`。

其他文件只读。禁止修改合同、模型、迁移、签名模块、路由、共享测试夹具、Edge、Connector、前端、发行工具、README、公共台账及锁文件。需要超范围修复时报告最小建议，不自行扩展。主开发者保留合同及总台账维护权。

## 4. 实现要求

1. 从已经验证的 installation_plan 派生预期任务类型和 payload。复用现有拆分语义：directory 的 SKILL.md 单独 skill_scan，并携 inventory_kind=skills；其余 include 为 scan。不得增加、删减或重排实际扫描范围。
2. 可以提取该文件内部小型纯函数，供首次创建和重放核对共同使用，避免两个任务拆分事实源。不得重构其他模块。
3. 重放严格核对每项任务的 environment、task_type、完整 payload（connector、scope、target_device_identity、必要 inventory_kind），以及任务集合数量与多重性。防止重复 ID、少项、多项、异常 task_ids/payload 引发未捕获异常或误通过。保留原 task_ids 顺序返回，不依赖 SQL IN 返回顺序。
4. 重放完整性失败沿用 `discovery_schedule_replay_unavailable` 等现有固定错误；不输出路径、payload、身份或秘密。不得删除/补齐/重签已有记录。
5. 不把当前能力心跳、当前配额、任务已完成/失败/过期等条件误加到历史重放上；正常重试仍可读回原 ID。保留当前计划状态、窗口、审计前置检查和事务/锁顺序。
6. 不通过调用 sign_task_payload 重签再比较来“验证”历史任务；本次仅保证任务范围符合绑定计划。完整历史签名/原始任务身份溯源如果需要额外存储或信任设计，记为范围外，不添加新机制、不声称已经证明。
7. 任一拒绝不得新增任务、outbox、审计，不改变 reserved_runs、last_reserved_slot、revision 或原任务。不得在函数中新增 commit。

## 5. 有限验证预算

先新增一个集中参数化回归复现旧实现问题，再修复。最少覆盖：合法同槽原 ID/顺序、篡改 connector/roots/include/task_type、同设备同环境但不符范围、重复/缺失 ID、异常 payload；directory 混合 SKILL.md 的拆分匹配；拒绝后计数/任务/outbox/审计不变。复用已有夹具与断言，不为每一项新建测试框架。

仅使用隔离测试配置、合成数据及测试签名材料。运行前确认 conftest 的数据库和签名隔离，不得读真实 .env 或连生产数据库。

在 `apps/control-api` 中使用本机已安装环境，不安装依赖、不联网同步：

```bash
uv run --no-sync pytest -o addopts='' -q app/tests/test_discovery_scheduler.py app/tests/test_discovery_schedule_tick.py
uv run --no-sync ruff check app/discovery_scheduler.py app/tests/test_discovery_scheduler.py
```

若已有环境命令不适用，使用已有虚拟环境等价命令并记录，不临时安装。调试只跑失败用例，完成时这两个测试文件合跑一次即可。不跑后端/前端/Go 全量，不新增浏览器、数据库服务或原生验收脚本。

执行 git diff --check；新增交接文档需另查空白。不得删除测试、放宽安全断言或用跳过消除失败。并行无关错误只如实记录。

## 6. 禁止操作

- 不读取 admin-password.private、真实 .env、密码、令牌、私钥或设备种子。
- 不启停/部署服务，不操作真实设备、不扫描真实目录、不上传、不签发。
- 不提交、建分支、推送、打标签、发 PR；不运行 git reset、checkout --、clean。
- 不编辑他人文件，不全局格式化，不增加依赖、功能、接口或表字段。

## 7. 交付

写入上述 handoff：复现与旧行为、最小修复、实际修改文件、精确测试命令和通过/失败数量、剩余限制、未运行事项。明确区分“计划范围核对”与“历史签名/来源认证”，不把前者冒充后者。

结尾明确：未提交、未部署，待主开发者复核；仅完成 CL-02-SCHEDULE-REPLAY-CLOSEOUT，不宣称 CL-02、ENT 总任务或正式发行完成。
