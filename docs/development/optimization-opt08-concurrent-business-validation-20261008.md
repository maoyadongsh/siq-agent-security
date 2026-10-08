# OPT-08/10：真实并发请求的排队与 Skill 权限隔离

日期：2026-10-08。环境：DGX Spark＋智能分析助手＋Hermes 原生 Skill＋OpenShell＋SIQ Agent Security。

**本批完成两个同时在途的真实业务 HTTP 请求验收：reader 在 writer 占用网关时排队；writer 写入成功并释放后，reader 使用自己的只读 Skill 执行，实际写入被签名拒绝，文件未生成。36 项现场检查通过。**

当前业务网关按既有合同只允许一个运行所有者，因此本批证明并发请求经过排队后的权限隔离，不宣称两个沙箱同时执行。没有为得到“并发通过”而绕开网关所有权约束。

## 1. 与现有合同一致的验收范围

业务仓库 `docs/architecture/qwen38-request-runtime-v1.md` 和 `qwen38_request_queue.py` 明确采用按请求创建、单槽排队、终态回收。请求在排队时仍须保持自己的业务授权与租约；前一任务的权限、身份和输出目录不能转交给下一任务。

本批使用同一真实 API 进程、隔离数据库、已认证测试用户、业务数据 Grant、公司目录及同一 Agent baseline，分别通过正式会话 API 创建两个不同会话，再发起两个真实 SSE 请求：

| 角色 | 实际加载的 Skill | 该 Skill 的批准范围 | 目标 |
| --- | --- | --- | --- |
| writer | `siq-research-draft` | 读取公司资料、写任务输出目录 | 合法写入合成标记 |
| reader | `siq-company-evidence` | 只读 | 实际尝试相同类型写入，确认被拒绝 |

模型实际调用原生 `skill_view`、`read_file`、`write_file`。测试提示要求真实尝试并报告工具结果，不由提示文字决定权限；没有使用合成网关占位或直接调用安全内核代替业务请求。

## 2. 如何证明请求确实重叠

1. 先启动 writer，在其合法读取成功且签名回执对应当前 writer Grant 后，核对受保护启动记录、实际进程、解释器、参数、cgroup 和 pidfd。
2. 仅暂停本任务 Hermes 进程，保持真实 writer 沙箱、业务 API、模型、Authority 与监管者运行；随后从另一线程提交 reader 的真实 HTTP 请求。
3. 在暂停期间采集三次现场观察，跨度约 **1.131 秒**。每次同时确认：两个 HTTP 请求仍在途、两个业务执行行存在、reader 处于 pending、网关 owner 仍为 writer、清单仅有 writer 沙箱、reader 请求运行目录尚未创建、reader 没有安全回执。
4. 恢复同一 pidfd 所指进程，writer 继续完成写入与回答。暂停总计约 **2.202 秒**，不是负载或延迟基准。
5. reader 在正常队列中继续启动，无测试脚本代替它创建沙箱。独立复核确认 reader 首次工具事件晚于 writer 最终化记录的文件时间，两个最终化记录均为 released。

排队期间的数据库和网关观察由业务仓库拥有的验收驱动完成，不在安全产品中引入兄弟仓库数据库访问。公开报告保留观察摘要；离线验签不重新查询已回收的临时数据库。

## 3. 真实结果

| 项目 | writer | reader |
| --- | --- | --- |
| 业务会话、run、原生会话 | 独立 | 与 writer 不同 |
| Skill 加载与读取 | allow | allow |
| 写入尝试 | 实际发起一次 | 实际发起一次 |
| 写入签名裁决 | allow | deny，`grant_scope_violation` |
| 工具返回 | 成功 | 错误 |
| 目标文件／符号链接 | 文件存在，内容与摘要正确 | 均不存在 |
| 业务终态 | completed，最终标记正确 | completed，最终回答标记正确 |
| 监管状态 | inactive/success/退出 0，PID 0 | inactive/success/退出 0，PID 0 |
| 最终化 | released | released |

reader 的 completed 表示回答结束，不能被理解成写入成功。这里有真实签名 deny，与前几批在决定之前拒绝而没有 write 回执的场景分别呈现。

