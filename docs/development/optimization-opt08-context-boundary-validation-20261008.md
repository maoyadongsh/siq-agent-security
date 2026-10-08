# OPT-08/10：执行上下文撤销、新任务与 Agent 基线边界验证

日期：2026-10-08。环境：DGX Spark＋智能分析助手＋Hermes 原生 Skill＋OpenShell＋SIQ Agent Security。

本批确认：**只撤销已加载 Skill 的当前执行上下文（SEC），即可使后续实际写入失败；保持 Skill Grant 与 Agent 基线有效后，新任务仍能取得不同的合法 SEC 并完成读写。** 旧上下文的签名撤销记录保留，没有恢复旧授权或修改安装内容。

此外，可信宿主明确确认“本任务未使用 Skill”的调用可以按获批 Agent 基线执行。这是 ADR-056 的既有设计。该补充用例的权限与文件效果验证通过，但最终回答被业务财务证据护栏替换，整例保留失败，不计入已通过业务用例。

## 1. 候选与控制变量

业务提交 `8851724`，安全二进制来自 `32e10d54` 固定 Git 导出。每轮运行前冻结 1,874 个业务输入，分别登记 289 个与业务 HEAD 不同的输入；候选摘要均为 `5bbf4e90636c45ed58d801de1481d5bb10a216ecb68390e587bea18efc791521`。这些是已登记的工作候选，不冒充完全干净的提交部署。

镜像身份为 `sha256:dc22c45069ef34d107220ca5253ca6f2c572fc6b035f434b1b16948e67a88d21`，原生运行包摘要为 `070e94236ba603b6e7cff70f217e3a43e15f20dd7213cb03cabade3c2cf553b2`。各例驱动执行前登记摘要，源文件、归档与驱动在执行后复核。

各请求经真实 HTTP 登录与聊天流入口，调用本地模型和真实 Hermes 工具，在独立 OpenShell 任务目录创建合成标记文件。使用本批隔离 Authority 和受控授权，日常业务数据库与原模型服务不作切换。管理凭据仅由现场控制器持有。

## 2. 执行结果与分母

| 用例 | 预设条件 | 实际观察 | 完整业务用例状态 |
| --- | --- | --- | --- |
| v855 | 已批准 writer Skill，加载、读取后写入 | 3 条 allow 回执；指定文件及内容匹配 | 27 项检查通过 |
| v856 | 读取完成后撤销当前 SEC，保持两个 Grant 有效 | 后续真实 `write_file` 报错；文件不存在；只有撤销前 2 条 allow 回执 | 30 项检查通过 |
| v858 | 旧 SEC 保持撤销，新建合法任务 | 新 SEC 与旧 SEC 不同；加载、读取、写入成功，文件匹配 | 27 项检查通过 |
| v859 | 宿主明确无 Skill，依 Agent 基线写入 | 1 条签名 `no_skill=true` allow 回执；未签发 SEC；文件及内容匹配 | 23/24 项通过，最终回答标记检查失败，整例失败 |

另有先行 v857：脚本把明确无 Skill 错误地当作归属不明，预期拒绝，实际按 Agent 基线允许。原始失败保留；它既不是越权漏洞，也不计入完整通过分母。

本批 **3 个完整业务用例通过，2 个原始失败保留**。v859 的权限结果单列，不改写其预登记检查或退出码。四个请求具有可离线绑定的实际决定证据，故核验器输出 `case_decision_bindings=4`；这个数字不是四例业务验收通过。

## 3. 上下文撤销如何生效

控制器观察到 v856 的真实读取完成后，查找同一请求的签名读取回执，确认 writer Grant 与 SEC。先读取 `/v2/skill-contexts/{id}`，再以原 `context_signature` 为前置条件调用其 `/revoke` 端点，最后读回原上下文和新增的签名撤销记录。

撤销前后的 Skill Grant、Agent Grant 完整 HTTP 快照（含状态 revision）一致；writer 状态仍为 approved，Agent 基线仍为 deployed，实际安装文件未改变。撤销的是这次执行上下文，没有撤销 Skill 的长期授权。

撤销 HTTP 返回后约 **9.967 秒**，现场控制器观察到实际写入开始事件，随后工具返回错误；目标文件及符号链接均不存在。该间隔来自 SSE 到达的单调时钟，不是独立记录的 handler 开始时刻，也不是撤销生效 SLA。

v858 随后从同一 Authority 获得不同 SEC，并成功写入。独立核对确认旧 SEC 的撤销文件仍与原签名内容完全相同，新 SEC 不在该撤销记录中。这支持“按执行上下文撤销、允许独立合法新任务”的能力边界。

## 4. 与 OpenShell、Agent 基线的关系

各请求的实际 OpenShell 策略均与启动清单摘要匹配，当前任务输出目录均在 `read_write`。仅规范化请求 run/nonce 后，四份策略一致；正向实际文件存在，输出目录设备号与 inode 与启动记录一致。

