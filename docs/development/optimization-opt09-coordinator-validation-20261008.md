# OPT-09 操作员模板与持久协调同次验证

日期：2026-10-08。状态：内部协调链路本批通过，OPT-09 继续 implementing。

## 结论

已将真实 OpenShell 策略下发、持久父操作、操作员批准模板、独立程序保护、三轮 CONNECT 差分、一次领取／消费及事务审计连接为同一次实际运行。重复提交同一验证 ID 没有再次产生探针流量；在专用数据库撤销 RuntimeBinding 后，新验证被阻止且未创建操作。原拒绝路径显式增加网络授权后连通，旧策略下的观测失效。

本次数据库是独立的开发验收 SQLite，审批人／租户等身份为合成材料；外部 OpenShell 网关、沙箱、受保护 ELF、网络连接和接收端效果均为实际执行。没有经过生产认证 API，也没有运行前端。因此不能把本结果称为生产企业端到端验收，部署验证等级仍为 `readback_verified`。

完整公开材料见 [机器证据](evidence/optimization-20261007/enterprise-behavior-coordinator.json)。此前独立探针验证见 [CONNECT 通道验证](optimization-opt09-connect-validation-20261008.md)，其证据保留。

## 实现

新增 `openshell-behavior-profiles/v1` 合同与操作员文件加载器。模板绑定完整部署来源、网关、策略、受保护容器／镜像／程序／UID、接收端、代理、时效和预算。最多 32 份模板，每份有效期不超过 24 小时，挑战继续限制五分钟。文件最多 128 KiB，拒绝重复 JSON 键、符号链接、硬链接、其他 UID 可写文件／父目录、过期或身份不一致的配置；保留并复核目录描述符及文件元数据。root 所有的 sticky 临时目录允许承载操作员独有子目录，普通可写父目录不允许。

配置入口为 `SIQ_AS_OPENSHELL_BEHAVIOR_PROFILES_FILE`。受测工作负载和普通请求不能自行传入端点、程序或代理配置。该变量已在 `.env.example` 说明；生产 API 尚未启用。

新增内部 `BehaviorCoordinator`，强制提供执行前授权和完成事务授权回调，复用既有跨进程目标互斥。执行顺序为：

1. 加载批准模板，核对 journal 的租户／部署范围并复核调用授权。
2. 获得目标互斥；已有验证 ID 返回原记录，不自动恢复 prepared／running。
3. 独立读回网关、策略和程序保护，验证挑战资格。
4. 提交 prepared 和 running 及其审计，随后才启动探针。
5. 每一臂前复核授权、模板字节、网关、策略和程序保护，任何变化停止后续调用。
6. 完成后再次读回；在结果提交事务中复核数据库授权，并再次检查期限。
7. 异常进入 unknown；若数据库或审计不可写，保留 running，不伪造成功或重放联网。

外部探测不在数据库写事务内运行。完成回调仅供可信宿主做数据库授权检查，不接收工作负载提交的回调代码。新回调导致最终授权阶段可能跨过截止时间，已加入第二次期限检查及专项反例。

## 验证结果

| 范围 | 结果与说明 |
| --- | --- |
| 定向回归 | 57 项通过：25 项模板／协调器，32 项既有持久台账；首轮 23 项与最终集合重叠，不累加 |
| 模板边界 | 文件／父目录符号链接、硬链接、可写权限、超限、重复键、过期、缺失、重复 ID 和目标不一致均拒绝 |
| 协调边界 | 每次模拟网络操作检查已提交 running 和两条审计；中途网关／策略／保护／授权／模板变化停止，完成授权拒绝和期限跨越不接受结果 |
| 事务失败 | prepared 审计失败时无探针；accepted 和 unknown 审计均失败时保留 running，再次调用不重放 |
| 并发与恢复 | 两个线程经实际文件互斥竞争同一验证 ID，只执行一组；prepared 崩溃状态不自动续跑 |
| 真实同次链路 | 12 项实际网关检查通过，包含持久策略下发、持久行为收集、重复调用不重放、数据库撤权阻止新操作、三轮差分与清理 |
| 实际网络效果 | 允许路径 3/3 CONNECT 200＋精确回显，拒绝路径 3/3 明确 policy_denied；主机前后对照 6/6；原挑战接收 9 条标识，授权反转新挑战接收 1 条 |
| 独立数据复核 | 私有验收库只读查询确认唯一行为记录 accepted/epoch 2，challenge/result 与公开观测逐字一致；父操作为 applied 且 revision/digest 相符；prepared/running/accepted 三条审计完整 |
| 静态与合同检查 | Ruff、JSON Schema、公开历史时间窗口内协议验证及 diff 检查通过 |

真实运行使用已验证 ELF `0d8c89512c9f373725abf44595801fc2c16b3dd1f7a86f88e66ab50fdf49f7df`，镜像 `sha256:ea5c48273e4c11b782e788a734a32e3b8043f2d22e1c341e0f297482aae9eefc`。本批未重新构建或改变探针，未重复无关 Go／前端全量。

## 复现与资源边界

在 `apps/control-api` 运行：

```bash
uv run --frozen pytest -q app/tests/test_openshell_behavior_coordinator.py \
  app/tests/test_openshell_behavior_journal.py
```

真实验收工具沿用 `owned-openshell-recovery-check.py`，在明确的 `--behavior-image`／`--probe-sha256` 及专用网关参数上增加 `--behavior-coordinated`。新辅助模块 `behavior_coordinated_fixture.py` 仅为隔离验收提供 SQLite、合成审批身份和已实际下发的父操作，不用于生产建表或授予业务权限。

本次私有输出为 `var/optimization-20261007/opt09-owned-coordinated-001/`。批准模板加载自独有的 0700 临时目录，结束后已清理；仓库父目录具有组写权限，因此没有放宽加载器规则以读取仓库内模板。接收线程、沙箱、独立网关和空网络均清理，数据库连接释放，原网关配置、TLS 和 CLI 注册元数据保持。私有验收库和日志作为本机复核材料保留，不提交仓库。未调用模型或访问日常业务数据库。

## 未完成范围

真实运行的身份授权由隔离数据库夹具提供，不能替代 JWT／权限、目标归属清单和业务审批链的生产复核。生产认证 API、前端、等级提升及过期／漂移后的展示与失效仍待实现；生产 PostgreSQL 上的新协调接线随 API 阶段验收。本批不将 SQLite 结果写成 PostgreSQL 结果，不将内部协调通过写成用户入口已上线。

OPT-09 保持 implementing，总体仍为 9/16。代码按本批本地提交，尚未推送远端或合并 main。
