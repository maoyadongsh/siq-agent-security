# 企业风险接受输入与终态边界预注册001

首次协议，未执行结果。当前候选`5470ab3780f2-riskfix1py312`已修复到期时区；冻结Python版本/二进制/依赖及源码，不调用模型、不访问现有业务系统。

现有威胁模型T15要求owner/reason/expiry；企业风险浏览器规格将resolved/risk_accepted定义为终态、无操作按钮；仓库不变量要求对象端点先定位404再鉴权403。本批验证这些已有语义在直接API请求下是否成立，不以UI隐藏按钮代替后端门禁。

真实原生Edge/Hermes Connector发现1个资产，合成签名Edge协议另有fixture-a资产。两者分别HTTP确认、实际规则引擎生成共4个finding，无SQL插入/重置finding。原生资产用于输入、鉴权、open/acknowledged正常接受控制；合成资产的实际规则finding用于resolved终态控制，分别记录身份，不能声称它是另一原生业务进程。

检查分配：

1. 合法body下，无权限的外租户和不存在对象应404；本租户无权限403；外租户有权限404。无finding、审计、outbox变化。
2. 空owner、纯空白owner、65字符owner、含换行owner、纯空白reason均应422；极端时区到期时间换算越界应受控422，不能500。每次前后比较完整finding、审计、outbox。
3. 原生资产风险open→acknowledged→risk_accepted应成功，owner/reason保留并恰新增1条接受审计及1条outbox；直接open→risk_accepted也应成功。
4. risk_accepted重复接受且改reason应409；resolved接受应409。终态内容、owner、审计、outbox均不变，不能借此覆盖修复引用或重复宣称resolved事件。

如旧产品错误接受输入导致状态污染，后续正常控制失败照实记录，不通过SQL重置抹除影响。resolved控制使用另一finding避免前面错误操作污染其初始状态。语义依据是既有规格，原先允许覆盖不被自动视为产品功能。

99项评测器显式HTTP（治理/合成Edge73+原生控制5+边界21），16项专项断言；原生Edge内部HTTP未独立计数。均为顺序场景，不能宣称并发互斥、通知、UI或自然攻击成功率。原始、导出、源码和协议哈希保留，离线重新评分，修复后另编号复测，不覆盖首次失败。

执行使用固定候选Python：

```bash
python benchmarks/third-party/enterprise_risk_boundaries_trial.py freeze --campaign third-party-evaluation/20261006 --protocol-id enterprise-risk-boundaries-001-protocol --candidate third-party-evaluation/20261006/private/candidates/5470ab3780f2-riskfix1py312
python third-party-evaluation/20261006/protocols/enterprise-risk-boundaries-001-protocol/harness-source/enterprise_risk_boundaries_trial.py run --campaign third-party-evaluation/20261006 --protocol-id enterprise-risk-boundaries-001-protocol --run-id enterprise-risk-boundaries-001 --candidate third-party-evaluation/20261006/private/candidates/5470ab3780f2-riskfix1py312
```