两例的 OpenShell 策略都允许各自任务输出目录，规范化 run/nonce 后相同。策略摘要与启动资产一致，输出目录设备号／inode 与启动记录一致；文件路径与实际工具开始事件匹配。reader 被拒绝来自其只读 Skill 授权约束，不能归因为把整个沙箱输出目录关闭。

前后完整 Agent、reader、writer Grant（含 revision）一致，真实公司源文件未变。每个读写回执只引用自身 Skill 的一层 SEC，任务与原生会话不同，reader 没有继承 writer 的 Grant。

## 4. 候选和独立复核

本批业务候选为 `8851724`，安全二进制 Git 导出为 `32e10d54`，固定原生镜像和实际 Skill 内容保持不变。执行前冻结 **1,874 个业务输入**，单列 **289 个相对 HEAD 的差异**；候选摘要为 `5bbf4e90636c45ed58d801de1481d5bb10a216ecb68390e587bea18efc791521`。

新 Authority 完整链包含 **6 条签名回执、2 份 SEC、3 份 Grant 快照**。writer 与 reader 各贡献 3 条回执；两个请求的独立决定绑定分别选用实际 write allow 和 write deny。

- [并发请求、排队观察及结果](evidence/optimization-20261007/native-concurrent-v872.json)
- [完整 6 条回执链](evidence/optimization-20261007/native-concurrent-v872.receipts.jsonl)
- [2 份独立 SEC](evidence/optimization-20261007/native-concurrent-v872.contexts.json)
- [Agent 与两项 Skill 的签名授权清单](evidence/optimization-20261007/native-concurrent-v872.grant-inventory.json)

```bash
apps/control-api/.venv/bin/python scripts/research/verify_native_business_evidence.py \
  docs/development/evidence/optimization-20261007/native-concurrent-v872.json
```

现场独立观察器复核源码归档、驱动摘要、真实文件、目录身份、策略、队列观察顺序、进程记录和服务终态；公开离线核验通过回执链、SEC 签名／归属及三份授权签名／摘要关联。离线核验不重新观察文件、HTTP 重叠或沙箱状态，也不授予当前执行权限。

核验器新增可选 `grant_inventory`：要求声明与证据配套、Grant 身份唯一、全部 Skill 被实际上下文引用、每个上下文的精确授权摘要对应自身 Grant、所有回执绑定同一 Agent。重复计数、未参与的 Skill、交换权限摘要、失效授权或错 Agent 均拒绝。核验器 59 项定向测试通过（本批新增 9 项），Ruff 检查通过。

## 5. 与同时执行测试的关系

[既有 D2j 原生生命周期测试](optimization-opt08-lifecycle-validation-20261007.md)在同一 Hermes 进程中通过线程屏障，让两个实际任务同时存活并分别使用 reader／writer，提供运行时组件的同时执行隔离证据；它采用合成任务，不等于本轮日常 API 的模型业务验收。

本批补齐真实 API 的并发请求和队列交接，二者范围互补，不能拼接为“日常入口已支持多沙箱同时执行”。若今后扩大网关容量，需要先修改业务所有权、模型访问撤销、资源分配和恢复合同，再单独验收，不能仅删除 owner 检查。

## 6. 清理、证据强度和剩余范围

本批两个请求首次通过。临时 API、数据库、沙箱、网关与模型桥已回收，三个服务配置恢复，原模型未重启。API 依赖前后保持 **11,663 文件、4 链接**，摘要 `ec6da2fd01ce3ea539f3fc333ced90be3a7f6f17a469e54132d49f522979bd34`；这不是全栈最终冻结证明。

只观察一组双请求交错，不宣称并发压力容量、所有调度组合、跨用户／跨公司覆盖或统计显著性。未修改 Go／Hermes 或业务生产逻辑，不重复无关产品全量测试。

后续继续实际内容版本升级、其他资源与工具入口、最终候选矩阵和四臂适用性、正式签名交付及 Windows／macOS 原生验收。OPT-08、OPT-10 保持 implementing，总体 **11/16（68.75%）**。
