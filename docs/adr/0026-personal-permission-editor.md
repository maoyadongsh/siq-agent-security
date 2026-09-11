# ADR-026：个人权限编辑与明确替换

- 日期：2026-09-10；状态：已实现，Linux 编辑旅程与原生回归已验证；对应 UX-007、UX-012，延续 ADR-025。跨系统与可信 Skill 运行绑定未完成。

资产详情中的旧补丁表单不预填授权范围，空值表示不修改，并在保存前获取最新 revision，可能覆盖用户编辑期间的外部修改。统一为可重新读取、显示当前范围、明确保存和重新批准的编辑窗口。

新增 `grant-resource-edit/v1`：管理端 `POST /v1/grants/{id}/resources`，仅 pending_approval；必填 actor_id、expected_revision、tools、network、filesystem.read_only/read_write、models。数组允许为空且明确表示清空该允许列表；缺省/null、未知字段、多文档、超过 64 KiB、非法值拒绝。每个列表最多 32 项，不截断输入，网络效应限 allow/deny；路径为明确且规范化的绝对 POSIX 路径，允许空格，不按空格或逗号拆分路径。Windows 路径需要后续原生适配，不能误显示为已支持。

工具名使用有界标识符；网络复用 Grant 执行层的主机/端口规范化。编辑不能改变主体、平台、准入版本、期限、状态或读回证据。保留文件和模型 deny、凭据保护、进程限制及仍被授予工具的人批条件；网络 allow/deny 均为显式编辑范围。工具 deny 始终覆盖 allow 与 require_approval，不能由重建列表放宽。派生允许列表不得将 deny 事实解释为 allow。旧 OpenClaw 授权仅在平台策略中保存的 deny 与 require_approval 也须保留；被保留工具的人批条件同步为签名事实，界面同时展示平台策略中的限制。

通过现有 PatchDesired 与 CommitGrant 签名、精确 CAS 和审计后发布。保存仍为待批准，旧 challenge 随 revision/摘要变化失效；已批准或部署的授权不原地编辑。新合同保持现有 Grant 输出结构，旧 patch-desired API 保持兼容，产品入口统一使用新合同。

界面读取原 Grant 后编辑，保存使用用户看到的 revision，不在保存前偷换为最新值。冲突保留输入并提示主动重新读取。关闭不提交；保存成功回到签发页重新批准。提供“目录改为只读”和“清空允许范围”，均只编辑草稿并明确展示范围。只读/读写文件与网络输入逐行处理，完整资源列表可审阅。

显示主体和来源准入，但明确其不是可信 Skill 运行归属。进程/模型保护能力不由配置写入推定，未知归属不显示为已验证。完整可信 Skill 绑定和跨系统验收仍属于后续 UX-007 门槛。
