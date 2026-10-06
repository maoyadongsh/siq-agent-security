# 企业真实目标独占与当前授权测评报告

2026-10-06，本项目作者侧执行。批次`enterprise-authority-001`首次完整运行通过：**113项评测器显式HTTP、176/176项检查**。这不是外部第三方认证，也不是176个独立攻击样本。

## 产品理解修正与结论

SIQ当前实现的是**独立目标授权与治理部署**：发现资产不授予目标所有权，审批通过不替代部署管理员的精确目标分配，旧回执也不替代回滚时的当前授权。本批真实执行证实了这些门禁的作用。

同时，当前版本不支持共享沙箱的权限交集或多Skill隔离。依据[ADR0053](../../../docs/adr/0053-enterprise-runtime-target-authority.md)、[授权加载实现](../../../apps/control-api/app/target_authority.py)、[绑定路由](../../../apps/control-api/app/routers/bindings.py)、[影响报告](../../../apps/control-api/app/routers/deployment_impact.py)，本批将原“共享目标/多绑定效果”细化为：相同目标重复绑定应拒绝；同连接同目标多租户分配应拒绝；影响报告应诚实披露未知。不能通过把全部请求拒绝来宣称共享业务可用或细粒度隔离已实现。

## 实际业务路径

沿用固定候选`5470ab3780f2-governancefix1`，本批重新创建生产模式API、PostgreSQL17、RS256/JWKS测试issuer，以及独立OpenShell v0.0.104网关、sandbox和receiver。真实Edge CLI注册、领取任务，真实Hermes Connector扫描1份配置、上报1个候选和1份证据；SIQ实际部署使用该原生发现资产。

链路为：原生发现 → 资产与实例绑定 → 独立审批 → 部署管理员目标授权 → 预览与影响检查 → SIQ部署 → 后端读回和实际请求 → 故障授权下的回滚拒绝 → 恢复合法授权后回滚。另一合成资产只用于尝试抢占目标，实例为管理API登记，并未启动第二个Hermes业务进程；预注册步骤2的“原生实例”不应解读为两个原生业务共用沙箱。无既有业务数据库、网关或真实客户资产被修改。

113项显式HTTP包含管理请求和沿用的合成Edge协议负向请求，**不包括原生Edge内部HTTP**；后者未独立计数。模型调用0，不增加S4独立任务数。

## 新增边界结果

| 条件 | 实际响应 | 独立状态或业务核对 |
|---|---|---|
| 另一资产实例登记相同后端目标 | 409 `binding_target_conflict` | 未新增绑定，数据库核心状态和后端策略不变 |
| 当前精确绑定的影响报告 | 200 | 主体与原生资产相符；coverage=registered_binding_only、shared_runtime_occupants=unknown、skill_isolation=not_established、execution_confirmation_supported=false |
| 6种失效授权下请求预览 | 各409 `deployment_target_authority_unverified` | 每种均无部署、策略或变更状态效果，后端版本及策略不变 |
| 合法授权改为另一assignment id，提交旧preview_digest | 409 `deployment_preview_changed` | 未部署；恢复原字节后正常提交成功 |
| effective部署在6种失效授权下请求回滚 | 各502 `openshell_rollback_failed: <digest>` | 每种新增1条rollback_fail审计；effective状态和后端限制保留；6次真实业务请求均被阻止 |
| 恢复原授权并正常回滚 | 200 | 策略内容恢复，实际正常请求再次到达且返回正确nonce |

六种失效状态分别是：删除授权文件、空分配、过期、错误asset、错误gateway摘要、同连接同目标增加另一tenant分配。每次由评测器在本批私有授权文件上显式注入并恢复原字节，不使用SQL伪造授权通过。每种都在预览和回滚两个阶段执行，共12个拒绝请求。

回滚失败当前使用502，属于产品错误分类现状；结论依据数据库、独立后端和接收端证据，不把HTTP错误码当作“请求已被安全阻止”的充分证据。

