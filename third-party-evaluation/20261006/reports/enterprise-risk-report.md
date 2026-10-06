# 原生企业资产风险生命周期与导出实测

2026-10-06，作者侧本机执行。首次真实测评发现风险接受到期的时区缺陷，完成产品修复后，以新候选、相同判据重新测评通过。**001为157/161，002和003均为161/161；三批各107项显式HTTP，无缺失或测评器中断。**失败证据保留，不将三批合并成全通过。

## 真实功能链与可归因结论

本批从实际Edge CLI注册、Hermes Connector扫描开始，在生产模式API和独立PostgreSQL17中产生原生发现资产及证据。通过产品HTTP确认该资产，不指定负责人、不创建effective权限；实际规则引擎识别“已确认但无负责人”和“无有效权限事实”两项风险，重复执行不新增同一风险。

随后实际完成：风险列表分页 → 确认 → 接受风险 → 后台到期重开 → 带修复引用解决 → OCSF导出。跨租户访问、缺权限、缺负责人字段、过去到期时间、无效状态转移和审计故障均通过真实API及数据库核对。没有把手工插入finding或构造返回值当作规则引擎工作。

这证明SIQ能从真实发现资产形成可治理风险、保持未知权限的事实边界、记录接受/解决审计，并按范围导出。它不证明该资产已经受到运行时保护；**风险接受不授予运行权限，修复引用字段也不证明外部工单真的存在。**

## 首次发现与修复

风险接受API将请求到期时间换算UTC校验；原worker却直接删去时区信息，再与naive UTC比较。因此，同一个截止时间的不同偏移表达产生不同结果。

| 时区表达 | 001原候选 | 003修复候选（Python3.12） |
|---|---|---|
| -08:00 | 尚有约3.58秒到期时已重开；到期后无新的重开 | 到期前保留接受，到期后重开1次，再运行0次 |
| +08:00 | 到期后及重复处理仍为risk_accepted | 到期前保留接受，到期后重开1次，再运行0次 |
| UTC | 到期前不重开，到期后重开1次 | 同样正确 |

每种使用API设置当前UTC+4秒的真实截止时刻，没有改主机时间或直接修改数据库到期值；执行前后保存UTC时间戳。首次所有早期worker都在截止前3秒以上结束，修复后也至少提前3秒结束，排除了“机器慢导致已经到期”的解释。具体窗口与原始stdout见[001复核](enterprise-risk-001-review.json)和[003复核](enterprise-risk-003-review.json)。

修复仅涉及[worker风险到期处理](../../../apps/control-api/app/worker.py)：先`astimezone(UTC)`再去掉tzinfo。原始记录、历史naive UTC、严格小于到期判断以及状态/审计/outbox事务语义保留。[修复说明](../../../docs/development/risk-acceptance-timezone-repair-20261006.md)及[回归测试](../../../apps/control-api/app/tests/test_risk_expiry_timezone.py)覆盖五种整小时/半小时时区，在到期前、等于和到期后共15种组合；旧代码6项失败，修复后全部通过，并检查重复处理不重复产生审计和outbox。

原候选为`5470ab3780f2-governancefix1`。002候选`5470ab3780f2-riskfix1`继承原有三份明确补丁，新增worker修复和测试，但uv自动选择Python3.13，原001保留环境为Python3.12；002属于存在解释器混杂的成功复测，不能作为仅改源码的严格对照。

因此另建同产品源码候选`5470ab3780f2-riskfix1py312`执行003，明确使用父候选Python3.12，冻结并在运行前核对解释器版本、二进制摘要和依赖包列表；与001保留环境的这些指纹完全相同，003再获161/161。001/002环境指纹为事后复核，不能伪称首次运行前已冻结，详见[环境比较](../inventory/enterprise-risk-runtime-comparison.json)和[003协议](../plan/enterprise-risk-003.md)。

三批Edge/Hermes Go源码、原生二进制摘要及锁文件未变，复用父候选原生二进制，不声称重新发行了安装包。

## 其余测量结果

