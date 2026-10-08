# OPT-08/10：可信无 Skill 调用的完整业务正向复测

日期：2026-10-08。环境：DGX Spark＋智能分析助手＋Hermes＋OpenShell＋SIQ Agent Security。

本批新增 v860，**30 项现场检查全部通过**：在宿主明确确认未使用 Skill、Agent 基线已获批的条件下，真实 `write_file` 成功，输出文件内容正确，最终模型回答包含预设标记，任务和自有资源正常释放。

这是 [上下文撤销与新任务验证](optimization-opt08-context-boundary-validation-20261008.md) 的增量补充。该文中的 v857/v859 原始失败及签名证据保持不变，本批不改写原分母。

## 1. 为什么补做本例

v859 已有可信 `no_skill=true` allow 回执和真实文件效果，但最终回答被业务财务证据护栏替换，整例失败。通过业务仓内只读分类器复现，原提示的七个财务证据判断分支中，只有 `_should_consider_wiki_fulltext_fallback` 返回 true，导致 `_needs_financial_evidence_contract` 要求财务证据。

在任务描述开头明确“这是 Hermes runtime 连通与工具权限验收”后，现有运行诊断分类器返回 true，该请求不再要求财务证据。向同一描述追加“请分析营业收入”时，财务证据要求仍为 true。四个只读诊断断言通过，未调用模型、数据库或业务 HTTP。

v860 因此采用明确标注的运行验收描述，保留原预登记检查：实际工具调用、目标路径与内容、最终回复标记、无 Skill 加载／SEC、签名授权绑定、认证与资源清理。没有修改产品分类规则、关掉护栏或删除失败检查。

这个复测证明明确运行诊断请求能完成，并不证明所有非财务自由文本均能正确分类。原提示的分类现象仍是业务体验待评估项；运行诊断标签也不是权限授权，实际工具仍由 SIQ 门禁裁决。

## 2. 真实结果

| 验证点 | v860 结果 |
| --- | --- |
| 业务入口 | 实际登录与 `/api/analysis/chat/stream`，真实本地模型 |
| Skill 使用 | 未调用 `skill_view` 或 `read_file`；本请求未签发 SEC |
| 决定证明 | 1 条签名 `write_file` allow 回执，`native_invocation.no_skill=true`，contexts 为空 |
| 授权 | Agent 基线及安装 writer Skill Grant 完整签名内容与先前快照一致；实际基线状态为 deployed |
| 文件效果 | 唯一任务输出文件存在，精确内容、摘要与回执资源绑定匹配 |
| 回答 | SSE 无 error，唯一 done 成功，返回预设标记 |
| 清理 | finalizer released；监管 inactive/success/退出 0，MainPID／ControlPID 均为 0 |
| 服务保护 | 自有网关与模型桥停止，三个配置恢复，原模型未重启 |

v860 使用与 v855/v856/v858/v859 一致的 1,874 个冻结业务输入、289 项登记差异、`8851724` 业务基线、安全二进制和原生镜像；候选摘要仍为 `5bbf4e90636c45ed58d801de1481d5bb10a216ecb68390e587bea18efc791521`。驱动执行前登记、执行后核对。归一化 OpenShell 策略仍相同，实际任务目录均可写。

API 依赖前后仍为 11,663 个文件、4 个链接，摘要 `ec6da2fd01ce3ea539f3fc333ced90be3a7f6f17a469e54132d49f522979bd34`；不是全栈冻结。

## 3. 增量证据与统计口径

本 Authority 链由原 10 条增至 **11 条回执**，仍为 **3 份 SEC、1 份签名撤销记录、2 份有效 Grant 签名快照**。v860 无 Skill，因此没有新增 SEC。

最终完整通过用例为 v855、v856、v858、v860，共四例，占 9 条回执；v857/v859 两次失败各占一条，继续保留以维护链连续。不同条件各是单次试点，不是同条件四次重复，也不是无保护／仅 SIQ／仅 OpenShell／联合保护的四臂实验。

本增量报告引用先前上下文／授权材料的原文件和摘要，仅增加新回执链和结果。离线核验器确认 11 条链签名、3 份 SEC、1 份撤销记录、2 份 Grant 内容摘要以及四个完整请求的决定绑定；不重新观察现场效果，不授权当前执行。

- [增量结果与只读分类诊断](evidence/optimization-20261007/native-context-boundary-v860.json)
- [累计 11 条回执链](evidence/optimization-20261007/native-context-boundary-v860.receipts.jsonl)
- [原始批次及失败保留](evidence/optimization-20261007/native-context-boundary-v855-v859.json)

```bash
apps/control-api/.venv/bin/python scripts/research/verify_native_business_evidence.py \
  docs/development/evidence/optimization-20261007/native-context-boundary-v860.json
```

新增真实增量材料回归检查后，相关套件 **34 项通过**，Ruff 通过；这个数量包含上一批 33 项，不累加为 67 项。没有重复无关产品模块全量测试。

## 4. 当前结论与后续边界

结合本批上下文撤销对照，可以分别说明：有效 Skill 能执行获批动作；当前 SEC 撤销后不能继续写入；独立合法新任务可重新取得 SEC；可信无 Skill 任务仍按已获批 Agent 基线工作。

“来源未知／必需调用证明缺失”的真实负向、运行中到期、并发、其余资源矩阵、最终同候选归因、Windows／macOS 和正式签名升级验收仍未完成。OPT-08、OPT-10 保持 implementing，总体主任务 **11/16（68.75%）**；本批本地提交，整体交付前不推送。
