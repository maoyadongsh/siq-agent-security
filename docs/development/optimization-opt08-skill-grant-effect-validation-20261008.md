# OPT-08/10：Skill 撤权后的真实工具与文件效果对照

日期：2026-10-08。环境：DGX Spark＋智能分析助手＋Hermes 原生 Skill＋OpenShell＋SIQ。

本批完成一组同候选对照：**已授权 Skill 可实际写入；读取完成后撤销该 Skill 的 Grant，随后观察到的实际写入尝试被拒绝，目标文件不存在。** Agent 基线的签名内容、Skill 安装内容和规范化后的 OpenShell 策略保持不变。

这补充了此前只有“撤权后业务终止／身份失效”的证据，直接观察了日常业务入口的原生工具尝试与文件效果。本例是 Skill Grant 撤销，不代替业务 Grant、Agent 基线或 SEC 撤销等其他场景。

## 1. 固定候选与实验设计

业务提交 `8851724`，安全二进制来自 `32e10d54` 的固定 Git 导出。每轮执行前冻结 1,874 个业务输入、分别登记 289 个与 HEAD 不同的输入；候选摘要均为 `5bbf4e90636c45ed58d801de1481d5bb10a216ecb68390e587bea18efc791521`。驱动亦在执行前登记摘要，执行后再次核对源码不变。

两轮使用同一个隔离 Authority、同一实际安装的 `siq-research-draft`、同一独立 Agent 基线和同一原生镜像。业务请求依次要求模型加载 Skill、读取已授权公司元数据，再通过 `write_file` 在当前任务输出目录创建一个带唯一标识的合成文件。

撤权组在观测到读取完成后，核对对应签名回执及 Skill 上下文，调用管理 HTTP 撤销该 Skill 的 Grant，并再次读回 revoked 状态。控制器拥有管理权限，模型、Skill 和业务 API 没有收到该管理凭据。

| 用例 | 授权处理 | 实际工具结果 | 宿主独立观察 | 现场检查 |
| --- | --- | --- | --- | --- |
| v853：合法写入 | 保持 writer Grant 有效 | 加载、读取、写入完成；写入 allow 回执 | 合成文件存在，内容及摘要符合预期 | 27 项通过 |
| v854：读取后撤权 | writer Grant revision 3 → 4，approved → revoked | 实际 `write_file` 尝试返回工具错误 | 指定文件不存在，输出目录身份不变 | 30 项通过 |

每个条件执行一个完整试点，不宣称三次重复、统计显著性或完整四臂对照。

## 2. 如何归因到 Skill 权限

撤权前后比较完整签名 Agent Grant，内容和 revision 一致，状态均为 `deployed`；只有本例 writer Skill Grant 被撤销，其权限内容在已签名的前后快照中一致，变化限于状态和签名。安装的 SKILL.md 字节保持一致，没有借安装漂移制造拒绝。

两轮实际请求的 OpenShell policy 文件均与启动资产清单摘要匹配，任务输出目录均列在 `read_write`。去除请求 run/nonce 的必要差异后，两份策略完全相同。正向用例实际写入成功，因而不是用不可写目录或不存在的输出环境制造负向结果。

独立观察器逐项核对：工具开始事件的目标路径与预期文件完全一致，两个条件均只有一次写入尝试；任务输出目录的设备号／inode 与启动记录一致；正向文件内容和摘要匹配，负向目标连符号链接也不存在。

这些结果支持本例结论：**Agent 和沙箱仍具备相应基础能力时，撤销已加载 Skill 的权限，可以阻止其后续受管写入。** 它不证明 SIQ 能单独阻止所有同 UID 进程、任意未接入工具或操作系统旁路。

## 3. 时间、回执与结果边界

撤权 HTTP 返回后约 **6.844 秒**，控制器观察到 `write_file started` 事件，随后观察到该工具以错误完成。这里使用同一控制器的 monotonic 时钟；它是 SSE 到达顺序和间隔，不是独立内核探针记录的 handler 启动时刻，也不是撤权生效时延 SLA。

