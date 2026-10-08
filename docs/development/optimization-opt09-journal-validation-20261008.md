# OPT-09：OpenShell 行为验证持久台账

日期：2026-10-08。任务保持 `implementing`，总体完整验收仍为 9/16。

本批完成内部持久台账、领取／消费控制和数据库迁移，未接入企业验证 API、真实探针收集器或前端。生产部署仍为配置读回验证；本批接受的合成观测不会提升部署等级。

## 实现与故障语义

依照 [ADR-058](../adr/0058-enterprise-openshell-behavior-verification.md)，迁移 `0031` 新增 `openshell_behavior_operation`，保存挑战、摘要、父 apply 操作、一次性 nonce 哈希、截止时间、epoch、观测结果及固定原因码。领取者随机令牌只返回内部调用方，数据库仅保存其 SHA-256，审计不保存令牌或原始错误输出。

状态路径为 `prepared → running → accepted / rejected / unknown`；未领取即到期进入 `expired`。状态只能向前：已领取的记录不能重新领取，丢失领取者后不会重新授予执行资格；到期／不确定执行保留未知状态，重测必须使用新的操作身份。`accepted` 只表示当前台账采信该份观测，不能作为通用网络隔离或部署等级证明。

领取前和消费前核对租户、部署、运行绑定、apply 操作、策略 revision／digest、部署回执及经认证加密的父操作来源。当前目标读回仍由未来可信收集器提供，API 用户权限、审批链、算子目标授权以及跨进程目标互斥也仍需在协调器中完成。

数据库状态转换使用范围谓词、旧状态和 epoch 条件更新，领取事务提交后才返回令牌。状态变化与审计同事务；审计不可用时 prepared、running、accepted、rejected、unknown、expired 六条路径均回滚。外部网络操作不会被放入这些事务。

本批复核发现：旧候选实现可能接受挑战有效期内、但早于实际领取时间产生的观测。新增负向用例先复现旧行为误记 `accepted`，随后增加实际领取时间下界检查，最终返回 `behavior_result_predates_claim`。原失败日志保留在私有验证目录。

## 验证结果

| 验证 | 结果 | 证明范围 |
| --- | --- | --- |
| 台账、协议、旧 apply 台账及旧探针定向回归 | 166 项通过，0 失败／错误／跳过 | 首轮包含 29 项行为台账用例，兼容既有协议和探针 |
| 补齐审计故障后的最终台账用例 | 32 项通过，0 失败／错误／跳过 | 增加 rejected／unknown／expired 三种审计回滚；与上行重叠，不相加计总量 |
| 独立 PostgreSQL 17 | 40 项检查通过 | 同一套 32 项用例在 Alembic 生成的真实表上执行，另含模型列／nonce 唯一约束、两组实际锁竞争及迁移保留检查 |
| Ruff、差异空白检查 | 通过 | 相关新文件与修改文件；未重复无关 Go／前端全量 |

PostgreSQL 并发检查先显式持有目标行锁，再独立观察两个数据库事务确实处于锁等待，释放后核对领取／消费分别只有一个成功者且审计数量准确。这比单纯启动两个线程提供更直接的数据库竞争证据。

覆盖范围包括跨租户／跨部署拒绝、nonce 和操作身份冲突、旧 epoch／错误令牌、重复消费、剩余预算不足、到期未知、领取前观测、安装绑定撤销、租户停用、部署与父策略漂移、密文来源不匹配、记录字段损坏、非法结果不落原始错误及六种状态的审计回滚。重启语义通过新 journal 实例读取同库和丢失领取者模拟验证；本批没有把它描述为真实探针进程崩溃实测。

干净库完整升级到 `0031`，空表降到 `0030` 再升级成功；有记录时直接迁移守卫和实际 Alembic 降级均拒绝，版本与证据保持。生产迁移不能删除已登记的行为证据。临时 PostgreSQL 仅绑定本机回环，数据位于临时内存挂载，运行结束已删除本批容器，未访问日常业务数据库。

## 可复核入口

```bash
cd apps/control-api
uv run --frozen pytest -q app/tests/test_openshell_behavior_journal.py \
  app/tests/test_openshell_behavior_protocol.py \
  app/tests/test_operation_journal.py app/tests/test_enforcement_probe.py
```

最终完整命令会包含新增的三条审计用例；本报告分别保留首轮 166 项和最终台账 32 项的实际运行分母，不将未重新执行的组合伪记为一次完整运行。

```bash
# 从仓库根目录执行，输出目录必须不存在；需要本机已有 postgres:17-alpine。
apps/control-api/.venv/bin/python \
  scripts/enterprise-experience/behavior-postgres-check.py \
  var/optimization-20261007/opt09-journal-postgres-new
```

机器可读记录：[enterprise-behavior-journal.json](evidence/optimization-20261007/enterprise-behavior-journal.json)。本地原始日志／JUnit：`var/optimization-20261007/opt09-journal-{preclaim-negative,focused,final}.*`；最终 PostgreSQL：`opt09-journal-postgres-002/`。原始目录、数据库连接信息和临时状态不提交。

## 后续工作

下一批实现独立授权的真实 ELF 收集器与固定探针模板，接入可信目标／策略／执行身份读回和 API 协调器，再完成同目标真实三臂验证及前端等级、范围、时间、过期与漂移展示。本批没有调用模型、OpenShell 网络探针或修改真实部署状态，也未推送远端、运行远端 CI 或合并主线。