| 功能 | 实际证据与结果 |
|---|---|
| 风险识别与幂等 | 同一原生资产2项预期风险；再次执行规则finding ID集合不变；effective事实数0 |
| 风险分页 | limit1的两页无重复、无遗漏；首页面截断1，末页0，returned均1 |
| 授权与参数边界 | 跨租户404、无权限403、缺owner422、过去expiry422；finding、审计及outbox前后不变 |
| 审计失败关闭 | 故障触发器导致接受风险500；完整状态回滚；恢复审计后正常接受 |
| 接受与解决 | 正常接受有owner/reason/expiry、审计及outbox；接受状态不能直接解决；到期重开后带fixture引用解决成功，重复解决409 |
| detection_finding导出 | limit1返回1条且截断1；完整返回2条且截断0；finding ID及状态映射与独立SQL一致 |
| 导出租户与时间范围 | 另一fixture租户、未来since均返回空；no-store与NDJSON媒体类型正确 |
| 导出审计 | 每次成功导出新增本租户1条记录，count等于实际返回数；summary只含class/count/since |
| 非法导出 | 无效class、极端时区since、无权限拒绝；无新增导出审计 |
| api_activity | 按数据库顺序逐条关联操作、actor、resource和summary；未借用另一租户审计 |

OCSF检查按本产品映射合同完成，不等于外部OCSF schema认证；该接口是有范围和上限的快照导出，不是完整归档系统。

## 分母与证据

每批107项显式HTTP包含73项既有治理/合成Edge协议检查、5项原生控制面请求、29项风险及导出请求。原生Edge内部注册/任务/上传/回执HTTP未独立计数。每批执行9个真实reaper子进程，三次实际等待截止窗口；三批累计321项显式HTTP、27次reaper调用。模型调用0，独立自然攻击任务增量0。

- [001预注册](../plan/enterprise-risk-001.md)、[002修复后协议](../plan/enterprise-risk-002.md)，三批风险评分器和判据相同。
- [001导出包](../data/enterprise-risk-001/manifest.json)及[离线核验](enterprise-risk-001-export-verification.json)：保留157/161及`passed=false`。导出锚点`d877af37d50b2ed0a92df8b627985ebbacacba5c0535d687ce45e1798b4070d3`。
- [002导出包](../data/enterprise-risk-002/manifest.json)及[离线核验](enterprise-risk-002-export-verification.json)：161/161。导出锚点`0847924d4e401b808b805b3411a27e8bfec94dbb06f7bc380fd1014e2f90af57`。
- [003解释器对齐导出包](../data/enterprise-risk-003/manifest.json)及[离线核验](enterprise-risk-003-export-verification.json)：161/161。导出锚点`8971c221b9b00009eb27469bf2cd8bf8117329a63f7774b5c0b5b0e4f8c83929`，私有原始锚点`712296f3a5af0ce16fd99574846df8fa2d00479777e4d4521d033209f04ec460`。
- 001/002私有原始锚点分别为`e5a921e806a33d6bc7ff60bb33028d14a0dc1c7ca8180237804ddda6858a57b4`、`79afa8b8466c98b29abb60a41b62158c6dd62d92417387074780c145b893e579`；完整性锚点不是第三方时间戳。
- 三批各核对9份worker原始输出、原生CLI捕获、配置摘要和资产关联。002和003各自12种错误证据反例全部被拒绝，包含提前重开、漏重开、审计缺失、隐藏截断、跨租户导出及假effective。
- [001资源与导出检查](enterprise-risk-001-export-review.json)、[002资源与导出检查](enterprise-risk-002-export-review.json)、[003资源与导出检查](enterprise-risk-003-export-review.json)：已知设备secret/seed及凭据模式未匹配白名单导出；各批API进程、数据库容器和原生临时根均已清理。
- [工程验证](enterprise-risk-engineering-validation.json)记录产品回归、lint和测评框架回归；[最终测评框架](enterprise-risk-framework-tests-002.txt)669 tests + 118 subtests通过。Python3.12和3.13的候选控制API全量回归各2272通过、1跳过；跳过项为未配置SIQ_BATCH_WIRE_SAMPLE的可选浏览器实采Go响应合同验证，不算通过。

## 当前边界与接续

本批采用实际worker中的reaper函数，由独立子进程受控调用；未验证长期运行worker的调度延迟、外部通知/Webhook或恢复重启。本批测试issuer仍非客户IdP；外部工单与负责人目录不在本服务核验范围。没有修改已有业务服务或重跑旧候选覆盖失败。

RB13仍保持部分完成：框架/角色/Skill历史与当前加载的区分、更多事实来源、风险重复接受/空白owner等输入边界、无权跨租户对象的定位优先级、完整UI和截断极限需继续。其他到期功能也不能自动继承本次风险reaper的时区结论。真实跨OS、自然模型确认集和独立第三方复现保持未完成。
