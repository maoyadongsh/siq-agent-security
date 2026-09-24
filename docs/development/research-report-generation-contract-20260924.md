# 请求范围内的固定报告生成合同

本增量关闭真实报告通过 terminal 被拒绝的工程缺口；不改变通用 shell 的 unknown 判定。调用事实源为 `packages/contracts/siq-research-report-generation-call.v1.schema.json`；既有发布工具 v1 不变。

`mcp__siq_business__research_generate_report` 仅接受 company_path、run_id、year。公司路径必须是规范的绝对项目路径下 `data/wiki/companies/六位代码-名称`，run_id 为 `qwen-request-` 加 16 位十六进制，年度 2000–2200。禁止任意命令、脚本、输出路径、URL、SQL、正文或额外参数。

描述器明确列出固定副作用：文件读取、文件写入、进程执行，以及可选的受控数据库只读查询/网络请求（按保守上界授权）。读取公司根和同项目 `data/wiki/_meta`，仅写该公司 `analysis/runs/<run_id>`；网络仅 `host.openshell.internal:18794`。按路径区分读与写，不要求对公司原资料授予写权限。意图约束仍检查全部资源，Grant 仍逐次复验，任一缺失拒绝。工具名/形状本身不是执行实现身份或权限证明。

执行器必须位于已校验候选镜像的不可写代码中。调用时将 company_path 与自己的项目根精确比较，运行命名空间的 scope hash 必须等于 `sha256("cn\0" + company_id)[:24]`，run_id 必须相同，拒绝符号链接与非私有运行目录。公司年度资料必须 ready。只启动固定 Python 流水线，参数只含公司、年度，不执行 shell；子环境只传固定路径、请求身份及受限 broker 凭据引用，不继承宿主数据库密钥或模型 Provider。

OpenShell 必须实际只读挂载该公司和公共市场元数据、只写挂载本次运行目录。不能仅靠环境变量声称隔离成立。数据 broker 继续依据本次业务授权检查查询；网络地址不可由模型选择。180 秒执行预算及 1 MiB 输出预算，超限终止本次进程组；每次运行只允许一次生成尝试，失败不自动覆盖重放。生成结果不是审批，后端独立校验完整八项材料与原运行来源，独立复核员才能批准发布。

上线须同时具备新版描述器、受限执行器、MCP 清单、固定镜像与真实模型到审核 API 的正负向验收。任一缺失维持原拒绝，不降级到 terminal 或 warn。冻结发行候选与既有服务不自动升级。
