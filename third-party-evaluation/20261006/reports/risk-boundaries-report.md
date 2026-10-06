# 企业风险接受输入、对象与终态边界实测

2026-10-06，作者侧本机执行。首次真实API/PostgreSQL测评为**132/150**，修复后相同99项请求、相同评分判据为**150/150**；无缺请求或测评器中断。原失败保留，不能把两批汇总成全通过，也不能把18项失败计作18个独立漏洞。

## 实际测了什么

真实原生Edge/Hermes Connector发现一个资产，合成签名Edge协议提供另一个fixture资产。通过HTTP确认两者，再调用实际规则引擎，各生成无负责人和无effective权限两种finding，共四项。没有通过SQL创建或重置finding。

输入、权限及open/acknowledged正常接受控制使用原生发现资产；resolved终态控制使用合成资产的实际规则finding。原生与合成资产的来源、ID及对应finding分别核验，不将合成资产冒充第二个原生业务进程。

判断依据是[威胁模型T15](../../../docs/threat-model.md)、[风险终态规格](../../../docs/development/enterprise-finding-explorer-handoff.md)及仓库“先定位404、后权限403”不变量。本次整理为[风险接受边界合同v1](../../../packages/contracts/enterprise-risk-acceptance.v1.md)。前端显示“已终态”不能替代直接HTTP接口的状态限制。

## 首次失败与修复后差异

| 条件 | 001原候选真实结果 | 002修复后结果 |
|---|---|---|
| 无权限外租户/不存在finding，合法body | 403，权限先于对象定位 | 404，符合本租户定位语义 |
| 本租户无权限 | 403 | 403；状态、审计、outbox不变 |
| 空owner、纯空白owner、含换行owner | 200，写入risk_accepted | 422，完全无写入 |
| 65字符owner | 500，PostgreSQL字段长度错误 | 422，请求模型受控拒绝 |
| 纯空白reason | 200，写入无实际原因的接受记录 | 422，完全无写入 |
| UTC换算越界的expiry | 500 | 422 `invalid_expiry`，无写入 |
| risk_accepted再次接受并改reason | 200，覆盖并再产事件 | 409，原记录与审计/outbox保持不变 |
| resolved直接接受 | 200，覆盖修复引用及终态 | 409，原修复引用保持不变 |
| 正常open→acknowledged→接受 | 前面错误接受已污染状态，ack409、控制失败 | 全流程正常，恰新增1条接受审计及1条outbox |
| 正常open→接受 | 正常 | 正常，负责人和原因保留 |

错误输入污染后续控制是本次观测的一部分；没有重置数据库来恢复“干净成功”。resolved使用独立finding，首次调用前确为resolved，因此不能将其终态覆盖归因于前面输入污染。

## 产品修复与验证

新候选`5470ab3780f2-riskboundaryfix1`继承`5470ab3780f2-riskfix1py312`，两批固定同Python3.12解释器指纹和依赖列表。新增修改仅涉及：

- [FindingAcceptRisk模型](../../../apps/control-api/app/schemas.py)：负责人采用已有CandidateConfirm的标识格式及64字符上限；原因至少包含一个非空白字符。
- [accept-risk路由](../../../apps/control-api/app/routers/findings.py)：按验证租户定位，再检查权限；仅open/acknowledged可接受，查询持有行锁至事务结束；到期UTC换算越界受控422。
- [15项回归测试](../../../apps/control-api/app/tests/test_risk_acceptance_boundaries.py)：修复前12失败、3通过；修复后与既有时区/规则/worker测试共66项通过，逐项检查拒绝不改finding、审计和outbox。

负责人存在性与目录归属仍由IAM负责，格式通过不等于目录验证。本批只有顺序请求；添加行锁不能代替真实并发接受/解决/到期竞态测评。原API字段和正常接受流程保留，没有放宽安全条件来让测试通过。

## 证据、复核与计数

每批99项评测器显式HTTP包含73项治理及合成Edge协议检查、5项原生控制面请求、21项本批风险请求；原生Edge内部HTTP未独立计数。两批累计198项显式HTTP，模型调用0、独立自然攻击任务增量0。

- [001预注册](../plan/enterprise-risk-boundaries-001.md)、[002修复后协议](../plan/enterprise-risk-boundaries-002.md)。
- [001导出](../data/enterprise-risk-boundaries-001/manifest.json)与[离线核验](enterprise-risk-boundaries-001-export-verification.json)：132/150，`passed=false`。导出锚点`6fdbbca61a115973dd8dd457e308f0c87f032b3ae98390e7356586f5d39ebb4d`；私有原始锚点`c45b7e2c8000af74c2c6683375f8c5688315a5d33876b415cf31de081f0af5fa`。
- [002导出](../data/enterprise-risk-boundaries-002/manifest.json)与[离线核验](enterprise-risk-boundaries-002-export-verification.json)：150/150。导出锚点`1ff22a97d48a3464ea4e3324bc2d52b646387ee0aff4eeab5c8f3fe38bf1b437`；私有原始锚点`2bf54ceca40f896dd632d4d5cf1a4c8e9a798a1d1d3b8486086400138775480c`。
- 两批实际HTTP、状态快照、审计与outbox均可重算。[002补充复核](enterprise-risk-boundaries-002-review.json)核对原生配置、CLI输出及finding来源；12种错误证据反例全部被拒绝。
- [001导出/清理检查](enterprise-risk-boundaries-001-export-review.json)、[002检查](enterprise-risk-boundaries-002-export-review.json)：已知设备secret/seed和凭据模式未匹配白名单导出；API、数据库容器和原生临时根均已清理。锚点为作者保存的完整性凭据，不是外部第三方时间戳。
- [工程验证](risk-boundaries-engineering-validation.json)记录产品全量回归2287通过、1项可选浏览器样本测试跳过；测评框架669 tests + 118 subtests通过，候选app lint与diff检查通过。

## 新候选的接续要求

早期enterprise-risk-001–003脚本曾在risk_accepted状态再次接受，以替换各时区测试的到期时间。终态修复后，该步骤会被正确拒绝，因此**旧到期脚本不能原样用于新候选**。旧候选及旧结果保留，但不外推为新候选完整到期链已通过。下一优先任务是：使用实际自然到期重开或独立finding，重新验证当前候选的接受→到期→重开→解决→导出链，不允许SQL重置或放开重复接受来迁就旧脚本。

RB13仍部分完成；并发状态竞争、长期worker/通知、UI整链、更多来源事实与历史/当前加载区分等仍待测。本批是内部可复现实测，不是外部独立认证或自然模型攻击成功率。
