# ADR-042：安装后实例权限准备的可恢复查询

日期：2026-09-11。状态：接受，实施中。承接 [ADR-041](0041-installed-instance-permission-binding.md)。

安装成功、实例权限已准备、宿主接入和运行自检是独立状态。个人安装结果页需要只读查询，以处理刷新和写请求响应丢失；不得通过自动重发 activate 恢复界面。

管理 GET `/v1/skill-installations/operations/{install_id}/runtime` 返回 runtime-readiness/v1：当前完整签名 Grant、状态版本、可选签名安装绑定，以及 not_prepared / incomplete / prepared / no_tools。查询完整复核目标、来源、批准内容、实例与期限。prepared 仅表示绑定存在且当前批准版本等于原批准版本加一，不代表已签发身份、已安装钩子或可信 Skill 运行归属。incomplete 表示绑定已发布但权限版本尚未提交，只能由原绑定操作者显式重试。错误撤下旧状态。

管理 GET `/v1/skill-installations/grants/{grant_id}/runtime` 从已签名绑定解析安装编号，复用同一验证，不接受客户端目标路径。未准备的 Grant 返回不存在，引导从安装结果准备。两个接口只读、不发布文件，复用安装管理权限、no-store、单并发和时间预算。

空工具权限无法形成有效运行会话。权限准备和实例身份发行必须在发布绑定/凭据之前明确拒绝空工具集（计算显式 deny 后的允许及需确认集合）；只读查询可返回 no_tools。不得为通过此检查自动补充工具、扩大权限或修改已批准 Grant。已有空工具绑定也不得用于运行。

个人界面展示完整权限、实例及有效期，用户明确确认实例范围后准备权限，再使用现有实例接入和独立自检入口。入口锁定安装对应实例和 Grant；导入 Grant 不能误走通用 deploy，也不能复用其他 Grant 的旧身份。三系统与平台真实验收仍分别登记。