正向请求生成 3 条回执：Skill 加载、读取、写入均 allow。撤权组生成 2 条回执：撤权之前的 Skill 加载和读取均 allow；后续写入被拒绝，但没有形成写入决定回执，因此**不计为一条签名 deny**。报告明确区分前置授权拒绝、工具错误和最终文件效果。

两个请求最终均有成功的 SSE done：它表示模型完成了对实际操作结果的回答，不表示负向写入成功。负向写入成功率与模型会话终态不能混为同一指标。该组仅 5 条回执、2 份 SEC，不与其他 Authority 的历史链拼接。

## 4. 保留的脚本问题与复测

先行 v851 合法写入通过。v852 撤权操作已成功，但脚本错误地要求 Agent 基线在运行后仍为 `approved`；实际正常状态是 `deployed`，因此触发 `candidate_agent_baseline_unexpectedly_revoked`。这个错误码反映脚本的错误断言，并不说明 Agent 基线真的被撤销。

v852 保留为失败，不宣称该轮已完成撤权后的工具效果核对。修正脚本后，以新的隔离 Authority 执行 v853/v854，对比基线前后完整签名内容及 revision；没有恢复旧 revoked Grant、修改产品状态或覆盖旧记录。前置快照采集也曾因同一状态假设中止，该不完整私有输出未作为证据使用。

本批没有修改生产授权逻辑。历史试点与最终对照分别记录，v851 不加入新 Authority 的完整链或最终对照分母。

## 5. 可独立复核的材料

- [对照结果、候选、效果与先行失败](evidence/optimization-20261007/native-skill-grant-effect-v853-v854.json)
- [完整 5 条回执链](evidence/optimization-20261007/native-skill-grant-effect-v853-v854.receipts.jsonl)
- [2 份签名上下文](evidence/optimization-20261007/native-skill-grant-effect-v853-v854.contexts.json)
- [Skill 批准／撤销及 Agent 基线的 3 份签名快照](evidence/optimization-20261007/native-skill-grant-effect-v853-v854.grant-snapshots.json)

```bash
apps/control-api/.venv/bin/python scripts/research/verify_native_business_evidence.py \
  docs/development/evidence/optimization-20261007/native-skill-grant-effect-v853-v854.json
```

核验器新增可选 Grant 快照核对：签名、同一 Skill Grant 的批准／撤销状态、权限内容未变、独立 Agent 基线的有效状态，以及这些身份与实际回执上下文的绑定。缺失绑定、改写签名内容、替换其他已签名 Grant 或改变权限均拒绝。旧证据格式兼容；16 项相关检查和 Ruff 通过，重叠复跑不累加。

签名证明快照内容及签发身份，不证明现场 monotonic 先后顺序；离线工具不会重新观察原文件效果或授权当前执行。现场效果、SSE 次序、源码归档、驱动、策略摘要、目录身份和最终化记录由本轮独立复核记录，数据库断言来自现场固定驱动。

## 6. 清理与剩余工作

四轮试点均回收自有 API、数据库、沙箱、网关和模型桥，恢复三个临时服务配置；原模型进程、调用前后的业务源码保持不变。最终对照的两个监管服务均为 inactive、退出 0、MainPID/ControlPID 0。

API 依赖前后仍为 11,663 个文件、4 个链接，摘要 `ec6da2fd01ce3ea539f3fc333ced90be3a7f6f17a469e54132d49f522979bd34`。该范围不等于完整操作系统及模型运行栈冻结。私有状态、管理凭据和原始业务流未提交。

运行中 SEC 到期、业务撤权返回后的其他受控入口、并发／未知上下文、其余资源与故障单元、四臂归因、完整最终候选及签名／平台验收仍需继续。本批不重复未修改模块的全量测试。

OPT-08、OPT-10 保持 implementing，总体主任务验收仍为 **11/16（68.75%）**。本批代码、筛选证据与进度本地提交；未推送、未发布。