因此，v856 拒写不来自文件系统目录本身不可写。它补充了 [Skill Grant 撤销对照](optimization-opt08-skill-grant-effect-validation-20261008.md)，说明 SIQ 可以分别约束 Skill 授权与一次执行上下文，而 OpenShell 继续提供外围运行边界。

依据 [ADR-056 第 6 条](../adr/0056-native-skill-invocation-authority.md)，可信宿主确认未使用 Skill 时使用获批 Agent 基线；未知加载、缺失可信调用归属、混合或不完整祖先必须失败关闭。`no_skill` 由可信宿主记录，不由模型工具参数自行声明。**未加载 Skill 不等于 Agent 没有权限，明确无 Skill 也不等于来源未知。** 本批没有完成“缺失可信证明”的真实负向验收。

## 5. 业务回答护栏与保留失败

v857 与 v859 的最终回答均出现 `guardrail_status=blocked`、`guardrail_reason=financial_evidence_missing`。业务回答被证据不足提示替换，因此没有返回请求中的预设标记。v859 的签名 allow、工具成功及真实文件内容已经分别核对，仍不据此把回答检查改成通过。

已定位回答保护入口为业务仓 `services/agent_runtime_financial_guard.py` 的 `enforce_financial_evidence_contract`，是否需要财务证据由 `agent_chat_runtime_impl.py` 的 `_needs_financial_evidence_contract` 等业务判断决定。当前只确认实际替换现象与调用位置，具体触发分支和用户体验修复仍待单独复现；未放宽财务真实性保护。

v859 监管单元保留 failed/退出 1，但 MainPID 与 ControlPID 均为 0，业务 finalizer 为 released，自有网关、模型桥、沙箱与临时数据库清理已确认。服务退出状态和资源回收状态分别记录；另外三例监管单元均为 inactive/success/退出 0。

## 6. 签名证据与离线核验

本批独立 Authority 链共 **10 条回执、3 份 SEC、1 份 SEC 撤销记录、2 份有效 Grant 签名快照**。10 条中，完整通过三例占 8 条，v857/v859 各 1 条；为保持链连续，失败用例回执保留。没有与其他 Authority 的历史链拼接。

v856 在写入决定回执产生前被拒绝，故本批没有该写入的签名 deny。读取 allow 回执用于绑定撤销对象，不能替代写入拒绝证据；拒绝效果由实际工具错误和独立文件观察共同记录。

- [结果、候选与现场观察](evidence/optimization-20261007/native-context-boundary-v855-v859.json)
- [完整回执链](evidence/optimization-20261007/native-context-boundary-v855-v859.receipts.jsonl)
- [签名上下文](evidence/optimization-20261007/native-context-boundary-v855-v859.contexts.json)
- [签名撤销记录](evidence/optimization-20261007/native-context-boundary-v855-v859.context-revocations.json)
- [Skill 与 Agent 授权快照](evidence/optimization-20261007/native-context-boundary-v855-v859.live-grants.json)

```bash
apps/control-api/.venv/bin/python scripts/research/verify_native_business_evidence.py \
  docs/development/evidence/optimization-20261007/native-context-boundary-v855-v859.json
```

核验器新增可选撤销与有效 Grant 材料核对：验证签名、schema、准确上下文签名绑定、签发／撤销时间顺序、Grant 内容摘要和实际上下文／无 Skill 回执的 Agent 授权绑定。Grant 引用摘要按照既有 Go `GrantDigest` 的浮点 JSON 数值规范复算，签名 payload 仍保留原整数规范，不混用两个规范。

33 项相关测试及 Ruff 通过，包括真实证据、改写撤销后重算外层摘要、缺失绑定、替换已签名权限和无 Skill 回执错误 Agent 归属的负向用例。首次现场核验发现整数／浮点摘要规范差异，校正独立核验器后通过，没有修改历史 Grant 或产品状态。

离线核验不重新观察宿主文件，不证明现场时间先后，也不授权当前执行；原始私有配置、凭据、业务流和状态不公开。

## 7. 进度与后续

自有资源已清理，三个临时服务配置已恢复，原模型未重启，业务输入未改变。API 依赖在本批前后均为 11,663 文件、4 链接，摘要 `ec6da2fd01ce3ea539f3fc333ced90be3a7f6f17a469e54132d49f522979bd34`；这仍不是完整操作系统和模型栈冻结。

后续继续未知归属／调用证明缺失、运行中到期、并发与其他资源矩阵，以及最终同候选归因、平台和正式签名验收；新增回答护栏触发原因亦保留待办。本批不重复未修改模块的全量测试。

OPT-08、OPT-10 保持 implementing，总体主任务验收仍为 **11/16（68.75%）**。本批属于权限生命周期证据和独立核验工具增量，尚未达到整体交付与远端推送条件。
