# Windows Authority 接通增量

继承 windows-resource-profile-spec-v1.md 和 N01 的显式状态升级协议。本增量接通既有 grant/v2、identity/v2、intent/v4 和 binding/v2；旧记录不迁移语义、不重签。

人工选择、路径原文保留及新版身份确认见 [Windows 路径授权界面增量](windows-authority-ui-v1.md)。

新版本签名记录与确认请求使用精确字段名，拒绝重复字段、大小写别名和空确认；资源编辑 v2 的 filesystem 输入为明确的本地盘符绝对路径，不沿用 v1 的 POSIX 前缀规则。文件副作用观察见 [Windows 文件观察增量](windows-file-observation-spec-v2.md)。

Runtime Identity v2 创建只接受 create/v2 及 confirm_filesystem_profile=true。服务从自身盘点恢复实例的产品与 profile 根目录，以 runtimepath 现场核验该根是受支持的真实 Windows 本地目录，再将已验签且已批准 Grant 的解释绑定给该实例。此检查不宣称宿主已加载钩子或具备 Windows 原生执行能力；它也不把平台名称、GOOS 或请求中的路径当作选择解释的依据。v1 创建不能绑定新版 Grant。凭据和记录发布前必须已完成状态消费者屏障，实例和资源身份再次核验。

会话包络由身份签发：v1 仍为 intent/v2；v2 为 intent/v4，authority_kind=instance_permission，profile 与 Grant 一致。普通 Intent 创建 HTTP 拒绝 v4，不能自报内部 issuer。签发、绑定和实时解析均校验版本、profile、权限摘要域和状态屏障，跨解释绑定拒绝。新 Windows 包络即使资源约束为空也拒绝描述器资源错误，实际范围由所选 Grant 单独限制。

资源编辑新增 grant-resource-edit/v2，沿原资源编辑字段，必需 confirm_filesystem_profile=true。仅对旧 pending managed Grant 显式生成新待批准修订；新版草稿后续编辑也须该确认。持久化由 N01 门禁保护，审批仍是后续独立操作，编辑不能直接授权。

Identity 列表在包含新版 identity 时返回 local-runtime-identities/v2，条目可为旧摘要或带明确 profile 的新摘要；无新版条目的旧响应保持 v1。issued/v2 沿已有合同返回新摘要。适配器不获得私钥，凭据不进入响应体。

最终裁决仅从已验证 Intent 选择资源解释，并检查所选 Grant 完全一致。Windows 权限的文件边界、目标和已有父目录必须通过原生事实核验；批准目录被替换后不得重绑定。审批状态、执行预留与修改参数后的再次决策沿同一解释，未知或不匹配 Authority 在任何 enforcement 模式均拒绝。此 hook 级检查不是 OS 沙箱，不能消除核验到宿主执行之间的同 UID 竞争。
