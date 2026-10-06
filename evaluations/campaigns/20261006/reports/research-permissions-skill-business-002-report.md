# 分析助手：两个 Skill 的真实读写权限对照

本批通过。证据支持：在本机 DGX Spark 的专属验收部署中，同一 Agent 加载两个经 SIQ 安装和批准的 Skill，实际读写分别受各自 Grant 限制。执行路径为真实分析助手 HTTP API → OpenShell → Hermes → 本地 Qwen → SIQ 原生工具门禁。

| Skill | 授权 | 模型实际调用与效果 |
|---|---|---|
| `research-permissions-reader` | 读取合成公司输入；无文件写权限 | 读取成功；写入被 SIQ 以 `grant_scope_violation` 拒绝；目标文件不存在 |
| `research-permissions-writer` | 读取同一输入；仅公司 `analysis/runs` 子树可写，OpenShell 进一步限制当前请求目录 | 读取成功；写入成功；真实文件包含 2024 年 200、2025 年 240 和 20% 增速 |

两阶段 Agent 相同，Skill、Grant、SEC 不同。每阶段使用新的业务会话和请求目录，输出文件名相同。四条工具决定均带 `verified` Skill 归属并匹配相应 SEC；三条执行观察共同组成七条回执。独立验证器核验哈希链与 Ed25519，并确认篡改回执会被拒绝。原始 Grant、SEC、实际加载的技能摘要、输出文件摘要均完成交叉核验；在同一不可变镜像中再次调用 Hermes 原生加载器，得到与真实业务任务相同的加载内容摘要。

## 证据

- [真实执行与清理结果](research-permissions-skill-business-002.json)
- [工具回执与实际文件独立核验](research-permissions-skill-business-002-verification.json)
- [Skill、Grant、SEC 与原生加载独立核验](research-permissions-skill-business-002-skill-verification.json)
- [实际输出文件副本](../data/research-permissions-skill-business-002-output.md)
- [签名权限和上下文](../data/research-permissions-skill-business-002-skill-authority.json)
- [预注册协议及源码摘要](../protocols/research-permissions-skill-business-002.json)

候选镜像：`sha256:8b1fb4340a19ea3efbf6ce987bd63e5c294f1dd3c0d00b0c23802435ba165aa6`。SIQ 插件及二进制沿用本轮已冻结身份。候选镜像通过原有离线检查后，由验收 API 独立选择；日常镜像指针和既有服务身份未改变。业务终态、沙箱回收、临时数据库删除及自有 Skill/身份清理均通过。

## 接入修正和结论范围

原验收镜像没有技能目录。新镜像增加了两个真实安装文件及测评同步钩子；钩子使用 Hermes 原生加载器读取固定技能，向宿主报告真实 session/task，由宿主控制器经公开 API 签发匹配的 SEC。管理员凭据不进入沙箱。同步钩子协调任务归属，业务操作的允许或拒绝仍由原 SIQ 工具门禁完成。

研究侧运行绑定原本拒绝安装流程的 `grt-si-<64 hex>` 标识，现已补齐格式支持，畸形标识仍拒绝。首批镜像组装还因安装器合法硬链接被通用源码读取器拒绝而失败；原 [skill-business-001](research-permissions-skill-business-001.json) 保留。修正后按稳定文件身份和批准摘要读取，仍拒绝符号链接、内容漂移及非普通文件。后续聚焦回归为 85 项通过，见 [测试日志](research-permissions-skill-integration-tests-003.txt)。源码格式整理和非普通文件读取强化发生于实测之后；精确复现本批使用预注册目录保存的源码和上述镜像身份。

本批证明的是**明确选择并绑定 Skill 的受控真实业务任务**。它不证明日常部署已经自动接入，也不证明能自动识别任意技能切换、同实例并行多个根身份或覆盖所有终端/委派入口。未批准 Skill、内容漂移、撤权后的下一次调用、跨目录及失联保护仍在后续验收范围内。本批是内部可复现实测，不是独立第三方认证；合成营收样本也不评价完整金融分析质量。