## 实际效果与归因

| 阶段 | 后端版本 | sandbox真实curl | receiver业务到达 | 健康控制 |
|---|---|---|---|---|
| 部署前允许基线 | 2 | exit 0，内容正确 | 1 | 正常 |
| SIQ审批部署收紧后 | 3 | exit 22，403 | 0 | 正常 |
| 6种失效授权各自拒绝回滚后 | 每次保持3 | 6次均exit 22，403 | 每次0 | 6次均正常 |
| 恢复合法授权并回滚后 | 4 | exit 0，内容正确 | 1 | 正常 |

以上9次业务执行使用同sandbox、同receiver和不同随机nonce；正常阶段与恢复阶段验证返回内容，拒绝阶段验证接收端仍健康。原始CLI stdout/stderr、receiver日志、健康命令和时间顺序均交叉复核，另核对28份新增拒绝前后策略读回与其真实CLI命令。

可归因结论：**SIQ的授权门禁阻止无当前授权的策略变更，SIQ驱动的OpenShell限制实际阻止指定网络请求，合法回滚恢复效用。**这是组合链路效果，不能将OpenShell的网络隔离全部归为SIQ自有运行时能力；也不能扩展为自然模型提示注入防护成功率。

## 证据与可复现入口

- [预注册协议](../plan/enterprise-authority-001.md)、[冻结协议及源码摘要](../protocols/enterprise-authority-001-protocol/protocol.json)。
- [脱敏导出清单](../data/enterprise-authority-001/manifest.json)、[原始离线核验](enterprise-authority-001-verification.json)、[导出离线核验](enterprise-authority-001-export-verification.json)，两者均重算176/176且无缺项。
- 私有原始manifest锚点：`7f274d8e77f70f29d649f0aa7a22bb2380c745d5175c492fadd6e6be504f549d`。
- 导出manifest锚点：`79576c2bd00d3fce52634e48f6f1e19e42057cd42b001093e390db89455e7427`。二者为作者保存的完整性锚点，不是第三方时间戳。
- [原始命令复核](enterprise-authority-001-review.json)：12种基于本次实际授权证据的错误变体全部被拒绝；沿用原链6种效果证据负向复核也通过。
- [导出和资源复核](enterprise-authority-001-export-review.json)：已知设备secret/seed与凭据模式未匹配导出文件；本批API/网关进程、数据库/sandbox/receiver容器、网络和原生临时目录均已清理。
- [框架回归](enterprise-authority-framework-tests-001.txt)：669 tests + 118 subtests通过。新增评分器15项测试包括14种错误证据反例；[工程核验](enterprise-authority-engineering-validation.json)记录范围。

从项目根目录离线核验导出包，无需启动服务：

```bash
third-party-evaluation/20261006/private/candidates/5470ab3780f2-governancefix1/apps/control-api/.venv/bin/python \
  third-party-evaluation/20261006/protocols/enterprise-authority-001-protocol/harness-source/verify_governance.py verify \
  third-party-evaluation/20261006/data/enterprise-authority-001 \
  --expected-manifest-sha256 79576c2bd00d3fce52634e48f6f1e19e42057cd42b001093e390db89455e7427
```

## 方案接续与限制

本批关闭RB14中“独占目标与顺序授权撤销/替换”的这一变体；完整RB14仍未关闭。共享运行时交集语义属于未实现能力，不能继续作为“已有功能等待一次实测即可通过”。检查后写入竞态、批量部署/丢响应与恢复、持续发现、企业UI全链、真实IdP及正式签名安装另列未完成；其他OS、自然模型确认集与独立第三方复现也不由本批覆盖。

此次只新增测评器、数据和方案，没有修改产品实现、放宽安全条件或重写旧批结果。[企业链001–004的全部失败与成功](enterprise-chain-report.md)仍保留。本批原始成绩不依赖事后改变预注册判据。
