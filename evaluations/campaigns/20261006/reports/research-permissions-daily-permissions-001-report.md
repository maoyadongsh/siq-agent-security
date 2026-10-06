# 日常分析助手：真实 Agent 读写授权配对通过

本批经原前端 `15173`、日常 API `18081`、本机 Qwen、Hermes 和 OpenShell
执行。同一 Agent 只读时成功读取、写入被 SIQ 拒绝；批准新写权限后真实文件写入
成功。两次请求均不传 `runtime_target`。测量约 244.7 秒，独立核验 21 项全部
通过，7 条签名记录有效；另有 4 项所属项目读回检查通过。

## 实际效果与身份

| 阶段 | SIQ Grant | 请求运行 | 实际效果 |
|---|---|---|---|
| 只读 | `grt-dfb318eac334-56f5324d`，revision 3 | `qwen-request-e58dd20d52902ec9` | `read_file` allow；`write_file` deny，原因 `grant_scope_violation`；目标文件不存在 |
| 批准写入 | `grt-d-463a21083918e17964739e723b1c0f26063b7d5d2ea279bf23c11caca2cf89f1`，revision 3 | `qwen-request-6eda4bcabb5cb53b` | 读取和写入均 allow；目标文件真实存在，含正确的 20% 合成营收增速 |

两阶段 Agent 均为 `hri-6172e905ed7c28c31a987ce74c426772`。合成公司为
`600000-SyntheticDaily9481f8ae98bb424b`；输入原字节未变。
输出摘要为 `446b532cc3dde71fd88563c4c211d7bcff389174be8ab0631a36a632b4e55d50`。
每次请求使用自己真实 `analysis/runs/<run_id>/permission-result.md` 目录，
不声称两次写的是同一物理文件。SIQ 批准公司专属 runs 范围，OpenShell 再限定当前
run；只读阶段的拒写来自 SIQ，不能把公司的 OS 只读根目录拒绝拿来替代此配对。

## 与此前专属部署的区别

- API 是原日常用户 unit，切换前 PID 为 453532，测量 PID 为 2716725。前端未替换。
- 正常本地登录创建令牌；两个临时账户分别承担操作者审批与 analyst 执行，后者
  尝试自授权确实返回 403。没有伪造 JWT 或覆盖认证依赖。
- 业务使用原项目 PostgreSQL；只有所属 Research CLI 创建带审计的本批账户并读取
  本批业务记录，Security 核验器只消费文件和签名证据。
- SIQ 使用原 `47611` 服务，其二进制摘要为
  `2bcbde4bc46a95b4aa599a94d7ad1aa707f9209823951ddbc438e2dfe5ec7b2e`，未重启该服务。
- 两次运行实际镜像均为
  `sha256:fe5bdcebbc09b2099a3b387a675a4e8d879b8491bdc6246d93fbc8abb51e1f02`；
  不是注入测评控制插件的新镜像。业务租约、运行来源、模型桥请求和终态可关联。
- 两条业务记录均 `succeeded`，API finalizer 均为 `released`。本批业务授权与
  SIQ 权限已撤销，账户 19/20 已禁用、令牌版本递增并验证旧令牌失效。

## 修复、回滚和边界

旧入口确实走 Host，并因模型连接错误失败，见 [daily-entry-001](research-permissions-daily-entry-001-report.md)。
错误分类修复见 [daily-entry-002](research-permissions-daily-entry-002-report.md)。
旧启动器冻结清单已过时；新启动器的保护/回滚模式先在独立端口实启通过，再切换
主端口，见 [launch-001](research-permissions-launch-001-report.md)。测评前确认
没有存活业务租约或占用中的请求 sandbox；没有停止其他用户任务。

本批前冻结 1,646 项 Research 源码并归档，测后全部摘要一致。日常 API 目前保留
保护路由；原路由的回滚模板和原 unit 已备份。现有公司不会自动新增授权，未授权
业务仍须拒绝。生产 IAM、任意 Skill 自动归属、任意本机进程隔离或系统重启后
自动启动均不由本批证明。

本批证明的是 **Agent 实例的文件权限管理**。已安装 Skill 的独立权限证据仍对应
专门 Skill 批次及其明确的任务选择/SEC 同步方式，不将其推广为默认任意 Skill
自动受管控。

原 SIQ 台账还包含其他活动。本批仅导出本 Agent 的记录并逐条独立验签、验证相邻
链链接；不声称导出了完整共享台账前缀。篡改内容和签名的负向校准均拒绝。
核验器为测后按预注册判据实施的独立检查，不伪称它已随测量前源码清单冻结。
本轮仍是项目方可复现测评，未获得独立机构认证。

## 证据入口

- [测前准备协议](../protocols/research-permissions-daily-permissions-001-preparation.json)、[绑定实际 PID 的运行协议](../protocols/research-permissions-daily-permissions-001.json)
- [默认入口切换记录](research-permissions-daily-permissions-001-cutover.json)、[原始测量](research-permissions-daily-permissions-001.json)
- [21 项独立核验](research-permissions-daily-permissions-001-verification.json)、[运行和账户读回](research-permissions-daily-permissions-001-readback.json)
- [签名记录](../data/research-permissions-daily-permissions-001-verified-receipts.json)、[实际输出副本](../data/research-permissions-daily-permissions-001-output.md)、[源码核对](research-permissions-daily-permissions-001-source-check.json)

Research 复现入口：`scripts/openshell/prove_research_daily_permissions.py`；操作步骤见
Research 的 `docs/runbooks/openshell/research-permission-daily-entry.md`。必须新建
批次与协议，不复用本批一次性账户、Grant 或已归档输出路径。
