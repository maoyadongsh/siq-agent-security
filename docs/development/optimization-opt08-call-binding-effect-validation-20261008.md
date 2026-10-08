# OPT-08/10：缺失必需调用标识的真实写入拒绝验证

日期：2026-10-08。环境：DGX Spark＋智能分析助手＋Hermes 原生 Skill＋OpenShell＋SIQ Agent Security。

本批确认：**在 Agent 身份、Skill 授权、已加载 SEC 和目标文件权限均有效时，真实写入请求若缺少必需的 `tool_call_id`，Authority 返回 HTTP 409，工具报错且文件不生成。保留该标识的正常对照完成写入。**

这验证了实际请求与可信宿主已登记调用之间的强制绑定，区别于“没有加载 Skill”和上一批“通道失联”。没有把所有未知归属场景概括为已测完。

## 1. 设计依据与控制变量

现有原生链路先由可信宿主登记调用，再以 `tool_call_id`、任务、主体及参数绑定实际决定请求；它不在业务请求中携带一个可直接删除的独立证明令牌。因此，本批精确测试的是**调用请求缺失必需标识**，不是删除 SEC、撤销 Grant 或伪造安装来源。

本批在受保护宿主 relay 与原 Go Authority 之间增加拥有明确生命周期的本地 HTTP 测试代理。代理只有固定 loopback 上游，只转发两个现有端点，不签发授权、不替换裁决响应、不记录认证头。管理 API 和业务身份签发仍使用原 Authority。

两个驱动及代理源文件在执行前登记摘要：

- v863 正常对照：所有请求字节原样转发，正常加载、读取、写入及回答必须完成。
- v864 缺失标识：合法读取完成且签名回执对应当前任务后，仅在该任务唯一一次真实写入 `/v1/decide` 请求中移除 `tool_call_id`。主体、会话、任务、工具、参数和认证头保持，其他请求字节原样转发。

候选仍为业务 `8851724`、安全二进制 Git 导出 `32e10d54`、同一原生镜像和隔离 Authority。每轮冻结 1,874 个业务输入，登记 289 个与 HEAD 不同的输入，摘要均为 `5bbf4e90636c45ed58d801de1481d5bb10a216ecb68390e587bea18efc791521`。新增代理属于显式故障注入，不作为未修改的部署配置冒充最终全栈候选。

## 2. 真实结果

| 项目 | v863：正常对照 | v864：缺少调用标识 |
| --- | --- | --- |
| Skill 加载与读取 | 成功，签名 allow | 成功，签名 allow |
| 唯一写入请求 | 原始／转发字节摘要一致 | 只有 `tool_call_id` 被移除 |
| 实际上游响应 | HTTP 200、allow | HTTP 409、`native_host_unavailable` |
| 真实工具结果 | 写入成功 | 写入报错 |
| 文件观察 | 文件存在，内容及摘要正确 | 文件／符号链接均不存在 |
| 写入回执 | 1 条 allow，与 HTTP 返回 receipt_id 一致 | 0 条，没有制造签名 deny |
| 业务终态 | completed，最终标记正确 | completed，模型完成对工具结果的回答 |
| 预登记检查 | 32 项通过 | 33 项通过 |
| 监管与清理 | inactive/success/退出 0，PID 均为 0 | inactive/success/退出 0，PID 均为 0 |

负向用例的业务 completed 表示回答结束，不表示写入成功。工具错误、文件不存在、HTTP 拒绝与业务会话终态分别呈现。

## 3. 拒绝如何归因

现场独立复核请求前后 JSON：负向转发内容精确等于原请求移除 `tool_call_id` 后的结果，没有额外改动。正常对照写入原始字节与转发字节摘要相同；两例所有非目标请求亦保持字节摘要一致。代理没有内部错误，并记录了实际上游响应；响应不是代理自造的拒绝。

前后完整 Agent／Skill Grant（含状态 revision）相同，SEC 内容不变且未撤销，结果记录生成时尚未到期。实际 OpenShell 策略与启动资产摘要匹配，任务输出目录均在可写范围；仅规范化 run/nonce 后两例策略相同，目录设备号／inode 与启动记录一致。

源码对应路径为 `Server.decide` → `NativeRuntime.bindDecision` → `host.Bind`。原生身份策略要求可信调用，缺少标识不能绑定此前登记的调用；请求在进入决定引擎前返回 409。这与现场无写入回执相符。单独“无回执”不足以证明拒绝，本批另有实际 HTTP 响应、工具错误和文件效果。

结论限定于：**有效身份和 Skill Grant 不能替代每次调用所需的可信绑定。** 本批没有测试所有字段错配、未知加载来源、并发或其他框架旁路。

## 4. 可复核材料与证据强度

新增 5 条回执、2 份 SEC；延续同一 Authority 的完整链为 **21 条回执、7 份 SEC**。本批两请求各绑定实际签名决定：正常例绑定写入 allow；负向例绑定移除标识之前的读取 allow。后者用于证明已成功进入授权链，不能被说成签名写入 deny。

独立观察器核对：冻结源码归档、驱动和代理摘要、请求差异、上游响应、HTTP receipt_id 与签名回执、完整链前缀、SEC 与有效 Grant 签名／摘要、实际文件、策略、目录身份、最终化与服务状态。

- [候选、请求差异摘要与结果](evidence/optimization-20261007/native-call-binding-v863-v864.json)
- [累计 21 条回执链](evidence/optimization-20261007/native-call-binding-v863-v864.receipts.jsonl)
- [7 份签名 SEC](evidence/optimization-20261007/native-call-binding-v863-v864.contexts.json)
- [前批通道失联与恢复](optimization-opt08-native-channel-fault-validation-20261008.md)

```bash
apps/control-api/.venv/bin/python scripts/research/verify_native_business_evidence.py \
  docs/development/evidence/optimization-20261007/native-call-binding-v863-v864.json
```

公开核验通过。HTTP 故障注入及文件观察来自本轮受控现场记录，离线验签不重新观察这些效果，也不使未签名的 HTTP 拒绝成为签名决定。公开记录筛选响应字段和摘要，不包含认证头、凭据或完整私有请求。

本批没有修改产品或核验器，未重复上一批工具单元测试及无关全量检查。每个条件一次真实试点，不宣称三次重复、统计显著性或四臂对照完成。

## 5. 清理与后续

两个临时代理 listener、业务 API、数据库、沙箱、网关与模型桥均已停止／回收，三个服务配置恢复，原模型未重启，业务源码不变。API 依赖前后仍为 11,663 文件、4 链接，摘要 `ec6da2fd01ce3ea539f3fc333ced90be3a7f6f17a469e54132d49f522979bd34`；不等同于全栈冻结。

剩余自然到期、并发、其他错配与资源入口、最终候选矩阵、四臂适用性、正式签名和原生平台验收继续。已请求补充 Windows／macOS 测试机接入信息；未收到接入信息不影响本地剩余开发。

OPT-08、OPT-10 保持 implementing，总体 **11/16（68.75%）**。本批筛选证据和进度本地提交；未完成整体交付前不推送。
