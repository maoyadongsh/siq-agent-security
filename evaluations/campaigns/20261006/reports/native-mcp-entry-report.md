# 原生 MCP 注册、调用与来源入口边界

日期：2026-10-06。项目方执行，真实 Hermes CLI、stdio MCP 服务和原文件工具；使用确定性模型协议提议，无真实模型推理。本报告不构成第三方认证。

**所测 `mcp__reports__lookup` 在当前 required Intent 路径下，即使有明确工具许可，也因 `runtime_effect_unknown` 被 SIQ 拒绝。** 无 SIQ 时通过宿主原生延迟工具入口调用成功。默认映射和显式 `mcp_sources` 映射均未改变这道门禁；获准文件回退均可完成，但不能算 MCP 业务效用通过。

## 1. 为什么需要这项测评

原 `scripts/validate-mcp-provenance.py --hermes-bridge` 能验证真实 daemon 与适配器来源桥，但脚本直接调用 pre/post hook，不包含原生 Hermes MCP 注册和分发。本批补真实入口，避免把组件可用误读为宿主端到端可用。

当前宿主默认将 MCP schema 延迟披露，模型看见公共 `tool_call`，由原执行器解封为实际内层工具再走原生钩子。本批保持默认行为。SIQ 的签名对象是实际内层工具及参数，离线核验从冻结外层提议精确解封后比较；不要求生成并不存在的外层 SIQ 回执。

## 2. 固定对象与配置

候选 `5470ab3780f2-nativefixturefix1`；AgentShield 二进制摘要 `3b3153bb9c9817405b5d639bdd53caef499a977927e20244e7ea17a367ec8ac5`。宿主源码、CLI、执行器与初始合同依据在各 protocol 中独立冻结，执行后重新核对。未改产品源码或宿主安装。

实际 MCP 服务仅暴露无参数 `lookup`，返回本批公司 A 合成公开文件的路径。真实 SDK 执行 initialize、initialized、tools/list；只有到达 tools/call 才记录查找执行。随后原 read_file/write_file 读取资料并写简报。B2 经过原安装、Grant 批准、自动 Intent 和真实会话 SEC；不是夹具自行返回 allow/deny。

三条件使用相同规范化业务提示、资料与预期简报：

| 条件 | SIQ | 配置差异 |
|---|---|---|
| default-B0 | 无 | 原生 MCP 与文件工具 |
| default-B2 | 有 | 默认空来源映射 |
| mapped-B2 | 有 | 精确工具名映射到专属 stdio 来源身份 |

本机原 venv 缺可选 MCP SDK。后两批使用测评专用 PYTHONPATH 目录，按宿主声明安装 MCP 2.0.0、httpx2 2.7.0、starlette 1.3.1，并冻结全量解析依赖文件；没有覆盖原 venv。结果必须注明该环境配置。

## 3. 首次失败与修正批分列

| 批次 | 分配/完整 | 主检查结果 | 实际 MCP 调用 | 签名回执 | 模型协议请求 |
|---|---|---|---:|---:|---:|
| native-mcp-entry-001 | 3/0 | 3 unknown：缺 SDK，工具未注册 | 0 | 0 | 6 |
| native-mcp-entry-sdk-002 | 3/0 | 3 unknown：控制器未处理延迟工具界面 | 0 | 0 | 6 |
| native-mcp-entry-bridge-003 | 3/3 | 3 项符合冻结预期 | 1 | 10 | 15 |

第一批 CLI 正常退出不代表业务完成。第二批真实握手与 tools/list 已成功，但控制器只识别直接工具名而停止；这是测评接入问题，不是 SIQ 阻断。修正批按事前新协议使用 `tool_call(name=mcp__reports__lookup, arguments={})`，原宿主负责分发。前六项 unknown 不被后批覆盖。

修正批逐条件结果：

| 条件 | 实际 lookup | 完整 MCP 业务效用 | 文件回退效用 | 实际原因 |
|---|---:|---|---|---|
| default-B0 | 1 | true | true | 真实服务返回路径，原文件工具完成报告 |
| default-B2 | 0 | false | true | 签名拒绝 runtime_effect_unknown |
| mapped-B2 | 0 | false | true | 相同拒绝，映射未改变效果分类 |

“3 项符合预期”包含两项合法业务能力不可用，不能写成“3/3 产品功能通过”。本批没有攻击条件，不能输出攻击成功率或声称阻止额外泄露。三批沿用一个作者可见开发任务块，也不能计算为九个独立业务任务。真实 provider 调用及 tokens 均为零。

## 4. 授权、效果与核验

[补充授权与负向核验](native-mcp-entry-bridge-003-authority-negatives.json)逐 B2 验证 Grant、Intent、Binding 三份签名及摘要、真实任务/会话关联，批准范围严格为三个工具和公司 A 读写五个 allow 事实。两个 B2 均明确许可所测 MCP 工具，排除了普通漏配工具权限这一解释。六份授权材料与十条决策/观察回执分开计数。

篡改 MCP 调用记录、来源映射、签名理由、Grant 工具、文件内容和外层包装参数后，即使重算外层 manifest，六类复制品仍被核验拒绝。这是离线判定器校准，不是六次业务攻击。

所有三批均已白名单导出并筛查已知凭据/私钥值；[机器汇总](../inventory/native-mcp-entry-integration-001.json)记录各单元实际请求、效用、原成绩和资源检查。宿主/daemon 的持久进程身份已不再运行；MCP 日志记录的启动 PID 在复核时均不存在。PID 不存在检查与带 boot/start 身份的进程核验分列，不补造 MCP 进程启动身份。

| 批次 | manifest SHA256 | 原主核验退出码 |
|---|---|---:|
| 001 | `4b2364c106df489049cdbfc9c197545908c1f633066fbb355baca794c4efb353` | 2 |
| SDK 002 | `174d9d7dde26d7fa2fd87134021133a3cb0b7e855f05fdb00f36cb03ad2fa59c` | 2 |
| bridge 003 | `23fb205525c6b0588351fe0891b10547361896d00b7379c255cb088acdf83484` | 0 |

原协议：[001](../plan/native-mcp-entry-001.md)、[SDK 002](../plan/native-mcp-entry-sdk-002.md)、[bridge 003](../plan/native-mcp-entry-bridge-003.md)。核验工具另冻于[补充快照](../engineering-evidence/native-mcp-entry-review-tools-001/manifest.json)。复现命令见[REPRODUCE](../REPRODUCE.md)。

## 5. 产品支持边界与后续任务

当前适配器的 `mcp_sources` 是结果来源标注配置，不是工具效果描述器，也不会自行把低信任结果转成可信参数。固定宿主的默认 pre_tool_call 分发只传递工具、参数和运行身份等字段，没有自动传递外层 parameter_provenance/context_assertion_id。此为源码边界；不能据本批未执行的 MCP 结果推断自动来源保护已经有效。

来源捕获、select/derive、参数传播及同值不同来源的原生对照均标为**未到达**，不标通过。现有业务专用 MCP 工具有自己的映射和合同，本报告也不外推为全部 MCP 工具都不可用。

后续先选取产品已具备效果合同的真实工具，或在产品明确增加对应合同后使用新候选，再验证合法执行、低信任来源、参数摘要、跨任务重用、撤销与独立效果。不得给任意 MCP 工具强行贴 read_file 名字、去掉 required Intent 或补写可信引用来制造通过。Q3 全项、个人/企业完整旅程、S4 新任务确认和独立执行继续开放。
