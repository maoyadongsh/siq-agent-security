# 剩余验收的现场条件（2026-09-24）

客户端准备构建及 DGX Spark 原生启动检查已完成；研究 API/Web 和企业 API/Web 已部署。此处只记录当前未满足的外部条件，不将复查状态或重复已有测试记作开发进度。当前没有正在等待完成的 Nemotron 测试或远端原生 CI 作业。

| 项目 | 本次直接观察 | 接续条件 |
| --- | --- | --- |
| 固定 Nemotron | `127.0.0.1:8006/v1/models` 连接失败；bridge unit 存活不等于上游模型在线 | 固定候选模型在可用资源窗口恢复后再做规定验收；不覆盖模型锁、不用 Qwen 冒充 |
| 主机资源 | 121 GiB 内存约 109 GiB 已用、约 12 GiB available；15 GiB swap 几乎用满；GB10 不提供常规独立显存读数 | 不在当前负载下盲目启动大模型；需要确认可用资源窗口及允许暂停的在用服务，或另行提供符合原合同的执行环境 |
| 既有模型 | Qwen 主服务在运行，8005 匿名模型列表为 401；另有 embedding/reranker 服务 | 401 仅说明匿名被拒，不代表认证推理故障；未停止这些用户服务 |
| 原生 CI | GitHub runners 查询成功，`total_count=0`；指定原生工作流 API 返回 404 | 发布已审阅的工作流并提供受控 runner，之后才能取得真实 CI 记录；本批未创建注册令牌、注册 runner 或推送 |
| 客户端原发行签名 | 当前进程无原发行 seed；仓库级 secret 名称中无 RELEASE/SIGN/PUBLISH 项；环境列表只有 github-pages | 用户所选的受控签发环境仍需实际入口或密钥引用；不能由这些查询推断其他位置一定没有密钥 |
| 正式源码身份 | 已验证的 11 文件补丁及发行工具改动尚未纳入新的客户端候选提交 | 已单独请求允许创建本地候选提交；不包含推送、合并或发布 |
| 报告权限与真实身份 | 原具体权限变更单决定仍未返回；没有已提供的真实业务测试账号和可供企业用户访问的研究业务 origin | 原请求继续有效；真实账号/组织、报告执行确认、独立复核和跨站联调仍待完成 |

已有 `release-signing.yml` 是研究压缩包校验和的 Sigstore/OIDC 签名及 Release 上传工作流，不是客户端 Ed25519 Skill 签发流程；不能触发该工作流来替代原客户端信任根。本次未调用它。

本地候选提交需要单独明确指令，来自 工作区 AGENTS.md（本机路径：`/home/maoyd/siq/AGENTS.md`）：“Do not create commits, tags, branches, pull requests, or pushes unless the user asks.” 已准备的补丁、源码清单、拒绝旧提交检查及签发命令见 [客户端发行交接](client-report-release-handoff-20260924.md)。此次请求是为了形成新源码身份，不是重复索取原发行密钥。

后续只在条件变化或必要信息到达时执行相应验收。没有继续构建或重跑同一套已通过测试来制造进度，不将总目标标记完成。外部审查和独立 Flow worker 故障继续分开记账，不扩大本轮收尾范围。

本次只读检查的[脱敏记录](../evidence/flagship-optimization-20260921/remaining-environment-gates-20260924.json)由同批 candidate 引用。部署当前事实分别见[研究主服务](main-api-cutover-20260924.md)和[企业控制台](enterprise-runtime-delivery-20260924.md)。
